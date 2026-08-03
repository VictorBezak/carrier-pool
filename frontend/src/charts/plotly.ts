import type { Config, Layout } from "plotly.js";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js/lib/core";
import bar from "plotly.js/lib/bar";
import scatter from "plotly.js/lib/scatter";
import scattergeo from "plotly.js/lib/scattergeo";
import "plotly.js/dist/plotly-geo-assets.js";

Plotly.register([bar, scatter, scattergeo]);

export const Plot = createPlotlyComponent(Plotly);

export const CHART_CONFIG: Partial<Config> = {
  displayModeBar: false,
  responsive: true
};

const FALLBACK_COLORS = {
  foreground: "#0f1418",
  muted: "#626c7a",
  border: "#e2e6ec",
  primary: "#1b4de4",
  card: "#ffffff",
  warn: "#b45309",
  comp: ["#12308c", "#1b4de4", "#4570ec", "#7c97f2", "#a8baf7", "#cbd7fb", "#e4eafd"]
};

function cssVar(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function chartColors() {
  return {
    foreground: cssVar("--foreground", FALLBACK_COLORS.foreground),
    muted: cssVar("--muted-foreground", FALLBACK_COLORS.muted),
    border: cssVar("--border", FALLBACK_COLORS.border),
    primary: cssVar("--primary", FALLBACK_COLORS.primary),
    card: cssVar("--card", FALLBACK_COLORS.card),
    warn: cssVar("--warn", FALLBACK_COLORS.warn),
    comp: FALLBACK_COLORS.comp.map((fallback, index) => cssVar(`--comp-${index + 1}`, fallback))
  };
}

export function baseLayout(height: number): Partial<Layout> {
  const colors = chartColors();
  return {
    autosize: true,
    height,
    margin: { l: 8, r: 8, t: 8, b: 28 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: {
      family: "IBM Plex Sans, system-ui, sans-serif",
      size: 11,
      color: colors.foreground
    },
    hoverlabel: {
      bgcolor: colors.foreground,
      bordercolor: colors.foreground,
      font: { color: colors.card, family: "IBM Plex Sans, system-ui, sans-serif", size: 11 }
    },
    showlegend: false
  };
}
