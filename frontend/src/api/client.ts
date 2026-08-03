import type { Broker, LoadDetail, LoadSummary, PoolPolicy, Recommendation, SyncFile } from "@/api/types";

export type LoggedRequest = {
  id: number;
  url: string;
  status: number | "error";
  duration_ms: number;
  at: string;
};

let entries: LoggedRequest[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

/** Every request the UI makes is recorded so the dev sheet can show what backs a view. */
export const requestLog = {
  snapshot: () => entries,
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  clear() {
    entries = [];
    listeners.forEach((listener) => listener());
  }
};

function record(url: string, status: number | "error", startedAt: number) {
  const entry: LoggedRequest = {
    id: nextId++,
    url,
    status,
    duration_ms: Math.round(performance.now() - startedAt),
    at: new Date().toISOString()
  };
  entries = [entry, ...entries].slice(0, 40);
  listeners.forEach((listener) => listener());
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const startedAt = performance.now();
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }
    });
  } catch (cause) {
    record(path, "error", startedAt);
    throw new Error(`Could not reach ${path}. Is the backend running?`, { cause });
  }
  record(path, response.status, startedAt);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export const api = {
  brokers: () => json<Broker[]>("/api/brokers"),
  loads: (brokerId: string) => json<LoadSummary[]>(`/api/brokers/${brokerId}/loads`),
  load: (brokerId: string, loadId: string) => json<LoadDetail>(`/api/brokers/${brokerId}/loads/${loadId}`),
  syncs: (brokerId: string) => json<SyncFile[]>(`/api/brokers/${brokerId}/syncs`),
  recommendation: (brokerId: string, loadId: string, asOf: string | null, pool: boolean) => {
    const params = new URLSearchParams({ pool: String(pool) });
    if (asOf) params.set("as_of", asOf);
    return json<Recommendation>(`/api/brokers/${brokerId}/loads/${loadId}/recommendation?${params.toString()}`);
  },
  setPoolOptIn: (brokerId: string, enabled: boolean) =>
    json<{ broker_id: string; pool_opt_in: boolean }>(`/api/brokers/${brokerId}/pool-opt-in`, {
      method: "PUT",
      body: JSON.stringify({ enabled })
    }),
  poolPolicy: () => json<PoolPolicy>("/api/pool/policy")
};
