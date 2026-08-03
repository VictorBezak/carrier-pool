from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import CanonicalStore, Carrier, Customer, Equipment, LoadStatus, LoadVersion, Location


def store_from_db(conn) -> CanonicalStore:
    store = CanonicalStore()
    with conn.cursor() as cur:
        cur.execute(
            """
            select broker_id, carrier_id, name, mc_number, dot_number, phone, home_city, home_state, home_zip_code
            from carrier
            order by broker_id, carrier_id
            """
        )
        for row in cur.fetchall():
            broker_id, carrier_id, name, mc_number, dot_number, phone, home_city, home_state, home_zip_code = row
            home = Location(home_city, home_state, home_zip_code or "") if home_city and home_state else None
            store.carriers[(broker_id, carrier_id)] = Carrier(broker_id, carrier_id, name, mc_number, dot_number, home, phone)

        cur.execute("select broker_id, customer_id, name from customer order by broker_id, customer_id")
        for broker_id, customer_id, name in cur.fetchall():
            store.customers[(broker_id, customer_id)] = Customer(broker_id, customer_id, name)

        cur.execute(
            """
            select broker_id, source_file, synced_at, raw_load_id, status, customer_id, customer_name,
                   carrier_id, equipment,
                   pickup_city, pickup_state, pickup_zip_code, delivery_city, delivery_state, delivery_zip_code,
                   pickup_open_at, pickup_close_at, pickup_arrived_at, pickup_departed_at,
                   delivery_open_at, delivery_close_at, delivery_arrived_at, delivery_departed_at,
                   distance_miles, weight_lbs, commodity, customer_rate_usd, carrier_rate_usd,
                   created_at, updated_at, raw
            from load_version
            order by synced_at, broker_id, source_file, raw_load_id
            """
        )
        for row in cur.fetchall():
            store.add_version(_version_from_row(row))
    return store


def brokers(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        # Counts describe the current state of each load, not every version ever synced:
        # a load that was ACTIVE last week and is COMPLETED today is not awaiting coverage.
        # The distinct-on ordering mirrors CanonicalStore.add_version so DB mode and file
        # mode agree on which version is current.
        cur.execute(
            """
            select b.broker_id, b.name, b.pool_opt_in,
                   count(current_version.raw_load_id) as load_count,
                   count(*) filter (where current_version.status = 'active') as active_count
            from broker b
            left join (
                select distinct on (broker_id, raw_load_id) broker_id, raw_load_id, status
                from load_version
                order by broker_id, raw_load_id, synced_at desc, source_file desc
            ) current_version on current_version.broker_id = b.broker_id
            group by b.broker_id, b.name, b.pool_opt_in
            order by b.broker_id
            """
        )
        return [
            {"broker_id": row[0], "name": row[1], "pool_opt_in": row[2], "load_count": row[3], "active_count": row[4]}
            for row in cur.fetchall()
        ]


def syncs(conn, broker_id: str | None = None) -> list[dict[str, Any]]:
    query = "select broker_id, source_file, filename, synced_at, processed_at from sync_file"
    params: tuple[Any, ...] = ()
    if broker_id:
        query += " where broker_id = %s"
        params = (broker_id,)
    query += " order by synced_at, broker_id, filename"
    with conn.cursor() as cur:
        cur.execute(query, params)
        return [
            {"broker_id": row[0], "source_file": row[1], "filename": row[2], "synced_at": row[3], "processed_at": row[4]}
            for row in cur.fetchall()
        ]


def set_pool_opt_in(conn, broker_id: str, enabled: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("update broker set pool_opt_in = %s where broker_id = %s", (enabled, broker_id))
    conn.commit()


def pool_opt_ins(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("select broker_id from broker where pool_opt_in")
        return {row[0] for row in cur.fetchall()}


def latest_watermark(conn) -> tuple[int, datetime | None]:
    with conn.cursor() as cur:
        cur.execute("select count(*), max(processed_at) from sync_file")
        row = cur.fetchone()
        return int(row[0]), row[1]


def _version_from_row(row: tuple) -> LoadVersion:
    (
        broker_id,
        source_file,
        synced_at,
        raw_load_id,
        status,
        customer_id,
        customer_name,
        carrier_id,
        equipment,
        pickup_city,
        pickup_state,
        pickup_zip_code,
        delivery_city,
        delivery_state,
        delivery_zip_code,
        pickup_open_at,
        pickup_close_at,
        pickup_arrived_at,
        pickup_departed_at,
        delivery_open_at,
        delivery_close_at,
        delivery_arrived_at,
        delivery_departed_at,
        distance_miles,
        weight_lbs,
        commodity,
        customer_rate_usd,
        carrier_rate_usd,
        created_at,
        updated_at,
        raw,
    ) = row
    return LoadVersion(
        broker_id=broker_id,
        source_file=source_file,
        synced_at=synced_at,
        raw_load_id=raw_load_id,
        status=LoadStatus(status),
        customer_id=customer_id,
        customer_name=customer_name,
        carrier_id=carrier_id,
        equipment=Equipment(equipment),
        pickup=Location(pickup_city, pickup_state, pickup_zip_code),
        delivery=Location(delivery_city, delivery_state, delivery_zip_code),
        pickup_open_at=pickup_open_at,
        pickup_close_at=pickup_close_at,
        pickup_arrived_at=pickup_arrived_at,
        pickup_departed_at=pickup_departed_at,
        delivery_open_at=delivery_open_at,
        delivery_close_at=delivery_close_at,
        delivery_arrived_at=delivery_arrived_at,
        delivery_departed_at=delivery_departed_at,
        distance_miles=float(distance_miles),
        weight_lbs=float(weight_lbs) if weight_lbs is not None else None,
        commodity=commodity,
        customer_rate_usd=float(customer_rate_usd) if customer_rate_usd is not None else None,
        carrier_rate_usd=float(carrier_rate_usd) if carrier_rate_usd is not None else None,
        created_at=created_at,
        updated_at=updated_at,
        raw=raw,
    )
