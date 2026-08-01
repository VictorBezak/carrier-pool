"""Stage B: candidate generation.

At this data volume every carrier a broker knows is a candidate, so this module
changes no answers today. It exists for two reasons that outlive the toy dataset.

First, the interface. A brokerage with 30,000 carriers cannot afford to run the
component models over all of them per load, and retrofitting a recall stage into
a system that assumed it could score everything is a rewrite. Second, the
reporting: each candidate carries the rules that surfaced it, which is how you
later diagnose *recall* failures - the eventual best carrier never being scored
at all is the one error that leaves no trace in the output.

Candidate generation optimises recall, deliberately. A cheap rule that lets
through a carrier the next stage rejects costs one model evaluation. A rule that
drops the best carrier costs the load.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import geo
from ..domain import Equipment, Load
from ..history import BrokerHistory

NEARBY_MILES = 200.0
RECENT_DAYS = 14.0


@dataclass
class Candidate:
    carrier_id: str
    surfaced_by: list[str] = field(default_factory=list)


def generate(load: Load, history: BrokerHistory) -> list[Candidate]:
    found: dict[str, Candidate] = {}

    def surface(carrier_id: str, rule: str) -> None:
        candidate = found.setdefault(carrier_id, Candidate(carrier_id=carrier_id))
        if rule not in candidate.surfaced_by:
            candidate.surfaced_by.append(rule)

    for carrier in history.carriers:
        loads = history.carrier_loads(carrier.carrier_id)
        if not loads:
            # Known to the broker but never booked. There is nothing to reason
            # from, and no offer history either, so it cannot be scored - only
            # explored. Left out, and reported as such by the engine.
            continue

        if any(item.lane == load.lane for item in loads):
            surface(carrier.carrier_id, "Runs this lane")
        if any(item.origin_market == load.origin_market for item in loads):
            surface(carrier.carrier_id, "Picks up in this market")
        if any(item.destination_market == load.destination_market for item in loads):
            surface(carrier.carrier_id, "Delivers into this market")
        if load.equipment is not Equipment.UNKNOWN and any(
            item.equipment == load.equipment for item in loads
        ):
            surface(carrier.carrier_id, "Has the trailer type")

        last = max((item.delivered_at for item in loads if item.delivered_at), default=None)
        if last is not None:
            days = (history.as_of - last).total_seconds() / 86400
            if days <= RECENT_DAYS:
                surface(carrier.carrier_id, "Active recently")
            ending = [item for item in loads if item.delivered_at == last]
            if ending:
                distance = geo.market_distance_miles(
                    ending[0].destination_market, load.origin_market
                )
                if distance is not None and distance <= NEARBY_MILES:
                    surface(carrier.carrier_id, "Truck likely nearby")

        if carrier.home_market and carrier.home_market == load.origin_market:
            surface(carrier.carrier_id, "Based in this market")

        # Anyone with a booking relationship is worth a call even when no
        # specific rule fired. At scale this is the rule that would be dropped
        # first, and the one whose removal needs measuring.
        surface(carrier.carrier_id, "Has worked with this broker")

    return list(found.values())
