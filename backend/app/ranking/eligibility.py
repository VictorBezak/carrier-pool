"""Stage A: hard gates.

A carrier that cannot legally or physically take the load does not belong at the
bottom of a ranked list - it belongs off the list, with a reason attached. Making
these gates rather than score penalties is the difference between a list a
dispatcher can act on and one they have to double-check.

The honest part of this module is what it *cannot* do. Several gates that any
real system must enforce - operating authority, insurance, safety scores, do-not-
use flags - have no source in any of the three TMS feeds. They are declared as
unchecked gates rather than quietly omitted, because an unstated missing gate is
how a broker ends up tendering to a carrier whose insurance lapsed.

The gates that *are* enforced are inferred from booking history, which is weaker
than a capability record. Each one is therefore deliberately conservative: it
fires only where the evidence is strong enough that a dispatcher would agree.

The trailer gate is the clearest case of that weakness, and it is handled by
admitting it rather than papering over it. Nothing here records what equipment a
carrier owns, only what it has hauled, so the gate reads a *probability* computed
in `components` and excludes below a threshold. The same estimate then flows into
ranking, which means the gate and the score can never disagree about whether a
carrier can pull a reefer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import geo
from ..domain import Equipment, Load
from ..history import BrokerHistory
from . import candidates, components
from .contracts import Exclusion, UncheckedGate

# Below this estimated probability of having the required trailer, a carrier is
# excluded rather than ranked low.
#
# A threshold on a probability rather than a rule about load counts, because the
# amount of evidence "no reefer loads" represents depends on how many loads there
# were and how often this broker even offers reefer work. At the volumes in this
# dataset it happens to bite at around three contrary loads, but it tightens on its
# own for a broker whose freight is mostly reefer, where two dry van loads already
# say something.
EQUIPMENT_MIN_CONFIDENCE = 0.12
# Practical payload ceilings by trailer type, in pounds.
#
# Deliberately *not* derived from what a carrier has hauled before. Every dry van
# has roughly the same capacity, so "heavier than its previous heaviest load" says
# nothing about capability - an earlier version of this gate used that rule and
# excluded a perfectly capable carrier because its last few loads were light.
# A gate that fires on a plausible-sounding proxy is worse than no gate: it is
# wrong in a way that looks authoritative.
EQUIPMENT_PAYLOAD_LBS = {
    Equipment.DRY_VAN: 45_000.0,
    Equipment.REEFER: 43_500.0,
    Equipment.FLATBED: 48_000.0,
}
# Deadhead radius within which a carrier counts as serving a market.
SERVICE_AREA_MILES = 150.0
# Planning speed for feasibility, plus the slack a dispatcher would insist on.
PLANNING_MPH = 45.0
PICKUP_BUFFER_HOURS = 2.0


UNCHECKED_GATES = [
    UncheckedGate(
        gate="AUTHORITY_AND_INSURANCE",
        gate_label="Operating authority and insurance",
        detail=(
            "Cannot be checked. No feed carries authority status, insurance certificates or "
            "coverage limits, so this gate is not enforced anywhere in the pipeline."
        ),
    ),
    UncheckedGate(
        gate="SAFETY_AND_COMPLIANCE",
        gate_label="Safety rating, fraud and identity",
        detail=(
            "Cannot be checked. No feed carries safety scores, inspection history or identity "
            "verification, and none of it is derivable from load records."
        ),
    ),
    UncheckedGate(
        gate="BLOCKLIST",
        gate_label="Broker or shipper blocklist",
        detail=(
            "Cannot be checked. A carrier a broker has banned looks identical to one it simply "
            "has not used lately."
        ),
    ),
    UncheckedGate(
        gate="TRUCK_AVAILABILITY",
        gate_label="Confirmed truck availability",
        detail=(
            "Cannot be checked. No feed reports capacity, so availability is inferred from where "
            "a carrier's last load ended and treated as a probability, not a fact."
        ),
    ),
    UncheckedGate(
        gate="COMMODITY_AND_HAZMAT",
        gate_label="Commodity compatibility and endorsements",
        detail=(
            "Cannot be checked. Commodity is a free-text description with no hazmat class or "
            "temperature requirement attached."
        ),
    ),
]


@dataclass(frozen=True)
class Screening:
    """The candidate set every engine is given, and everything ruled out of it.

    Produced once per request and shared by all engines. Eligibility is a property
    of the load and the carrier, not of a scoring strategy, so leaving it inside an
    engine meant whether a hard constraint got enforced depended on which engine
    the caller happened to pick — the heuristic would happily rank a carrier the
    expected-value engine excluded as unable to haul the freight.
    """

    eligible: list[str]
    surfaced_by: dict[str, list[str]]
    exclusions: list[Exclusion]
    unchecked_gates: list[UncheckedGate]


def prepare(load: Load, history: BrokerHistory) -> Screening:
    pool = candidates.generate(load, history)
    surfaced_by = {item.carrier_id: item.surfaced_by for item in pool}

    eligible: list[str] = []
    exclusions: list[Exclusion] = []

    for item in pool:
        carrier = history.carrier(item.carrier_id)
        if carrier is None:
            continue
        carrier_history = history.carrier_history_for(item.carrier_id, load)
        loads = history.carrier_loads(item.carrier_id)
        failure = (
            _equipment_gate(load, carrier_history, history)
            or _weight_gate(load, loads)
            or _service_area_gate(load, loads, carrier.home_market)
            or _pickup_feasibility_gate(load, loads, history)
        )
        if failure is None:
            eligible.append(item.carrier_id)
        else:
            gate, gate_label, detail = failure
            exclusions.append(
                Exclusion(
                    carrier_id=item.carrier_id,
                    carrier_name=carrier.name,
                    gate=gate,
                    gate_label=gate_label,
                    detail=detail,
                )
            )

    surfaced = {item.carrier_id for item in pool}
    exclusions.extend(
        Exclusion(
            carrier_id=carrier.carrier_id,
            carrier_name=carrier.name,
            gate="NO_HISTORY",
            gate_label="No booking history",
            detail=(
                "Known to this broker but never booked and never offered a load, so no "
                "component can be estimated for them. A carrier in this state needs "
                "deliberate exploration, not a score."
            ),
        )
        for carrier in history.carriers
        if carrier.carrier_id not in surfaced
    )

    return Screening(
        eligible=eligible,
        surfaced_by=surfaced_by,
        exclusions=exclusions,
        unchecked_gates=UNCHECKED_GATES,
    )


def _equipment_gate(
    load: Load, carrier_history, history: BrokerHistory
) -> tuple[str, str, str] | None:
    """Exclude only when the carrier probably cannot cover the trailer.

    The gate reads a probability rather than deciding one, so the same estimate the
    ranking layer uses is the one that does the excluding. Letting a possibly
    unequipped carrier through to be ranked low costs one evaluation; excluding one
    that does own the trailer removes it permanently.
    """
    if load.equipment is Equipment.UNKNOWN or carrier_history is None:
        return None

    confidence = components.equipment_confidence(load, carrier_history, history)
    if confidence.value >= EQUIPMENT_MIN_CONFIDENCE:
        return None

    needed = load.equipment.value.replace("_", " ").lower()
    hauled = {
        item.equipment
        for item in history.carrier_loads(carrier_history.carrier.carrier_id)
        if item.equipment is not Equipment.UNKNOWN
    }
    had = ", ".join(sorted(item.value.replace("_", " ").lower() for item in hauled))
    return (
        "EQUIPMENT",
        "Trailer type",
        f"Needs a {needed}, and roughly a {confidence.value * 100:.0f}% chance of having one: "
        f"all {confidence.observations} of its loads for this broker were {had}. "
        f"No feed records what equipment a carrier owns, so this is inferred.",
    )


def _weight_gate(load: Load, loads: list[Load]) -> tuple[str, str, str] | None:
    """Payload against what the trailer type can legally carry.

    This is a gate on the *load*, not on the carrier, which is the honest scope:
    nothing in the feeds describes an individual carrier's equipment. It binds
    rarely, and that is the correct behaviour rather than a sign it is useless.
    """
    ceiling = EQUIPMENT_PAYLOAD_LBS.get(load.equipment)
    if load.weight_lbs is None or ceiling is None:
        return None
    if load.weight_lbs <= ceiling:
        return None
    return (
        "WEIGHT_CAPACITY",
        "Weight capacity",
        f"Load is {load.weight_lbs:,.0f} lbs, over the {ceiling:,.0f} lb payload a "
        f"{load.equipment.value.replace('_', ' ').lower()} can carry.",
    )


def _service_area_gate(
    load: Load, loads: list[Load], home_market: str | None
) -> tuple[str, str, str] | None:
    origin = load.origin_market
    if origin == geo.UNKNOWN_MARKET:
        return None

    known = {item.origin_market for item in loads} | {item.destination_market for item in loads}
    if home_market:
        known.add(home_market)
    known.discard(geo.UNKNOWN_MARKET)
    if not known:
        return None
    if origin in known:
        return None

    nearest = min(
        (
            (geo.market_distance_miles(market, origin) or 9_999, market)
            for market in known
        ),
        default=(9_999, None),
    )
    distance, market = nearest
    if distance <= SERVICE_AREA_MILES:
        return None
    return (
        "SERVICE_AREA",
        "Service area",
        f"Has never operated within {SERVICE_AREA_MILES:g} miles of {geo.market_label(origin)}; "
        f"the closest is {geo.market_label(market)} at roughly {distance:g} miles."
        if market
        else f"Has never operated near {geo.market_label(origin)}.",
    )


def _pickup_feasibility_gate(
    load: Load, loads: list[Load], history: BrokerHistory
) -> tuple[str, str, str] | None:
    """Can the truck physically get there before the appointment closes?

    Position is the market its most recent load delivered into, which is a guess:
    the truck may have moved since on freight this broker never saw. So the gate
    only fires when the shortfall is large enough that no plausible repositioning
    would close it.
    """
    appointment = load.origin.appointment if load.origin else None
    if appointment is None or load.origin_market == geo.UNKNOWN_MARKET:
        return None

    dated = [(item.delivered_at, item) for item in loads if item.delivered_at]
    if not dated:
        return None
    dated.sort(key=lambda pair: pair[0])
    last_at, last_load = dated[-1]
    position = last_load.destination_market
    if position == geo.UNKNOWN_MARKET:
        return None

    deadhead = geo.market_distance_miles(position, load.origin_market)
    if not deadhead:
        return None

    hours_available = (appointment - max(last_at, history.as_of)).total_seconds() / 3600
    hours_needed = deadhead / PLANNING_MPH + PICKUP_BUFFER_HOURS
    if hours_available >= hours_needed:
        return None
    return (
        "PICKUP_FEASIBILITY",
        "Can reach the pickup",
        f"Needs roughly {hours_needed:.0f}h to cover {deadhead:g} deadhead miles from "
        f"{geo.market_label(position)}, but the pickup appointment is {hours_available:.0f}h away.",
    )
