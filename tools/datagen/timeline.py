from __future__ import annotations

from datetime import timedelta

from .cast import slot_datetime
from .models import CanonicalStatus, LoadEvent, LoadSpec


COMPRESSED_OFFSETS = (
    (0, CanonicalStatus.ACTIVE),
    (1, CanonicalStatus.COVERED),
    (3, CanonicalStatus.COMPLETED),
)

FULL_OFFSETS = (
    (0, CanonicalStatus.ACTIVE),
    (1, CanonicalStatus.COVERED),
    (2, CanonicalStatus.IN_TRANSIT),
    (3, CanonicalStatus.DELIVERED),
    (4, CanonicalStatus.COMPLETED),
)


def expand_load(spec: LoadSpec) -> list[LoadEvent]:
    if spec.lifecycle == "day11":
        offsets = ((0, CanonicalStatus.ACTIVE),)
    elif spec.lifecycle == "full":
        offsets = FULL_OFFSETS
    elif spec.lifecycle == "covered_only":
        offsets = ((0, CanonicalStatus.COVERED),)
    else:
        offsets = COMPRESSED_OFFSETS

    events: list[LoadEvent] = []
    created_at = slot_datetime(spec.start_slot) - timedelta(hours=2, minutes=17)
    current_buy = spec.buy_usd
    for offset, status in offsets:
        slot = spec.start_slot + offset
        visible_buy = current_buy if status != CanonicalStatus.ACTIVE else None
        modified_at = slot_datetime(slot) - timedelta(minutes=43)
        events.append(
            LoadEvent(
                spec=spec,
                slot=slot,
                status=status,
                buy_usd=visible_buy,
                created_at=created_at,
                modified_at=modified_at,
            )
        )

    if spec.correction_delta_usd:
        correction_slot = spec.start_slot + (5 if spec.lifecycle == "full" else 4)
        corrected_buy = round((spec.buy_usd or 0) + spec.correction_delta_usd, 2)
        events.append(
            LoadEvent(
                spec=spec,
                slot=correction_slot,
                status=CanonicalStatus.COMPLETED,
                buy_usd=corrected_buy,
                is_correction=True,
                correction_delta_usd=spec.correction_delta_usd,
                created_at=created_at,
                modified_at=slot_datetime(correction_slot) - timedelta(minutes=19),
            )
        )

    return events


def expand_loads(specs: list[LoadSpec]) -> list[LoadEvent]:
    events: list[LoadEvent] = []
    for spec in specs:
        events.extend(expand_load(spec))
    return sorted(events, key=lambda event: (event.slot, event.spec.broker.value, event.spec.key))
