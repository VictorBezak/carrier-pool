"""Empirical-Bayes shrinkage.

The single most dangerous thing you can do with carrier data is take a raw
average. A carrier that delivered one load on time is not a 100% on-time
carrier, and one that was late once is not a 0% on-time carrier - but a mean
says exactly that, and it says it with total confidence.

Everything here pulls a small sample toward a prior drawn from the most specific
context that has enough data to be worth trusting. Two properties matter for the
rest of the system:

- the amount of shrinkage applied is reported, not hidden, so a recommendation
  can say "this is mostly the lane average, because we have two loads";
- an uncertainty comes out alongside the estimate, which is what lets the ranking
  layer be optimistic or cautious on purpose rather than by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class PriorLevel:
    """One rung of a prior hierarchy: a context, and what was observed in it."""

    label: str
    total: float
    observations: int

    @property
    def mean(self) -> float | None:
        if self.observations == 0:
            return None
        return self.total / self.observations


@dataclass(frozen=True)
class Estimate:
    """A shrunk quantity that can explain itself."""

    value: float
    raw: float | None
    observations: int
    prior: float
    prior_label: str
    # 0 = the answer is entirely the carrier's own record, 1 = entirely the prior.
    prior_share: float
    sd: float

    @property
    def is_mostly_prior(self) -> bool:
        return self.prior_share >= 0.5

    def band(self, sigmas: float = 1.0) -> tuple[float, float]:
        return self.value - sigmas * self.sd, self.value + sigmas * self.sd


def resolve_prior(levels: list[PriorLevel], minimum: int = 3) -> PriorLevel:
    """Walk a hierarchy narrow-to-wide and take the first rung with enough data.

    Ordering the levels from most to least specific is the caller's job, because
    what counts as "specific" differs per quantity: for on-time performance the
    lane matters most, for price the equipment does.

    The last level is the fallback and is returned even if it is thin - by that
    point there is nothing wider to back off to.
    """
    for level in levels:
        if level.observations >= minimum:
            return level
    return levels[-1]


def shrink_rate(
    successes: float,
    observations: int,
    prior: float,
    prior_label: str,
    prior_weight: float = 4.0,
) -> Estimate:
    """Beta-binomial posterior for a success rate.

    `prior_weight` is how many observations the prior is worth. At 4, a carrier
    needs four loads of its own before its record outweighs the population it was
    drawn from, which is roughly where a broker's own intuition sits.
    """
    alpha = successes + prior_weight * prior
    beta = (observations - successes) + prior_weight * (1 - prior)
    total = alpha + beta
    value = alpha / total if total else prior
    sd = sqrt(alpha * beta / (total * total * (total + 1))) if total > 0 else 0.5
    return Estimate(
        value=value,
        raw=(successes / observations) if observations else None,
        observations=observations,
        prior=prior,
        prior_label=prior_label,
        prior_share=prior_weight / (observations + prior_weight),
        sd=sd,
    )


def shrink_mean(
    values: list[float],
    prior: float,
    prior_label: str,
    prior_weight: float = 3.0,
    prior_sd: float | None = None,
    evidence: float | None = None,
) -> Estimate:
    """Normal-normal shrinkage for a continuous quantity.

    Used for things like response time and price floors, where the question is
    not "how often" but "how much".

    `evidence` decouples how much a sample is *worth* from how many numbers it
    arrived as. A price floor derived from nine offers is a single value but nine
    observations' worth of support, and weighting it as one data point would
    shrink a well-evidenced estimate as hard as a guess.
    """
    observations = len(values)
    raw = sum(values) / observations if observations else None
    support = float(evidence if evidence is not None else observations)
    value = ((raw * support) + prior * prior_weight) / (support + prior_weight) if support else prior

    if observations >= 2:
        spread = sqrt(sum((item - raw) ** 2 for item in values) / (observations - 1))
    else:
        # A single value says nothing about spread, so the prior's own spread is
        # the only honest answer.
        spread = prior_sd if prior_sd is not None else abs(prior) * 0.25
    sd = spread / sqrt(support + prior_weight)

    return Estimate(
        value=value,
        raw=raw,
        observations=int(support) if evidence is not None else observations,
        prior=prior,
        prior_label=prior_label,
        prior_share=prior_weight / (support + prior_weight),
        sd=sd,
    )
