import type { ComponentScore } from "@/api/types";
import { Num } from "@/components/indicators";
import { contribution, rampClass } from "@/components/ContributionBar";
import { componentName } from "@/labels";
import { cn } from "@/lib/utils";

/**
 * The decomposition for one carrier, named rather than colour-coded. Each row is a track
 * whose length is how far that component can move the score at all, filled by how much of
 * it this carrier earned, so a short full bar (a light component done well) reads
 * differently from a long empty one (a heavy component the carrier fails).
 *
 * Tracks are scaled against the heaviest component rather than against 100, since the
 * widest weight is 0.30 and an absolute scale would leave every bar in the left third.
 * That keeps relative influence honest while using the column.
 */
export function CarrierScoreBreakdown({ components }: { components: ComponentScore[] }) {
  if (components.length === 0) {
    return <p className="text-sm text-muted-foreground">No scored components for this carrier.</p>;
  }

  const heaviest = Math.max(...components.map((component) => component.weight));

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2">
        {components.map((component, index) => (
          <Row key={component.name} component={component} index={index} heaviest={heaviest} />
        ))}
      </div>
      <p className="text-[11.5px] leading-relaxed text-muted-foreground">
        Bar length is how much a component can move the score; the filled part is what this carrier earned. Expand the
        carrier's reasoning for the evidence behind each one.
      </p>
    </div>
  );
}

function Row({ component, index, heaviest }: { component: ComponentScore; index: number; heaviest: number }) {
  const earned = Math.round(contribution(component) * 100);
  const available = Math.round(component.weight * 100);
  return (
    <>
      <span className="flex items-center gap-2 text-[12.5px] whitespace-nowrap">
        <span className={cn("size-2 shrink-0 rounded-[2px]", rampClass(index))} aria-hidden />
        {componentName(component.name)}
      </span>
      <span className="flex h-2.5 items-center">
        <span
          className="flex h-full overflow-hidden rounded-sm bg-muted ring-1 ring-inset ring-border"
          style={{ width: `${(component.weight / heaviest) * 100}%` }}
        >
          <span className={cn("h-full", rampClass(index))} style={{ width: `${component.score * 100}%` }} />
        </span>
      </span>
      <span className="whitespace-nowrap text-right">
        <Num className="font-medium">{earned}</Num>
        <Num className="ml-1.5 text-[10.5px] text-muted-foreground">of {available}</Num>
      </span>
    </>
  );
}
