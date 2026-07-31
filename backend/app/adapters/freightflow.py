"""TMS A - FreightFlow. Nested camelCase REST, US units, text statuses.

The easy one: everything about a load is in a single object and the units are
already what we want. The only real work is vocabulary mapping and reading the
trailer type out of a free-text field.
"""

from __future__ import annotations

from datetime import datetime

from ..domain import Carrier, Equipment, Load, LoadStatus, Stop
from .base import SyncBatch

STATUS_MAP: dict[str, LoadStatus] = {
    "quoting": LoadStatus.PLANNED,
    "booking": LoadStatus.ACTIVE,
    "dispatched": LoadStatus.COVERED,
    "at shipper": LoadStatus.IN_TRANSIT,
    "en route": LoadStatus.IN_TRANSIT,
    "at receiver": LoadStatus.IN_TRANSIT,
    "delivered": LoadStatus.DELIVERED,
    "completed": LoadStatus.COMPLETED,
}


def parse_equipment(text: str | None) -> Equipment:
    """FreightFlow's equipment is free text like "53 ft Van | Reefer".

    Order matters: a reefer is also described as a "Van", so the temperature
    control has to be checked first or every reefer reads as a dry van.
    """
    if not text:
        return Equipment.UNKNOWN
    lowered = text.lower()
    if "reefer" in lowered or "refrigerated" in lowered:
        return Equipment.REEFER
    if "flatbed" in lowered or "step deck" in lowered:
        return Equipment.FLATBED
    if "van" in lowered or "dry" in lowered:
        return Equipment.DRY_VAN
    return Equipment.UNKNOWN


def parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _stop_kind(stop_type: str | None, index: int, total: int) -> str:
    text = (stop_type or "").lower()
    if "pickup" in text or index == 0:
        return "PICKUP"
    if "drop" in text and index == total - 1:
        return "DROPOFF"
    return "DROPOFF" if index == total - 1 else "INTERMEDIATE"


class FreightFlowAdapter:
    source_tms = "tms_a_freightflow"

    def __init__(self, broker_id: str) -> None:
        self.broker_id = broker_id

    def parse(self, payload: dict) -> SyncBatch:
        synced_at = parse_dt(payload["syncedAt"])
        batch = SyncBatch(synced_at=synced_at)

        for raw in payload.get("loads", []):
            source_ref = str(raw["shipmentId"])
            raw_carrier = raw.get("carrier")
            carrier_id = None
            carrier_name = None

            if raw_carrier:
                carrier_id = str(raw_carrier["carrierMasterId"])
                carrier_name = raw_carrier["name"]
                batch.carriers.append(
                    Carrier(
                        broker_id=self.broker_id,
                        carrier_id=carrier_id,
                        name=carrier_name,
                        mc_number=raw_carrier.get("mcNumber"),
                        dot_number=raw_carrier.get("dotNumber"),
                        phone=raw_carrier.get("phoneNumber"),
                        first_seen_at=synced_at,
                    )
                )

            raw_stops = raw.get("stops", [])
            stops = [
                Stop.build(
                    sequence=index + 1,
                    kind=_stop_kind(raw_stop.get("stopType"), index, len(raw_stops)),
                    city=raw_stop["city"].title(),
                    state=raw_stop["state"],
                    postal_code=raw_stop.get("zipCode"),
                    scheduled_start=parse_dt(raw_stop.get("estimatedReadyDateTime")),
                    scheduled_end=parse_dt(raw_stop.get("estimatedCloseDateTime")),
                    actual_departure=parse_dt(raw_stop.get("actualDepartureDateTime")),
                )
                for index, raw_stop in enumerate(raw_stops)
            ]

            batch.loads.append(
                Load(
                    broker_id=self.broker_id,
                    load_id=f"{self.broker_id}:{source_ref}",
                    source_tms=self.source_tms,
                    source_ref=source_ref,
                    reference=source_ref,
                    status=STATUS_MAP[raw["status"].strip().lower()],
                    equipment=parse_equipment(raw.get("equipment")),
                    weight_lbs=raw.get("weightTotal"),
                    distance_miles=raw.get("mileage"),
                    customer_name=(raw.get("customer") or {}).get("name"),
                    customer_id=str((raw.get("customer") or {}).get("customerId")),
                    customer_rate=raw.get("totalSell"),
                    carrier_rate=raw.get("totalBuy"),
                    carrier_id=carrier_id,
                    carrier_name=carrier_name,
                    stops=stops,
                    created_at=parse_dt(raw.get("createdDate")),
                    updated_at=parse_dt(raw.get("lastModifiedDate")),
                )
            )

        return batch
