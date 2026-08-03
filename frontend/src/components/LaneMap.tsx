import type { LaneGeometry, MapPoint } from "@/api/types";

const BOUNDS = { minLon: -99.9, maxLon: -94.4, minLat: 28.7, maxLat: 33.4 };

function project(point: MapPoint | null) {
  if (!point) return null;
  return {
    x: 24 + ((point.lon - BOUNDS.minLon) / (BOUNDS.maxLon - BOUNDS.minLon)) * 272,
    y: 168 - ((point.lat - BOUNDS.minLat) / (BOUNDS.maxLat - BOUNDS.minLat)) * 140
  };
}

/**
 * Historical lanes are fanned out with increasing curvature. A carrier's history is
 * usually the same corridor as the load being covered, so drawn straight they would all
 * collapse onto the target line and read as one trip.
 */
function bow({ x: x1, y: y1 }: { x: number; y: number }, { x: x2, y: y2 }: { x: number; y: number }, index: number) {
  const midX = (x1 + x2) / 2;
  const midY = (y1 + y2) / 2;
  const length = Math.hypot(x2 - x1, y2 - y1) || 1;
  const offset = (index % 2 === 0 ? 1 : -1) * (6 + Math.floor(index / 2) * 9);
  const controlX = midX + ((y2 - y1) / length) * offset;
  const controlY = midY - ((x2 - x1) / length) * offset;
  return `M${x1} ${y1} Q${controlX} ${controlY} ${x2} ${y2}`;
}

/**
 * Curved lines are the carrier's own history weighted by lane similarity, dashed is the
 * deadhead from their last known delivery, straight is the load being covered.
 */
export function LaneMap({ geometry }: { geometry: LaneGeometry }) {
  const origin = project(geometry.target.origin);
  const destination = project(geometry.target.destination);
  const lastDelivery = project(geometry.last_delivery);

  return (
    <svg viewBox="0 0 320 190" role="img" aria-label="Texas Triangle lane trace" className="h-auto w-full">
      <path d="M68 40 L268 78 L156 162 Z" className="fill-none stroke-border" strokeWidth="1" strokeDasharray="2 3" />
      <g className="fill-muted-foreground font-mono text-[9px] uppercase tracking-wider">
        <text x="52" y="32">DFW</text>
        <text x="262" y="68">Houston</text>
        <text x="130" y="178">San Antonio</text>
      </g>

      {geometry.historical_lanes.map((lane, index) => {
        const from = project(lane.origin);
        const to = project(lane.destination);
        if (!from || !to) return null;
        return (
          <path
            key={`${lane.origin?.zip_code}-${lane.destination?.zip_code}-${index}`}
            d={bow(from, to, index)}
            fill="none"
            className="stroke-comp-4"
            strokeWidth={1 + Math.min(2.5, lane.weight * 2)}
            strokeLinecap="round"
            opacity={0.4 + Math.min(0.45, lane.weight * 0.5)}
          />
        );
      })}

      {lastDelivery && origin && (
        <line
          x1={lastDelivery.x}
          y1={lastDelivery.y}
          x2={origin.x}
          y2={origin.y}
          className="stroke-warn"
          strokeWidth="1.25"
          strokeDasharray="3 4"
        />
      )}
      {lastDelivery && <circle cx={lastDelivery.x} cy={lastDelivery.y} r="2.5" className="fill-background stroke-warn" strokeWidth="1.25" />}

      {origin && destination && (
        <line x1={origin.x} y1={origin.y} x2={destination.x} y2={destination.y} className="stroke-primary" strokeWidth="1.75" strokeLinecap="round" />
      )}
      {origin && <circle cx={origin.x} cy={origin.y} r="3.5" className="fill-primary" />}
      {destination && <circle cx={destination.x} cy={destination.y} r="3.5" className="fill-background stroke-primary" strokeWidth="1.75" />}
    </svg>
  );
}

export function LaneMapKey() {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-4 bg-primary" aria-hidden /> this load
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-4 bg-comp-4" aria-hidden /> carrier history
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-4 border-t border-dashed border-warn" aria-hidden /> deadhead
      </span>
    </div>
  );
}
