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

/** Every read is projected at a point in time; `null` means the latest sync. */
function query(asOf: string | null, extra?: Record<string, string>) {
  const params = new URLSearchParams(extra);
  if (asOf) params.set("as_of", asOf);
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export const api = {
  brokers: () => json<Broker[]>("/api/brokers"),
  loads: (brokerId: string, asOf: string | null) => json<LoadSummary[]>(`/api/brokers/${brokerId}/loads${query(asOf)}`),
  load: (brokerId: string, loadId: string, asOf: string | null) =>
    json<LoadDetail>(`/api/brokers/${brokerId}/loads/${loadId}${query(asOf)}`),
  syncs: (brokerId: string) => json<SyncFile[]>(`/api/brokers/${brokerId}/syncs`),
  recommendation: (brokerId: string, loadId: string, asOf: string | null, pool: boolean) =>
    json<Recommendation>(`/api/brokers/${brokerId}/loads/${loadId}/recommendation${query(asOf, { pool: String(pool) })}`),
  setPoolOptIn: (brokerId: string, enabled: boolean) =>
    json<{ broker_id: string; pool_opt_in: boolean }>(`/api/brokers/${brokerId}/pool-opt-in`, {
      method: "PUT",
      body: JSON.stringify({ enabled })
    }),
  poolPolicy: () => json<PoolPolicy>("/api/pool/policy")
};
