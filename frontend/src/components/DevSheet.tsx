import { useEffect, useState } from "react";
import { FlaskConical, RotateCcw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { ColumnLabel } from "@/components/indicators";
import { timestamp } from "@/format";
import { useSession } from "@/session";

const OPEN_KEY = "carrier-pool.dev-tools-open";

export function DevSheet() {
  const session = useSession();
  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) === "true");

  useEffect(() => {
    localStorage.setItem(OPEN_KEY, String(open));
  }, [open]);

  const asOfIndex = session.asOf ? session.syncs.findIndex((sync) => sync.synced_at === session.asOf) : session.syncs.length;

  return (
    <Sheet open={open} onOpenChange={setOpen} modal={false}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="sm" className="border border-dashed border-dev/50 text-dev hover:bg-dev-surface hover:text-dev">
          <FlaskConical />
          Dev tools
        </Button>
      </SheetTrigger>
      <SheetContent
        side="right"
        overlay={false}
        onInteractOutside={(event) => event.preventDefault()}
        className="w-full gap-0 sm:max-w-md"
      >
        <SheetHeader className="border-b border-dashed border-dev/40 bg-dev-surface">
          <SheetTitle className="flex items-center gap-2 text-dev-foreground">
            <FlaskConical className="size-4" />
            Dev tools
          </SheetTitle>
          <SheetDescription>Not part of the broker-facing product. Nothing here changes what a broker can see.</SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="flex flex-col gap-6 p-4">
            <section className="flex flex-col gap-2">
              <ColumnLabel>View as broker</ColumnLabel>
              <p className="text-[12px] text-muted-foreground">
                Impersonates a tenant. Each broker only ever sees answers derived from its own data.
              </p>
              <Select value={session.brokerId} onValueChange={session.viewAs}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select a broker" />
                </SelectTrigger>
                <SelectContent>
                  {session.brokers.map((broker) => (
                    <SelectItem key={broker.broker_id} value={broker.broker_id}>
                      <span className="truncate">{broker.name}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </section>

            <Separator />

            <section className="flex flex-col gap-3">
              <div className="flex items-baseline justify-between">
                <ColumnLabel>As-of replay</ColumnLabel>
                <span className="font-mono text-[11px] tabular-nums">
                  {session.asOf ? timestamp(session.asOf) : "live"}
                </span>
              </div>
              <p className="text-[12px] text-muted-foreground">
                Rewinds to an earlier sync and recomputes every ranking from only the history known at that moment.
              </p>
              <Slider
                min={0}
                max={Math.max(session.syncs.length, 1)}
                step={1}
                value={[asOfIndex < 0 ? session.syncs.length : asOfIndex]}
                onValueChange={([next]) => session.setAsOf(next >= session.syncs.length ? null : session.syncs[next].synced_at)}
              />
              <div className="flex justify-between font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
                <span>{session.syncs.length > 0 ? timestamp(session.syncs[0].synced_at) : "no syncs"}</span>
                <span>live</span>
              </div>
              {session.asOf && (
                <Button variant="ghost" size="xs" className="self-start text-dev hover:bg-dev-surface hover:text-dev" onClick={() => session.setAsOf(null)}>
                  <RotateCcw />
                  Return to live
                </Button>
              )}
            </section>

            <Separator />

            <section className="flex flex-col gap-3">
              <div className="flex items-center justify-between gap-3">
                <ColumnLabel>Shared carrier pool</ColumnLabel>
                <Switch
                  checked={session.poolEnabled}
                  disabled={!session.poolEligible}
                  onCheckedChange={(checked) => void session.setPoolOptIn(checked)}
                />
              </div>
              {session.poolEligible ? (
                <p className="text-[12px] text-muted-foreground">
                  Opted-in carriers from other brokers appear as a separate, clearly labelled tier on each load.
                </p>
              ) : (
                <p className="text-[12px] text-muted-foreground">
                  {(session.broker && session.poolPolicy?.ineligible_brokers[session.broker.broker_id]) ?? "Pool unavailable for this broker."}
                </p>
              )}
              {session.poolPolicy && (
                <div className="flex flex-col gap-2 rounded-md border bg-card p-3">
                  <ColumnLabel>Crosses the boundary</ColumnLabel>
                  <div className="flex flex-wrap gap-1">
                    {session.poolPolicy.fields.map((field) => (
                      <Badge key={field} variant="secondary" className="font-mono text-[10px]">
                        {field}
                      </Badge>
                    ))}
                  </div>
                  <ColumnLabel>Never shared</ColumnLabel>
                  <div className="flex flex-wrap gap-1">
                    {session.poolPolicy.never_shared.map((field) => (
                      <Badge key={field} variant="outline" className="border-neg/30 bg-neg/5 font-mono text-[10px] text-neg">
                        {field}
                      </Badge>
                    ))}
                  </div>
                  <p className="text-[11.5px] leading-relaxed text-muted-foreground">{session.poolPolicy.matching_rule}</p>
                </div>
              )}
            </section>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
