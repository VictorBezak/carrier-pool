"""The tenant registry.

One broker per TMS directory. The broker id is the tenancy key: every read
path in the store takes one, and nothing in the API can return data without
one. Tenancy is not a filter applied at the end, it is the lookup key.
"""

from __future__ import annotations

from .domain import Broker

BROKERS: tuple[Broker, ...] = (
    Broker(
        broker_id="redline",
        name="Redline Freight Partners",
        source_tms="tms_a_freightflow",
        tms_label="FreightFlow",
        tms_style="Modern REST: nested JSON, camelCase, US units",
    ),
    Broker(
        broker_id="anchor",
        name="Anchor Logistics Group",
        source_tms="tms_b_hauldesk",
        tms_label="HaulDesk",
        tms_style="Legacy table dump: snake_case, metric units, append-only rate lines",
    ),
    Broker(
        broker_id="summit",
        name="Summit Freight Solutions",
        source_tms="tms_c_brokeros",
        tms_label="BrokerOS",
        tms_style="CRM package: opaque IDs, child records, referenced lookups",
    ),
)

BY_ID: dict[str, Broker] = {broker.broker_id: broker for broker in BROKERS}
BY_TMS: dict[str, Broker] = {broker.source_tms: broker for broker in BROKERS}


def get(broker_id: str) -> Broker | None:
    return BY_ID.get(broker_id)
