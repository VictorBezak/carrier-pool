import { Navigate, Outlet, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, useResource } from "./api/client";
import type { BrokerSummary } from "./api/types";
import { ErrorNote, Loading } from "./components/atoms";
import { LoadDetailPage } from "./pages/LoadDetailPage";
import { LoadListPage } from "./pages/LoadListPage";
import { dateTime } from "./format";

export function App() {
  const brokers = useResource((signal) => api.brokers(signal), []);

  if (brokers.loading) return <Loading what="brokers" />;
  if (brokers.error) return <ErrorNote message={brokers.error} />;
  if (!brokers.data || brokers.data.length === 0) {
    return <ErrorNote message="the backend reported no brokers" />;
  }

  const first = brokers.data[0]!;

  return (
    <Routes>
      <Route path="/" element={<Navigate to={`/brokers/${first.broker_id}`} replace />} />
      <Route path="/brokers/:brokerId" element={<Shell brokers={brokers.data} />}>
        <Route index element={<LoadListPage />} />
        <Route path="loads/:sourceRef" element={<LoadDetailPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

/**
 * The broker switcher is the whole of the multi-tenant UI. Switching brokers
 * changes the path, which changes every API call — the frontend has no way to
 * ask for two brokers at once, because the backend has no route that would
 * answer.
 */
function Shell({ brokers }: { brokers: BrokerSummary[] }) {
  const { brokerId } = useParams();
  const navigate = useNavigate();
  const active = brokers.find((broker) => broker.broker_id === brokerId);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">Carrier&nbsp;Pool</span>
          <span className="brand-sub">carrier recommendations from a broker's own history</span>
        </div>

        <label className="broker-select">
          <span>Broker</span>
          <select
            value={brokerId ?? ""}
            onChange={(event) => navigate(`/brokers/${event.target.value}`)}
          >
            {brokers.map((broker) => (
              <option key={broker.broker_id} value={broker.broker_id}>
                {broker.name} — {broker.tms_label}
              </option>
            ))}
          </select>
        </label>
      </header>

      {active && (
        <div className="broker-strip">
          <span>
            <strong>{active.active_load_count}</strong> load
            {active.active_load_count === 1 ? "" : "s"} need a carrier
          </span>
          <span>
            <strong>{active.load_count}</strong> loads ingested
          </span>
          <span>
            <strong>{active.carrier_count}</strong> known carriers
          </span>
          <span>
            <strong>{active.sync_file_count}</strong> sync files processed
          </span>
          <span className="muted">
            {active.tms_style} · latest sync {dateTime(active.last_synced_at)}
          </span>
        </div>
      )}

      <main>
        <Outlet />
      </main>
    </div>
  );
}
