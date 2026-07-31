"""One adapter per TMS. Adding a fourth broker means adding a file here and a
row in `brokers.py`; nothing else in the system changes."""

from __future__ import annotations

from .base import Adapter, SyncBatch
from .brokeros import BrokerOSAdapter
from .freightflow import FreightFlowAdapter
from .hauldesk import HaulDeskAdapter

ADAPTERS_BY_TMS = {
    FreightFlowAdapter.source_tms: FreightFlowAdapter,
    HaulDeskAdapter.source_tms: HaulDeskAdapter,
    BrokerOSAdapter.source_tms: BrokerOSAdapter,
}


def build(source_tms: str, broker_id: str) -> Adapter:
    try:
        return ADAPTERS_BY_TMS[source_tms](broker_id)
    except KeyError:
        raise ValueError(f"no adapter registered for TMS {source_tms!r}") from None


__all__ = ["Adapter", "SyncBatch", "build", "ADAPTERS_BY_TMS"]
