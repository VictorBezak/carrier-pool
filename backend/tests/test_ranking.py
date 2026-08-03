from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from carrier_pool.geo import GeoIndex
from carrier_pool.ingest import BROKER_BROKEROS, BROKER_FREIGHTFLOW, BROKER_HAULDESK, ingest_data
from carrier_pool.models import Equipment, LoadStatus
from carrier_pool.pricing import estimate_price
from carrier_pool.ranking import (
    UNKNOWN_POSITION_SCORE,
    WEIGHTS,
    _broker_history,
    _correction_counts,
    _deadhead_score,
    _fallthrough_counts,
    _position_estimate,
    _reliability_score,
    active_loads,
    lane_weight,
    rank_carriers,
)

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


def _carrier_names(store, broker_id: str) -> dict[str, str]:
    return {carrier.carrier_id: carrier.name for (broker, carrier_id), carrier in store.carriers.items() if broker == broker_id}


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


def test_deadhead_outweighs_lane_and_area_evidence(store):
    """The close carrier wins on empty miles alone.

    River City runs the corridor inbound, so it has only reverse-lane credit and almost no
    pickup history near New Braunfels; Bayou Bend beats it on both. The ranking still has to
    prefer the truck that is 29 expected empty miles out over the one that is 124.
    """
    load = active_by_lane(store, BROKER_FREIGHTFLOW, "New Braunfels", "Pasadena", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    close = next(ranking for ranking in rankings if ranking.carrier_name == "RIVER CITY HAULAGE")
    far = next(ranking for ranking in rankings if ranking.carrier_name == "BAYOU BEND EXPRESS")

    assert component(close, "lane_familiarity").score < component(far, "lane_familiarity").score
    assert component(close, "positioning").evidence["pickups_within_50mi"] < component(far, "positioning").evidence["pickups_within_50mi"]
    assert component(close, "positioning").score > component(far, "positioning").score
    assert close.score > far.score
    assert names(rankings).index("RIVER CITY HAULAGE") < names(rankings).index("BAYOU BEND EXPRESS")


def test_geography_is_scored_in_exactly_one_component(store):
    """Working near the pickup must not both cut the deadhead estimate and earn its own points.

    An earlier pass scored pickup density separately from positioning, which let a shuttle
    carrier refund the deadhead penalty its own stale position had just earned.
    """
    load = active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    delta = next(ranking for ranking in rankings if ranking.carrier_name == "DELTA PRIME LLC")
    assert [component.name for component in delta.components].count("positioning") == 1
    assert "area_familiarity" not in {component.name for component in delta.components}
    # The density evidence survives for auditing, it just no longer carries weight of its own.
    assert component(delta, "positioning").evidence["pickups_within_50mi"] == 8


def test_nearby_truck_beats_corridor_veteran_with_a_stale_far_position(store):
    """Brazos has never touched this corridor but has a truck 27 miles out; Delta Prime runs
    it daily from 103 miles out. Empty miles decide it."""
    load = active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    assert rankings[0].carrier_name == "BRAZOS CARRIER GROUP"
    brazos = rankings[0]
    delta = next(ranking for ranking in rankings if ranking.carrier_name == "DELTA PRIME LLC")
    assert component(brazos, "lane_familiarity").score < component(delta, "lane_familiarity").score
    assert component(brazos, "positioning").score > component(delta, "positioning").score


def test_deadhead_is_scored_against_loaded_miles_not_absolute_miles(store):
    """165 empty miles is ruinous on a short haul and routine on a long one."""
    assert _deadhead_score(165.0, 209.0) < 0.4
    assert _deadhead_score(165.0, 1200.0) == pytest.approx(1.0)
    # Short drayage keeps its absolute allowance despite a geometrically large ratio.
    assert _deadhead_score(30.0, 40.0) == pytest.approx(1.0)
    # Monotonic in empty miles for a fixed load.
    scores = [_deadhead_score(miles, 250.0) for miles in (0, 25, 50, 100, 200, 400)]
    assert scores == sorted(scores, reverse=True)


def test_position_falls_back_to_operating_footprint_when_last_delivery_is_stale(store, geo):
    """A shuttle carrier is credited with returning home, but only once its drop goes cold.

    Delta Prime runs New Braunfels->Pasadena daily, so six days after its last Pasadena drop
    its equipment is near Seguin, not stranded 165 miles away at the Houston end.
    """
    target = active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    history = _broker_history(store, target, target.synced_at)
    delta = next(carrier_id for carrier_id, name in _carrier_names(store, BROKER_HAULDESK).items() if name == "DELTA PRIME LLC")
    position = _position_estimate([load for load in history if load.carrier_id == delta], target, geo, target.synced_at)

    assert position.staleness_days > 4
    # A six-day-old drop keeps less than half the say in where the truck is.
    assert position.freshness < 0.5
    assert position.last_delivery_deadhead_miles > 150
    assert position.footprint_deadhead_miles < 60
    assert position.expected_deadhead_miles < position.last_delivery_deadhead_miles / 1.5


def test_fresh_nearby_delivery_is_credited_but_shrunk_on_thin_evidence(store):
    """Waxahachie Way delivered into the pickup ZIP two days earlier, off a single load.

    The empty miles are as good as they get, so the raw deadhead curve is maxed out, but one
    delivery is not proof the carrier can free a truck tomorrow. The score sits between the
    unknown-position prior and a perfect estimate, and the thin evidence is disclosed.
    """
    load = active_by_lane(store, BROKER_BROKEROS, "Plano", "Pearland", Equipment.DRY_VAN)
    rankings = rank_carriers(store, load)
    waxahachie = next(ranking for ranking in rankings if ranking.carrier_name == "Waxahachie Way")
    positioning = component(waxahachie, "positioning")

    assert positioning.evidence["last_delivery_deadhead_miles"] < 5
    assert positioning.evidence["position_observations"] == 1
    assert _deadhead_score(positioning.evidence["expected_deadhead_miles"], load.distance_miles) == pytest.approx(1.0)
    assert UNKNOWN_POSITION_SCORE < positioning.score < 1.0
    assert any("recorded delivery" in limitation for limitation in waxahachie.limitations)


def test_positioning_shrinks_toward_the_prior_on_thin_evidence(store):
    """Two carriers can be equally close and not equally believable.

    Brazos has eight consistent Schertz drops; Comal Creek has one, six days old. Both sit
    inside the free-mileage allowance, so both max the raw curve, but they must not score the
    same. Every other component already shrinks small samples this way (DECISIONS 5).
    """
    load = active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    brazos = next(ranking for ranking in rankings if ranking.carrier_name == "BRAZOS CARRIER GROUP")
    comal = next(ranking for ranking in rankings if ranking.carrier_name == "COMAL CREEK FREIGHT")

    for ranking in (brazos, comal):
        evidence = component(ranking, "positioning").evidence
        assert _deadhead_score(evidence["expected_deadhead_miles"], load.distance_miles) == pytest.approx(1.0)

    assert component(brazos, "positioning").evidence["position_observations"] == 8
    assert component(comal, "positioning").evidence["position_observations"] == 1
    assert component(brazos, "positioning").score > component(comal, "positioning").score
    # Shrinkage is bounded by the evidence, so even a flawless eight-load position is not 1.0.
    assert component(brazos, "positioning").score < 1.0


def test_unknown_position_collapses_to_the_prior(store):
    """A carrier with no delivery actuals scores exactly the prior, with no special-casing."""
    load = active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    alamo = next(ranking for ranking in rankings if ranking.carrier_name == "ALAMO LINEHAUL")
    positioning = component(alamo, "positioning")

    assert positioning.evidence["expected_deadhead_miles"] is None
    assert positioning.score == pytest.approx(UNKNOWN_POSITION_SCORE)


def test_high_deadhead_carrier_is_flagged_and_priced_per_mile_driven(store):
    load = active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    rankings = rank_carriers(store, load)
    delta = next(ranking for ranking in rankings if ranking.carrier_name == "DELTA PRIME LLC")
    price = component(delta, "price").evidence

    assert any("empty miles against" in limitation for limitation in delta.limitations)
    # The quoted rate only pays for loaded miles, so what the carrier turns is strictly less.
    assert price["all_in_ppm_with_deadhead"] < price["shrunk_ppm"]


def test_positioning_is_the_heaviest_component():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert WEIGHTS["positioning"] == max(WEIGHTS.values())
    assert WEIGHTS["positioning"] > WEIGHTS["lane_familiarity"]


def test_inferred_footprint_never_fully_overrides_an_observed_position(store, geo):
    """A stale drop keeps at least half the say, however routine the carrier's area is.

    Delta Prime's return to New Braunfels is unrecorded, and for a one-directional shuttle
    that repositioning move is itself unpaid deadhead. The estimate may lean on it, but it
    cannot pretend the observed Pasadena drop never happened.
    """
    target = active_by_lane(store, BROKER_HAULDESK, "Seguin", "Baytown", Equipment.REEFER)
    history = _broker_history(store, target, target.synced_at)
    delta = next(carrier_id for carrier_id, name in _carrier_names(store, BROKER_HAULDESK).items() if name == "DELTA PRIME LLC")
    position = _position_estimate([load for load in history if load.carrier_id == delta], target, geo, target.synced_at)

    midpoint = (position.last_delivery_deadhead_miles + position.footprint_deadhead_miles) / 2
    assert position.freshness < 0.5
    assert position.expected_deadhead_miles == pytest.approx(midpoint)


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

