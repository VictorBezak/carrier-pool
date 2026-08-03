import type { ComponentScore, LaneGeometry } from "@/api/types";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CONTRIBUTION_RAMP, contribution } from "@/components/ContributionBar";
import { LaneMap, LaneMapKey } from "@/components/LaneMap";
import { ColumnLabel, Num, ReasonList } from "@/components/indicators";
import { componentLabel, evidenceValue } from "@/format";
import { cn } from "@/lib/utils";

export function CarrierEvidence({
  components,
  geometry,
  reasons,
  limitations
}: {
  components: ComponentScore[];
  geometry: LaneGeometry;
  reasons: string[];
  limitations: string[];
}) {
  return (
    <div className="grid gap-5 border-t bg-muted/30 p-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-3">
        {components.length > 0 && <ComponentTable components={components} />}
        <div className="grid gap-4 sm:grid-cols-2">
          <ReasonList label="Why this carrier" items={reasons} />
          <ReasonList label="What we don't know" items={limitations} tone="caution" />
        </div>
      </div>

      <div className="flex flex-col gap-2 rounded-md border bg-card p-3">
        <ColumnLabel>Lane trace</ColumnLabel>
        <LaneMap geometry={geometry} />
        <LaneMapKey />
      </div>
    </div>
  );
}

function ComponentTable({ components }: { components: ComponentScore[] }) {
  return (
    <div className="overflow-hidden rounded-md border bg-card">
      <Table className="text-[12px]">
        <TableHeader className="bg-muted/60">
          <TableRow className="hover:bg-transparent">
            <TableHead className="h-7 px-2.5">
              <ColumnLabel>Component</ColumnLabel>
            </TableHead>
            <TableHead className="h-7 px-2.5 text-right">
              <ColumnLabel>Score</ColumnLabel>
            </TableHead>
            <TableHead className="h-7 px-2.5 text-right">
              <ColumnLabel>Weight</ColumnLabel>
            </TableHead>
            <TableHead className="h-7 px-2.5 text-right">
              <ColumnLabel>Contribution</ColumnLabel>
            </TableHead>
            <TableHead className="h-7 px-2.5">
              <ColumnLabel>Evidence</ColumnLabel>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {components.map((component, index) => (
            <TableRow key={component.name}>
              <TableCell className="px-2.5 py-1.5">
                <span className="flex items-center gap-2">
                  <span className={cn("size-2 shrink-0 rounded-[2px]", CONTRIBUTION_RAMP[index % CONTRIBUTION_RAMP.length])} aria-hidden />
                  <span className="capitalize">{componentLabel(component.name)}</span>
                </span>
              </TableCell>
              <TableCell className="px-2.5 py-1.5 text-right">
                <Num>{component.score.toFixed(3)}</Num>
              </TableCell>
              <TableCell className="px-2.5 py-1.5 text-right">
                <Num className="text-muted-foreground">{component.weight.toFixed(2)}</Num>
              </TableCell>
              <TableCell className="px-2.5 py-1.5 text-right">
                <Num className="font-medium">{contribution(component).toFixed(3)}</Num>
              </TableCell>
              <TableCell className="px-2.5 py-1.5">
                <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
                  {Object.entries(component.evidence).map(([key, value]) => (
                    <span key={key}>
                      {componentLabel(key)} <Num className="text-foreground">{evidenceValue(value)}</Num>
                    </span>
                  ))}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
