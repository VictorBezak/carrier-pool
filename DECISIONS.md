# Decisions

## What this iteration is

The platform end to end — ingestion, normalisation, tenancy, API, UI — with a
**deliberately simple ranking algorithm**. The scoring is a transparent weighted
sum and the price is a median of comparables. That is a placeholder, and it is
meant to be replaced.

The reason for building it in this order is that the interesting risk in this
problem is not the formula. It is everything around it: three incompatible
schemas, amounts that change after the fact, what a "lane" even is, and keeping
three brokers' data apart. Those constraints shape the interfaces the algorithm
has to live inside, so they were worth settling first. The scoring engine sits
behind one interface (`RecommendationEngine`) with one registration point
(`ENGINES` in `backend/app/ranking.py`), so replacing it does not touch
ingestion, the API or the frontend.

## The judgment calls

### A lane is a metro market pair, resolved from ZIP prefix

City names are too fine and states are far too coarse, exactly as the brief
says. So history is grouped by *metro market*, and a stop's market is resolved
from its ZIP prefix rather than its city name.

ZIP is the resolver because ZIP prefixes already encode geography, which is what
fixes the NYC/Newark case: `07xxx` and `100xx` can be assigned to one metro
despite disagreeing on both city *and* state. Grouping by city name could never
do that, and grouping by state gets Dallas→Houston and El Paso→Houston confused.

**Rejected:** clustering stops by lat/long distance. It is the better answer and
it is what I would build next, because it handles the "is this suburb its own
market" question continuously instead of by fiat. It needs a geocoder and a
decision about cluster radius, and it would have consumed the time this
iteration spent on the data pipeline.

**Limitation, stated plainly:** the market table is hardcoded ZIP3 ranges for
the Texas Triangle plus a city-name fallback for records that carry no ZIP
(carrier home bases). It is the right *shape* at the wrong *resolution*. It also
treats Austin and San Antonio as separate markets while treating all of
Dallas–Fort Worth as one, which is defensible but arbitrary — DFW is 9,000
square miles.

### Nothing derived is stored, so corrections need no repair

This is the answer to "what happens to your analytics when yesterday's load is
corrected today".

Loads are **upserted by identity**. A sync file carries the whole load object
again, so the newest sync is simply the truth, and re-running a file changes
nothing. Lane statistics, carrier scores and price estimates are **computed at
read time** from current load state. A correction that lands on day 6 for a
day 2 load is therefore reflected immediately, with no aggregate to patch and no
chance of a stale number surviving somewhere.

`test_replay_is_idempotent` asserts that replaying the whole feed produces
byte-identical state, which is what makes "rebuild from scratch" a legitimate
recovery strategy rather than a hope.

**What would break at millions of loads:** all of it. Recomputing every lane
median per request is fine at 35 loads and absurd at 35 million. The real design
is incremental aggregates keyed by (broker, lane, equipment, time bucket),
updated by applying a delta when a load changes — which means storing the
*previous* contribution of each load so it can be subtracted, and accepting that
a correction now mutates derived state and needs an audit trail. That is a much
bigger system, and its correctness argument is much weaker. I would keep
recompute-on-read as the reference implementation and test the incremental path
against it.

### Corrections are classified, not just detected

The store diffs every load against its previous version and records what
changed. The `kind` matters more than the diff:

- `REVEALED` — an amount went from null to a number. The carrier rate becoming
  known at booking is *not* a correction, and treating it as one would cry wolf
  on every load.
- `CORRECTION` — a real value was replaced by a different real value. Somebody
  restated history.
- `PROGRESS` — status moved forward. A status moving *backwards* is classified as
  a correction, because freight does not un-deliver.
- `DETAIL` — everything else.

The UI shows this per load ("How this load arrived") including which sync file
each change came from, so a surprising number can be traced to the file that
caused it.

### Money is modelled per TMS, because each one lies differently

- **FreightFlow** restates `totalBuy` in place. Easy.
- **HaulDesk** has no rate field at all: money is an append-only ledger of line
  items, and a correction arrives as a *new negative row*. The adapter
  accumulates rows across syncs keyed by `rate_id`, so re-reading a file cannot
  double-count. Crucially, a load with no `pay` rows has a carrier rate of
  `None`, not `0` — "not yet priced" and "priced at zero" are different facts and
  conflating them would drag every median down.
- **BrokerOS** simply changes `bos__Carrier_Rate__c` to a different number with
  no marker. Nothing but a diff against the previous version can detect it.

### Where a price comes from when the lane is thin

The estimator walks comparable sets from narrowest to widest and stops at the
first one with at least 3 priced loads:

1. same lane, same trailer type
2. same lane, any trailer
3. same pickup market, same trailer
4. same pickup market
5. everything this broker has priced

It then **says which level it used**, in the UI, in plain words ("Fewer than 3
priced loads exist on this lane, same trailer type, so the comparison was
widened to loads out of this pickup market"). If nothing reaches 3 it still
answers, using the narrowest non-empty set, and marks itself low confidence.
Refusing to answer is worse than answering with a stated caveat.

Two details that matter: a load is never a comparable for itself, and when a
load has **no** equipment type recorded, the trailer-qualified levels are
skipped entirely rather than allowed to silently match everything. Otherwise the
estimate would claim its comparables were "the same trailer type" when no
trailer type was ever known. (This was a real bug during development, caught by
`test_price_basis_never_overstates_the_match`.)

The band is a quartile spread where there are at least 4 comparables and a plain
min/max where there are 2–3, because quartiles of three numbers are theatre.

### Fairness to carriers with thin history: flagged, not solved

The v1 scorer has a `relationship_depth` component, so a carrier with one
excellent load structurally cannot out-score a carrier with five mediocre ones.
**That is a real bias and this iteration does not fix it.**

What it does instead is refuse to hide it. Every recommendation carries a
`history_depth` with an `is_thin` flag and a human label ("Thin history: only one
booked load ever"), which the UI renders on the card. A dispatcher sees a low
score *and* the reason the evidence is weak, rather than a low score that looks
like a judgement about quality.

The principled fix is shrinkage: score toward the lane's prior when a carrier's
sample is small, so thin history pulls a carrier toward average rather than
toward the bottom, and add a confidence interval per carrier instead of a point
score. That is what I would do next, and it is a change entirely inside
`ranking.py`.

### Tenancy is structural, not a filter

One broker per TMS directory. The tenant is:

- part of every API path (`/api/brokers/{broker_id}/...`), never an optional
  query parameter somebody could forget;
- the constructor argument to `BrokerHistory`, which is the **only** thing the
  ranking engine is given — an engine has no reference to the store and
  physically cannot reach another tenant's loads;
- part of the load's primary key, so `/api/brokers/anchor/loads/{a redline ref}`
  is a 404 rather than a leak.

The dataset makes this testable rather than assertable: IBRAHIM TRANSPORT works
for two brokers under the same MC number, with three loads under one and one
under the other. `test_same_carrier_has_independent_history_per_broker` fails if
those views ever converge.

## What I cut, and why

- **Postgres.** The compose file has no database. Ingestion order, idempotency
  and correction handling are the parts of persistence that carry actual risk,
  and all three are exercised by replaying files into an in-memory store behind
  a narrow `Store` interface. Adding Postgres would have bought a schema
  migration and no new insight this iteration. The cost is real: nothing
  survives a restart, and the read-time recompute strategy above only looks
  reasonable because the dataset is small.
- **The shared carrier pool.** Not attempted. But the seam is deliberate:
  `BrokerHistory` is the only surface the ranking engine sees, so a pooled view
  is a second implementation of that one interface with an explicit list of what
  it exposes. MC/DOT numbers are carried through all three adapters precisely
  because cross-broker carrier identity is the thing a pool would be built on.
- **7 days of data instead of 10 + day 11.** Days 1–6 are history and day 7 is
  the answer set. Day count is a constant in the generator; the shape of the
  dataset is what took the thought, not its length.
- **Carrier quality signals.** Nothing models whether a carrier was cheap, late,
  or a problem. The scorer rewards presence, not performance. Real on-time data
  would need actual-vs-scheduled comparison per stop, which the data supports but
  the scorer ignores.

## Known limitations

- **The deadhead signal uses a carrier's most recent delivery market**, which is
  a proxy that goes stale fast. A truck that delivered into Houston four days ago
  is not in Houston now. Real repositioning needs current truck location or at
  least a decay window.
- **Lane matching is binary.** Neighbouring markets contribute nothing, so a
  Dallas→Austin veteran gets no credit for a Dallas→Georgetown load beyond the
  shared origin — even though Georgetown is 30 miles from Austin. This is the
  same limitation as the market table, seen from the scoring side.
- **HaulDesk timestamps are naive local time** and are read as US Central. Every
  timestamp in this dataset is in CDT so it is correct here, and it would be
  wrong across a DST boundary. `tzdata` is installed in the image so `zoneinfo`
  resolves properly rather than falling back to a fixed offset.
- **Weights are hand-picked.** 0.40 for lane experience is a guess that sounds
  reasonable, not a fitted parameter. With outcome data — did the called carrier
  accept, at what rate — these should be learned, and the honest version of this
  system logs recommendations and their outcomes from day one so that data
  exists later.
- **Score is presented as a 0–100 number**, which invites more trust than a
  hand-weighted heuristic deserves. The component breakdown is there to
  counteract that, but a rank plus a confidence band would be more honest than a
  precise-looking score.
