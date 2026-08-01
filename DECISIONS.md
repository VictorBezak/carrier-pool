# Decisions

> This version of DECISIONS.md was generated entirely by our coding agent

## What this iteration is

The platform end to end — ingestion, normalisation, tenancy, API, UI — plus **two
ranking engines behind one contract**:

- `simple-heuristic`: a transparent weighted sum of history signals. Ordinal, no
  units, needs no data beyond the TMS feeds.
- `expected-value`: a staged pipeline — hard eligibility gates, candidate
  generation, per-outcome predictions shrunk toward contextual priors, combined
  into expected margin per hour of broker time, with the offered rate chosen as
  part of the decision.

Both are exposed at once, switchable in the UI and via `?engine=`, on identical
data. Keeping the simple one after building the better one is deliberate: it is
the control that makes "this is an improvement" checkable rather than asserted,
and it still answers for a tenant whose offer log is empty.

The build order was pipeline first, algorithm second. The interesting risk in this
problem is not the formula — it is three incompatible schemas, amounts that change
after the fact, what a "lane" even is, and keeping three brokers' data apart.
Those constraints shape the interfaces the algorithm has to live inside.

## The central reframing

The recommendation does not answer *"how good is this carrier?"* It answers:

> Given this load, what is the economic value of calling this carrier next, and
> what should we offer them?

Three consequences fall out of taking that literally.

### Price and acceptance are one surface, not two predictions

The obvious decomposition has an "expected carrier rate" model and an "acceptance
probability" model. That loses the only variable the broker actually controls.
What a carrier costs is not a property of the carrier — it is the outcome of a
negotiation whose input is the number you say first.

So the engine estimates a **reservation price** per carrier and models acceptance
as a function of the rate offered:

```
P(accept | carrier, load, offered_rate) = logistic((offered − floor) / width)
```

The rate is then a **decision variable**: the engine searches it and keeps the
value that maximises expected value. That is what makes the output actionable —
"offer $1,250, 81% likely to land, $1,340 would make it 90%" is a sentence a
dispatcher can use, where "expected rate: $1,205" is not.

`width` grows with the uncertainty in the floor, so a carrier we know little about
gets a flatter curve rather than a confident guess in the wrong place.

**Why a structural model instead of logistic regression.** With five to nine
offers per carrier, a fitted logistic is noise with standard errors. A
reservation-price model uses the shape of the actual mechanism, degrades into a
population average rather than into garbage, and produces a parameter — "we think
their floor is $1,178 ± $64" — that a broker can disagree with specifically.

### Ranking is by value per hour, not by value

If a dispatcher works down a list making calls, the value of a call includes the
option to call the next person when it fails. A carrier that answers in twenty
minutes resolves the load sooner than one that takes three hours, and time to
cover is a real cost.

Ranking purely by expected value systematically over-prefers the safe, cheap, slow
carrier in exactly the workflow that is most common. So the score is expected value
divided by expected hours to resolve, and the time adjustment is a visible line in
the breakdown rather than a hidden normalisation.

This is a partial answer. The full version is an optimal-search problem — the
value of calling someone depends on the whole remaining sequence, not just their
own resolution time. Value-per-hour is a defensible one-step approximation of it.

### Optimism under uncertainty, not pessimism

The standard move is to rank by `E[U] − λσ`, penalising uncertain predictions. That
is correct when the downside of being wrong is a committed load. It is wrong when
the downside is a wasted phone call — and it creates a feedback loop where
unfamiliar carriers never get called, so they stay unfamiliar forever.

A call is cheap and it *produces the data that resolves the uncertainty*. So the
sign follows the workflow: for a human calling down a list the engine credits part
of the upside (`+λσ`, default 35%), and for automatic tendering it should subtract
it. Exploration stops being a bolted-on 5% quota and becomes a property of the
objective.

The UI reflects this: expected value renders as a *range*, and a wide range on a
thin-history carrier is presented as a reason to call them.

## The data problem that had to be solved first

**No TMS in this dataset records a tender, an offer, a refusal, a counter, or a
response time.** They record the carrier that ended up on the load.

That makes acceptance unidentifiable from TMS data — not sparse, *absent*. There is
no negative class, and the rate that was refused is never written down, so even the
positive examples are missing their most important feature.

So the platform keeps its own log, in `data/platform_activity/`, deliberately
separate from the feeds. The fact that it *has* to be separate is the design
finding, and it is why decision logging is a prerequisite rather than an
enhancement: it is the mechanism by which the training data for every learned
component comes into existence at all.

Two other signals were missing and were added to the generator, because a model
that consumes a constant feature looks like it works while doing nothing:

- **Service failures.** Earlier every load hit its appointment — zero variance, so
  a reliability term would have been decorative. Now specific carriers run late,
  and lateness crosses the *appointment day* rather than the hour, because BrokerOS
  records scheduled dates with no time of day and same-day lateness would be
  invisible in one of the three feeds.
- **Carrier fall-offs.** A carrier accepts and walks away. No feed reports this;
  the only evidence is a status moving backwards out of `COVERED` and the carrier
  field changing. The store previously classified that as a data correction, which
  meant a genuine business event with a real cost was indistinguishable from a
  typo.

Carrier reservation prices and reply times are **latent** in the generator — never
written to any file — and the booked rates in the TMS feeds are derived from them.
That keeps the feeds and the offer log from contradicting each other, and it means
the estimated floors can be validated against a known truth rather than merely
inspected for plausibility. `test_estimated_price_floor_recovers_the_hidden_reserve`
holds them to a mean error under 10%; they currently land at 3.6%.

## Shrinkage, and the fairness problem it actually fixes

The previous iteration flagged incumbency bias and did not fix it. This one does.

Every component estimate is empirical-Bayes shrunk toward a prior drawn from the
most specific context that has enough data to be worth trusting. The prior
hierarchy for a price floor is: accepted offers on this equipment type → accepted
offers across this broker's carriers → a global default. For on-time it is the
broker's own overall rate, because at this data volume there are not enough
observed outcomes per lane for a lane-level prior to beat it, and adding a rung
that cannot support weight is worse than not having it.

The concrete case the dataset was built to test: PANHANDLE delivered its single
load late. A raw average calls that a **0% on-time carrier**. Shrinkage puts it at
roughly 60% and reports that the estimate is mostly prior. Meanwhile IBRAHIM,
clean across several loads, still beats LONE OAK, late on two of three — so the
shrinkage is not flattening everyone into the average.

Two properties are reported alongside every estimate rather than hidden:

- `prior_share` — how much of this number is the population rather than this
  carrier. "97% on-time" and "97% on-time, of which 80% is just the average
  carrier" are very different claims, and the UI shows the difference in a column.
- `uncertainty` — which is what lets the ranking layer be optimistic on purpose.

Excluding the carrier being estimated from its own prior matters: otherwise its
record leaks into its own prior and the shrinkage quietly stops doing anything.

## Business costs are named, in one file

`ranking/costs.py` holds the dollar value of each bad outcome: a late delivery at
$275, a fall-off at $425, broker time at $42/hour. They are business inputs, not
model outputs, and they live together because they are the part a broker should
argue with.

This is the real reason expected value beats a weighted score. A weight of 0.15 on
"reliability" is unfalsifiable. Saying a late delivery costs $275 is a claim
someone can check against their own accessorial data and be wrong about in a
specific, fixable way. Changing one requires no retraining and no redeploy of any
estimator.

Claims cost, tracking compliance and operational effort are set to **zero with a
stated reason** rather than guessed at, because no feed carries them. They appear
in the response's `limitations` so the gap is visible in the output instead of
buried in a constant.

## Eligibility is a gate, and some gates cannot be closed

A carrier that cannot take the load is removed with a reason attached, not ranked
last. Exclusions are first-class output: a carrier missing from a list with no
explanation is indistinguishable from a bug, and a dispatcher who cannot find a
carrier they expected stops trusting the whole list.

The enforced gates are trailer type, payload against the trailer's legal capacity,
service area, and whether the truck can physically reach the pickup before the
appointment closes.

The gates that **cannot be evaluated** are declared explicitly and rendered in the
UI: operating authority, insurance, safety and fraud screening, do-not-use
blocklists, and confirmed truck availability. None of them exist in any feed. An
unstated missing gate is how a broker ends up tendering to a carrier whose
insurance lapsed, so the absence is published rather than assumed away.

One gate got this wrong during development and is worth recording. The weight
check originally compared a load against the heaviest load that carrier had
previously hauled, and promptly excluded a perfectly capable dry van carrier
because its recent freight had been light. Every dry van has roughly the same
capacity — booking history says nothing about capability. A gate that fires on a
plausible-sounding proxy is worse than no gate, because it is wrong in a way that
looks authoritative. It now checks the trailer type's payload ceiling, which binds
rarely, and that is the correct behaviour rather than a sign it is useless.

## The trailer "gate" is a probability, because the data cannot support a gate

Equipment ought to be the cleanest hard filter in the system: look up the fleet,
and either there is a reefer or there is not. None of the three feeds records a
fleet. All that is observable is what a carrier has hauled for this broker, and
three dry van loads is *evidence* of no reefer, not proof of one.

So the honest quantity is `P(carrier can pull this trailer)`, and the gate is a
threshold on it rather than a rule of its own. Two things fall out of that.

First, it is a posterior over a latent capability, deliberately **not** the share
of a carrier's loads that used the trailer. A carrier splitting work evenly between
reefer and dry van would score 0.5 on a rate over loads while obviously owning a
reefer. Capability is a yes/no: one load on the trailer settles it, and zero loads
is weak evidence over two loads and strong evidence over twenty. It is weaker again
when the broker rarely offers that trailer type at all — never hauling a flatbed for
a broker that tenders one a month says much less than never hauling a dry van. With
`p` the base rate of owning the trailer among this broker's carriers, `q` the chance
any given load would have used it, and `n` loads none of which did:

```
P(owns | none of n) = p(1-q)^n / [ p(1-q)^n + (1-p) ]
```

The previous version of this gate fired at "three or more loads, none on this
trailer". That is roughly where the probability version lands at this data volume,
but the threshold now adapts to how much a silence is worth instead of asserting a
load count, and it reports the number it acted on.

Second, capability enters the utility as a **multiplier on acceptance**, not as a
score bonus. That is the mechanism it actually acts through: a carrier without a
reefer declines a reefer load at any price. Money buys willingness, never equipment.
Modelling it this way also stops the rate search from trying to pay its way out of a
capability problem, which a score penalty would quietly allow.

The threshold stays conservative in the same direction as before: letting a possibly
unequipped carrier through to be ranked low costs one evaluation, while excluding one
that does own the trailer removes it permanently.

A note on display, since it was the symptom that exposed all of this. The engines say
nothing about equipment for a carrier that has proven the trailer — telling a
dispatcher that the carrier they use for reefer freight every week has a reefer is
noise. Proven capability is treated as exactly certain rather than 0.97-for-safety,
so the gate, the dollar term and the explanation all key off one condition instead of
three thresholds that drift apart. The informative case is the carrier that cleared
the gate on a thin record, and that one is stated as a probability.

## Eligibility cannot depend on which engine you picked

Screening originally lived inside the expected-value engine. The heuristic engine had
its own notion of equipment as a weighted signal and no gates at all, which meant it
ranked carriers second and fourth on a reefer load that the other engine excluded by
name as unable to haul it. Choosing an engine silently chose whether hard constraints
were enforced.

Eligibility and candidate generation are now a shared pre-stage that runs before any
scoring, so both engines receive the same candidate set and publish the same
exclusions. The rule this encodes: a gate is a fact about the load and the carrier,
so it cannot live inside a scoring strategy. Anything an engine is allowed to define
for itself is something the engines are allowed to disagree about.

The heuristic's equipment signal now reads the same probability the gate reads. It is
no longer deciding eligibility — it separates a carrier proven on the trailer from one
that survived on a thin record — and sharing the estimate is the point, since two
different notions of "has a reefer" is exactly how a carrier gets excluded by one part
of the system and rewarded by another.

## Ranking by value per hour, and where that stops working

Carriers are ordered by expected value per hour of broker time, not raw expected
value, because a $200 load that resolves in twenty minutes is worth more than a $220
load that takes a day to hear back on. Reply time is a real cost and the offer log
measures it.

That normalisation inverts once the value being divided is negative. Dividing by time
answers "how much value does an hour of broker time buy", which is meaningless when
the answer is a loss — a longer wait moves a negative number *toward* zero, so the
slowest carrier wins. A live case had a carrier at -$45 over 7.4 hours score -6.1/hour
and outrank one at -$20 over 1.1 hours at -17.0/hour. The normalisation now applies
only where expected value is positive, and losing loads rank on expected value alone.

## Cover or reprice, decided before who to call

Fixing the inversion above exposed the real problem underneath. On a load that loses
money at every rate, maximising expected value rewards carriers who are *unlikely to
accept*: one who declines costs only the phone call, while one who accepts locks in the
loss. So the ordering becomes least-bad rather than best-to-call, and a dispatcher
working down it spends the day on carriers who will say no. The old behaviour put the
one capable carrier first, but only by accident of the negative-EV division.

A ranked list quietly asserts the load is worth covering. So that premise is now
checked first, and when it fails the output stops being a ranking and becomes the
number that would change it: **what the load has to bill to be worth calling anyone
about.** For a fixed offer rate the call is worth making when

```
p(R - r - service) > (1 - p) * call
```

so the revenue required is `r + service + call*(1-p)/p`, minimised over the offer
rates available. Conceding more raises `r` but also raises `p`, which shrinks the
wasted-call term, so the minimum is a genuine trade-off and not simply the cheapest
offer.

This also fixes the perversity rather than merely labelling it, and the mechanism is
worth stating. Acceptance is capped by trailer capability, so for a carrier that
probably lacks the trailer `(1-p)/p` explodes and the revenue needed to justify calling
them goes with it — most of those calls are wasted. The cheapest route back to
viability is therefore a carrier that can actually haul the freight. On the sample
flatbed load the repricing target is the only carrier with a proven flatbed, needing
$1,437 against the $1,385 it bills now, while raw expected value ranks that same
carrier last of six. The decision and the ranking disagree, and the decision is right.

One of the three open loads in the sample data is in this state, so this is visible in
the UI rather than hypothetical. The heuristic engine returns no decision at all: an
engine with no notion of value cannot tell a load worth covering from one that is not,
and should not pretend to.

## The interface is a call sheet, not a dashboard

The first UI showed everything at once, which was the right instinct for an evaluator
reading a justification and the wrong one for a broker being shown the product. One
load detail screen carried roughly sixty data rows for the carrier list alone, plus a
nine-column table, a sidebar of four panels, and eighteen separate disclosure toggles.
Progressive disclosure was technically present and practically useless: a page full of
collapsed summaries still reads as dense, because every summary line is one more thing
to decide whether to read.

The reframing is that **this product's output is a phone call.** Everything the engine
computes exists to make one call better than the call a rep would have made from
memory, so the page is built around the call rather than around metrics. The number is
set large and dialable, the rate to open at is the second-biggest thing on the screen,
and the two or three facts that would change a dispatcher's mind sit under it. That is
the whole of the primary view.

Three tiers, strictly enforced:

- the verdict and the call, always visible;
- everyone else, one line each, because a dispatcher makes one call at a time and six
  fully-argued options is a way of declining to answer;
- the proof, behind one entry point with five named doors instead of eighteen anonymous
  toggles.

**Nothing was deleted.** The prior shares, the unchecked gates, the audit trail, the
comparables, the EV arithmetic and the engine comparison are all still reachable, and a
check that every API field is still rendered somewhere is part of the review. What
changed is that they stopped competing with the answer for attention.

Two consequences worth recording. Reasons now carry a `kind` of `offer`, `basis` or
`carrier`, because the call card renders the rate and the odds itself and was otherwise
restating its own headline back in prose — the duplication was only visible once the
page was quiet enough to notice. And on a load flagged for repricing the card follows
the *verdict* rather than the ranking: they name different carriers on purpose, since
expected value on a losing load favours whoever is least likely to accept while the
repricing target is whoever is cheapest to make viable. Showing the ranking's leader
beside a verdict naming someone else just read as the page contradicting itself.

Colour and type come from the subject rather than from product convention. Interstate
guide-sign green with every neutral tinted toward it, so the palette reads as one
material; amber for "don't cover", which puts the verdict in the road's own signalling
vocabulary rather than inventing one. Archivo for lanes and verdicts, and every figure —
rate, reference, MC number, phone — set in IBM Plex Mono, because on a rate
confirmation or a bill of lading the numbers *are* the document and a broker reads them
by scanning columns. Fonts are self-hosted rather than pulled from a CDN so a demo
survives a bad conference network.

## The rate is a lever, not a prediction

The one claim a broker will not take on faith is the rate, because negotiating is the
part of the job they believe they are good at. Handing them a single figure invites an
argument, so the interface hands them the curve it came from: drag the offer and watch
the odds climb while expected value peaks and rolls over. Overpaying visibly buys
certainty and visibly costs money, and the recommendation stops being an opinion and
becomes the top of a hill.

The curve is sampled by the engine and published on the offer plan, never refitted in
the browser. A second implementation of the acceptance model could disagree with the one
that chose the offer, and the page would then be inviting a broker to "correct" the
engine toward a worse number — the same class of bug as having two notions of whether a
carrier owns a reefer. A test asserts the published curve is monotone in the rate and
that its maximum really is the recommended offer.

## Selection bias, stated rather than corrected

The offer log only contains carriers somebody chose to call. A carrier never called
looks unknown rather than unsuitable, and nothing distinguishes "would have said
no" from "was never asked". Estimated acceptance is therefore biased, and the
`limitations` array on every recommendation says so.

Correcting it needs randomised exploration or propensity weighting, neither of
which is implemented. What *is* implemented is the log schema that makes those
techniques possible later — capturing the candidate set, the offer, the order and
the outcome is the part that has to happen before any of it is available.

## Earlier decisions that still stand

### A lane is a metro market pair, resolved from ZIP prefix

City names are too fine and states are far too coarse. A stop's market is resolved
from its ZIP prefix rather than its city name, because ZIP prefixes already encode
geography — which is what fixes the NYC/Newark case: `07xxx` and `100xx` can be
assigned to one metro despite disagreeing on both city *and* state.

**Rejected:** clustering stops by lat/long. It is the better answer and what I
would build next; it needs a geocoder and a cluster-radius decision.

**Limitation:** the market table is hardcoded ZIP3 ranges for the Texas Triangle
plus a city-name fallback for records with no ZIP. Right shape, wrong resolution.
It also treats Austin and San Antonio as separate while treating all 9,000 square
miles of Dallas–Fort Worth as one market, which is defensible but arbitrary.

### Nothing derived is stored, so corrections need no repair

Loads are **upserted by identity** — a sync carries the whole object again, so the
newest sync is the truth and re-running a file changes nothing. Lane statistics,
carrier scores and price estimates are **computed at read time**. A correction
landing on day 6 for a day 2 load is reflected immediately, with no aggregate to
patch and no chance of a stale number surviving.

`test_replay_is_idempotent` asserts a full replay produces byte-identical state,
which is what makes "rebuild from scratch" a recovery strategy rather than a hope.

**What breaks at millions of loads:** all of it. The real design is incremental
aggregates keyed by (broker, lane, equipment, time bucket), which means storing
each load's previous contribution so it can be subtracted, and accepting that a
correction now mutates derived state and needs its own audit trail. I would keep
recompute-on-read as the reference implementation and test the incremental path
against it.

### Changes are classified, not just detected

- `REVEALED` — null became a number. A carrier rate appearing at booking is not a
  correction, and treating it as one would cry wolf on every load.
- `CORRECTION` — a real value replaced by a different real value.
- `PROGRESS` — status moved forward.
- `FALL_OFF` — status moved backwards out of `COVERED`, or the carrier on a booked
  load changed. Strictly this is indistinguishable from someone fixing a mistyped
  carrier; the business reading is preferred because it is far more common and far
  more expensive to miss.
- `DETAIL` — everything else.

### Money is modelled per TMS, because each one lies differently

- **FreightFlow** restates `totalBuy` in place.
- **HaulDesk** has no rate field: money is an append-only ledger, and a correction
  arrives as a *new negative row*. The adapter accumulates rows keyed by `rate_id`
  so re-reading cannot double-count. A load with no `pay` rows has a carrier rate
  of `None`, not `0` — conflating "not yet priced" with "priced at zero" would drag
  every median down. A carrier falling off reverses its linehaul row rather than
  deleting it, and the ledger still nets to what the replacement is owed.
- **BrokerOS** changes `bos__Carrier_Rate__c` with no marker. Only a diff detects it.

### Where a price comes from when the lane is thin

Comparable sets from narrowest to widest, stopping at the first with 3+ priced
loads: same lane + trailer → same lane → same pickup market + trailer → same pickup
market → everything this broker has priced. It then **says which level it used**,
in plain words. If nothing reaches 3 it still answers from the narrowest non-empty
set and marks itself low confidence, because refusing to answer is worse than
answering with a stated caveat.

A load is never a comparable for itself, and when a load has **no** equipment type
the trailer-qualified levels are skipped entirely rather than allowed to silently
match everything — otherwise the estimate would claim its comparables were "the
same trailer type" when no trailer type was ever known. That was a real bug, caught
by `test_price_basis_never_overstates_the_match`.

### Tenancy is structural, not a filter

The tenant is part of every API path, the constructor argument to `BrokerHistory`
(the **only** surface an engine is given, so it physically cannot reach another
tenant), and part of the load's primary key — so `/api/brokers/anchor/loads/{a
redline ref}` is a 404 rather than a leak.

IBRAHIM TRANSPORT works for two brokers under the same MC number, which makes this
testable rather than assertable. That now extends to the offer log:
`test_tenancy_holds_across_the_offer_log` fails if one broker's calls ever inform
another's estimates.

**A connection worth making for the shared pool.** The top of the shrinkage
hierarchy — the population prior — is inherently a *cross-tenant* quantity, and
that gives the pool a principled scope with tiered disclosure. Sharing a
population-level prior by equipment type reveals essentially nothing about any
individual broker's book, while sharing carrier-level history keyed by MC reveals
who your competitors haul with. The pool's first and safest product is priors for
sparse carriers, which is also exactly where brokers get the most value.

## What I cut, and why

- **Multi-load assignment.** Independent rankings are wrong when several loads
  compete for one truck, and this dataset demonstrates it: `TRINITY RIVER EXPRESS`
  ranks in the top three for all three of Redline's open loads, and for Summit
  `ALAMO RIDGE` is #1 for both. The fix is maximum-weight bipartite matching over
  a load × carrier utility matrix. The utility matrix already exists, so this is
  an additive layer rather than a rewrite — it is the single highest-value thing
  left undone.
- **Trained models.** No component is a fitted model; each is a shrunk estimate
  over a handful of observations. Gradient-boosted trees are the right answer at
  thousands of loads and actively worse at 8–12 priced loads per broker.
- **Counterfactual evaluation.** Propensity weighting and doubly robust estimation
  need the exploration data the log is designed to collect and does not yet have.
- **Postgres.** Ingestion order, idempotency and correction handling are the parts
  of persistence that carry risk, and all three are exercised by replaying files
  into an in-memory store behind a narrow `Store` interface. The cost is real:
  nothing survives a restart.
- **The shared carrier pool.** Not attempted, but the seam is deliberate and
  MC/DOT numbers are carried through all three adapters because cross-broker
  carrier identity is what a pool is built on.

## Known limitations

- **Position is a carrier's most recent delivery market**, which goes stale fast. A
  truck that delivered into Houston four days ago is not in Houston now. Real
  repositioning needs current truck location, and availability is a probability
  here rather than the fact it pretends to be.
- **Lane matching is binary.** Neighbouring markets contribute nothing, so a
  Dallas→Austin veteran gets no credit for a Dallas→Georgetown load beyond the
  shared origin, even though Georgetown is 30 miles from Austin.
- **Ranking is per load.** See the assignment cut above.
- **Value per hour is a one-step approximation** of a sequential search problem.
- **The heuristic engine's weights are still hand-picked** — that engine is a
  control, and its unfalsifiable weights are precisely the thing the expected-value
  engine exists to replace.
- **HaulDesk timestamps are naive local time** read as US Central; correct for this
  dataset, wrong across a DST boundary. `tzdata` is in the image so `zoneinfo`
  resolves properly. BrokerOS appointment dates carry no time at all and are
  anchored to Central — a normalisation gap that let a naive datetime reach the
  ranking layer and crash it, now covered by
  `test_every_normalised_datetime_is_timezone_aware`.
- **Service outcomes are compared at date granularity**, the common denominator
  across the three feeds. An hours-late truck is invisible in BrokerOS, and using a
  finer comparison would make the same carrier look reliable under one broker and
  late under another.
- **Business costs are plausible, not calibrated.** Nothing in this dataset could
  calibrate them, and the ranking is sensitive to them. A sensitivity analysis is
  the obvious next check.
