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
from .domain import SyncFileRecord
from .store import Store

log = logging.getLogger(__name__)

SYNC_FILENAME = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})_sync\.json$")


@dataclass(frozen=True)
class PendingFile:
    broker_id: str
    source_tms: str
    path: Path
    scheduled_at: datetime


def _scheduled_at(filename: str) -> datetime | None:
    """The sync time encoded in the filename, used only for ordering.

    The authoritative timestamp is inside the file, but we need an order
    *before* opening anything, and every feed writes its own timezone
    differently. The filename is the one convention all three share.
    """
    match = SYNC_FILENAME.match(filename)
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
    # Ties broken by broker id so a replay is deterministic.
    pending.sort(key=lambda item: (item.scheduled_at, item.broker_id))
    return pending


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

    log.info("ingested %d sync files across %d brokers", len(files), len(brokers.BROKERS))
    return store
