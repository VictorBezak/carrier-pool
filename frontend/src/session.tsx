import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "@/api/client";
import type { Broker, PoolPolicy, SyncFile } from "@/api/types";

const BROKER_KEY = "carrier-pool.viewing-as";
const AS_OF_KEY = "carrier-pool.as-of";

/** Replay points are kept per broker, since each timestamp only indexes into that broker's syncs. */
function readAsOfs(): Record<string, string> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(AS_OF_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

type Session = {
  brokers: Broker[];
  broker: Broker | null;
  brokerId: string;
  viewAs: (brokerId: string) => void;
  syncs: SyncFile[];
  asOf: string | null;
  setAsOf: (value: string | null) => void;
  poolEnabled: boolean;
  poolEligible: boolean;
  poolPolicy: PoolPolicy | null;
  setPoolOptIn: (enabled: boolean) => Promise<void>;
  error: string | null;
  loading: boolean;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [brokers, setBrokers] = useState<Broker[]>([]);
  const [poolPolicy, setPoolPolicy] = useState<PoolPolicy | null>(null);
  const [brokerId, setBrokerId] = useState<string>(() => localStorage.getItem(BROKER_KEY) ?? "");
  const [syncs, setSyncs] = useState<SyncFile[]>([]);
  const [asOfByBroker, setAsOfByBroker] = useState<Record<string, string>>(readAsOfs);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const asOf = asOfByBroker[brokerId] ?? null;

  useEffect(() => {
    void Promise.all([api.brokers(), api.poolPolicy()])
      .then(([brokerRows, policy]) => {
        setBrokers(brokerRows);
        setPoolPolicy(policy);
        setBrokerId((current) => (brokerRows.some((row) => row.broker_id === current) ? current : (brokerRows[0]?.broker_id ?? "")));
      })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!brokerId) return;
    localStorage.setItem(BROKER_KEY, brokerId);
    void api
      .syncs(brokerId)
      .then(setSyncs)
      .catch((cause: Error) => setError(cause.message));
  }, [brokerId]);

  useEffect(() => {
    localStorage.setItem(AS_OF_KEY, JSON.stringify(asOfByBroker));
  }, [asOfByBroker]);

  const viewAs = useCallback((next: string) => setBrokerId(next), []);

  const setAsOf = useCallback(
    (value: string | null) =>
      setAsOfByBroker((current) => {
        const next = { ...current };
        if (value) next[brokerId] = value;
        else delete next[brokerId];
        return next;
      }),
    [brokerId]
  );

  const setPoolOptIn = useCallback(
    async (enabled: boolean) => {
      const row = await api.setPoolOptIn(brokerId, enabled);
      setBrokers((current) =>
        current.map((item) => (item.broker_id === row.broker_id ? { ...item, pool_opt_in: row.pool_opt_in } : item))
      );
    },
    [brokerId]
  );

  const value = useMemo<Session>(() => {
    const broker = brokers.find((item) => item.broker_id === brokerId) ?? null;
    return {
      brokers,
      broker,
      brokerId,
      viewAs,
      syncs,
      asOf,
      setAsOf,
      poolEnabled: Boolean(broker?.pool_opt_in),
      poolEligible: Boolean(broker && poolPolicy?.eligible_brokers.includes(broker.broker_id)),
      poolPolicy,
      setPoolOptIn,
      error,
      loading
    };
  }, [brokers, brokerId, viewAs, syncs, asOf, setAsOf, poolPolicy, setPoolOptIn, error, loading]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside SessionProvider");
  return session;
}
