import type { LaneGeometry, MapPoint } from "@/api/types";
import { Plot, CHART_CONFIG, baseLayout, chartColors } from "@/charts/plotly";

type GeoLine = {
  name: string;
  points: Array<MapPoint | null>;
  color: string;
  width: number;
  dash?: "solid" | "dash";
  showlegend?: boolean;
};

function lats(points: Array<MapPoint | null>) {
  return points.map((point) => point?.lat ?? null);
}

function lons(points: Array<MapPoint | null>) {
  return points.map((point) => point?.lon ?? null);
}

function historyLines(geometry: LaneGeometry, color: string): GeoLine[] {
  return geometry.historical_lanes.slice(0, 12).map((lane, index) => ({
    name: index === 0 ? "carrier history" : "carrier history",
    points: [lane.origin, lane.destination],
    color,
    width: 1 + Math.min(3, lane.weight * 2),
    showlegend: index === 0
  }));
}

export function LaneGeoMap({ geometry }: { geometry: LaneGeometry }) {
  const colors = chartColors();
  const lines: GeoLine[] = [
    ...historyLines(geometry, colors.comp[3]),
    {
      name: "deadhead",
      points: [geometry.last_delivery, geometry.target.origin],
      color: colors.warn,
      width: 1.5,
      dash: "dash" as const,
      showlegend: Boolean(geometry.last_delivery)
    },
    {
      name: "this load",
      points: [geometry.target.origin, geometry.target.destination],
      color: colors.primary,
      width: 3,
      showlegend: true
    }
  ].filter((line) => line.points.every(Boolean) && (line.showlegend || line.name !== "deadhead"));

  const data = lines.map((line) => ({
    type: "scatter",
    mode: "lines+markers",
    name: line.name,
    x: lons(line.points),
    y: lats(line.points),
    line: { color: line.color, width: line.width, dash: line.dash ?? "solid" },
    marker: { color: line.color, size: line.name === "this load" ? 5 : 3 },
    opacity: line.name === "carrier history" ? 0.66 : 1,
    showlegend: line.showlegend,
    hovertemplate: "%{y:.2f}, %{x:.2f}<extra>%{fullData.name}</extra>"
  }));

  const layout = {
    ...baseLayout(278),
    margin: { l: 32, r: 10, t: 8, b: 26 },
    legend: {
      orientation: "h",
      y: -0.12,
      x: 0.02,
      font: { size: 10, color: colors.muted }
    },
    showlegend: true,
    xaxis: {
      range: [-100.2, -94.2],
      showgrid: true,
      gridcolor: colors.border,
      showticklabels: false,
      ticks: "",
      zeroline: false,
      tickfont: { family: "IBM Plex Mono, monospace", size: 10, color: colors.muted },
      fixedrange: true
    },
    yaxis: {
      range: [28.4, 33.5],
      scaleanchor: "x",
      scaleratio: 1,
      showgrid: true,
      gridcolor: colors.border,
      showticklabels: false,
      ticks: "",
      zeroline: false,
      tickfont: { family: "IBM Plex Mono, monospace", size: 10, color: colors.muted },
      fixedrange: true
    },
    annotations: [
      { x: -97.1, y: 32.8, text: "DFW", showarrow: false, font: { size: 10, color: colors.muted } },
      { x: -95.37, y: 29.76, text: "Houston", showarrow: false, font: { size: 10, color: colors.muted } },
      { x: -98.5, y: 29.42, text: "San Antonio", showarrow: false, font: { size: 10, color: colors.muted } }
    ]
  };

  return (
    <Plot
      data={data}
      layout={layout}
      config={CHART_CONFIG}
      useResizeHandler
      className="h-full w-full"
      style={{ width: "100%", height: "100%" }}
    />
  );
}
