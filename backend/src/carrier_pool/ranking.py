from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from .geo import GeoIndex
from .models import CanonicalStore, CarrierRanking, ComponentScore, Equipment, LoadStatus, LoadVersion
from .pricing import PriceEstimate, estimate_carrier_price, estimate_price, lane_weight as weighted_lane_weight

WEIGHTS = {
    "positioning": 0.30,
    "lane_familiarity": 0.24,
    "price": 0.16,
    "reliability": 0.12,
    "relationship": 0.10,
    "customer_affinity": 0.04,
    "stability": 0.04,
}

# Empty miles are only meaningful against the loaded miles the carrier gets paid for, so
# deadhead is scored on both scales and judged by the kinder of the two: 165 empty miles is
# routine on a 1,200-mile run and ruinous on a 209-mile one, while 40 empty miles is cheap
# on any load even though it is a large fraction of a short drayage move.
DEADHEAD_FREE_MILES = 45.0
DEADHEAD_FREE_RATIO = 0.15
DEADHEAD_MILES_DECAY = 90.0
DEADHEAD_RATIO_DECAY = 0.30

# A carrier's next available truck is not necessarily at its last recorded delivery. A
# shuttle running New Braunfels->Pasadena every day is near New Braunfels about half the
# time, so the operating footprint softly minimises distance over every recent stop. The
# last delivery is trusted in proportion to how fresh it is and the footprint carries the
# rest, which keeps a same-day position authoritative without letting a week-old one pose
# as the truck's current location.
POSITION_SOFTMIN_MILES = 40.0
POSITION_RECENCY_HALFLIFE_DAYS = 4.0
UNKNOWN_POSITION_SCORE = 0.35

# The last delivery is observed; the footprint is an inference about a repositioning move
# nobody recorded, and for a one-directional shuttle that move is itself unpaid deadhead the
# carrier has to absorb. So the inference is capped: it can pull the estimate halfway toward
# the carrier's usual area but never further, and a stale drop always keeps half the say.
POSITION_MAX_FOOTPRINT_WEIGHT = 0.5

# Freshness answers "is this position still true"; shrinkage answers "is one drop enough to
# believe". They are different uncertainties and both apply. One six-day-old delivery and
# eight consistent ones pointing at the same town are not the same evidence that a truck can
# be had near the pickup tomorrow, so positioning shrinks toward the unknown-position prior
# like every other component does (see DECISIONS 5). With no observations at all the formula
# collapses to the prior, so the unknown case needs no separate branch.
POSITION_PRIOR_OBSERVATIONS = 2.0


@dataclass(frozen=True)
class PositionEstimate:
    """Where this carrier's equipment is likely to be when the load needs covering."""

    expected_deadhead_miles: float | None
    last_delivery_deadhead_miles: float | None
    footprint_deadhead_miles: float | None
    staleness_days: float | None
    freshness: float
    observations: int
    basis: str


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
    position: PositionEstimate
    correction_count: int
    fallthrough_count: int


def rank_carriers(store: CanonicalStore, target: LoadVersion, geo: GeoIndex | None = None, as_of: datetime | None = None) -> list[CarrierRanking]:
    geo = geo or GeoIndex.bundled()
    as_of = as_of or target.synced_at
    history = _broker_history(store, target, as_of)
    candidate_ids = _candidate_ids(history, target)
    market_price = estimate_price(store, target, geo, as_of=as_of)
    fallthroughs = _fallthrough_counts(store, target.broker_id, as_of)
    corrections = _correction_counts(store, target.broker_id, as_of)
    rankings: list[CarrierRanking] = []

    for carrier_id in candidate_ids:
        carrier_history = [load for load in history if load.carrier_id == carrier_id]
        evidence = _evidence(carrier_id, carrier_history, target, geo, as_of, corrections.get(carrier_id, 0), fallthroughs.get(carrier_id, 0))
        carrier_price = estimate_carrier_price(store, target, carrier_id, geo, as_of=as_of, market_prior=market_price.point_ppm)
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


def _broker_history(store: CanonicalStore, target: LoadVersion, as_of: datetime) -> list[LoadVersion]:
    return [
        load
        for load in store.loads_as_of(target.broker_id, as_of)
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


def _evidence(carrier_id: str, history: list[LoadVersion], target: LoadVersion, geo: GeoIndex, as_of: datetime, correction_count: int, fallthrough_count: int) -> CarrierEvidence:
    weighted = [lane_weight(target, load, geo) for load in history]
    lane_effective = sum(item[0] for item in weighted)
    direct_effective = sum(item[1] for item in weighted)
    reverse_effective = sum(item[2] for item in weighted)
    target_time = as_of
    recent_loads = sum(1 for load in history if load.updated_at and (target_time - load.updated_at).days <= 21)
    reliability_observations = sum(len(_reliability_events(load)) for load in history)
    price_observations = sum(1 for load in history if load.carrier_rate_usd and load.distance_miles > 0)
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
        position=_position_estimate(history, target, geo, target_time),
        correction_count=correction_count,
        fallthrough_count=fallthrough_count,
    )


def _position_estimate(history: list[LoadVersion], target: LoadVersion, geo: GeoIndex, as_of: datetime) -> PositionEstimate:
    """Estimate the empty miles this carrier would run to reach the target pickup.

    Two readings are combined. The last recorded delivery says where a truck actually was,
    which is decisive when it is recent and worthless when it is a week old. The operating
    footprint is a recency-weighted soft minimum over every recent stop, which captures the
    repeating rotations that dominate this business: a carrier that keeps originating loads
    near the pickup will have equipment back there regardless of where it last dropped.
    """
    reference = target.pickup_open_at or as_of
    weighted_positions: list[tuple[float, float]] = []
    last_delivery_at: datetime | None = None
    last_delivery_miles: float | None = None
    observations = 0

    for load in history:
        delivered_at = _delivery_known_at(load)
        if delivered_at is None or delivered_at > as_of:
            continue
        observations += 1
        age_days = max(0.0, (reference - delivered_at).total_seconds() / 86400.0)
        weight = 0.5 ** (age_days / POSITION_RECENCY_HALFLIFE_DAYS)
        # Both stops count as places this carrier's equipment passes through. The pickup is
        # strictly older than the delivery, but for a repeating rotation what matters is
        # that the carrier is present in that area, not the exact hour it was there.
        for zip_code in (load.delivery.zip_code, load.pickup.zip_code):
            miles = geo.miles(zip_code, target.pickup.zip_code)
            if not math.isinf(miles):
                weighted_positions.append((weight, miles))
        if last_delivery_at is None or delivered_at > last_delivery_at:
            delivery_miles = geo.miles(load.delivery.zip_code, target.pickup.zip_code)
            last_delivery_at = delivered_at
            # An unlocatable ZIP leaves the position unknown rather than infinitely far.
            last_delivery_miles = None if math.isinf(delivery_miles) else delivery_miles

    footprint_miles = _soft_min_miles(weighted_positions)
    staleness_days = max(0.0, (reference - last_delivery_at).total_seconds() / 86400.0) if last_delivery_at else None
    freshness = 0.5 ** (staleness_days / POSITION_RECENCY_HALFLIFE_DAYS) if staleness_days is not None else 0.0

    if last_delivery_miles is None and footprint_miles is None:
        return PositionEstimate(None, None, None, staleness_days, 0.0, observations, "unknown")
    if last_delivery_miles is None:
        return PositionEstimate(footprint_miles, None, footprint_miles, staleness_days, 0.0, observations, "operating_footprint")
    if footprint_miles is None:
        return PositionEstimate(last_delivery_miles, last_delivery_miles, None, staleness_days, freshness, observations, "last_delivery")

    footprint_weight = min(POSITION_MAX_FOOTPRINT_WEIGHT, 1 - freshness)
    expected = (1 - footprint_weight) * last_delivery_miles + footprint_weight * footprint_miles
    basis = "last_delivery" if footprint_weight < 0.2 else "blended"
    return PositionEstimate(expected, last_delivery_miles, footprint_miles, staleness_days, freshness, observations, basis)


def _soft_min_miles(weighted_positions: list[tuple[float, float]]) -> float | None:
    """Recency-weighted soft minimum over candidate positions.

    A hard minimum would let one ancient stop near the pickup claim the carrier is parked
    there forever; a mean would drown a genuinely close truck in the carrier's other work.
    """
    total_weight = sum(weight for weight, _ in weighted_positions)
    if total_weight <= 0:
        return None
    decayed = sum(weight * math.exp(-miles / POSITION_SOFTMIN_MILES) for weight, miles in weighted_positions) / total_weight
    if decayed <= 0:
        return None
    return -POSITION_SOFTMIN_MILES * math.log(decayed)


def _deadhead_score(deadhead_miles: float, loaded_miles: float) -> float:
    """Score empty miles on both an absolute and a paid-distance-relative scale."""
    absolute_excess = max(0.0, deadhead_miles - DEADHEAD_FREE_MILES)
    absolute_score = math.exp(-absolute_excess / DEADHEAD_MILES_DECAY)
    if loaded_miles <= 0:
        return absolute_score
    ratio_excess = max(0.0, (deadhead_miles / loaded_miles) - DEADHEAD_FREE_RATIO)
    ratio_score = math.exp(-ratio_excess / DEADHEAD_RATIO_DECAY)
    # The kinder of the two scales wins so that neither a short haul nor a long one is
    # punished by a metric that does not apply to it.
    return max(absolute_score, ratio_score)


def _components(evidence: CarrierEvidence, history: list[LoadVersion], target: LoadVersion, geo: GeoIndex, carrier_price: PriceEstimate, market_price: PriceEstimate) -> list[ComponentScore]:
    lane_score = 1 - math.exp(-evidence.lane_effective / 2.0)
    positioning_score = _positioning_score(evidence.position, target)
    price_score, price_evidence = _price_score(carrier_price, market_price, evidence.position, target)
    reliability_score = _reliability_score(history)
    relationship_score = min(1.0, 0.55 * (1 - math.exp(-evidence.total_loads / 5.0)) + 0.45 * (1 - math.exp(-evidence.recent_loads / 2.0)))
    customer_score = _customer_score(history, target)
    stability_score = max(0.0, 1.0 - 0.18 * evidence.correction_count - 0.28 * evidence.fallthrough_count)
    return [
        ComponentScore("positioning", _clip(positioning_score), WEIGHTS["positioning"], _position_evidence(evidence.position, target, history, geo)),
        ComponentScore("lane_familiarity", _clip(lane_score), WEIGHTS["lane_familiarity"], {"effective_loads": round(evidence.lane_effective, 2), "direct": round(evidence.direct_effective, 2), "reverse": round(evidence.reverse_effective, 2)}),
        ComponentScore("price", _clip(price_score), WEIGHTS["price"], price_evidence),
        ComponentScore("reliability", _clip(reliability_score), WEIGHTS["reliability"], {"observations": evidence.reliability_observations, "measures": _reliability_measures(history)}),
        ComponentScore("relationship", _clip(relationship_score), WEIGHTS["relationship"], {"total_loads": evidence.total_loads, "recent_loads": evidence.recent_loads}),
        ComponentScore("customer_affinity", _clip(customer_score), WEIGHTS["customer_affinity"], {"same_customer_loads": sum(1 for load in history if load.customer_id == target.customer_id)}),
        ComponentScore("stability", _clip(stability_score), WEIGHTS["stability"], {"corrections": evidence.correction_count, "fallthroughs": evidence.fallthrough_count}),
    ]


def _positioning_score(position: PositionEstimate, target: LoadVersion) -> float:
    raw = UNKNOWN_POSITION_SCORE if position.expected_deadhead_miles is None else _deadhead_score(position.expected_deadhead_miles, target.distance_miles)
    supported = position.observations if position.expected_deadhead_miles is not None else 0
    return (supported * raw + POSITION_PRIOR_OBSERVATIONS * UNKNOWN_POSITION_SCORE) / (supported + POSITION_PRIOR_OBSERVATIONS)


def _position_evidence(position: PositionEstimate, target: LoadVersion, history: list[LoadVersion], geo: GeoIndex) -> dict[str, float | int | str | None]:
    """Everything geographic the broker needs to audit the deadhead estimate.

    How often a carrier works near the pickup is reported here rather than scored as its own
    component. It already shapes the estimate through the operating footprint, so paying for
    it a second time is what let a badly positioned shuttle carrier refund its own penalty.
    """
    expected = position.expected_deadhead_miles
    ratio = expected / target.distance_miles if expected is not None and target.distance_miles > 0 else None
    return {
        "expected_deadhead_miles": _round_optional(expected),
        "deadhead_ratio": round(ratio, 3) if ratio is not None else None,
        "last_delivery_deadhead_miles": _round_optional(position.last_delivery_deadhead_miles),
        "footprint_deadhead_miles": _round_optional(position.footprint_deadhead_miles),
        "position_age_days": _round_optional(position.staleness_days),
        "position_observations": position.observations,
        "pickups_within_50mi": sum(1 for load in history if geo.miles(load.pickup.zip_code, target.pickup.zip_code) <= 50.0),
        "basis": position.basis,
    }


def _price_score(carrier_price: PriceEstimate, market_price: PriceEstimate, position: PositionEstimate, target: LoadVersion) -> tuple[float, dict[str, float | int | str]]:
    relative = (market_price.point_ppm - carrier_price.point_ppm) / market_price.point_ppm if market_price.point_ppm else 0.0
    score = 0.5 + relative * 2.2
    evidence: dict[str, float | int | str] = {
        "observed_ppm": carrier_price.observed_ppm,
        "shrunk_ppm": carrier_price.point_ppm,
        "prior_ppm": market_price.point_ppm,
        "price_effective_loads": carrier_price.effective_loads,
        "basis": carrier_price.basis,
        "point_usd": carrier_price.point_usd,
    }
    # What the carrier actually earns per mile it turns. The quoted rate only covers loaded
    # miles, so a badly positioned truck is being offered less than the headline suggests,
    # which is why it is the one most likely to decline or ask for more.
    all_in = _all_in_ppm(carrier_price.point_usd, position.expected_deadhead_miles, target.distance_miles)
    if all_in is not None:
        evidence["all_in_ppm_with_deadhead"] = all_in
    return score, evidence


def _all_in_ppm(point_usd: float, deadhead_miles: float | None, loaded_miles: float) -> float | None:
    if deadhead_miles is None or loaded_miles <= 0:
        return None
    total_miles = loaded_miles + max(0.0, deadhead_miles)
    return round(point_usd / total_miles, 2) if total_miles > 0 else None


def _reliability_score(history: list[LoadVersion]) -> float:
    successes = 3.0
    observations = 4.0
    for load in history:
        for actual, close_at, _measure in _reliability_events(load):
            observations += 1
            successes += 1 if actual <= close_at else 0
    return successes / observations


def _reliability_events(load: LoadVersion) -> list[tuple[datetime, datetime, str]]:
    events = []
    if load.pickup_arrived_at and load.pickup_close_at:
        events.append((load.pickup_arrived_at, load.pickup_close_at, "pickup_arrival"))
    if load.pickup_departed_at and load.pickup_close_at:
        events.append((load.pickup_departed_at, load.pickup_close_at, "pickup_departure"))
    if load.delivery_arrived_at and load.delivery_close_at:
        events.append((load.delivery_arrived_at, load.delivery_close_at, "delivery_arrival"))
    if load.delivery_departed_at and load.delivery_close_at:
        events.append((load.delivery_departed_at, load.delivery_close_at, "delivery_departure"))
    return events


def _reliability_measures(history: list[LoadVersion]) -> str:
    measures = Counter(measure for load in history for _actual, _close_at, measure in _reliability_events(load))
    return ",".join(f"{measure}:{count}" for measure, count in sorted(measures.items()))


def _delivery_known_at(load: LoadVersion) -> datetime | None:
    return load.delivery_departed_at or load.delivery_arrived_at


def _customer_score(history: list[LoadVersion], target: LoadVersion) -> float:
    same = sum(1 for load in history if load.customer_id == target.customer_id)
    return (same + 1.0) / (same + 6.0)


def _fallthrough_counts(store: CanonicalStore, broker_id: str, as_of: datetime) -> Counter[str]:
    counts: Counter[str] = Counter()
    by_load: dict[str, list[LoadVersion]] = defaultdict(list)
    for version in store.versions:
        if version.broker_id == broker_id and version.synced_at <= as_of:
            by_load[version.raw_load_id].append(version)
    for versions in by_load.values():
        previous = None
        for version in sorted(versions, key=lambda item: item.updated_at or datetime.min.replace(tzinfo=timezone.utc)):
            if previous and version.carrier_id and previous != version.carrier_id:
                counts[previous] += 1
            if version.carrier_id:
                previous = version.carrier_id
    return counts


def _correction_counts(store: CanonicalStore, broker_id: str, as_of: datetime) -> Counter[str]:
    counts: Counter[str] = Counter()
    by_load: dict[str, list[LoadVersion]] = defaultdict(list)
    for version in store.versions:
        if version.broker_id == broker_id and version.synced_at <= as_of:
            by_load[version.raw_load_id].append(version)

    for versions in by_load.values():
        previous_rate = None
        previous_carrier = None
        for version in sorted(versions, key=lambda item: item.updated_at or datetime.min.replace(tzinfo=timezone.utc)):
            if version.carrier_rate_usd is None:
                continue
            adjusted = float(version.raw.get("_rate_adjustment_abs", 0.0) or 0.0) > 0.0
            rate_changed = previous_rate is not None and not math.isclose(version.carrier_rate_usd, previous_rate)
            carrier_changed = previous_carrier is not None and version.carrier_id is not None and previous_carrier != version.carrier_id
            if version.carrier_id and not carrier_changed and (rate_changed or adjusted):
                counts[version.carrier_id] += 1
            if version.carrier_id:
                previous_carrier = version.carrier_id
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
    position = evidence.position
    if position.expected_deadhead_miles is not None:
        ratio = position.expected_deadhead_miles / target.distance_miles if target.distance_miles > 0 else None
        share = f" ({ratio:.0%} of the loaded miles)" if ratio is not None else ""
        reasons.append(f"expected deadhead is {position.expected_deadhead_miles:.0f} miles{share}")
        superseded = (
            position.basis != "last_delivery"
            and position.last_delivery_deadhead_miles is not None
            and position.footprint_deadhead_miles is not None
            and position.last_delivery_deadhead_miles - position.footprint_deadhead_miles > 25
        )
        if superseded:
            reasons.append(
                f"last delivery was {position.last_delivery_deadhead_miles:.0f} miles out but is {position.staleness_days:.0f} days stale, "
                f"and this carrier routinely works within {position.footprint_deadhead_miles:.0f} miles of the pickup"
            )
    price = _component(components, "price")
    reasons.append(f"shrunk price history is ${price.evidence['shrunk_ppm']}/mi vs ${price.evidence['prior_ppm']}/mi broker benchmark")
    if target.equipment != Equipment.UNKNOWN:
        reasons.append(f"equipment-compatible history for {target.equipment.value}")
    return reasons


def _limitations(evidence: CarrierEvidence, target: LoadVersion) -> list[str]:
    limitations = []
    position = evidence.position
    expected = position.expected_deadhead_miles
    if expected is None:
        limitations.append("no delivery actuals for this carrier, so its position is unknown")
    elif target.distance_miles > 0 and expected / target.distance_miles > DEADHEAD_FREE_RATIO * 2:
        limitations.append(
            f"expects {expected:.0f} empty miles against {target.distance_miles:.0f} loaded, "
            f"so this carrier turns fewer paid miles than the rate implies and may push back on price"
        )
    if position.staleness_days is not None and position.staleness_days > POSITION_RECENCY_HALFLIFE_DAYS * 2:
        limitations.append(f"last known position is {position.staleness_days:.0f} days old")
    if expected is not None and position.observations < 3:
        plural = "delivery" if position.observations == 1 else "deliveries"
        limitations.append(
            f"empty miles are estimated from only {position.observations} recorded {plural}, "
            f"so this carrier may not have a truck free near the pickup"
        )
    if evidence.lane_effective < 1:
        limitations.append("low lane confidence: little direct or nearby-lane history")
    if evidence.reliability_observations < 3:
        limitations.append("limited reliability observations")
    measures = {measure for load in evidence.history for _actual, _close_at, measure in _reliability_events(load)}
    if measures and all("arrival" in measure for measure in measures):
        limitations.append("reliability is based on arrival timestamps only for this broker")
    elif measures and all("departure" in measure for measure in measures):
        limitations.append("reliability is based on departure timestamps only for this broker")
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
