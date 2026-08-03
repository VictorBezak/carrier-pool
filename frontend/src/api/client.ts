import type { Broker, LoadDetail, LoadSummary, PoolPolicy, Recommendation, SyncFile } from "@/api/types";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }
    });
  } catch (cause) {
    throw new Error(`Could not reach ${path}. Is the backend running?`, { cause });
  }
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
