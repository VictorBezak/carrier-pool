from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from carrier_pool.geo import GeoIndex
from carrier_pool.ingest import BROKER_BROKEROS, BROKER_FREIGHTFLOW, BROKER_HAULDESK, ingest_data
from carrier_pool.models import Equipment, LoadStatus
from carrier_pool.pricing import estimate_price
from carrier_pool.ranking import _correction_counts, active_loads, lane_weight, rank_carriers

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


def copy_data_without(tmp_path: Path, excluded: set[str]) -> Path:
    target = tmp_path / "data"
    for broker_dir in DATA_DIR.glob("tms_*"):
        copied_dir = target / broker_dir.name
        copied_dir.mkdir(parents=True)
        for path in broker_dir.glob("*_sync.json"):
            rel = f"{broker_dir.name}/{path.name}"
            if rel not in excluded:
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


def test_corrections_move_price_estimate(tmp_path, geo):
    full_store = ingest_data(DATA_DIR)
    without_correction = ingest_data(copy_data_without(tmp_path, {"tms_c_brokeros/2026-07-15T18-00_sync.json"}))
    full_load = active_by_lane(full_store, BROKER_BROKEROS, "Plano", "Pearland", Equipment.DRY_VAN)
    stale_load = active_by_lane(without_correction, BROKER_BROKEROS, "Plano", "Pearland", Equipment.DRY_VAN)
    assert estimate_price(full_store, full_load, geo).point_usd != estimate_price(without_correction, stale_load, geo).point_usd


def test_correction_counts_cover_all_three_brokers(store):
    assert sum(_correction_counts(store, BROKER_FREIGHTFLOW).values()) == 1
    assert sum(_correction_counts(store, BROKER_HAULDESK).values()) == 1
    assert sum(_correction_counts(store, BROKER_BROKEROS).values()) == 1


def test_price_shrinkage_collapses_single_load_outlier(store):
    load = active_by_lane(store, BROKER_HAULDESK, "Plano", "New Braunfels", Equipment.DRY_VAN)
    rankings = rank_carriers(store, load)
    comal = next(ranking for ranking in rankings if ranking.carrier_name == "COMAL CREEK FREIGHT")
    price = component(comal, "price").evidence
    assert price["shrunk_ppm"] > price["observed_ppm"]


def test_hauldesk_local_times_parse_as_central(store):
    actual = next(load.pickup_actual_at for load in store.versions if load.broker_id == BROKER_HAULDESK and load.pickup_actual_at is not None)
    assert actual.utcoffset().total_seconds() == -5 * 60 * 60


def test_brokeros_on_time_verdicts_stay_unchanged(store):
    actuals = 0
    late = 0
    for load in store.versions:
        if load.broker_id != BROKER_BROKEROS:
            continue
        for actual, close_at in ((load.pickup_actual_at, load.pickup_close_at), (load.delivery_actual_at, load.delivery_close_at)):
            if actual is not None and close_at is not None:
                actuals += 1
                late += actual > close_at
    assert actuals == 76
    assert late == 0

