---
name: combined carrier table
overview: Combine the local and pool carrier tables in the load detail UI, add clear source/pool contribution indicators, and move the lane history map below the table at full width.
todos: []
isProject: false
---

# Combined Carrier Table

## Scope

This should be a frontend-only change in `[frontend/src/pages/LoadDetailPage.tsx](frontend/src/pages/LoadDetailPage.tsx)`. The backend already returns the right separation:

- `own_carriers`: broker-local carriers, some with `pooled: true` when shared-pool facts enriched an overlap.
- `pool_carriers`: non-overlapping carriers from other brokers, still separate because they lack local component evidence and local lane history.

## Layout Change

Replace the current two-column carrier/map section:

```tsx
<div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
  <CarrierTable carriers={recommendation.own_carriers} ... />
  <Card>...<LaneGeoMap ... /></Card>
</div>

{session.poolEnabled && <PoolTable carriers={recommendation.pool_carriers} />}
```

with a vertical full-width layout:

- Full-width combined carrier table.
- Full-width lane history card below it.
- Remove the separate `PoolTable` section.

## Combined Row Model

Inside `LoadDetailPage.tsx`, create a small discriminated union:

- Local row: wraps `CarrierRanking`, source `local`, price from the `price` component, evidence from `CarrierEvidence`, geometry from `carrier.geometry`.
- Pool row: wraps `PoolCarrierRanking`, source `pool`, price from `expected_carrier_cost_usd`, evidence from the existing “What was shared” payload panel, geometry from `carrier.geometry` which currently shows the target only.

Sort local rows first by their existing rank, then pool rows as `P1`, `P2`, etc. That preserves the product meaning: “call my known carriers first; here are extra carriers if needed.”

## Table UX

Rename `CarrierTable` to something like `CombinedCarrierTable` and add a source column:

- `Your network` for broker-local carriers with no pooled contribution.
- `Your network + pool facts` for overlapping carriers where `carrier.pooled === true`.
- `Shared pool` for non-overlapping pool carriers.

Keep the current `pooled facts` badge for local enriched carriers, and add a distinct `shared pool` badge for pool-only carriers. The existing expand button can show:

- `Show reasoning` for local rows.
- `What was shared` for pool rows.

## Selection And Map

Change selected carrier state from `carrier_id` to a stable row key, e.g. `local:${carrier_id}` or `pool:${contributor_broker_id}:${carrier_id}`.

The map card below the table should use the selected row’s geometry:

- Local carrier: current lane history map.
- Pool carrier: target-only map plus a short note like “Pool carriers share bucketed lane cells, not raw historical lanes.”

## Types And Cleanup

No backend/API type change should be needed. Update only frontend helper types in `LoadDetailPage.tsx` if useful.

Remove `PoolTable` after its payload-expansion UI has been folded into `CombinedCarrierTable`.

## Verification

Run:

- `npm run build`
- `uv run --with pytest pytest -q` from `[backend](backend)` only if no backend files changed
- `./scripts/verify.sh` if you want to re-confirm the Docker/API path still passes after the UI change
