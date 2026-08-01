import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, useResource } from "../api/client";
import { Bench, CallCard } from "../components/CallCard";
import { Empty, ErrorNote, Loading, StatusPill } from "../components/atoms";
import { ShowTheWork, type WorkTab } from "../components/ShowTheWork";
import { Verdict } from "../components/Verdict";
import { EQUIPMENT_LABELS, miles, money, shortDate } from "../format";

/**
 * One load, one answer.
 *
 * The page reads top to bottom as the decision a dispatcher actually makes: is this
 * worth covering, who do I ring, what do I say, and then — only if they want it — how
 * do you know. Everything that used to sit at the same visual weight as the answer is
 * still here, behind one entry point rather than eighteen.
 */
export function LoadDetailPage() {
  const { brokerId = "", sourceRef = "" } = useParams();
  const [engine, setEngine] = useState("expected-value");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [work, setWork] = useState<WorkTab | null>(null);

  const load = useResource(
    (signal) => api.load(brokerId, sourceRef, signal),
    [brokerId, sourceRef],
  );
  const recommendations = useResource(
    (signal) => api.recommendations(brokerId, sourceRef, engine, signal),
    [brokerId, sourceRef, engine],
  );

  // Switching engines can reorder or drop carriers, so a pinned selection has to be
  // released rather than left pointing at someone who is no longer ranked.
  const carriers = recommendations.data?.carriers ?? [];
  useEffect(() => {
    if (selectedId && !carriers.some((carrier) => carrier.carrier_id === selectedId)) {
      setSelectedId(null);
    }
  }, [carriers, selectedId]);

  if (load.loading) return <Loading what="load" />;
  if (load.error) return <ErrorNote message={load.error} />;
  if (!load.data) return <Empty>Load not found.</Empty>;

  const detail = load.data;
  const result = recommendations.data;

  // On a load that should be repriced, the card follows the verdict rather than the
  // ranking. They name different carriers on purpose: expected value on a losing load
  // favours whoever is least likely to accept, while the repricing target is whoever
  // is cheapest to make viable. Showing the ranking's leader next to a verdict naming
  // someone else just reads as the page contradicting itself.
  const repriceTarget = result?.coverage?.target?.carrier_id;
  const lead =
    carriers.find((carrier) => carrier.carrier_id === selectedId) ??
    carriers.find((carrier) => carrier.carrier_id === repriceTarget) ??
    carriers[0];
  const rest = carriers.filter((carrier) => carrier.carrier_id !== lead?.carrier_id);

  return (
    <div className="sheetpage">
      <nav className="crumb">
        <Link to={`/brokers/${brokerId}`}>← All loads</Link>
      </nav>

      <header className="loadhead">
        <h1>{detail.lane_label}</h1>
        <p className="loadhead-meta">
          <span className="fig">{detail.reference}</span>
          <span>{EQUIPMENT_LABELS[detail.equipment]}</span>
          <span>{miles(detail.distance_miles)}</span>
          {detail.pickup_at && <span>picks up {shortDate(detail.pickup_at)}</span>}
          {detail.customer_name && <span>{detail.customer_name}</span>}
          <StatusPill status={detail.status} />
        </p>
        {detail.customer_rate != null && (
          <p className="loadhead-rate">
            <span className="eyebrow">Customer pays</span>
            <span className="fig">{money(detail.customer_rate)}</span>
          </p>
        )}
      </header>

      {detail.status !== "ACTIVE" && (
        <p className="notice">
          This load is{" "}
          <strong>{detail.status === "PLANNED" ? "not yet being covered" : "already covered"}</strong>
          . What follows is shown for reference — the platform answers for loads actively looking
          for a truck.
        </p>
      )}

      {recommendations.loading && <Loading what="the recommendation" />}
      {recommendations.error && <ErrorNote message={recommendations.error} />}

      {result && (
        <>
          <Verdict result={result} />

          {lead ? (
            <CallCard carrier={lead} result={result} onShowWork={() => setWork("call")} />
          ) : (
            <Empty>
              No carrier can haul this load. Everyone this broker works with was ruled out — the
              reasons are in the work.
            </Empty>
          )}

          <Bench
            carriers={rest}
            selectedId={lead?.carrier_id ?? ""}
            onSelect={(carrierId) => setSelectedId(carrierId)}
          />

          <div className="workbar">
            <button type="button" className="workbar-btn" onClick={() => setWork("ruled-out")}>
              {result.exclusions.length > 0
                ? `${result.exclusions.length} ruled out`
                : "Nobody ruled out"}
              {result.unchecked_gates.length > 0 && (
                <> · {result.unchecked_gates.length} gates we can't check</>
              )}
            </button>
            <button type="button" className="workbar-btn" onClick={() => setWork("price")}>
              What the lane says this should cost
            </button>
            <button type="button" className="workbar-btn" onClick={() => setWork("load")}>
              Stops, offers, audit trail
            </button>
            <button type="button" className="workbar-btn" onClick={() => setWork("engine")}>
              {result.engine.name} v{result.engine.version}
            </button>
          </div>

          {result.notes.map((note) => (
            <p className="notice notice-quiet" key={note}>
              {note}
            </p>
          ))}

          {work && (
            <ShowTheWork
              result={result}
              detail={detail}
              carrier={lead}
              brokerId={brokerId}
              engine={engine}
              onEngineChange={setEngine}
              tab={work}
              onTab={setWork}
              onClose={() => setWork(null)}
            />
          )}
        </>
      )}
    </div>
  );
}
