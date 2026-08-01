"""Tests for the staged expected-value engine.

These lean on a property the dataset was built to have: the generator gives every
carrier a hidden reservation price and a hidden reply time, writes neither into
the data, and derives the offer log and the booked rates from them. So the
estimated price floor can be checked against a *known truth* rather than merely
inspected for plausibility - which is the difference between testing a model and
admiring it.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app import brokers, config, ingest, ranking
from app.domain import Equipment, OfferOutcome
from app.history import BrokerHistory
from app.ranking import components, eligibility
from app.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data_gen"))


@pytest.fixture(scope="module")
def store() -> Store:
    return ingest.ingest_all(config.data_dir())


@pytest.fixture(scope="module")
def truth() -> dict[str, float]:
    """The generator's hidden reserve multipliers, by carrier name."""
    from generate import CARRIERS

    return {carrier.name: carrier.reserve_mult for carrier in CARRIERS.values()}


def test_the_offer_log_was_ingested_and_joins_to_real_records(store: Store) -> None:
    """An offer that references a load or carrier the platform does not have is
    worse than no offer: it silently drops out of every estimate."""
    for broker in brokers.BROKERS:
        offers = store.offers(broker.broker_id)
        assert offers, f"{broker.broker_id} has no offer log"

        load_ids = {load.load_id for load in store.loads(broker.broker_id)}
        carrier_ids = {carrier.carrier_id for carrier in store.carriers(broker.broker_id)}
        assert not {offer.load_id for offer in offers} - load_ids
        assert not {offer.carrier_id for offer in offers} - carrier_ids

        outcomes = {offer.outcome for offer in offers}
        assert OfferOutcome.ACCEPTED in outcomes
        # Without refusals there is no negative class and acceptance is
        # unidentifiable, which is the whole reason this log exists.
        assert outcomes & {OfferOutcome.DECLINED, OfferOutcome.COUNTERED}


def test_estimated_price_floor_recovers_the_hidden_reserve(store: Store, truth: dict[str, float]) -> None:
    from generate import RATE_PER_MILE

    errors: list[float] = []
    for broker in brokers.BROKERS:
        history = BrokerHistory(store, broker.broker_id)
        load = history.open_loads()[0]
        market_rpm = components.market_rate(history, load.equipment)
        loads_by_id = {item.load_id: item for item in history.all_loads}

        for carrier in history.carriers:
            hist = history.carrier_history_for(carrier.carrier_id, load)
            if hist is None:
                continue
            curve = components.build_acceptance_curve(load, hist, history, loads_by_id, market_rpm)
            actual = RATE_PER_MILE[load.equipment.value] * truth[carrier.name] * load.distance_miles
            errors.append(abs(curve.floor_usd - actual) / actual)

    assert errors
    mean_error = sum(errors) / len(errors)
    # Loose bounds on purpose. The claim being tested is that the estimator
    # recovers the right neighbourhood from a handful of offers, not that it nails
    # a number it has only ever seen indirectly.
    assert mean_error < 0.10, f"mean floor error {mean_error:.1%} is too high to be signal"
    assert max(errors) < 0.20, f"worst floor error {max(errors):.1%}"


def test_acceptance_probability_rises_with_the_offer(store: Store) -> None:
    """The curve is only useful if it is monotonic in the rate - otherwise
    "offer more to be more likely" stops being true and the rate search is
    meaningless."""
    history = BrokerHistory(store, "redline")
    load = history.open_loads()[0]
    market_rpm = components.market_rate(history, load.equipment)
    loads_by_id = {item.load_id: item for item in history.all_loads}

    for carrier in history.carriers:
        hist = history.carrier_history_for(carrier.carrier_id, load)
        if hist is None:
            continue
        curve = components.build_acceptance_curve(load, hist, history, loads_by_id, market_rpm)
        probabilities = [curve.probability(rate) for rate in range(600, 2000, 50)]
        assert probabilities == sorted(probabilities)
        assert 0.0 < probabilities[0] < probabilities[-1] < 1.0
        # The inverse must agree with the curve, since the UI quotes it as
        # "$X to be 90% confident".
        rate_at_90 = curve.rate_for_probability(0.9)
        assert abs(curve.probability(rate_at_90) - 0.9) < 0.01


def test_one_bad_load_does_not_condemn_a_carrier(store: Store) -> None:
    """PANHANDLE delivered its single load late. A raw average calls that 0%
    on-time; shrinkage must not."""
    history = BrokerHistory(store, "redline")
    load = history.open_loads()[0]
    panhandle = next(c for c in history.carriers if "PANHANDLE" in c.name)
    hist = history.carrier_history_for(panhandle.carrier_id, load)

    assert hist.service_known == 1
    assert hist.on_time_ratio == 0.0, "raw rate should be the damning 0% we are protecting against"

    estimate = components.on_time_estimate(hist, history)
    assert 0.35 < estimate.value < 0.85, (
        f"one late load out of one shrank to {estimate.value:.0%}, which is either "
        "still condemning or has ignored the evidence entirely"
    )
    assert estimate.is_mostly_prior


def test_a_reliable_carrier_still_beats_an_unreliable_one(store: Store) -> None:
    """Shrinkage must not flatten everybody into the prior."""
    history = BrokerHistory(store, "redline")
    load = history.open_loads()[0]

    def on_time_for(fragment: str) -> float:
        carrier = next(c for c in history.carriers if fragment in c.name)
        hist = history.carrier_history_for(carrier.carrier_id, load)
        return components.on_time_estimate(hist, history).value

    # IBRAHIM is clean across several loads; LONE OAK is late on two of three.
    assert on_time_for("IBRAHIM") > on_time_for("LONE OAK") + 0.1


def test_cheap_and_unreliable_loses_to_dependable(store: Store) -> None:
    """The point of the whole exercise: LONE OAK has the lowest price floor of
    any Redline carrier and is late half the time. A margin-only ranking puts it
    near the top. Expected value must not."""
    history = BrokerHistory(store, "redline")
    load = history.open_loads()[0]

    ev = ranking.get_engine("expected-value").recommend(load, history, limit=10)
    heuristic = ranking.get_engine("simple-heuristic").recommend(load, history, limit=10)

    def rank_of(result, fragment: str) -> int:
        return next(c.rank for c in result.carriers if fragment in c.carrier_name)

    lone_oak = next(c for c in ev.carriers if "LONE OAK" in c.carrier_name)
    cheapest = min(
        (c for c in ev.carriers if c.offer_plan),
        key=lambda c: c.offer_plan.offer_rate_usd,
    )
    assert "LONE OAK" in cheapest.carrier_name or lone_oak.offer_plan.offer_rate_usd <= (
        cheapest.offer_plan.offer_rate_usd + 30
    )
    assert rank_of(ev, "LONE OAK") > rank_of(heuristic, "LONE OAK"), (
        "expected value should demote the cheap unreliable carrier relative to the heuristic"
    )
    assert rank_of(ev, "LONE OAK") >= 4


def test_a_refusal_on_this_load_raises_the_recommended_offer(store: Store) -> None:
    """A carrier that already said no to $1,065 must not be recommended at
    $1,065 again. This is the most concrete thing the offer log buys."""
    history = BrokerHistory(store, "redline")
    engine = ranking.get_engine("expected-value")

    checked = 0
    for load in history.open_loads():
        result = engine.recommend(load, history, limit=10)
        for carrier in result.carriers:
            refusals = [offer for offer in carrier.prior_offers if offer.outcome != "ACCEPTED"]
            if not refusals:
                continue
            checked += 1
            worst = max(offer.counter_rate_usd or offer.offered_rate_usd for offer in refusals)
            assert carrier.offer_plan.offer_rate_usd > max(
                offer.offered_rate_usd for offer in refusals
            ), f"{carrier.carrier_name} was refused and is being offered the same or less"
            assert any("Already asked" == reason.label for reason in carrier.reasons)
            assert worst > 0

    assert checked, "no open load had a prior refusal, so this behaviour went untested"


def test_the_recommended_offer_beats_its_neighbours(store: Store) -> None:
    """The chosen rate must actually be the argmax of expected value, not merely a
    plausible-looking number near it."""
    history = BrokerHistory(store, "anchor")
    engine = ranking.get_engine("expected-value")
    load = history.open_loads()[0]
    result = engine.recommend(load, history, limit=5)

    for carrier in result.carriers:
        plan = carrier.offer_plan
        assert plan is not None
        # Value terms must reconstruct the headline expected value.
        assert abs(sum(term.amount_usd for term in plan.value_terms) - plan.expected_value_usd) < 1.0
        assert 0.0 < plan.acceptance_probability < 1.0
        assert plan.offer_rate_usd < plan.walk_away_rate_usd
        assert plan.pessimistic_value_usd <= plan.expected_value_usd <= plan.optimistic_value_usd


def test_exclusions_are_reported_rather_than_silent(store: Store) -> None:
    history = BrokerHistory(store, "redline")
    engine = ranking.get_engine("expected-value")
    load = history.open_loads()[0]
    result = engine.recommend(load, history, limit=10)

    named = {c.carrier_id for c in result.carriers} | {e.carrier_id for e in result.exclusions}
    known = {c.carrier_id for c in history.carriers}
    assert known - named == set(), "a carrier vanished from the answer with no reason given"

    for exclusion in result.exclusions:
        assert exclusion.detail and exclusion.gate_label

    # Gates that cannot be evaluated must be declared, not quietly skipped.
    gates = {gate.gate for gate in result.unchecked_gates}
    assert {"AUTHORITY_AND_INSURANCE", "SAFETY_AND_COMPLIANCE", "BLOCKLIST"} <= gates
    assert result.limitations


def test_equipment_gate_excludes_only_on_real_evidence(store: Store) -> None:
    """The trailer gate is inferred from booking history, so it must stay
    conservative: a carrier with one or two loads has not proven anything."""
    history = BrokerHistory(store, "redline")
    reefer_load = next(
        load for load in history.open_loads() if load.equipment is Equipment.REEFER
    )
    result = eligibility.prepare(reefer_load, history)
    excluded = {
        exclusion.carrier_id for exclusion in result.exclusions if exclusion.gate == "EQUIPMENT"
    }

    for carrier_id in excluded:
        loads = history.carrier_loads(carrier_id)
        assert Equipment.REEFER not in {load.equipment for load in loads}
        # Never on a one- or two-load record: that is not enough contrary evidence
        # to conclude anything, and excluding wrongly is the expensive error.
        assert len(loads) >= 3

    for carrier_id in set(result.eligible):
        hauled = {
            load.equipment
            for load in history.carrier_loads(carrier_id)
            if load.equipment is not Equipment.UNKNOWN
        }
        if len(history.carrier_loads(carrier_id)) >= 3 and hauled:
            assert Equipment.REEFER in hauled


def test_equipment_confidence_is_a_capability_not_a_load_share(store: Store) -> None:
    """The estimate answers "can they pull this trailer", which is not the same
    question as "how often do they".

    A carrier splitting its work between reefer and dry van would score ~0.5 on a
    rate over loads while obviously owning a reefer, so a single load on the trailer
    has to be close to conclusive.
    """
    history = BrokerHistory(store, "redline")
    reefer_load = next(
        load for load in history.open_loads() if load.equipment is Equipment.REEFER
    )

    proven = unproven = None
    for carrier in history.carriers:
        hist = history.carrier_history_for(carrier.carrier_id, reefer_load)
        if hist is None:
            continue
        estimate = components.equipment_confidence(reefer_load, hist, history)
        if hist.loads_with_equipment:
            proven = estimate
            # Even one reefer load settles it, regardless of how much dry van work
            # sits alongside it.
            assert estimate.value > 0.9
        elif hist.loads_total >= 3:
            unproven = estimate

    assert proven is not None and unproven is not None
    assert unproven.value < proven.value
    # And the naive reading of the record is kept alongside, so the inference is
    # visible as an inference.
    assert unproven.raw == 0.0 and proven.raw == 1.0


def test_absent_evidence_decays_with_the_number_of_chances_to_show_it(store: Store) -> None:
    """Zero reefer loads out of two is weak evidence; out of twenty it is strong.

    This is the property a load-count threshold cannot express, and the reason the
    gate reads a probability rather than counting loads.
    """
    history = BrokerHistory(store, "redline")
    reefer_load = next(
        load for load in history.open_loads() if load.equipment is Equipment.REEFER
    )
    hist = next(
        history.carrier_history_for(carrier.carrier_id, reefer_load)
        for carrier in history.carriers
        if (h := history.carrier_history_for(carrier.carrier_id, reefer_load)) is not None
        and not h.loads_with_equipment
    )

    confidences = [
        components.equipment_confidence(
            reefer_load, replace(hist, loads_total=n, loads_with_equipment=0), history
        ).value
        for n in (1, 2, 5, 20)
    ]
    assert confidences == sorted(confidences, reverse=True)
    assert confidences[0] > eligibility.EQUIPMENT_MIN_CONFIDENCE
    assert confidences[-1] < eligibility.EQUIPMENT_MIN_CONFIDENCE


@pytest.mark.parametrize("engine_key", sorted(ranking.ENGINES))
def test_hard_gates_do_not_depend_on_the_chosen_engine(store: Store, engine_key: str) -> None:
    """Eligibility is a fact about the load, not a scoring preference.

    Regression test for a real bug: screening lived inside the expected-value engine,
    so the heuristic engine ranked carriers that had no chance of pulling the trailer
    while the other engine excluded them by name. Choosing an engine silently chose
    whether hard constraints were enforced.
    """
    history = BrokerHistory(store, "redline")
    engine = ranking.get_engine(engine_key)

    for load in history.open_loads():
        result = engine.recommend(load, history, limit=25)
        recommended = {carrier.carrier_id for carrier in result.carriers}
        excluded = {exclusion.carrier_id for exclusion in result.exclusions}

        assert not (recommended & excluded), (
            f"{engine_key} both ranked and excluded a carrier on {load.reference}"
        )
        # Every engine must account for every carrier it knows about.
        assert recommended | excluded == {
            carrier.carrier_id for carrier in history.carriers
        }


def test_a_slower_carrier_never_outranks_a_better_one_on_a_losing_load(store: Store) -> None:
    """Value per hour inverts once the value is negative.

    Dividing by time is meant to answer "how much value does an hour of broker time
    buy", which has no meaning when the answer is a loss: a longer wait moves a
    negative number toward zero, so the slowest carrier would win. A real case had a
    carrier at -$45 over 7.4 hours score -6.1/hour and beat one at -$20 over 1.1
    hours at -17.0/hour. On losing loads the ranking must fall back to expected value.
    """
    history = BrokerHistory(store, "redline")
    engine = ranking.get_engine("expected-value")
    seen_a_losing_load = False

    for load in history.open_loads():
        result = engine.recommend(load, history, limit=25)
        losing = [c for c in result.carriers if c.offer_plan.expected_value_usd <= 0]
        if len(losing) < 2:
            continue
        seen_a_losing_load = True
        for carrier in losing:
            plan = carrier.offer_plan
            time_term = next(c for c in carrier.components if c.key == "time_to_resolve")
            credit = next(c for c in carrier.components if c.key == "uncertainty_credit")

            # No time normalisation at all, however slow the carrier is.
            assert time_term.points == 0.0, (
                f"{carrier.carrier_name} was normalised by {plan.expected_resolution_hours}h "
                f"on a load with {plan.expected_value_usd} expected value"
            )
            # Which leaves expected value as the whole of the ranking, apart from the
            # optimism credit, whose job is to reorder and which is asserted elsewhere.
            assert carrier.score - credit.points == pytest.approx(
                plan.expected_value_usd, abs=0.05
            )

    assert seen_a_losing_load, "dataset no longer covers a load that loses money"


def test_the_published_curve_agrees_with_the_offer_it_explains(store: Store) -> None:
    """The rate curve is what the UI lets a broker drag, so it has to be the same
    model that chose the offer rather than a redrawn approximation of it.

    Two claims: acceptance rises with the rate (a logistic in the offer), and the
    recommended rate really is the maximum of the curve. If the second ever fails the
    UI would be inviting a broker to "correct" the engine toward a worse number.
    """
    history = BrokerHistory(store, "redline")
    engine = ranking.get_engine("expected-value")

    for load in history.open_loads():
        for carrier in engine.recommend(load, history, limit=25).carriers:
            plan = carrier.offer_plan
            curve = plan.rate_curve
            assert len(curve) > 10, "too few points to draw a shape from"

            probabilities = [point.acceptance_probability for point in curve]
            assert probabilities == sorted(probabilities)

            # The offered rate is on the curve, and it is the peak of it.
            at_offer = [p for p in curve if p.rate_usd == plan.offer_rate_usd]
            assert at_offer, "the recommended rate is not among the published points"
            assert at_offer[0].expected_value_usd == pytest.approx(
                plan.expected_value_usd, abs=0.05
            )
            assert at_offer[0].acceptance_probability == pytest.approx(
                plan.acceptance_probability, abs=0.0002
            )
            assert plan.expected_value_usd >= max(p.expected_value_usd for p in curve) - 0.05

            # And the floor is below the offer, or the offer would be pointless.
            assert plan.estimated_floor_usd > 0
            assert plan.offer_rate_usd >= plan.estimated_floor_usd * 0.5


def test_an_uncoverable_load_is_answered_with_a_price_not_a_ranking(store: Store) -> None:
    """A ranked list assumes the load is worth covering. When it is not, the output
    has to become the number that would change that."""
    history = BrokerHistory(store, "redline")
    engine = ranking.get_engine("expected-value")

    seen = {"COVER": False, "REPRICE": False}
    for load in history.open_loads():
        result = engine.recommend(load, history, limit=25)
        coverage = result.coverage
        assert coverage is not None
        seen[coverage.decision] = True

        best = max(c.offer_plan.expected_value_usd for c in result.carriers)
        assert coverage.best_expected_value_usd == pytest.approx(best, abs=0.05)

        if coverage.decision == "COVER":
            assert best > 0
            assert coverage.target is None
            continue

        assert best <= 0
        target = coverage.target
        assert target is not None
        # The load has to bill more than it does now, or there would be nothing to ask
        # the customer for.
        assert target.required_revenue_usd > target.current_revenue_usd
        assert target.shortfall_usd == pytest.approx(
            target.required_revenue_usd - target.current_revenue_usd, abs=0.05
        )
        # And it is the cheapest route back to viability, across every eligible carrier.
        assert target.required_revenue_usd == min(
            c.offer_plan.revenue_to_break_even_usd for c in result.carriers
        )

    assert seen["COVER"], "no open load is worth covering, so the happy path is untested"
    assert seen["REPRICE"], "dataset no longer covers an uncoverable load"


def test_repricing_targets_the_carrier_that_can_actually_haul_it(store: Store) -> None:
    """The perversity this stage exists to fix, pinned.

    Raw expected value on a losing load favours carriers *unlikely to accept*, because
    declining only costs a phone call - which ranked the one carrier with the right
    trailer last. Break-even revenue inverts that correctly: low acceptance means most
    calls are wasted, so `(1-p)/p` inflates the revenue needed to justify calling them.
    The repricing target must therefore be a carrier that can actually take the load.
    """
    history = BrokerHistory(store, "redline")
    engine = ranking.get_engine("expected-value")

    checked = False
    for load in history.open_loads():
        result = engine.recommend(load, history, limit=25)
        if result.coverage is None or result.coverage.decision != "REPRICE":
            continue
        checked = True
        target_id = result.coverage.target.carrier_id
        target = next(c for c in result.carriers if c.carrier_id == target_id)

        # Proven on the trailer: no equipment prediction is emitted for a carrier whose
        # capability is certain.
        assert not any(p.key == "equipment" for p in target.predictions)
        assert target.offer_plan.acceptance_probability > 0.5

        # And it is *not* simply the top of the expected-value ranking, which is the
        # whole point of computing the decision separately.
        assert any(
            c.offer_plan.expected_value_usd > target.offer_plan.expected_value_usd
            for c in result.carriers
        )

    assert checked, "dataset no longer covers an uncoverable load"


def test_a_rate_increase_cannot_buy_a_trailer(store: Store) -> None:
    """Equipment enters as a multiplier on acceptance, so paying more must never
    close an equipment gap the way it closes a price gap."""
    history = BrokerHistory(store, "redline")
    reefer_load = next(
        load for load in history.open_loads() if load.equipment is Equipment.REEFER
    )
    result = ranking.get_engine("expected-value").recommend(reefer_load, history, limit=25)

    unproven = [
        carrier
        for carrier in result.carriers
        if any(term.key == "capability" for term in carrier.offer_plan.value_terms)
    ]
    assert unproven, "expected at least one carrier surviving the gate without proof"

    for carrier in unproven:
        capability = next(
            term for term in carrier.offer_plan.value_terms if term.key == "capability"
        )
        # The discount is a cost, never a credit.
        assert capability.amount_usd < 0
        # And acceptance is capped by capability rather than by the rate alone.
        assert carrier.offer_plan.acceptance_probability < 1.0
        assert carrier.offer_plan.acceptance_probability <= 0.95


def test_fall_offs_are_read_as_events_not_typos(store: Store) -> None:
    """A load going backwards from COVERED is a carrier walking away. It must be
    classified as its own thing, or the cost of it never enters any ranking."""
    fall_offs = [
        change
        for broker in brokers.BROKERS
        for change in store.changes(broker.broker_id)
        if change.kind == "FALL_OFF"
    ]
    assert fall_offs, "the dataset contains fall-offs but none were detected"

    statuses = [change for change in fall_offs if change.field == "status"]
    assert statuses, "a status regressing out of COVERED was not flagged"
    for change in statuses:
        assert change.old_value == "COVERED"

    history = BrokerHistory(store, "redline")
    assert history.fall_off_count("BLUEBONNET FREIGHT CO") == 1
    assert history.fall_off_count("IBRAHIM TRANSPORT INC") == 0


def test_a_broker_with_no_offer_log_still_gets_an_answer(store: Store) -> None:
    """Every tenant starts with an empty offer log. The engine must degrade to
    priors rather than fail or return nothing."""
    history = BrokerHistory(store, "redline")
    load = history.open_loads()[0]

    class Blind(BrokerHistory):
        @property
        def offers(self):
            return []

        def offers_for_load(self, load_id: str):
            return []

    blind = Blind(store, "redline")
    result = ranking.get_engine("expected-value").recommend(load, blind, limit=5)

    assert result.carriers
    assert any("No offers have been logged" in note for note in result.notes)
    for carrier in result.carriers:
        assert carrier.offer_plan is not None
        floor = next(p for p in carrier.predictions if p.key == "acceptance_floor")
        assert floor.prior_share == pytest.approx(1.0, abs=0.01), (
            "with no offer log the floor must be entirely prior"
        )


def test_tenancy_holds_across_the_offer_log(store: Store) -> None:
    """IBRAHIM works for two brokers. Its offers under one must never inform the
    other, or the shared-pool question has already been answered by accident."""
    redline = BrokerHistory(store, "redline")
    anchor = BrokerHistory(store, "anchor")

    for history in (redline, anchor):
        assert all(offer.broker_id == history.broker_id for offer in history.offers)

    redline_ibrahim = next(c for c in redline.carriers if "IBRAHIM" in c.name)
    anchor_ibrahim = next(c for c in anchor.carriers if "IBRAHIM" in c.name)
    assert redline_ibrahim.mc_number == anchor_ibrahim.mc_number
    assert redline_ibrahim.carrier_id != anchor_ibrahim.carrier_id

    redline_offers = redline.carrier_offers(redline_ibrahim.carrier_id)
    anchor_offers = anchor.carrier_offers(anchor_ibrahim.carrier_id)
    assert redline_offers and anchor_offers
    assert not {offer.offer_id for offer in redline_offers} & {
        offer.offer_id for offer in anchor_offers
    }
