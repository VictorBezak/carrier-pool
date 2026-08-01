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
      <header className="masthead">
        <span className="wordmark">
          Carrier<span>Pool</span>
        </span>

        <label className="brokerpick">
          <span className="eyebrow">Broker</span>
          <select
            value={brokerId ?? ""}
            onChange={(event) => navigate(`/brokers/${event.target.value}`)}
          >
            {brokers.map((broker) => (
              <option key={broker.broker_id} value={broker.broker_id}>
                {broker.name}
              </option>
            ))}
          </select>
        </label>

        {/* The one number a broker cares about on arrival. Ingest counts - sync files
            processed, carriers known - are engineering telemetry: true, verifiable, and
            not what someone came to this screen to find out. They moved into the feed
            summary below rather than leading the page. */}
        {active && (
          <span className="masthead-count">
            <strong className="fig">{active.active_load_count}</strong> need a truck
          </span>
        )}
      </header>

      <main>
        <Outlet />
      </main>

      {active && (
        <footer className="feedfoot">
          <span>
            {active.name} · {active.tms_label}
          </span>
          <span className="feedfoot-stats">
            <span className="fig">{active.load_count}</span> loads ·{" "}
            <span className="fig">{active.carrier_count}</span> carriers ·{" "}
            <span className="fig">{active.sync_file_count}</span> sync files · latest{" "}
            {dateTime(active.last_synced_at)}
          </span>
        </footer>
      )}
    </div>
  );
}
