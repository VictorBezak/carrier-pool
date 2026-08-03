from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .db import connect, init_db
from .ingest import BROKER_IDS, BROKER_HAULDESK, HaulDeskRate, ParsedSync, _add_hauldesk_rates, parse_sync_file, sync_timestamp
from .models import Carrier, Customer, LoadVersion, Location

BROKER_ORDER = {broker_id: index for index, broker_id in enumerate(BROKER_IDS)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest TMS sync files into Postgres one file at a time.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="Path to generated TMS sync data")
    parser.add_argument("--database-url", default=None, help="Postgres connection string; defaults to DATABASE_URL")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N new sync files")
    args = parser.parse_args()

    with connect(args.database_url) as conn:
        init_db(conn)
        processed = sync_data(conn, args.data_dir, limit=args.limit)
    print(f"Processed {processed} new sync files.")


def iter_sync_files(data_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for broker_id in BROKER_IDS:
        paths.extend(sorted((data_dir / broker_id).glob("*_sync.json")))
    return sorted(paths, key=lambda path: (sync_timestamp(path), BROKER_ORDER[path.parent.name], path.name))


def sync_data(conn, data_dir: Path, limit: int | None = None) -> int:
    processed = 0
    rate_totals = _load_hauldesk_rate_totals(conn)
    for path in iter_sync_files(data_dir):
        source_file = f"{path.parent.name}/{path.name}"
        if _sync_file_exists(conn, path.parent.name, source_file):
            continue
        parsed = parse_sync_file(path, rate_totals if path.parent.name == BROKER_HAULDESK else None)
        with conn.transaction():
            write_parsed_sync(conn, parsed)
        if parsed.broker_id == BROKER_HAULDESK:
            _add_hauldesk_rates(rate_totals, parsed.hauldesk_rates)
        processed += 1
        if limit is not None and processed >= limit:
            break
    conn.commit()
    return processed


def write_parsed_sync(conn, parsed: ParsedSync) -> None:
    with conn.cursor() as cur:
        for carrier in parsed.carriers:
            _upsert_carrier(cur, carrier)
        for customer in parsed.customers:
            _upsert_customer(cur, customer)
        for rate in parsed.hauldesk_rates:
            _upsert_hauldesk_rate(cur, rate)
        for version in parsed.versions:
            _upsert_load_version(cur, version)
        cur.execute(
            """
            insert into sync_file (broker_id, source_file, filename, synced_at)
            values (%s, %s, %s, %s)
            on conflict (broker_id, source_file) do nothing
            """,
            (parsed.broker_id, parsed.source_file, Path(parsed.source_file).name, parsed.synced_at),
        )


def _load_hauldesk_rate_totals(conn) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"bill": 0.0, "pay": 0.0, "adjustment_abs": 0.0})
    with conn.cursor() as cur:
        cur.execute("select load_num, side, code, amount_usd from hauldesk_rate where broker_id = %s order by synced_at, rate_id", (BROKER_HAULDESK,))
        for load_num, side, code, amount_usd in cur.fetchall():
            totals[load_num][side] += float(amount_usd)
            if code == "ADJUSTMENT":
                totals[load_num]["adjustment_abs"] += abs(float(amount_usd))
    return totals


def _sync_file_exists(conn, broker_id: str, source_file: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("select 1 from sync_file where broker_id = %s and source_file = %s", (broker_id, source_file))
        return cur.fetchone() is not None


def _upsert_carrier(cur, carrier: Carrier) -> None:
    cur.execute(
        """
        insert into carrier (broker_id, carrier_id, name, mc_number, dot_number, phone, home_city, home_state, home_zip_code)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (broker_id, carrier_id) do update set
            name = excluded.name,
            mc_number = excluded.mc_number,
            dot_number = excluded.dot_number,
            phone = excluded.phone,
            home_city = excluded.home_city,
            home_state = excluded.home_state,
            home_zip_code = excluded.home_zip_code,
            updated_at = now()
        """,
        (
            carrier.broker_id,
            carrier.carrier_id,
            carrier.name,
            carrier.mc_number,
            carrier.dot_number,
            carrier.phone,
            carrier.home.city if carrier.home else None,
            carrier.home.state if carrier.home else None,
            carrier.home.zip_code if carrier.home else None,
        ),
    )


def _upsert_customer(cur, customer: Customer) -> None:
    cur.execute(
        """
        insert into customer (broker_id, customer_id, name)
        values (%s, %s, %s)
        on conflict (broker_id, customer_id) do update set
            name = excluded.name,
            updated_at = now()
        """,
        (customer.broker_id, customer.customer_id, customer.name),
    )


def _upsert_hauldesk_rate(cur, rate: HaulDeskRate) -> None:
    cur.execute(
        """
        insert into hauldesk_rate (broker_id, rate_id, source_file, synced_at, load_num, side, code, amount_usd, raw)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        on conflict (broker_id, rate_id) do update set
            source_file = excluded.source_file,
            synced_at = excluded.synced_at,
            load_num = excluded.load_num,
            side = excluded.side,
            code = excluded.code,
            amount_usd = excluded.amount_usd,
            raw = excluded.raw
        """,
        (rate.broker_id, rate.rate_id, rate.source_file, rate.synced_at, rate.load_num, rate.side, rate.code, rate.amount_usd, _json(rate.raw)),
    )


def _upsert_load_version(cur, version: LoadVersion) -> None:
    cur.execute(
        """
        insert into load_version (
            broker_id, source_file, synced_at, raw_load_id, status, customer_id, customer_name, carrier_id, equipment,
            pickup_city, pickup_state, pickup_zip_code, delivery_city, delivery_state, delivery_zip_code,
            pickup_open_at, pickup_close_at, pickup_arrived_at, pickup_departed_at,
            delivery_open_at, delivery_close_at, delivery_arrived_at, delivery_departed_at,
            distance_miles, weight_lbs, commodity, customer_rate_usd, carrier_rate_usd, created_at, updated_at, raw
        )
        values (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s::jsonb
        )
        on conflict (broker_id, raw_load_id, source_file) do update set
            synced_at = excluded.synced_at,
            status = excluded.status,
            customer_id = excluded.customer_id,
            customer_name = excluded.customer_name,
            carrier_id = excluded.carrier_id,
            equipment = excluded.equipment,
            pickup_city = excluded.pickup_city,
            pickup_state = excluded.pickup_state,
            pickup_zip_code = excluded.pickup_zip_code,
            delivery_city = excluded.delivery_city,
            delivery_state = excluded.delivery_state,
            delivery_zip_code = excluded.delivery_zip_code,
            pickup_open_at = excluded.pickup_open_at,
            pickup_close_at = excluded.pickup_close_at,
            pickup_arrived_at = excluded.pickup_arrived_at,
            pickup_departed_at = excluded.pickup_departed_at,
            delivery_open_at = excluded.delivery_open_at,
            delivery_close_at = excluded.delivery_close_at,
            delivery_arrived_at = excluded.delivery_arrived_at,
            delivery_departed_at = excluded.delivery_departed_at,
            distance_miles = excluded.distance_miles,
            weight_lbs = excluded.weight_lbs,
            commodity = excluded.commodity,
            customer_rate_usd = excluded.customer_rate_usd,
            carrier_rate_usd = excluded.carrier_rate_usd,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at,
            raw = excluded.raw
        """,
        (
            version.broker_id,
            version.source_file,
            version.synced_at,
            version.raw_load_id,
            version.status.value,
            version.customer_id,
            version.customer_name,
            version.carrier_id,
            version.equipment.value,
            version.pickup.city,
            version.pickup.state,
            version.pickup.zip_code,
            version.delivery.city,
            version.delivery.state,
            version.delivery.zip_code,
            version.pickup_open_at,
            version.pickup_close_at,
            version.pickup_arrived_at,
            version.pickup_departed_at,
            version.delivery_open_at,
            version.delivery_close_at,
            version.delivery_arrived_at,
            version.delivery_departed_at,
            version.distance_miles,
            version.weight_lbs,
            version.commodity,
            version.customer_rate_usd,
            version.carrier_rate_usd,
            version.created_at,
            version.updated_at,
            _json(version.raw),
        ),
    )


def _json(value: dict) -> str:
    import json

    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _locations(rows: Iterable[tuple]) -> list[Location]:
    return [Location(city=row[0], state=row[1], zip_code=row[2]) for row in rows]


if __name__ == "__main__":
    main()
