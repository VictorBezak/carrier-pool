import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { ComponentScore } from "@/api/types";
import { componentLabel } from "@/format";

/**
 * The bar length is the carrier's total score, split into the seven weighted
 * components that produced it: each segment is weight x score. So the same element
 * answers "how strong is this carrier" and "what made it strong".
 */
const RAMP = ["bg-comp-1", "bg-comp-2", "bg-comp-3", "bg-comp-4", "bg-comp-5", "bg-comp-6", "bg-comp-7"];

export function contribution(component: ComponentScore) {
  return component.score * component.weight;
}

export function ContributionBar({ components, className }: { components: ComponentScore[]; className?: string }) {
  return (
    <div className={cn("flex h-2.5 w-full overflow-hidden rounded-sm bg-muted ring-1 ring-inset ring-border", className)}>
      {components.map((component, index) => (
        <Tooltip key={component.name}>
          <TooltipTrigger asChild>
            <div
              className={cn("min-w-px transition-opacity hover:opacity-70", RAMP[index % RAMP.length])}
              style={{ width: `${contribution(component) * 100}%` }}
            />
          </TooltipTrigger>
          <TooltipContent side="top">
            <span className="capitalize">{componentLabel(component.name)}</span>
            <span className="font-mono tabular-nums text-background/70">
              {component.score.toFixed(2)} x {component.weight.toFixed(2)} = {contribution(component).toFixed(3)}
            </span>
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}

export function ContributionLegend({ components }: { components: ComponentScore[] }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1">
      {components.map((component, index) => (
        <span key={component.name} className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className={cn("size-2 rounded-[2px]", RAMP[index % RAMP.length])} aria-hidden />
          <span className="capitalize">{componentLabel(component.name)}</span>
        </span>
      ))}
    </div>
  );
}

export { RAMP as CONTRIBUTION_RAMP };
