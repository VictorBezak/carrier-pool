"""Lane price estimation: what this load should cost.

Shared by every engine, because "what is this lane worth" is a property of the
broker's history rather than of any particular ranking strategy. The
expected-value engine also uses it as the yardstick that makes offers on
different loads comparable - a $1,000 offer means something different on a
200-mile dry van run than on a 400-mile reefer.

The method is a median of comparables with a widening definition of comparable.
It is deliberately simple; what makes it usable is that it always states which
definition it fell back to and shows the loads it used.
"""

from __future__ import annotations

from statistics import median

from ..domain import Equipment, Load
from ..history import BrokerHistory
from .contracts import Comparable, Confidence, PriceEstimate, Reason

MIN_COMPARABLES = 3

BASIS_LABELS = {
    "LANE_EQUIPMENT": "this lane, same trailer type",
    "LANE": "this lane, any trailer type",
    "ORIGIN_EQUIPMENT": "loads out of this pickup market, same trailer type",
    "ORIGIN": "loads out of this pickup market",
    "BROKER": "all of this broker's priced loads",
}


def estimate_price(load: Load, history: BrokerHistory) -> PriceEstimate | None:
    miles = load.distance_miles
    if not miles:
        return None

    levels = _comparable_levels(load, history)
    narrowest = levels[0][0]

    for basis, comparables in levels:
        if len(comparables) >= MIN_COMPARABLES:
            return _build_estimate(basis, narrowest, comparables, miles)

    # Nothing reached the minimum. Rather than refuse to answer, use the
    # narrowest non-empty set and be explicit that it is thin.
    for basis, comparables in levels:
        if comparables:
            return _build_estimate(basis, narrowest, comparables, miles)
    return None


def market_rate_per_mile(history: BrokerHistory, equipment: Equipment) -> float | None:
    """The broker's own going rate for this trailer type.

    Used to put offers across different loads on one scale. Derived from booked
    loads rather than a constant, so it reflects what this broker actually pays
    rather than what a rate index says the market is.
    """
    rates = [
        load.carrier_rate_per_mile
        for load in history.priced_loads
        if load.carrier_rate_per_mile
        and (equipment is Equipment.UNKNOWN or load.equipment == equipment)
    ]
    if not rates:
        rates = [load.carrier_rate_per_mile for load in history.priced_loads if load.carrier_rate_per_mile]
    return round(median(rates), 4) if rates else None


def _comparable_levels(load: Load, history: BrokerHistory) -> list[tuple[str, list[Load]]]:
    """Comparable sets from narrowest to widest.

    This is the answer to "where does a price come from when the exact lane
    is thin": widen the definition of comparable one step at a time and say
    out loud which step was used.

    When the load has no equipment type, the trailer-qualified levels are
    dropped rather than allowed to quietly match everything - otherwise the
    estimate would claim comparables were "the same trailer type" when no
    trailer type was ever known.
    """
    exclude = {load.load_id}
    known_equipment = load.equipment is not Equipment.UNKNOWN

    def usable(loads: list[Load]) -> list[Load]:
        return [item for item in loads if item.load_id not in exclude]

    levels: list[tuple[str, list[Load]]] = []
    if known_equipment:
        levels.append(
            ("LANE_EQUIPMENT", usable(history.lane_loads(lane=load.lane, equipment=load.equipment)))
        )
    levels.append(("LANE", usable(history.lane_loads(lane=load.lane))))
    if known_equipment:
        levels.append(
            (
                "ORIGIN_EQUIPMENT",
                usable(history.lane_loads(origin_market=load.origin_market, equipment=load.equipment)),
            )
        )
    levels.append(("ORIGIN", usable(history.lane_loads(origin_market=load.origin_market))))
    levels.append(("BROKER", usable(history.priced_loads)))
    return levels


def _build_estimate(
    basis: str, narrowest: str, comparables: list[Load], miles: float
) -> PriceEstimate:
    rates = sorted(item.carrier_rate_per_mile for item in comparables if item.carrier_rate_per_mile)
    centre = median(rates)
    low_rate, high_rate = _spread(rates, centre)
    sample = len(rates)

    if basis in ("LANE_EQUIPMENT", "LANE") and sample >= 5:
        confidence: Confidence = "high"
    elif sample >= MIN_COMPARABLES:
        confidence = "medium"
    else:
        confidence = "low"

    basis_label = BASIS_LABELS[basis]
    reasons = [
        Reason(
            label="Where this came from",
            detail=(
                f"Median of {sample} past load{'s' if sample != 1 else ''} priced on "
                f"{basis_label}, at ${centre:.2f} per mile over {miles:g} miles."
            ),
            sentiment="neutral",
        )
    ]
    if basis == narrowest:
        reasons.append(
            Reason(
                label="Closest possible match",
                detail=f"Every comparable is drawn from {basis_label}, the tightest set available.",
                sentiment="positive",
            )
        )
    else:
        reasons.append(
            Reason(
                label="Had to widen the comparison",
                detail=(
                    f"Fewer than {MIN_COMPARABLES} priced loads exist on {BASIS_LABELS[narrowest]}, "
                    f"so the comparison was widened to {basis_label}."
                ),
                sentiment="negative" if basis == "BROKER" else "neutral",
            )
        )
    if sample < MIN_COMPARABLES:
        reasons.append(
            Reason(
                label="Very little to go on",
                detail=(
                    f"Only {sample} comparable load{'s' if sample != 1 else ''} exists at any "
                    f"level of similarity. Treat this as a starting point, not a benchmark."
                ),
                sentiment="negative",
            )
        )
    spread = (high_rate - low_rate) / centre if centre else 0
    if spread > 0.2:
        reasons.append(
            Reason(
                label="Rates vary a lot here",
                detail=(
                    f"Comparable rates run from ${low_rate:.2f} to ${high_rate:.2f} per mile, "
                    "so the lane is not priced consistently."
                ),
                sentiment="negative",
            )
        )

    return PriceEstimate(
        point_usd=round(centre * miles / 5) * 5.0,
        low_usd=round(low_rate * miles / 5) * 5.0,
        high_usd=round(high_rate * miles / 5) * 5.0,
        rate_per_mile=round(centre, 3),
        basis=basis,
        basis_label=basis_label,
        sample_size=sample,
        confidence=confidence,
        reasons=reasons,
        comparables=[
            Comparable(
                load_id=item.load_id,
                source_ref=item.source_ref,
                reference=item.reference,
                lane_label=item.lane_label,
                equipment=item.equipment,
                carrier_name=item.carrier_name,
                distance_miles=item.distance_miles,
                carrier_rate=item.carrier_rate,
                rate_per_mile=item.carrier_rate_per_mile,
                delivered_at=item.delivered_at,
            )
            for item in sorted(comparables, key=lambda item: item.carrier_rate_per_mile or 0)
        ],
    )


def _spread(rates: list[float], centre: float) -> tuple[float, float]:
    """A quartile band where there is enough data for quartiles to mean
    anything, and an honest flat band where there is not."""
    if len(rates) >= 4:
        lower = rates[: len(rates) // 2]
        upper = rates[(len(rates) + 1) // 2 :]
        return median(lower), median(upper)
    if len(rates) >= 2:
        return rates[0], rates[-1]
    return round(centre * 0.9, 3), round(centre * 1.1, 3)
