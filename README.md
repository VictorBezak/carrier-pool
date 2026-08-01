# Take-Home: Carrier Recommendation for Freight Brokers

- You may use AI coding tools (Claude Code, Codex, Cursor, etc) are strongly encouraged.
- With AI tools and the provided skeleton, a working baseline is roughly a **4-hour job — that's the floor, not the goal**. Strong submissions typically take one to two focused days on top.
- **Cutting scope deliberately is a valid strategy, not a failure** — a smaller thing done deeply beats a big thing done shallow. Say what you cut and why in `DECISIONS.md`.
- We want to see how you think, how deep you go, and which problems you notice on your own.
- In the review call you'll walk us through your decisions and defend them.

## The world

A **freight broker** is a middleman:

- **Customers (shippers)** — companies that have goods to move.
- **Carriers** — trucking companies that move the goods.
- The customer pays the broker one amount (**customer rate**). The broker (ideally) pays the carrier a smaller amount (**carrier rate**). The broker keeps the difference (**margin**).

Each shipment is called a **load**: a pickup place, a delivery place, the truck type needed (dry van, refrigerated, flatbed, etc.), dates, and weight.

A load goes through statuses as it moves through real life:

| Status | Plain meaning |
|---|---|
| `PLANNED` | The customer asked the broker to move this load; nothing has happened yet |
| `ACTIVE` | The broker is now searching for a carrier to take it |
| `COVERED` | A carrier said yes and is booked; the price the broker will pay them is now fixed |
| `IN_TRANSIT` | The truck is on the road |
| `DELIVERED` | The goods arrived |
| `COMPLETED` | All paperwork is done and the final money amounts are confirmed |

Loads can be updated or corrected at any point — freight data is messy.

Two more concepts:

- A **lane** is a from→to pair (for example "Dallas area → Houston area"). A carrier that has done many loads on or near a lane is likely a good fit for the next load on it.
- But what counts as "the same lane" is tricky. Think of New York City and Newark, NJ: they are ~10 miles apart, so for a trucker, Chicago → NYC and Chicago → Newark are practically the same lane — yet they have different city names *and* different states, so grouping history by city or by state would treat them as unrelated. Going the other way, "Texas → Texas" as one lane is useless: Dallas → Houston is 240 miles, El Paso → Houston is 750. You will face the same issue at smaller scale inside the Texas Triangle (suburbs of one metro vs another).
- **Deadhead** = empty miles a truck drives to reach a pickup. Carriers hate it. A truck that just delivered close to your new load's pickup is an easy yes.

## The problem

The platform you are building serves **multiple freight brokers**:

- Each broker runs a **different TMS** (Transportation Management System — the software where all their loads, carriers, and customers live). So each broker's data arrives in a different shape.
- Every day, each broker gets new loads (and sometimes new customers and carriers) *and* updates to existing ones.

For a broker's `ACTIVE` load, your platform must answer two questions:

1. **Which of my carriers should I call first, and why?**
2. **What should I expect to pay a carrier for this load?**

Both answers must come from the broker's own historical data. The broker must be able to see *why* — a bare score or price with no explanation is not useful.

**Bonus — the shared carrier pool.** If you have the appetite: let brokers opt in to a shared carrier pool, so a load can also be matched with carriers known by *other* opted-in brokers. Sharing between competitors is sensitive — so if you attempt this, clearly define and indicate what data crosses the broker boundary (and what never does), and design the sharing around that.

## Repository layout (your starting point)

This repo is an empty shell — placeholder Dockerfiles, compose file, and frontend/backend stubs. You fill it in (or restructure it). The only thing that matters out of the box is `data/`.

```
README.md                       # this file
docker-compose.yaml             # empty shell — yours to fill
backend/                        # empty Dockerfile + pyproject.toml stub
frontend/                       # empty Dockerfile + Vite-style stub
data/
  tms_a_freightflow/            # one directory per TMS
    example_sync.jsonc          # commented schema example — READ THIS FIRST
    example_sync_next.jsonc     # the following sync: same load, updated (how changes arrive)
    2026-07-06T06-00_sync.json  # empty placeholder — shows the filename convention
  tms_b_hauldesk/
    example_sync.jsonc
    2026-07-06T06-00_sync.json
  tms_c_brokeros/
    example_sync.jsonc
    2026-07-06T06-00_sync.json
```

The `example_sync.jsonc` files are the schema documentation (comments included). The real sync files you generate are plain `.json`, named `{YYYY-MM-DD}T{HH-MM}_sync.json` (ISO-8601-style, so filenames sort chronologically).

## Constraints (the few we do impose)

**Starting point**

- Assume the data has already been downloaded from each TMS — the raw data sits in the `data/` directories, exactly as the TMS produced it. Don't build or fake the TMS APIs themselves.
- **We provide the 3 fictional TMS schemas** — see `data/tms_a_freightflow/`, `data/tms_b_hauldesk/`, `data/tms_c_brokeros/`. How you get from their raw shapes to answers is yours to design.
- Each TMS is synced **every 6 hours** (00:00, 06:00, 12:00, 18:00). Every sync produces one self-contained file in that TMS's directory, with the sync datetime in the filename. A sync contains **1–3 loads**: everything created or changed since the last sync.

**Data (synthetic — you generate it; AI is good at this, but you own its sanity)**

- Geography: loads move within the **Texas Triangle** (Dallas–Fort Worth, Houston, San Antonio areas). Spread stops across nearby towns and suburbs, not just the three city centers.
- Create the sync files for **10 simulated days** (4 syncs per TMS per day, following the provided schemas and examples). Use AI to write the files, but *direct* it — **design the data like test cases for your own system**, not random noise. Every behavior you want to show off should have data that demonstrates it.
- At minimum, the data must contain these scenarios (how many and when is up to you):
  1. Loads progressing through the **full lifecycle across syncs**, with money amounts appearing as they become known (e.g. the carrier rate gets fixed when a carrier is booked; final amounts confirmed at completion).
  2. **Corrections** — loads whose *already-recorded* amount or detail changes to a new value in a later sync.
  3. **Contrast**: lanes with rich history next to lanes with thin history; carriers with lots of experience next to carriers with almost none.
- **Day 11** brings fresh loads that are still looking for a carrier — the ones your system must answer for, using days 1–10 as history. We should be able to look at your data and trace *why* your system gave each day-11 answer.
- **Ingestion processes one sync file at a time, in chronological order** — like the real scheduled syncs would have. No loading everything in one shot.

**Platform**

- **Multi-tenant**: one broker's data must never leak into or influence another broker's answers — the bonus pool, if you build it, is the single deliberate opt-in exception.
- **Stack**: use whatever you want. We recommend Python/TypeScript backend + TypeScript/React (and Postgres via docker compose) because that's what the shell hints at — but the stubs are optional, not a mandate.
- **Frontend**: any working UI that shows a load list, and per load the price estimate plus the ranked carriers with their reasoning. Correctness and clarity count; visual polish counts for nothing.
- **How to run**: document it. We will run your project ourselves — a short doc (README section or similar) with the command sequence to bring everything up and reproduce your results. An end-to-end check that exercises that path is a plus — we care that you thought about it, not which tool you picked.

## What we're looking for

Not feature count. We read for the problems you noticed and how you resolved them, for example:

- What happens to your analytics when yesterday's load is corrected today? Do you patch the derived numbers, or rebuild them from scratch — and what would break at millions of loads?
- What is a "lane", exactly, when pickups are scattered across suburbs?
- How does a scoring formula stay fair to a carrier with little history?
- Where should a price estimate come from when the exact lane has little data?
- (If you attempt the pool) what exactly is shared, and how do you prove nothing else leaks?

Some of these have no single right answer — your reasoning is the deliverable as much as the code.

Include a short `DECISIONS.md`:

- The judgment calls you made and the alternatives you rejected.
- What you'd do next with more time.
- Honest limitations score better than hidden ones.

---

# How to run this submission

## Quickest path

```bash
docker compose up --build
```

Then open **http://localhost:5173**. The API is on http://localhost:8000, with
interactive docs at http://localhost:8000/docs.

The backend ingests 84 TMS sync files plus 35 platform offer-log files on
startup (about a second) and holds everything in memory, so there is no database
to migrate and no seed step. `data/` is mounted read-only — ingestion never writes
to it.

## Running without Docker

Two terminals.

```bash
# terminal 1 - API on :8000
cd backend
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
# terminal 2 - UI on :5173, proxying /api to :8000
cd frontend
npm install
npm run dev
```

## Reproducing the dataset

The sync files in `data/` are generated, deterministically — re-running produces
byte-identical files.

```bash
python3 data_gen/generate.py     # stdlib only, no dependencies
curl -X POST localhost:8000/api/reingest   # or just restart the backend
```

## The end-to-end check

```bash
cd backend && .venv/bin/python -m pytest -q
```

48 tests over the real data in `data/`. They assert the claims the system makes
about itself rather than exercising code paths: metric units are converted, a
reefer is not read as a dry van, null equipment is not assumed to be a dry van,
replaying the feed is idempotent, corrections are distinguished from progress and
from carrier fall-offs, no naive datetime survives normalisation, the same carrier
has independent history under each broker, one broker's load ID 404s under
another, and every score equals the sum of the components shown to explain it —
for *every* registered engine, not just the default.

A few guard bugs worth naming. `test_hard_gates_do_not_depend_on_the_chosen_engine`
asserts no engine can both rank and exclude the same carrier, because screening used
to live inside one engine and the other would happily recommend a carrier that could
not haul the freight. `test_a_rate_increase_cannot_buy_a_trailer` asserts that trailer
capability caps acceptance, since paying more closes a price gap but never an
equipment one. `test_a_slower_carrier_never_outranks_a_better_one_on_a_losing_load`
pins the fact that dividing value by time inverts once the value is negative. And
`test_repricing_targets_the_carrier_that_can_actually_haul_it` pins the reason the
cover/reprice decision exists: on a losing load, raw expected value favours carriers
*unlikely to accept*, so the decision has to be computed separately from the ranking.
`test_the_published_curve_agrees_with_the_offer_it_explains` guards the rate dial: the
curve the UI lets a broker drag has to be monotone in the rate and peak at the rate the
engine actually recommended, or the interface would be inviting them to "correct" it
toward a worse number.

The most interesting one is `test_estimated_price_floor_recovers_the_hidden_reserve`.
The generator gives each carrier a secret reservation price, never writes it to any
file, and derives both the offer log and the booked rates from it. So the test can
check the estimated price floors against a **known truth** instead of eyeballing
them for plausibility. They currently land within 3.6% on average.

```bash
cd frontend && npm run build   # typecheck + production build
```

## What to look at first

The interface is built as a dispatcher's call sheet rather than a dashboard: one load,
one answer, with the proof one click away behind **Show the work**. `DECISIONS.md`
explains why, and what was traded away to get there.

1. **Open load `127472835`** (Redline / FreightFlow, Dallas–Fort Worth → San Antonio).
   The page answers in the order the decision is actually made: worth covering, then
   who to ring, then what to open at. The phone number is the hero because a phone call
   is what this system produces.
2. **Drag the rate dial.** The curve is expected value across every rate you could
   offer, sampled by the engine itself. Push the rate up and the odds climb toward
   certainty while the value rolls over the peak, and the page tells you what the move
   costs against its own pick. This is the argument for choosing the rate rather than
   predicting it, and it is the fastest way to see that the recommendation is a maximum
   rather than an opinion.
3. **Open *Show the work* → *This call*.** The `From their own record` column is how
   much of each estimate is this carrier versus the population. `PANHANDLE` was late on
   its only load — a raw average would call it a 0% on-time carrier; shrinkage puts it
   near 60% and says the number is mostly prior.
4. **Switch engines under *Show the work* → *Engine*.** `LONE OAK` moves position. It
   has the lowest price floor of any Redline carrier and delivers late half the time; a
   margin-only ranking likes it, expected value does not. The switcher lives in the work
   rather than the main view on purpose: which model ran is a question about the
   product, not a choice a dispatcher should have to make to get an answer.
5. **Open *Ruled out*.** Exclusions carry their gate and reason. Underneath, five hard
   gates — authority, insurance, safety, blocklists, truck availability — are declared
   **unevaluable**, because no feed in this dataset carries them. Nothing here is a
   compliance check.
6. **Open *Stops, offers, audit trail*.** The offers table is the only data on the page
   that comes from no TMS at all. Carriers who already refused a price get recommended
   at a *higher* rate, and the reason says so.
7. **Open load `127473232`** (Dallas–Fort Worth → Austin, flatbed). The answer is not a
   call list: every carrier who could haul it loses money at every rate they would
   accept, so the page leads with the rate to take back to the customer — bills $1,385,
   needs to bill $1,437, ask for $52. Note that the carrier named in the verdict is the
   one shown on the card, which is *not* the top of the expected-value ranking; the two
   differ by design and the reason is in `DECISIONS.md`.
8. **Open load `127474779`** — a completed load where `BLUEBONNET` accepted and then
   walked away. The audit trail shows it as *carrier fell off*, reconstructed from a
   status moving backwards, because no feed reports the event.
9. **Switch to Summit Freight Solutions** and open its Houston → Austin load, shown as
   `SHP6743131`. Its TMS never recorded an equipment type, so the trailer gate is
   skipped and the response says why rather than assuming a dry van. (BrokerOS keys
   loads by an opaque ID, so this one's URL is not its reference number — find it from
   the list.)

## Where things live

```
data_gen/generate.py            designed, deterministic generator for feeds + offer log
data/tms_*/                     sync files, exactly as each TMS produced them
data/platform_activity/         the platform's own offer log - NOT from any TMS
backend/app/adapters/           one file per TMS; all schema quirks stop here
backend/app/geo.py              ZIP -> metro market; the definition of a "lane"
backend/app/store.py            upsert-by-identity, diffing, change classification
backend/app/history.py          the single-broker view an engine is allowed to see
backend/app/stats.py            empirical-Bayes shrinkage and prior hierarchies
backend/app/ranking/
  contracts.py                  the shape every engine answers in
  eligibility.py                Stage A: hard gates, and the gates we cannot close
  candidates.py                 Stage B: recall-oriented candidate generation
  components.py                 Stage C: acceptance curve, on-time, fall-off, reply time
  costs.py                      what each bad outcome is worth, in dollars
  expected_value.py             Stage D: utility, offer-rate search, ranking
  heuristic.py                  the v1 weighted engine, kept as a control
  pricing.py                    lane price estimation, shared by both engines
frontend/src/tokens.css         palette, type and spacing; the whole visual direction
frontend/src/components/
  Verdict.tsx                   cover or reprice, decided before who to call
  CallCard.tsx                  the one answer, plus the bench of fallbacks
  RateDial.tsx                  the engine's acceptance curve, as a lever
  ShowTheWork.tsx               all the evidence, behind one entry point
frontend/design-shots.mjs       screenshot harness for design review (not shipped)
```

Why the offer log is a separate data source, and why that is the point rather than
a shortcut: see `data/platform_activity/README.md`. The reasoning behind the whole
staged design is in `DECISIONS.md`.
