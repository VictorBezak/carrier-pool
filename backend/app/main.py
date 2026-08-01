"""HTTP surface.

Every load-facing route is nested under `/api/brokers/{broker_id}`, so the
tenant is part of the path rather than an optional query parameter that could be
forgotten. Handlers resolve a `BrokerHistory` scoped to that id and pass only
that to the ranking engine.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import brokers, config, ingest, ranking
from .domain import Broker, LoadStatus, SyncFileRecord
from .history import BrokerHistory
from .ranking import EngineInfo, Recommendations
from .schemas import BrokerSummary, CarrierSummary, LaneSummary, LoadDetail, LoadSummary
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("carrier_pool")

STATE: dict[str, Store] = {}


def load_store() -> Store:
    """Replay the whole feed. Cheap enough at this size that reingest is just
    'do it again', which is also the honest answer to corrections: rebuild."""
    data_dir = config.data_dir()
    log.info("ingesting sync files from %s", data_dir)
    store = ingest.ingest_all(data_dir)
    log.info(
        "ready: %d sync files, %d loads",
        len(store.sync_files()),
        sum(len(store.loads(broker.broker_id)) for broker in brokers.BROKERS),
    )
    return store


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE["store"] = load_store()
    yield
    STATE.clear()


app = FastAPI(
    title="Carrier Pool",
    version="0.1.0",
    description="Carrier recommendations and price estimates from a broker's own history.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_store() -> Store:
    store = STATE.get("store")
    if store is None:  # pragma: no cover - only if a request beats startup
        raise HTTPException(status_code=503, detail="Store is still warming up")
    return store


def get_broker(broker_id: str) -> Broker:
    broker = brokers.get(broker_id)
    if broker is None:
        raise HTTPException(status_code=404, detail=f"Unknown broker {broker_id!r}")
    return broker


def get_history(
    broker: Broker = Depends(get_broker), store: Store = Depends(get_store)
) -> BrokerHistory:
    return BrokerHistory(store, broker.broker_id)


# --------------------------------------------------------------------------


class Health(BaseModel):
    status: str
    sync_files: int
    loads: int
    last_synced_at: datetime | None


@app.get("/api/health", response_model=Health, tags=["meta"])
def health(store: Store = Depends(get_store)) -> Health:
    return Health(
        status="ok",
        sync_files=len(store.sync_files()),
        loads=sum(len(store.loads(broker.broker_id)) for broker in brokers.BROKERS),
        last_synced_at=store.last_synced_at,
    )


@app.get("/api/engines", response_model=list[EngineInfo], tags=["meta"])
def engines() -> list[EngineInfo]:
    return [engine.info for engine in ranking.ENGINES.values()]


@app.post("/api/reingest", response_model=Health, tags=["meta"])
def reingest() -> Health:
    """Rebuild from the sync files. Used after regenerating data."""
    STATE["store"] = load_store()
    return health(STATE["store"])


@app.get("/api/brokers", response_model=list[BrokerSummary], tags=["brokers"])
def list_brokers(store: Store = Depends(get_store)) -> list[BrokerSummary]:
    summaries = []
    for broker in brokers.BROKERS:
        loads = store.loads(broker.broker_id)
        sync_files = store.sync_files(broker.broker_id)
        summaries.append(
            BrokerSummary(
                broker_id=broker.broker_id,
                name=broker.name,
                tms_label=broker.tms_label,
                tms_style=broker.tms_style,
                load_count=len(loads),
                active_load_count=sum(1 for load in loads if load.status == LoadStatus.ACTIVE),
                carrier_count=len(store.carriers(broker.broker_id)),
                sync_file_count=len(sync_files),
                last_synced_at=max((record.synced_at for record in sync_files), default=None),
            )
        )
    return summaries


@app.get("/api/brokers/{broker_id}/loads", response_model=list[LoadSummary], tags=["loads"])
def list_loads(
    status: LoadStatus | None = None,
    q: str | None = None,
    store: Store = Depends(get_store),
    broker: Broker = Depends(get_broker),
) -> list[LoadSummary]:
    loads = store.loads(broker.broker_id)
    if status is not None:
        loads = [load for load in loads if load.status == status]
    if q:
        needle = q.strip().lower()
        loads = [
            load
            for load in loads
            if needle in load.reference.lower()
            or needle in (load.customer_name or "").lower()
            or needle in (load.carrier_name or "").lower()
            or needle in load.lane_label.lower()
            or any(needle in stop.city.lower() for stop in load.stops)
        ]

    corrections: dict[str, int] = {}
    for change in store.changes(broker.broker_id):
        if change.kind == "CORRECTION":
            corrections[change.load_id] = corrections.get(change.load_id, 0) + 1

    summaries = [LoadSummary.of(load, corrections.get(load.load_id, 0)) for load in loads]
    # Loads that need action first, then the most recently touched.
    summaries.sort(
        key=lambda item: (
            item.status != LoadStatus.ACTIVE,
            -(item.updated_at.timestamp() if item.updated_at else 0),
        )
    )
    return summaries


@app.get("/api/brokers/{broker_id}/loads/{source_ref}", response_model=LoadDetail, tags=["loads"])
def get_load(
    source_ref: str,
    store: Store = Depends(get_store),
    broker: Broker = Depends(get_broker),
) -> LoadDetail:
    load_id = f"{broker.broker_id}:{source_ref}"
    load = store.load(broker.broker_id, load_id)
    if load is None:
        raise HTTPException(status_code=404, detail=f"Unknown load {source_ref!r} for {broker.broker_id}")
    changes = sorted(
        store.changes_for_load(broker.broker_id, load_id), key=lambda change: change.observed_at
    )
    offers = store.offers_for_load(broker.broker_id, load_id)
    return LoadDetail.of_load(load, changes, offers)


@app.get(
    "/api/brokers/{broker_id}/loads/{source_ref}/recommendations",
    response_model=Recommendations,
    tags=["recommendations"],
)
def recommend(
    source_ref: str,
    engine: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    store: Store = Depends(get_store),
    broker: Broker = Depends(get_broker),
    history: BrokerHistory = Depends(get_history),
) -> Recommendations:
    load = store.load(broker.broker_id, f"{broker.broker_id}:{source_ref}")
    if load is None:
        raise HTTPException(status_code=404, detail=f"Unknown load {source_ref!r} for {broker.broker_id}")
    try:
        selected = ranking.get_engine(engine)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown engine {engine!r}") from None
    return selected.recommend(load, history, limit=limit)


@app.get("/api/brokers/{broker_id}/lanes", response_model=list[LaneSummary], tags=["brokers"])
def list_lanes(history: BrokerHistory = Depends(get_history)) -> list[LaneSummary]:
    return [LaneSummary(**summary) for summary in history.lane_summary()]


@app.get("/api/brokers/{broker_id}/carriers", response_model=list[CarrierSummary], tags=["brokers"])
def list_carriers(history: BrokerHistory = Depends(get_history)) -> list[CarrierSummary]:
    summaries = [
        CarrierSummary(
            carrier_id=carrier.carrier_id,
            name=carrier.name,
            mc_number=carrier.mc_number,
            dot_number=carrier.dot_number,
            home_city=carrier.home_city,
            home_state=carrier.home_state,
            phone=carrier.phone,
            loads_total=len(history.carrier_loads(carrier.carrier_id)),
        )
        for carrier in history.carriers
    ]
    summaries.sort(key=lambda item: (-item.loads_total, item.name))
    return summaries


@app.get("/api/brokers/{broker_id}/syncs", response_model=list[SyncFileRecord], tags=["brokers"])
def list_syncs(
    store: Store = Depends(get_store), broker: Broker = Depends(get_broker)
) -> list[SyncFileRecord]:
    return store.sync_files(broker.broker_id)
