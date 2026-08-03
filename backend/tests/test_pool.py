from __future__ import annotations

from pathlib import Path

import pytest

from carrier_pool.geo import GeoIndex
from carrier_pool.ingest import BROKER_BROKEROS, BROKER_FREIGHTFLOW, BROKER_HAULDESK, ingest_data
from carrier_pool.models import Equipment
from carrier_pool.pool import POOL_FIELDS, pooled_facts, pool_contributions, pool_rankings, recommend, recursive_payload_keys
from carrier_pool.ranking import WEIGHTS, active_loads

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


def _component(ranking, name: str):
    return next(component for component in ranking.components if component.name == name)


def _delta_prime(rankings):
    return next(ranking for ranking in rankings if "DELTA PRIME" in ranking.carrier_name.upper())


def test_pool_toggle_preserves_price_and_broker_owned_components(store, geo):
    load = _active_by_lane(store, BROKER_FREIGHTFLOW, "Grand Prairie", "Katy", Equipment.DRY_VAN)
    without_pool = recommend(store, load, geo, opt_in_brokers={BROKER_FREIGHTFLOW, BROKER_HAULDESK}, include_pool=False)
    with_pool = recommend(store, load, geo, opt_in_brokers={BROKER_FREIGHTFLOW, BROKER_HAULDESK}, include_pool=True)
    assert with_pool.price == without_pool.price

    before = _delta_prime(without_pool.own_carriers)
    after = _delta_prime(with_pool.own_carriers)
    assert after.pooled
    for name in ("price", "customer_affinity", "relationship"):
        assert _component(after, name).score == _component(before, name).score

    assert _component(after, "lane_familiarity").score == _component(before, "lane_familiarity").score
    assert _component(after, "lane_familiarity").evidence["pooled_lane_cells"]
    assert with_pool.pool_carriers


def test_pool_contribution_payload_is_exact_allowlist(store):
    as_of = max(version.synced_at for version in store.versions)
    contributions = pool_contributions(store, BROKER_FREIGHTFLOW, as_of) + pool_contributions(store, BROKER_HAULDESK, as_of)
    assert contributions
    for contribution in contributions:
        assert set(contribution.payload) == POOL_FIELDS
        assert recursive_payload_keys(contribution.payload) == POOL_FIELDS


def test_overlapping_delta_prime_is_enriched_not_listed_as_stranger(store, geo):
    ff_load = _active_by_lane(store, BROKER_FREIGHTFLOW, "Grand Prairie", "Katy", Equipment.DRY_VAN)
    hd_load = _active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    opt_ins = {BROKER_FREIGHTFLOW, BROKER_HAULDESK}

    assert all("DELTA PRIME" not in ranking.carrier_name.upper() for ranking in pool_rankings(store, ff_load, geo, ff_load.synced_at, opt_ins))
    assert all("DELTA PRIME" not in ranking.carrier_name.upper() for ranking in pool_rankings(store, hd_load, geo, hd_load.synced_at, opt_ins))

    ff_without = _delta_prime(recommend(store, ff_load, geo, opt_in_brokers=opt_ins, include_pool=False).own_carriers)
    ff_with = _delta_prime(recommend(store, ff_load, geo, opt_in_brokers=opt_ins, include_pool=True).own_carriers)
    assert _component(ff_with, "reliability").score > _component(ff_without, "reliability").score
    assert _component(ff_with, "reliability").evidence["pooled_observations"] > 0
    assert _component(ff_with, "positioning").evidence["position_pooled_observations"] > 0

    hd_without = _delta_prime(recommend(store, hd_load, geo, opt_in_brokers=opt_ins, include_pool=False).own_carriers)
    hd_with = _delta_prime(recommend(store, hd_load, geo, opt_in_brokers=opt_ins, include_pool=True).own_carriers)
    assert _component(hd_with, "positioning").score > _component(hd_without, "positioning").score
    assert _component(hd_with, "positioning").evidence["position_pooled_observations"] > 0


def test_pooled_payload_never_contains_broker_owned_identifiers(store):
    as_of = max(version.synced_at for version in store.versions)
    contributions = pool_contributions(store, BROKER_FREIGHTFLOW, as_of) + pool_contributions(store, BROKER_HAULDESK, as_of)
    forbidden_keys = {"customer", "customer_id", "load_id", "source_file", "carrier_rate_usd", "customer_rate_usd", "raw"}
    for contribution in contributions:
        assert not (recursive_payload_keys(contribution.payload) & forbidden_keys)
        payload_text = repr(contribution.payload)
        assert all(load.raw_load_id not in payload_text for load in store.versions)
        assert all(load.customer_name not in payload_text for load in store.versions)


def test_pool_carrier_reasons_describe_bucketed_history(store, geo):
    load = _active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    rankings = pool_rankings(store, load, geo, load.synced_at, {BROKER_FREIGHTFLOW, BROKER_HAULDESK})
    assert rankings
    first = rankings[0]
    assert "pooled" in first.reasons[0]
    assert "ZIP3" in first.reasons[0]
    assert any("appointment record" in reason for reason in first.reasons)
    assert any("raw trips stay private" in limitation for limitation in first.limitations)


def test_pool_only_carriers_use_same_component_model_with_local_missing_priors(store, geo):
    load = _active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    rankings = pool_rankings(store, load, geo, load.synced_at, {BROKER_FREIGHTFLOW, BROKER_HAULDESK})
    assert rankings
    ranking = rankings[0]
    assert [component.name for component in ranking.components] == list(WEIGHTS)
    assert {component.name: component.weight for component in ranking.components} == WEIGHTS

    price = _component(ranking, "price")
    assert price.score == 0.5
    assert price.evidence["basis"] == "broker_market_fallback"
    assert price.evidence["price_effective_loads"] == 0

    relationship = _component(ranking, "relationship")
    assert relationship.score == 0
    assert relationship.evidence["basis"] == "no_local_relationship"

    customer = _component(ranking, "customer_affinity")
    assert customer.score == pytest.approx(1 / 6, abs=0.0001)
    assert customer.evidence["basis"] == "cold_start_prior"

    assert _component(ranking, "positioning").evidence["position_pooled_observations"] > 0
    assert _component(ranking, "reliability").evidence["pooled_observations"] >= 0


def test_opted_out_and_brokeros_brokers_do_not_exchange_pool_data(store, geo):
    ff_load = _active_by_lane(store, BROKER_FREIGHTFLOW, "Arlington", "Sugar Land", Equipment.DRY_VAN)
    hd_load = _active_by_lane(store, BROKER_HAULDESK, "Plano", "New Braunfels", Equipment.DRY_VAN)
    bo_load = _active_by_lane(store, BROKER_BROKEROS, "Conroe", "Cibolo", Equipment.REEFER)
    assert pool_rankings(store, ff_load, geo, ff_load.synced_at, {BROKER_FREIGHTFLOW}) == []
    assert pool_rankings(store, hd_load, geo, hd_load.synced_at, {BROKER_FREIGHTFLOW}) == []
    assert pool_rankings(store, bo_load, geo, bo_load.synced_at, {BROKER_BROKEROS, BROKER_FREIGHTFLOW, BROKER_HAULDESK}) == []
    assert pooled_facts(store, BROKER_HAULDESK, {BROKER_FREIGHTFLOW}, hd_load.synced_at) == {}
