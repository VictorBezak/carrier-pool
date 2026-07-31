import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, useResource } from "../api/client";
import type { LoadStatus } from "../api/types";
import { Empty, ErrorNote, Loading, StatusPill } from "../components/atoms";
import { EQUIPMENT_LABELS, dateTime, miles, money, shortDate } from "../format";

const FILTERS: { key: LoadStatus | "ALL"; label: string }[] = [
  { key: "ACTIVE", label: "Needs a carrier" },
  { key: "COVERED", label: "Covered" },
  { key: "IN_TRANSIT", label: "In transit" },
  { key: "COMPLETED", label: "Completed" },
  { key: "ALL", label: "All loads" },
];

export function LoadListPage() {
  const { brokerId = "" } = useParams();
  const [status, setStatus] = useState<LoadStatus | "ALL">("ACTIVE");
  const [query, setQuery] = useState("");

  const loads = useResource(
    (signal) => api.loads(brokerId, { status, q: query || undefined }, signal),
    [brokerId, status, query],
  );
  const lanes = useResource((signal) => api.lanes(brokerId, signal), [brokerId]);

  return (
    <div className="page">
      <div className="toolbar">
        <div className="tabs">
          {FILTERS.map((filter) => (
            <button
              key={filter.key}
              className={filter.key === status ? "tab tab-active" : "tab"}
              onClick={() => setStatus(filter.key)}
            >
              {filter.label}
            </button>
          ))}
        </div>
        <input
          className="search"
          type="search"
          placeholder="Search load, customer, carrier or city"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {loads.loading && <Loading what="loads" />}
      {loads.error && <ErrorNote message={loads.error} />}
      {loads.data?.length === 0 && <Empty>No loads match this filter.</Empty>}

      {loads.data && loads.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Load</th>
              <th>Status</th>
              <th>Lane</th>
              <th>Equipment</th>
              <th className="numeric">Distance</th>
              <th>Customer</th>
              <th className="numeric">Customer pays</th>
              <th className="numeric">Carrier costs</th>
              <th>Carrier</th>
              <th>Pickup</th>
            </tr>
          </thead>
          <tbody>
            {loads.data.map((load) => (
              <tr key={load.load_id}>
                <td>
                  <Link className="load-link" to={`/brokers/${brokerId}/loads/${encodeURIComponent(load.source_ref)}`}>
                    {load.reference}
                  </Link>
                  {load.correction_count > 0 && (
                    <span className="pill pill-change pill-correction" title="An already-recorded value on this load was later changed">
                      {load.correction_count} correction{load.correction_count > 1 ? "s" : ""}
                    </span>
                  )}
                </td>
                <td><StatusPill status={load.status} /></td>
                <td>
                  <div className="lane-label">{load.lane_label}</div>
                  <div className="lane-cities">
                    {load.origin_label} → {load.destination_label}
                  </div>
                </td>
                <td>{EQUIPMENT_LABELS[load.equipment]}</td>
                <td className="numeric">{miles(load.distance_miles)}</td>
                <td>{load.customer_name ?? "—"}</td>
                <td className="numeric">{money(load.customer_rate)}</td>
                <td className="numeric">{money(load.carrier_rate)}</td>
                <td>{load.carrier_name ?? <span className="muted">not booked</span>}</td>
                <td title={dateTime(load.pickup_at)}>{shortDate(load.pickup_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {lanes.data && lanes.data.length > 0 && (
        <section className="lane-panel">
          <h2>Where this broker has history</h2>
          <p className="card-subtitle">
            Lanes are metro-to-metro, not city-to-city, and are built only from loads a carrier
            actually committed to at a known price. Thin lanes are why some estimates below have to
            widen their comparison.
          </p>
          <table className="table table-compact">
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
                  <td className="numeric">{lane.load_count}</td>
                  <td className="numeric">{lane.carrier_count}</td>
                  <td className="numeric">
                    {lane.median_rate_per_mile == null ? "—" : `$${lane.median_rate_per_mile.toFixed(2)}/mi`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
