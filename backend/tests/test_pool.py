from __future__ import annotations

from pathlib import Path

import pytest

from carrier_pool.geo import GeoIndex
from carrier_pool.ingest import BROKER_BROKEROS, BROKER_FREIGHTFLOW, BROKER_HAULDESK, ingest_data
from carrier_pool.models import Equipment
from carrier_pool.pool import POOL_FIELDS, pool_contributions, pool_rankings, recommend, recursive_payload_keys
from carrier_pool.ranking import active_loads

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


@pytest.fixture(scope="module")
def store():
    return ingest_data(DATA_DIR)


@pytest.fixture(scope="module")
def geo():
    return GeoIndex.bundled()


def _active_by_lane(store, broker_id: str, pickup_city: str, delivery_city: str, equipment: Equipment):
    matches = [
        load
        for load in active_loads(store, broker_id)
        if load.pickup.city == pickup_city
        and load.delivery.city == delivery_city
        and load.equipment == equipment
    ]
    assert len(matches) == 1
    return matches[0]


def test_pool_toggle_does_not_change_broker_local_answer(store, geo):
    load = _active_by_lane(store, BROKER_FREIGHTFLOW, "Arlington", "Sugar Land", Equipment.DRY_VAN)
    without_pool = recommend(store, load, geo, opt_in_brokers={BROKER_FREIGHTFLOW, BROKER_HAULDESK}, include_pool=False)
    with_pool = recommend(store, load, geo, opt_in_brokers={BROKER_FREIGHTFLOW, BROKER_HAULDESK}, include_pool=True)
    assert with_pool.price == without_pool.price
    assert [(r.carrier_id, r.score, r.confidence) for r in with_pool.own_carriers] == [
        (r.carrier_id, r.score, r.confidence) for r in without_pool.own_carriers
    ]
    assert with_pool.pool_carriers


def test_pool_contribution_payload_is_exact_allowlist(store):
    as_of = max(version.synced_at for version in store.versions)
    contributions = pool_contributions(store, BROKER_FREIGHTFLOW, as_of) + pool_contributions(store, BROKER_HAULDESK, as_of)
    assert contributions
    for contribution in contributions:
        assert set(contribution.payload) == POOL_FIELDS
        assert recursive_payload_keys(contribution.payload) == POOL_FIELDS


def test_overlapping_delta_prime_never_enters_pool_tier(store, geo):
    ff_load = _active_by_lane(store, BROKER_FREIGHTFLOW, "Grand Prairie", "Katy", Equipment.DRY_VAN)
    hd_load = _active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    opt_ins = {BROKER_FREIGHTFLOW, BROKER_HAULDESK}
    assert all("DELTA PRIME" not in ranking.carrier_name.upper() for ranking in pool_rankings(store, ff_load, geo, ff_load.synced_at, opt_ins))
    assert all("DELTA PRIME" not in ranking.carrier_name.upper() for ranking in pool_rankings(store, hd_load, geo, hd_load.synced_at, opt_ins))


def test_opted_out_and_brokeros_brokers_do_not_exchange_pool_data(store, geo):
    ff_load = _active_by_lane(store, BROKER_FREIGHTFLOW, "Arlington", "Sugar Land", Equipment.DRY_VAN)
    hd_load = _active_by_lane(store, BROKER_HAULDESK, "Plano", "New Braunfels", Equipment.DRY_VAN)
    bo_load = _active_by_lane(store, BROKER_BROKEROS, "Conroe", "Cibolo", Equipment.REEFER)
    assert pool_rankings(store, ff_load, geo, ff_load.synced_at, {BROKER_FREIGHTFLOW}) == []
    assert pool_rankings(store, hd_load, geo, hd_load.synced_at, {BROKER_FREIGHTFLOW}) == []
    assert pool_rankings(store, bo_load, geo, bo_load.synced_at, {BROKER_BROKEROS, BROKER_FREIGHTFLOW, BROKER_HAULDESK}) == []
