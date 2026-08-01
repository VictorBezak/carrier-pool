"""What each bad outcome is worth, in dollars.

Every number here is a business input, not a model output. They belong in one
small file because they are the part of the system a broker should argue with:
the ranking is sensitive to them, and changing one should not require retraining
or redeploying anything.

They are also the reason an expected-value ranking beats a weighted score. A
weight of 0.15 on "reliability" is unfalsifiable. Saying a late delivery costs
$275 is a claim someone can check against their own accessorial and claims data,
and be wrong about in a specific, fixable way.

Values below are plausible for regional dry van and reefer freight and are not
calibrated against real data, which no part of this dataset would support.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    # Goodwill, accessorials and the share of a late delivery that eventually
    # shows up as a lost customer. Deliberately larger than the direct cost.
    late_delivery_usd: float = 275.0
    # Re-covering a load after a carrier walks, usually at short notice and a
    # worse rate, plus the operational scramble.
    fall_off_usd: float = 425.0
    # A broker's time, applied to how long a carrier takes to answer. This is what
    # makes a fast mediocre carrier worth calling before a slow excellent one.
    broker_hourly_usd: float = 42.0
    # Not modelled: no feed carries claims, tracking compliance or intervention
    # effort. Left at zero and stated, rather than guessed at, so the gap is
    # visible in the output instead of buried in a constant.
    claim_usd: float = 0.0
    operational_usd: float = 0.0

    def unmodelled(self) -> list[str]:
        return [
            "Claims risk is not modelled: no feed records claims, damage or their cost.",
            "Tracking and communication reliability are not modelled: no feed records them.",
            "Operational effort per carrier is not modelled: no feed records broker touches.",
        ]


DEFAULT = CostModel()
