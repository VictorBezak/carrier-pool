from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from .cast import TOTAL_SLOTS
from .models import Broker, LoadEvent

MAX_LOADS_PER_SYNC = 3


def pack_events(events: list[LoadEvent]) -> dict[Broker, dict[int, list[LoadEvent]]]:
    packed: dict[Broker, dict[int, list[LoadEvent]]] = {broker: {slot: [] for slot in range(TOTAL_SLOTS)} for broker in Broker}
    by_broker: dict[Broker, list[LoadEvent]] = defaultdict(list)
    for event in events:
        by_broker[event.spec.broker].append(event)

    for broker, broker_events in by_broker.items():
        for event in sorted(broker_events, key=lambda item: (item.slot, item.spec.key, item.status.value)):
            slot = event.slot
            while slot < TOTAL_SLOTS:
                sync_events = packed[broker][slot]
                already_present = {item.spec.key for item in sync_events}
                if len(sync_events) < MAX_LOADS_PER_SYNC and event.spec.key not in already_present:
                    packed[broker][slot].append(replace(event, slot=slot))
                    break
                slot += 1
            else:
                raise ValueError(f"No capacity left to place {event.spec.key} for {broker.value}")

    errors: list[str] = []
    for broker, slots in packed.items():
        for slot, sync_events in slots.items():
            if not sync_events:
                errors.append(f"{broker.value} slot {slot} is empty")
            if len(sync_events) > MAX_LOADS_PER_SYNC:
                errors.append(f"{broker.value} slot {slot} has {len(sync_events)} loads")
            keys = [event.spec.key for event in sync_events]
            if len(keys) != len(set(keys)):
                errors.append(f"{broker.value} slot {slot} has duplicate load keys")
    if errors:
        raise ValueError("Invalid sync packing:\n" + "\n".join(errors))

    return packed
