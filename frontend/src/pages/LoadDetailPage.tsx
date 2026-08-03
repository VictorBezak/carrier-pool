import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, TriangleAlert } from "lucide-react";
import { api } from "@/api/client";
import type { CarrierRanking, LoadDetail, PoolCarrierRanking, Recommendation } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CarrierCompositionChart } from "@/charts/CarrierCompositionChart";
import { LaneGeoMap } from "@/charts/LaneGeoMap";
import { PriceRangeChart } from "@/charts/PriceRangeChart";
import { CarrierEvidence } from "@/components/CarrierEvidence";
import { VersionHistory } from "@/components/VersionHistory";
import { ColumnLabel, ConfidenceBadge, Num, ReasonList, StatusBadge } from "@/components/indicators";
import { equipment as equipmentLabel, evidenceValue, margin, miles, money, percent, place, pounds, timestamp } from "@/format";
import { basisName, evidenceName, matchScore, priceStory } from "@/labels";
import { cn } from "@/lib/utils";
import { useSession } from "@/session";

export function LoadDetailPage() {
  const { loadId = "" } = useParams();
  const session = useSession();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<LoadDetail | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [selectedCarrierKey, setSelectedCarrierKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const carrierRows = useMemo(() => buildCarrierRows(recommendation), [recommendation]);

  useEffect(() => {
    if (!session.brokerId || !loadId) return;
    setDetail(null);
    setError(null);
    void api
      .load(session.brokerId, loadId, session.asOf)
      .then(setDetail)
      .catch(() => navigate("/loads", { replace: true }));
  }, [session.brokerId, loadId, session.asOf, navigate]);

  useEffect(() => {
    if (!session.brokerId || !loadId) return;
    setRecommendation(null);
    setError(null);
    void api
      .recommendation(session.brokerId, loadId, session.asOf, session.poolEnabled)
      .then(setRecommendation)
      .catch((cause: Error) => setError(cause.message));
  }, [session.brokerId, loadId, session.asOf, session.poolEnabled]);

  useEffect(() => {
    setSelectedCarrierKey(carrierRows[0]?.key ?? null);
  }, [carrierRows]);

  if (!detail) {
    return <Skeleton className="h-64 w-full" />;
  }

  const selectedCarrierRow = carrierRows.find((row) => row.key === selectedCarrierKey) ?? carrierRows[0] ?? null;
  const selectedCarrierName = selectedCarrierRow?.carrier.carrier_name ?? null;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Breadcrumb>
          <BreadcrumbList className="text-[12px]">
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/loads">Load board</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage className="font-mono">{detail.load_id}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-base font-medium">
            {detail.pickup.city} <span className="font-normal text-muted-foreground">to</span> {detail.delivery.city}
          </h1>
          <StatusBadge status={detail.status} />
          {session.asOf && (
            <Badge variant="outline" className="border-dev/40 bg-dev-surface text-dev-foreground">
              replayed as of {timestamp(session.asOf)}
            </Badge>
          )}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border bg-card">
        <div className="flex flex-wrap items-start justify-between gap-x-10 gap-y-5 p-4">
          <div className="flex flex-wrap items-start gap-4">
            <Stop label="Pickup" location={place(detail.pickup)} appointment={detail.pickup_window.open_at} />
            <ArrowRight className="mt-[26px] size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <Stop label="Delivery" location={place(detail.delivery)} appointment={detail.delivery_window.open_at} />
          </div>

          <div className="flex flex-wrap items-start gap-x-10 gap-y-5">
            <PrimaryField label="Equipment">
              <span className="capitalize">{equipmentLabel(detail.equipment)}</span>
            </PrimaryField>
            <PrimaryField label="Customer rate">
              <Num>{money(detail.customer_rate_usd)}</Num>
            </PrimaryField>
          </div>
        </div>

        <div className="grid gap-3 border-t bg-muted/30 px-4 py-3 sm:grid-cols-3 lg:grid-cols-6">
          <SecondaryField label="Customer">{detail.customer.name}</SecondaryField>
          <SecondaryField label="Weight">
            <Num>{pounds(detail.weight_lbs)}</Num>
          </SecondaryField>
          <SecondaryField label="Miles">
            <Num>{miles(detail.distance_miles)}</Num>
          </SecondaryField>
          <SecondaryField label="Carrier rate">
            <Num>{money(detail.carrier_rate_usd)}</Num>
          </SecondaryField>
          <SecondaryField label="Updated">
            <Num>{timestamp(detail.synced_at)}</Num>
          </SecondaryField>
          <SecondaryField label="Source file">
            <Num className="text-[10.5px]">{detail.source_file.split("/").pop()}</Num>
          </SecondaryField>
        </div>
      </div>

      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button variant="outline" size="sm" className="w-fit">
            Sync history
            <Badge variant="secondary" className="font-mono text-[10px]">
              {historySummary(detail.versions)}
            </Badge>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="pt-3">
          <VersionHistory versions={detail.versions} />
        </CollapsibleContent>
      </Collapsible>

      {error && (
        <Alert variant="destructive">
          <TriangleAlert />
          <AlertTitle>No recommendation for this load</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!error && !recommendation && <Skeleton className="h-72 w-full" />}

      {recommendation && (
        <>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <Card size="sm">
              <CardHeader>
                <CardTitle className="flex items-baseline justify-between gap-3">
                  <span>Expected cost to book this load</span>
                  <ConfidenceBadge confidence={recommendation.price.confidence} />
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <div className="flex items-baseline gap-2">
                  <Num className="text-3xl leading-none">{money(recommendation.price.point_usd)}</Num>
                </div>
                <p className="text-[12.5px] leading-relaxed text-muted-foreground">{priceStory(recommendation.price, detail)}</p>
                <PriceRangeChart price={recommendation.price} detail={detail} />
                <PriceMath price={recommendation.price} />
              </CardContent>
            </Card>

            <Card size="sm">
              <CardHeader>
                <CardTitle>Carrier comparison</CardTitle>
              </CardHeader>
              <CardContent className="min-h-[270px]">
                <CarrierCompositionChart
                  carriers={recommendation.own_carriers}
                  selectedCarrierId={selectedCarrierRow?.kind === "local" ? selectedCarrierRow.carrier.carrier_id : null}
                />
              </CardContent>
            </Card>
          </div>

          <CombinedCarrierTable
            rows={carrierRows}
            customerRate={detail.customer_rate_usd}
            selectedRowKey={selectedCarrierRow?.key ?? null}
            onSelectRow={setSelectedCarrierKey}
          />

          <Card size="sm">
            <CardHeader>
              <CardTitle>{selectedCarrierName ? `${selectedCarrierName}'s lane history` : "Lane history"}</CardTitle>
            </CardHeader>
            <CardContent className="flex h-[360px] flex-col gap-2">
              {selectedCarrierRow ? (
                <>
                  <div className="min-h-0 flex-1">
                    <LaneGeoMap geometry={selectedCarrierRow.carrier.geometry} />
                  </div>
                  {selectedCarrierRow.kind === "pool" && (
                    <p className="text-[12px] text-muted-foreground">Pool carriers share bucketed lane cells, not raw historical lanes.</p>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">Select a carrier to see lane history.</p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

/**
 * The details a coverage desk reads before it picks up the phone: where the truck has to
 * be and when, what trailer it needs, and what the load pays. Everything else on the load
 * is context and sits in the muted strip below.
 */
function Stop({ label, location, appointment }: { label: string; location: string; appointment: string | null }) {
  return (
    <div className="flex flex-col gap-1">
      <ColumnLabel>{label}</ColumnLabel>
      <div className="text-[15px] font-medium">{location}</div>
      <Num className="text-[12px] text-muted-foreground">{timestamp(appointment)}</Num>
    </div>
  );
}

function PrimaryField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <ColumnLabel>{label}</ColumnLabel>
      <div className="text-[15px] font-medium">{children}</div>
    </div>
  );
}

function SecondaryField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <ColumnLabel>{label}</ColumnLabel>
      <div className="text-[12px] text-muted-foreground">{children}</div>
    </div>
  );
}

function PriceMath({ price }: { price: Recommendation["price"] }) {
  return (
    <Collapsible>
      <CollapsibleTrigger asChild>
        <Button variant="outline" size="sm" className="w-fit">
          Show reasoning
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-3 flex flex-col gap-4">
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="secondary" className="font-mono text-[10px]">
            {basisName(price.basis)}
          </Badge>
          <Badge variant="secondary" className="font-mono text-[10px] tabular-nums">
            {price.effective_loads.toFixed(1)} comparable loads
          </Badge>
          <Badge variant="secondary" className="font-mono text-[10px] tabular-nums">
            {price.point_ppm.toFixed(2)}/mi
          </Badge>
        </div>
        <ReasonList label="Why this price" items={price.reasons} />
        <ReasonList label="Watch-outs" items={price.limitations} tone="caution" />
        {price.comparables.length > 0 && <ComparablesTable price={price} />}
      </CollapsibleContent>
    </Collapsible>
  );
}

function ComparablesTable({ price }: { price: Recommendation["price"] }) {
  return (
    <div className="flex flex-col gap-1.5">
      <ColumnLabel>Past loads used for pricing ({price.comparables.length})</ColumnLabel>
      <div className="overflow-hidden rounded-md border">
        <Table className="text-[11.5px]">
          <TableHeader className="bg-muted/60">
            <TableRow className="hover:bg-transparent">
              <TableHead className="h-7 px-2">
                <ColumnLabel>Load</ColumnLabel>
              </TableHead>
              <TableHead className="h-7 px-2">
                <ColumnLabel>Lane</ColumnLabel>
              </TableHead>
              <TableHead className="h-7 px-2 text-right">
                <ColumnLabel>Fit</ColumnLabel>
              </TableHead>
              <TableHead className="h-7 px-2 text-right">
                <ColumnLabel>Rate/mi</ColumnLabel>
              </TableHead>
              <TableHead className="h-7 px-2 text-right">
                <ColumnLabel>Paid</ColumnLabel>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {price.comparables.map((comparable) => (
              <TableRow key={`${comparable.load_id}-${comparable.source_file}`}>
                <TableCell className="px-2 py-1">
                  <Num className="text-muted-foreground">{comparable.load_id}</Num>
                </TableCell>
                <TableCell className="px-2 py-1">
                  {comparable.origin} to {comparable.destination}
                </TableCell>
                <TableCell className="px-2 py-1 text-right">
                  <Num className="text-muted-foreground">{comparable.weight.toFixed(2)}</Num>
                </TableCell>
                <TableCell className="px-2 py-1 text-right">
                  <Num>{comparable.ppm.toFixed(2)}</Num>
                </TableCell>
                <TableCell className="px-2 py-1 text-right">
                  <Num>{money(comparable.carrier_rate_usd)}</Num>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

type CombinedCarrierRow =
  | { kind: "local"; key: string; rankLabel: string; carrier: CarrierRanking }
  | { kind: "pool"; key: string; rankLabel: string; carrier: PoolCarrierRanking };

function buildCarrierRows(recommendation: Recommendation | null): CombinedCarrierRow[] {
  if (!recommendation) return [];
  const localRows = recommendation.own_carriers.map((carrier) => ({
    kind: "local" as const,
    key: `local:${carrier.carrier_id}`,
    rankLabel: "",
    carrier
  }));
  const poolRows = recommendation.pool_carriers.map((carrier, index) => ({
    kind: "pool" as const,
    key: `pool:${index}:${carrier.carrier_id}`,
    rankLabel: "",
    carrier
  }));
  return [...localRows, ...poolRows]
    .sort(compareCarrierRows)
    .map((row, index) => ({ ...row, rankLabel: String(index + 1) }));
}

function carrierPrice(carrier: CarrierRanking) {
  const value = carrier.components.find((component) => component.name === "price")?.evidence.point_usd;
  return typeof value === "number" ? value : null;
}

function rowPrice(row: CombinedCarrierRow) {
  return row.kind === "local" ? carrierPrice(row.carrier) : row.carrier.expected_carrier_cost_usd;
}

function rowSource(row: CombinedCarrierRow) {
  if (row.kind === "pool") return "Shared pool";
  return row.carrier.pooled ? "Your network + pool facts" : "Your network";
}

/**
 * Empty miles is the heaviest component in the score and the number a carrier prices its
 * quote around, so it earns a column of its own rather than living inside the reasoning.
 * Null means no position on record, which is a different statement than zero.
 */
function rowDeadheadMiles(row: CombinedCarrierRow) {
  const value = row.carrier.components.find((component) => component.name === "positioning")?.evidence.expected_deadhead_miles;
  return typeof value === "number" ? value : null;
}

function compareCarrierRows(a: CombinedCarrierRow, b: CombinedCarrierRow) {
  const scoreDelta = b.carrier.score - a.carrier.score;
  if (scoreDelta !== 0) return scoreDelta;
  const confidenceDelta = confidenceRank(b.carrier.confidence) - confidenceRank(a.carrier.confidence);
  if (confidenceDelta !== 0) return confidenceDelta;
  if (a.kind !== b.kind) return a.kind === "local" ? -1 : 1;
  return a.carrier.carrier_name.localeCompare(b.carrier.carrier_name);
}

function confidenceRank(value: CarrierRanking["confidence"]) {
  return { high: 3, medium: 2, low: 1 }[value];
}

function CombinedCarrierTable({
  rows,
  customerRate,
  selectedRowKey,
  onSelectRow
}: {
  rows: CombinedCarrierRow[];
  customerRate: number | null;
  selectedRowKey: string | null;
  onSelectRow: (rowKey: string) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[13px] font-medium">Call these carriers first</h2>
          <p className="text-[12px] text-muted-foreground">
            Ranked by empty miles, lane history, price, and on-time record. Select a carrier to update the lane map.
            Rankings come from synced TMS data that may be stale or incomplete — always confirm equipment availability
            with the carrier before booking.
          </p>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border bg-card">
        <Table className="text-[12.5px]">
          <TableHeader className="bg-muted/60">
            <TableRow className="hover:bg-transparent">
              <TableHead className="h-8 w-10 px-2.5">
                <ColumnLabel>#</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 px-2.5">
                <ColumnLabel>Carrier</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 px-2.5">
                <ColumnLabel>Source</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 w-20 px-2.5 text-right">
                <ColumnLabel>Match</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 px-2.5 text-right">
                <ColumnLabel>Empty miles</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 px-2.5 text-right">
                <ColumnLabel>Expected cost</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 px-2.5 text-right">
                <ColumnLabel>Est. margin</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 px-2.5">
                <ColumnLabel>Confidence</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 w-8 px-2.5" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="h-16 text-center text-muted-foreground">
                  No carrier in this broker's history matches this load yet.
                </TableCell>
              </TableRow>
            )}
            {rows.map((row) => {
              const carrier = row.carrier;
              const open = expanded === row.key;
              const deadhead = rowDeadheadMiles(row);
              const rowMargin = margin(customerRate, rowPrice(row));
              return [
                <TableRow
                  key={row.key}
                  aria-expanded={open}
                  tabIndex={0}
                  className="cursor-pointer"
                  onClick={() => onSelectRow(row.key)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      onSelectRow(row.key);
                    }
                  }}
                  data-state={selectedRowKey === row.key ? "selected" : undefined}
                >
                  <TableCell className="px-2.5 py-2">
                    <Num className={cn("text-muted-foreground", row.rankLabel === "1" && "font-medium text-primary")}>{row.rankLabel}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2">
                    <span className="font-medium">{carrier.carrier_name}</span>
                    {row.kind === "local" && row.carrier.pooled && (
                      <Badge variant="outline" className="ml-2 border-primary/30 font-normal text-[10px]">
                        pooled facts
                      </Badge>
                    )}
                    {row.kind === "pool" && (
                      <Badge variant="outline" className="ml-2 border-primary/30 font-normal text-[10px]">
                        shared pool
                      </Badge>
                    )}
                    <Num className="ml-2 text-[10.5px] text-muted-foreground">{carrier.carrier_id}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2">
                    <span className="flex flex-col gap-0.5">
                      <span>{rowSource(row)}</span>
                    </span>
                  </TableCell>
                  <TableCell className="px-2.5 py-2 text-right">
                    <Num className="font-medium">{matchScore(carrier.score)}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2 text-right">
                    <Num className={cn(deadhead === null && "text-muted-foreground")}>{deadhead === null ? "—" : miles(deadhead)}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2 text-right">
                    <Num>{money(rowPrice(row))}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2 text-right">
                    <Num>{money(rowMargin)}</Num>
                    {rowMargin !== null && customerRate !== null && (
                      <Num className="ml-1.5 text-[10.5px] text-muted-foreground">{percent(rowMargin / customerRate)}</Num>
                    )}
                  </TableCell>
                  <TableCell className="px-2.5 py-2">
                    <ConfidenceBadge confidence={carrier.confidence} />
                  </TableCell>
                  <TableCell className="px-2.5 py-2">
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={(event) => {
                        event.stopPropagation();
                        setExpanded(open ? null : row.key);
                      }}
                    >
                      Reasoning
                    </Button>
                  </TableCell>
                </TableRow>,
                open ? (
                  <TableRow key={`${row.key}-evidence`} className="hover:bg-transparent">
                    <TableCell colSpan={9} className="p-0 whitespace-normal">
                      {row.kind === "local" ? (
                        <CarrierEvidence
                          components={row.carrier.components}
                          reasons={row.carrier.reasons}
                          limitations={row.carrier.limitations}
                        />
                      ) : (
                        <PoolEvidence carrier={row.carrier} />
                      )}
                    </TableCell>
                  </TableRow>
                ) : null
              ];
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function PoolEvidence({ carrier }: { carrier: PoolCarrierRanking }) {
  return (
    <div>
      <CarrierEvidence components={carrier.components} reasons={carrier.reasons} limitations={carrier.limitations} />
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5 border-t bg-muted/30 p-4">
          <ColumnLabel>Everything that crossed the boundary</ColumnLabel>
          <div className="overflow-hidden rounded-md border bg-card">
            <Table className="text-[11.5px]">
              <TableBody>
                {Object.entries(carrier.payload).map(([key, value]) => (
                  <TableRow key={key}>
                    <TableCell className="w-40 px-2 py-1">
                      <ColumnLabel>{evidenceName(key)}</ColumnLabel>
                    </TableCell>
                    <TableCell className="px-2 py-1">
                      <Num>{Array.isArray(value) ? value.join(", ") || "—" : evidenceValue(value ?? null)}</Num>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
    </div>
  );
}

function historySummary(versions: LoadDetail["versions"]) {
  if (versions.length <= 1) return "1 update";
  let corrections = 0;
  for (let index = 1; index < versions.length; index += 1) {
    const previous = versions[index - 1];
    const current = versions[index];
    if (previous.carrier_rate_usd !== current.carrier_rate_usd && previous.carrier_rate_usd !== null) corrections += 1;
    if (previous.customer_rate_usd !== current.customer_rate_usd && previous.customer_rate_usd !== null) corrections += 1;
  }
  return corrections > 0 ? `${versions.length} updates, ${corrections} rate correction${corrections === 1 ? "" : "s"}` : `${versions.length} updates`;
}
