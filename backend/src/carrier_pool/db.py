from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DATABASE_URL = "postgresql://carrier_pool:carrier_pool@localhost:5432/carrier_pool"
BROKER_NAMES = {
    "tms_a_freightflow": "FreightFlow Brokerage",
    "tms_b_hauldesk": "HaulDesk Logistics",
    "tms_c_brokeros": "BrokerOS Freight",
}


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def schema_sql() -> str:
    return Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


@contextmanager
def connect(url: str | None = None) -> Iterator:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised in Docker, not the local venv.
        raise RuntimeError("psycopg is required for database access; install backend dependencies or use Docker") from exc

    with psycopg.connect(url or database_url()) as conn:
        yield conn


def init_db(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(schema_sql())
        for broker_id, name in BROKER_NAMES.items():
            cur.execute(
                """
                insert into broker (broker_id, name)
                values (%s, %s)
                on conflict (broker_id) do update set name = excluded.name
                """,
                (broker_id, name),
            )
    conn.commit()
