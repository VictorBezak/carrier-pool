from __future__ import annotations

import json
from pathlib import Path

from .cast import TOTAL_SLOTS, slot_filename
from .models import Broker
from .scenarios import SCENARIOS

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


def main() -> None:
    errors: list[str] = []
    active_day11 = 0

    for broker in Broker:
        broker_dir = DATA_DIR / broker.value
        files = sorted(broker_dir.glob("*_sync.json"))
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
            errors.extend(_referential_errors(broker, payload, path))
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

    if errors:
        raise SystemExit("Validation failed:\n" + "\n".join(errors))

    print(f"Validated {len(Broker) * TOTAL_SLOTS} sync files with {active_day11} day-11 active loads.")


def _count_loads(broker: Broker, payload: dict) -> int:
    if broker == Broker.BROKEROS:
        return len(payload["records"])
    return len(payload["loads"])


def _referential_errors(broker: Broker, payload: dict, path: Path) -> list[str]:
    errors: list[str] = []
    if broker == Broker.HAULDESK:
        carriers = {row["carrier_id"] for row in payload["carriers"]}
        for row in payload["loads"]:
            if row["carrier_ref"] is not None and row["carrier_ref"] not in carriers:
                errors.append(f"{path}: missing carrier row for {row['carrier_ref']}")
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
    else:
        for row in payload["loads"]:
            if not (100 <= row["mileage"] <= 800 or row["mileage"] >= 8):
                errors.append(f"{path}: suspicious mileage {row['mileage']}")
    return errors


def _active_count(broker: Broker, payload: dict) -> int:
    if broker == Broker.FREIGHTFLOW:
        return sum(1 for row in payload["loads"] if row["status"] == "Booking")
    if broker == Broker.HAULDESK:
        return sum(1 for row in payload["loads"] if row["status_code"] == 20)
    return sum(1 for row in payload["records"] if row["bos__Load_Status__c"] == "Ready to Book")


if __name__ == "__main__":
    main()
