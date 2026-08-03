---
name: pool score parity
overview: Bring pool-only carrier scoring into the same component model as in-network carriers, then sort the combined carrier table by comparable score while keeping privacy and provenance explicit.
todos:
  - id: pooled-component-model
    content: Add a same-shape component scoring path for pool-only carriers using the existing ranker weights and explicit local-missing evidence
    status: pending
  - id: pool-positioning
    content: Score pool-only positioning from pooled ZIP5 six-hour stop sightings using the same deadhead and shrinkage logic as local carriers
    status: pending
  - id: pool-lane-reliability-stability
    content: Translate pooled ZIP3 lane cells, appointment counts, equipment buckets, and fall-through counts into same-named components
    status: pending
  - id: broker-owned-priors
    content: Keep price, relationship, and customer affinity private by using requesting-broker market priors, zero local relationship, and cold-start customer affinity
    status: pending
  - id: api-shape
    content: Return pool-only rows with comparable components, reasons, limitations, confidence, expected cost, and no contributor broker identity
    status: pending
  - id: combined-sort
    content: Sort local and pool-only rows together by comparable score in the combined carrier table, preserving source badges and provenance evidence
    status: pending
  - id: tests-and-docs
    content: Add regression tests for score parity, privacy, mixed sorting, and document the scoring policy in DECISIONS.md
    status: pending
isProject: false
---

# Pool Score Parity

## Goal

Bring pool-only carriers into the same scoring language as in-network carriers so the combined table can be sorted by score without misleading the broker.

This does **not** mean pooled evidence becomes as rich as local evidence. It means every row is scored through the same component names and weights, with missing broker-local evidence represented as priors or penalties rather than hidden behind a separate mini-score.

## Current Problem

Local carriers use the full ranker:

- `positioning`
- `lane_familiarity`
- `price`
- `reliability`
- `relationship`
- `customer_affinity`
- `stability`

Pool-only carriers currently use a separate exploratory score in `[backend/src/carrier_pool/pool.py](backend/src/carrier_pool/pool.py)`:

- bucketed lane match
- equipment bucket
- on-time band
- recency band

Those scores are not directly comparable, so the frontend keeps local carriers first and pool-only carriers after them. That is honest, but it is not the end state.

## Product Judgment

The broker should see one ranked list once the score is comparable. A pool-only carrier can beat an in-network carrier, but only after paying the real cost of missing broker-local evidence:

- no local relationship
- no customer history
- no carrier-specific rate history
- lower-resolution lane evidence
- lower confidence when evidence is thin or bucketed

That is better for the broker than either hiding pool candidates at the bottom or pretending pooled data is as strong as local TMS history.

## Backend Plan

### 1. Introduce Pool-Only Component Scoring

In `[backend/src/carrier_pool/pool.py](backend/src/carrier_pool/pool.py)`, replace the pool-only mini-score with a same-shape component builder.

Pool-only rows should produce `ComponentScore`s with the same names and weights as `[backend/src/carrier_pool/ranking.py](backend/src/carrier_pool/ranking.py)`:

- `positioning`
- `lane_familiarity`
- `price`
- `reliability`
- `relationship`
- `customer_affinity`
- `stability`

Prefer reusing ranker constants and helper functions where practical. If a helper is private but now shared across local and pool-only scoring, either keep the dependency explicit or move the shared helper into a small neutral module later. Avoid a broad refactor unless needed.

### 2. Component Policies

`positioning`: Use pooled `stops` (`zip5:bucket:kind`) with the same deadhead curve, freshness decay, and shrinkage logic as local carriers. This is the strongest reason to do parity.

`lane_familiarity`: Convert pooled `lane_cells` into a same-named component, but evidence must say it came from ZIP3 buckets, not ZIP5 centroid kernels. This component is comparable in weight but lower-resolution in evidence.

`price`: Never use contributor rates. Score price as neutral against the requesting broker's market estimate. Evidence should say `basis: broker_market_fallback` or equivalent, with the same expected cost as the requester's market estimate.

`reliability`: Use pooled appointment counts through the same Beta-style prior as local reliability.

`relationship`: Score as zero or near-zero because the requesting broker has no relationship with this carrier.

`customer_affinity`: Use the same cold-start prior as a local carrier with no same-customer loads.

`stability`: Use pooled fall-through/carrier-change count if available. Do not use correction counts, which are contributor data hygiene rather than carrier conduct.

### 3. PoolCarrierRanking Shape

Extend `PoolCarrierRanking` in `[backend/src/carrier_pool/pool.py](backend/src/carrier_pool/pool.py)` to include:

- `components: list[ComponentScore]`
- `pooled: true` or an equivalent source marker if useful
- existing `score`, `confidence`, `expected_carrier_cost_usd`, `reasons`, `limitations`, `payload`

Do **not** reintroduce contributor broker ID or name.

Update `[backend/src/carrier_pool/api/serializers.py](backend/src/carrier_pool/api/serializers.py)` and `[frontend/src/api/types.ts](frontend/src/api/types.ts)` to pass through the same component evidence for pool rows.

### 4. Confidence

Pool-only confidence should remain conservative:

- high should be rare unless there is strong lane bucket evidence, matching equipment, enough appointment observations, and recent stop evidence.
- medium is acceptable for good bucketed evidence.
- low remains the default for exploratory candidates.

The confidence label is important because a comparable score can still rest on less-auditable evidence.

## Frontend Plan

### 1. Sort One Combined List

In `[frontend/src/pages/LoadDetailPage.tsx](frontend/src/pages/LoadDetailPage.tsx)`, update `buildCarrierRows` so it sorts both local and pool rows by `score` descending.

Use a stable tie-breaker:

1. higher score
2. higher confidence (`high > medium > low`)
3. local before pool if still tied
4. carrier name

Rank labels should become ordinary row numbers (`1`, `2`, `3`) instead of `P1`, `P2`, etc. The `Source` column and badges are enough to distinguish pool-only rows.

### 2. Evidence Expansion

Pool-only rows should use the same `CarrierEvidence` component table now that they have components. Keep the boundary payload visible below or after the component table under a label like `Shared evidence payload`.

Local rows keep their existing component evidence.

### 3. Map Behavior

Keep the current map behavior:

- local carrier: local lane history map
- pool-only carrier: target-only map plus note that raw historical lanes are not shared

If pool lane cells become useful enough later, add a separate bucketed lane visualization. Do not draw raw trip lines from pooled data.

## Privacy Guardrails

Do not share or serialize:

- contributor broker ID
- contributor broker name
- rates
- margins
- customers
- load IDs
- source files
- raw TMS payloads
- exact trip timestamps
- exact load counts

Pool-only score parity should be achieved by making missing broker-owned evidence explicit, not by crossing more broker-owned data.

## Tests

Update or add tests covering:

- pool-only `PoolCarrierRanking` has all seven component names with the same weights as local rankings.
- price, relationship, and customer affinity for pool-only carriers do not use contributor data.
- pool-only API response does not include contributor broker identity.
- combined table sorting can place a pool carrier above a local carrier when its comparable score is higher.
- pool row reasons explain bucketed lane/equipment/reliability evidence, not generic pool copy.

Run:

- `cd backend && uv run --with pytest pytest -q`
- `cd frontend && npm run build`
- `./scripts/verify.sh` if the API shape or verify assertions change.

## Documentation

Add a new `(AGENT)` entry to `[DECISIONS.md](DECISIONS.md)` explaining:

- why pool-only carriers now use the same component model
- why missing local evidence is penalized/prior-backed rather than ignored
- why raw contributor rates/trips still do not cross the boundary
- why the combined table can now sort all carriers by score
