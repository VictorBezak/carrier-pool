import { useEffect, useRef, useState } from "react";
import type { LaneGeometry, MapPoint } from "@/api/types";
import { Plot, CHART_CONFIG, baseLayout, chartColors } from "@/charts/plotly";

type GeoLine = {
  name: string;
  points: Array<MapPoint | null>;
  color: string;
  width: number;
  dash?: "solid" | "dash";
  showlegend?: boolean;
  legendrank: number;
};

function lats(points: Array<MapPoint | null>) {
  return points.map((point) => point?.lat ?? null);
}

function lons(points: Array<MapPoint | null>) {
  return points.map((point) => point?.lon ?? null);
}

function zips(points: Array<MapPoint | null>) {
  return points.map((point) => point?.zip_code ?? "");
}

// Keep enough of the surrounding country in frame that state outlines stay
// recognizable, even when a lane is short.
const MIN_SPAN_DEGREES = 6;
const PAD_RATIO = 0.35;
const MARGIN_X = 8;
const MARGIN_Y = 30;

function paddedSpan(values: number[]) {
  const low = Math.min(...values);
  const high = Math.max(...values);
  return {
    mid: (low + high) / 2,
    span: Math.max(high - low, MIN_SPAN_DEGREES) * (1 + PAD_RATIO)
  };
}

function mercatorY(latDegrees: number) {
  return Math.log(Math.tan(Math.PI / 4 + (latDegrees * Math.PI) / 360));
}

function mercatorLat(y: number) {
  return ((2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180) / Math.PI;
}

// A geo subplot fits its lon/lat box into the plot area without distorting it, so
// a box that does not share the container's aspect ratio gets letterboxed. Widen
// whichever axis is short, in projected mercator units, so the map fills the card.
function mapWindow(points: MapPoint[], aspect: number) {
  const lon = paddedSpan(points.map((point) => point.lon));
  const lat = paddedSpan(points.map((point) => point.lat));

  const latTop = mercatorY(lat.mid + lat.span / 2);
  const latBottom = mercatorY(lat.mid - lat.span / 2);
  const projectedHeight = latTop - latBottom;
  const projectedWidth = (lon.span * Math.PI) / 180;

  if (projectedWidth < projectedHeight * aspect) {
    const width = ((projectedHeight * aspect) / Math.PI) * 180;
    return {
      lonRange: [lon.mid - width / 2, lon.mid + width / 2],
      latRange: [mercatorLat(latBottom), mercatorLat(latTop)]
    };
  }

  const midY = mercatorY(lat.mid);
  const height = projectedWidth / aspect;
  return {
    lonRange: [lon.mid - lon.span / 2, lon.mid + lon.span / 2],
    latRange: [mercatorLat(midY - height / 2), mercatorLat(midY + height / 2)]
  };
}

// The plot area and the lon/lat box have to be measured against the same numbers,
// so the layout height comes from this measurement too rather than a constant.
function usePlotArea() {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 420, height: 278 });

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > MARGIN_X && height > MARGIN_Y) setSize({ width, height });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, size, aspect: (size.width - MARGIN_X) / (size.height - MARGIN_Y) };
}

function historyLines(geometry: LaneGeometry, color: string): GeoLine[] {
  return geometry.historical_lanes.slice(0, 12).map((lane, index) => ({
    name: index === 0 ? "carrier history" : "carrier history",
    points: [lane.origin, lane.destination],
    color,
    width: 1 + Math.min(3, lane.weight * 2),
    showlegend: index === 0,
    legendrank: 1
  }));
}

export function LaneGeoMap({ geometry }: { geometry: LaneGeometry }) {
  const colors = chartColors();
  const { ref, size, aspect } = usePlotArea();
  // Traces paint in array order, so the repositioning leg comes last to stay on top of the
  // thicker target lane it usually overlaps. legendrank keeps the legend reading
  // history, last delivery, this load regardless of paint order.
  const lines: GeoLine[] = [
    ...historyLines(geometry, colors.comp[3]),
    {
      name: "this load",
      points: [geometry.target.origin, geometry.target.destination],
      color: colors.primary,
      width: 3,
      showlegend: true,
      legendrank: 3
    },
    {
      // Named for what it is rather than for the score: this is the run from the carrier's
      // last recorded drop, which is only the deadhead the ranker uses when that drop is
      // fresh. A stale drop is superseded by the carrier's operating footprint.
      name: "from last delivery",
      points: [geometry.last_delivery, geometry.target.origin],
      color: colors.warn,
      width: 1.5,
      dash: "dash" as const,
      showlegend: Boolean(geometry.last_delivery),
      legendrank: 2
    }
  ].filter((line) => line.points.every(Boolean) && (line.showlegend || line.name !== "from last delivery"));

  const drawn = lines.flatMap((line) => line.points).filter((point): point is MapPoint => Boolean(point));

  if (drawn.length === 0) {
    return <p className="text-sm text-muted-foreground">No mapped lanes for this carrier.</p>;
  }

  const view = mapWindow(drawn, aspect);

  const data = lines.map((line) => ({
    type: "scattergeo",
    geo: "geo",
    mode: "lines+markers",
    name: line.name,
    legendgroup: line.name,
    legendrank: line.legendrank,
    lat: lats(line.points),
    lon: lons(line.points),
    text: zips(line.points),
    line: { color: line.color, width: line.width, dash: line.dash ?? "solid" },
    marker: { color: line.color, size: line.name === "this load" ? 5 : 3 },
    opacity: line.name === "carrier history" ? 0.66 : 1,
    showlegend: line.showlegend,
    hovertemplate: "%{text}<extra>%{fullData.name}</extra>"
  }));

  const layout = {
    ...baseLayout(size.height),
    margin: { l: 4, r: 4, t: 4, b: 26 },
    legend: {
      orientation: "h",
      y: -0.12,
      x: 0.02,
      font: { size: 10, color: colors.muted }
    },
    showlegend: true,
    geo: {
      // "north america" at 50m is the only scope besides "usa" that carries state
      // boundaries, and unlike "usa" it is not locked to the albers usa
      // projection, whose fixed center cannot follow a single lane.
      scope: "north america",
      resolution: 50,
      projection: { type: "mercator" },
      bgcolor: "rgba(0,0,0,0)",
      showland: true,
      landcolor: colors.surface,
      showocean: true,
      oceancolor: colors.accent,
      showlakes: true,
      lakecolor: colors.accent,
      showcoastlines: true,
      coastlinecolor: colors.muted,
      coastlinewidth: 0.8,
      showcountries: true,
      countrycolor: colors.muted,
      countrywidth: 0.8,
      showsubunits: true,
      subunitcolor: colors.muted,
      subunitwidth: 0.6,
      lonaxis: { range: view.lonRange },
      lataxis: { range: view.latRange },
      domain: { x: [0, 1], y: [0, 1] }
    }
  };

  return (
    <div ref={ref} className="h-full w-full">
      <Plot
        data={data}
        layout={layout}
        config={CHART_CONFIG}
        useResizeHandler
        className="h-full w-full"
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
