from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .geo import GeoIndex
from .ingest import BROKER_BROKEROS
from .models import CanonicalStore, CarrierRanking, Equipment, LoadStatus, LoadVersion, PooledFacts, PooledStop
from .pricing import PriceEstimate, estimate_price
from .ranking import _fallthrough_counts, rank_carriers

POOL_FIELD_TIERS = {
    "carrier_identity": [
        "carrier_name",
        "mc_number",
        "dot_number",
        "home_city",
        "home_state",
    ],
    "carrier_owned_facts": [
        "equipment_types",
        "stops",
        "appointment_observations",
        "appointment_on_time",
        "fallthrough_count",
        "lane_cells",
        "on_time_band",
        "recency_band",
    ],
    "broker_owned_never_shared": [
        "customer",
        "load_id",
        "source_file",
        "rates",
        "margins",
        "exact_load_counts",
        "exact_timestamps",
        "correction_counts",
        "raw_tms_payload",
    ],
}

POOL_FIELDS = frozenset(
    {
        "carrier_name",
        "mc_number",
        "dot_number",
        "home_city",
        "home_state",
        "equipment_types",
        "stops",
        "appointment_observations",
        "appointment_on_time",
        "fallthrough_count",
        "lane_cells",
        "on_time_band",
        "recency_band",
    }
)

POOL_POLICY = {
    "fields": sorted(POOL_FIELDS),
    "field_tiers": POOL_FIELD_TIERS,
    "eligible_brokers": ["tms_a_freightflow", "tms_b_hauldesk"],
    "ineligible_brokers": {BROKER_BROKEROS: "BrokerOS carrier records do not include MC/DOT authority numbers."},
    "never_shared": POOL_FIELD_TIERS["broker_owned_never_shared"],
    "matching_rule": "MC or DOT authority match; overlapping carriers merge carrier-owned facts into the requesting broker's own ranking with provenance.",
}


@dataclass(frozen=True)
class PoolContribution:
    carrier_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class PoolCarrierRanking:
    carrier_id: str
    carrier_name: str
    score: float
    confidence: str
    expected_carrier_cost_usd: float
    reasons: list[str]
    limitations: list[str]
    payload: dict[str, Any]


@dataclass(frozen=True)
class RecommendationBundle:
    price: PriceEstimate
    own_carriers: list[CarrierRanking]
    pool_carriers: list[PoolCarrierRanking]


def recommend(
    store: CanonicalStore,
    target: LoadVersion,
    geo: GeoIndex | None = None,
    as_of: datetime | None = None,
    opt_in_brokers: set[str] | None = None,
    include_pool: bool = False,
) -> RecommendationBundle:
    geo = geo or GeoIndex.bundled()
    as_of = as_of or target.synced_at
    price = estimate_price(store, target, geo, as_of=as_of)
    opt_ins = opt_in_brokers or set()
    pooled = pooled_facts(store, target.broker_id, opt_ins, as_of) if include_pool else {}
    own = rank_carriers(store, target, geo, as_of=as_of, pooled=pooled)
    pool = pool_rankings(store, target, geo, as_of, opt_ins, price) if include_pool else []
    return RecommendationBundle(price=price, own_carriers=own, pool_carriers=pool)


def pool_rankings(
    store: CanonicalStore,
    target: LoadVersion,
    geo: GeoIndex,
    as_of: datetime,
    opt_in_brokers: set[str],
    market_price: PriceEstimate | None = None,
) -> list[PoolCarrierRanking]:
    if target.broker_id == BROKER_BROKEROS or target.broker_id not in opt_in_brokers:
        return []
    market_price = market_price or estimate_price(store, target, geo, as_of=as_of)
    rankings: list[PoolCarrierRanking] = []
    for broker_id in sorted(opt_in_brokers):
        if broker_id == target.broker_id or broker_id == BROKER_BROKEROS:
            continue
        for contribution in pool_contributions(store, broker_id, as_of):
            if _matching_local_carrier_id(store, target.broker_id, contribution.payload, as_of):
                continue
            score, confidence, reasons, limitations = _score_contribution(contribution.payload, target)
            rankings.append(
                PoolCarrierRanking(
                    carrier_id=contribution.carrier_id,
                    carrier_name=contribution.payload["carrier_name"],
                    score=score,
                    confidence=confidence,
                    expected_carrier_cost_usd=market_price.point_usd,
                    reasons=reasons,
                    limitations=limitations,
                    payload=contribution.payload,
                )
            )
    return sorted(rankings, key=lambda ranking: (-ranking.score, ranking.carrier_name))


def pooled_facts(store: CanonicalStore, requesting_broker_id: str, opt_in_brokers: set[str], as_of: datetime) -> dict[str, PooledFacts]:
    """Carrier-owned facts from other opted-in brokers, keyed by the requesting broker's carrier_id."""
    if requesting_broker_id == BROKER_BROKEROS or requesting_broker_id not in opt_in_brokers:
        return {}
    merged: dict[str, PooledFacts] = {}
    for broker_id in sorted(opt_in_brokers):
        if broker_id == requesting_broker_id or broker_id == BROKER_BROKEROS:
            continue
        for contribution in pool_contributions(store, broker_id, as_of):
            local_carrier_id = _matching_local_carrier_id(store, requesting_broker_id, contribution.payload, as_of)
            if local_carrier_id is None:
                continue
            facts = _facts_from_payload(contribution.payload)
            existing = merged.get(local_carrier_id, PooledFacts())
            merged[local_carrier_id] = PooledFacts(
                equipment_types=existing.equipment_types | facts.equipment_types,
                stops=existing.stops + facts.stops,
                appointment_observations=existing.appointment_observations + facts.appointment_observations,
                appointment_on_time=existing.appointment_on_time + facts.appointment_on_time,
                fallthrough_count=existing.fallthrough_count + facts.fallthrough_count,
                lane_cells=tuple(sorted(set(existing.lane_cells) | set(facts.lane_cells))),
            )
    return merged


def pool_contributions(store: CanonicalStore, broker_id: str, as_of: datetime) -> list[PoolContribution]:
    if broker_id == BROKER_BROKEROS:
        return []
    loads = [
        load
        for load in store.loads_as_of(broker_id, as_of)
        if load.carrier_id
        and load.status in {LoadStatus.COVERED, LoadStatus.IN_TRANSIT, LoadStatus.DELIVERED, LoadStatus.COMPLETED}
    ]
    by_carrier: dict[str, list[LoadVersion]] = defaultdict(list)
    for load in loads:
        by_carrier[load.carrier_id].append(load)

    contributions: list[PoolContribution] = []
    fallthroughs = _fallthrough_counts(store, broker_id, as_of)
    for carrier_id, history in sorted(by_carrier.items()):
        carrier = store.carriers.get((broker_id, carrier_id))
        if not carrier or not (carrier.mc_number or carrier.dot_number):
            continue
        payload = _payload(
            carrier.name,
            carrier.mc_number,
            carrier.dot_number,
            carrier.home.city if carrier.home else None,
            carrier.home.state if carrier.home else None,
            history,
            fallthroughs.get(carrier_id, 0),
        )
        contributions.append(PoolContribution(carrier_id, payload))
    return contributions


def recursive_payload_keys(payload: Any) -> set[str]:
    if isinstance(payload, dict):
        keys = set(payload)
        for value in payload.values():
            keys |= recursive_payload_keys(value)
        return keys
    if isinstance(payload, list):
        keys: set[str] = set()
        for value in payload:
            keys |= recursive_payload_keys(value)
        return keys
    return set()


def _payload(
    name: str,
    mc_number: str | None,
    dot_number: str | None,
    home_city: str | None,
    home_state: str | None,
    history: list[LoadVersion],
    fallthrough_count: int,
) -> dict[str, Any]:
    equipment_types = sorted({load.equipment.value for load in history if load.equipment != Equipment.UNKNOWN})
    lane_counter: Counter[tuple[str, str, str]] = Counter((load.pickup.zip_code[:3], load.delivery.zip_code[:3], load.equipment.value) for load in history)
    lane_cells = [f"{origin}>{dest}:{equipment}:{_activity_band(count)}" for (origin, dest, equipment), count in sorted(lane_counter.items())]
    appointment_on_time, appointment_observations = _appointment_counts(history)
    return {
        "carrier_name": name,
        "mc_number": mc_number,
        "dot_number": dot_number,
        "home_city": home_city,
        "home_state": home_state,
        "equipment_types": equipment_types,
        "stops": _stop_cells(history),
        "appointment_observations": appointment_observations,
        "appointment_on_time": appointment_on_time,
        "fallthrough_count": fallthrough_count,
        "lane_cells": lane_cells,
        "on_time_band": _on_time_band(history),
        "recency_band": _recency_band(history),
    }


def _score_contribution(payload: dict[str, Any], target: LoadVersion) -> tuple[float, str, list[str], list[str]]:
    lane_strength = _lane_strength(payload["lane_cells"], target)
    equipment_strength = 1.0 if target.equipment.value in payload["equipment_types"] else 0.45
    on_time_strength = {"strong": 0.9, "mixed": 0.62, "thin": 0.5, "weak": 0.35}[payload["on_time_band"]]
    recency_strength = {"recent": 0.9, "warm": 0.65, "stale": 0.35, "unknown": 0.45}[payload["recency_band"]]
    raw = 0.45 * lane_strength + 0.20 * equipment_strength + 0.20 * on_time_strength + 0.15 * recency_strength
    confidence = "medium" if lane_strength >= 0.65 and payload["on_time_band"] in {"strong", "mixed"} else "low"
    reasons = [
        f"pool carrier from an opted-in broker with {payload['on_time_band']} on-time history",
        f"{payload['recency_band']} relationship activity in bucketed contribution data",
    ]
    if lane_strength >= 0.65:
        reasons.insert(0, "bucketed ZIP3 lane history matches this load")
    else:
        reasons.insert(0, "no exact bucketed ZIP3 lane match; treated as exploratory pool coverage")
    limitations = [
        "pool tier uses bucketed contribution data only, never another broker's rates or load records",
        "expected cost falls back to the requesting broker's market estimate",
    ]
    if target.equipment.value not in payload["equipment_types"]:
        limitations.append(f"pool carrier has no shared {target.equipment.value} equipment bucket")
    return round(max(0.0, min(1.0, raw)), 4), confidence, reasons, limitations


def _lane_strength(lane_cells: list[str], target: LoadVersion) -> float:
    target_origin = target.pickup.zip_code[:3]
    target_dest = target.delivery.zip_code[:3]
    target_equipment = target.equipment.value
    best = 0.0
    for cell in lane_cells:
        lane, equipment, band = cell.split(":")
        origin, dest = lane.split(">")
        band_strength = {"one": 0.45, "some": 0.72, "many": 1.0}[band]
        equipment_strength = 1.0 if equipment == target_equipment else 0.5
        if origin == target_origin and dest == target_dest:
            best = max(best, band_strength * equipment_strength)
        elif origin == target_dest and dest == target_origin:
            best = max(best, 0.35 * band_strength * equipment_strength)
    return 1 - math.exp(-best * 1.7)


def _matching_local_carrier_id(store: CanonicalStore, broker_id: str, payload: dict[str, Any], as_of: datetime) -> str | None:
    del as_of  # Carrier masters are not versioned in the canonical store.
    for (carrier_broker_id, carrier_id), carrier in sorted(store.carriers.items()):
        if carrier_broker_id != broker_id:
            continue
        if _authority_matches(carrier.mc_number, carrier.dot_number, payload.get("mc_number"), payload.get("dot_number")):
            return carrier_id
    return None


def _authority_matches(local_mc: str | None, local_dot: str | None, pooled_mc: str | None, pooled_dot: str | None) -> bool:
    return bool((local_mc and pooled_mc and local_mc == pooled_mc) or (local_dot and pooled_dot and local_dot == pooled_dot))


def _activity_band(count: int) -> str:
    if count >= 4:
        return "many"
    if count >= 2:
        return "some"
    return "one"


def _on_time_band(history: list[LoadVersion]) -> str:
    on_time, observations = _appointment_counts(history)
    if observations < 3:
        return "thin"
    rate = on_time / observations
    if rate >= 0.82:
        return "strong"
    if rate >= 0.62:
        return "mixed"
    return "weak"


def _appointment_counts(history: list[LoadVersion]) -> tuple[int, int]:
    observations = 0
    on_time = 0
    for load in history:
        for actual, close_at in (
            (load.pickup_arrived_at, load.pickup_close_at),
            (load.pickup_departed_at, load.pickup_close_at),
            (load.delivery_arrived_at, load.delivery_close_at),
            (load.delivery_departed_at, load.delivery_close_at),
        ):
            if actual and close_at:
                observations += 1
                on_time += int(actual <= close_at)
    return on_time, observations


def _stop_cells(history: list[LoadVersion]) -> list[str]:
    cells: list[str] = []
    for load in history:
        pickup_at = load.pickup_departed_at or load.pickup_arrived_at
        delivery_at = load.delivery_departed_at or load.delivery_arrived_at
        if pickup_at:
            cells.append(_stop_cell(load.pickup.zip_code, pickup_at, "pickup"))
        if delivery_at:
            cells.append(_stop_cell(load.delivery.zip_code, delivery_at, "delivery"))
    return sorted(cells)


def _stop_cell(zip_code: str, observed_at: datetime, kind: str) -> str:
    bucket = int(observed_at.timestamp() // (6 * 60 * 60))
    return f"{zip_code}:{bucket}:{kind}"


def _facts_from_payload(payload: dict[str, Any]) -> PooledFacts:
    return PooledFacts(
        equipment_types=frozenset(str(item) for item in payload["equipment_types"]),
        stops=tuple(_parse_stop_cell(cell) for cell in payload["stops"]),
        appointment_observations=int(payload["appointment_observations"]),
        appointment_on_time=int(payload["appointment_on_time"]),
        fallthrough_count=int(payload["fallthrough_count"]),
        lane_cells=tuple(str(item) for item in payload["lane_cells"]),
    )


def _parse_stop_cell(cell: str) -> PooledStop:
    zip_code, bucket, kind = cell.split(":")
    observed_at = datetime.fromtimestamp(int(bucket) * 6 * 60 * 60, tz=timezone.utc)
    return PooledStop(zip_code=zip_code, observed_at=observed_at, kind=kind)


def _recency_band(history: list[LoadVersion]) -> str:
    updated = [load.updated_at for load in history if load.updated_at]
    if not updated:
        return "unknown"
    days = (max(load.synced_at for load in history) - max(updated)).days
    if days <= 21:
        return "recent"
    if days <= 60:
        return "warm"
    return "stale"
