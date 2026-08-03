import type { LoadSummary } from "@/api/types";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ColumnLabel, Num, StatusBadge } from "@/components/indicators";
import { miles, money, pounds, timestamp } from "@/format";
import { cn } from "@/lib/utils";

type Field = {
  key: string;
  label: string;
  align?: "right";
  value: (version: LoadSummary) => string | number | null;
  render: (version: LoadSummary) => React.ReactNode;
};

const FIELDS: Field[] = [
  { key: "status", label: "Status", value: (v) => v.status, render: (v) => <StatusBadge status={v.status} /> },
  { key: "lane", label: "Lane", value: (v) => `${v.pickup.zip_code}-${v.delivery.zip_code}`, render: (v) => `${v.pickup.city} to ${v.delivery.city}` },
  { key: "equipment", label: "Equipment", value: (v) => v.equipment, render: (v) => <span className="capitalize">{v.equipment.replace(/_/g, " ")}</span> },
  { key: "weight", label: "Weight", align: "right", value: (v) => v.weight_lbs, render: (v) => <Num>{pounds(v.weight_lbs)}</Num> },
  { key: "distance", label: "Miles", align: "right", value: (v) => v.distance_miles, render: (v) => <Num>{miles(v.distance_miles)}</Num> },
  {
    key: "customer_rate",
    label: "Customer rate",
    align: "right",
    value: (v) => v.customer_rate_usd,
    render: (v) => <Num>{money(v.customer_rate_usd)}</Num>
  },
  {
    key: "carrier_rate",
    label: "Carrier rate",
    align: "right",
    value: (v) => v.carrier_rate_usd,
    render: (v) => <Num>{money(v.carrier_rate_usd)}</Num>
  }
];

/**
 * One row per sync that touched this load. A highlighted cell is a value this sync
 * changed after it had already been recorded - the corrections case the ranking and
 * pricing models have to survive.
 */
export function VersionHistory({ versions }: { versions: LoadSummary[] }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-[13px] font-medium">Sync history</h2>
          <p className="text-[12px] text-muted-foreground">
            {versions.length === 1
              ? "This load has arrived in one sync so far, so nothing has been corrected yet."
              : `${versions.length} versions of this load arrived across syncs. Highlighted cells changed a value that was already known.`}
          </p>
        </div>
        {versions.length > 1 && (
          <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
            <span className="size-2.5 rounded-[2px] bg-warn/15 ring-1 ring-warn/40" aria-hidden />
            corrected in that sync
          </span>
        )}
      </div>

      <div className="overflow-hidden rounded-lg border bg-card">
        <Table className="text-[12px]">
          <TableHeader className="bg-muted/60">
            <TableRow className="hover:bg-transparent">
              <TableHead className="h-7 px-2.5">
                <ColumnLabel>Synced at</ColumnLabel>
              </TableHead>
              <TableHead className="h-7 px-2.5">
                <ColumnLabel>Source file</ColumnLabel>
              </TableHead>
              {FIELDS.map((field) => (
                <TableHead key={field.key} className={cn("h-7 px-2.5", field.align === "right" && "text-right")}>
                  <ColumnLabel>{field.label}</ColumnLabel>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {versions.map((version, index) => {
              const previous = index > 0 ? versions[index - 1] : null;
              return (
                <TableRow key={`${version.source_file}-${version.synced_at}`}>
                  <TableCell className="px-2.5 py-1.5">
                    <Num>{timestamp(version.synced_at)}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-1.5">
                    <Num className="text-[10.5px] text-muted-foreground">{version.source_file.split("/").pop()}</Num>
                  </TableCell>
                  {FIELDS.map((field) => {
                    const changed = previous !== null && field.value(previous) !== field.value(version) && field.value(previous) !== null;
                    return (
                      <TableCell
                        key={field.key}
                        className={cn("px-2.5 py-1.5", field.align === "right" && "text-right", changed && "bg-warn/10 ring-1 ring-inset ring-warn/30")}
                      >
                        {field.render(version)}
                      </TableCell>
                    );
                  })}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
