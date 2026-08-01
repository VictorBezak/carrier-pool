"""Ingestion: one sync file at a time, in the order the real schedule produced
them.

The files are named so they sort chronologically, but sorting by name is only
correct within one directory. Across brokers the ordering has to come from the
timestamp, so the runner interleaves all three feeds into a single timeline and
walks it. That matters less for correctness today (brokers are isolated) than
for honesty: this is the order the platform would really have seen events in,
and it is the order a replay has to reproduce.

`example_sync.jsonc` files are documentation, not data, and are skipped.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import adapters, brokers
from .domain import Offer, OfferOutcome, SyncFileRecord
from .store import Store

log = logging.getLogger(__name__)

SYNC_FILENAME = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})_sync\.json$")
OFFER_FILENAME = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})_offers\.json$")
ACTIVITY_DIR = "platform_activity"


@dataclass(frozen=True)
class PendingFile:
    broker_id: str
    source_tms: str
    path: Path
    scheduled_at: datetime
    # Offer logs are the platform's own record, not a TMS sync, and are parsed by
    # a different code path. Kept on one timeline so a replay sees events in the
    # order they really happened.
    kind: str = "sync"


def _scheduled_at(filename: str, pattern: re.Pattern[str] = SYNC_FILENAME) -> datetime | None:
    """The sync time encoded in the filename, used only for ordering.

    The authoritative timestamp is inside the file, but we need an order
    *before* opening anything, and every feed writes its own timezone
    differently. The filename is the one convention all three share.
    """
    match = pattern.match(filename)
    if not match:
        return None
    day, hour, minute = match.groups()
    return datetime.fromisoformat(f"{day}T{hour}:{minute}:00")


def discover(data_root: Path) -> list[PendingFile]:
    pending: list[PendingFile] = []
    for broker in brokers.BROKERS:
        directory = data_root / broker.source_tms
        if not directory.is_dir():
            log.warning("no data directory for %s at %s", broker.broker_id, directory)
            continue
        for path in sorted(directory.iterdir()):
            scheduled_at = _scheduled_at(path.name)
            if scheduled_at is None:
                continue
            pending.append(
                PendingFile(
                    broker_id=broker.broker_id,
                    source_tms=broker.source_tms,
                    path=path,
                    scheduled_at=scheduled_at,
                )
            )

        activity = data_root / ACTIVITY_DIR / broker.broker_id
        if not activity.is_dir():
            # A broker with no offer log is not an error - it means the platform
            # has not yet recorded any calls for them, which is the state every
            # new tenant starts in.
            log.info("no offer log for %s; acceptance data will be unavailable", broker.broker_id)
            continue
        for path in sorted(activity.iterdir()):
            scheduled_at = _scheduled_at(path.name, OFFER_FILENAME)
            if scheduled_at is None:
                continue
            pending.append(
                PendingFile(
                    broker_id=broker.broker_id,
                    source_tms=broker.source_tms,
                    path=path,
                    scheduled_at=scheduled_at,
                    kind="offers",
                )
            )

    # Ties broken by broker id, then kind, so a replay is deterministic.
    pending.sort(key=lambda item: (item.scheduled_at, item.broker_id, item.kind))
    return pending


def _parse_offers(payload: dict, broker_id: str) -> list[Offer]:
    offers = []
    for row in payload.get("offers", []):
        offers.append(
            Offer(
                broker_id=broker_id,
                offer_id=row["offer_id"],
                load_id=f"{broker_id}:{row['load_ref']}",
                # Carrier ids are already broker-scoped in the canonical model,
                # so they are used as the feed states them.
                carrier_id=str(row["carrier_ref"]),
                carrier_name=row["carrier_name"],
                offered_at=datetime.fromisoformat(row["offered_at"]),
                offered_rate=float(row["offered_rate_usd"]),
                outcome=OfferOutcome(row["outcome"].upper()),
                counter_rate=row.get("counter_rate_usd"),
                responded_at=(
                    datetime.fromisoformat(row["responded_at"]) if row.get("responded_at") else None
                ),
                decline_reason=row.get("decline_reason"),
            )
        )
    return offers


def ingest_all(data_root: Path, store: Store | None = None) -> Store:
    """Build a store by replaying every sync file in chronological order."""
    store = store or Store()
    sessions = {
        broker.broker_id: adapters.build(broker.source_tms, broker.broker_id)
        for broker in brokers.BROKERS
    }

    files = discover(data_root)
    for pending in files:
        payload = json.loads(pending.path.read_text())

        if pending.kind == "offers":
            offers = _parse_offers(payload, pending.broker_id)
            for offer in offers:
                store.record_offer(offer)
            store.record_sync_file(
                SyncFileRecord(
                    broker_id=pending.broker_id,
                    source_tms=pending.source_tms,
                    filename=pending.path.name,
                    synced_at=datetime.fromisoformat(payload["logged_at"]),
                    loads_seen=0,
                    carriers_seen=0,
                    changes_recorded=0,
                    offers_seen=len(offers),
                )
            )
            continue

        adapter = sessions[pending.broker_id]
        batch = adapter.parse(payload)

        for carrier in batch.carriers:
            store.upsert_carrier(carrier)

        change_count = 0
        for load in batch.loads:
            change_count += len(store.upsert_load(load, batch.synced_at, pending.path.name))

        store.record_sync_file(
            SyncFileRecord(
                broker_id=pending.broker_id,
                source_tms=pending.source_tms,
                filename=pending.path.name,
                synced_at=batch.synced_at,
                loads_seen=len(batch.loads),
                carriers_seen=len(batch.carriers),
                changes_recorded=change_count,
            )
        )

    log.info("ingested %d files across %d brokers", len(files), len(brokers.BROKERS))
    return store
