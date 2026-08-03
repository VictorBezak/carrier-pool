---
name: Corrections Pricing Equipment
overview: "Repair the silently-dropped rate corrections in the generated data, make correction detection work across all three brokers, add the load-level and per-carrier price estimate the README requires, and apply the equipment discount to lane evidence that plan #3 specified but never implemented."
todos:
  - id: fix-dropped-corrections
    content: Reschedule correction-bearing loads in scenarios.py so ff-correction-rate and hd-flatbed-history-1 land inside TOTAL_SLOTS; verify HaulDesk now emits an ADJUSTMENT pay row
    status: pending
  - id: validator-correction-rule
    content: Add validator rule that every non-zero correction_delta_usd produces an observable restatement or ADJUSTMENT row in the emitted data
    status: pending
  - id: correction-detection
    content: Replace the HaulDesk-only _rate_adjustment_abs check with broker-agnostic correction detection by diffing carrier_rate_usd across store.versions
    status: pending
  - id: pricing-module
    content: Add pricing.py with PriceEstimate, estimate_price, and estimate_carrier_price using the three-tier lane/equipment/broker fallback with comparables and confidence
    status: pending
  - id: ranking-price-refactor
    content: Refactor _prior_ppm and _price_score to delegate to pricing.py so kernel and equipment logic lives in one place
    status: pending
  - id: equipment-affinity
    content: Add shared equipment_affinity multiplier used by lane_weight, _price_score, and _prior_ppm; keep the candidate gate and fallback; feed equipment-matched evidence into _confidence
    status: pending
  - id: timezone-fix
    content: Parse HaulDesk Central timestamps as Central instead of stamping UTC; assert the 76 BrokerOS on-time verdicts are unchanged
    status: pending
  - id: scenario-tests
    content: Add tests for correction moves answer, rich-lane sanity check, state grouping trap, plus pricing tests for tight/wide bands and basis tier
    status: pending
  - id: cli
    content: Add python -m carrier_pool.cli printing each day-11 load with price estimate and ranked carriers with reasons
    status: pending
isProject: false
---

# Corrections, Pricing, and Equipment Evidence

## At a glance

Three problems, split by the layer each one breaks in. Nothing below is speculative cleanup; every item is either a stated README requirement or a verified bug.

- **Pricing (missing requirement).** The README requires answering "what should I expect to pay" for an active load. Nothing does. Section 4 - one new module, plus pointing the ranker at it instead of keeping duplicate math.
- **Corrections (verified bug, three layers).** The README mandates corrections in the data. Three are declared, one exists. The generator drops two, the validator misses it, and the ranker's detector reads a field that is always zero. Sections 1, 2, 3.
- **Equipment discount (verified bug, small).** Plan #3 line 138 said mismatched equipment history must not count as clean evidence. That discount landed in the pricing path but not the lane path. Section 5.

Section 7 is verification and visibility: tests for the above, and a CLI so the price output is observable. Section 6 (timezone) is cosmetic - measured at zero behavioural impact - and is the first thing to drop if scope needs cutting.

Suggested order: fix the data first (1-2), since later work is scored against it, then the ranker bug (3), then pricing (4), then equipment (5), then timezone, tests, and CLI.

## Context

An audit against the README surfaced one missing deliverable (the price estimate) and one data-integrity bug that invalidates a README-mandated scenario. Deferred at the user's direction: Dockerfiles/compose, and the `DECISIONS.md` pass answering the README's questions.

## 1. Repair dropped rate corrections (data integrity, do first)

Only one of three declared corrections reaches the emitted data. Verified via the canonical store: `bo-silent-restatement` goes `1180 -> 1320`; `ff-correction-rate` (+175) and `hd-flatbed-history-1` (-85) never produce a rate change.

Root cause is the early return in [tools/datagen/timeline.py](tools/datagen/timeline.py):

```python
if spec.correction_delta_usd:
    correction_slot = next_sync_slot(schedule["delivery_arrived"] + timedelta(hours=30))
    if correction_slot >= TOTAL_SLOTS:
        return _latest_per_sync(events)   # correction silently discarded
```

Both dropped loads sit late in the calendar (`TOTAL_SLOTS=43`), so `delivery_arrived + 30h` overflows the window.

Fix: move the correction-bearing loads earlier in [tools/datagen/scenarios.py](tools/datagen/scenarios.py) so the correction lands inside the window, rather than clamping the slot (clamping would collide with the terminal `COMPLETED` event in `_latest_per_sync`). Keep the guard, but it must become unreachable for declared corrections.

Knock-on effect: zero `ADJUSTMENT` rate rows exist today, so the `elif event.is_correction` branch in `_hauldesk_rates` ([tools/datagen/emitters/__init__.py](tools/datagen/emitters/__init__.py) line 251) has never fired. Confirm HaulDesk emits an `ADJUSTMENT` pay row once the event survives. The pay side currently carries only `LINEHAUL`, so an `ADJUSTMENT` row is unambiguously a correction.

## 2. Make the validator enforce it

[tools/datagen/validate.py](tools/datagen/validate.py) passes 129 files without noticing two missing scenarios, and `data/SCENARIOS.md` documents corrections that do not exist, making it a misleading acceptance-test map.

Add a rule: every spec with a non-zero `correction_delta_usd` must produce an observable change in the emitted data - a restated buy rate for FreightFlow/BrokerOS, or an `ADJUSTMENT` rate row for HaulDesk. Fail the build otherwise.

## 3. Correction detection across all three brokers

`correction_count` in [backend/src/carrier_pool/ranking.py](backend/src/carrier_pool/ranking.py) reads `load.raw["_rate_adjustment_abs"]`, which [backend/src/carrier_pool/ingest.py](backend/src/carrier_pool/ingest.py) injects only for HaulDesk. Combined with item 1, the signal is currently dead everywhere.

Replace with a broker-agnostic derivation over `store.versions`: count a correction when `carrier_rate_usd` moves from one non-null value to a *different* non-null value, attributed to the carrier of record at that time. Initial `null -> value` is population, not correction.

This is safe for HaulDesk despite its accumulating `+=` rates, because `carrier_rate_usd` sums only the `pay` side and that side carries just `LINEHAUL` then `ADJUSTMENT`. Retain `_rate_adjustment_abs` as corroboration.

## 4. Price estimate (README question 2)

New module `backend/src/carrier_pool/pricing.py`. Both shapes requested:

- `estimate_price(store, target, geo) -> PriceEstimate` - the load-level market rate
- `estimate_carrier_price(store, target, carrier_id, geo) -> PriceEstimate` - what this specific carrier is likely to want

`PriceEstimate` carries `point_usd`, `low_usd`, `high_usd`, `point_ppm`, `basis`, `effective_loads`, `confidence`, `comparables`, `reasons`, `limitations`. Comparables list the actual historical loads and their kernel weights so a reviewer can trace any number back to source files.

Fallback hierarchy, following plan #3 lines 116-118 and answering the README's "where should a price estimate come from when the exact lane has little data":

1. Broker + equipment-weighted + lane kernel
2. Broker + equipment + distance band
3. Broker-wide equipment prior

Reuse the existing shrinkage form `(n_eff * observed + k * prior) / (n_eff + k)` with `k=4`. Derive the range from the weighted dispersion of comparable rates, widened as `n_eff` shrinks, so a thin lane returns a visibly wide band rather than false precision. `basis` names which tier produced the answer.

Then refactor `_prior_ppm` and `_price_score` in `ranking.py` to delegate to this module, so the kernel and equipment logic exists once rather than being duplicated across three functions.

## 5. Equipment evidence discount (not a scored component)

Investigated per the user's request. Keeping equipment as a gate is correct and deliberate:

- Plan #3 line 68 specifies it as a requirement, not a feature weight
- Equipment is physical feasibility, not preference; scoring it would let a flatbed carrier out-rank a reefer carrier on a reefer load
- The HaulDesk `Seguin -> Baytown` reefer load has 0 equipment-matching carriers of 6, so the `_candidate_ids` fallback is load-bearing; a hard gate returns nothing
- Only 1 of 22 carriers has multi-equipment history, so inferred capability is far too thin to exclude on

The actual defect is that `lane_weight()` applies no equipment term, so mismatched history earns full lane familiarity - contradicting plan #3 line 138 ("does not treat flatbed history as clean reefer evidence"). Meanwhile `_price_score` uses 0.35 and `_prior_ppm` uses 1.0/0.6/0.25, three inconsistent constants.

Fix: a single shared `equipment_affinity(target_equipment, historical_equipment) -> float` used by `lane_weight`, `_price_score`, and `_prior_ppm`. Keep the candidate gate and its fallback. Feed equipment-matched evidence into `_confidence`, which currently uses raw `lane_effective`. Keep the existing limitation string.

## 6. Timezone handling (minor, latent)

`_central_date()` in `ingest.py` stamps `+00:00` despite its name, and `_parse_local()` labels HaulDesk's naive Central wall-clock as UTC. Generator confirms the intent: FreightFlow emits real `-05:00` offsets, BrokerOS emits true UTC, HaulDesk emits naive Central.

Measured impact is currently zero - 0 of 76 BrokerOS stop arrivals change their on-time verdict under corrected windows - so this is mislabeling, not a live bug. Fix it to parse Central as Central, and assert the verdict count is unchanged.

## 7. Tests and a way to run it

Add coverage for the three documented-but-untested scenarios: correction moves answer, rich-lane sanity check, state grouping trap. The correction test should assert an estimate actually moves after the correcting sync is ingested.

Add pricing tests: rich lane produces a tight band and high confidence, cold lane falls through to a broader tier with a wide band and low confidence, and `basis` reports the tier used.

Add a small `python -m carrier_pool.cli` that prints each day-11 load with its price estimate and ranked carriers with reasons. This is an inspection and demo entry point, not deployment work - it is how the price estimate becomes visible now, and it is the natural precursor to the API behind the eventual frontend.

## Deferred

- Dockerfiles, compose, and run docs - per user, deferred to the frontend phase
- `DECISIONS.md` pass answering the README's questions - user is handling
- Scaling: `rank_carriers` rescans all broker history per call, which is O(all history) per recommendation. Premature to optimize at 69 loads; worth documenting later as a known limitation.