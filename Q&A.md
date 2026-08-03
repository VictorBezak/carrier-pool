# Q&A

The questions the README says this platform has to answer, with short answers and a live example from the demo data. Every number below comes from the running stack, so you can follow along in the UI.

Reasoning always ships next to the answer: each carrier row has a **Reasoning** expander with the plain-English "why" *and* the watch-outs, and every price has a **Show reasoning** panel listing the past loads it came from.

---

## 1. Which of my carriers should I call first, and why?

The load board has a **Call first** column, and opening a load ranks every carrier 0–100 with the reasoning attached.

The score blends seven things about the carrier's own history with this broker, weighted by how much they matter:

| What we look at | Weight |
|---|---|
| Empty miles to reach the pickup | 30% |
| Experience on this lane | 24% |
| What they usually charge | 16% |
| On-time record | 12% |
| Depth of your relationship | 10% |
| History with this customer | 4% |
| Rate and fall-through stability | 4% |

**Live example** — FreightFlow's Arlington → Sugar Land load: **Ibrahim Transport, 71, high confidence.** They've run 10 loads for this broker, 5.3 of which count as similar-lane, at $4.79/mi against a $4.94/mi benchmark.

Empty miles is the heaviest input because that is the number a carrier prices its quote around — a truck that just delivered near your pickup is an easy yes, and it's cheaper. On HaulDesk's Seguin → Baytown load, Brazos wins at 61 with 27 empty miles over Delta Prime at 58, even though Delta Prime knows the corridor better.

**What it is not:** a prediction of who will say yes. No TMS records who was called, tendered, or declined, so we rank by observable fit and let the broker make the call.

---

## 2. What should I expect to pay a carrier for this load?

A dollar figure, a range, and a confidence badge — priced per mile from the broker's own booked loads, then multiplied by this load's miles.

**Live example** — Arlington → Sugar Land: **$1,349, expected $1,201 to $1,496, high confidence**, built from 7.2 comparable loads. Against the $1,490 customer rate, that's the margin shown right in the carrier table.

The range is not decoration. It widens automatically when the evidence is thin, which is how a broker can tell a firm number from a guess at a glance.

---

## 3. Where does the price come from when the exact lane has little data?

It walks down a ladder and tells you which rung it landed on:

1. **Similar lanes** — nearby pickups and deliveries, weighted by distance.
2. **Distance band** — loads of comparable length on the same equipment.
3. **Equipment prior** — what this broker pays for this trailer type generally.

Whatever it finds gets pulled toward the broker's general rate, so one weird load can't set the price.

**Live example** — BrokerOS's Conroe → Cibolo reefer load has no history on that lane at all. It falls to the distance band and reports **$1,212 with a wide $879–$1,544 range and low confidence** — honest about being a rough number instead of inventing precision.

---

## 4. What counts as "the same lane" when pickups are scattered across suburbs?

Not city names, and definitely not states. We measure the actual distance between ZIP centroids and let history count in proportion to how close it is, fading out over about 35 miles at each end.

That gets all three hard cases right:

- Grand Prairie history informs an Arlington pickup, because they're 8 miles apart.
- Chicago → NYC and Chicago → Newark would count as the same lane.
- "Texas → Texas" never becomes one lane. Dallas → Houston earns nothing on an El Paso → Houston load.

Running the lane backwards counts too, but discounted to 35%, since a carrier who knows the corridor isn't the same as one positioned for your direction.

Coordinates come from the US Census ZCTA file (all 33,144 of them), vendored into the repo so the geography is a real external authority rather than something we made up.

---

## 5. How does the scoring stay fair to a carrier with little history?

Every statistic is pulled toward a sensible default in proportion to how little evidence backs it, so one lucky load can't outrank a proven record. A carrier with a single great load lands near average, not at the top.

Separately, **confidence is calculated independently of score.** That's the important part: a carrier can rank first and still be flagged low confidence, which tells the broker "best available option, thin evidence" rather than hiding the uncertainty.

**Live example** — on HaulDesk's Seguin → Baytown load, Comal Creek sits 33 empty miles from the pickup and Brazos sits 27. Nearly identical. But Comal Creek's position rests on **one** delivery from 6 days ago while Brazos's rests on **eight** from 2 days ago, so they score 57 and 87 on that component and Comal Creek lands 5th. Its row says exactly why: *"empty miles are estimated from only 1 recorded delivery, so this carrier may not have a truck free near the pickup."*

Brazos wins that load at 61 and is still badged **low confidence** — the clearest demo of the two numbers doing different jobs.

---

## 6. What happens to your analytics when yesterday's load is corrected today?

**We never patch a derived number.** A correction arrives as a new version of the load in an append-only log, and the answer is recomputed from history. There is no stale aggregate to go hunting for, because there is no aggregate.

**Live example** — BrokerOS restated a Plano → Pearland buy rate from $1,180 to $1,320 in the day-10 evening sync. The lane's estimate moved from **$1,603 to $1,654** on its own. Open **Sync history** on any load to see the sync-by-sync trail with corrected values highlighted.

This also gives you **As-of replay** (under Dev tools): rewind to any earlier sync and the whole board — statuses, rates, rankings — re-renders as that broker's TMS actually had it at that moment.

**Honest limit at scale:** replaying a broker's full history per request is fine for this corpus and would not survive millions of loads. The next step is materialized per-broker, per-lane feature tables invalidated by the affected load-version keys — same rebuild-not-patch principle, just incremental.

---

## 7. How do you keep one broker's data out of another broker's answers?

Every statistic is keyed by *(broker, carrier)*, so there is no code path where one broker's numbers can reach another's ranking.

The proof is a test that doesn't take our word for it: for **every** active load, it re-ingests that broker's directory *alone* — the other two literally absent from disk — and asserts the rankings, scores, confidence, and prices come out byte-identical.

**Live example** — Delta Prime works for both FreightFlow and HaulDesk under the same MC number, with a great record at one and a poor one at the other. Switch brokers under **View as broker** and each sees only its own version of that carrier.

---

## 8. If brokers opt into the shared pool, what exactly is shared?

Only **facts about the carrier**, never facts about the broker. Both sides must opt in, and carriers are matched by MC/DOT authority number.

| Crosses the boundary | Never crosses |
|---|---|
| Carrier name, MC/DOT, home city/state | Rates and margins |
| Equipment types | Customer names |
| Stop sightings, bucketed to 6 hours | Load IDs and source files |
| On-time counts and band | Exact load counts and timestamps |
| Lane activity, bucketed to ZIP3 | Raw TMS payloads |

So a broker gains a better read on where a carrier's trucks are and how reliably they show up, and learns nothing about anyone's book. Price, relationship, and customer signals stay 100% local. Pool rows are scored on the same seven components as your own carriers — so a pool carrier *can* outrank one of yours, but only after paying the score cost of having no relationship or rate history with you.

**How it's proven:** the payload is an explicit allowlist, and tests walk the serialized output recursively to assert no key outside that list appears, no load ID or customer name appears anywhere in the text, and the contributing broker's identity is nowhere in the response. In the UI, expanding a pool carrier shows a literal **"Everything that crossed the boundary"** table — the whole payload, nothing hidden.

**Honest limits:** with two eligible brokers, anonymity is fiction — each can infer the contributor. And BrokerOS can't participate at all, because its TMS export has no MC/DOT field to match carriers on. We'd rather say that than invent an identifier.

---

## 9. How do I run it?

```bash
./scripts/verify.sh
```

Builds the stack, waits for health, opts two brokers into the pool, and asserts the known day-11 answer through the HTTP API. Then open <http://localhost:3000>.

The UI is deliberately **single-broker**, the way a real tenant sees it. Anything a broker wouldn't have in production — broker switching, as-of replay, the pool toggle, the request log — is quarantined behind **Dev tools** in the top-right.
