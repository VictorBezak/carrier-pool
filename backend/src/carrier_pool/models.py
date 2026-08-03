from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Equipment(str, Enum):
    DRY_VAN = "dry_van"
    REEFER = "reefer"
    FLATBED = "flatbed"
    UNKNOWN = "unknown"


class LoadStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    COVERED = "covered"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    COMPLETED = "completed"


@dataclass(frozen=True)
class Location:
    city: str
    state: str
    zip_code: str


@dataclass
class Carrier:
    broker_id: str
    carrier_id: str
    name: str
    mc_number: str | None = None
    dot_number: str | None = None
    home: Location | None = None
    phone: str | None = None


@dataclass
class Customer:
    broker_id: str
    customer_id: str
    name: str


@dataclass
class LoadVersion:
    broker_id: str
    source_file: str
    raw_load_id: str
    status: LoadStatus
    customer_id: str
    customer_name: str
    carrier_id: str | None
    equipment: Equipment
    pickup: Location
    delivery: Location
    pickup_open_at: datetime | None
    pickup_close_at: datetime | None
    pickup_actual_at: datetime | None
    delivery_open_at: datetime | None
    delivery_close_at: datetime | None
    delivery_actual_at: datetime | None
    distance_miles: float
    weight_lbs: float | None
    commodity: str | None
    customer_rate_usd: float | None
    carrier_rate_usd: float | None
    created_at: datetime | None
    updated_at: datetime | None
    raw: dict


@dataclass
class CanonicalStore:
    carriers: dict[tuple[str, str], Carrier] = field(default_factory=dict)
    customers: dict[tuple[str, str], Customer] = field(default_factory=dict)
    versions: list[LoadVersion] = field(default_factory=list)
    current_loads: dict[tuple[str, str], LoadVersion] = field(default_factory=dict)

    def add_version(self, version: LoadVersion) -> None:
        self.versions.append(version)
        self.current_loads[(version.broker_id, version.raw_load_id)] = version

    def broker_versions(self, broker_id: str) -> list[LoadVersion]:
        return [version for version in self.versions if version.broker_id == broker_id]

    def broker_current_loads(self, broker_id: str) -> list[LoadVersion]:
        return [version for (broker, _), version in self.current_loads.items() if broker == broker_id]


@dataclass(frozen=True)
class ComponentScore:
    name: str
    score: float
    weight: float
    evidence: dict[str, float | int | str | None]


@dataclass(frozen=True)
class CarrierRanking:
    broker_id: str
    load_id: str
    carrier_id: str
    carrier_name: str
    score: float
    confidence: str
    components: list[ComponentScore]
    reasons: list[str]
    limitations: list[str]
