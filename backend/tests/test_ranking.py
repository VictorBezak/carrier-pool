from __future__ import annotations

import json
from pathlib import Path

import pytest

from carrier_pool.geo import GeoIndex
from carrier_pool.ingest import BROKER_BROKEROS, BROKER_FREIGHTFLOW, BROKER_HAULDESK, ingest_data
from carrier_pool.models import Equipment, LoadStatus
from carrier_pool.ranking import active_loads, lane_weight, rank_carriers

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
    load = active_by_lane(store, BROKER_BROKEROS, "Conroe", "Selma", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    assert rankings[0].confidence == "low"
    assert any("low lane confidence" in limitation for limitation in rankings[0].limitations)


def test_directionality_uses_reverse_lane_with_discount(store, geo):
    load = active_by_lane(store, BROKER_BROKEROS, "Grand Prairie", "Katy", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    assert rankings[0].carrier_name == "Lone Pine Logistics"
    lane = component(rankings[0], "lane_familiarity").evidence
    assert lane["reverse"] > 0
    assert lane["reverse"] < 3


def test_price_shrinkage_collapses_single_load_outlier(store):
    load = active_by_lane(store, BROKER_HAULDESK, "Plano", "New Braunfels", Equipment.DRY_VAN)
    rankings = rank_carriers(store, load)
    comal = next(ranking for ranking in rankings if ranking.carrier_name == "COMAL CREEK FREIGHT")
    price = component(comal, "price").evidence
    assert price["shrunk_ppm"] > price["observed_ppm"]

