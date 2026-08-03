declare module "plotly.js/lib/core" {
  import type * as Plotly from "plotly.js";

  const core: typeof Plotly;
  export default core;
}

declare module "plotly.js/lib/bar" {
  import type * as Plotly from "plotly.js";

  const trace: Plotly.PlotlyModule;
  export default trace;
}

declare module "plotly.js/lib/scatter" {
  import type * as Plotly from "plotly.js";

  const trace: Plotly.PlotlyModule;
  export default trace;
}

declare module "plotly.js/lib/scattergeo" {
  import type * as Plotly from "plotly.js";

  const trace: Plotly.PlotlyModule;
  export default trace;
}

declare module "plotly.js/dist/plotly-geo-assets.js";
