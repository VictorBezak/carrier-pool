# Carrier Pool

Ranked carrier recommendations and price estimates for freight brokers, derived only from each broker's own TMS history.

The original task prompt is in [PROJECT_BRIEF.md](PROJECT_BRIEF.md), some of the work-in-progress thoughts in [WIP_NOTES.md](WIP_NOTES.md), a [DECISIONS_AGENT.md](DECISIONS_AGENT.md) to document some of our overarching decisions & trade-offs, a [DECISIONS_OPERATOR.md](DECISIONS_OPERATOR.md) to give a less technical & comprehensive but more personalized and candid take on our decisions and tradeoffs, and a [Q&A.md](Q&A.md) doc to aid in live-demo discussion.

## Run it

```bash
./scripts/verify.sh
```

Builds the stack, waits for `/health`, opts two brokers into the shared pool, and asserts the day-11 answer over the API: Ibrahim Transport ranks first with high confidence.

- UI — <http://localhost:3000>
- API — <http://localhost:8000/api/brokers>

Postgres holds an append-only sync log, the backend ingests one sync file at a time in chronological order, and nginx serves the React build.

## App Experience

The UI is scoped to a single broker, the way a real tenant would see it.

- **Load board** — that broker's book. Every `ACTIVE` load shows its expected carrier cost and who to call first.
- **A load** — the price estimate and its range, every carrier ranked with a contribution bar, the selected carrier's score breakdown and lane map, the past loads behind the price, and the sync-by-sync trail with corrections highlighted. Shared-pool carriers rank in the same table, labelled by source.
- **Dev tools**, top right — what a broker would not have in production: switch tenants to check that each answers only from its own data, replay the board as of an earlier sync, and toggle the pool opt-in alongside the exact list of fields that cross the boundary.

## Local development

Backend without Postgres:

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e .
pytest -q
CARRIER_POOL_FILE_MODE=1 uvicorn carrier_pool.api.app:app --reload
```

Frontend, which proxies `/api` and `/health` to port 8000:

```bash
cd frontend && npm install && npm run dev
```

Stack by hand:

```bash
docker compose up --build
docker compose down -v   # also drops the Postgres volume
```

Regenerating `data/` with `python -m tools.datagen.generate` needs a `docker compose down -v` first. Ingestion keys its watermark on the sync filename and treats a file it has already seen as immutable history.
