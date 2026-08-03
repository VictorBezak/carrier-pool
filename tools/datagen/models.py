from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Broker(str, Enum):
    FREIGHTFLOW = "tms_a_freightflow"
    HAULDESK = "tms_b_hauldesk"
    BROKEROS = "tms_c_brokeros"


class Equipment(str, Enum):
    DRY_VAN = "dry_van"
    REEFER = "reefer"
    FLATBED = "flatbed"
    UNKNOWN = "unknown"


class CanonicalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COVERED = "COVERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class Place:
    key: str
    city: str
    state: str
    zip_code: str
    metro: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Customer:
    broker: Broker
    key: str
    name: str


@dataclass(frozen=True)
class Carrier:
    broker: Broker
    key: str
    name: str
    mc: str
    dot: str
    home: str
    phone: str


@dataclass(frozen=True)
class LoadSpec:
    key: str
    broker: Broker
    customer: str
    carrier: str | None
    pickup: str
    delivery: str
    equipment: Equipment
    weight_lbs: float
    sell_usd: float
    buy_usd: float | None
    start_slot: int
    lifecycle: str = "compressed"
    scenario_ids: tuple[str, ...] = ()
    notes: str = ""
    intermediate_stops: tuple[str, ...] = ()
    correction_delta_usd: float = 0.0
    brokeros_weight_units: str = "lbs"
    brokeros_null_equipment: bool = False
    hauldesk_carrier_rename_slot: int | None = None


@dataclass(frozen=True)
class LoadEvent:
    spec: LoadSpec
    slot: int
    status: CanonicalStatus
    buy_usd: float | None
    is_correction: bool = False
    correction_delta_usd: float = 0.0
    created_at: datetime | None = None
    modified_at: datetime | None = None


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    description: str
    expected_behavior: str
    load_keys: tuple[str, ...] = field(default_factory=tuple)
