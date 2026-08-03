from __future__ import annotations

import os
from pathlib import Path

import pytest

from carrier_pool.geo import GeoIndex
from carrier_pool.ingest import ingest_data
from carrier_pool.models import LoadStatus
from carrier_pool.pricing import estimate_price
from carrier_pool.ranking import active_loads, rank_carriers

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


@pytest.mark.skipif(not os.environ.get("CARRIER_POOL_DB_TEST_URL"), reason="requires a throwaway Postgres URL")
def test_db_store_matches_file_store_for_active_recommendations():
    from carrier_pool.db import connect, init_db
    from carrier_pool.repository import store_from_db
    from carrier_pool.sync import iter_sync_files, sync_data

    with connect(os.environ["CARRIER_POOL_DB_TEST_URL"]) as conn:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute("truncate hauldesk_rate, load_version, sync_file, carrier, customer restart identity cascade")
        conn.commit()
        init_db(conn)
        # Every sync file on disk must be ingested exactly once, so the expectation is
        # derived from the data rather than pinned to a number that drifts when it changes.
        assert sync_data(conn, DATA_DIR) == len(list(iter_sync_files(DATA_DIR)))
        db_store = store_from_db(conn)

    file_store = ingest_data(DATA_DIR)
    geo = GeoIndex.bundled()
    for file_load in active_loads(file_store):
        db_load = next(load for load in active_loads(db_store, file_load.broker_id) if load.raw_load_id == file_load.raw_load_id)
        assert estimate_price(db_store, db_load, geo) == estimate_price(file_store, file_load, geo)
        assert [(r.carrier_id, r.score, r.confidence) for r in rank_carriers(db_store, db_load, geo)] == [
            (r.carrier_id, r.score, r.confidence) for r in rank_carriers(file_store, file_load, geo)
        ]


@pytest.mark.skipif(not os.environ.get("CARRIER_POOL_DB_TEST_URL"), reason="requires a throwaway Postgres URL")
def test_broker_counts_describe_current_versions_not_every_version():
    """A load that was ACTIVE in an earlier sync must not still count as awaiting coverage."""
    from carrier_pool.db import connect, init_db
    from carrier_pool.repository import brokers
    from carrier_pool.sync import sync_data

    with connect(os.environ["CARRIER_POOL_DB_TEST_URL"]) as conn:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute("truncate hauldesk_rate, load_version, sync_file, carrier, customer restart identity cascade")
        conn.commit()
        init_db(conn)
        sync_data(conn, DATA_DIR)
        rows = {row["broker_id"]: row for row in brokers(conn)}

    file_store = ingest_data(DATA_DIR)
    for broker_id, row in rows.items():
        current = file_store.broker_current_loads(broker_id)
        assert row["load_count"] == len(current)
        assert row["active_count"] == sum(load.status == LoadStatus.ACTIVE for load in current)
        # The data has loads that progressed past ACTIVE, so the buggy "any version was
        # active" count would have been strictly larger here.
        assert row["active_count"] < row["load_count"]
