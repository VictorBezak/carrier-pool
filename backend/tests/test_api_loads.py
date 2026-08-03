from __future__ import annotations

import pytest

from carrier_pool.api import app as api
from carrier_pool.ingest import BROKER_BROKEROS, BROKER_FREIGHTFLOW

# FreightFlow load reassigned from one carrier to another mid-lifecycle, then rate-corrected.
REASSIGNED_LOAD = "127738346"
ACTIVE_LOAD = "127233279"


@pytest.fixture(autouse=True)
def file_mode(monkeypatch):
    monkeypatch.setenv("CARRIER_POOL_FILE_MODE", "1")
    monkeypatch.setattr(api.app.state, "store_cache", None)
    yield
    api.app.state.store_cache = None


def test_booked_carrier_is_named_not_just_rated():
    detail = api.get_load_detail(BROKER_FREIGHTFLOW, REASSIGNED_LOAD, as_of=None)
    assert detail["status"] == "completed"
    assert detail["carrier"] == {"id": "918323", "name": "CEDAR HILL FREIGHT"}


def test_a_load_awaiting_coverage_has_no_carrier():
    detail = api.get_load_detail(BROKER_FREIGHTFLOW, ACTIVE_LOAD, as_of=None)
    assert detail["status"] == "active"
    assert detail["carrier"] is None


def test_opaque_crm_carrier_ids_resolve_to_names():
    """BrokerOS carrier IDs are 18-char CRM keys, so the ID alone tells a broker nothing."""
    booked = [load for load in api.get_loads(BROKER_BROKEROS, as_of=None) if load["carrier"]]
    assert booked
    for load in booked:
        assert load["carrier"]["name"] != load["carrier"]["id"]


def test_version_trail_exposes_the_carrier_reassignment():
    """The fall-through the stability component penalizes has to be visible to a broker.

    Before this, the trail carried the buy rate but never the carrier, so a load moving
    from one carrier to another was indistinguishable from one that never changed hands.
    """
    versions = api.get_load_detail(BROKER_FREIGHTFLOW, REASSIGNED_LOAD, as_of=None)["versions"]
    booked = []
    for version in versions:
        name = version["carrier"]["name"] if version["carrier"] else None
        if name and (not booked or booked[-1] != name):
            booked.append(name)
    assert booked == ["BLUE ROUTE CARRIERS", "CEDAR HILL FREIGHT"]
