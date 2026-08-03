import type { CarrierRanking } from "@/api/types";
import { Plot, CHART_CONFIG, baseLayout, chartColors } from "@/charts/plotly";
import { componentName, componentTooltip, matchScore } from "@/labels";

function contribution(component: CarrierRanking["components"][number]) {
  return component.score * component.weight * 100;
}

export function CarrierCompositionChart({
  carriers,
  selectedCarrierId
}: {
  carriers: CarrierRanking[];
  selectedCarrierId: string | null;
}) {
  const colors = chartColors();
  const topCarriers = carriers.slice(0, 5);
  const components = topCarriers[0]?.components ?? [];
  const y = topCarriers.map((carrier) => carrier.carrier_name);

  const data = components.map((component, componentIndex) => ({
    type: "bar",
    orientation: "h",
    name: componentName(component.name),
    x: topCarriers.map((carrier) => contribution(carrier.components[componentIndex] ?? component)),
    y,
    marker: { color: colors.comp[componentIndex % colors.comp.length] },
    opacity: topCarriers.map((carrier) => (!selectedCarrierId || carrier.carrier_id === selectedCarrierId ? 1 : 0.42)),
    hovertemplate: `%{y}<br>${componentName(component.name)}: %{x:.0f} match points<extra></extra>`,
    customdata: topCarriers.map((carrier) => componentTooltip(carrier.components[componentIndex] ?? component))
  }));

  const layout = {
    ...baseLayout(250),
    margin: { l: 150, r: 18, t: 6, b: 30 },
    barmode: "stack",
    legend: {
      orientation: "h",
      y: -0.3,
      x: 0,
      font: { size: 10, color: colors.muted }
    },
    showlegend: true,
    xaxis: {
      range: [0, 100],
      title: { text: "Match", font: { size: 10, color: colors.muted } },
      ticksuffix: "",
      gridcolor: colors.border,
      zeroline: false,
      tickfont: { family: "IBM Plex Mono, monospace", size: 10, color: colors.muted }
    },
    yaxis: {
      autorange: "reversed",
      tickfont: { size: 10, color: colors.foreground }
    },
    annotations: topCarriers.map((carrier) => ({
      x: matchScore(carrier.score) + 1.5,
      y: carrier.carrier_name,
      text: `${matchScore(carrier.score)}`,
      showarrow: false,
      xanchor: "left",
      font: { family: "IBM Plex Mono, monospace", size: 10, color: colors.foreground }
    }))
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
