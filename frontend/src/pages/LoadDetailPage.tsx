import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronRight, TriangleAlert } from "lucide-react";
import { api } from "@/api/client";
import type { CarrierRanking, LoadDetail, PoolCarrierRanking, Recommendation } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from "@/components/ui/breadcrumb";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CarrierEvidence } from "@/components/CarrierEvidence";
import { ContributionBar, ContributionLegend } from "@/components/ContributionBar";
import { LaneMap, LaneMapKey } from "@/components/LaneMap";
import { PriceBand } from "@/components/PriceBand";
import { VersionHistory } from "@/components/VersionHistory";
import { ColumnLabel, ConfidenceBadge, Field, Num, ReasonList, StatusBadge } from "@/components/indicators";
import { componentLabel, equipment as equipmentLabel, evidenceValue, miles, money, place, pounds, timestamp } from "@/format";
import { cn } from "@/lib/utils";
import { useSession } from "@/session";

export function LoadDetailPage() {
  const { loadId = "" } = useParams();
  const session = useSession();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<LoadDetail | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session.brokerId || !loadId) return;
    setDetail(null);
    setError(null);
    void api
      .load(session.brokerId, loadId)
      .then(setDetail)
      .catch(() => navigate("/loads", { replace: true }));
  }, [session.brokerId, loadId, navigate]);

  useEffect(() => {
    if (!session.brokerId || !loadId) return;
    setRecommendation(null);
    void api
      .recommendation(session.brokerId, loadId, session.asOf, session.poolEnabled)
      .then(setRecommendation)
      .catch((cause: Error) => setError(cause.message));
  }, [session.brokerId, loadId, session.asOf, session.poolEnabled]);

  if (!detail) {
    return <Skeleton className="h-64 w-full" />;
  }

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

      <div className="grid gap-3 rounded-lg border bg-card p-4 sm:grid-cols-3 lg:grid-cols-6">
        <Field label="Customer">{detail.customer.name}</Field>
        <Field label="Equipment">
          <span className="capitalize">{equipmentLabel(detail.equipment)}</span>
        </Field>
        <Field label="Pickup">{place(detail.pickup)}</Field>
        <Field label="Delivery">{place(detail.delivery)}</Field>
        <Field label="Distance">
          <Num>{miles(detail.distance_miles)}</Num>
        </Field>
        <Field label="Weight">
          <Num>{pounds(detail.weight_lbs)}</Num>
        </Field>
        <Field label="Pickup window">
          <Num className="text-[12px]">{timestamp(detail.pickup_window.open_at)}</Num>
        </Field>
        <Field label="Delivery window">
          <Num className="text-[12px]">{timestamp(detail.delivery_window.open_at)}</Num>
        </Field>
        <Field label="Customer rate">
          <Num>{money(detail.customer_rate_usd)}</Num>
        </Field>
        <Field label="Carrier rate">
          <Num>{money(detail.carrier_rate_usd)}</Num>
        </Field>
        <Field label="Last sync">
          <Num className="text-[12px]">{timestamp(detail.synced_at)}</Num>
        </Field>
        <Field label="Source file">
          <Num className="text-[10.5px] text-muted-foreground">{detail.source_file.split("/").pop()}</Num>
        </Field>
      </div>

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
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
            <Card size="sm">
              <CardHeader>
                <CardTitle className="flex items-baseline justify-between gap-3">
                  <span>Expected carrier cost</span>
                  <ConfidenceBadge confidence={recommendation.price.confidence} />
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <div className="flex items-baseline gap-2">
                  <Num className="text-3xl leading-none">{money(recommendation.price.point_usd)}</Num>
                  <Num className="text-muted-foreground">{recommendation.price.point_ppm.toFixed(2)}/mi</Num>
                </div>
                <PriceBand price={recommendation.price} />
                <div className="flex flex-wrap gap-1.5">
                  <Badge variant="secondary" className="font-mono text-[10px]">
                    basis {componentLabel(recommendation.price.basis)}
                  </Badge>
                  <Badge variant="secondary" className="font-mono text-[10px] tabular-nums">
                    {recommendation.price.effective_loads.toFixed(1)} effective loads
                  </Badge>
                </div>
              </CardContent>
            </Card>

            <Card size="sm">
              <CardHeader>
                <CardTitle>How this estimate was built</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <ReasonList label="Reasoning" items={recommendation.price.reasons} />
                <ReasonList label="Limitations" items={recommendation.price.limitations} tone="caution" />
                {recommendation.price.comparables.length > 0 && <ComparablesTable price={recommendation.price} />}
              </CardContent>
            </Card>
          </div>

          <CarrierTable carriers={recommendation.own_carriers} brokerName={session.broker?.name ?? ""} />

          {session.poolEnabled && <PoolTable carriers={recommendation.pool_carriers} />}
        </>
      )}

      <Separator />
      <VersionHistory versions={detail.versions} />
    </div>
  );
}

function ComparablesTable({ price }: { price: Recommendation["price"] }) {
  return (
    <div className="flex flex-col gap-1.5">
      <ColumnLabel>Comparable loads ({price.comparables.length})</ColumnLabel>
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
                <ColumnLabel>Similarity</ColumnLabel>
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

function carrierPrice(carrier: CarrierRanking) {
  const value = carrier.components.find((component) => component.name === "price")?.evidence.point_usd;
  return typeof value === "number" ? value : null;
}

function CarrierTable({ carriers, brokerName }: { carriers: CarrierRanking[]; brokerName: string }) {
  const [expanded, setExpanded] = useState<string | null>(carriers[0]?.carrier_id ?? null);
  const legend = useMemo(() => carriers[0]?.components ?? [], [carriers]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[13px] font-medium">Call these carriers first</h2>
          <p className="text-[12px] text-muted-foreground">
            Ranked from {brokerName}'s own history only. The bar is the score, split into the components that earned it.
          </p>
        </div>
        {legend.length > 0 && <ContributionLegend components={legend} />}
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
              <TableHead className="h-8 w-20 px-2.5 text-right">
                <ColumnLabel>Score</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 min-w-56 px-2.5">
                <ColumnLabel>Score composition</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 px-2.5 text-right">
                <ColumnLabel>Their price</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 px-2.5">
                <ColumnLabel>Confidence</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 w-8 px-2.5" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {carriers.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="h-16 text-center text-muted-foreground">
                  No carrier in this broker's history matches this load yet.
                </TableCell>
              </TableRow>
            )}
            {carriers.map((carrier, index) => {
              const open = expanded === carrier.carrier_id;
              return [
                <TableRow
                  key={carrier.carrier_id}
                  aria-expanded={open}
                  tabIndex={0}
                  className="cursor-pointer"
                  onClick={() => setExpanded(open ? null : carrier.carrier_id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setExpanded(open ? null : carrier.carrier_id);
                    }
                  }}
                >
                  <TableCell className="px-2.5 py-2">
                    <Num className={cn("text-muted-foreground", index === 0 && "font-medium text-primary")}>{index + 1}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2">
                    <span className="font-medium">{carrier.carrier_name}</span>
                    <Num className="ml-2 text-[10.5px] text-muted-foreground">{carrier.carrier_id}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2 text-right">
                    <Num className="font-medium">{carrier.score.toFixed(3)}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2">
                    <ContributionBar components={carrier.components} />
                  </TableCell>
                  <TableCell className="px-2.5 py-2 text-right">
                    <Num>{money(carrierPrice(carrier))}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2">
                    <ConfidenceBadge confidence={carrier.confidence} />
                  </TableCell>
                  <TableCell className="px-2.5 py-2">
                    <ChevronRight className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-90")} />
                  </TableCell>
                </TableRow>,
                open ? (
                  <TableRow key={`${carrier.carrier_id}-evidence`} className="hover:bg-transparent">
                    <TableCell colSpan={7} className="p-0 whitespace-normal">
                      <CarrierEvidence
                        components={carrier.components}
                        geometry={carrier.geometry}
                        reasons={carrier.reasons}
                        limitations={carrier.limitations}
                      />
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

function PoolTable({ carriers }: { carriers: PoolCarrierRanking[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-2">
      <div>
        <h2 className="flex items-center gap-2 text-[13px] font-medium">
          Shared pool tier
          <Badge variant="outline" className="font-normal">
            other brokers
          </Badge>
        </h2>
        <p className="text-[12px] text-muted-foreground">
          Carriers this broker has never used, contributed by opted-in brokers as bucketed data. No other broker's rates or load records cross
          the boundary.
        </p>
      </div>

      <div className="overflow-hidden rounded-lg border border-l-2 border-l-dashed border-l-primary/40 bg-card">
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
                <ColumnLabel>Contributed by</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 w-20 px-2.5 text-right">
                <ColumnLabel>Score</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 px-2.5 text-right">
                <ColumnLabel>Expected cost</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 px-2.5">
                <ColumnLabel>Confidence</ColumnLabel>
              </TableHead>
              <TableHead className="h-8 w-8 px-2.5" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {carriers.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="h-16 text-center text-muted-foreground">
                  No eligible pool carriers for this load.
                </TableCell>
              </TableRow>
            )}
            {carriers.map((carrier, index) => {
              const key = `${carrier.contributor_broker_id}:${carrier.carrier_id}`;
              const open = expanded === key;
              return [
                <TableRow
                  key={key}
                  aria-expanded={open}
                  tabIndex={0}
                  className="cursor-pointer"
                  onClick={() => setExpanded(open ? null : key)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setExpanded(open ? null : key);
                    }
                  }}
                >
                  <TableCell className="px-2.5 py-2">
                    <Num className="text-muted-foreground">P{index + 1}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2 font-medium">{carrier.carrier_name}</TableCell>
                  <TableCell className="px-2.5 py-2 text-muted-foreground">{carrier.contributor_broker_name}</TableCell>
                  <TableCell className="px-2.5 py-2 text-right">
                    <Num>{carrier.score.toFixed(3)}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2 text-right">
                    <Num>{money(carrier.expected_carrier_cost_usd)}</Num>
                  </TableCell>
                  <TableCell className="px-2.5 py-2">
                    <ConfidenceBadge confidence={carrier.confidence} />
                  </TableCell>
                  <TableCell className="px-2.5 py-2">
                    <ChevronRight className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-90")} />
                  </TableCell>
                </TableRow>,
                open ? (
                  <TableRow key={`${key}-evidence`} className="hover:bg-transparent">
                    <TableCell colSpan={7} className="p-0 whitespace-normal">
                      <div className="grid gap-5 border-t bg-muted/30 p-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
                        <div className="flex flex-col gap-4">
                          <div className="grid gap-4 sm:grid-cols-2">
                            <ReasonList label="Why this carrier" items={carrier.reasons} />
                            <ReasonList label="What we don't know" items={carrier.limitations} tone="caution" />
                          </div>
                          <div className="flex flex-col gap-1.5">
                            <ColumnLabel>Everything that crossed the boundary</ColumnLabel>
                            <div className="overflow-hidden rounded-md border bg-card">
                              <Table className="text-[11.5px]">
                                <TableBody>
                                  {Object.entries(carrier.payload).map(([key, value]) => (
                                    <TableRow key={key}>
                                      <TableCell className="w-40 px-2 py-1">
                                        <ColumnLabel>{componentLabel(key)}</ColumnLabel>
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
                        <div className="flex flex-col gap-2 rounded-md border bg-card p-3">
                          <ColumnLabel>Lane trace</ColumnLabel>
                          <LaneMap geometry={carrier.geometry} />
                          <LaneMapKey />
                        </div>
                      </div>
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
