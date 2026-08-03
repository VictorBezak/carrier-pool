import type { LoadDetail, PriceEstimate } from "@/api/types";
import { Plot, CHART_CONFIG, baseLayout, chartColors } from "@/charts/plotly";
import { money } from "@/format";

function dollars(ppm: number, distance: number) {
  return ppm * distance;
}

export function PriceRangeChart({ price, detail }: { price: PriceEstimate; detail: LoadDetail }) {
  const colors = chartColors();
  const similarLane = dollars(price.observed_ppm, detail.distance_miles);
  const brokerAverage = dollars(price.prior_ppm, detail.distance_miles);
  const markers = [
    { label: "similar lanes", value: similarLane, color: colors.comp[2] },
    { label: "your average", value: brokerAverage, color: colors.muted },
    { label: "we suggest", value: price.point_usd, color: colors.primary }
  ];

  const layout = {
    ...baseLayout(158),
    margin: { l: 10, r: 10, t: 6, b: 52 },
    xaxis: {
      range: [price.low_usd - 35, price.high_usd + 35],
      gridcolor: colors.border,
      zeroline: false,
      tickfont: { family: "IBM Plex Mono, monospace", size: 10, color: colors.muted },
      tickprefix: "$",
      fixedrange: true
    },
    yaxis: {
      visible: false,
      fixedrange: true
    },
    shapes: markers.map((marker) => ({
      type: "line",
      x0: marker.value,
      x1: marker.value,
      y0: -0.36,
      y1: 0.36,
      xref: "x",
      yref: "y",
      line: { color: marker.color, width: marker.label === "we suggest" ? 3 : 2 }
    })),
    annotations: markers.map((marker, index) => ({
      x: marker.value,
      y: index === 1 ? -0.5 : 0.5,
      text: `${marker.label}<br><b>${money(marker.value)}</b>`,
      showarrow: false,
      xanchor: "center",
      yanchor: index === 1 ? "top" : "bottom",
      font: { family: "IBM Plex Sans, system-ui, sans-serif", size: 10, color: marker.color }
    }))
  };

  return (
    <Plot
      data={[
        {
          type: "bar",
          orientation: "h",
          x: [price.high_usd - price.low_usd],
          base: [price.low_usd],
          y: [0],
          width: [0.22],
          marker: { color: colors.comp[6], line: { color: colors.border, width: 1 } },
          hovertemplate: `Expected range: ${money(price.low_usd)} to ${money(price.high_usd)}<extra></extra>`
        }
      ]}
      layout={layout}
      config={CHART_CONFIG}
      useResizeHandler
      className="h-full w-full"
      style={{ width: "100%", height: "100%" }}
    />
  );
}
