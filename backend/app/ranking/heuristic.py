"""v1 engine: a transparent weighted heuristic.

**This is the deliberately simple version**, kept after the expected-value engine
was built rather than deleted. Two reasons:

- it is the control. Both engines run on identical data through the same
  contract, so `?engine=` is a real comparison rather than a claim.
- it degrades better. It needs no offer log, so it still answers for a tenant
  the platform has never made a call for.

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
- The weights are asserted, not derived. They encode a plausible ordering of what
  matters, but no business cost is attached to any of them, so the resulting
  score is ordinal and has no units. That is the specific gap the expected-value
  engine closes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import geo
from ..domain import Equipment, Load
from ..history import BrokerHistory, CarrierLaneHistory
from . import components, eligibility
from .contracts import (
    CarrierRecommendation,
    EngineInfo,
    HistoryDepth,
    PriceEstimate,
    Reason,
    Recommendations,
    ScoreComponent,
    Sentiment,
)
from .pricing import estimate_price

WEIGHTS: dict[str, tuple[str, float]] = {
    "lane_experience": ("Lane experience", 0.40),
    "equipment_confidence": ("Can pull this trailer", 0.20),
    "recency": ("Recently active", 0.15),
    "relationship_depth": ("Relationship depth", 0.15),
    "repositioning": ("Easy repositioning", 0.10),
}

# Number of loads on a lane past which more history stops adding confidence.
LANE_SATURATION = 3
RELATIONSHIP_SATURATION = 5


class SimpleHeuristicEngine:
    info = EngineInfo(
        key="simple-heuristic",
        name="Transparent weighted heuristic",
        version="1.2",
        objective="Rank by a weighted sum of history signals. Ordinal, no units.",
        description=(
            "Weighted sum of lane experience, trailer capability, recency, relationship depth "
            "and repositioning, over the carriers that cleared the shared eligibility gates. "
            "Price is the median rate per mile of the narrowest comparable set with enough "
            "loads in it."
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
                "The source TMS did not record an equipment type, so no carrier was screened "
                "out or credited on trailer fit, rather than assuming a dry van."
            )

        scored: list[CarrierRecommendation] = []
        estimate = estimate_price(load, history)

        # Screening is shared with every other engine rather than reimplemented here.
        # Eligibility is a fact about the load and the carrier, so it cannot depend on
        # which scoring strategy the caller asked for: before this was hoisted out,
        # this engine ranked carriers the expected-value engine excluded as unable to
        # haul the freight, and picking an engine silently picked whether hard
        # constraints applied at all.
        screened = eligibility.prepare(load, history)

        for carrier_id in screened.eligible:
            carrier_history = history.carrier_history_for(carrier_id, load)
            if carrier_history is None:
                continue
            scored.append(
                self._score_carrier(
                    load,
                    carrier_history,
                    estimate,
                    history,
                    screened.surfaced_by.get(carrier_id, []),
                )
            )

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
            carriers_considered=len(screened.eligible),
            exclusions=screened.exclusions,
            unchecked_gates=screened.unchecked_gates,
            notes=notes,
        )

    # ---- carrier scoring ----------------------------------------------

    def _score_carrier(
        self,
        load: Load,
        carrier_history: CarrierLaneHistory,
        estimate: PriceEstimate | None,
        history: BrokerHistory,
        surfaced_by: list[str],
    ) -> CarrierRecommendation:
        breakdown: list[ScoreComponent] = []
        reasons: list[Reason] = []

        for key, (value, reason) in self._signals(load, carrier_history, history).items():
            label, weight = WEIGHTS[key]
            points = round(weight * value * 100, 1)
            breakdown.append(
                ScoreComponent(key=key, label=label, weight=weight, value=round(value, 3), points=points)
            )
            reason.points = points
            reasons.append(reason)

        score = round(sum(component.points for component in breakdown), 1)
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
            components=breakdown,
            reasons=reasons,
            surfaced_by=surfaced_by,
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
        self, load: Load, hist: CarrierLaneHistory, history: BrokerHistory
    ) -> dict[str, tuple[float, Reason]]:
        return {
            "lane_experience": self._lane_experience(load, hist),
            "equipment_confidence": self._equipment_confidence(load, hist, history),
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
    def _equipment_confidence(
        load: Load, hist: CarrierLaneHistory, history: BrokerHistory
    ) -> tuple[float, Reason]:
        """Reads the same probability the trailer gate reads.

        Carriers who probably cannot pull the trailer have already been excluded, so
        this signal is not deciding eligibility - it is separating a carrier proven on
        this trailer from one that survived the gate on a thin record. Sharing the
        estimate with the gate is the point: two different notions of "has a reefer"
        is how a carrier gets excluded by one part of the system and rewarded by
        another.
        """
        if load.equipment is Equipment.UNKNOWN:
            return 0.5, Reason(
                label="Equipment unknown",
                detail=(
                    "The load has no trailer type recorded, so nothing could be checked and "
                    "no carrier was credited or penalised for it."
                ),
                sentiment="neutral",
            )

        confidence = components.equipment_confidence(load, hist, history)
        equipment_label = load.equipment.value.replace("_", " ").lower()
        if hist.loads_with_equipment:
            plural = "s" if hist.loads_with_equipment != 1 else ""
            return confidence.value, Reason(
                label="Proven on this trailer",
                detail=(
                    f"Has hauled {hist.loads_with_equipment} {equipment_label} "
                    f"load{plural} for this broker."
                ),
                sentiment="positive",
            )
        return confidence.value, Reason(
            label="Unproven on this trailer",
            detail=(
                f"Has never hauled a {equipment_label} for this broker in "
                f"{confidence.observations} load{'s' if confidence.observations != 1 else ''}, "
                f"leaving roughly a {confidence.value * 100:.0f}% chance they can take it. "
                f"No feed records what equipment a carrier owns."
            ),
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
