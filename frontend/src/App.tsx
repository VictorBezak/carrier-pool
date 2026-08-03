import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type {
  Broker,
  CarrierRanking,
  LaneGeometry,
  LoadDetail,
  LoadSummary,
  MapPoint,
  PoolCarrierRanking,
  PoolPolicy,
  Recommendation,
  SyncFile
} from "./types";

const CONFIDENCE_CLASS: Record<string, string> = { high: "confidence-high", medium: "confidence-medium", low: "confidence-low" };

export default function App() {
  const [brokers, setBrokers] = useState<Broker[]>([]);
  const [loads, setLoads] = useState<LoadSummary[]>([]);
  const [syncs, setSyncs] = useState<SyncFile[]>([]);
  const [policy, setPolicy] = useState<PoolPolicy | null>(null);
  const [selectedBroker, setSelectedBroker] = useState("");
  const [selectedLoad, setSelectedLoad] = useState("");
  const [selectedAsOf, setSelectedAsOf] = useState<string | null>(null);
  const [detail, setDetail] = useState<LoadDetail | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [expandedCarrier, setExpandedCarrier] = useState<string | null>(null);
  const [showPolicy, setShowPolicy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([api.brokers(), api.poolPolicy()])
      .then(([brokerRows, policyRow]) => {
        setBrokers(brokerRows);
        setPolicy(policyRow);
        setSelectedBroker(brokerRows[0]?.broker_id ?? "");
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!selectedBroker) return;
    setSelectedLoad("");
    setSelectedAsOf(null);
    void Promise.all([api.loads(selectedBroker), api.syncs(selectedBroker)])
      .then(([loadRows, syncRows]) => {
        setLoads(loadRows);
        setSyncs(syncRows);
        const firstActive = loadRows.find((load) => load.status === "active") ?? loadRows[0];
        setSelectedLoad(firstActive?.load_id ?? "");
      })
      .catch((err: Error) => setError(err.message));
  }, [selectedBroker]);

  useEffect(() => {
    if (!selectedBroker || !selectedLoad) return;
    void api
      .load(selectedBroker, selectedLoad)
      .then((value) => {
        setDetail(value);
        setSelectedAsOf(null);
      })
      .catch((err: Error) => setError(err.message));
  }, [selectedBroker, selectedLoad]);

  const broker = brokers.find((item) => item.broker_id === selectedBroker);
  const poolEnabled = Boolean(broker?.pool_opt_in);

  useEffect(() => {
    if (!selectedBroker || !selectedLoad) return;
    void api
      .recommendation(selectedBroker, selectedLoad, selectedAsOf, poolEnabled)
      .then((value) => {
        setRecommendation(value);
        setExpandedCarrier(value.own_carriers[0]?.carrier_id ?? value.pool_carriers[0]?.carrier_id ?? null);
      })
      .catch((err: Error) => setError(err.message));
  }, [selectedBroker, selectedLoad, selectedAsOf, poolEnabled]);

  const changedFiles = useMemo(() => new Set(detail?.versions.map((version) => version.source_file) ?? []), [detail]);
  const activeLoads = loads.filter((load) => load.status === "active");
  const completedLoads = loads.filter((load) => load.status !== "active");

  async function togglePool(enabled: boolean) {
    if (!selectedBroker) return;
    const row = await api.setPoolOptIn(selectedBroker, enabled);
    setBrokers((current) => current.map((item) => (item.broker_id === row.broker_id ? { ...item, pool_opt_in: row.pool_opt_in } : item)));
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Carrier Pool</p>
          <h1>Coverage desk</h1>
        </div>
        <div className="broker-tabs" aria-label="Broker">
          {brokers.map((item) => (
            <button
              className={item.broker_id === selectedBroker ? "tab active" : "tab"}
              key={item.broker_id}
              onClick={() => setSelectedBroker(item.broker_id)}
            >
              <span>{item.name}</span>
              <b>{item.active_count} active</b>
            </button>
          ))}
        </div>
      </header>

      {error && <div className="error-card">{error}</div>}

      <section className="desk">
        <aside className="load-queue" aria-label="Load queue">
          <div className="queue-header">
            <p className="eyebrow">Need coverage</p>
            <strong>{activeLoads.length} active loads</strong>
          </div>
          <LoadList loads={activeLoads} selectedLoad={selectedLoad} onSelect={setSelectedLoad} />
          <details className="completed-drawer">
            <summary>{completedLoads.length} historical / booked loads</summary>
            <LoadList loads={completedLoads} selectedLoad={selectedLoad} onSelect={setSelectedLoad} />
          </details>
        </aside>

        <section className="workbench">
          {recommendation && detail ? (
            <>
              <LoadHeader detail={detail} recommendation={recommendation} />
              <SyncStrip syncs={syncs} changedFiles={changedFiles} selectedAsOf={selectedAsOf} onSelect={setSelectedAsOf} />
              <PoolSwitch broker={broker} enabled={poolEnabled} policy={policy} showPolicy={showPolicy} setShowPolicy={setShowPolicy} onToggle={togglePool} />
              <CarrierSection
                carriers={recommendation.own_carriers}
                expandedCarrier={expandedCarrier}
                setExpandedCarrier={setExpandedCarrier}
              />
              {poolEnabled && (
                <PoolSection
                  carriers={recommendation.pool_carriers}
                  expandedCarrier={expandedCarrier}
                  setExpandedCarrier={setExpandedCarrier}
                />
              )}
            </>
          ) : (
            <div className="empty-state">Select a load to see expected cost and who to call first.</div>
          )}
        </section>
      </section>
    </main>
  );
}

function LoadList({ loads, selectedLoad, onSelect }: { loads: LoadSummary[]; selectedLoad: string; onSelect: (loadId: string) => void }) {
  return (
    <div className="load-list">
      {loads.map((load) => (
        <button className={load.load_id === selectedLoad ? "load-row active" : "load-row"} key={load.load_id} onClick={() => onSelect(load.load_id)}>
          <span className="load-row__status">{load.status}</span>
          <strong>
            {load.pickup.city} to {load.delivery.city}
          </strong>
          <span>
            {load.equipment.replace("_", " ")} / {load.distance_miles.toFixed(0)} mi
          </span>
        </button>
      ))}
    </div>
  );
}

function LoadHeader({ detail, recommendation }: { detail: LoadDetail; recommendation: Recommendation }) {
  const price = recommendation.price;
  return (
    <article className="load-hero">
      <div>
        <p className="eyebrow">Call first</p>
        <h2>
          {detail.pickup.city} <span>to</span> {detail.delivery.city}
        </h2>
        <p>
          {detail.customer.name} / {detail.equipment.replace("_", " ")} / {detail.distance_miles.toFixed(1)} miles / load {detail.load_id}
        </p>
      </div>
      <div className={`price-card ${CONFIDENCE_CLASS[price.confidence]}`}>
        <span>Expect to pay</span>
        <strong>{money(price.point_usd)}</strong>
        <small>
          {money(price.low_usd)} to {money(price.high_usd)} / {price.point_ppm.toFixed(2)}/mi / {price.confidence}
        </small>
      </div>
    </article>
  );
}

function SyncStrip({
  syncs,
  changedFiles,
  selectedAsOf,
  onSelect
}: {
  syncs: SyncFile[];
  changedFiles: Set<string>;
  selectedAsOf: string | null;
  onSelect: (value: string | null) => void;
}) {
  return (
    <section className="sync-strip">
      <div>
        <p className="eyebrow">As-of replay</p>
        <strong>{selectedAsOf ? new Date(selectedAsOf).toLocaleString() : "Current view"}</strong>
      </div>
      <div className="ticks" role="list" aria-label="Sync timestamps">
        <button className={!selectedAsOf ? "tick current active" : "tick current"} onClick={() => onSelect(null)} title="Current">
          Now
        </button>
        {syncs.map((sync) => (
          <button
            className={[
              "tick",
              changedFiles.has(sync.source_file) ? "changed" : "",
              selectedAsOf === sync.synced_at ? "active" : ""
            ].join(" ")}
            key={sync.source_file}
            onClick={() => onSelect(sync.synced_at)}
            title={`${sync.filename}${changedFiles.has(sync.source_file) ? " changed this load" : ""}`}
          />
        ))}
      </div>
    </section>
  );
}

function PoolSwitch({
  broker,
  enabled,
  policy,
  showPolicy,
  setShowPolicy,
  onToggle
}: {
  broker: Broker | undefined;
  enabled: boolean;
  policy: PoolPolicy | null;
  showPolicy: boolean;
  setShowPolicy: (value: boolean) => void;
  onToggle: (value: boolean) => void;
}) {
  const isEligible = Boolean(broker && policy?.eligible_brokers.includes(broker.broker_id));
  return (
    <section className="pool-panel">
      <div>
        <p className="eyebrow">Shared carrier pool</p>
        <strong>{isEligible ? "Opted-in carriers appear as a separate pool tier" : "Pool unavailable for this broker"}</strong>
        {!isEligible && broker && <span>{policy?.ineligible_brokers[broker.broker_id]}</span>}
      </div>
      <label className="switch">
        <input type="checkbox" checked={enabled} disabled={!isEligible} onChange={(event) => void onToggle(event.currentTarget.checked)} />
        <span>Pool on</span>
      </label>
      <button className="text-button" onClick={() => setShowPolicy(!showPolicy)}>
        {showPolicy ? "Hide boundary" : "Show boundary"}
      </button>
      {showPolicy && policy && (
        <div className="policy-drawer">
          <p>Only these fields cross brokers: {policy.fields.join(", ")}.</p>
          <p>Never shared: {policy.never_shared.join(", ")}.</p>
          <p>{policy.matching_rule}</p>
        </div>
      )}
    </section>
  );
}

function CarrierSection({
  carriers,
  expandedCarrier,
  setExpandedCarrier
}: {
  carriers: CarrierRanking[];
  expandedCarrier: string | null;
  setExpandedCarrier: (id: string) => void;
}) {
  return (
    <section className="carrier-stack">
      <div className="section-title">
        <p className="eyebrow">Broker-local ranking</p>
        <strong>{carriers.length} carriers from this broker's own history</strong>
      </div>
      {carriers.map((carrier, index) => (
        <CarrierCard
          key={carrier.carrier_id}
          carrier={carrier}
          index={index}
          expanded={expandedCarrier === carrier.carrier_id}
          onExpand={() => setExpandedCarrier(carrier.carrier_id)}
        />
      ))}
    </section>
  );
}

function PoolSection({
  carriers,
  expandedCarrier,
  setExpandedCarrier
}: {
  carriers: PoolCarrierRanking[];
  expandedCarrier: string | null;
  setExpandedCarrier: (id: string) => void;
}) {
  return (
    <section className="carrier-stack pool-stack">
      <div className="section-title">
        <p className="eyebrow">Pool tier</p>
        <strong>{carriers.length ? `${carriers.length} unknown carriers from opted-in brokers` : "No eligible pool carriers for this load"}</strong>
      </div>
      {carriers.map((carrier, index) => (
        <PoolCard
          key={`${carrier.contributor_broker_id}:${carrier.carrier_id}`}
          carrier={carrier}
          index={index}
          expanded={expandedCarrier === carrier.carrier_id}
          onExpand={() => setExpandedCarrier(carrier.carrier_id)}
        />
      ))}
    </section>
  );
}

function CarrierCard({ carrier, index, expanded, onExpand }: { carrier: CarrierRanking; index: number; expanded: boolean; onExpand: () => void }) {
  const price = carrier.components.find((item) => item.name === "price")?.evidence.point_usd as number | undefined;
  return (
    <article className={`carrier-card ${CONFIDENCE_CLASS[carrier.confidence]}`}>
      <button className="carrier-head" onClick={onExpand}>
        <span className="rank">{index + 1}</span>
        <span>
          <strong>{carrier.carrier_name}</strong>
          <small>{carrier.confidence} confidence</small>
        </span>
        <b>{carrier.score.toFixed(3)}</b>
        <span>{price ? money(price) : "Market"}</span>
      </button>
      {expanded && <CarrierEvidence carrier={carrier} />}
    </article>
  );
}

function PoolCard({ carrier, index, expanded, onExpand }: { carrier: PoolCarrierRanking; index: number; expanded: boolean; onExpand: () => void }) {
  return (
    <article className={`carrier-card pool-card ${CONFIDENCE_CLASS[carrier.confidence]}`}>
      <button className="carrier-head" onClick={onExpand}>
        <span className="rank">P{index + 1}</span>
        <span>
          <strong>{carrier.carrier_name}</strong>
          <small>via {carrier.contributor_broker_name}</small>
        </span>
        <b>{carrier.score.toFixed(3)}</b>
        <span>{money(carrier.expected_carrier_cost_usd)}</span>
      </button>
      {expanded && (
        <div className="evidence-grid">
          <LaneTrace geometry={carrier.geometry} />
          <ReasonList title="Why" items={carrier.reasons} />
          <ReasonList title="What we don't know" items={carrier.limitations} />
          <div className="payload-card">
            <h4>Boundary payload</h4>
            {Object.entries(carrier.payload).map(([key, value]) => (
              <p key={key}>
                <span>{key}</span>
                <b>{Array.isArray(value) ? value.join(", ") || "none" : value ?? "none"}</b>
              </p>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}

function CarrierEvidence({ carrier }: { carrier: CarrierRanking }) {
  const comparables = (carrier.components.find((item) => item.name === "price")?.evidence.comparables ?? []) as never[];
  return (
    <div className="evidence-grid">
      <LaneTrace geometry={carrier.geometry} />
      <div className="component-panel">
        <h4>Score components</h4>
        {carrier.components.map((component) => (
          <div className="component-row" key={component.name}>
            <span>{component.name.replace("_", " ")}</span>
            <div>
              <i style={{ width: `${component.score * 100}%` }} />
            </div>
            <b>{component.score.toFixed(2)}</b>
          </div>
        ))}
      </div>
      <ReasonList title="Why" items={carrier.reasons} />
      <ReasonList title="What we don't know" items={carrier.limitations} />
      <div className="comparable-panel">
        <h4>Price evidence</h4>
        {carrier.components.map((component) => (
          <details key={component.name}>
            <summary>{component.name.replace("_", " ")}</summary>
            {Object.entries(component.evidence).map(([key, value]) => (
              <p key={key}>
                <span>{key}</span>
                <b>{String(value ?? "none")}</b>
              </p>
            ))}
          </details>
        ))}
        {comparables.length === 0 && <small>Comparable load detail is surfaced in the price estimate basis.</small>}
      </div>
    </div>
  );
}

function ReasonList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="reason-list">
      <h4>{title}</h4>
      {items.map((item) => (
        <p key={item}>{item}</p>
      ))}
    </div>
  );
}

function LaneTrace({ geometry }: { geometry: LaneGeometry }) {
  const targetOrigin = project(geometry.target.origin);
  const targetDestination = project(geometry.target.destination);
  const lastDelivery = project(geometry.last_delivery);
  return (
    <svg className="lane-map" viewBox="0 0 320 210" role="img" aria-label="Texas Triangle lane trace">
      <path className="triangle" d="M72 45 L270 84 L160 176 Z" />
      <text x="55" y="36">DFW</text>
      <text x="266" y="73">Houston</text>
      <text x="134" y="194">San Antonio</text>
      {geometry.historical_lanes.map((lane, index) => {
        const origin = project(lane.origin);
        const destination = project(lane.destination);
        if (!origin || !destination) return null;
        return (
          <line
            className="history-line"
            key={`${origin.x}:${origin.y}:${index}`}
            x1={origin.x}
            y1={origin.y}
            x2={destination.x}
            y2={destination.y}
            style={{ opacity: 0.12 + Math.min(0.76, lane.weight * 0.75) }}
          />
        );
      })}
      {lastDelivery && targetOrigin && <line className="deadhead-line" x1={lastDelivery.x} y1={lastDelivery.y} x2={targetOrigin.x} y2={targetOrigin.y} />}
      {targetOrigin && targetDestination && <line className="target-line" x1={targetOrigin.x} y1={targetOrigin.y} x2={targetDestination.x} y2={targetDestination.y} />}
      {targetOrigin && <circle className="origin-dot" cx={targetOrigin.x} cy={targetOrigin.y} r="5" />}
      {targetDestination && <circle className="dest-dot" cx={targetDestination.x} cy={targetDestination.y} r="5" />}
    </svg>
  );
}

function project(point: MapPoint | null): { x: number; y: number } | null {
  if (!point) return null;
  const minLon = -99.9;
  const maxLon = -94.4;
  const minLat = 28.7;
  const maxLat = 33.4;
  return {
    x: 28 + ((point.lon - minLon) / (maxLon - minLon)) * 264,
    y: 188 - ((point.lat - minLat) / (maxLat - minLat)) * 158
  };
}

function money(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}
