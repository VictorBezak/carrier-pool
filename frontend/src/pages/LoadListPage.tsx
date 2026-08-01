import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, useResource } from "../api/client";
import type { LoadStatus } from "../api/types";
import { Empty, ErrorNote, Loading, StatusPill } from "../components/atoms";
import { EQUIPMENT_LABELS, miles, money, shortDate } from "../format";

const FILTERS: { key: LoadStatus | "ALL"; label: string }[] = [
  { key: "ACTIVE", label: "Needs a truck" },
  { key: "COVERED", label: "Covered" },
  { key: "IN_TRANSIT", label: "Rolling" },
  { key: "COMPLETED", label: "Delivered" },
  { key: "ALL", label: "Everything" },
];

/**
 * The board: which loads need a truck, in the order a dispatcher would work them.
 *
 * This was a nine-column table, which is the right shape for auditing an ingest and
 * the wrong shape for choosing what to work next. Each load is now a row you read in
 * one pass — lane first, because the lane is how a dispatcher thinks about a load, and
 * the reference number second, because it is only how the TMS thinks about it.
 */
export function LoadListPage() {
  const { brokerId = "" } = useParams();
  const [status, setStatus] = useState<LoadStatus | "ALL">("ACTIVE");
  const [query, setQuery] = useState("");
  const [showLanes, setShowLanes] = useState(false);

  const loads = useResource(
    (signal) => api.loads(brokerId, { status, q: query || undefined }, signal),
    [brokerId, status, query],
  );
  const lanes = useResource((signal) => api.lanes(brokerId, signal), [brokerId]);

  return (
    <div className="sheetpage">
      <div className="board-bar">
        <div className="segments" role="tablist">
          {FILTERS.map((filter) => (
            <button
              key={filter.key}
              role="tab"
              aria-selected={filter.key === status}
              className={filter.key === status ? "segment is-active" : "segment"}
              onClick={() => setStatus(filter.key)}
            >
              {filter.label}
            </button>
          ))}
        </div>
        <input
          className="find"
          type="search"
          placeholder="Load, customer, carrier or city"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {loads.loading && <Loading what="loads" />}
      {loads.error && <ErrorNote message={loads.error} />}
      {loads.data?.length === 0 && <Empty>No loads match this filter.</Empty>}

      {loads.data && loads.data.length > 0 && (
        <ul className="board">
          {loads.data.map((load) => (
            <li key={load.load_id}>
              <Link
                className="boardrow"
                to={`/brokers/${brokerId}/loads/${encodeURIComponent(load.source_ref)}`}
              >
                <span className="boardrow-lane">
                  <span className="boardrow-title">{load.lane_label}</span>
                  <span className="boardrow-cities">
                    {load.origin_label} → {load.destination_label}
                  </span>
                </span>

                <span className="boardrow-spec">
                  <span>{EQUIPMENT_LABELS[load.equipment]}</span>
                  <span className="fig">{miles(load.distance_miles)}</span>
                </span>

                <span className="boardrow-when">
                  <span className="eyebrow">Picks up</span>
                  <span className="fig">{shortDate(load.pickup_at)}</span>
                </span>

                <span className="boardrow-money">
                  <span className="eyebrow">Customer pays</span>
                  <span className="fig">{money(load.customer_rate)}</span>
                </span>

                <span className="boardrow-who">
                  {load.carrier_name ? (
                    <>
                      <span className="eyebrow">Carrier</span>
                      <span>{load.carrier_name}</span>
                    </>
                  ) : (
                    <StatusPill status={load.status} />
                  )}
                  {load.correction_count > 0 && (
                    <span
                      className="flag flag-thin"
                      title="An already-recorded value on this load was later changed"
                    >
                      {load.correction_count} correction{load.correction_count > 1 ? "s" : ""}
                    </span>
                  )}
                </span>

                <span className="boardrow-go" aria-hidden="true">
                  →
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {lanes.data && lanes.data.length > 0 && (
        <section className="lanes">
          <button
            type="button"
            className="lanes-toggle"
            onClick={() => setShowLanes(!showLanes)}
            aria-expanded={showLanes}
          >
            Where this broker has history{" "}
            <span className="fig">
              {lanes.data.length} lane{lanes.data.length === 1 ? "" : "s"}
            </span>
          </button>
          {showLanes && (
            <>
              <p className="prose">
                Lanes are metro-to-metro rather than city-to-city, and are built only from loads a
                carrier actually committed to at a known price. Thin lanes are why some estimates
                have to widen their comparison.
              </p>
              <table className="grid">
                <thead>
                  <tr>
                    <th>Lane</th>
                    <th className="numeric">Priced loads</th>
                    <th className="numeric">Carriers used</th>
                    <th className="numeric">Median rate</th>
                  </tr>
                </thead>
                <tbody>
                  {lanes.data.map((lane) => (
                    <tr key={lane.lane}>
                      <td>{lane.lane_label}</td>
                      <td className="numeric fig">{lane.load_count}</td>
                      <td className="numeric fig">{lane.carrier_count}</td>
                      <td className="numeric fig">
                        {lane.median_rate_per_mile == null
                          ? "—"
                          : `$${lane.median_rate_per_mile.toFixed(2)}/mi`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}
    </div>
  );
}
