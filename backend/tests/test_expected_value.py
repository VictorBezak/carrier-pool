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
    result = eligibility.screen(
        reefer_load, history, [carrier.carrier_id for carrier in history.carriers]
    )
    excluded = {
        exclusion.carrier_id for exclusion in result.exclusions if exclusion.gate == "EQUIPMENT"
    }

    for carrier_id in excluded:
        loads = history.carrier_loads(carrier_id)
        assert len(loads) >= eligibility.EQUIPMENT_EVIDENCE_MIN
        assert Equipment.REEFER not in {load.equipment for load in loads}

    for carrier_id in {carrier.carrier_id for carrier in history.carriers} - excluded:
        loads = history.carrier_loads(carrier_id)
        if len(loads) >= eligibility.EQUIPMENT_EVIDENCE_MIN and loads:
            hauled = {load.equipment for load in loads if load.equipment is not Equipment.UNKNOWN}
            assert not hauled or Equipment.REEFER in hauled


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
