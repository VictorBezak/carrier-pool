import type { ComponentScore } from "@/api/types";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ColumnLabel, Num, ReasonList } from "@/components/indicators";
import { componentName, evidenceDisplay, evidenceName, matchScore } from "@/labels";

export function CarrierEvidence({
  components,
  reasons,
  limitations
}: {
  components: ComponentScore[];
  reasons: string[];
  limitations: string[];
}) {
  return (
    <div className="flex flex-col gap-4 border-t bg-muted/30 p-4">
      {components.length > 0 && <ComponentTable components={components} />}
      <div className="grid gap-4 sm:grid-cols-2">
        <ReasonList label="Why this carrier" items={reasons} />
        <ReasonList label="Watch-outs" items={limitations} tone="caution" />
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
              <ColumnLabel>Strength</ColumnLabel>
            </TableHead>
            <TableHead className="h-7 px-2.5 text-right">
              <ColumnLabel>Influence</ColumnLabel>
            </TableHead>
            <TableHead className="h-7 px-2.5 text-right">
              <ColumnLabel>Match points</ColumnLabel>
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
                <span>{componentName(component.name)}</span>
              </TableCell>
              <TableCell className="px-2.5 py-1.5 text-right">
                <Num>{matchScore(component.score)}</Num>
              </TableCell>
              <TableCell className="px-2.5 py-1.5 text-right">
                <Num className="text-muted-foreground">{Math.round(component.weight * 100)}%</Num>
              </TableCell>
              <TableCell className="px-2.5 py-1.5 text-right">
                <Num className="font-medium">{Math.round(component.score * component.weight * 100)}</Num>
              </TableCell>
              <TableCell className="px-2.5 py-1.5">
                <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
                  {Object.entries(component.evidence).map(([key, value]) => (
                    <span key={key}>
                      {evidenceName(key)} <Num className="text-foreground">{evidenceDisplay(key, value)}</Num>
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
