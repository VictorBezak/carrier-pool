---
name: pooled carrier facts
overview: "Replace the \"suppress on overlap\" pool rule with a fact-typed merge: carrier-owned facts (stop positions, appointment adherence, fall-throughs, equipment) pool across opted-in brokers and feed the primary ranking with visible provenance, while broker-owned facts (rates, customers, relationship depth) stay strictly local."
todos:
  - id: payload-tiers
    content: Restructure POOL_FIELDS into carrier-owned / positional / never-shared tiers; add stops (zip5 + 6h bucket + kind), appointment counts, fallthrough_count to the payload
    status: completed
  - id: merge-not-suppress
    content: Replace the overlap suppression in pool_rankings with pooled_facts(); add as_of to _known_authorities and switch authority matching to 'mc or dot'
    status: completed
  - id: blend-positioning
    content: Thread pooled stops into _position_estimate under the existing decay; let pooled deliveries compete for last_delivery_at; add own/pooled observation counts and the pooled_last_delivery basis
    status: completed
  - id: blend-reliability-stability
    content: Add pooled appointment counts to the reliability Beta accumulator, pooled fall-throughs to stability, and pooled equipment to candidate gating
    status: completed
  - id: no-blend-guards
    content: Assert structurally that price, customer_affinity, and relationship remain broker-local, and that pooled lane cells are reported but unweighted
    status: completed
  - id: provenance
    content: Surface own vs pooled counts through CarrierRanking, serializers, types, LoadDetailPage badges, and the DevSheet tiered policy panel
    status: completed
  - id: invert-tests
    content: Replace the two tests encoding the old suppression rule with the tighter invariants; update scripts/verify.sh
    status: completed
  - id: decisions
    content: Add the (AGENT) implementation entry to DECISIONS.md and flag the (USER) reversal of decision 1 for the user to author
    status: completed
isProject: false
---

# Pooled carrier facts for overlapping carriers

## The principle

Draw the line on **what kind of fact it is**, not on whose carrier it is:

- **Carrier-owned** — where a truck physically was and when, what equipment it runs, whether it hit appointments, whether it bailed after committing. True regardless of who observed it. Withholding makes the answer wrong, not private.
- **Broker-owned** — what A paid, who A's customer was, how much volume A runs, how deep A's relationship is. Never crosses.

Two rules follow that keep this consistent with existing decisions:

1. **Geography is priced once** (decisions 16, 17). Pooled stops feed `positioning` only. Pooled lane cells must stay unweighted, or the double-count that decisions 16 and 17 removed returns a third time, one level deeper.
2. **Own observations are never overridden, only supplemented.** The existing freshness machinery already handles this correctly — a pooled stop is just as *observed* as a local one, so it enters under the same `0.5 ** (age_days / 4)` decay with no provenance discount. More stops, not new math.

## Why the corpus already proves it

Delta Prime (MC 884201 / DOT 2551377), the only overlapping carrier:

- FreightFlow: 2 loads, Grand Prairie 75050 to Katy 77449, real `delivery_departed_at` timestamps.
- HaulDesk: 8 loads, New Braunfels 78130 to Pasadena 77502, `delivery_departed_at` absent throughout.

Concrete wins available today:

- HaulDesk's Seguin to Baytown load is the exact case decisions 16 and 17 agonize over (165 vs 85 vs 102 estimated empty miles). FreightFlow's observed Katy delivery is a real Houston-metro sighting that turns part of that inference into an observation.
- FreightFlow's Grand Prairie to Katy load currently ranks Delta Prime on 2 loads of evidence; pooling adds 8 stops and a strong adherence record.
- `_limitations` line 481, "reliability is based on arrival timestamps only for this broker", is literally fixed by pooling — the two brokers hold complementary timestamp types.

## Component verdicts

- `positioning` 0.30 — **blend**. Pooled stops enter `_position_estimate`, including competing for `last_delivery_at`.
- `reliability` 0.12 — **blend**. Pooled `(on_time, observations)` counts join the Beta accumulator.
- `stability` 0.04 — **blend fall-throughs only**. Corrections are the contributor's data hygiene, not carrier conduct.
- Equipment capability — **blend**. Feeds `_candidate_ids` gating and clears the false "no {equipment} history" limitation.
- `lane_familiarity` 0.24 — **report, do not weight**. `lane_effective` is a sum of continuous ZIP5-centroid kernels; ZIP3 buckets cannot enter that sum without corrupting it (decision 4), and weighting them re-creates the double count.
- `price` 0.16 — **never**. A contributor's carrier rates are its cost basis, and brokers exchanging what they pay the same carrier is rate-fixing-adjacent.
- `customer_affinity` 0.04 — **never**.
- `relationship` 0.10 — **never**. "How many loads I have run with them" is genuinely mine; a carrier owes A no favor because B ran 40. This is where the intent of decision 1 survives.

## Changes

### 1. New crossing payload — [backend/src/carrier_pool/pool.py](backend/src/carrier_pool/pool.py)

Restructure `POOL_FIELDS` from one flat allowlist into named tiers so the policy endpoint can explain itself. Add to the payload:

- `stops`: list of `zip5:bucket:kind` where `bucket` is a 6-hour slot id (matching the sync cadence, so it reveals nothing the sync schedule does not already imply) and `kind` is `pickup` or `delivery`. The 4-day freshness half-life makes 6h quantisation worth a few percent of weight.
- `appointment_observations` and `appointment_on_time`: integer counts, replacing the lossy `on_time_band` for merge purposes (keep the band for the stranger tier).
- `fallthrough_count`: integer.

Keep `carrier_name`, `mc_number`, `dot_number`, `home_city`, `home_state`, `equipment_types`, `lane_cells`, `recency_band`. Never add: rates, customers, load ids, source files, margins, correction counts, contributor volume.

Replace the suppression at line 101 with a merge. `_known_authorities` gains an `as_of` parameter for consistency with the rest of the read path, and authority matching becomes `mc or dot` rather than an exact tuple so a partially-identified carrier is not mistaken for a stranger.

New function producing the merge input:

```python
def pooled_facts(store, requesting_broker_id, opt_in_brokers, as_of) -> dict[str, PooledFacts]:
    """Carrier-owned facts from other opted-in brokers, keyed by the requesting
    broker's own carrier_id. Strangers are excluded — they remain the pool tier."""
```

### 2. Blend into the ranker — [backend/src/carrier_pool/ranking.py](backend/src/carrier_pool/ranking.py)

`rank_carriers` gains `pooled: dict[str, PooledFacts] | None = None`, threaded through `_evidence` to `_position_estimate` and `_components`.

- `_position_estimate` — pooled stops append to `weighted_positions` under the same decay, and pooled deliveries compete for `last_delivery_at`. `PositionEstimate` gains `own_observations` and `pooled_observations`, and `basis` gains `pooled_last_delivery`.
- `_positioning_score` — `observations` grows, correctly lifting the carrier out of `POSITION_PRIOR_OBSERVATIONS` shrinkage, since there genuinely is more evidence.
- `_reliability_score` — add pooled counts to the `successes=3.0 / observations=4.0` accumulator.
- `_components` — `evidence.fallthrough_count` includes pooled fall-throughs; `lane_familiarity` evidence gains an unweighted `pooled_lane_cells` line; positioning and reliability evidence report own vs pooled counts side by side.
- `_confidence` — pooled reliability observations count; `total_loads` and `price_observations` stay local, so confidence rises modestly and honestly.

### 3. Provenance surfacing

- `CarrierRanking` gains `pooled: bool` plus per-component own/pooled counts in `evidence`. Deliberately **no contributor name**: at two participants a count already identifies the source, but at n>2 attribution is a real leak and the API should not be shaped to require it.
- `_reasons` — e.g. "position confirmed by a pooled sighting 3 hours old, not present in your TMS".
- `_limitations` — "part of this carrier's evidence comes from the shared pool and cannot be traced to your sync files"; and clear the arrival-only and missing-equipment limitations when pooled data fills the gap.
- [backend/src/carrier_pool/api/serializers.py](backend/src/carrier_pool/api/serializers.py) `carrier_ranking` passes the new fields; [frontend/src/api/types.ts](frontend/src/api/types.ts) mirrors them.
- [frontend/src/pages/LoadDetailPage.tsx](frontend/src/pages/LoadDetailPage.tsx) — pooled badge on affected carrier rows, own vs pooled counts in the component evidence.
- [frontend/src/components/DevSheet.tsx](frontend/src/components/DevSheet.tsx) — the flat `fields` / `never_shared` lists become the three tiers, with the merge rule stated.

### 4. Tests that must invert — [backend/tests/test_pool.py](backend/tests/test_pool.py)

`test_pool_toggle_does_not_change_broker_local_answer` and `test_overlapping_delta_prime_never_enters_pool_tier` encode the old rule and must be **replaced** with tighter invariants, not deleted:

- price estimate byte-identical with the pool on and off.
- `price`, `customer_affinity`, `relationship` component scores byte-identical with the pool on and off.
- `positioning` and `reliability` change for Delta Prime, in the expected direction, with `pooled_observations > 0`.
- payload key set still exactly equals the allowlist under `recursive_payload_keys`.
- new: no pooled field value can be traced to a rate, customer, or load id.
- opted-out and BrokerOS isolation unchanged.

[scripts/verify.sh](scripts/verify.sh) asserts the pool tier *excludes* overlapping Delta Prime history; that assertion inverts to Delta Prime being enriched in the requesting broker's own tier.

### 5. Optional data case — [tools/datagen/scenarios.py](tools/datagen/scenarios.py)

The Delta Prime split is a strong natural demo, but no case yet exists where a pooled sighting *flips* a ranking. Consider one crafted overlap where the contributor's 6-hour-old delivery sits 20 miles from the requesting broker's pickup while the local last sighting is 6 days and 165 miles out. Requires `docker compose down -v` before re-ingest, per the README.

## Honest limitations to record

- **At two participants, anonymity is fiction.** FreightFlow and HaulDesk are the only eligible brokers, so every pooled fact is fully attributable. A pooled Pasadena stop tells FreightFlow that HaulDesk has freight into Pasadena. This is accepted and documented, not mitigated; k-anonymity is vacuous at n=2.
- ZIP5 stop locations are the finest grain in the design and exist because `DEADHEAD_FREE_MILES` is 45 and `POSITION_SOFTMIN_MILES` is 40 — ZIP3 error is the same size as the effect being measured, so a coarser grain would buy provenance complexity for no accuracy.
- Pooled evidence is not auditable from the receiving broker's own sync files, which is a genuine weakening of the explainability property the rest of the product rests on. The provenance labelling is the mitigation.

## Your action item

Decision 1 in [DECISIONS.md](DECISIONS.md) is a `(USER)` entry and states the rule this reverses. It needs a new `(USER)` decision in your words; an agent must not edit or supersede it. The implementation entry will be added as `(AGENT)` alongside.
