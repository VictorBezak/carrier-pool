"""Stage D: combine the pieces into money, then rank.

The question this engine answers is not "how good is this carrier". It is:

    given this load, what is the economic value of calling this carrier next,
    and what should we offer them?

The rate is a decision variable, not a prediction. For each carrier the engine
searches the rate it could offer and keeps the one that maximises expected value,
which is the calculation a good dispatcher does in their head.

Two design choices worth defending:

**Ranking by value per hour, not by value.** If a broker works down a list making
calls, the value of a call includes the option to call the next person when it
fails. A carrier that answers in twenty minutes resolves the load sooner than one
that takes three hours, and time to cover is a real cost. Ranking purely by
expected value systematically over-prefers the safe, cheap, slow carrier in
exactly the workflow that is most common.

**Optimism, not pessimism, under uncertainty.** The usual move is to subtract a
multiple of the standard deviation, which penalises unfamiliar carriers and
guarantees they stay unfamiliar. That is correct when the downside is a committed
load, and wrong when the downside is a wasted phone call: a call is cheap, and it
produces the data that resolves the uncertainty. So the sign of the risk term
follows the workflow - optimistic for a human calling down a list, cautious for
automatic tendering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil

from .. import geo
from ..domain import Equipment, Load
from ..history import BrokerHistory, CarrierLaneHistory
from . import components, costs, eligibility
from .contracts import (
    CarrierRecommendation,
    CoverageDecision,
    EngineInfo,
    HistoryDepth,
    OfferPlan,
    PriceEstimate,
    PriorOffer,
    Reason,
    RatePoint,
    Recommendations,
    RepricingTarget,
    ScoreComponent,
    ValueTerm,
)
from .pricing import estimate_price

# The rate search runs over this fraction of the lane estimate, in $5 steps.
RATE_FLOOR_FACTOR = 0.78
RATE_CEILING_FACTOR = 1.30
RATE_STEP = 5.0
# How much of the optimistic case to credit when ranking for a human call list.
OPTIMISM = 0.35
# A call cannot resolve a load faster than this, so value-per-hour stays finite.
MIN_RESOLUTION_HOURS = 0.25
# Roughly how many points of the acceptance curve to publish.
CURVE_POINTS = 40


def _duration(minutes: float) -> str:
    """Minutes are the model's unit and a poor way to say "most of a working day".

    Nobody reads 443 minutes as seven hours, and a recommendation that has to be
    converted in the reader's head is one they will skim past.
    """
    if minutes < 90:
        return f"{minutes:.0f} minutes"
    hours = minutes / 60
    if hours < 10:
        return f"{hours:.0f} hours" if abs(hours - round(hours)) < 0.15 else f"{hours:.1f} hours"
    if hours < 24:
        return f"{hours:.0f} hours"
    days = hours / 24
    return "about a day" if days < 1.5 else f"{days:.0f} days"


class ExpectedValueEngine:
    """Eligibility -> candidates -> component models -> expected value."""

    info = EngineInfo(
        key="expected-value",
        name="Risk-adjusted expected value",
        version="2.0",
        objective=(
            "Maximise expected margin per hour of broker time, net of service risk, choosing the "
            "offer rate as part of the decision."
        ),
        description=(
            "Hard eligibility gates, then per-outcome predictions shrunk toward contextual priors "
            "(acceptance as a function of the offered rate, on-time, fall-off, reply time), "
            "combined into expected value using named business costs."
        ),
    )

    def __init__(self, cost_model: costs.CostModel | None = None, optimism: float = OPTIMISM) -> None:
        self.costs = cost_model or costs.DEFAULT
        self.optimism = optimism

    def recommend(self, load: Load, history: BrokerHistory, limit: int = 10) -> Recommendations:
        notes: list[str] = []
        estimate = estimate_price(load, history)

        if load.equipment is Equipment.UNKNOWN:
            notes.append(
                "The source TMS did not record an equipment type, so the trailer gate could not be "
                "applied and every carrier passed it."
            )
        if load.origin_market == geo.UNKNOWN_MARKET or load.destination_market == geo.UNKNOWN_MARKET:
            notes.append(
                "This load's pickup or delivery could not be resolved to a known market, so lane "
                "history and deadhead estimates are unreliable for it."
            )
        if not history.offers:
            notes.append(
                "No offers have been logged for this broker, so every acceptance curve is the "
                "population prior. Ranking is driven by service risk and price alone."
            )

        screened = eligibility.prepare(load, history)
        market_rpm = components.market_rate(history, load.equipment)
        loads_by_id = {item.load_id: item for item in history.all_loads}
        prior_offers = history.offers_for_load(load.load_id)

        scored: list[CarrierRecommendation] = []
        for carrier_id in screened.eligible:
            carrier_history = history.carrier_history_for(carrier_id, load)
            if carrier_history is None:
                continue
            scored.append(
                self._evaluate(
                    load=load,
                    hist=carrier_history,
                    history=history,
                    estimate=estimate,
                    market_rpm=market_rpm,
                    loads_by_id=loads_by_id,
                    surfaced_by=screened.surfaced_by.get(carrier_id, []),
                    prior_offers=[
                        offer for offer in prior_offers if offer.carrier_id == carrier_id
                    ],
                )
            )

        scored.sort(key=lambda item: (-item.score, item.carrier_name))
        for index, recommendation in enumerate(scored[:limit], start=1):
            recommendation.rank = index

        coverage = self._coverage(load, scored, estimate)

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
            coverage=coverage,
            notes=notes,
            exclusions=screened.exclusions,
            unchecked_gates=screened.unchecked_gates,
            limitations=self._limitations(history),
        )

    # ---- cover or reprice ---------------------------------------------

    def _coverage(
        self,
        load: Load,
        scored: list[CarrierRecommendation],
        estimate: PriceEstimate | None,
    ) -> CoverageDecision | None:
        """Decide whether this load is worth working before deciding who to call.

        Ranking carriers presupposes the load should be covered. When no carrier has
        positive expected value that premise is false, and the ordering answers the
        wrong question in a specifically misleading way: maximising expected value on
        a load that loses money at every rate favours carriers *unlikely to accept*,
        because a carrier who declines costs only the phone call while one who accepts
        locks in the loss. Worked top-down, that list tells a dispatcher to spend the
        day on carriers who will say no.

        So the decision is made explicitly, and when the answer is "do not cover", the
        output becomes the number that would change it - what the load has to bill to
        be worth calling anyone about.
        """
        if not scored:
            return None

        best = max(item.offer_plan.expected_value_usd for item in scored)
        if best > 0:
            leader = scored[0]
            return CoverageDecision(
                decision="COVER",
                headline=f"Worth covering. Open with {leader.carrier_name}.",
                detail=(
                    f"Best expected value is ${best:,.0f} at "
                    f"${leader.offer_plan.offer_rate_usd:,.0f}."
                ),
                best_expected_value_usd=round(best, 2),
            )

        revenue = load.customer_rate or (estimate.point_usd * 1.18 if estimate else 0.0)
        # Cheapest route back to viability, not the carrier that ranks first: the
        # ranking is the thing we have just decided not to trust here.
        candidates = [
            item for item in scored if item.offer_plan.revenue_to_break_even_usd is not None
        ]
        target = None
        if candidates and revenue > 0:
            pick = min(candidates, key=lambda item: item.offer_plan.revenue_to_break_even_usd)
            required = pick.offer_plan.revenue_to_break_even_usd
            target = RepricingTarget(
                carrier_id=pick.carrier_id,
                carrier_name=pick.carrier_name,
                current_revenue_usd=round(revenue, 2),
                required_revenue_usd=round(required, 2),
                shortfall_usd=round(required - revenue, 2),
                shortfall_pct=round((required - revenue) / revenue * 100, 1),
                offer_rate_usd=pick.offer_plan.offer_rate_usd,
                acceptance_probability=pick.offer_plan.acceptance_probability,
            )

        detail = (
            "Every eligible carrier loses money at every rate they would accept, so working "
            "down the list below is the wrong move - it is ordered least-bad, and being "
            "unlikely to accept is what makes a carrier look good on a load like this."
        )
        if target is not None:
            detail += (
                f" The cheapest way to make this coverable is {target.carrier_name}, who needs "
                f"${target.required_revenue_usd:,.0f} against the ${target.current_revenue_usd:,.0f} "
                f"it bills now."
            )
        headline = (
            f"Reprice with the customer: ${target.shortfall_usd:,.0f} short "
            f"({target.shortfall_pct:.0f}%)."
            if target is not None
            else "Reprice with the customer. No eligible carrier is worth calling at this rate."
        )
        return CoverageDecision(
            decision="REPRICE",
            headline=headline,
            detail=detail,
            best_expected_value_usd=round(best, 2),
            target=target,
        )

    # ---- per-carrier evaluation ---------------------------------------

    def _evaluate(
        self,
        load: Load,
        hist: CarrierLaneHistory,
        history: BrokerHistory,
        estimate: PriceEstimate | None,
        market_rpm: float | None,
        loads_by_id: dict[str, Load],
        surfaced_by: list[str],
        prior_offers: list,
    ) -> CarrierRecommendation:
        curve = components.build_acceptance_curve(load, hist, history, loads_by_id, market_rpm)
        equipment = components.equipment_confidence(load, hist, history)
        on_time = components.on_time_estimate(hist, history)
        fall_off = components.fall_off_estimate(hist, history)
        reply = components.response_estimate(hist, history)
        silence = components.no_response_estimate(hist, history)

        # A carrier that already refused a specific number on *this* load has told
        # us its floor is above it. That is stronger evidence than the curve, which
        # is fitted from other loads.
        #
        # Whether that raises the floor estimate and whether the dispatcher should
        # be told are separate questions: they need to know they have already made
        # this call either way, even when the fitted floor was above the refusal
        # and nothing moved.
        refusals = [offer for offer in prior_offers if not offer.accepted]
        refusal_note = None
        if refusals:
            parts = []
            for offer in refusals:
                part = f"refused ${offer.offered_rate:,.0f}"
                if offer.counter_rate:
                    part += f" and countered at ${offer.counter_rate:,.0f}"
                elif offer.outcome.value == "NO_RESPONSE":
                    part = f"never replied to ${offer.offered_rate:,.0f}"
                parts.append(part)
            refusal_note = "Already " + "; ".join(parts) + " on this load."

        floor_usd = max(
            [curve.floor_usd]
            + [offer.counter_rate or offer.offered_rate * 1.04 for offer in refusals]
        )
        if floor_usd > curve.floor_usd:
            curve = type(curve)(
                floor_usd=floor_usd,
                floor_sd_usd=curve.floor_sd_usd * 0.6,
                width_usd=curve.width_usd,
                evidence=f"refused an offer on this load; {curve.evidence}",
                observations=curve.observations,
                prior_share=curve.prior_share,
                prior_label=curve.prior_label,
            )

        service_cost = (
            (1 - on_time.value) * self.costs.late_delivery_usd
            + fall_off.value * self.costs.fall_off_usd
            + self.costs.claim_usd
            + self.costs.operational_usd
        )
        reply_hours = reply.value / 60.0
        call_cost = reply_hours * self.costs.broker_hourly_usd
        revenue = load.customer_rate or (estimate.point_usd * 1.18 if estimate else 0.0)

        plan = self._best_offer(
            curve=curve,
            revenue=revenue,
            service_cost=service_cost,
            call_cost=call_cost,
            reply_hours=reply_hours,
            estimate=estimate,
            load=load,
            capability=equipment.value,
        )

        # The two adjustments that turn expected value into a *call order* are kept
        # as explicit components rather than folded into the score, so the ranking
        # arithmetic stays reconstructable: a carrier that ranks above one with more
        # expected value should be able to show which adjustment did it.
        #
        # Dividing by time only orders correctly while the value being divided is
        # positive. On a load that loses money at every rate, a longer wait moves a
        # negative value *toward* zero, so the slowest carrier wins: a carrier at
        # -$45 over 7.4 hours scores -6.1/hour and beats one at -$20 over 1.1 hours
        # at -17.0/hour, which is backwards. Rate per hour answers "how much value
        # does an hour of broker time buy", and that question is meaningless when
        # the answer is a loss - you are not buying value, you are choosing how
        # quickly to find out. So the normalisation applies only to loads worth
        # covering, and the rest rank on expected value alone, which still puts the
        # least bad option first.
        if plan.expected_value_usd > 0 and plan.value_per_hour_usd is not None:
            per_hour = plan.value_per_hour_usd
        else:
            per_hour = plan.expected_value_usd
        time_adjustment = per_hour - plan.expected_value_usd
        upside = max(plan.optimistic_value_usd - plan.expected_value_usd, 0.0)
        uncertainty_credit = self.optimism * upside

        predictions = [
            components.describe_curve(curve),
            components.describe(
                "on_time", "On-time delivery", on_time,
                display=f"{on_time.value * 100:.0f}%",
                note=(
                    f"Own record: {hist.service_on_time}/{hist.service_known} on time."
                    if hist.service_known
                    else "No completed loads with an observable outcome yet."
                ),
            ),
            components.describe(
                "fall_off", "Fall-off risk", fall_off,
                display=f"{fall_off.value * 100:.1f}%",
                note=(
                    f"Came off {hist.fall_offs} load{'s' if hist.fall_offs != 1 else ''} after accepting."
                    if hist.fall_offs
                    else "Never come off a load after accepting."
                ),
            ),
            components.describe(
                "reply_time", "Expected reply time", reply,
                display=_duration(reply.value),
                note=f"{len(hist.offers)} logged offer{'s' if len(hist.offers) != 1 else ''}.",
            ),
            components.describe(
                "no_response", "Chance of no reply", silence,
                display=f"{silence.value * 100:.0f}%",
            ),
        ]

        # Only worth a row when there is something to be uncertain about. Every
        # carrier here cleared the trailer gate, so restating "has the right trailer"
        # for a carrier that has demonstrably hauled twenty of them is noise; the
        # informative case is the one that has never hauled this type and is being
        # ranked on the possibility that it can.
        if equipment.value < 1.0:
            predictions.insert(
                1,
                components.describe(
                    "equipment", f"Has a {load.equipment.value.replace('_', ' ').lower()}", equipment,
                    display=f"{equipment.value * 100:.0f}%",
                    note=(
                        f"Never hauled one for this broker in {equipment.observations} "
                        f"load{'s' if equipment.observations != 1 else ''}. No feed records "
                        f"what a carrier owns, so this is inferred from what it has hauled."
                    ),
                ),
            )

        reasons = self._reasons(
            hist, curve, on_time, fall_off, reply, plan, refusal_note, equipment, load
        )

        # Components are dollars here rather than arbitrary points, and they still
        # sum to the score - which is the one invariant every engine must hold, or
        # the explanation and the ranking can drift apart unnoticed.
        breakdown = [
            ScoreComponent(
                key=term.key, label=term.label, weight=1.0,
                value=round(term.amount_usd, 2), points=round(term.amount_usd, 2),
            )
            for term in plan.value_terms
        ]
        breakdown.append(
            ScoreComponent(
                key="time_to_resolve",
                label=(
                    "Adjusted for time to resolve"
                    if time_adjustment
                    else "Not adjusted for time: this load loses money at every rate"
                ),
                weight=1.0,
                value=round(plan.expected_resolution_hours or 0.0, 2),
                points=round(time_adjustment, 2),
            )
        )
        breakdown.append(
            ScoreComponent(
                key="uncertainty_credit",
                label="Credit for uncertainty worth resolving",
                weight=self.optimism,
                value=round(upside, 2),
                points=round(uncertainty_credit, 2),
            )
        )
        score = round(sum(component.points for component in breakdown), 1)

        return CarrierRecommendation(
            rank=0,
            carrier_id=hist.carrier.carrier_id,
            carrier_name=hist.carrier.name,
            mc_number=hist.carrier.mc_number,
            phone=hist.carrier.phone,
            score=score,
            components=breakdown,
            reasons=reasons,
            history_depth=self._history_depth(hist),
            loads_total=hist.loads_total,
            loads_on_lane=hist.loads_on_lane,
            days_since_last_load=hist.days_since_last_load,
            last_delivery_market_label=(
                geo.market_label(hist.last_delivery_market) if hist.last_delivery_market else None
            ),
            median_lane_rate_per_mile=hist.median_lane_rate_per_mile,
            suggested_rate_usd=plan.offer_rate_usd,
            offer_plan=plan,
            predictions=predictions,
            prior_offers=[
                PriorOffer(
                    offered_rate_usd=offer.offered_rate,
                    outcome=offer.outcome.value,
                    counter_rate_usd=offer.counter_rate,
                    response_minutes=offer.response_minutes,
                    offered_at=offer.offered_at,
                )
                for offer in prior_offers
            ],
            surfaced_by=surfaced_by,
        )

    def _best_offer(
        self,
        curve: components.AcceptanceCurve,
        revenue: float,
        service_cost: float,
        call_cost: float,
        reply_hours: float,
        estimate: PriceEstimate | None,
        load: Load,
        capability: float,
    ) -> OfferPlan:
        """Search the offer rate. The maximum is where conceding another $5 stops
        buying enough acceptance probability to pay for itself.

        `capability` is P(the carrier can actually pull this trailer), and it enters
        as a multiplier on acceptance rather than as a score adjustment, because that
        is the mechanism it acts through: a carrier without a reefer says no to a
        reefer load at any price. Money buys willingness, never equipment. Modelling
        it this way also stops the rate search from trying to solve a capability
        problem by paying more, which is what a score penalty would let it do.
        """
        anchor = estimate.point_usd if estimate else (load.carrier_rate or curve.floor_usd)
        low = max(RATE_STEP, round(anchor * RATE_FLOOR_FACTOR / RATE_STEP) * RATE_STEP)
        high = round(anchor * RATE_CEILING_FACTOR / RATE_STEP) * RATE_STEP

        def value_at(rate: float, floor_shift: float = 0.0) -> tuple[float, float, float]:
            willing = curve.probability(rate, floor_shift)
            probability = capability * willing
            margin = revenue - rate - service_cost
            return probability * margin - (1 - probability) * call_cost, probability, willing

        best_rate, best_value = low, float("-inf")
        best_probability = best_willing = 0.0
        rate = low
        while rate <= high:
            value, probability, willing = value_at(rate)
            if value > best_value:
                best_rate, best_value = rate, value
                best_probability, best_willing = probability, willing
            rate += RATE_STEP

        optimistic, *_ = value_at(best_rate, floor_shift=-1.0)
        pessimistic, *_ = value_at(best_rate, floor_shift=1.0)

        margin = revenue - best_rate - service_cost
        terms = [
            ValueTerm(
                key="revenue", label="Customer pays", amount_usd=round(revenue, 2),
                detail="What this load bills at." if load.customer_rate else "Estimated from the lane price.",
            ),
            ValueTerm(
                key="offer", label="Offer to carrier", amount_usd=round(-best_rate, 2),
                detail=f"Chosen to maximise expected value; {best_probability * 100:.0f}% likely to be accepted.",
            ),
            ValueTerm(
                key="service_risk", label="Expected service cost", amount_usd=round(-service_cost, 2),
                detail="Probability of a late delivery and of a fall-off, priced at their business cost.",
            ),
            ValueTerm(
                key="acceptance", label="Weighted by acceptance", amount_usd=round(best_willing * margin - margin, 2),
                detail=f"Margin of ${margin:,.0f} only materialises {best_willing * 100:.0f}% of the time.",
            ),
        ]
        if capability < 1.0:
            terms.append(
                ValueTerm(
                    key="capability",
                    label="Discounted for trailer uncertainty",
                    amount_usd=round((best_probability - best_willing) * margin, 2),
                    detail=(
                        f"{capability * 100:.0f}% chance they have the right trailer at all, "
                        f"which no rate can change."
                    ),
                )
            )
        terms.append(
            ValueTerm(
                key="call_cost", label="Cost of a failed call", amount_usd=round(-(1 - best_probability) * call_cost, 2),
                detail=f"{reply_hours * 60:.0f} minutes of broker time at ${self.costs.broker_hourly_usd:.0f}/hour.",
            )
        )

        # The customer rate at which this carrier becomes worth calling. At a fixed
        # offer rate the call is worth making when
        #
        #     p(R - r - service) > (1 - p) * call
        #
        # so the revenue required is r + service + call*(1-p)/p, and the useful figure
        # is the smallest such value over the rates on offer. Conceding a higher rate
        # raises `r` but also raises `p`, which shrinks the wasted-call term, so the
        # minimum is a real trade-off rather than just the cheapest offer.
        #
        # Note what this does to a carrier that probably lacks the trailer: `p` is
        # capped by capability, so (1-p)/p explodes and the revenue it would take to
        # justify the call goes with it. The carrier who can actually haul the freight
        # comes out cheapest, which is the opposite of how raw expected value ranks
        # them on a losing load.
        break_even = None
        rate = low
        while rate <= high:
            probability = capability * curve.probability(rate)
            if probability > 0.01:
                required = rate + service_cost + call_cost * (1 - probability) / probability
                if break_even is None or required < break_even:
                    break_even = required
            rate += RATE_STEP

        # Thinned to a readable number of points: the curve is for showing the shape
        # of the trade-off, and $5 resolution across a $1,000 span is more samples
        # than any chart or slider can express.
        stride = max(1, ceil((high - low) / RATE_STEP / CURVE_POINTS))
        curve_points: list[RatePoint] = []
        rate = low
        index = 0
        while rate <= high:
            if index % stride == 0 or rate == best_rate:
                value, probability, _ = value_at(rate)
                curve_points.append(
                    RatePoint(
                        rate_usd=rate,
                        acceptance_probability=round(probability, 4),
                        expected_value_usd=round(value, 2),
                    )
                )
            rate += RATE_STEP
            index += 1

        resolution_hours = max(reply_hours, MIN_RESOLUTION_HOURS)
        return OfferPlan(
            estimated_floor_usd=round(curve.floor_usd, 2),
            rate_curve=curve_points,
            revenue_to_break_even_usd=round(break_even, 2) if break_even is not None else None,
            offer_rate_usd=best_rate,
            acceptance_probability=round(best_probability, 4),
            expected_value_usd=round(best_value, 2),
            value_terms=terms,
            optimistic_value_usd=round(optimistic, 2),
            pessimistic_value_usd=round(pessimistic, 2),
            expected_resolution_hours=round(resolution_hours, 2),
            value_per_hour_usd=round(best_value / resolution_hours, 2),
            rate_ceiling_usd=round(curve.rate_for_probability(0.9) / RATE_STEP) * RATE_STEP,
            walk_away_rate_usd=round((revenue - service_cost) / RATE_STEP) * RATE_STEP,
        )

    def _reasons(
        self, hist, curve, on_time, fall_off, reply, plan: OfferPlan,
        refusal_note: str | None, equipment, load: Load,
    ) -> list[Reason]:
        reasons = [
            Reason(
                label="What to offer",
                detail=(
                    f"Open at ${plan.offer_rate_usd:,.0f}. That is {plan.acceptance_probability * 100:.0f}% "
                    f"likely to be accepted, and ${plan.rate_ceiling_usd:,.0f} would make it 90%. "
                    f"Above ${plan.walk_away_rate_usd:,.0f} this load stops being worth covering with them."
                ),
                sentiment="neutral",
                points=round(plan.expected_value_usd, 1),
                kind="offer",
            ),
            Reason(
                label="Where the floor estimate comes from",
                detail=f"Estimated from {curve.evidence}."
                + (
                    f" {curve.prior_share * 100:.0f}% of it is still the population prior "
                    f"({curve.prior_label})."
                    if curve.prior_share >= 0.4
                    else ""
                ),
                sentiment="neutral" if curve.prior_share < 0.5 else "negative",
                kind="basis",
            ),
        ]

        if refusal_note:
            reasons.append(
                Reason(
                    label="Already asked",
                    detail=refusal_note,
                    sentiment="negative",
                    kind="offer",
                )
            )

        # Silent when the trailer is proven, which is the common case. There is no
        # value in telling a dispatcher that a carrier they use for reefer freight
        # every week has a reefer.
        if equipment.value < 1.0:
            needed = load.equipment.value.replace("_", " ").lower()
            reasons.append(
                Reason(
                    label="Unproven on this trailer",
                    detail=(
                        f"Has never hauled a {needed} for this broker, across "
                        f"{equipment.observations} load{'s' if equipment.observations != 1 else ''}. "
                        f"That leaves roughly a {equipment.value * 100:.0f}% chance they can take it, "
                        f"and it is worth confirming before negotiating."
                    ),
                    sentiment="negative",
                )
            )

        if hist.service_known:
            sentiment = "positive" if on_time.value >= 0.85 else "negative"
            detail = (
                f"{hist.service_on_time} of {hist.service_known} completed loads hit their "
                f"appointment. Adjusted for sample size that reads as {on_time.value * 100:.0f}%"
            )
            if on_time.is_mostly_prior:
                detail += f", mostly carried by {on_time.prior_label}"
            reasons.append(Reason(label="Service record", detail=detail + ".", sentiment=sentiment))
        else:
            reasons.append(
                Reason(
                    label="No service record yet",
                    detail=(
                        f"No completed load with an observable outcome, so on-time is assumed to be "
                        f"{on_time.prior_label}."
                    ),
                    sentiment="neutral",
                )
            )

        if hist.fall_offs:
            reasons.append(
                Reason(
                    label="Has walked away before",
                    detail=(
                        f"Came off {hist.fall_offs} load{'s' if hist.fall_offs != 1 else ''} after "
                        f"accepting, which costs about ${self.costs.fall_off_usd:,.0f} each time to "
                        f"re-cover. Shrunk to a {fall_off.value * 100:.1f}% risk here."
                    ),
                    sentiment="negative",
                )
            )

        if reply.value <= 40:
            reasons.append(
                Reason(
                    label="Answers quickly",
                    detail=f"Typically replies in about {_duration(reply.value)}.",
                    sentiment="positive",
                )
            )
        elif reply.value >= 120:
            reasons.append(
                Reason(
                    label="Slow to answer",
                    detail=(
                        f"Typically takes about {_duration(reply.value)} to reply, which delays "
                        f"the next call if they say no."
                    ),
                    sentiment="negative",
                )
            )

        spread = plan.optimistic_value_usd - plan.pessimistic_value_usd
        if spread > 120:
            reasons.append(
                Reason(
                    label="Uncertain, and worth finding out",
                    detail=(
                        f"Expected value ranges ${plan.pessimistic_value_usd:,.0f} to "
                        f"${plan.optimistic_value_usd:,.0f} depending on where their floor really is. "
                        f"Calling them is cheap and settles it."
                    ),
                    sentiment="neutral",
                )
            )

        reasons.sort(key=lambda item: -(item.points or 0))
        return reasons

    @staticmethod
    def _history_depth(hist: CarrierLaneHistory) -> HistoryDepth:
        thin = hist.loads_total <= 1 or hist.loads_on_lane == 0
        if hist.loads_total <= 1:
            label = "Thin history: only one booked load ever"
        elif hist.loads_on_lane == 0:
            label = "No history on this exact lane"
        elif hist.loads_on_lane >= 3:
            label = "Well established on this lane"
        else:
            label = "Some history on this lane"
        return HistoryDepth(
            loads_total=hist.loads_total,
            loads_on_lane=hist.loads_on_lane,
            label=label,
            is_thin=thin,
        )

    def _limitations(self, history: BrokerHistory) -> list[str]:
        """Stated in the response, because a number without its caveat gets quoted
        without its caveat."""
        limits = [
            "Offers are only logged for carriers a broker actually called, so acceptance is "
            "estimated from a biased sample: a carrier that was never called looks unknown rather "
            "than unsuitable. Correcting this needs randomised exploration or propensity weighting, "
            "neither of which is implemented.",
            "Rankings are independent per load. When several loads compete for the same truck the "
            "right answer is a global assignment, not the top of each list.",
            "No component is a trained model. Each is a shrunk estimate over a handful of "
            "observations, which is appropriate at this data volume and would be replaced by "
            "gradient-boosted trees once there are thousands of loads rather than dozens.",
        ]
        limits.extend(self.costs.unmodelled())
        if len(history.priced_loads) < 30:
            limits.append(
                f"This broker has only {len(history.priced_loads)} priced loads. Every estimate here "
                "leans heavily on its prior."
            )
        return limits
