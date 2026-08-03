import type { ComponentScore } from "@/api/types";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { componentName, componentTooltip, matchScore } from "@/labels";
import { cn } from "@/lib/utils";

/**
 * The bar length is the carrier's match score, split into the weighted components that
 * produced it: each segment is weight x score, so the same element answers "how strong is
 * this carrier" and "what made it strong". The track is the full 100 points, which makes
 * the unearned remainder as legible as the earned part.
 *
 * Seven segments in one hue cannot be decoded from a legend, so the row bar carries a
 * tooltip per segment and the named breakdown lives beside the lane map for whichever
 * carrier is selected. The bar is for shape and comparison, not for lookup.
 */
export const CONTRIBUTION_RAMP = ["bg-comp-1", "bg-comp-2", "bg-comp-3", "bg-comp-4", "bg-comp-5", "bg-comp-6", "bg-comp-7"];

export function contribution(component: ComponentScore) {
  return component.score * component.weight;
}

export function rampClass(index: number) {
  return CONTRIBUTION_RAMP[index % CONTRIBUTION_RAMP.length];
}

export function ContributionBar({ components, className }: { components: ComponentScore[]; className?: string }) {
  const total = components.reduce((sum, component) => sum + contribution(component), 0);
  return (
    <div
      className={cn("flex h-2.5 overflow-hidden rounded-sm bg-muted ring-1 ring-inset ring-border", className)}
      role="img"
      aria-label={`Match ${matchScore(total)} of 100, composed of ${components.map((component) => componentName(component.name)).join(", ")}`}
    >
      {components.map((component, index) => (
        <Tooltip key={component.name}>
          <TooltipTrigger asChild>
            <div
              className={cn("min-w-px transition-opacity hover:opacity-70", rampClass(index))}
              style={{ width: `${contribution(component) * 100}%` }}
            />
          </TooltipTrigger>
          <TooltipContent side="top">{componentTooltip(component)}</TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}
