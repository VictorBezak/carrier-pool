"""API response shapes.

Deliberately separate from `domain`. The domain model exposes derived values as
Python properties, which do not serialise, and the wire format should be free to
differ from the internal one anyway.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .domain import Equipment, FieldChange, Load, LoadStatus, Stop


class BrokerSummary(BaseModel):
    broker_id: str
    name: str
    tms_label: str
    tms_style: str
    load_count: int
    active_load_count: int
    carrier_count: int
    sync_file_count: int
    last_synced_at: datetime | None


class LoadSummary(BaseModel):
    load_id: str
    source_ref: str
    reference: str
    status: LoadStatus
    equipment: Equipment
    customer_name: str | None
    origin_label: str | None
    destination_label: str | None
    lane: str
    lane_label: str
    distance_miles: float | None
    weight_lbs: float | None
    customer_rate: float | None
    carrier_rate: float | None
    carrier_name: str | None
    margin: float | None
    pickup_at: datetime | None
    updated_at: datetime | None
    sync_count: int
    correction_count: int

    @classmethod
    def of(cls, load: Load, correction_count: int = 0) -> "LoadSummary":
        return cls(
            load_id=load.load_id,
            source_ref=load.source_ref,
            reference=load.reference,
            status=load.status,
            equipment=load.equipment,
            customer_name=load.customer_name,
            origin_label=load.origin.place_label if load.origin else None,
            destination_label=load.destination.place_label if load.destination else None,
            lane=load.lane,
            lane_label=load.lane_label,
            distance_miles=load.distance_miles,
            weight_lbs=load.weight_lbs,
            customer_rate=load.customer_rate,
            carrier_rate=load.carrier_rate,
            carrier_name=load.carrier_name,
            margin=load.margin,
            pickup_at=load.pickup_at,
            updated_at=load.updated_at,
            sync_count=load.sync_count,
            correction_count=correction_count,
        )


class LoadDetail(LoadSummary):
    source_tms: str
    commodity: str | None
    carrier_rate_per_mile: float | None
    stops: list[Stop]
    created_at: datetime | None
    first_seen_sync: datetime | None
    last_seen_sync: datetime | None
    history: list[FieldChange]

    @classmethod
    def of_load(cls, load: Load, history: list[FieldChange]) -> "LoadDetail":
        corrections = sum(1 for change in history if change.kind == "CORRECTION")
        base = LoadSummary.of(load, corrections).model_dump()
        return cls(
            **base,
            source_tms=load.source_tms,
            commodity=load.commodity,
            carrier_rate_per_mile=load.carrier_rate_per_mile,
            stops=load.stops,
            created_at=load.created_at,
            first_seen_sync=load.first_seen_sync,
            last_seen_sync=load.last_seen_sync,
            history=history,
        )


class LaneSummary(BaseModel):
    lane: str
    lane_label: str
    load_count: int
    median_rate_per_mile: float | None
    carrier_count: int


class CarrierSummary(BaseModel):
    carrier_id: str
    name: str
    mc_number: str | None
    dot_number: str | None
    home_city: str | None
    home_state: str | None
    phone: str | None
    loads_total: int
