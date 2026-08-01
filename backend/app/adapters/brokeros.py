"""TMS C - BrokerOS. CRM managed package: opaque IDs, child records, and a
`referenced_records` lookup that has to be resolved before anything makes sense.

The traps here:

- **Customers and carriers are the same object type.** Both are Accounts,
  distinguished only by `record_type`, so the carrier has to be identified by
  which field pointed at it rather than by its own shape.
- **Weight units are per record.** `bos__Weight_Units__c` is usually lbs but not
  always, so unit conversion happens per line item, not per feed.
- **Equipment can be null and null does not mean dry van.** The schema says so
  explicitly, so it maps to UNKNOWN and the ranker treats it as a missing fact
  rather than assuming the most common value.
- **Stops are unordered child records.** They carry `bos__Number__c` and must be
  sorted by it; direction comes from boolean flags, not position.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..domain import Carrier, Equipment, Load, LoadStatus, Stop
from .base import SyncBatch

# Appointment dates carry no time and no offset. They are wall-clock dates at the
# stop, and this broker's freight is all Texas, so Central is the correct reading.
CENTRAL = ZoneInfo("America/Chicago")

KG_TO_LBS = 2.20462262

STATUS_MAP: dict[str, LoadStatus] = {
    "quotes requested": LoadStatus.PLANNED,
    "ready to book": LoadStatus.ACTIVE,
    "booked": LoadStatus.COVERED,
    "in transit": LoadStatus.IN_TRANSIT,
    "delivered": LoadStatus.DELIVERED,
    "invoiced": LoadStatus.COMPLETED,
    "paid": LoadStatus.COMPLETED,
}

EQUIPMENT_MAP: dict[str, Equipment] = {
    "dry van": Equipment.DRY_VAN,
    "reefer": Equipment.REEFER,
    "flatbed": Equipment.FLATBED,
}


def parse_dt(value: str | None) -> datetime | None:
    """BrokerOS emits UTC as "...T09:40:02.000+0000", which predates
    fromisoformat's tolerance for a colon-less offset on older Pythons."""
    if not value:
        return None
    normalised = value.replace("Z", "+00:00")
    if normalised.endswith("+0000"):
        normalised = normalised[:-5] + "+00:00"
    return datetime.fromisoformat(normalised)


def parse_date(value: str | None) -> datetime | None:
    """A bare appointment date, anchored to Central.

    Every datetime in the canonical model must be timezone-aware. Letting one
    naive value through does not fail here - it fails much later, wherever
    something first tries to compare it against a real timestamp.
    """
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=CENTRAL)


class BrokerOSAdapter:
    source_tms = "tms_c_brokeros"

    def __init__(self, broker_id: str) -> None:
        self.broker_id = broker_id
        # referenced_records is repeated in every sync for convenience, but
        # keeping a cumulative view means a record referenced before it is
        # described still resolves.
        self._refs: dict[str, dict] = {}

    def parse(self, payload: dict) -> SyncBatch:
        synced_at = parse_dt(payload["synced_at"])
        self._refs.update(payload.get("referenced_records", {}))
        batch = SyncBatch(synced_at=synced_at)

        for raw in payload.get("records", []):
            source_ref = raw["Id"]
            carrier_ref = raw.get("bos__Carrier__c")
            carrier_account = self._refs.get(carrier_ref) if carrier_ref else None
            carrier_name = carrier_account.get("Name") if carrier_account else None

            if carrier_ref and carrier_name:
                batch.carriers.append(
                    Carrier(
                        broker_id=self.broker_id,
                        carrier_id=carrier_ref,
                        name=carrier_name,
                        first_seen_at=synced_at,
                    )
                )

            customer_ref = raw.get("bos__Customer__c")
            customer_account = self._refs.get(customer_ref) if customer_ref else None

            line_items = raw.get("bos__Line_Items__r") or []
            equipment_raw = raw.get("bos__Equipment_Type__c")

            batch.loads.append(
                Load(
                    broker_id=self.broker_id,
                    load_id=f"{self.broker_id}:{source_ref}",
                    source_tms=self.source_tms,
                    source_ref=source_ref,
                    reference=raw.get("Name") or source_ref,
                    status=STATUS_MAP[raw["bos__Load_Status__c"].strip().lower()],
                    equipment=EQUIPMENT_MAP.get(
                        (equipment_raw or "").strip().lower(), Equipment.UNKNOWN
                    ),
                    commodity=self._commodity(line_items),
                    weight_lbs=self._weight_lbs(line_items),
                    distance_miles=raw.get("bos__Distance_Miles__c"),
                    customer_name=customer_account.get("Name") if customer_account else None,
                    customer_id=customer_ref,
                    customer_rate=raw.get("bos__Customer_Rate__c"),
                    carrier_rate=raw.get("bos__Carrier_Rate__c"),
                    carrier_id=carrier_ref,
                    carrier_name=carrier_name,
                    stops=self._stops(raw.get("bos__Stops__r") or []),
                    created_at=parse_dt(raw.get("CreatedDate")),
                    updated_at=parse_dt(raw.get("LastModifiedDate")),
                )
            )

        return batch

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _commodity(line_items: list[dict]) -> str | None:
        names = [item.get("bos__Commodity__c") for item in line_items if item.get("bos__Commodity__c")]
        return ", ".join(names) if names else None

    @staticmethod
    def _weight_lbs(line_items: list[dict]) -> float | None:
        """Total the line items, converting per item - the unit is a property of
        the row, not of the feed."""
        total = 0.0
        seen = False
        for item in line_items:
            weight = item.get("bos__Weight__c")
            if weight is None:
                continue
            seen = True
            units = (item.get("bos__Weight_Units__c") or "lbs").strip().lower()
            total += weight * KG_TO_LBS if units in ("kg", "kgs", "kilograms") else weight
        return round(total, 1) if seen else None

    def _stops(self, raw_stops: list[dict]) -> list[Stop]:
        ordered = sorted(raw_stops, key=lambda stop: stop.get("bos__Number__c") or 0)
        stops: list[Stop] = []
        for index, raw_stop in enumerate(ordered):
            location = self._refs.get(raw_stop.get("bos__Location__c")) or {}
            if raw_stop.get("bos__Is_Pickup__c"):
                kind = "PICKUP"
            elif raw_stop.get("bos__Is_Dropoff__c"):
                kind = "DROPOFF"
            else:
                kind = "INTERMEDIATE"
            stops.append(
                Stop.build(
                    sequence=index + 1,
                    kind=kind,
                    city=location.get("bos__City__c") or "",
                    state=location.get("bos__State__c") or "",
                    postal_code=location.get("bos__Postal_Code__c"),
                    location_name=location.get("Name"),
                    scheduled_start=parse_date(raw_stop.get("bos__Scheduled_Date__c")),
                    actual_arrival=parse_dt(raw_stop.get("bos__Arrival_Time__c")),
                )
            )
        return stops
