import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "@/api/client";
import type { Broker, PoolPolicy, SyncFile } from "@/api/types";

const STORAGE_KEY = "carrier-pool.viewing-as";

type Session = {
  brokers: Broker[];
  broker: Broker | null;
  brokerId: string;
  /** True while the operator is impersonating a broker other than the default tenant. */
  impersonating: boolean;
  viewAs: (brokerId: string) => void;
  resetBroker: () => void;
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
  const [brokerId, setBrokerId] = useState<string>(() => localStorage.getItem(STORAGE_KEY) ?? "");
  const [syncs, setSyncs] = useState<SyncFile[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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
    setAsOf(null);
    void api
      .syncs(brokerId)
      .then(setSyncs)
      .catch((cause: Error) => setError(cause.message));
  }, [brokerId]);

  const viewAs = useCallback((next: string) => {
    localStorage.setItem(STORAGE_KEY, next);
    setBrokerId(next);
  }, []);

  const resetBroker = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setBrokers((current) => {
      setBrokerId(current[0]?.broker_id ?? "");
      return current;
    });
  }, []);

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
      impersonating: Boolean(brokerId) && brokers.length > 0 && brokerId !== brokers[0].broker_id,
      viewAs,
      resetBroker,
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
  }, [brokers, brokerId, viewAs, resetBroker, syncs, asOf, poolPolicy, setPoolOptIn, error, loading]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside SessionProvider");
  return session;
}
