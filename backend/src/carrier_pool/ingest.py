from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CanonicalStore, Carrier, Customer, Equipment, LoadStatus, LoadVersion, Location

BROKER_FREIGHTFLOW = "tms_a_freightflow"
BROKER_HAULDESK = "tms_b_hauldesk"
BROKER_BROKEROS = "tms_c_brokeros"


def ingest_data(data_dir: Path) -> CanonicalStore:
    store = CanonicalStore()
    _ingest_freightflow(data_dir / BROKER_FREIGHTFLOW, store)
    _ingest_hauldesk(data_dir / BROKER_HAULDESK, store)
    _ingest_brokeros(data_dir / BROKER_BROKEROS, store)
    return store


def _sync_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*_sync.json"))


def _ingest_freightflow(folder: Path, store: CanonicalStore) -> None:
    for path in _sync_files(folder):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["loads"]:
            customer_id = str(row["customer"]["customerId"])
            store.customers[(BROKER_FREIGHTFLOW, customer_id)] = Customer(BROKER_FREIGHTFLOW, customer_id, row["customer"]["name"])
            carrier_id = None
            if row["carrier"]:
                carrier = row["carrier"]
                carrier_id = str(carrier["carrierMasterId"])
                store.carriers[(BROKER_FREIGHTFLOW, carrier_id)] = Carrier(
                    broker_id=BROKER_FREIGHTFLOW,
                    carrier_id=carrier_id,
                    name=carrier["name"],
                    mc_number=carrier.get("mcNumber"),
                    dot_number=carrier.get("dotNumber"),
                    phone=carrier.get("phoneNumber"),
                )
            stops = row["stops"]
            pickup = stops[0]
            delivery = stops[-1]
            store.add_version(
                LoadVersion(
                    broker_id=BROKER_FREIGHTFLOW,
                    source_file=str(path.relative_to(folder.parent)),
                    raw_load_id=str(row["shipmentId"]),
                    status=_freightflow_status(row["status"]),
                    customer_id=customer_id,
                    customer_name=row["customer"]["name"],
                    carrier_id=carrier_id,
                    equipment=_freightflow_equipment(row.get("equipment")),
                    pickup=_location(pickup["city"], pickup["state"], pickup["zipCode"]),
                    delivery=_location(delivery["city"], delivery["state"], delivery["zipCode"]),
                    pickup_open_at=_parse_dt(pickup.get("estimatedReadyDateTime")),
                    pickup_close_at=_parse_dt(pickup.get("estimatedCloseDateTime")),
                    pickup_actual_at=_parse_dt(pickup.get("actualDepartureDateTime")),
                    delivery_open_at=_parse_dt(delivery.get("estimatedReadyDateTime")),
                    delivery_close_at=_parse_dt(delivery.get("estimatedCloseDateTime")),
                    delivery_actual_at=_parse_dt(delivery.get("actualDepartureDateTime")),
                    distance_miles=float(row["mileage"]),
                    weight_lbs=float(row["weightTotal"]) if row.get("weightTotal") is not None else None,
                    commodity=None,
                    customer_rate_usd=float(row["totalSell"]) if row.get("totalSell") is not None else None,
                    carrier_rate_usd=float(row["totalBuy"]) if row.get("totalBuy") is not None else None,
                    created_at=_parse_dt(row.get("createdDate")),
                    updated_at=_parse_dt(row.get("lastModifiedDate")),
                    raw=row,
                )
            )


def _ingest_hauldesk(folder: Path, store: CanonicalStore) -> None:
    carrier_registry: dict[int, Carrier] = {}
    rates_by_load: dict[str, dict[str, float]] = defaultdict(lambda: {"bill": 0.0, "pay": 0.0, "adjustment_abs": 0.0})
    for path in _sync_files(folder):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for carrier in payload["carriers"]:
            carrier_id = str(carrier["carrier_id"])
            model = Carrier(
                broker_id=BROKER_HAULDESK,
                carrier_id=carrier_id,
                name=carrier["carrier_name"],
                mc_number=carrier.get("mc_no"),
                dot_number=carrier.get("dot_no"),
                home=_location(carrier["home_city"], carrier["home_state"], ""),
                phone=carrier.get("phone"),
            )
            carrier_registry[carrier["carrier_id"]] = model
            store.carriers[(BROKER_HAULDESK, carrier_id)] = model

        for rate in payload["rates"]:
            side = rate["side"]
            amount = float(rate["amount_usd"])
            rates_by_load[rate["load_num"]][side] += amount
            if rate["code"] == "ADJUSTMENT":
                rates_by_load[rate["load_num"]]["adjustment_abs"] += abs(amount)

        for row in payload["loads"]:
            customer_id = row["customer_code"]
            store.customers[(BROKER_HAULDESK, customer_id)] = Customer(BROKER_HAULDESK, customer_id, row["customer_name"])
            carrier_id = str(row["carrier_ref"]) if row.get("carrier_ref") is not None else None
            rate_totals = rates_by_load[row["load_num"]]
            store.add_version(
                LoadVersion(
                    broker_id=BROKER_HAULDESK,
                    source_file=str(path.relative_to(folder.parent)),
                    raw_load_id=row["load_num"],
                    status=_hauldesk_status(row["status_code"]),
                    customer_id=customer_id,
                    customer_name=row["customer_name"],
                    carrier_id=carrier_id,
                    equipment=_hauldesk_equipment(row.get("equip")),
                    pickup=_location(row["pu_city"], row["pu_state"], row["pu_zip"]),
                    delivery=_location(row["del_city"], row["del_state"], row["del_zip"]),
                    pickup_open_at=_central_date(row["pu_date"], 8),
                    pickup_close_at=_central_date(row["pu_date"], 16),
                    pickup_actual_at=_parse_local(row.get("pu_departed_at")),
                    delivery_open_at=_central_date(row["del_date"], 8),
                    delivery_close_at=_central_date(row["del_date"], 16),
                    delivery_actual_at=_parse_local(row.get("del_arrived_at")),
                    distance_miles=float(row["dist_km"]) / 1.609344,
                    weight_lbs=float(row["weight_kg"]) / 0.45359237 if row.get("weight_kg") is not None else None,
                    commodity=None,
                    customer_rate_usd=rate_totals["bill"] or None,
                    carrier_rate_usd=rate_totals["pay"] or None,
                    created_at=_parse_local(row.get("entered_at")),
                    updated_at=_parse_local(row.get("updated_at")),
                    raw={**row, "_rate_adjustment_abs": rate_totals["adjustment_abs"]},
                )
            )


def _ingest_brokeros(folder: Path, store: CanonicalStore) -> None:
    for path in _sync_files(folder):
        payload = json.loads(path.read_text(encoding="utf-8"))
        refs = payload["referenced_records"]
        for row in payload["records"]:
            customer_ref = refs[row["bos__Customer__c"]]
            customer_id = row["bos__Customer__c"]
            store.customers[(BROKER_BROKEROS, customer_id)] = Customer(BROKER_BROKEROS, customer_id, customer_ref["Name"])
            carrier_id = None
            if row.get("bos__Carrier__c"):
                carrier_id = row["bos__Carrier__c"]
                carrier_ref = refs[carrier_id]
                store.carriers[(BROKER_BROKEROS, carrier_id)] = Carrier(BROKER_BROKEROS, carrier_id, carrier_ref["Name"])

            stops = sorted(row["bos__Stops__r"], key=lambda stop: stop["bos__Number__c"])
            pickup_stop = stops[0]
            delivery_stop = stops[-1]
            pickup_ref = refs[pickup_stop["bos__Location__c"]]
            delivery_ref = refs[delivery_stop["bos__Location__c"]]
            line_items = row.get("bos__Line_Items__r", [])
            total_weight_lbs = sum(_weight_lbs(item) for item in line_items) if line_items else None
            commodity = ", ".join(sorted({item["bos__Commodity__c"] for item in line_items})) if line_items else None
            store.add_version(
                LoadVersion(
                    broker_id=BROKER_BROKEROS,
                    source_file=str(path.relative_to(folder.parent)),
                    raw_load_id=row["Id"],
                    status=_brokeros_status(row["bos__Load_Status__c"]),
                    customer_id=customer_id,
                    customer_name=customer_ref["Name"],
                    carrier_id=carrier_id,
                    equipment=_brokeros_equipment(row.get("bos__Equipment_Type__c")),
                    pickup=_location(pickup_ref["bos__City__c"], pickup_ref["bos__State__c"], pickup_ref["bos__Postal_Code__c"]),
                    delivery=_location(delivery_ref["bos__City__c"], delivery_ref["bos__State__c"], delivery_ref["bos__Postal_Code__c"]),
                    pickup_open_at=_crm_date(pickup_stop["bos__Scheduled_Date__c"], 8),
                    pickup_close_at=_crm_date(pickup_stop["bos__Scheduled_Date__c"], 16),
                    pickup_actual_at=_parse_crm(pickup_stop.get("bos__Arrival_Time__c")),
                    delivery_open_at=_crm_date(delivery_stop["bos__Scheduled_Date__c"], 8),
                    delivery_close_at=_crm_date(delivery_stop["bos__Scheduled_Date__c"], 16),
                    delivery_actual_at=_parse_crm(delivery_stop.get("bos__Arrival_Time__c")),
                    distance_miles=float(row["bos__Distance_Miles__c"]),
                    weight_lbs=total_weight_lbs,
                    commodity=commodity,
                    customer_rate_usd=float(row["bos__Customer_Rate__c"]) if row.get("bos__Customer_Rate__c") is not None else None,
                    carrier_rate_usd=float(row["bos__Carrier_Rate__c"]) if row.get("bos__Carrier_Rate__c") is not None else None,
                    created_at=_parse_crm(row.get("CreatedDate")),
                    updated_at=_parse_crm(row.get("LastModifiedDate")),
                    raw=row,
                )
            )


def _location(city: str, state: str, zip_code: str) -> Location:
    return Location(city=city.title(), state=state, zip_code=zip_code)


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _parse_local(value: str | None) -> datetime | None:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if value else None


def _parse_crm(value: str | None) -> datetime | None:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.000+0000").replace(tzinfo=timezone.utc) if value else None


def _central_date(value: str, hour: int) -> datetime:
    return datetime.fromisoformat(f"{value}T{hour:02d}:00:00+00:00")


def _crm_date(value: str, hour: int) -> datetime:
    return datetime.fromisoformat(f"{value}T{hour:02d}:00:00+00:00")


def _freightflow_status(status: str) -> LoadStatus:
    return {
        "Quoting": LoadStatus.PLANNED,
        "Booking": LoadStatus.ACTIVE,
        "Dispatched": LoadStatus.COVERED,
        "At Shipper": LoadStatus.IN_TRANSIT,
        "En Route": LoadStatus.IN_TRANSIT,
        "At Receiver": LoadStatus.DELIVERED,
        "Delivered": LoadStatus.DELIVERED,
        "Completed": LoadStatus.COMPLETED,
    }[status]


def _hauldesk_status(status: int) -> LoadStatus:
    return {10: LoadStatus.PLANNED, 20: LoadStatus.ACTIVE, 30: LoadStatus.COVERED, 40: LoadStatus.IN_TRANSIT, 50: LoadStatus.DELIVERED, 90: LoadStatus.COMPLETED}[status]


def _brokeros_status(status: str) -> LoadStatus:
    return {
        "Quotes Requested": LoadStatus.PLANNED,
        "Ready to Book": LoadStatus.ACTIVE,
        "Booked": LoadStatus.COVERED,
        "In Transit": LoadStatus.IN_TRANSIT,
        "Delivered": LoadStatus.DELIVERED,
        "Invoiced": LoadStatus.DELIVERED,
        "Paid": LoadStatus.COMPLETED,
    }[status]


def _freightflow_equipment(value: str | None) -> Equipment:
    if not value:
        return Equipment.UNKNOWN
    if "Reefer" in value:
        return Equipment.REEFER
    if "Flatbed" in value:
        return Equipment.FLATBED
    if "Dry" in value:
        return Equipment.DRY_VAN
    return Equipment.UNKNOWN


def _hauldesk_equipment(value: str | None) -> Equipment:
    return {"V": Equipment.DRY_VAN, "R": Equipment.REEFER, "F": Equipment.FLATBED, None: Equipment.UNKNOWN}.get(value, Equipment.UNKNOWN)


def _brokeros_equipment(value: str | None) -> Equipment:
    return {"Dry Van": Equipment.DRY_VAN, "Reefer": Equipment.REEFER, "Flatbed": Equipment.FLATBED, None: Equipment.UNKNOWN}.get(value, Equipment.UNKNOWN)


def _weight_lbs(item: dict[str, Any]) -> float:
    weight = float(item["bos__Weight__c"])
    return weight / 0.45359237 if item["bos__Weight_Units__c"] == "kg" else weight
