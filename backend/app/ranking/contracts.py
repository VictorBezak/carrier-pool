"""The contract every ranking engine answers in.

This file is the reason a scoring change is cheap. The API, the UI and the tests
depend on these shapes, not on any particular way of arriving at them, so a
weighted heuristic and an expected-value model can be swapped for one another or
run side by side on the same data.

Two things are deliberately mandatory rather than optional:

- an engine must decompose its answer into named parts that reconstruct the
  headline number, so the explanation and the arithmetic cannot drift apart;
- an engine must say what it *excluded* and why. A carrier missing from a list
  with no reason given is indistinguishable from a bug.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from ..domain import Equipment, Load

Sentiment = Literal["positive", "neutral", "negative"]
Confidence = Literal["high", "medium", "low"]


class Reason(BaseModel):
    """One human-readable justification. `points` is how much this contributed
    to the score, so the explanation and the arithmetic cannot drift apart.

    `kind` separates what a dispatcher needs before dialling from what they need
    only when arguing with the answer. The three sorts are genuinely different
    questions: what to say on the call, where the estimate came from, and what this
    carrier is actually like. A UI that renders all three at one weight ends up
    restating its own headline in prose, which is most of how a page gets dense.
    """

    label: str
    detail: str
    sentiment: Sentiment
    points: float | None = None
    kind: Literal["offer", "basis", "carrier"] = "carrier"


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


class Exclusion(BaseModel):
    """A carrier that was ruled out before scoring, and the rule that did it.

    Kept as first-class output rather than filtered away silently: a dispatcher
    who expects to see a carrier needs to know it was considered and rejected,
    and on what grounds, or they will stop trusting the list.
    """

    carrier_id: str
    carrier_name: str
    gate: str
    gate_label: str
    detail: str


class UncheckedGate(BaseModel):
    """A hard constraint that should be enforced and cannot be, because no feed
    carries the data. Reported so its absence is a known gap rather than an
    unstated assumption."""

    gate: str
    gate_label: str
    detail: str


class Prediction(BaseModel):
    """One component estimate, with the evidence behind it.

    `prior_share` is how much of this number came from the population rather than
    from this carrier. A prediction that is 80% prior is a statement about
    carriers in general, and saying so is the difference between a useful
    estimate and a misleading one.
    """

    key: str
    label: str
    value: float
    display: str
    observations: int
    prior_share: float
    prior_label: str
    uncertainty: float
    note: str | None = None


class ValueTerm(BaseModel):
    """One line of the expected-value arithmetic, in dollars."""

    key: str
    label: str
    amount_usd: float
    detail: str


class RatePoint(BaseModel):
    """One point on the acceptance curve, sampled from the engine's own model.

    Sampled server-side rather than refitted in the browser. The curve is the
    engine's central object, and a second implementation of it in JavaScript could
    disagree with the one that produced the recommendation - which is the same class
    of bug as having two notions of whether a carrier owns a reefer.
    """

    rate_usd: float
    acceptance_probability: float
    expected_value_usd: float


class OfferPlan(BaseModel):
    """The recommendation's actual content: who to call, and what to say.

    The rate is chosen, not predicted. It is the value that maximises expected
    value given this carrier's estimated price floor, which is the only lever the
    broker actually controls.
    """

    offer_rate_usd: float
    acceptance_probability: float
    expected_value_usd: float
    value_terms: list[ValueTerm]
    # Expected value if the carrier's true floor is at the optimistic and
    # pessimistic ends of its estimated range. The width is the honest cost of
    # thin evidence.
    optimistic_value_usd: float
    pessimistic_value_usd: float
    expected_resolution_hours: float | None
    value_per_hour_usd: float | None
    rate_ceiling_usd: float
    walk_away_rate_usd: float
    # The customer rate at which calling this carrier becomes worth doing. Above the
    # load's actual revenue this is what the load is short by, which is the only
    # actionable number on a load that cannot be covered profitably.
    revenue_to_break_even_usd: float | None
    # Where this carrier's price is estimated to start, which is what the offer is
    # chosen relative to.
    estimated_floor_usd: float
    # The trade-off the offer was picked from, so a broker can see the shape of it
    # rather than being handed a single number to trust.
    rate_curve: list[RatePoint] = Field(default_factory=list)


class RepricingTarget(BaseModel):
    """The cheapest way to turn an uncoverable load into a coverable one."""

    carrier_id: str
    carrier_name: str
    current_revenue_usd: float
    required_revenue_usd: float
    shortfall_usd: float
    shortfall_pct: float
    offer_rate_usd: float
    acceptance_probability: float


class CoverageDecision(BaseModel):
    """Whether to work this load at all, decided before deciding who to call.

    A ranked list assumes the load is worth covering. When it is not, ordering
    carriers answers the wrong question, so the decision is made explicitly and
    published alongside the list rather than inferred from it.
    """

    decision: Literal["COVER", "REPRICE"]
    headline: str
    detail: str
    best_expected_value_usd: float
    target: RepricingTarget | None = None


class PriorOffer(BaseModel):
    """Something already asked of this carrier on this load."""

    offered_rate_usd: float
    outcome: str
    counter_rate_usd: float | None
    response_minutes: float | None
    offered_at: datetime


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
    # Populated by expected-value engines; absent for the plain heuristic.
    offer_plan: OfferPlan | None = None
    predictions: list[Prediction] = Field(default_factory=list)
    prior_offers: list[PriorOffer] = Field(default_factory=list)
    surfaced_by: list[str] = Field(default_factory=list)


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
    # What this engine optimises. Two engines can rank the same data differently
    # and both be right, if they are answering different questions.
    objective: str | None = None


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
    # Null for engines with no notion of value, which cannot tell a load worth
    # covering from one that is not.
    coverage: CoverageDecision | None = None
    notes: list[str] = Field(default_factory=list)
    exclusions: list[Exclusion] = Field(default_factory=list)
    unchecked_gates: list[UncheckedGate] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class RecommendationEngine(Protocol):
    info: EngineInfo

    def recommend(self, load: Load, history: "BrokerHistory", limit: int) -> Recommendations: ...


# Imported late: BrokerHistory imports nothing from this module, but the type is
# only needed for the protocol signature above.
from ..history import BrokerHistory  # noqa: E402
