"""Carrier ranking, in stages.

    eligibility  -> candidates -> components -> expected_value
    (hard gates)    (recall)      (per-outcome  (business costs,
                                   predictions)  offer rate, ranking)

Two engines are registered against one contract:

- `simple-heuristic`: a weighted sum of history signals. Ordinal, no units, needs
  no offer log.
- `expected-value`: the staged pipeline above, ranking by expected margin per hour
  of broker time and choosing the rate to offer.

Both are exposed at once on purpose. `?engine=` runs them over identical data so
the claim that the second is better is checkable rather than asserted, and the
first stays useful for a tenant whose offer log is empty.
"""

from __future__ import annotations

from .contracts import (
    CarrierRecommendation,
    Comparable,
    Confidence,
    CoverageDecision,
    EngineInfo,
    Exclusion,
    HistoryDepth,
    OfferPlan,
    Prediction,
    PriceEstimate,
    PriorOffer,
    Reason,
    RecommendationEngine,
    Recommendations,
    RepricingTarget,
    ScoreComponent,
    Sentiment,
    UncheckedGate,
    ValueTerm,
)
from .expected_value import ExpectedValueEngine
from .heuristic import SimpleHeuristicEngine
from .pricing import estimate_price

ENGINES: dict[str, RecommendationEngine] = {
    ExpectedValueEngine.info.key: ExpectedValueEngine(),
    SimpleHeuristicEngine.info.key: SimpleHeuristicEngine(),
}

DEFAULT_ENGINE_KEY = ExpectedValueEngine.info.key


def get_engine(key: str | None = None) -> RecommendationEngine:
    """The single seam. Swap the default here, or pass `?engine=` to compare
    implementations against each other on identical data."""
    return ENGINES[key or DEFAULT_ENGINE_KEY]


def engine_catalogue() -> list[EngineInfo]:
    return [engine.info for engine in ENGINES.values()]


__all__ = [
    "CarrierRecommendation",
    "Comparable",
    "Confidence",
    "CoverageDecision",
    "DEFAULT_ENGINE_KEY",
    "ENGINES",
    "EngineInfo",
    "Exclusion",
    "ExpectedValueEngine",
    "HistoryDepth",
    "OfferPlan",
    "Prediction",
    "PriceEstimate",
    "PriorOffer",
    "Reason",
    "RecommendationEngine",
    "Recommendations",
    "RepricingTarget",
    "ScoreComponent",
    "Sentiment",
    "SimpleHeuristicEngine",
    "UncheckedGate",
    "ValueTerm",
    "engine_catalogue",
    "estimate_price",
    "get_engine",
]
