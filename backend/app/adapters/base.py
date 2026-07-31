"""Adapter contract.

An adapter is instantiated once per ingestion run and fed sync files in
chronological order. It is allowed to keep state between files, because some
TMSs need it: HaulDesk sends money as append-only line items and introduces
carriers in whichever sync first saw them, so the total for a load can only be
known by accumulating rows across syncs.

State living in the adapter rather than the store keeps TMS quirks out of the
domain. Replaying the feed from the beginning rebuilds that state exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..domain import Carrier, Load


@dataclass
class SyncBatch:
    synced_at: datetime
    loads: list[Load] = field(default_factory=list)
    carriers: list[Carrier] = field(default_factory=list)


class Adapter(Protocol):
    broker_id: str
    source_tms: str

    def parse(self, payload: dict) -> SyncBatch: ...
