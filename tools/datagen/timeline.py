from __future__ import annotations

from datetime import datetime, time, timedelta

from .cast import RELIABILITY_BIAS_HOURS, TOTAL_SLOTS, road_miles, slot_datetime
from .models import CanonicalStatus, LoadEvent, LoadSpec

STATUS_ORDER = {
    CanonicalStatus.PLANNED: 0,
    CanonicalStatus.ACTIVE: 1,
    CanonicalStatus.COVERED: 2,
    CanonicalStatus.AT_SHIPPER: 3,
    CanonicalStatus.IN_TRANSIT: 4,
    CanonicalStatus.AT_RECEIVER: 5,
    CanonicalStatus.DELIVERED: 6,
    CanonicalStatus.INVOICED: 7,
    CanonicalStatus.COMPLETED: 8,
}


def next_sync_slot(when: datetime) -> int:
    for slot in range(TOTAL_SLOTS):
        if slot_datetime(slot) >= when:
            return slot
    return TOTAL_SLOTS


def _physical_schedule(spec: LoadSpec, created_at: datetime) -> dict[str, datetime]:
    pickup_date = created_at.date() + timedelta(days=1)
    pickup_open = datetime.combine(pickup_date, time(8, 0), created_at.tzinfo)
    pickup_close = datetime.combine(pickup_date, time(16, 0), created_at.tzinfo)
    carrier_key = spec.reassigned_carrier or spec.carrier
    bias = RELIABILITY_BIAS_HOURS.get(carrier_key or "", 0.75)
    # Deterministic small variation keeps profiles visible without making every load identical.
    variation = ((sum(ord(char) for char in spec.key) % 5) - 2) * 0.25
    pickup_arrived = pickup_open + timedelta(hours=max(0.0, 1.0 + bias * 0.25 + variation))
    pickup_departed = pickup_open + timedelta(hours=7.0 + bias + variation)
    if pickup_departed < pickup_open:
        pickup_departed = pickup_open + timedelta(minutes=30)

    transit_hours = max(1.5, road_miles(spec.pickup, spec.delivery) / 45.0 + 1.0)
    delivery_date = pickup_date + timedelta(days=1)
    delivery_open = datetime.combine(delivery_date, time(8, 0), created_at.tzinfo)
    delivery_close = datetime.combine(delivery_date, time(16, 0), created_at.tzinfo)
    delivery_arrived = delivery_open + timedelta(hours=1.0 + bias * 0.5 + variation)
    earliest_arrival = pickup_departed + timedelta(hours=transit_hours)
    if delivery_arrived < earliest_arrival:
        delivery_arrived = earliest_arrival

    return {
        "pickup_open": pickup_open,
        "pickup_close": pickup_close,
        "pickup_arrived": pickup_arrived,
        "pickup_departed": pickup_departed,
        "delivery_open": delivery_open,
        "delivery_close": delivery_close,
        "delivery_arrived": delivery_arrived,
    }


def expand_load(spec: LoadSpec) -> list[LoadEvent]:
    created_at = slot_datetime(spec.start_slot) - timedelta(hours=2, minutes=17)
    schedule = _physical_schedule(spec, created_at)

    if spec.lifecycle == "day11":
        event_plan = ((spec.start_slot, CanonicalStatus.ACTIVE, spec.carrier),)
    elif spec.lifecycle == "full":
        event_plan = (
            (spec.start_slot, CanonicalStatus.PLANNED, spec.carrier),
            (min(spec.start_slot + 1, TOTAL_SLOTS - 1), CanonicalStatus.ACTIVE, spec.carrier),
            (min(spec.start_slot + 2, TOTAL_SLOTS - 1), CanonicalStatus.COVERED, spec.carrier),
            (next_sync_slot(schedule["pickup_arrived"]), CanonicalStatus.AT_SHIPPER, spec.carrier),
            (next_sync_slot(schedule["pickup_departed"]), CanonicalStatus.IN_TRANSIT, spec.reassigned_carrier or spec.carrier),
            (next_sync_slot(schedule["delivery_arrived"]), CanonicalStatus.AT_RECEIVER, spec.reassigned_carrier or spec.carrier),
            (next_sync_slot(schedule["delivery_arrived"] + timedelta(hours=6)), CanonicalStatus.DELIVERED, spec.reassigned_carrier or spec.carrier),
            (next_sync_slot(schedule["delivery_arrived"] + timedelta(hours=12)), CanonicalStatus.INVOICED, spec.reassigned_carrier or spec.carrier),
            (next_sync_slot(schedule["delivery_arrived"] + timedelta(hours=24)), CanonicalStatus.COMPLETED, spec.reassigned_carrier or spec.carrier),
        )
    elif spec.lifecycle == "covered_only":
        event_plan = ((spec.start_slot, CanonicalStatus.COVERED, spec.carrier),)
    else:
        covered_slot = min(spec.start_slot + 1, TOTAL_SLOTS - 1)
        delivered_slot = next_sync_slot(schedule["delivery_arrived"] + timedelta(hours=6))
        completed_slot = next_sync_slot(schedule["delivery_arrived"] + timedelta(hours=18))
        event_plan = (
            (spec.start_slot, CanonicalStatus.ACTIVE, spec.carrier),
            (covered_slot, CanonicalStatus.COVERED, spec.carrier),
            (delivered_slot, CanonicalStatus.DELIVERED, spec.reassigned_carrier or spec.carrier),
            (completed_slot, CanonicalStatus.COMPLETED, spec.reassigned_carrier or spec.carrier),
        )

    if spec.reassigned_carrier and spec.lifecycle != "day11":
        reassign_slot = min(next_sync_slot(schedule["pickup_open"] - timedelta(hours=6)), TOTAL_SLOTS - 1)
        event_plan = (*event_plan, (reassign_slot, CanonicalStatus.COVERED, spec.reassigned_carrier))

    events: list[LoadEvent] = []
    for slot, status, carrier_key in sorted(set(event_plan), key=lambda item: (item[0], item[1].value)):
        if slot >= TOTAL_SLOTS:
            continue
        visible_buy = spec.buy_usd if status not in {CanonicalStatus.PLANNED, CanonicalStatus.ACTIVE} else None
        modified_at = slot_datetime(slot) - timedelta(minutes=43)
        events.append(
            LoadEvent(
                spec=spec,
                slot=slot,
                status=status,
                carrier_key=carrier_key if status not in {CanonicalStatus.PLANNED, CanonicalStatus.ACTIVE} else None,
                buy_usd=visible_buy,
                created_at=created_at,
                modified_at=modified_at,
                pickup_open_at=schedule["pickup_open"],
                pickup_close_at=schedule["pickup_close"],
                pickup_arrived_at=schedule["pickup_arrived"],
                pickup_departed_at=schedule["pickup_departed"],
                delivery_open_at=schedule["delivery_open"],
                delivery_close_at=schedule["delivery_close"],
                delivery_arrived_at=schedule["delivery_arrived"],
            )
        )

    if spec.correction_delta_usd:
        correction_slot = next_sync_slot(schedule["delivery_arrived"] + timedelta(hours=30))
        if correction_slot >= TOTAL_SLOTS:
            return _latest_per_sync(events)
        corrected_buy = round((spec.buy_usd or 0) + spec.correction_delta_usd, 2)
        events.append(
            LoadEvent(
                spec=spec,
                slot=correction_slot,
                status=CanonicalStatus.COMPLETED,
                carrier_key=spec.reassigned_carrier or spec.carrier,
                buy_usd=corrected_buy,
                is_correction=True,
                correction_delta_usd=spec.correction_delta_usd,
                created_at=created_at,
                modified_at=slot_datetime(correction_slot) - timedelta(minutes=19),
                pickup_open_at=schedule["pickup_open"],
                pickup_close_at=schedule["pickup_close"],
                pickup_arrived_at=schedule["pickup_arrived"],
                pickup_departed_at=schedule["pickup_departed"],
                delivery_open_at=schedule["delivery_open"],
                delivery_close_at=schedule["delivery_close"],
                delivery_arrived_at=schedule["delivery_arrived"],
            )
        )

    return _latest_per_sync(events)


def expand_loads(specs: list[LoadSpec]) -> list[LoadEvent]:
    events: list[LoadEvent] = []
    for spec in specs:
        events.extend(expand_load(spec))
    return sorted(events, key=lambda event: (event.slot, event.spec.broker.value, event.spec.key))


def _latest_per_sync(events: list[LoadEvent]) -> list[LoadEvent]:
    latest: dict[tuple[int, str], LoadEvent] = {}
    for event in events:
        key = (event.slot, event.spec.key)
        existing = latest.get(key)
        if existing is None or STATUS_ORDER[event.status] >= STATUS_ORDER[existing.status]:
            latest[key] = event
    return sorted(latest.values(), key=lambda event: (event.slot, STATUS_ORDER[event.status]))
