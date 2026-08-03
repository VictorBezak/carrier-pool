import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Confidence, LoadStatus } from "@/api/types";
import { statusLabel } from "@/format";

/**
 * Status reads as a neutral chip with a colored dot rather than a flooded pill, so a
 * table of twenty loads does not turn into a colour chart.
 */
const STATUS_DOT: Record<LoadStatus, string> = {
  planned: "bg-muted-foreground",
  active: "bg-primary",
  covered: "bg-pos",
  in_transit: "bg-warn",
  delivered: "bg-pos/70",
  completed: "bg-muted-foreground/50"
};

export function StatusBadge({ status }: { status: LoadStatus }) {
  return (
    <Badge variant="outline" className="gap-1.5 bg-card font-normal capitalize">
      <span className={cn("size-1.5 rounded-full", STATUS_DOT[status])} aria-hidden />
      {statusLabel(status)}
    </Badge>
  );
}

const CONFIDENCE_STYLE: Record<Confidence, string> = {
  high: "border-pos/30 bg-pos/10 text-pos",
  medium: "border-warn/30 bg-warn/10 text-warn",
  low: "border-border bg-muted text-muted-foreground"
};

export function ConfidenceBadge({ confidence, className }: { confidence: Confidence; className?: string }) {
  return (
    <Badge variant="outline" className={cn("font-mono text-[10px] uppercase tracking-wider", CONFIDENCE_STYLE[confidence], className)}>
      {confidence}
    </Badge>
  );
}

/** Column-header voice: the utility face, small and tracked out. */
export function ColumnLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-foreground", className)}>
      {children}
    </span>
  );
}

export function Num({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono tabular-nums", className)}>{children}</span>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <ColumnLabel>{label}</ColumnLabel>
      <div className="text-[13px]">{children}</div>
    </div>
  );
}

export function ReasonList({ label, items, tone = "default" }: { label: string; items: string[]; tone?: "default" | "caution" }) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <ColumnLabel>{label}</ColumnLabel>
      <ul className="flex flex-col gap-1">
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-[12.5px] leading-relaxed">
            <span className={cn("mt-1.5 size-1 shrink-0 rounded-full", tone === "caution" ? "bg-warn" : "bg-primary/60")} aria-hidden />
            <span className={tone === "caution" ? "text-muted-foreground" : undefined}>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
