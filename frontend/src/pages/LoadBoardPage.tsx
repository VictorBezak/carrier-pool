import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type VisibilityState
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown, Search } from "lucide-react";
import { api } from "@/api/client";
import type { LoadSummary, Recommendation } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { ColumnLabel, ConfidenceBadge, Num, StatusBadge } from "@/components/indicators";
import { day, equipment as equipmentLabel, margin, miles, money, timestamp } from "@/format";
import { cn } from "@/lib/utils";
import { useSession } from "@/session";

type Row = LoadSummary & { recommendation?: Recommendation | null };

const STATUS_FILTERS = [
  { value: "active", label: "Needs coverage" },
  { value: "covered", label: "Booked" },
  { value: "completed", label: "Delivered" },
  { value: "all", label: "All" }
] as const;

type StatusFilter = (typeof STATUS_FILTERS)[number]["value"];

export function LoadBoardPage() {
  const session = useSession();
  const navigate = useNavigate();
  const [loads, setLoads] = useState<LoadSummary[]>([]);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("active");
  const [equipmentFilter, setEquipmentFilter] = useState("all");
  const recommendations = useActiveRecommendations(session.brokerId, loads, session.asOf, session.poolEnabled);

  useEffect(() => {
    if (!session.brokerId) return;
    setPending(true);
    setError(null);
    void api
      .loads(session.brokerId, session.asOf)
      .then(setLoads)
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setPending(false));
  }, [session.brokerId, session.asOf]);

  const equipmentOptions = useMemo(() => [...new Set(loads.map((load) => load.equipment))].sort(), [loads]);

  const rows = useMemo<Row[]>(() => {
    const term = search.trim().toLowerCase();
    return loads
      .filter((load) => {
        if (status === "completed") {
          if (load.status !== "completed" && load.status !== "delivered") return false;
        } else if (status !== "all" && load.status !== status) {
          return false;
        }
        if (equipmentFilter !== "all" && load.equipment !== equipmentFilter) return false;
        if (!term) return true;
        return [load.load_id, load.customer.name, load.pickup.city, load.delivery.city, load.pickup.zip_code, load.delivery.zip_code]
          .join(" ")
          .toLowerCase()
          .includes(term);
      })
      .map((load) => ({ ...load, recommendation: recommendations[load.load_id] }));
  }, [loads, search, status, equipmentFilter, recommendations]);

  const columnVisibility = useMemo<VisibilityState>(() => {
    const visibility: VisibilityState = {};
    if (status === "active") {
      visibility.carrier_rate_usd = false;
      visibility.margin = false;
      return visibility;
    }
    if (status === "covered" || status === "completed") {
      visibility.estimate = false;
      visibility.topCarrier = false;
      return visibility;
    }
    return visibility;
  }, [status]);

  const table = useReactTable({
    data: rows,
    columns: COLUMNS,
    state: { sorting, columnVisibility },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel()
  });

  const counts = useMemo(() => {
    const completed = loads.filter((load) => load.status === "completed");
    const margins = completed.map((load) => margin(load.customer_rate_usd, load.carrier_rate_usd)).filter((value): value is number => value !== null);
    return {
      active: loads.filter((load) => load.status === "active").length,
      booked: loads.filter((load) => load.status === "covered" || load.status === "in_transit").length,
      completed: completed.length,
      avgMargin: margins.length ? margins.reduce((total, value) => total + value, 0) / margins.length : null
    };
  }, [loads]);

  const lastSync = session.syncs.at(-1);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-base font-medium">Load board</h1>
        <p className="text-[12.5px] text-muted-foreground">
          Every load in this broker's book. Active loads carry a carrier recommendation and an expected cost.
        </p>
      </div>

      <div className="grid grid-cols-2 divide-y divide-x rounded-lg border bg-card sm:grid-cols-4 sm:divide-y-0">
        <Stat label="Needs coverage" value={counts.active} pending={pending} emphasis />
        <Stat label="Booked" value={counts.booked} pending={pending} />
        <Stat label="Completed" value={counts.completed} pending={pending} />
        <Stat
          label="Avg margin, completed"
          value={counts.avgMargin === null ? "—" : money(counts.avgMargin)}
          hint={lastSync ? `last sync ${timestamp(lastSync.synced_at)}` : undefined}
          pending={pending}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search lane, customer, load"
            className="h-8 w-64 pl-8 text-[13px]"
          />
        </div>
        <ToggleGroup type="single" size="sm" value={status} onValueChange={(next) => setStatus((next || "all") as StatusFilter)}>
          {STATUS_FILTERS.map((option) => (
            <ToggleGroupItem key={option.value} value={option.value} className="px-2.5 text-[12px]">
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <Select value={equipmentFilter} onValueChange={setEquipmentFilter}>
          <SelectTrigger size="sm" className="w-40 text-[13px] capitalize">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All equipment</SelectItem>
            {equipmentOptions.map((option) => (
              <SelectItem key={option} value={option} className="capitalize">
                {equipmentLabel(option)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">
          {rows.length} of {loads.length} loads
        </span>
      </div>

      <div className="overflow-hidden rounded-lg border bg-card">
        <Table className="text-[12.5px]">
          <TableHeader className="bg-muted/60">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent">
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} className="h-8 px-2.5">
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {error && (
              <TableRow>
                <TableCell colSpan={table.getVisibleLeafColumns().length} className="h-20 text-center text-muted-foreground">
                  {error}
                </TableCell>
              </TableRow>
            )}
            {!error && pending && (
              <TableRow>
                <TableCell colSpan={table.getVisibleLeafColumns().length} className="h-20 text-center text-muted-foreground">
                  Loading loads
                </TableCell>
              </TableRow>
            )}
            {!error && !pending && table.getRowModel().rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={table.getVisibleLeafColumns().length} className="h-20 text-center text-muted-foreground">
                  No loads match these filters. Clear the search or pick another status.
                </TableCell>
              </TableRow>
            )}
            {!error &&
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  onClick={() => navigate(`/loads/${row.original.load_id}`)}
                  className="cursor-pointer"
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") navigate(`/loads/${row.original.load_id}`);
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className="h-8 px-2.5 py-1.5">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  pending,
  emphasis
}: {
  label: string;
  value: number | string;
  hint?: string;
  pending?: boolean;
  emphasis?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1 px-3.5 py-2.5">
      <ColumnLabel>{label}</ColumnLabel>
      {pending ? <Skeleton className="h-5 w-12" /> : <Num className={cn("text-lg leading-none", emphasis && "text-primary")}>{value}</Num>}
      {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
    </div>
  );
}

function SortHeader({ label, onClick, sorted, align = "left" }: { label: string; onClick: () => void; sorted: false | "asc" | "desc"; align?: "left" | "right" }) {
  const Icon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ChevronsUpDown;
  return (
    <Button
      variant="ghost"
      size="xs"
      onClick={onClick}
      className={cn("-mx-1.5 h-6 gap-1 px-1.5 font-normal", align === "right" && "w-full justify-end")}
    >
      <ColumnLabel>{label}</ColumnLabel>
      <Icon className={cn("size-3", sorted ? "text-foreground" : "text-muted-foreground/50")} />
    </Button>
  );
}

const COLUMNS: ColumnDef<Row>[] = [
  {
    accessorKey: "load_id",
    header: ({ column }) => <SortHeader label="Load" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />,
    cell: ({ row }) => <Num className="text-muted-foreground">{row.original.load_id}</Num>
  },
  {
    accessorKey: "status",
    header: () => <ColumnLabel>Status</ColumnLabel>,
    cell: ({ row }) => <StatusBadge status={row.original.status} />
  },
  {
    id: "lane",
    accessorFn: (row) => `${row.pickup.city} ${row.delivery.city}`,
    header: ({ column }) => <SortHeader label="Lane" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />,
    cell: ({ row }) => (
      <div className="flex items-center gap-2">
        <span className="font-medium">{row.original.pickup.city}</span>
        <span className="text-muted-foreground">to</span>
        <span className="font-medium">{row.original.delivery.city}</span>
      </div>
    )
  },
  {
    accessorKey: "customer",
    accessorFn: (row) => row.customer.name,
    header: ({ column }) => <SortHeader label="Customer" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />,
    cell: ({ row }) => <span className="text-muted-foreground">{row.original.customer.name}</span>
  },
  {
    accessorKey: "equipment",
    header: () => <ColumnLabel>Equipment</ColumnLabel>,
    cell: ({ row }) => <span className="capitalize">{equipmentLabel(row.original.equipment)}</span>
  },
  {
    accessorKey: "distance_miles",
    header: ({ column }) => (
      <SortHeader label="Miles" align="right" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />
    ),
    cell: ({ row }) => <Num className="block text-right">{miles(row.original.distance_miles)}</Num>
  },
  {
    id: "synced",
    accessorFn: (row) => row.synced_at,
    header: ({ column }) => <SortHeader label="Updated" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />,
    cell: ({ row }) => <Num className="text-muted-foreground">{day(row.original.synced_at)}</Num>
  },
  {
    accessorKey: "customer_rate_usd",
    header: ({ column }) => (
      <SortHeader label="Customer rate" align="right" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />
    ),
    cell: ({ row }) => <Num className="block text-right">{money(row.original.customer_rate_usd)}</Num>
  },
  {
    accessorKey: "carrier_rate_usd",
    header: ({ column }) => (
      <SortHeader label="Carrier rate" align="right" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />
    ),
    cell: ({ row }) => <Num className="block text-right">{money(row.original.carrier_rate_usd)}</Num>
  },
  {
    id: "margin",
    accessorFn: (row) => margin(row.customer_rate_usd, row.carrier_rate_usd) ?? Number.NEGATIVE_INFINITY,
    header: ({ column }) => (
      <SortHeader label="Margin" align="right" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")} sorted={column.getIsSorted()} />
    ),
    cell: ({ row }) => {
      const value = margin(row.original.customer_rate_usd, row.original.carrier_rate_usd);
      if (value === null) return <span className="block text-right text-muted-foreground">—</span>;
      return <Num className={cn("block text-right", value >= 0 ? "text-pos" : "text-neg")}>{money(value)}</Num>;
    }
  },
  {
    id: "estimate",
    header: () => <ColumnLabel className="block text-right">Expected cost</ColumnLabel>,
    cell: ({ row }) => {
      if (row.original.status !== "active") return <span className="block text-right text-muted-foreground">—</span>;
      const recommendation = row.original.recommendation;
      if (recommendation === undefined) return <Skeleton className="ml-auto h-4 w-16" />;
      if (recommendation === null) return <span className="block text-right text-muted-foreground">unavailable</span>;
      return (
        <div className="flex items-center justify-end gap-1.5">
          <Num>{money(recommendation.price.point_usd)}</Num>
          <ConfidenceBadge confidence={recommendation.price.confidence} />
        </div>
      );
    }
  },
  {
    id: "topCarrier",
    header: () => <ColumnLabel>Call first</ColumnLabel>,
    cell: ({ row }) => {
      if (row.original.status !== "active") return <span className="text-muted-foreground">—</span>;
      const recommendation = row.original.recommendation;
      if (recommendation === undefined) return <Skeleton className="h-4 w-32" />;
      const best = recommendation?.own_carriers[0];
      if (!best) return <span className="text-muted-foreground">no ranked carrier</span>;
      return (
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{best.carrier_name}</span>
          <Badge variant="secondary" className="font-mono text-[10px] tabular-nums">
            {best.score.toFixed(3)}
          </Badge>
        </div>
      );
    }
  }
];

/**
 * Only active loads need an answer, so the board fetches recommendations for those
 * rows alone, four at a time, and shows skeleton cells until each lands.
 */
function useActiveRecommendations(brokerId: string, loads: LoadSummary[], asOf: string | null, pool: boolean) {
  const [byLoad, setByLoad] = useState<Record<string, Recommendation | null>>({});

  useEffect(() => {
    if (!brokerId) return;
    setByLoad({});
    const queue = loads.filter((load) => load.status === "active").map((load) => load.load_id);
    let cancelled = false;

    async function worker() {
      while (queue.length > 0 && !cancelled) {
        const loadId = queue.shift();
        if (!loadId) return;
        const result = await api.recommendation(brokerId, loadId, asOf, pool).catch(() => null);
        if (!cancelled) setByLoad((current) => ({ ...current, [loadId]: result }));
      }
    }

    void Promise.all(Array.from({ length: 4 }, worker));
    return () => {
      cancelled = true;
    };
  }, [brokerId, loads, asOf, pool]);

  return byLoad;
}
