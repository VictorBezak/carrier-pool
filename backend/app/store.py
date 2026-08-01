"""In-memory tenant-partitioned store.

Two decisions worth calling out.

**Loads are upserted by identity, not appended.** A sync file carries the whole
load object again, so the newest sync is simply the truth. Re-running the same
file changes nothing, which means ingestion is idempotent and replaying the
whole feed from day 1 is always safe.

**Nothing derived is stored.** Lane statistics, carrier scores and price
estimates are all computed from current load state at read time. That is why a
correction landing on day 6 for a day 2 load needs no repair work: there are no
stale aggregates to patch. It is also the thing that would not survive real
volume - see DECISIONS.md.
"""

from __future__ import annotations

from datetime import datetime

from .domain import (
    BOOKED_STATUSES,
    Carrier,
    ChangeKind,
    FieldChange,
    Load,
    LoadStatus,
    Offer,
    SyncFileRecord,
)

# Fields worth telling the user about when they change between syncs.
_TRACKED_FIELDS = (
    "status",
    "equipment",
    "weight_lbs",
    "distance_miles",
    "customer_rate",
    "carrier_rate",
    "carrier_name",
)
_MONEY_FIELDS = frozenset({"customer_rate", "carrier_rate"})

_STATUS_ORDER = {status: index for index, status in enumerate(LoadStatus)}


_SEARCHING = frozenset({LoadStatus.PLANNED, LoadStatus.ACTIVE})


def _classify(field: str, old, new) -> ChangeKind:
    if field == "status":
        old_rank = _STATUS_ORDER.get(old, -1)
        new_rank = _STATUS_ORDER.get(new, -1)
        if new_rank > old_rank:
            return "PROGRESS"
        # A load that was covered and is now looking for a truck again is a
        # carrier walking away, which is a business event with a real cost - not
        # a data-entry mistake. No feed reports it as anything; the regression is
        # the only evidence there is.
        if old in BOOKED_STATUSES and new in _SEARCHING:
            return "FALL_OFF"
        return "CORRECTION"
    if old is None:
        return "REVEALED"
    if field == "carrier_name":
        # The carrier on a booked load changing means the first one came off it.
        # Strictly this is indistinguishable from someone fixing a mistyped
        # carrier, and we prefer the business reading because it is far more
        # common and far more expensive to miss.
        return "FALL_OFF"
    if field in _MONEY_FIELDS:
        return "CORRECTION"
    return "DETAIL"


def _render(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


class Store:
    def __init__(self) -> None:
        self._loads: dict[str, dict[str, Load]] = {}
        self._carriers: dict[str, dict[str, Carrier]] = {}
        self._changes: list[FieldChange] = []
        self._sync_files: list[SyncFileRecord] = []
        # Offers are keyed by id so replaying a log file cannot duplicate them.
        self._offers: dict[str, dict[str, Offer]] = {}

    # ---- writes --------------------------------------------------------

    def upsert_load(self, load: Load, synced_at: datetime, source_file: str) -> list[FieldChange]:
        """Insert or replace a load, returning the changes this sync caused."""
        bucket = self._loads.setdefault(load.broker_id, {})
        existing = bucket.get(load.load_id)
        changes: list[FieldChange] = []

        if existing is None:
            load.first_seen_sync = synced_at
            load.sync_count = 1
        else:
            load.first_seen_sync = existing.first_seen_sync
            load.sync_count = existing.sync_count + 1
            for field in _TRACKED_FIELDS:
                old = getattr(existing, field)
                new = getattr(load, field)
                if old == new:
                    continue
                changes.append(
                    FieldChange(
                        broker_id=load.broker_id,
                        load_id=load.load_id,
                        reference=load.reference,
                        field=field,
                        kind=_classify(field, old, new),
                        old_value=_render(old),
                        new_value=_render(new),
                        observed_at=synced_at,
                        source_file=source_file,
                    )
                )

        load.last_seen_sync = synced_at
        bucket[load.load_id] = load
        self._changes.extend(changes)
        return changes

    def upsert_carrier(self, carrier: Carrier) -> None:
        bucket = self._carriers.setdefault(carrier.broker_id, {})
        existing = bucket.get(carrier.carrier_id)
        if existing is not None:
            carrier.first_seen_at = existing.first_seen_at or carrier.first_seen_at
        bucket[carrier.carrier_id] = carrier

    def record_offer(self, offer: Offer) -> None:
        self._offers.setdefault(offer.broker_id, {})[offer.offer_id] = offer

    def record_sync_file(self, record: SyncFileRecord) -> None:
        self._sync_files.append(record)

    # ---- reads (always scoped to one broker) ---------------------------

    def loads(self, broker_id: str) -> list[Load]:
        return list(self._loads.get(broker_id, {}).values())

    def load(self, broker_id: str, load_id: str) -> Load | None:
        return self._loads.get(broker_id, {}).get(load_id)

    def carriers(self, broker_id: str) -> list[Carrier]:
        return list(self._carriers.get(broker_id, {}).values())

    def carrier(self, broker_id: str, carrier_id: str) -> Carrier | None:
        return self._carriers.get(broker_id, {}).get(carrier_id)

    def changes_for_load(self, broker_id: str, load_id: str) -> list[FieldChange]:
        return [
            change
            for change in self._changes
            if change.broker_id == broker_id and change.load_id == load_id
        ]

    def changes(self, broker_id: str) -> list[FieldChange]:
        return [change for change in self._changes if change.broker_id == broker_id]

    def offers(self, broker_id: str) -> list[Offer]:
        return list(self._offers.get(broker_id, {}).values())

    def offers_for_load(self, broker_id: str, load_id: str) -> list[Offer]:
        return sorted(
            (offer for offer in self.offers(broker_id) if offer.load_id == load_id),
            key=lambda offer: offer.offered_at,
        )

    def sync_files(self, broker_id: str | None = None) -> list[SyncFileRecord]:
        if broker_id is None:
            return list(self._sync_files)
        return [record for record in self._sync_files if record.broker_id == broker_id]

    @property
    def last_synced_at(self) -> datetime | None:
        if not self._sync_files:
            return None
        return max(record.synced_at for record in self._sync_files)
