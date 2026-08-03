from __future__ import annotations

import pytest

from carrier_pool.api import app as api
from carrier_pool.ingest import BROKER_FREIGHTFLOW, BROKER_HAULDESK


@pytest.fixture(autouse=True)
def file_mode(monkeypatch):
    monkeypatch.setenv("CARRIER_POOL_FILE_MODE", "1")
    monkeypatch.setattr(api.app.state, "store_cache", None)
    api.app.state.file_pool_opt_ins = set()
    yield
    api.app.state.store_cache = None
    api.app.state.file_pool_opt_ins = set()


def test_pool_api_does_not_expose_contributor_broker_identity():
    api.put_pool_opt_in(BROKER_FREIGHTFLOW, api.PoolOptInPayload(enabled=True))
    api.put_pool_opt_in(BROKER_HAULDESK, api.PoolOptInPayload(enabled=True))

    target = next(
        load
        for load in api.get_loads(BROKER_HAULDESK, as_of=None)
        if load["status"] == "active" and load["pickup"]["city"] == "Seguin" and load["delivery"]["city"] == "Baytown"
    )
    recommendation = api.get_recommendation(BROKER_HAULDESK, target["load_id"], as_of=None, pool=True)

    assert recommendation["pool_carriers"]
    for carrier in recommendation["pool_carriers"]:
        assert "contributor_broker_id" not in carrier
        assert "contributor_broker_name" not in carrier
        serialized = repr(carrier)
        assert BROKER_FREIGHTFLOW not in serialized
        assert BROKER_HAULDESK not in serialized
        assert "FreightFlow Brokerage" not in serialized
        assert "HaulDesk Logistics" not in serialized
