"""TMS B - HaulDesk. Legacy flat export: table dumps, metric units, numeric
statuses, naive local timestamps, and money as append-only line items.

Three things make this the awkward one:

1. **Units.** Weight is kilograms and distance is kilometres. Converted at the
   boundary so nothing downstream has to remember.
2. **Money is a ledger, not a field.** A load's carrier rate is the sum of its
   `pay` line items, and later syncs append more rows (fuel, detention, or a
   negative correction row) rather than editing the old ones. So the adapter
   accumulates rows across syncs, keyed by `rate_id` - which makes re-reading a
   file harmless instead of double-counting.
3. **Carriers arrive out of band.** A load row references `carrier_ref`, but the
   matching row in `carriers` may have arrived in an earlier sync, so the
   adapter keeps its own carrier lookup.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..domain import Carrier, Equipment, Load, LoadStatus, Stop
from ..geo import market_for_city
from .base import SyncBatch

try:  # pragma: no cover - depends on tzdata availability
    from zoneinfo import ZoneInfo

    CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    # Every timestamp in this dataset falls in CDT. A fixed offset is wrong in
    # November and right here; the real fix is shipping tzdata.
    CENTRAL = timezone(timedelta(hours=-5))

KG_TO_LBS = 2.20462262
KM_TO_MILES = 0.621371192

STATUS_MAP: dict[int, LoadStatus] = {
    10: LoadStatus.PLANNED,
    20: LoadStatus.ACTIVE,
    30: LoadStatus.COVERED,
    40: LoadStatus.IN_TRANSIT,
    50: LoadStatus.DELIVERED,
    90: LoadStatus.COMPLETED,
}

EQUIPMENT_MAP: dict[str, Equipment] = {
    "V": Equipment.DRY_VAN,
    "R": Equipment.REEFER,
    "F": Equipment.FLATBED,
}


def parse_dt(value: str | None) -> datetime | None:
    """HaulDesk timestamps have no offset; they are US Central wall time."""
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CENTRAL)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=CENTRAL)


class HaulDeskAdapter:
    source_tms = "tms_b_hauldesk"

    def __init__(self, broker_id: str) -> None:
        self.broker_id = broker_id
        # load_num -> rate_id -> (side, amount). Keyed by rate_id so replaying a
        # file cannot double-count an append-only ledger.
        self._rate_lines: dict[str, dict[int, tuple[str, float]]] = {}
        self._carriers: dict[str, Carrier] = {}

    def parse(self, payload: dict) -> SyncBatch:
        synced_at = parse_dt(payload["synced_at"])
        batch = SyncBatch(synced_at=synced_at)

        for raw in payload.get("carriers", []):
            carrier_id = str(raw["carrier_id"])
            carrier = Carrier(
                broker_id=self.broker_id,
                carrier_id=carrier_id,
                name=raw["carrier_name"],
                mc_number=raw.get("mc_no"),
                dot_number=raw.get("dot_no"),
                home_city=raw.get("home_city"),
                home_state=raw.get("home_state"),
                home_market=market_for_city(raw.get("home_city"), raw.get("home_state")),
                phone=raw.get("phone"),
                first_seen_at=synced_at,
            )
            self._carriers[carrier_id] = carrier
            batch.carriers.append(carrier)

        for raw in payload.get("rates", []):
            ledger = self._rate_lines.setdefault(raw["load_num"], {})
            ledger[int(raw["rate_id"])] = (raw["side"], float(raw["amount_usd"]))

        for raw in payload.get("loads", []):
            load_num = raw["load_num"]
            carrier_ref = raw.get("carrier_ref")
            carrier = self._carriers.get(str(carrier_ref)) if carrier_ref is not None else None

            batch.loads.append(
                Load(
                    broker_id=self.broker_id,
                    load_id=f"{self.broker_id}:{load_num}",
                    source_tms=self.source_tms,
                    source_ref=load_num,
                    reference=load_num,
                    status=STATUS_MAP[int(raw["status_code"])],
                    equipment=EQUIPMENT_MAP.get(raw.get("equip") or "", Equipment.UNKNOWN),
                    weight_lbs=self._to_lbs(raw.get("weight_kg")),
                    distance_miles=self._to_miles(raw.get("dist_km")),
                    customer_name=raw.get("customer_name"),
                    customer_id=raw.get("customer_code"),
                    customer_rate=self._side_total(load_num, "bill"),
                    carrier_rate=self._side_total(load_num, "pay"),
                    carrier_id=carrier.carrier_id if carrier else None,
                    carrier_name=carrier.name if carrier else None,
                    stops=self._stops(raw),
                    created_at=parse_dt(raw.get("entered_at")),
                    updated_at=parse_dt(raw.get("updated_at")),
                )
            )

        return batch

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _to_lbs(kg: float | None) -> float | None:
        return round(kg * KG_TO_LBS, 1) if kg is not None else None

    @staticmethod
    def _to_miles(km: float | None) -> float | None:
        return round(km * KM_TO_MILES, 1) if km is not None else None

    def _side_total(self, load_num: str, side: str) -> float | None:
        """Sum one side of a load's ledger. No rows means not yet priced, which
        is different from priced at zero."""
        ledger = self._rate_lines.get(load_num)
        if not ledger:
            return None
        amounts = [amount for row_side, amount in ledger.values() if row_side == side]
        return round(sum(amounts), 2) if amounts else None

    def _stops(self, raw: dict) -> list[Stop]:
        return [
            Stop.build(
                sequence=1,
                kind="PICKUP",
                city=raw["pu_city"],
                state=raw["pu_state"],
                postal_code=raw.get("pu_zip"),
                scheduled_start=parse_date(raw.get("pu_date")),
                actual_departure=parse_dt(raw.get("pu_departed_at")),
            ),
            Stop.build(
                sequence=2,
                kind="DROPOFF",
                city=raw["del_city"],
                state=raw["del_state"],
                postal_code=raw.get("del_zip"),
                scheduled_start=parse_date(raw.get("del_date")),
                actual_arrival=parse_dt(raw.get("del_arrived_at")),
            ),
        ]
