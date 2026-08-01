"""Stage C: predict the pieces separately.

One model per outcome, each shrunk toward a contextual prior and each carrying
its own uncertainty. Separating them buys three things: a business cost can
change without touching any estimator, each piece can be checked against reality
on its own, and the explanation shown to a broker is the actual arithmetic.

The centrepiece is the acceptance curve, and it is not a probability - it is a
*function of the rate offered*. Treating "will they accept" and "what will they
charge" as two independent predictions loses the only variable the broker
controls. What a carrier costs is the outcome of a negotiation whose input is the
number you say first.

Rather than fit a logistic regression to five data points, the curve is built
from an explicit reservation-price model: each carrier has a floor, the log tells
us things about where that floor is, and acceptance is the probability the offer
clears it. With this little data an interpretable structural model beats a
flexible one, and it degrades into a population average instead of into noise.

What is *not* modelled, because no data supports it: claims frequency and cost,
tracking compliance, and operational intervention effort. They appear in the
utility layer as zero with a stated reason rather than as invented constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp

from ..domain import Equipment, Load, OfferOutcome
from ..history import BrokerHistory, CarrierLaneHistory
from ..stats import Estimate, PriorLevel, resolve_prior, shrink_mean, shrink_rate
from .contracts import Prediction
from .pricing import market_rate_per_mile

# How sharply acceptance rises around the floor, as a fraction of the market rate.
# Wider when the floor is uncertain: a carrier we know little about gets a curve
# that admits it might say yes to less, or need more.
BASE_CURVE_WIDTH = 0.035
# A carrier that has never been offered anything at all.
UNKNOWN_FLOOR_INDEX = 0.97
NO_RESPONSE_MINUTES = 12 * 60.0


@dataclass(frozen=True)
class AcceptanceCurve:
    """P(accept | offered rate) for one carrier on one load."""

    floor_usd: float
    floor_sd_usd: float
    width_usd: float
    evidence: str
    observations: int
    prior_share: float
    prior_label: str

    def probability(self, offered_usd: float, floor_shift: float = 0.0) -> float:
        """Logistic in the gap between the offer and the estimated floor.

        `floor_shift` moves the assumed floor in units of its own standard
        deviation, which is how the utility layer prices its own uncertainty
        instead of pretending the floor is known.
        """
        floor = self.floor_usd + floor_shift * self.floor_sd_usd
        return 1.0 / (1.0 + exp(-(offered_usd - floor) / self.width_usd))

    def rate_for_probability(self, target: float) -> float:
        """The offer that would clear at a given probability - the inverse curve.

        This is what makes the recommendation actionable: "$1,180 to be 80%
        confident" is a sentence a dispatcher can use.
        """
        target = min(max(target, 0.01), 0.99)
        from math import log

        return self.floor_usd + self.width_usd * log(target / (1 - target))


def _rate_index(load: Load, rate_usd: float, market_rpm: float | None) -> float | None:
    """An offer expressed as a fraction of the going rate for that trailer type.

    Necessary because offers are only comparable across loads once length and
    equipment are divided out - $1,100 is generous on one load and insulting on
    another. Without this the acceptance data looks like noise.
    """
    if not load.distance_miles or not market_rpm:
        return None
    return (rate_usd / load.distance_miles) / market_rpm


def build_acceptance_curve(
    load: Load,
    hist: CarrierLaneHistory,
    history: BrokerHistory,
    loads_by_id: dict[str, Load],
    market_rpm: float | None,
) -> AcceptanceCurve:
    """Locate the carrier's price floor from whatever the offer log revealed.

    Three grades of evidence, in descending strength:

    - a counter-offer states the floor outright;
    - an acceptance proves the floor is at or below what was offered;
    - a decline or silence proves it is above.

    Everything is converted to a rate index first, then shrunk toward the floor of
    a comparable population, so a carrier with one data point ends up near the
    population and one with eight ends up near its own record.
    """
    accepted: list[float] = []
    refused: list[float] = []
    revealed: list[float] = []

    for offer in hist.offers:
        offer_load = loads_by_id.get(offer.load_id)
        if offer_load is None:
            continue
        index = _rate_index(offer_load, offer.offered_rate, market_rpm)
        if index is None:
            continue
        if offer.outcome is OfferOutcome.ACCEPTED:
            accepted.append(index)
            continue
        refused.append(index)
        if offer.counter_rate is not None:
            countered = _rate_index(offer_load, offer.counter_rate, market_rpm)
            if countered is not None:
                revealed.append(countered)

    observations = len(accepted) + len(refused)

    # How much the carrier's own record is worth, in observation-equivalents. A
    # counter states the floor outright and is worth several one-sided offers; a
    # bracket is nearly as good; a pile of accepts with no refusal only ever
    # proves an upper bound and is worth much less.
    if revealed:
        own = sum(revealed) / len(revealed)
        evidence = f"{len(revealed)} counter-offer{'s' if len(revealed) != 1 else ''} stating their price"
        support = 2.5 * len(revealed) + 0.5 * len(refused)
    elif accepted and refused:
        # The floor is bracketed. Midpoint of the tightest bracket the log gives.
        own = (max(refused) + min(accepted)) / 2
        evidence = f"{len(accepted)} accepted and {len(refused)} refused offers bracket their floor"
        support = 1.5 + 0.5 * observations
    elif accepted:
        own = min(accepted)
        evidence = f"{len(accepted)} accepted offer{'s' if len(accepted) != 1 else ''}, none refused"
        support = 0.5 * len(accepted)
    elif refused:
        own = max(refused) * 1.04
        evidence = f"{len(refused)} refused offer{'s' if len(refused) != 1 else ''}, none accepted"
        support = 0.5 * len(refused)
    else:
        own = None
        evidence = "never been offered a load through the platform"
        support = 0.0

    prior = _floor_prior(history, loads_by_id, market_rpm, load.equipment, exclude=hist.carrier.carrier_id)
    estimate = shrink_mean(
        values=[own] if own is not None else [],
        prior=prior.mean if prior.mean is not None else UNKNOWN_FLOOR_INDEX,
        prior_label=prior.label,
        prior_weight=3.0,
        prior_sd=0.06,
        evidence=support,
    )

    miles = load.distance_miles or 0.0
    scale = (market_rpm or 0.0) * miles
    if scale <= 0:
        # No mileage means the index cannot be turned back into dollars. Fall back
        # to the carrier rate the load already carries, or refuse to be confident.
        scale = load.carrier_rate or load.customer_rate or 1000.0

    floor_usd = estimate.value * scale
    floor_sd_usd = max(estimate.sd * scale, scale * 0.01)
    # An uncertain floor is a flatter curve, not a sharp one in the wrong place.
    width_usd = max(BASE_CURVE_WIDTH * scale, floor_sd_usd * 0.9)

    return AcceptanceCurve(
        floor_usd=floor_usd,
        floor_sd_usd=floor_sd_usd,
        width_usd=width_usd,
        evidence=evidence,
        observations=observations,
        prior_share=estimate.prior_share,
        prior_label=estimate.prior_label,
    )


def _floor_prior(
    history: BrokerHistory,
    loads_by_id: dict[str, Load],
    market_rpm: float | None,
    equipment: Equipment,
    exclude: str,
) -> PriorLevel:
    """Where carriers in general set their floor, narrowest usable context first.

    Excluding the carrier being estimated matters: otherwise its own record leaks
    into its own prior and the shrinkage stops doing anything.
    """
    same_equipment: list[float] = []
    everyone: list[float] = []

    for offer in history.offers:
        if offer.carrier_id == exclude or offer.outcome is not OfferOutcome.ACCEPTED:
            continue
        offer_load = loads_by_id.get(offer.load_id)
        if offer_load is None:
            continue
        index = _rate_index(offer_load, offer.offered_rate, market_rpm)
        if index is None:
            continue
        everyone.append(index)
        if equipment is not Equipment.UNKNOWN and offer_load.equipment == equipment:
            same_equipment.append(index)

    levels = [
        PriorLevel(
            label=f"accepted offers on {equipment.value.replace('_', ' ').lower()} loads",
            total=sum(same_equipment),
            observations=len(same_equipment),
        ),
        PriorLevel(
            label="accepted offers across this broker's carriers",
            total=sum(everyone),
            observations=len(everyone),
        ),
        PriorLevel(label="no offer history at all", total=UNKNOWN_FLOOR_INDEX, observations=1),
    ]
    return resolve_prior(levels, minimum=4)


def on_time_estimate(hist: CarrierLaneHistory, history: BrokerHistory) -> Estimate:
    """P(no service failure), shrunk toward the broker's own record.

    The prior hierarchy is thin here on purpose: with this dataset there are not
    enough observed outcomes per lane for a lane-level prior to beat the broker
    average, and pretending otherwise would just add a noisy step.
    """
    broker_on_time, broker_known = history.service_record()
    prior_rate = (broker_on_time / broker_known) if broker_known else 0.85
    return shrink_rate(
        successes=hist.service_on_time,
        observations=hist.service_known,
        prior=prior_rate,
        prior_label=f"this broker's overall on-time rate across {broker_known} completed loads",
        prior_weight=4.0,
    )


def fall_off_estimate(hist: CarrierLaneHistory, history: BrokerHistory) -> Estimate:
    """P(accepts then walks away), shrunk hard.

    Fall-offs are rare and expensive, which is the worst combination for a raw
    rate: one event on two loads reads as 50%. The prior weight is high so a
    single incident moves the estimate without dominating it.
    """
    total_bookings = sum(1 for load in history.all_loads if load.is_booked)
    total_fall_offs = history.total_fall_offs()
    prior_rate = (total_fall_offs / total_bookings) if total_bookings else 0.05
    # A carrier can only fall off a load it accepted, so exposure is its bookings
    # plus the fall-offs themselves, which never became bookings for it.
    exposure = hist.loads_total + hist.fall_offs
    return shrink_rate(
        successes=hist.fall_offs,
        observations=exposure,
        prior=prior_rate,
        prior_label=f"this broker's overall fall-off rate across {total_bookings} bookings",
        prior_weight=8.0,
    )


def response_estimate(hist: CarrierLaneHistory, history: BrokerHistory) -> Estimate:
    """Expected minutes to an answer, counting silence as a long wait.

    Matters because a broker calling down a list spends time, not just money. A
    carrier that answers in fifteen minutes is worth calling before one that takes
    three hours even at a slightly worse price.
    """
    own = [
        offer.response_minutes if offer.response_minutes is not None else NO_RESPONSE_MINUTES
        for offer in hist.offers
    ]
    population = [
        offer.response_minutes if offer.response_minutes is not None else NO_RESPONSE_MINUTES
        for offer in history.offers
        if offer.carrier_id != hist.carrier.carrier_id
    ]
    prior = sum(population) / len(population) if population else 90.0
    return shrink_mean(
        values=own,
        prior=prior,
        prior_label=f"average reply time across this broker's other carriers ({prior:.0f} min)",
        prior_weight=3.0,
        prior_sd=60.0,
    )


def no_response_estimate(hist: CarrierLaneHistory, history: BrokerHistory) -> Estimate:
    population = [
        1.0 if offer.outcome is OfferOutcome.NO_RESPONSE else 0.0
        for offer in history.offers
        if offer.carrier_id != hist.carrier.carrier_id
    ]
    prior = sum(population) / len(population) if population else 0.1
    silent = sum(1 for offer in hist.offers if offer.outcome is OfferOutcome.NO_RESPONSE)
    return shrink_rate(
        successes=silent,
        observations=len(hist.offers),
        prior=prior,
        prior_label="how often this broker's other carriers never reply",
        prior_weight=4.0,
    )


def describe_curve(curve: AcceptanceCurve) -> Prediction:
    """The acceptance curve reported in the same shape as the other components.

    It is a curve rather than a scalar, so what gets published is its location -
    the floor - which is the number a dispatcher can act on.
    """
    return Prediction(
        key="acceptance_floor",
        label="Estimated price floor",
        value=round(curve.floor_usd, 2),
        display=f"${curve.floor_usd:,.0f} ± ${curve.floor_sd_usd:,.0f}",
        observations=curve.observations,
        prior_share=round(curve.prior_share, 3),
        prior_label=curve.prior_label,
        uncertainty=round(curve.floor_sd_usd, 2),
        note=f"From {curve.evidence}.",
    )


def describe(key: str, label: str, estimate: Estimate, display: str, note: str | None = None) -> Prediction:
    return Prediction(
        key=key,
        label=label,
        value=round(estimate.value, 4),
        display=display,
        observations=estimate.observations,
        prior_share=round(estimate.prior_share, 3),
        prior_label=estimate.prior_label,
        uncertainty=round(estimate.sd, 4),
        note=note,
    )


def market_rate(history: BrokerHistory, equipment: Equipment) -> float | None:
    return market_rate_per_mile(history, equipment)
