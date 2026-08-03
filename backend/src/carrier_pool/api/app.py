from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from carrier_pool.api.serializers import carrier_ranking, load_detail, load_summary, pool_ranking, price_estimate
from carrier_pool.db import BROKER_NAMES, connect, init_db
from carrier_pool.geo import GeoIndex
from carrier_pool.ingest import BROKER_BROKEROS, BROKER_FREIGHTFLOW, BROKER_HAULDESK, BROKER_IDS, ingest_data, sync_timestamp
from carrier_pool.models import CanonicalStore, LoadStatus, LoadVersion
from carrier_pool.pool import POOL_POLICY, recommend
from carrier_pool.ranking import _broker_history, active_loads
from carrier_pool.repository import brokers as db_brokers
from carrier_pool.repository import latest_watermark, pool_opt_ins, set_pool_opt_in, store_from_db, syncs as db_syncs

ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))

app = FastAPI(title="Carrier Pool API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.file_pool_opt_ins = set()
app.state.store_cache = None
app.state.watermark_cache = None


class PoolOptInPayload(BaseModel):
    enabled: bool


@app.get("/health")
def health() -> dict[str, Any]:
    store = _store()
    return {"ok": True, "loads": len(store.current_loads), "versions": len(store.versions), "source": "db" if _database_enabled() else "files"}


@app.get("/api/brokers")
def get_brokers() -> list[dict[str, Any]]:
    if _database_enabled():
        with connect() as conn:
            init_db(conn)
            return db_brokers(conn)
    store = _store()
    opt_ins = _pool_opt_ins()
    rows = []
    for broker_id in BROKER_IDS:
        loads = store.broker_current_loads(broker_id)
        rows.append(
            {
                "broker_id": broker_id,
                "name": BROKER_NAMES[broker_id],
                "pool_opt_in": broker_id in opt_ins,
                "load_count": len(loads),
                "active_count": sum(load.status == LoadStatus.ACTIVE for load in loads),
            }
        )
    return rows


@app.get("/api/brokers/{broker_id}/loads")
def get_loads(broker_id: str, as_of: str | None = Query(default=None)) -> list[dict[str, Any]]:
    _validate_broker(broker_id)
    cutoff = _cutoff(as_of)
    loads = _store().loads_as_of(broker_id, cutoff) if cutoff else _store().broker_current_loads(broker_id)
    loads = sorted(loads, key=lambda load: (load.status != LoadStatus.ACTIVE, load.synced_at, load.raw_load_id))
    return [load_summary(load, _store().carriers) for load in loads]


@app.get("/api/brokers/{broker_id}/loads/{load_id}")
def get_load_detail(broker_id: str, load_id: str, as_of: str | None = Query(default=None)) -> dict[str, Any]:
    cutoff = _cutoff(as_of)
    load = _load_as_of_or_404(broker_id, load_id, cutoff)
    return load_detail(load, _versions_for_load(broker_id, load_id, cutoff), _store().carriers)


@app.get("/api/brokers/{broker_id}/loads/{load_id}/recommendation")
def get_recommendation(
    broker_id: str,
    load_id: str,
    as_of: str | None = Query(default=None),
    pool: bool = Query(default=False),
) -> dict[str, Any]:
    cutoff = _cutoff(as_of)
    target = _load_as_of_or_404(broker_id, load_id, cutoff)
    geo = GeoIndex.bundled()
    bundle = recommend(_store(), target, geo, as_of=cutoff or target.synced_at, opt_in_brokers=_pool_opt_ins(), include_pool=pool)
    history = _broker_history(_store(), target, cutoff or target.synced_at)
    return {
        "load": load_summary(target, _store().carriers),
        "price": price_estimate(bundle.price),
        "own_carriers": [carrier_ranking(ranking, target, history, geo) for ranking in bundle.own_carriers],
        "pool_carriers": [pool_ranking(ranking, target, geo) for ranking in bundle.pool_carriers],
    }


@app.get("/api/brokers/{broker_id}/syncs")
def get_syncs(broker_id: str) -> list[dict[str, Any]]:
    _validate_broker(broker_id)
    if _database_enabled():
        with connect() as conn:
            return [_serialize_sync(row) for row in db_syncs(conn, broker_id)]
    rows = []
    for path in sorted((DATA_DIR / broker_id).glob("*_sync.json")):
        rows.append({"broker_id": broker_id, "source_file": f"{broker_id}/{path.name}", "filename": path.name, "synced_at": sync_timestamp(path), "processed_at": None})
    return [_serialize_sync(row) for row in rows]


@app.put("/api/brokers/{broker_id}/pool-opt-in")
def put_pool_opt_in(broker_id: str, payload: PoolOptInPayload) -> dict[str, Any]:
    _validate_broker(broker_id)
    if _database_enabled():
        with connect() as conn:
            set_pool_opt_in(conn, broker_id, payload.enabled)
    else:
        if payload.enabled:
            app.state.file_pool_opt_ins.add(broker_id)
        else:
            app.state.file_pool_opt_ins.discard(broker_id)
    return {"broker_id": broker_id, "pool_opt_in": payload.enabled}


@app.get("/api/pool/policy")
def get_pool_policy() -> dict[str, Any]:
    return POOL_POLICY


def _cutoff(as_of: str | None) -> datetime | None:
    """Parse the as-of replay cutoff, rejecting a bad value instead of raising a 500.

    `as_of` is the one query parameter a client composes by hand, and forgetting to
    URL-encode the `+` in a UTC offset turns it into a space. That is the caller's
    mistake, so it should read as one.
    """
    if not as_of:
        return None
    try:
        return datetime.fromisoformat(as_of)
    except ValueError as cause:
        raise HTTPException(status_code=400, detail=f"Invalid as_of timestamp {as_of!r}; expected an ISO-8601 datetime") from cause


def _database_enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL")) and os.environ.get("CARRIER_POOL_FILE_MODE") != "1"


def _store() -> CanonicalStore:
    if not _database_enabled():
        if app.state.store_cache is None:
            app.state.store_cache = ingest_data(DATA_DIR)
        return app.state.store_cache
    with connect() as conn:
        init_db(conn)
        watermark = latest_watermark(conn)
        if app.state.store_cache is None or app.state.watermark_cache != watermark:
            app.state.store_cache = store_from_db(conn)
            app.state.watermark_cache = watermark
        return app.state.store_cache


def _pool_opt_ins() -> set[str]:
    if _database_enabled():
        with connect() as conn:
            return pool_opt_ins(conn)
    return set(app.state.file_pool_opt_ins)


def _validate_broker(broker_id: str) -> None:
    if broker_id not in BROKER_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown broker {broker_id!r}")


def _current_load_or_404(broker_id: str, load_id: str) -> LoadVersion:
    _validate_broker(broker_id)
    load = _store().current_loads.get((broker_id, load_id))
    if load is None:
        raise HTTPException(status_code=404, detail=f"Unknown load {load_id!r}")
    return load


def _load_as_of_or_404(broker_id: str, load_id: str, cutoff: datetime | None) -> LoadVersion:
    if cutoff is None:
        return _current_load_or_404(broker_id, load_id)
    _validate_broker(broker_id)
    matches = [load for load in _store().loads_as_of(broker_id, cutoff) if load.raw_load_id == load_id]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Load {load_id!r} was not known at {cutoff.isoformat()}")
    return matches[0]


def _versions_for_load(broker_id: str, load_id: str, cutoff: datetime | None = None) -> list[LoadVersion]:
    return [
        version
        for version in _store().versions
        if version.broker_id == broker_id and version.raw_load_id == load_id and (cutoff is None or version.synced_at <= cutoff)
    ]


def _serialize_sync(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "broker_id": row["broker_id"],
        "source_file": row["source_file"],
        "filename": row["filename"],
        "synced_at": row["synced_at"].isoformat(),
        "processed_at": row["processed_at"].isoformat() if row.get("processed_at") else None,
    }
