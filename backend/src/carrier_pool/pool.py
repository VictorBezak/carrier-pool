from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .db import BROKER_NAMES
from .geo import GeoIndex
from .ingest import BROKER_BROKEROS
from .models import CanonicalStore, CarrierRanking, Equipment, LoadStatus, LoadVersion
from .pricing import PriceEstimate, estimate_price
from .ranking import rank_carriers

POOL_FIELDS = frozenset(
    {
        "carrier_name",
        "mc_number",
        "dot_number",
        "home_city",
        "home_state",
        "equipment_types",
        "lane_cells",
        "on_time_band",
        "recency_band",
    }
)

POOL_POLICY = {
    "fields": sorted(POOL_FIELDS),
    "eligible_brokers": ["tms_a_freightflow", "tms_b_hauldesk"],
    "ineligible_brokers": {BROKER_BROKEROS: "BrokerOS carrier records do not include MC/DOT authority numbers."},
    "never_shared": ["customer", "load_id", "source_file", "rates", "exact_counts", "zip5", "timestamps", "raw_tms_payload"],
    "matching_rule": "MC/DOT authority numbers only; overlapping carriers use the requesting broker's own history.",
}


@dataclass(frozen=True)
class PoolContribution:
    contributor_broker_id: str
    contributor_broker_name: str
    carrier_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class PoolCarrierRanking:
    contributor_broker_id: str
    contributor_broker_name: str
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
    own = rank_carriers(store, target, geo, as_of=as_of)
    pool = pool_rankings(store, target, geo, as_of, opt_in_brokers or set(), price) if include_pool else []
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
    known_authorities = _known_authorities(store, target.broker_id)
    rankings: list[PoolCarrierRanking] = []
    for broker_id in sorted(opt_in_brokers):
        if broker_id == target.broker_id or broker_id == BROKER_BROKEROS:
            continue
        for contribution in pool_contributions(store, broker_id, as_of):
            if _authority(contribution.payload) in known_authorities:
                continue
            score, confidence, reasons, limitations = _score_contribution(contribution.payload, target)
            rankings.append(
                PoolCarrierRanking(
                    contributor_broker_id=broker_id,
                    contributor_broker_name=contribution.contributor_broker_name,
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
    for carrier_id, history in sorted(by_carrier.items()):
        carrier = store.carriers.get((broker_id, carrier_id))
        if not carrier or not (carrier.mc_number or carrier.dot_number):
            continue
        payload = _payload(carrier.name, carrier.mc_number, carrier.dot_number, carrier.home.city if carrier.home else None, carrier.home.state if carrier.home else None, history)
        contributions.append(PoolContribution(broker_id, BROKER_NAMES.get(broker_id, broker_id), carrier_id, payload))
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


def _payload(name: str, mc_number: str | None, dot_number: str | None, home_city: str | None, home_state: str | None, history: list[LoadVersion]) -> dict[str, Any]:
    equipment_types = sorted({load.equipment.value for load in history if load.equipment != Equipment.UNKNOWN})
    lane_counter: Counter[tuple[str, str, str]] = Counter((load.pickup.zip_code[:3], load.delivery.zip_code[:3], load.equipment.value) for load in history)
    lane_cells = [f"{origin}>{dest}:{equipment}:{_activity_band(count)}" for (origin, dest, equipment), count in sorted(lane_counter.items())]
    return {
        "carrier_name": name,
        "mc_number": mc_number,
        "dot_number": dot_number,
        "home_city": home_city,
        "home_state": home_state,
        "equipment_types": equipment_types,
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


def _known_authorities(store: CanonicalStore, broker_id: str) -> set[tuple[str | None, str | None]]:
    return {
        (carrier.mc_number, carrier.dot_number)
        for (carrier_broker_id, _carrier_id), carrier in store.carriers.items()
        if carrier_broker_id == broker_id and (carrier.mc_number or carrier.dot_number)
    }


def _authority(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    return payload["mc_number"], payload["dot_number"]


def _activity_band(count: int) -> str:
    if count >= 4:
        return "many"
    if count >= 2:
        return "some"
    return "one"


def _on_time_band(history: list[LoadVersion]) -> str:
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
    if observations < 3:
        return "thin"
    rate = on_time / observations
    if rate >= 0.82:
        return "strong"
    if rate >= 0.62:
        return "mixed"
    return "weak"


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
