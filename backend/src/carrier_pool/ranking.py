from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from .geo import GeoIndex
from .models import CanonicalStore, CarrierRanking, ComponentScore, Equipment, LoadStatus, LoadVersion
from .pricing import PriceEstimate, estimate_carrier_price, estimate_price, lane_weight as weighted_lane_weight

WEIGHTS = {
    "lane_familiarity": 0.28,
    "positioning": 0.20,
    "price": 0.18,
    "reliability": 0.14,
    "recency": 0.10,
    "customer_affinity": 0.05,
    "stability": 0.05,
}


@dataclass(frozen=True)
class CarrierEvidence:
    carrier_id: str
    history: list[LoadVersion]
    lane_effective: float
    direct_effective: float
    reverse_effective: float
    total_loads: int
    recent_loads: int
    reliability_observations: int
    price_observations: int
    last_delivery_deadhead_miles: float | None
    home_deadhead_miles: float | None
    correction_count: int
    fallthrough_count: int


def rank_carriers(store: CanonicalStore, target: LoadVersion, geo: GeoIndex | None = None) -> list[CarrierRanking]:
    geo = geo or GeoIndex.bundled()
    history = _broker_history(store, target)
    candidate_ids = _candidate_ids(history, target)
    market_price = estimate_price(store, target, geo)
    fallthroughs = _fallthrough_counts(store, target.broker_id)
    corrections = _correction_counts(store, target.broker_id)
    rankings: list[CarrierRanking] = []

    for carrier_id in candidate_ids:
        carrier_history = [load for load in history if load.carrier_id == carrier_id]
        evidence = _evidence(carrier_id, carrier_history, target, geo, corrections.get(carrier_id, 0), fallthroughs.get(carrier_id, 0))
        carrier_price = estimate_carrier_price(store, target, carrier_id, geo)
        components = _components(evidence, carrier_history, target, geo, carrier_price, market_price)
        score = round(sum(component.score * component.weight for component in components), 4)
        confidence = _confidence(evidence)
        carrier = store.carriers[(target.broker_id, carrier_id)]
        rankings.append(
            CarrierRanking(
                broker_id=target.broker_id,
                load_id=target.raw_load_id,
                carrier_id=carrier_id,
                carrier_name=carrier.name,
                score=score,
                confidence=confidence,
                components=components,
                reasons=_reasons(components, evidence, target),
                limitations=_limitations(evidence, target),
            )
        )

    return sorted(rankings, key=lambda ranking: (-ranking.score, ranking.carrier_name))


def active_loads(store: CanonicalStore, broker_id: str | None = None) -> list[LoadVersion]:
    loads = [load for load in store.current_loads.values() if load.status == LoadStatus.ACTIVE]
    if broker_id is not None:
        loads = [load for load in loads if load.broker_id == broker_id]
    return sorted(loads, key=lambda load: (load.broker_id, load.raw_load_id))


def _broker_history(store: CanonicalStore, target: LoadVersion) -> list[LoadVersion]:
    return [
        load
        for load in store.current_loads.values()
        if load.broker_id == target.broker_id
        and load.raw_load_id != target.raw_load_id
        and load.carrier_id is not None
        and load.carrier_rate_usd is not None
        and load.status in {LoadStatus.COVERED, LoadStatus.IN_TRANSIT, LoadStatus.DELIVERED, LoadStatus.COMPLETED}
    ]


def _candidate_ids(history: list[LoadVersion], target: LoadVersion) -> list[str]:
    by_carrier: dict[str, list[LoadVersion]] = defaultdict(list)
    for load in history:
        by_carrier[load.carrier_id].append(load)
    all_candidates = sorted(by_carrier)
    if target.equipment == Equipment.UNKNOWN:
        return all_candidates
    candidates = []
    for carrier_id, loads in by_carrier.items():
        if any(load.equipment in {target.equipment, Equipment.UNKNOWN} for load in loads):
            candidates.append(carrier_id)
    return sorted(candidates) if candidates else all_candidates


def lane_weight(target: LoadVersion, historical: LoadVersion, geo: GeoIndex) -> tuple[float, float, float]:
    return weighted_lane_weight(target, historical, geo)


def _evidence(carrier_id: str, history: list[LoadVersion], target: LoadVersion, geo: GeoIndex, correction_count: int, fallthrough_count: int) -> CarrierEvidence:
    weighted = [lane_weight(target, load, geo) for load in history]
    lane_effective = sum(item[0] for item in weighted)
    direct_effective = sum(item[1] for item in weighted)
    reverse_effective = sum(item[2] for item in weighted)
    target_time = target.pickup_open_at or target.created_at or datetime.now(timezone.utc)
    recent_loads = sum(1 for load in history if load.updated_at and (target_time - load.updated_at).days <= 21)
    reliability_observations = sum(1 for load in history if load.pickup_actual_at or load.delivery_actual_at)
    price_observations = sum(1 for load in history if load.carrier_rate_usd and load.distance_miles > 0)
    last_load = max((load for load in history if load.delivery_actual_at and load.delivery_actual_at <= target_time), key=lambda load: load.delivery_actual_at, default=None)
    last_deadhead = geo.miles(last_load.delivery.zip_code, target.pickup.zip_code) if last_load else None
    if last_deadhead is not None and math.isinf(last_deadhead):
        # Unlocatable ZIP: report positioning as unknown rather than an infinite deadhead.
        last_deadhead = None
    return CarrierEvidence(
        carrier_id=carrier_id,
        history=history,
        lane_effective=lane_effective,
        direct_effective=direct_effective,
        reverse_effective=reverse_effective,
        total_loads=len(history),
        recent_loads=recent_loads,
        reliability_observations=reliability_observations,
        price_observations=price_observations,
        last_delivery_deadhead_miles=last_deadhead,
        home_deadhead_miles=None,
        correction_count=correction_count,
        fallthrough_count=fallthrough_count,
    )


def _components(evidence: CarrierEvidence, history: list[LoadVersion], target: LoadVersion, geo: GeoIndex, carrier_price: PriceEstimate, market_price: PriceEstimate) -> list[ComponentScore]:
    lane_score = 1 - math.exp(-evidence.lane_effective / 2.0)
    positioning_score = _positioning_score(evidence, history, target, geo)
    price_score, price_evidence = _price_score(carrier_price, market_price)
    reliability_score = _reliability_score(history)
    recency_score = min(1.0, 0.55 * (1 - math.exp(-evidence.total_loads / 5.0)) + 0.45 * (1 - math.exp(-evidence.recent_loads / 2.0)))
    customer_score = _customer_score(history, target)
    stability_score = max(0.0, 1.0 - 0.18 * evidence.correction_count - 0.28 * evidence.fallthrough_count)
    return [
        ComponentScore("lane_familiarity", _clip(lane_score), WEIGHTS["lane_familiarity"], {"effective_loads": round(evidence.lane_effective, 2), "direct": round(evidence.direct_effective, 2), "reverse": round(evidence.reverse_effective, 2)}),
        ComponentScore("positioning", _clip(positioning_score), WEIGHTS["positioning"], {"last_delivery_deadhead_miles": _round_optional(evidence.last_delivery_deadhead_miles)}),
        ComponentScore("price", _clip(price_score), WEIGHTS["price"], price_evidence),
        ComponentScore("reliability", _clip(reliability_score), WEIGHTS["reliability"], {"observations": evidence.reliability_observations}),
        ComponentScore("recency", _clip(recency_score), WEIGHTS["recency"], {"total_loads": evidence.total_loads, "recent_loads": evidence.recent_loads}),
        ComponentScore("customer_affinity", _clip(customer_score), WEIGHTS["customer_affinity"], {"same_customer_loads": sum(1 for load in history if load.customer_id == target.customer_id)}),
        ComponentScore("stability", _clip(stability_score), WEIGHTS["stability"], {"corrections": evidence.correction_count, "fallthroughs": evidence.fallthrough_count}),
    ]


def _positioning_score(evidence: CarrierEvidence, history: list[LoadVersion], target: LoadVersion, geo: GeoIndex) -> float:
    if evidence.last_delivery_deadhead_miles is not None:
        last_score = math.exp(-evidence.last_delivery_deadhead_miles / 85.0)
    else:
        last_score = 0.35
    pickup_density = sum(math.exp(-geo.miles(load.pickup.zip_code, target.pickup.zip_code) / 50.0) for load in history)
    density_score = 1 - math.exp(-pickup_density / 2.0)
    return 0.7 * last_score + 0.3 * density_score


def _price_score(carrier_price: PriceEstimate, market_price: PriceEstimate) -> tuple[float, dict[str, float | int | str]]:
    relative = (market_price.point_ppm - carrier_price.point_ppm) / market_price.point_ppm if market_price.point_ppm else 0.0
    score = 0.5 + relative * 2.2
    return score, {
        "observed_ppm": carrier_price.observed_ppm,
        "shrunk_ppm": carrier_price.point_ppm,
        "prior_ppm": market_price.point_ppm,
        "price_effective_loads": carrier_price.effective_loads,
        "basis": carrier_price.basis,
        "point_usd": carrier_price.point_usd,
    }


def _reliability_score(history: list[LoadVersion]) -> float:
    successes = 3.0
    observations = 4.0
    for load in history:
        if load.pickup_actual_at and load.pickup_close_at:
            observations += 1
            successes += 1 if load.pickup_actual_at <= load.pickup_close_at else 0
        if load.delivery_actual_at and load.delivery_close_at:
            observations += 1
            successes += 1 if load.delivery_actual_at <= load.delivery_close_at else 0
    return successes / observations


def _customer_score(history: list[LoadVersion], target: LoadVersion) -> float:
    same = sum(1 for load in history if load.customer_id == target.customer_id)
    return (same + 1.0) / (same + 6.0)


def _fallthrough_counts(store: CanonicalStore, broker_id: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    by_load: dict[str, list[LoadVersion]] = defaultdict(list)
    for version in store.versions:
        if version.broker_id == broker_id:
            by_load[version.raw_load_id].append(version)
    for versions in by_load.values():
        previous = None
        for version in sorted(versions, key=lambda item: item.updated_at or datetime.min.replace(tzinfo=timezone.utc)):
            if previous and version.carrier_id and previous != version.carrier_id:
                counts[previous] += 1
            if version.carrier_id:
                previous = version.carrier_id
    return counts


def _correction_counts(store: CanonicalStore, broker_id: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    by_load: dict[str, list[LoadVersion]] = defaultdict(list)
    for version in store.versions:
        if version.broker_id == broker_id:
            by_load[version.raw_load_id].append(version)

    for versions in by_load.values():
        previous_rate = None
        for version in sorted(versions, key=lambda item: item.updated_at or datetime.min.replace(tzinfo=timezone.utc)):
            if version.carrier_rate_usd is None:
                continue
            adjusted = float(version.raw.get("_rate_adjustment_abs", 0.0) or 0.0) > 0.0
            rate_changed = previous_rate is not None and not math.isclose(version.carrier_rate_usd, previous_rate)
            if version.carrier_id and (rate_changed or adjusted):
                counts[version.carrier_id] += 1
            previous_rate = version.carrier_rate_usd
    return counts


def _confidence(evidence: CarrierEvidence) -> str:
    if evidence.lane_effective < 0.35:
        return "low"
    raw = (
        0.35 * (1 - math.exp(-evidence.lane_effective / 2.0))
        + 0.25 * (1 - math.exp(-evidence.total_loads / 5.0))
        + 0.2 * (1 - math.exp(-evidence.price_observations / 4.0))
        + 0.2 * (1 - math.exp(-evidence.reliability_observations / 4.0))
    )
    if raw >= 0.68:
        return "high"
    if raw >= 0.34:
        return "medium"
    return "low"


def _reasons(components: list[ComponentScore], evidence: CarrierEvidence, target: LoadVersion) -> list[str]:
    reasons = [
        f"{evidence.lane_effective:.1f} effective similar-lane loads",
        f"{evidence.total_loads} broker-local historical loads",
    ]
    positioning = _component(components, "positioning")
    if positioning.evidence.get("last_delivery_deadhead_miles") is not None:
        reasons.append(f"last known delivery is {positioning.evidence['last_delivery_deadhead_miles']} miles from pickup")
    price = _component(components, "price")
    reasons.append(f"shrunk price history is ${price.evidence['shrunk_ppm']}/mi vs ${price.evidence['prior_ppm']}/mi broker benchmark")
    if target.equipment != Equipment.UNKNOWN:
        reasons.append(f"equipment-compatible history for {target.equipment.value}")
    return reasons


def _limitations(evidence: CarrierEvidence, target: LoadVersion) -> list[str]:
    limitations = []
    if evidence.lane_effective < 1:
        limitations.append("low lane confidence: little direct or nearby-lane history")
    if evidence.reliability_observations < 3:
        limitations.append("limited reliability observations")
    if target.equipment == Equipment.UNKNOWN:
        limitations.append("target equipment is unknown, so equipment compatibility was not gated")
    elif not any(load.equipment == target.equipment for load in evidence.history):
        limitations.append(f"no {target.equipment.value} history for this carrier; equipment evidence is a fallback")
    if evidence.reverse_effective > evidence.direct_effective and evidence.direct_effective < 0.5:
        limitations.append("mostly reverse-lane evidence, discounted from direct lane evidence")
    return limitations


def _component(components: list[ComponentScore], name: str) -> ComponentScore:
    return next(component for component in components if component.name == name)


def _clip(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _round_optional(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
