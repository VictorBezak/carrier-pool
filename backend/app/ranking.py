"""Carrier ranking and price estimation.

**This is the deliberately simple version.** It is a weighted sum of five
transparent signals plus a median-of-comparables price. It is not clever, and
it is not meant to be - it exists so the ingestion, tenancy, API and UI can be
built and judged against a real answer shape, and then have the scoring swapped
out underneath them.

The part that is meant to survive the swap is the *contract*:

- every score is decomposed into named components with explicit weights, so the
  number is always attributable;
- every recommendation carries reasons written for a human dispatcher, not a
  debug log;
- every price carries its basis, its sample size and the actual comparable loads
  it came from, so a broker can check the work.

A replacement engine implements `RecommendationEngine` and gets registered in
`ENGINES`. Nothing else in the codebase should need to change.

Known weaknesses of *this* engine, stated rather than hidden:

- `relationship_depth` structurally favours incumbents: a carrier with one
  excellent load can not out-score a carrier with five mediocre ones. Each
  recommendation therefore carries `history_depth` so the UI can mark thin
  evidence instead of quietly presenting it as equivalent.
- Lane matching is a binary market-pair test. Neighbouring markets contribute
  nothing, so a Dallas->Austin veteran gets no credit for a Dallas->Georgetown
  load beyond the shared origin.
- Nothing here models price *quality*: a carrier is not rewarded for having been
  cheap, only for having been present.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from . import geo
from .domain import Equipment, Load
from .history import BrokerHistory, CarrierLaneHistory

Sentiment = Literal["positive", "neutral", "negative"]
Confidence = Literal["high", "medium", "low"]


class Reason(BaseModel):
    """One human-readable justification. `points` is how much this contributed
    to the score, so the explanation and the arithmetic cannot drift apart."""

    label: str
    detail: str
    sentiment: Sentiment
    points: float | None = None


class ScoreComponent(BaseModel):
    key: str
    label: str
    weight: float
    value: float
    points: float


class HistoryDepth(BaseModel):
    """How much evidence is behind a score, kept separate from the score itself
    so that "confident yes" and "hopeful guess" do not look identical."""

    loads_total: int
    loads_on_lane: int
    label: str
    is_thin: bool


class CarrierRecommendation(BaseModel):
    rank: int
    carrier_id: str
    carrier_name: str
    mc_number: str | None = None
    phone: str | None = None
    score: float
    components: list[ScoreComponent]
    reasons: list[Reason]
    history_depth: HistoryDepth
    loads_total: int
    loads_on_lane: int
    days_since_last_load: float | None
    last_delivery_market_label: str | None
    median_lane_rate_per_mile: float | None
    suggested_rate_usd: float | None


class Comparable(BaseModel):
    """A past load the estimate is standing on. Present so the number can be
    audited by hand."""

    load_id: str
    # BrokerOS's human-readable load number is not its record ID, so the UI needs
    # the ref that actually addresses the load as well as the one to display.
    source_ref: str
    reference: str
    lane_label: str
    equipment: Equipment
    carrier_name: str | None
    distance_miles: float | None
    carrier_rate: float | None
    rate_per_mile: float | None
    delivered_at: datetime | None


class PriceEstimate(BaseModel):
    point_usd: float
    low_usd: float
    high_usd: float
    rate_per_mile: float
    basis: str
    basis_label: str
    sample_size: int
    confidence: Confidence
    reasons: list[Reason]
    comparables: list[Comparable]


class EngineInfo(BaseModel):
    key: str
    name: str
    version: str
    description: str


class Recommendations(BaseModel):
    load_id: str
    lane: str
    lane_label: str
    engine: EngineInfo
    generated_at: datetime
    as_of: datetime
    price_estimate: PriceEstimate | None
    carriers: list[CarrierRecommendation]
    carriers_considered: int
    notes: list[str] = Field(default_factory=list)


class RecommendationEngine(Protocol):
    info: EngineInfo

    def recommend(self, load: Load, history: BrokerHistory, limit: int) -> Recommendations: ...


# --------------------------------------------------------------------------
# v1: transparent weighted heuristic
# --------------------------------------------------------------------------

WEIGHTS: dict[str, tuple[str, float]] = {
    "lane_experience": ("Lane experience", 0.40),
    "equipment_fit": ("Equipment fit", 0.20),
    "recency": ("Recently active", 0.15),
    "relationship_depth": ("Relationship depth", 0.15),
    "repositioning": ("Easy repositioning", 0.10),
}

# Number of loads on a lane past which more history stops adding confidence.
LANE_SATURATION = 3
RELATIONSHIP_SATURATION = 5
MIN_COMPARABLES = 3

_BASIS_LABELS = {
    "LANE_EQUIPMENT": "this lane, same trailer type",
    "LANE": "this lane, any trailer type",
    "ORIGIN_EQUIPMENT": "loads out of this pickup market, same trailer type",
    "ORIGIN": "loads out of this pickup market",
    "BROKER": "all of this broker's priced loads",
}


class SimpleHeuristicEngine:
    info = EngineInfo(
        key="simple-heuristic",
        name="Transparent weighted heuristic",
        version="1.0",
        description=(
            "Weighted sum of lane experience, equipment fit, recency, relationship depth and "
            "repositioning. Price is the median rate per mile of the narrowest comparable set "
            "with enough loads in it."
        ),
    )

    def recommend(self, load: Load, history: BrokerHistory, limit: int = 10) -> Recommendations:
        notes: list[str] = []
        if load.origin_market == geo.UNKNOWN_MARKET or load.destination_market == geo.UNKNOWN_MARKET:
            notes.append(
                "This load's pickup or delivery could not be resolved to a known market, so lane "
                "history is unreliable for it."
            )
        if load.equipment is Equipment.UNKNOWN:
            notes.append(
                "The source TMS did not record an equipment type. Trailer fit was scored as "
                "unknown rather than assumed to be a dry van."
            )

        scored: list[CarrierRecommendation] = []
        considered = 0
        estimate = self.estimate_price(load, history)

        for carrier in history.carriers:
            carrier_history = history.carrier_history_for(carrier.carrier_id, load)
            if carrier_history is None:
                # Known to the broker but never booked: nothing to reason from.
                continue
            considered += 1
            scored.append(self._score_carrier(load, carrier_history, estimate))

        scored.sort(key=lambda item: (-item.score, -item.loads_on_lane, item.carrier_name))
        for index, recommendation in enumerate(scored[:limit], start=1):
            recommendation.rank = index

        return Recommendations(
            load_id=load.load_id,
            lane=load.lane,
            lane_label=load.lane_label,
            engine=self.info,
            generated_at=datetime.now(timezone.utc),
            as_of=history.as_of,
            price_estimate=estimate,
            carriers=scored[:limit],
            carriers_considered=considered,
            notes=notes,
        )

    # ---- carrier scoring ----------------------------------------------

    def _score_carrier(
        self,
        load: Load,
        carrier_history: CarrierLaneHistory,
        estimate: PriceEstimate | None,
    ) -> CarrierRecommendation:
        components: list[ScoreComponent] = []
        reasons: list[Reason] = []

        for key, (value, reason) in self._signals(load, carrier_history).items():
            label, weight = WEIGHTS[key]
            points = round(weight * value * 100, 1)
            components.append(
                ScoreComponent(key=key, label=label, weight=weight, value=round(value, 3), points=points)
            )
            reason.points = points
            reasons.append(reason)

        score = round(sum(component.points for component in components), 1)
        reasons.sort(key=lambda item: -(item.points or 0))

        carrier = carrier_history.carrier
        suggested = None
        if estimate is not None:
            suggested = self._suggested_rate(load, carrier_history, estimate)

        return CarrierRecommendation(
            rank=0,
            carrier_id=carrier.carrier_id,
            carrier_name=carrier.name,
            mc_number=carrier.mc_number,
            phone=carrier.phone,
            score=score,
            components=components,
            reasons=reasons,
            history_depth=self._history_depth(carrier_history),
            loads_total=carrier_history.loads_total,
            loads_on_lane=carrier_history.loads_on_lane,
            days_since_last_load=carrier_history.days_since_last_load,
            last_delivery_market_label=(
                geo.market_label(carrier_history.last_delivery_market)
                if carrier_history.last_delivery_market
                else None
            ),
            median_lane_rate_per_mile=carrier_history.median_lane_rate_per_mile,
            suggested_rate_usd=suggested,
        )

    def _signals(
        self, load: Load, hist: CarrierLaneHistory
    ) -> dict[str, tuple[float, Reason]]:
        return {
            "lane_experience": self._lane_experience(load, hist),
            "equipment_fit": self._equipment_fit(load, hist),
            "recency": self._recency(hist),
            "relationship_depth": self._relationship_depth(hist),
            "repositioning": self._repositioning(load, hist),
        }

    @staticmethod
    def _lane_experience(load: Load, hist: CarrierLaneHistory) -> tuple[float, Reason]:
        origin_label = geo.market_label(load.origin_market)
        if hist.loads_on_lane:
            value = min(1.0, hist.loads_on_lane / LANE_SATURATION)
            plural = "s" if hist.loads_on_lane != 1 else ""
            return value, Reason(
                label="Knows this lane",
                detail=(
                    f"Has run {hist.loads_on_lane} load{plural} on {load.lane_label} for this "
                    f"broker."
                ),
                sentiment="positive",
            )
        if hist.loads_from_origin:
            plural = "s" if hist.loads_from_origin != 1 else ""
            return 0.35, Reason(
                label="Knows the pickup area",
                detail=(
                    f"No history on {load.lane_label}, but {hist.loads_from_origin} load{plural} "
                    f"picked up in {origin_label}."
                ),
                sentiment="neutral",
            )
        return 0.0, Reason(
            label="New to this lane",
            detail=f"No loads on {load.lane_label} and none out of {origin_label}.",
            sentiment="negative",
        )

    @staticmethod
    def _equipment_fit(load: Load, hist: CarrierLaneHistory) -> tuple[float, Reason]:
        if load.equipment is Equipment.UNKNOWN:
            return 0.5, Reason(
                label="Equipment unknown",
                detail="The load has no trailer type recorded, so equipment fit could not be checked.",
                sentiment="neutral",
            )
        equipment_label = load.equipment.value.replace("_", " ").lower()
        if hist.loads_with_equipment:
            plural = "s" if hist.loads_with_equipment != 1 else ""
            return 1.0, Reason(
                label="Right trailer",
                detail=f"Has hauled {hist.loads_with_equipment} {equipment_label} load{plural} for this broker.",
                sentiment="positive",
            )
        return 0.2, Reason(
            label="Unproven on this trailer",
            detail=f"Has never hauled a {equipment_label} load for this broker.",
            sentiment="negative",
        )

    @staticmethod
    def _recency(hist: CarrierLaneHistory) -> tuple[float, Reason]:
        days = hist.days_since_last_load
        if days is None:
            return 0.1, Reason(
                label="Last activity unknown",
                detail="No usable date on this carrier's past loads.",
                sentiment="neutral",
            )
        for threshold, value in ((2, 1.0), (5, 0.75), (10, 0.5), (20, 0.25)):
            if days <= threshold:
                return value, Reason(
                    label="Recently active",
                    detail=f"Last ran for this broker {days:g} days ago.",
                    sentiment="positive" if value >= 0.75 else "neutral",
                )
        return 0.1, Reason(
            label="Gone quiet",
            detail=f"Has not run for this broker in {days:g} days.",
            sentiment="negative",
        )

    @staticmethod
    def _relationship_depth(hist: CarrierLaneHistory) -> tuple[float, Reason]:
        value = min(1.0, hist.loads_total / RELATIONSHIP_SATURATION)
        plural = "s" if hist.loads_total != 1 else ""
        sentiment: Sentiment = "positive" if hist.loads_total >= 3 else "neutral"
        return value, Reason(
            label="Relationship depth",
            detail=f"{hist.loads_total} booked load{plural} with this broker in total.",
            sentiment=sentiment,
        )

    @staticmethod
    def _repositioning(load: Load, hist: CarrierLaneHistory) -> tuple[float, Reason]:
        origin = load.origin_market
        origin_label = geo.market_label(origin)

        if hist.last_delivery_market and hist.last_delivery_market == origin:
            return 1.0, Reason(
                label="Already in the area",
                detail=f"Its most recent load delivered into {origin_label}, so almost no deadhead.",
                sentiment="positive",
            )
        if hist.carrier.home_market and hist.carrier.home_market == origin:
            return 0.7, Reason(
                label="Based nearby",
                detail=f"Home base is in {origin_label}.",
                sentiment="positive",
            )
        if hist.last_delivery_market:
            miles = geo.market_distance_miles(hist.last_delivery_market, origin)
            last_label = geo.market_label(hist.last_delivery_market)
            if miles is not None:
                value = 0.5 if miles <= 100 else 0.2
                return value, Reason(
                    label="Needs to reposition",
                    detail=(
                        f"Its most recent load delivered into {last_label}, roughly {miles:g} "
                        f"deadhead miles from this pickup."
                    ),
                    sentiment="neutral" if value >= 0.5 else "negative",
                )
        return 0.2, Reason(
            label="Position unknown",
            detail="No usable record of where this carrier's truck last ended up.",
            sentiment="neutral",
        )

    @staticmethod
    def _history_depth(hist: CarrierLaneHistory) -> HistoryDepth:
        thin = hist.loads_total <= 1 or hist.loads_on_lane == 0
        if hist.loads_total <= 1:
            label = "Thin history: only one booked load ever"
        elif hist.loads_on_lane == 0:
            label = "No history on this exact lane"
        elif hist.loads_on_lane >= LANE_SATURATION:
            label = "Well established on this lane"
        else:
            label = "Some history on this lane"
        return HistoryDepth(
            loads_total=hist.loads_total,
            loads_on_lane=hist.loads_on_lane,
            label=label,
            is_thin=thin,
        )

    @staticmethod
    def _suggested_rate(load: Load, hist: CarrierLaneHistory, estimate: PriceEstimate) -> float:
        """What to open the call at.

        Where we know what this specific carrier has accepted on this lane
        before, blend it evenly with the lane estimate rather than trusting
        either alone: their own history is the more relevant number but is
        usually a much smaller sample.
        """
        own = hist.median_lane_rate_per_mile
        if own is None or not load.distance_miles:
            return estimate.point_usd
        blended = (own + estimate.rate_per_mile) / 2
        return round(blended * load.distance_miles / 5) * 5.0

    # ---- price estimation ---------------------------------------------

    def estimate_price(self, load: Load, history: BrokerHistory) -> PriceEstimate | None:
        miles = load.distance_miles
        if not miles:
            return None

        levels = self._comparable_levels(load, history)
        narrowest = levels[0][0]

        for basis, comparables in levels:
            if len(comparables) >= MIN_COMPARABLES:
                return self._build_estimate(basis, narrowest, comparables, miles)

        # Nothing reached the minimum. Rather than refuse to answer, use the
        # narrowest non-empty set and be explicit that it is thin.
        for basis, comparables in levels:
            if comparables:
                return self._build_estimate(basis, narrowest, comparables, miles)
        return None

    @staticmethod
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
        self, basis: str, narrowest: str, comparables: list[Load], miles: float
    ) -> PriceEstimate:
        rates = sorted(
            item.carrier_rate_per_mile for item in comparables if item.carrier_rate_per_mile
        )
        centre = median(rates)
        low_rate, high_rate = self._spread(rates, centre)
        sample = len(rates)

        if basis in ("LANE_EQUIPMENT", "LANE") and sample >= 5:
            confidence: Confidence = "high"
        elif sample >= MIN_COMPARABLES:
            confidence = "medium"
        else:
            confidence = "low"

        basis_label = _BASIS_LABELS[basis]
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
                        f"Fewer than {MIN_COMPARABLES} priced loads exist on {_BASIS_LABELS[narrowest]}, "
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
                for item in sorted(
                    comparables, key=lambda item: item.carrier_rate_per_mile or 0
                )
            ],
        )

    @staticmethod
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


ENGINES: dict[str, RecommendationEngine] = {
    SimpleHeuristicEngine.info.key: SimpleHeuristicEngine(),
}

DEFAULT_ENGINE_KEY = SimpleHeuristicEngine.info.key


def get_engine(key: str | None = None) -> RecommendationEngine:
    """The single seam. Swap the default here, or pass `?engine=` to compare a
    new implementation against this one on identical data."""
    return ENGINES[key or DEFAULT_ENGINE_KEY]
