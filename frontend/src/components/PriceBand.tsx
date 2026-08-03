import { cn } from "@/lib/utils";
import type { PriceEstimate } from "@/api/types";
import { money, perMile } from "@/format";

function ratio(value: number, low: number, high: number) {
  if (high <= low) return 0.5;
  return Math.min(1, Math.max(0, (value - low) / (high - low)));
}

/**
 * Two rulers: what the load should cost, and how the estimate got there. The second
 * one is the whole pricing argument - observed history pulled toward the broker prior
 * by however much history there was.
 */
export function PriceBand({ price }: { price: PriceEstimate }) {
  const point = ratio(price.point_usd, price.low_usd, price.high_usd);

  const ppmValues = [price.observed_ppm, price.prior_ppm, price.point_ppm];
  const pad = (Math.max(...ppmValues) - Math.min(...ppmValues) || 0.4) * 0.35;
  const ppmLow = Math.min(...ppmValues) - pad;
  const ppmHigh = Math.max(...ppmValues) + pad;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <div className="relative h-9">
          <div className="absolute inset-x-0 top-4 h-1.5 rounded-sm bg-gradient-to-r from-muted via-primary/25 to-muted ring-1 ring-inset ring-border" />
          <div className="absolute top-2.5 h-4.5 w-0.5 -translate-x-1/2 rounded-full bg-primary" style={{ left: `${point * 100}%` }} />
        </div>
        <div className="flex items-baseline justify-between font-mono text-[11px] tabular-nums text-muted-foreground">
          <span>{money(price.low_usd)}</span>
          <span className="text-foreground">{money(price.point_usd)}</span>
          <span>{money(price.high_usd)}</span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className="relative h-8">
          <div className="absolute inset-x-0 top-3.5 h-px bg-border" />
          <Tick label="observed" value={price.observed_ppm} at={ratio(price.observed_ppm, ppmLow, ppmHigh)} tone="observed" />
          <Tick label="prior" value={price.prior_ppm} at={ratio(price.prior_ppm, ppmLow, ppmHigh)} tone="prior" />
          <Tick label="estimate" value={price.point_ppm} at={ratio(price.point_ppm, ppmLow, ppmHigh)} tone="point" />
        </div>
        <p className="text-[11.5px] text-muted-foreground">
          Observed {perMile(price.observed_ppm)} shrunk toward the {perMile(price.prior_ppm)} broker prior on{" "}
          <span className="font-mono tabular-nums text-foreground">{price.effective_loads.toFixed(1)}</span> effective loads.
        </p>
      </div>
    </div>
  );
}

function Tick({
  label,
  value,
  at,
  tone
}: {
  label: string;
  value: number;
  at: number;
  tone: "observed" | "prior" | "point";
}) {
  const style = {
    observed: "bg-comp-4",
    prior: "bg-muted-foreground",
    point: "bg-primary"
  }[tone];
  return (
    <div className="absolute top-0 flex -translate-x-1/2 flex-col items-center gap-1" style={{ left: `${at * 100}%` }}>
      <span className="font-mono text-[10px] tabular-nums text-muted-foreground">{value.toFixed(2)}</span>
      <span className={cn("h-2.5 w-0.5 rounded-full", style)} />
      <span className={cn("font-mono text-[9.5px] uppercase tracking-wide", tone === "point" ? "text-primary" : "text-muted-foreground")}>
        {label}
      </span>
    </div>
  );
}
