from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from carrier_pool.geo import GeoIndex
from carrier_pool.ingest import BROKER_BROKEROS, BROKER_FREIGHTFLOW, BROKER_HAULDESK, ingest_data
from carrier_pool.models import Equipment, LoadStatus
from carrier_pool.pricing import estimate_price
from carrier_pool.ranking import _broker_history, _correction_counts, _fallthrough_counts, _reliability_score, active_loads, lane_weight, rank_carriers

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


@pytest.fixture(scope="module")
def store():
    return ingest_data(DATA_DIR)


@pytest.fixture(scope="module")
def geo():
    return GeoIndex.bundled()


def active_by_lane(store, broker_id: str, pickup_city: str, delivery_city: str, equipment: Equipment):
    matches = [
        load
        for load in active_loads(store, broker_id)
        if load.pickup.city == pickup_city
        and load.delivery.city == delivery_city
        and load.equipment == equipment
    ]
    assert len(matches) == 1
    return matches[0]


def names(rankings):
    return [ranking.carrier_name for ranking in rankings]


def component(ranking, name):
    return next(item for item in ranking.components if item.name == name)


def copy_data_through(tmp_path: Path, broker_id: str, through_name: str) -> Path:
    target = tmp_path / "data"
    broker_dir = DATA_DIR / broker_id
    copied_dir = target / broker_id
    copied_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(broker_dir.glob("*_sync.json")):
        if path.name <= through_name:
            shutil.copy2(path, copied_dir / path.name)
    return target


def copy_broker_only(tmp_path: Path, broker_id: str) -> Path:
    target = tmp_path / broker_id / "data"
    copied_dir = target / broker_id
    copied_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted((DATA_DIR / broker_id).glob("*_sync.json")):
        shutil.copy2(path, copied_dir / path.name)
    return target


def test_ingests_all_generated_loads(store):
    assert len(store.current_loads) == 69
    assert len(store.versions) > len(store.current_loads)
    assert len(active_loads(store)) == 8


def test_zcta_reference_covers_every_generated_zip(geo):
    zips = set()
    for path in DATA_DIR.glob("tms_*/*_sync.json"):
        payload = json.loads(path.read_text())
        if "loads" in payload:
            for row in payload["loads"]:
                for key in ("zipCode", "pu_zip", "del_zip"):
                    if key in row:
                        zips.add(row[key])
                for stop in row.get("stops", []):
                    zips.add(stop["zipCode"])
        else:
            refs = payload["referenced_records"]
            for ref in refs.values():
                if ref.get("type") == "Location":
                    zips.add(ref["bos__Postal_Code__c"])
    assert zips <= set(geo.centroids)


def test_near_miss_lane_ranks_freightflow_veteran_first(store):
    load = active_by_lane(store, BROKER_FREIGHTFLOW, "Arlington", "Sugar Land", Equipment.DRY_VAN)
    rankings = rank_carriers(store, load)
    assert rankings[0].carrier_name == "IBRAHIM TRANSPORT INC"
    assert rankings[0].confidence == "high"
    assert component(rankings[0], "lane_familiarity").evidence["effective_loads"] >= 5


def test_rich_lane_price_estimate_has_high_confidence(store, geo):
    load = active_by_lane(store, BROKER_FREIGHTFLOW, "Arlington", "Sugar Land", Equipment.DRY_VAN)
    estimate = estimate_price(store, load, geo)
    assert estimate.basis == "similar_lane"
    assert estimate.confidence == "high"
    assert estimate.effective_loads >= 5
    assert estimate.low_usd < estimate.point_usd < estimate.high_usd


def test_cross_broker_twin_does_not_leak_hauldesk_history(store):
    load = active_by_lane(store, BROKER_FREIGHTFLOW, "Grand Prairie", "Katy", Equipment.DRY_VAN)
    rankings = rank_carriers(store, load)
    assert rankings[0].carrier_name == "IBRAHIM TRANSPORT INC"
    assert names(rankings).index("DELTA PRIME, LLC") > names(rankings).index("IBRAHIM TRANSPORT INC")


def test_small_sample_trap_prefers_many_load_carrier(store):
    load = active_by_lane(store, BROKER_HAULDESK, "Plano", "New Braunfels", Equipment.DRY_VAN)
    rankings = rank_carriers(store, load)
    assert rankings[0].carrier_name == "BRAZOS CARRIER GROUP"
    assert names(rankings).index("BRAZOS CARRIER GROUP") < names(rankings).index("COMAL CREEK FREIGHT")


def test_deadhead_positioning_breaks_tie(store):
    load = active_by_lane(store, BROKER_FREIGHTFLOW, "New Braunfels", "Pasadena", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    assert names(rankings).index("RIVER CITY HAULAGE") < names(rankings).index("BAYOU BEND EXPRESS")


def test_equipment_mismatch_is_marked_as_fallback(store):
    load = active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    assert rankings
    assert any("equipment evidence is a fallback" in limitation for limitation in rankings[0].limitations)


def test_cold_lane_returns_low_confidence(store):
    load = active_by_lane(store, BROKER_BROKEROS, "Conroe", "Cibolo", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    assert rankings[0].confidence == "low"
    assert any("low lane confidence" in limitation for limitation in rankings[0].limitations)


def test_cold_lane_price_falls_back_with_low_confidence(store, geo):
    load = active_by_lane(store, BROKER_BROKEROS, "Conroe", "Cibolo", Equipment.REEFER)
    estimate = estimate_price(store, load, geo)
    assert estimate.basis == "distance_band"
    assert estimate.confidence == "low"
    assert estimate.high_usd - estimate.low_usd > 500
    assert any("fallback evidence" in limitation for limitation in estimate.limitations)


def test_directionality_uses_reverse_lane_with_discount(store, geo):
    load = active_by_lane(store, BROKER_BROKEROS, "Grand Prairie", "Katy", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    assert rankings[0].carrier_name == "Lone Pine Logistics"
    lane = component(rankings[0], "lane_familiarity").evidence
    assert lane["reverse"] > 0
    assert lane["reverse"] < 3


def test_state_grouping_trap_has_low_lane_similarity(store, geo):
    target = active_by_lane(store, BROKER_BROKEROS, "Grand Prairie", "Katy", Equipment.REEFER)
    intra_texas = next(load for load in store.current_loads.values() if load.pickup.city == "Fort Worth" and load.delivery.city == "Plano")
    assert target.pickup.state == target.delivery.state == intra_texas.pickup.state == intra_texas.delivery.state == "TX"
    assert geo.miles(intra_texas.pickup.zip_code, intra_texas.delivery.zip_code) < 50
    assert geo.miles(target.pickup.zip_code, target.delivery.zip_code) > 200
    assert lane_weight(target, intra_texas, geo)[0] < 0.01


def test_corrections_move_price_estimate_as_of(store, geo):
    load = active_by_lane(store, BROKER_BROKEROS, "Plano", "Pearland", Equipment.DRY_VAN)
    before_correction = next(version.synced_at for version in store.versions if version.source_file == "tms_c_brokeros/2026-07-15T12-00_sync.json")
    assert estimate_price(store, load, geo, as_of=before_correction).point_usd != estimate_price(store, load, geo).point_usd


def test_correction_counts_cover_all_three_brokers(store):
    cutoff = max(version.synced_at for version in store.versions)
    assert sum(_correction_counts(store, BROKER_FREIGHTFLOW, cutoff).values()) == 1
    assert sum(_correction_counts(store, BROKER_HAULDESK, cutoff).values()) == 1
    assert sum(_correction_counts(store, BROKER_BROKEROS, cutoff).values()) == 1


def test_price_shrinkage_collapses_single_load_outlier(store):
    load = active_by_lane(store, BROKER_HAULDESK, "Plano", "New Braunfels", Equipment.DRY_VAN)
    rankings = rank_carriers(store, load)
    comal = next(ranking for ranking in rankings if ranking.carrier_name == "COMAL CREEK FREIGHT")
    price = component(comal, "price").evidence
    assert price["shrunk_ppm"] > price["observed_ppm"]


def test_hauldesk_local_times_parse_as_central(store):
    actual = next(load.pickup_departed_at for load in store.versions if load.broker_id == BROKER_HAULDESK and load.pickup_departed_at is not None)
    assert actual.utcoffset().total_seconds() == -5 * 60 * 60


def test_reliability_signal_has_late_pickups_and_deliveries_per_broker(store):
    for broker in (BROKER_FREIGHTFLOW, BROKER_HAULDESK, BROKER_BROKEROS):
        pickup_late = 0
        delivery_late = 0
        for load in store.versions:
            if load.broker_id != broker:
                continue
            pickup_actuals = [actual for actual in (load.pickup_arrived_at, load.pickup_departed_at) if actual is not None]
            delivery_actuals = [actual for actual in (load.delivery_arrived_at, load.delivery_departed_at) if actual is not None]
            pickup_late += any(actual > load.pickup_close_at for actual in pickup_actuals if load.pickup_close_at is not None)
            delivery_late += any(actual > load.delivery_close_at for actual in delivery_actuals if load.delivery_close_at is not None)
        assert pickup_late > 0
        assert delivery_late > 0


def test_tenant_isolation_is_exhaustive(tmp_path, store, geo):
    for load in active_loads(store):
        isolated = ingest_data(copy_broker_only(tmp_path, load.broker_id))
        isolated_load = next(item for item in active_loads(isolated, load.broker_id) if item.raw_load_id == load.raw_load_id)
        full_rankings = rank_carriers(store, load, geo)
        isolated_rankings = rank_carriers(isolated, isolated_load, geo)
        assert [(r.carrier_id, r.score, r.confidence) for r in isolated_rankings] == [(r.carrier_id, r.score, r.confidence) for r in full_rankings]
        assert estimate_price(isolated, isolated_load, geo) == estimate_price(store, load, geo)


def test_as_of_ranking_unchanged_by_later_syncs(tmp_path, store, geo):
    load = active_by_lane(store, BROKER_FREIGHTFLOW, "Arlington", "Sugar Land", Equipment.DRY_VAN)
    partial_store = ingest_data(copy_data_through(tmp_path, BROKER_FREIGHTFLOW, "2026-07-16T00-00_sync.json"))
    partial_load = active_by_lane(partial_store, BROKER_FREIGHTFLOW, "Arlington", "Sugar Land", Equipment.DRY_VAN)
    assert [(r.carrier_id, r.score, r.confidence) for r in rank_carriers(partial_store, partial_load, geo)] == [
        (r.carrier_id, r.score, r.confidence) for r in rank_carriers(store, load, geo)
    ]


def test_reassigned_load_has_single_transition_and_one_fallthrough(store):
    versions = [version for version in store.versions if version.raw_load_id == "127738346"]
    compact = []
    for carrier_id in [version.carrier_id for version in versions]:
        if not compact or compact[-1] != carrier_id:
            compact.append(carrier_id)
    assert len([carrier_id for carrier_id in compact if carrier_id is not None]) == 2
    cutoff = max(version.synced_at for version in store.versions)
    loser = next(carrier_id for carrier_id in compact if carrier_id is not None)
    assert _fallthrough_counts(store, BROKER_FREIGHTFLOW, cutoff)[loser] == 1


def test_reliability_score_discriminates_late_carrier(store):
    target = active_by_lane(store, BROKER_FREIGHTFLOW, "Arlington", "Sugar Land", Equipment.DRY_VAN)
    history = _broker_history(store, target, target.synced_at)
    by_carrier = {}
    for load in history:
        by_carrier.setdefault(load.carrier_id, []).append(load)
    punctual = next(carrier_id for carrier_id, loads in by_carrier.items() if any(load.carrier_id == carrier_id and load.pickup_departed_at and load.pickup_departed_at <= load.pickup_close_at for load in loads))
    late = next(carrier_id for carrier_id, loads in by_carrier.items() if any(load.carrier_id == carrier_id and load.pickup_departed_at and load.pickup_departed_at > load.pickup_close_at for load in loads))
    assert _reliability_score(by_carrier[punctual]) > _reliability_score(by_carrier[late])

