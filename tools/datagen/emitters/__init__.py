from __future__ import annotations

import hashlib
from datetime import timedelta, timezone
from typing import Any

from ..cast import CARRIERS, CUSTOMERS, PLACES, road_miles, slot_datetime
from ..models import Broker, CanonicalStatus, Equipment, LoadEvent, LoadSpec, Place


def emit_sync(broker: Broker, slot: int, events: list[LoadEvent]) -> dict[str, Any]:
    if broker == Broker.FREIGHTFLOW:
        return _emit_freightflow(slot, events)
    if broker == Broker.HAULDESK:
        return _emit_hauldesk(slot, events)
    if broker == Broker.BROKEROS:
        return _emit_brokeros(slot, events)
    raise ValueError(f"Unsupported broker: {broker}")


def stable_int(key: str, digits: int = 7) -> int:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return int(digest[:10], 16) % (10**digits)


def stable_id(prefix: str, key: str, size: int = 18) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return (prefix + digest)[:size]


def _iso_central(dt) -> str:
    return dt.isoformat(timespec="seconds")


def _iso_utc_crm(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def _naive_central(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _equipment_freightflow(equipment: Equipment) -> str | None:
    return {
        Equipment.DRY_VAN: "53 ft Van | Dry",
        Equipment.REEFER: "53 ft Van | Reefer",
        Equipment.FLATBED: "48 ft Flatbed",
        Equipment.UNKNOWN: None,
    }[equipment]


def _equipment_hauldesk(equipment: Equipment) -> str | None:
    return {
        Equipment.DRY_VAN: "V",
        Equipment.REEFER: "R",
        Equipment.FLATBED: "F",
        Equipment.UNKNOWN: None,
    }[equipment]


def _equipment_brokeros(spec: LoadSpec) -> str | None:
    if spec.brokeros_null_equipment or spec.equipment == Equipment.UNKNOWN:
        return None
    return {
        Equipment.DRY_VAN: "Dry Van",
        Equipment.REEFER: "Reefer",
        Equipment.FLATBED: "Flatbed",
    }[spec.equipment]


def _freightflow_status(status: CanonicalStatus) -> str:
    return {
        CanonicalStatus.ACTIVE: "Booking",
        CanonicalStatus.COVERED: "Dispatched",
        CanonicalStatus.IN_TRANSIT: "En Route",
        CanonicalStatus.DELIVERED: "Delivered",
        CanonicalStatus.COMPLETED: "Completed",
    }[status]


def _hauldesk_status(status: CanonicalStatus) -> int:
    return {
        CanonicalStatus.ACTIVE: 20,
        CanonicalStatus.COVERED: 30,
        CanonicalStatus.IN_TRANSIT: 40,
        CanonicalStatus.DELIVERED: 50,
        CanonicalStatus.COMPLETED: 90,
    }[status]


def _brokeros_status(status: CanonicalStatus) -> str:
    return {
        CanonicalStatus.ACTIVE: "Ready to Book",
        CanonicalStatus.COVERED: "Booked",
        CanonicalStatus.IN_TRANSIT: "In Transit",
        CanonicalStatus.DELIVERED: "Delivered",
        CanonicalStatus.COMPLETED: "Paid",
    }[status]


def _stops(spec: LoadSpec) -> list[Place]:
    return [PLACES[spec.pickup], *(PLACES[key] for key in spec.intermediate_stops), PLACES[spec.delivery]]


def _emit_freightflow(slot: int, events: list[LoadEvent]) -> dict[str, Any]:
    return {
        "syncedAt": _iso_central(slot_datetime(slot)),
        "loads": [_freightflow_load(event) for event in sorted(events, key=lambda item: item.spec.key)],
    }


def _freightflow_load(event: LoadEvent) -> dict[str, Any]:
    spec = event.spec
    customer = CUSTOMERS[spec.customer]
    carrier = CARRIERS[spec.carrier] if spec.carrier and event.status != CanonicalStatus.ACTIVE else None
    stop_rows = []
    for index, place in enumerate(_stops(spec), start=1):
        pickup = index == 1
        delivery = index == len(_stops(spec))
        ready = event.created_at.date() + timedelta(days=index)
        departed = None
        if pickup and event.status in {CanonicalStatus.IN_TRANSIT, CanonicalStatus.DELIVERED, CanonicalStatus.COMPLETED}:
            departed = _iso_central(slot_datetime(event.slot) - timedelta(hours=2))
        if delivery and event.status in {CanonicalStatus.DELIVERED, CanonicalStatus.COMPLETED}:
            departed = _iso_central(slot_datetime(event.slot) - timedelta(hours=1))
        stop_rows.append(
            {
                "stopType": "First Pickup" if pickup else "Last Drop" if delivery else f"Stop {index}",
                "city": place.city.upper(),
                "state": place.state,
                "zipCode": place.zip_code,
                "estimatedReadyDateTime": _iso_central(slot_datetime(event.slot).replace(hour=8) + timedelta(days=index)),
                "estimatedCloseDateTime": _iso_central(slot_datetime(event.slot).replace(hour=16) + timedelta(days=index)),
                "actualDepartureDateTime": departed,
            }
        )

    return {
        "shipmentId": 127000000 + stable_int(spec.key, 6),
        "status": _freightflow_status(event.status),
        "mileage": road_miles(spec.pickup, spec.delivery),
        "totalSell": round(spec.sell_usd, 2),
        "totalBuy": round(event.buy_usd, 2) if event.buy_usd is not None else None,
        "customer": {"customerId": 880000 + stable_int(spec.customer, 5), "name": customer.name},
        "carrier": None
        if carrier is None
        else {
            "carrierMasterId": 830000 + stable_int(carrier.key, 5),
            "name": carrier.name.upper() if spec.broker == Broker.FREIGHTFLOW else carrier.name,
            "mcNumber": carrier.mc,
            "dotNumber": carrier.dot,
            "phoneNumber": carrier.phone,
        },
        "equipment": _equipment_freightflow(spec.equipment),
        "weightTotal": spec.weight_lbs,
        "stops": stop_rows,
        "createdDate": _iso_central(event.created_at),
        "lastModifiedDate": _iso_central(event.modified_at),
    }


def _emit_hauldesk(slot: int, events: list[LoadEvent]) -> dict[str, Any]:
    carrier_rows = []
    seen_carriers = set()
    for event in events:
        if event.spec.carrier and event.status != CanonicalStatus.ACTIVE and event.spec.carrier not in seen_carriers:
            seen_carriers.add(event.spec.carrier)
            carrier_rows.append(_hauldesk_carrier(event.spec, slot))

    return {
        "synced_at": _naive_central(slot_datetime(slot)),
        "loads": [_hauldesk_load(event) for event in sorted(events, key=lambda item: item.spec.key)],
        "carriers": carrier_rows,
        "rates": [row for event in sorted(events, key=lambda item: item.spec.key) for row in _hauldesk_rates(event)],
    }


def _hauldesk_load(event: LoadEvent) -> dict[str, Any]:
    spec = event.spec
    pickup = PLACES[spec.pickup]
    delivery = PLACES[spec.delivery]
    carrier_ref = 66000 + stable_int(spec.carrier, 4) if spec.carrier and event.status != CanonicalStatus.ACTIVE else None
    return {
        "load_num": f"HD-2026-{stable_int(spec.key, 6):06d}",
        "status_code": _hauldesk_status(event.status),
        "customer_code": f"C-{stable_int(spec.customer, 4):04d}",
        "customer_name": CUSTOMERS[spec.customer].name,
        "carrier_ref": carrier_ref,
        "equip": _equipment_hauldesk(spec.equipment),
        "weight_kg": round(spec.weight_lbs * 0.45359237, 1),
        "dist_km": round(road_miles(spec.pickup, spec.delivery) * 1.609344, 1),
        "pu_city": pickup.city,
        "pu_state": pickup.state,
        "pu_zip": pickup.zip_code,
        "pu_date": (event.created_at.date() + timedelta(days=1)).isoformat(),
        "pu_departed_at": _naive_central(slot_datetime(event.slot) - timedelta(hours=2)) if event.status in {CanonicalStatus.IN_TRANSIT, CanonicalStatus.DELIVERED, CanonicalStatus.COMPLETED} else None,
        "del_city": delivery.city,
        "del_state": delivery.state,
        "del_zip": delivery.zip_code,
        "del_date": (event.created_at.date() + timedelta(days=2)).isoformat(),
        "del_arrived_at": _naive_central(slot_datetime(event.slot) - timedelta(hours=1)) if event.status in {CanonicalStatus.DELIVERED, CanonicalStatus.COMPLETED} else None,
        "entered_at": _naive_central(event.created_at),
        "updated_at": _naive_central(event.modified_at),
    }


def _hauldesk_carrier(spec: LoadSpec, slot: int) -> dict[str, Any]:
    carrier = CARRIERS[spec.carrier]
    renamed = spec.hauldesk_carrier_rename_slot is not None and slot >= spec.hauldesk_carrier_rename_slot
    name = f"{carrier.name} DBA GULFWAY" if renamed else carrier.name
    home = PLACES[carrier.home]
    return {
        "carrier_id": 66000 + stable_int(carrier.key, 4),
        "carrier_name": name,
        "mc_no": carrier.mc,
        "dot_no": carrier.dot,
        "home_city": home.city,
        "home_state": home.state,
        "phone": carrier.phone,
    }


def _hauldesk_rates(event: LoadEvent) -> list[dict[str, Any]]:
    spec = event.spec
    load_num = f"HD-2026-{stable_int(spec.key, 6):06d}"
    rows: list[dict[str, Any]] = []
    if event.status == CanonicalStatus.ACTIVE:
        rows.append(_rate_row(spec.key, load_num, "bill", "LINEHAUL", spec.sell_usd, event.modified_at, "bill"))
    elif event.status == CanonicalStatus.COVERED and event.buy_usd is not None:
        rows.append(_rate_row(spec.key, load_num, "pay", "LINEHAUL", event.buy_usd, event.modified_at, "pay"))
    elif event.is_correction:
        rows.append(_rate_row(spec.key, load_num, "pay", "ADJUSTMENT", event.correction_delta_usd, event.modified_at, "adjustment"))
    return rows


def _rate_row(spec_key: str, load_num: str, side: str, code: str, amount: float, created_at, salt: str) -> dict[str, Any]:
    return {
        "rate_id": 910000 + stable_int(f"{spec_key}:{salt}", 6),
        "load_num": load_num,
        "side": side,
        "code": code,
        "amount_usd": round(amount, 2),
        "created_at": _naive_central(created_at),
    }


def _emit_brokeros(slot: int, events: list[LoadEvent]) -> dict[str, Any]:
    referenced: dict[str, dict[str, Any]] = {}
    records = []
    for event in sorted(events, key=lambda item: item.spec.key):
        record, refs = _brokeros_load(event)
        records.append(record)
        referenced.update(refs)
    return {"synced_at": _iso_utc_crm(slot_datetime(slot)), "records": records, "referenced_records": referenced}


def _brokeros_load(event: LoadEvent) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = event.spec
    refs: dict[str, dict[str, Any]] = {}
    customer_id = stable_id("001", f"customer:{spec.customer}")
    refs[customer_id] = {"type": "Account", "record_type": "Customer", "Name": CUSTOMERS[spec.customer].name}
    carrier_id = None
    if spec.carrier and event.status != CanonicalStatus.ACTIVE:
        carrier = CARRIERS[spec.carrier]
        carrier_id = stable_id("001", f"carrier:{carrier.key}")
        refs[carrier_id] = {
            "type": "Account",
            "record_type": "Carrier",
            "Name": carrier.name,
            "bos__MC_Number__c": carrier.mc,
            "bos__DOT_Number__c": carrier.dot,
            "Phone": carrier.phone,
        }

    stop_rows = []
    for index, place in enumerate(_stops(spec), start=1):
        location_id = stable_id("001", f"location:{place.key}")
        refs[location_id] = {
            "type": "Location",
            "Name": f"{place.city} Facility",
            "bos__City__c": place.city,
            "bos__State__c": place.state,
            "bos__Postal_Code__c": place.zip_code,
        }
        is_pickup = index == 1
        is_dropoff = index == len(_stops(spec))
        arrival = None
        if is_pickup and event.status in {CanonicalStatus.IN_TRANSIT, CanonicalStatus.DELIVERED, CanonicalStatus.COMPLETED}:
            arrival = _iso_utc_crm(slot_datetime(event.slot) - timedelta(hours=3))
        if is_dropoff and event.status in {CanonicalStatus.DELIVERED, CanonicalStatus.COMPLETED}:
            arrival = _iso_utc_crm(slot_datetime(event.slot) - timedelta(hours=2))
        stop_rows.append(
            {
                "bos__Number__c": float(index),
                "bos__Is_Pickup__c": is_pickup,
                "bos__Is_Dropoff__c": is_dropoff,
                "bos__Location__c": location_id,
                "bos__Scheduled_Date__c": (event.created_at.date() + timedelta(days=index)).isoformat(),
                "bos__Arrival_Time__c": arrival,
            }
        )

    weight = spec.weight_lbs
    units = spec.brokeros_weight_units
    if units == "kg":
        weight = round(weight * 0.45359237, 1)

    return (
        {
            "Id": stable_id("a0j", f"load:{spec.key}"),
            "Name": f"SHP{stable_int(spec.key, 7):07d}",
            "bos__Load_Status__c": _brokeros_status(event.status),
            "bos__Distance_Miles__c": road_miles(spec.pickup, spec.delivery),
            "bos__Customer__c": customer_id,
            "bos__Carrier__c": carrier_id,
            "bos__Equipment_Type__c": _equipment_brokeros(spec),
            "bos__Customer_Rate__c": round(spec.sell_usd, 2),
            "bos__Carrier_Rate__c": round(event.buy_usd, 2) if event.buy_usd is not None else None,
            "bos__Stops__r": stop_rows,
            "bos__Line_Items__r": [
                {
                    "bos__Commodity__c": "General freight",
                    "bos__Weight__c": weight,
                    "bos__Weight_Units__c": units,
                    "bos__Pallet_Count__c": 18.0,
                }
            ],
            "CreatedDate": _iso_utc_crm(event.created_at),
            "LastModifiedDate": _iso_utc_crm(event.modified_at),
        },
        refs,
    )
