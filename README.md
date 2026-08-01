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
