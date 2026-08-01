import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, useResource } from "../api/client";
import type { LoadDetail } from "../api/types";
import {
  Card,
  ChangeKindPill,
  Empty,
  ErrorNote,
  Field,
  Loading,
  StatusPill,
} from "../components/atoms";
import { CarrierList } from "../components/CarrierList";
import { Coverage } from "../components/Coverage";
import { Eligibility } from "../components/Eligibility";
import { OfferLog } from "../components/OfferLog";
import { PriceEstimateCard } from "../components/PriceEstimateCard";
import {
  EQUIPMENT_LABELS,
  dateTime,
  fieldLabel,
  miles,
  money,
  perMile,
  pounds,
  shortDate,
} from "../format";

export function LoadDetailPage() {
  const { brokerId = "", sourceRef = "" } = useParams();
  // Both engines are exposed side by side rather than the better one silently
  // replacing the other. Switching between them on the same load is the only way
  // to see that the ranking actually changed, and why.
  const [engine, setEngine] = useState("expected-value");
  const load = useResource((signal) => api.load(brokerId, sourceRef, signal), [brokerId, sourceRef]);
  const recommendations = useResource(
    (signal) => api.recommendations(brokerId, sourceRef, engine, signal),
    [brokerId, sourceRef, engine],
  );

  if (load.loading) return <Loading what="load" />;
  if (load.error) return <ErrorNote message={load.error} />;
  if (!load.data) return <Empty>Load not found.</Empty>;

  const detail = load.data;

  return (
    <div className="page">
      <nav className="breadcrumb">
        <Link to={`/brokers/${brokerId}`}>← All loads</Link>
      </nav>

      <header className="load-header">
        <div>
          <h1>
            Load {detail.reference} <StatusPill status={detail.status} />
          </h1>
          <p className="load-subhead">
            {detail.lane_label} · {EQUIPMENT_LABELS[detail.equipment]} ·{" "}
            {miles(detail.distance_miles)} · {detail.customer_name}
          </p>
        </div>
        <dl className="header-money">
          <Field label="Customer pays">{money(detail.customer_rate)}</Field>
          <Field label="Carrier costs">{money(detail.carrier_rate)}</Field>
          <Field label="Margin">{money(detail.margin)}</Field>
        </dl>
      </header>

      <div className="detail-grid">
        <div className="detail-main">
          {detail.status !== "ACTIVE" && (
            <p className="banner">
              This load is <strong>{detail.status === "PLANNED" ? "not yet being covered" : "already covered"}</strong>.
              The recommendations below are shown for reference — the platform is designed to answer
              for loads that are actively looking for a carrier.
            </p>
          )}

          {recommendations.loading && <Loading what="recommendations" />}
          {recommendations.error && <ErrorNote message={recommendations.error} />}

          {recommendations.data && (
            <>
              {recommendations.data.notes.map((note) => (
                <p className="banner banner-warn" key={note}>
                  {note}
                </p>
              ))}

              <PriceEstimateCard
                estimate={recommendations.data.price_estimate}
                customerRate={detail.customer_rate}
                brokerId={brokerId}
              />

              <EngineSwitch engine={engine} onChange={setEngine} />
              {/* Above the list deliberately: whether to cover is decided before who
                  to call, and on a load that should not be covered the list below is
                  the wrong thing to read first. */}
              <Coverage result={recommendations.data} />
              <CarrierList result={recommendations.data} />
              <Eligibility result={recommendations.data} />
            </>
          )}
        </div>

        <aside className="detail-side">
          <LoadFacts detail={detail} />
          <OfferLog detail={detail} />
          <Stops detail={detail} />
          <ChangeLog detail={detail} />
        </aside>
      </div>
    </div>
  );
}

/**
 * Two engines, one contract, identical data. The heuristic scores are ordinal and
 * the expected-value scores are dollars per hour, so they are deliberately not
 * presented as comparable numbers — only the resulting order is comparable.
 */
function EngineSwitch({
  engine,
  onChange,
}: {
  engine: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="engine-switch">
      <span className="engine-switch-label">Ranked by</span>
      {(
        [
          ["expected-value", "Expected value"],
          ["simple-heuristic", "Weighted heuristic"],
        ] as const
      ).map(([key, label]) => (
        <button
          key={key}
          type="button"
          className={engine === key ? "engine-tab engine-tab-active" : "engine-tab"}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function LoadFacts({ detail }: { detail: LoadDetail }) {
  return (
    <Card title="Load details">
      <dl className="fields">
        <Field label="Reference">{detail.reference}</Field>
        <Field label="Customer">{detail.customer_name ?? "—"}</Field>
        <Field label="Equipment">{EQUIPMENT_LABELS[detail.equipment]}</Field>
        {detail.commodity && <Field label="Commodity">{detail.commodity}</Field>}
        <Field label="Weight">{pounds(detail.weight_lbs)}</Field>
        <Field label="Distance">{miles(detail.distance_miles)}</Field>
        <Field label="Booked carrier">{detail.carrier_name ?? "—"}</Field>
        <Field label="Paid rate">
          {money(detail.carrier_rate)}
          {detail.carrier_rate_per_mile != null && (
            <span className="muted"> ({perMile(detail.carrier_rate_per_mile)})</span>
          )}
        </Field>
        <Field label="Source TMS">{detail.source_tms}</Field>
        <Field label="Seen in syncs">{detail.sync_count}</Field>
      </dl>
    </Card>
  );
}

function Stops({ detail }: { detail: LoadDetail }) {
  return (
    <Card
      title="Stops"
      subtitle="Each stop is resolved to a metro market, which is the unit lane history is grouped by."
    >
      <ol className="stops">
        {detail.stops.map((stop) => (
          <li key={stop.sequence} className={`stop stop-${stop.kind.toLowerCase()}`}>
            <div className="stop-kind">{stop.kind.toLowerCase()}</div>
            <div className="stop-place">
              {stop.location_name && <div className="stop-name">{stop.location_name}</div>}
              <div>
                {stop.city}, {stop.state} {stop.postal_code}
              </div>
              <div className="muted">
                {stop.market_label}
                {stop.scheduled_start && ` · scheduled ${shortDate(stop.scheduled_start)}`}
              </div>
              {stop.actual_arrival && (
                <div className="muted">arrived {dateTime(stop.actual_arrival)}</div>
              )}
              {stop.actual_departure && (
                <div className="muted">departed {dateTime(stop.actual_departure)}</div>
              )}
              <OnTimeNote
                onTime={stop.kind === "PICKUP" ? detail.pickup_on_time : detail.delivery_on_time}
              />
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/**
 * Tri-state on purpose: a load still rolling has no outcome yet, which is
 * different from having made it on time.
 */
function OnTimeNote({ onTime }: { onTime: boolean | null }) {
  if (onTime === null) return null;
  return (
    <div className={onTime ? "ontime ontime-good" : "ontime ontime-bad"}>
      {onTime ? "hit the appointment" : "missed the appointment day"}
    </div>
  );
}

/**
 * The audit trail. Freight data is messy and amounts get restated, so the load
 * shows exactly what changed, when, and which sync file said so.
 */
function ChangeLog({ detail }: { detail: LoadDetail }) {
  const corrections = detail.history.filter((entry) => entry.kind === "CORRECTION");

  return (
    <Card
      title="How this load arrived"
      subtitle={
        detail.history.length === 0
          ? "Seen once, never changed."
          : `${detail.history.length} change${detail.history.length > 1 ? "s" : ""} across ${detail.sync_count} syncs` +
            (corrections.length > 0
              ? `, including ${corrections.length} that restated a value already recorded.`
              : ".")
      }
    >
      {detail.history.length === 0 ? (
        <Empty>This load has only ever appeared in one sync.</Empty>
      ) : (
        <ol className="changelog">
          {detail.history.map((entry, index) => (
            <li key={`${entry.field}-${entry.observed_at}-${index}`} className={`change change-${entry.kind.toLowerCase()}`}>
              <div className="change-head">
                <strong>{fieldLabel(entry.field)}</strong>
                <ChangeKindPill kind={entry.kind} />
              </div>
              <div className="change-values">
                <span className="old">{entry.old_value ?? "not set"}</span>
                <span aria-hidden> → </span>
                <span className="new">{entry.new_value ?? "cleared"}</span>
              </div>
              <div className="muted change-meta">
                {dateTime(entry.observed_at)} · {entry.source_file}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
