from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .cast import TOTAL_SLOTS, slot_filename
from .emitters import stable_id, stable_int
from .models import Broker
from .scenarios import SCENARIOS, build_load_specs

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


def main() -> None:
    errors: list[str] = []
    active_day11 = 0
    status_seen: dict[Broker, set] = {broker: set() for broker in Broker}

    for broker in Broker:
        broker_dir = DATA_DIR / broker.value
        files = sorted(broker_dir.glob("*_sync.json"))
        seen_hauldesk_carriers: dict[int, str] = {}
        load_state: dict[str, dict] = {}
        expected_names = [slot_filename(slot) for slot in range(TOTAL_SLOTS)]
        actual_names = [path.name for path in files]
        if actual_names != expected_names:
            errors.append(f"{broker.value}: expected generated sync names do not match actual names")

        for slot, expected_name in enumerate(expected_names):
            path = broker_dir / expected_name
            if not path.exists():
                errors.append(f"missing {path}")
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            count = _count_loads(broker, payload)
            if count < 1 or count > 3:
                errors.append(f"{path}: expected 1-3 loads, found {count}")
            errors.extend(_referential_errors(broker, payload, path, seen_hauldesk_carriers))
            errors.extend(_coherence_errors(broker, payload, path, load_state))
            status_seen[broker].update(_statuses(broker, payload))
            if slot >= 40:
                active_day11 += _active_count(broker, payload)

    if active_day11 < 6 or active_day11 > 8:
        errors.append(f"expected 6-8 day-11 active loads, found {active_day11}")

    manifest = DATA_DIR / "SCENARIOS.md"
    if not manifest.exists():
        errors.append("missing data/SCENARIOS.md")
    else:
        text = manifest.read_text(encoding="utf-8")
        for scenario_key in SCENARIOS:
            if f"`{scenario_key}`" not in text:
                errors.append(f"manifest missing scenario {scenario_key}")

    required_statuses = {
        Broker.FREIGHTFLOW: {"Quoting", "Booking", "Dispatched", "At Shipper", "En Route", "At Receiver", "Delivered", "Completed"},
        Broker.HAULDESK: {10, 20, 30, 40, 50, 90},
        Broker.BROKEROS: {"Quotes Requested", "Ready to Book", "Booked", "In Transit", "Delivered", "Invoiced", "Paid"},
    }
    for broker, required in required_statuses.items():
        missing = required - status_seen[broker]
        if missing:
            errors.append(f"{broker.value}: missing documented statuses {sorted(missing)}")

    errors.extend(_correction_errors())
    errors.extend(_scenario_invariant_errors())

    if errors:
        raise SystemExit("Validation failed:\n" + "\n".join(errors))

    print(f"Validated {len(Broker) * TOTAL_SLOTS} sync files with {active_day11} day-11 active loads.")


def _count_loads(broker: Broker, payload: dict) -> int:
    if broker == Broker.BROKEROS:
        return len(payload["records"])
    return len(payload["loads"])


def _referential_errors(broker: Broker, payload: dict, path: Path, seen_hauldesk_carriers: dict[int, str]) -> list[str]:
    errors: list[str] = []
    if broker == Broker.HAULDESK:
        for row in payload["carriers"]:
            signature = json.dumps(row, sort_keys=True)
            previous = seen_hauldesk_carriers.get(row["carrier_id"])
            if previous == signature:
                errors.append(f"{path}: repeated unchanged HaulDesk carrier row {row['carrier_id']}")
            seen_hauldesk_carriers[row["carrier_id"]] = signature
        for row in payload["loads"]:
            if row["carrier_ref"] is not None and row["carrier_ref"] not in seen_hauldesk_carriers:
                errors.append(f"{path}: carrier {row['carrier_ref']} referenced before first carrier row")
            if not (1000 <= row["weight_kg"] <= 30000):
                errors.append(f"{path}: suspicious kg weight {row['weight_kg']}")
            if not (10 <= row["dist_km"] <= 900):
                errors.append(f"{path}: suspicious km distance {row['dist_km']}")
        load_nums = {row["load_num"] for row in payload["loads"]}
        for row in payload["rates"]:
            if row["load_num"] not in load_nums:
                errors.append(f"{path}: rate references absent load {row['load_num']}")
    elif broker == Broker.BROKEROS:
        refs = payload["referenced_records"]
        for record in payload["records"]:
            if record["bos__Customer__c"] not in refs:
                errors.append(f"{path}: missing customer ref")
            if record["bos__Carrier__c"] is not None and record["bos__Carrier__c"] not in refs:
                errors.append(f"{path}: missing carrier ref")
            for stop in record["bos__Stops__r"]:
                if stop["bos__Location__c"] not in refs:
                    errors.append(f"{path}: missing location ref")
            for item in record["bos__Line_Items__r"]:
                if item["bos__Weight_Units__c"] not in {"lbs", "kg"}:
                    errors.append(f"{path}: unsupported weight unit {item['bos__Weight_Units__c']}")
            for ref in refs.values():
                if ref.get("record_type") == "Carrier":
                    allowed = {"type", "record_type", "Name"}
                    extra = set(ref) - allowed
                    if extra:
                        errors.append(f"{path}: BrokerOS carrier ref has undocumented fields {sorted(extra)}")
    else:
        for row in payload["loads"]:
            if not (100 <= row["mileage"] <= 800 or row["mileage"] >= 8):
                errors.append(f"{path}: suspicious mileage {row['mileage']}")
    return errors


def _coherence_errors(broker: Broker, payload: dict, path: Path, load_state: dict[str, dict]) -> list[str]:
    if broker == Broker.FREIGHTFLOW:
        return _freightflow_coherence(payload, path, load_state)
    if broker == Broker.HAULDESK:
        return _hauldesk_coherence(payload, path, load_state)
    return _brokeros_coherence(payload, path, load_state)


def _freightflow_coherence(payload: dict, path: Path, load_state: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    order = {"Quoting": 0, "Booking": 1, "Dispatched": 2, "At Shipper": 3, "En Route": 4, "At Receiver": 5, "Delivered": 6, "Completed": 7}
    for row in payload["loads"]:
        load_id = str(row["shipmentId"])
        state = load_state.setdefault(load_id, {"status_order": -1, "windows": None, "actuals": {}})
        if order[row["status"]] < state["status_order"]:
            errors.append(f"{path}: status regression on FreightFlow load {load_id}")
        state["status_order"] = max(state["status_order"], order[row["status"]])
        if len(row["stops"]) != 2:
            errors.append(f"{path}: FreightFlow load {load_id} has undocumented stop count {len(row['stops'])}")
        if {stop["stopType"] for stop in row["stops"]} - {"First Pickup", "Last Drop"}:
            errors.append(f"{path}: FreightFlow load {load_id} has undocumented stopType")

        windows = tuple((stop["estimatedReadyDateTime"], stop["estimatedCloseDateTime"]) for stop in row["stops"])
        if state["windows"] is None:
            state["windows"] = windows
        elif state["windows"] != windows:
            errors.append(f"{path}: FreightFlow load {load_id} schedule drifted")

        pickup = row["stops"][0]
        delivery = row["stops"][-1]
        pickup_departed = pickup["actualDepartureDateTime"]
        delivery_departed = delivery["actualDepartureDateTime"]
        errors.extend(_actual_immutability(path, state, "pickup_departed", pickup_departed))
        errors.extend(_actual_immutability(path, state, "delivery_departed", delivery_departed))
        if pickup_departed:
            dep = datetime.fromisoformat(pickup_departed)
            open_at = datetime.fromisoformat(pickup["estimatedReadyDateTime"])
            close_at = datetime.fromisoformat(pickup["estimatedCloseDateTime"])
            if not (open_at <= dep <= close_at + timedelta(hours=4)):
                errors.append(f"{path}: FreightFlow pickup departure outside appointment tolerance")
        if pickup_departed and delivery_departed:
            dep = datetime.fromisoformat(pickup_departed)
            arr = datetime.fromisoformat(delivery_departed)
            if arr <= dep:
                errors.append(f"{path}: FreightFlow delivery departure before pickup departure")
            if arr - dep > timedelta(days=4):
                errors.append(f"{path}: FreightFlow transit duration implausibly long")
        if not isinstance(row["totalSell"], float) or not isinstance(row["weightTotal"], float):
            errors.append(f"{path}: FreightFlow money/weight should serialize as floats")
    return errors


def _hauldesk_coherence(payload: dict, path: Path, load_state: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    order = {10: 0, 20: 1, 30: 2, 40: 3, 50: 4, 90: 5}
    for row in payload["loads"]:
        load_id = row["load_num"]
        state = load_state.setdefault(load_id, {"status_order": -1, "dates": None, "actuals": {}})
        if order[row["status_code"]] < state["status_order"]:
            errors.append(f"{path}: status regression on HaulDesk load {load_id}")
        state["status_order"] = max(state["status_order"], order[row["status_code"]])
        dates = (row["pu_date"], row["del_date"])
        if state["dates"] is None:
            state["dates"] = dates
        elif state["dates"] != dates:
            errors.append(f"{path}: HaulDesk load {load_id} date schedule drifted")
        errors.extend(_actual_immutability(path, state, "pu_departed_at", row["pu_departed_at"]))
        errors.extend(_actual_immutability(path, state, "del_arrived_at", row["del_arrived_at"]))
        if row["pu_departed_at"] and row["del_arrived_at"]:
            departed = datetime.fromisoformat(row["pu_departed_at"])
            arrived = datetime.fromisoformat(row["del_arrived_at"])
            if arrived <= departed:
                errors.append(f"{path}: HaulDesk delivery before pickup departure")
            if arrived - departed > timedelta(days=4):
                errors.append(f"{path}: HaulDesk transit duration implausibly long")
        if not isinstance(row["weight_kg"], float) or not isinstance(row["dist_km"], float):
            errors.append(f"{path}: HaulDesk weight/distance should serialize as floats")
    for rate in payload["rates"]:
        if not isinstance(rate["amount_usd"], float):
            errors.append(f"{path}: HaulDesk rate amount should serialize as float")
    return errors


def _brokeros_coherence(payload: dict, path: Path, load_state: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    order = {"Quotes Requested": 0, "Ready to Book": 1, "Booked": 2, "In Transit": 3, "Delivered": 4, "Invoiced": 5, "Paid": 6}
    for row in payload["records"]:
        load_id = row["Id"]
        state = load_state.setdefault(load_id, {"status_order": -1, "dates": None, "actuals": {}})
        if order[row["bos__Load_Status__c"]] < state["status_order"]:
            errors.append(f"{path}: status regression on BrokerOS load {load_id}")
        state["status_order"] = max(state["status_order"], order[row["bos__Load_Status__c"]])
        stops = sorted(row["bos__Stops__r"], key=lambda stop: stop["bos__Number__c"])
        dates = tuple(stop["bos__Scheduled_Date__c"] for stop in stops)
        if state["dates"] is None:
            state["dates"] = dates
        elif state["dates"] != dates:
            errors.append(f"{path}: BrokerOS load {load_id} scheduled dates drifted")
        for index, stop in enumerate(stops, start=1):
            errors.extend(_actual_immutability(path, state, f"arrival_{index}", stop["bos__Arrival_Time__c"]))
        arrivals = [datetime.strptime(stop["bos__Arrival_Time__c"], "%Y-%m-%dT%H:%M:%S.000+0000") for stop in stops if stop["bos__Arrival_Time__c"]]
        if arrivals != sorted(arrivals):
            errors.append(f"{path}: BrokerOS stop arrivals are not chronological")
        if not isinstance(row["bos__Distance_Miles__c"], float) or not isinstance(row["bos__Customer_Rate__c"], float):
            errors.append(f"{path}: BrokerOS distance/rates should serialize as floats")
    return errors


def _actual_immutability(path: Path, state: dict, field: str, value: str | None) -> list[str]:
    previous = state["actuals"].get(field)
    if previous is not None and value is not None and previous != value:
        return [f"{path}: actual {field} changed after it was recorded"]
    if previous is None and value is not None:
        state["actuals"][field] = value
    return []


def _statuses(broker: Broker, payload: dict) -> set:
    if broker == Broker.FREIGHTFLOW:
        return {row["status"] for row in payload["loads"]}
    if broker == Broker.HAULDESK:
        return {row["status_code"] for row in payload["loads"]}
    return {row["bos__Load_Status__c"] for row in payload["records"]}


def _active_count(broker: Broker, payload: dict) -> int:
    if broker == Broker.FREIGHTFLOW:
        return sum(1 for row in payload["loads"] if row["status"] == "Booking")
    if broker == Broker.HAULDESK:
        return sum(1 for row in payload["loads"] if row["status_code"] == 20)
    return sum(1 for row in payload["records"] if row["bos__Load_Status__c"] == "Ready to Book")


def _correction_errors() -> list[str]:
    errors: list[str] = []
    for spec in build_load_specs():
        if not spec.correction_delta_usd:
            continue
        if spec.broker == Broker.FREIGHTFLOW:
            load_id = 127000000 + stable_int(spec.key, 6)
            buys = []
            for path in sorted((DATA_DIR / spec.broker.value).glob("*_sync.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                buys.extend(row["totalBuy"] for row in payload["loads"] if row["shipmentId"] == load_id and row["totalBuy"] is not None)
            if len(set(buys)) < 2:
                errors.append(f"{spec.broker.value}: correction {spec.key} did not restate totalBuy")
        elif spec.broker == Broker.HAULDESK:
            load_num = f"HD-2026-{stable_int(spec.key, 6):06d}"
            adjustments = []
            for path in sorted((DATA_DIR / spec.broker.value).glob("*_sync.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                adjustments.extend(rate for rate in payload["rates"] if rate["load_num"] == load_num and rate["code"] == "ADJUSTMENT")
            if not adjustments:
                errors.append(f"{spec.broker.value}: correction {spec.key} did not emit an ADJUSTMENT rate")
        else:
            load_id = stable_id("a0j", f"load:{spec.key}")
            buys = []
            for path in sorted((DATA_DIR / spec.broker.value).glob("*_sync.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                buys.extend(row["bos__Carrier_Rate__c"] for row in payload["records"] if row["Id"] == load_id and row["bos__Carrier_Rate__c"] is not None)
            if len(set(buys)) < 2:
                errors.append(f"{spec.broker.value}: correction {spec.key} did not restate bos__Carrier_Rate__c")
    return errors


def _scenario_invariant_errors() -> list[str]:
    errors: list[str] = []
    carriers_by_load: dict[tuple[Broker, str], list[str | int | None]] = {}
    statuses_by_load: dict[tuple[Broker, str], set] = {}
    late_counts: dict[Broker, dict[str, int]] = {broker: {"pickup": 0, "delivery": 0} for broker in Broker}
    hauldesk_linehaul: dict[str, int] = {}

    for broker in Broker:
        for path in sorted((DATA_DIR / broker.value).glob("*_sync.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if broker == Broker.FREIGHTFLOW:
                for row in payload["loads"]:
                    key = (broker, str(row["shipmentId"]))
                    statuses_by_load.setdefault(key, set()).add(row["status"])
                    carrier = row["carrier"]["carrierMasterId"] if row["carrier"] else None
                    carriers_by_load.setdefault(key, []).append(carrier)
                    pickup, delivery = row["stops"][0], row["stops"][-1]
                    if pickup["actualDepartureDateTime"] and datetime.fromisoformat(pickup["actualDepartureDateTime"]) > datetime.fromisoformat(pickup["estimatedCloseDateTime"]):
                        late_counts[broker]["pickup"] += 1
                    if delivery["actualDepartureDateTime"] and datetime.fromisoformat(delivery["actualDepartureDateTime"]) > datetime.fromisoformat(delivery["estimatedCloseDateTime"]):
                        late_counts[broker]["delivery"] += 1
            elif broker == Broker.HAULDESK:
                for row in payload["loads"]:
                    key = (broker, row["load_num"])
                    statuses_by_load.setdefault(key, set()).add(row["status_code"])
                    carriers_by_load.setdefault(key, []).append(row["carrier_ref"])
                    if row["pu_departed_at"] and datetime.fromisoformat(row["pu_departed_at"]) > datetime.fromisoformat(f"{row['pu_date']}T16:00:00"):
                        late_counts[broker]["pickup"] += 1
                    if row["del_arrived_at"] and datetime.fromisoformat(row["del_arrived_at"]) > datetime.fromisoformat(f"{row['del_date']}T16:00:00"):
                        late_counts[broker]["delivery"] += 1
                for rate in payload["rates"]:
                    if rate["side"] == "pay" and rate["code"] == "LINEHAUL":
                        hauldesk_linehaul[rate["load_num"]] = hauldesk_linehaul.get(rate["load_num"], 0) + 1
            else:
                refs = payload["referenced_records"]
                for row in payload["records"]:
                    key = (broker, row["Id"])
                    statuses_by_load.setdefault(key, set()).add(row["bos__Load_Status__c"])
                    carriers_by_load.setdefault(key, []).append(row["bos__Carrier__c"])
                    stops = sorted(row["bos__Stops__r"], key=lambda stop: stop["bos__Number__c"])
                    for stop in stops:
                        if not stop["bos__Arrival_Time__c"]:
                            continue
                        arrival = datetime.strptime(stop["bos__Arrival_Time__c"], "%Y-%m-%dT%H:%M:%S.000+0000")
                        close_at = datetime.fromisoformat(f"{stop['bos__Scheduled_Date__c']}T16:00:00")
                        late_key = "pickup" if stop["bos__Is_Pickup__c"] else "delivery" if stop["bos__Is_Dropoff__c"] else None
                        if late_key and arrival > close_at:
                            late_counts[broker][late_key] += 1

    for (broker, load_id), carriers in carriers_by_load.items():
        compact = []
        for carrier in carriers:
            if not compact or compact[-1] != carrier:
                compact.append(carrier)
        if len([carrier for carrier in compact if carrier is not None]) > 2:
            errors.append(f"{broker.value}: load {load_id} changes carrier more than once or reverts")

    active_status = {Broker.FREIGHTFLOW: "Booking", Broker.HAULDESK: 20, Broker.BROKEROS: "Ready to Book"}
    for spec in build_load_specs():
        if spec.lifecycle != "full":
            continue
        key = (spec.broker, _raw_load_id(spec))
        if active_status[spec.broker] not in statuses_by_load.get(key, set()):
            errors.append(f"{spec.broker.value}: full lifecycle load {spec.key} never appears ACTIVE")

    for load_num, count in hauldesk_linehaul.items():
        if count > 1:
            errors.append(f"{Broker.HAULDESK.value}: load {load_num} has {count} pay LINEHAUL rows")

    for broker, counts in late_counts.items():
        if counts["pickup"] == 0:
            errors.append(f"{broker.value}: expected at least one late pickup")
        if counts["delivery"] == 0:
            errors.append(f"{broker.value}: expected at least one late delivery")
    return errors


def _raw_load_id(spec) -> str:
    if spec.broker == Broker.FREIGHTFLOW:
        return str(127000000 + stable_int(spec.key, 6))
    if spec.broker == Broker.HAULDESK:
        return f"HD-2026-{stable_int(spec.key, 6):06d}"
    return stable_id("a0j", f"load:{spec.key}")


if __name__ == "__main__":
    main()
