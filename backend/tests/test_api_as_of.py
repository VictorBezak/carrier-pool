from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from carrier_pool.api import app as api
from carrier_pool.ingest import BROKER_FREIGHTFLOW, ingest_data

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


@pytest.fixture(autouse=True)
def file_mode(monkeypatch):
    """The as-of projection is a store concern, so these run against the file store."""
    monkeypatch.setenv("CARRIER_POOL_FILE_MODE", "1")
    monkeypatch.setattr(api.app.state, "store_cache", None)
    yield
    api.app.state.store_cache = None


@pytest.fixture(scope="module")
def sync_times():
    store = ingest_data(DATA_DIR)
    return sorted({version.synced_at for version in store.versions if version.broker_id == BROKER_FREIGHTFLOW})


def test_load_board_replays_the_book_as_it_stood(sync_times):
    live = api.get_loads(BROKER_FREIGHTFLOW, as_of=None)
    midpoint = sync_times[len(sync_times) // 2]
    replayed = api.get_loads(BROKER_FREIGHTFLOW, as_of=midpoint.isoformat())

    assert len(replayed) < len(live)
    assert all(datetime.fromisoformat(load["synced_at"]) <= midpoint for load in replayed)

    # The bug this guards: the board served live rows regardless of as_of, so no count on
    # the page ever moved. A load delivered by now was still in flight at the midpoint.
    live_status = {load["load_id"]: load["status"] for load in live}
    replayed_status = {load["load_id"]: load["status"] for load in replayed}
    assert any(replayed_status[load_id] != live_status[load_id] for load_id in replayed_status)


def test_every_replayed_row_has_a_recommendation_at_the_same_as_of(sync_times):
    """Board rows and recommendations must agree, or the page renders 'unavailable' cells."""
    seen_active = 0
    for cutoff in sync_times:
        as_of = cutoff.isoformat()
        for load in api.get_loads(BROKER_FREIGHTFLOW, as_of=as_of):
            if load["status"] != "active":
                continue
            seen_active += 1
            bundle = api.get_recommendation(BROKER_FREIGHTFLOW, load["load_id"], as_of=as_of, pool=False)
            assert bundle["price"]["point_usd"] > 0
    assert seen_active > 0


def test_load_detail_truncates_status_and_history_to_the_cutoff(sync_times):
    live = api.get_load_detail(BROKER_FREIGHTFLOW, "127356583", as_of=None)
    assert live["status"] == "completed"

    early = api.get_load_detail(BROKER_FREIGHTFLOW, "127356583", as_of=sync_times[1].isoformat())
    assert early["status"] == "active"
    assert early["carrier_rate_usd"] is None
    assert len(early["versions"]) < len(live["versions"])
    assert all(datetime.fromisoformat(version["synced_at"]) <= sync_times[1] for version in early["versions"])


def test_a_load_that_did_not_exist_yet_is_absent_rather_than_stale(sync_times):
    from fastapi import HTTPException

    first = sync_times[0].isoformat()
    assert all(load["load_id"] != "127233279" for load in api.get_loads(BROKER_FREIGHTFLOW, as_of=first))
    with pytest.raises(HTTPException) as excinfo:
        api.get_load_detail(BROKER_FREIGHTFLOW, "127233279", as_of=first)
    assert excinfo.value.status_code == 404
