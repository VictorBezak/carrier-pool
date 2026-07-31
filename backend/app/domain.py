"""The canonical shape every TMS is translated into.

Nothing downstream of the adapters knows that FreightFlow speaks camelCase or
that HaulDesk measures in kilograms. Everything is US units, one status
vocabulary, one equipment vocabulary.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from . import geo


class LoadStatus(StrEnum):
    """The README's vocabulary. Each TMS's statuses map onto this."""

    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COVERED = "COVERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"


# Statuses where a carrier is committed, so the carrier rate is real money
# rather than a guess. These are the loads that history is built from.
BOOKED_STATUSES = frozenset(
    {LoadStatus.COVERED, LoadStatus.IN_TRANSIT, LoadStatus.DELIVERED, LoadStatus.COMPLETED}
)
# Statuses where the load actually ran, i.e. the carrier proved it will do the
# lane rather than merely having accepted it.
RAN_STATUSES = frozenset({LoadStatus.DELIVERED, LoadStatus.COMPLETED})


class Equipment(StrEnum):
    DRY_VAN = "DRY_VAN"
    REEFER = "REEFER"
    FLATBED = "FLATBED"
    UNKNOWN = "UNKNOWN"


StopKind = Literal["PICKUP", "DROPOFF", "INTERMEDIATE"]


class Stop(BaseModel):
    sequence: int
    kind: StopKind
    city: str
    state: str
    postal_code: str | None = None
    location_name: str | None = None
    market: str = geo.UNKNOWN_MARKET
    market_label: str = ""
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    actual_arrival: datetime | None = None
    actual_departure: datetime | None = None

    @classmethod
    def build(cls, **kwargs) -> "Stop":
        """Fill in the derived market fields from the address."""
        market = geo.resolve_market(
            kwargs.get("postal_code"), kwargs.get("city"), kwargs.get("state")
        )
        return cls(**kwargs, market=market, market_label=geo.market_label(market))

    @property
    def place_label(self) -> str:
        return f"{self.city.title()}, {self.state}"


class Carrier(BaseModel):
    """A carrier as one broker knows them.

    `carrier_id` is scoped to the broker. `mc_number`/`dot_number` are the
    federal identity of the real-world company and are the only thing that
    could ever tie this record to another broker's record of the same carrier -
    which is what a shared pool would be built on.
    """

    broker_id: str
    carrier_id: str
    name: str
    mc_number: str | None = None
    dot_number: str | None = None
    home_city: str | None = None
    home_state: str | None = None
    home_market: str = geo.UNKNOWN_MARKET
    phone: str | None = None
    first_seen_at: datetime | None = None


class Load(BaseModel):
    broker_id: str
    load_id: str
    source_tms: str
    source_ref: str
    reference: str
    status: LoadStatus
    equipment: Equipment = Equipment.UNKNOWN
    commodity: str | None = None
    weight_lbs: float | None = None
    distance_miles: float | None = None
    customer_name: str | None = None
    customer_id: str | None = None
    customer_rate: float | None = None
    carrier_rate: float | None = None
    carrier_id: str | None = None
    carrier_name: str | None = None
    stops: list[Stop] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    first_seen_sync: datetime | None = None
    last_seen_sync: datetime | None = None
    sync_count: int = 0

    # ---- derived views -------------------------------------------------

    @property
    def origin(self) -> Stop | None:
        return self.stops[0] if self.stops else None

    @property
    def destination(self) -> Stop | None:
        return self.stops[-1] if self.stops else None

    @property
    def origin_market(self) -> str:
        return self.origin.market if self.origin else geo.UNKNOWN_MARKET

    @property
    def destination_market(self) -> str:
        return self.destination.market if self.destination else geo.UNKNOWN_MARKET

    @property
    def lane(self) -> str:
        return geo.lane_code(self.origin_market, self.destination_market)

    @property
    def lane_label(self) -> str:
        return geo.lane_label(self.origin_market, self.destination_market)

    @property
    def is_booked(self) -> bool:
        return self.status in BOOKED_STATUSES

    @property
    def has_run(self) -> bool:
        return self.status in RAN_STATUSES

    @property
    def margin(self) -> float | None:
        if self.customer_rate is None or self.carrier_rate is None:
            return None
        return round(self.customer_rate - self.carrier_rate, 2)

    @property
    def carrier_rate_per_mile(self) -> float | None:
        if not self.carrier_rate or not self.distance_miles:
            return None
        return round(self.carrier_rate / self.distance_miles, 3)

    @property
    def pickup_at(self) -> datetime | None:
        return self.origin.scheduled_start if self.origin else None

    @property
    def delivered_at(self) -> datetime | None:
        dest = self.destination
        if not dest:
            return None
        return dest.actual_arrival or dest.scheduled_start


ChangeKind = Literal["PROGRESS", "REVEALED", "CORRECTION", "DETAIL"]


class FieldChange(BaseModel):
    """One field of one load changing value in a later sync.

    Kept because "the amount was corrected after the fact" is a first-class
    event in this domain, not an error. The `kind` is the distinction that
    matters: a rate going from null to a number is the amount becoming known
    (REVEALED), a rate going from one number to a different number is somebody
    restating history (CORRECTION), and those two deserve different treatment.
    """

    broker_id: str
    load_id: str
    reference: str
    field: str
    kind: ChangeKind
    old_value: str | None
    new_value: str | None
    observed_at: datetime
    source_file: str


class SyncFileRecord(BaseModel):
    """Provenance for one ingested sync file."""

    broker_id: str
    source_tms: str
    filename: str
    synced_at: datetime
    loads_seen: int
    carriers_seen: int
    changes_recorded: int


class Broker(BaseModel):
    """A tenant. One broker, one TMS, one silo of data."""

    broker_id: str
    name: str
    source_tms: str
    tms_label: str
    tms_style: str
