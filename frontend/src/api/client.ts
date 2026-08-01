import { useEffect, useState } from "react";
import type {
  BrokerSummary,
  LaneSummary,
  LoadDetail,
  LoadStatus,
  LoadSummary,
  Recommendations,
} from "./types";

const BASE = "/api";

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { signal });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // A non-JSON error body is not worth failing over.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  brokers: (signal?: AbortSignal) => request<BrokerSummary[]>("/brokers", signal),
  loads: (
    brokerId: string,
    params: { status?: LoadStatus | "ALL"; q?: string } = {},
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams();
    if (params.status && params.status !== "ALL") query.set("status", params.status);
    if (params.q) query.set("q", params.q);
    const suffix = query.toString() ? `?${query}` : "";
    return request<LoadSummary[]>(`/brokers/${brokerId}/loads${suffix}`, signal);
  },
  load: (brokerId: string, sourceRef: string, signal?: AbortSignal) =>
    request<LoadDetail>(`/brokers/${brokerId}/loads/${encodeURIComponent(sourceRef)}`, signal),
  recommendations: (
    brokerId: string,
    sourceRef: string,
    engine?: string,
    signal?: AbortSignal,
  ) =>
    request<Recommendations>(
      `/brokers/${brokerId}/loads/${encodeURIComponent(sourceRef)}/recommendations?limit=8` +
        (engine ? `&engine=${encodeURIComponent(engine)}` : ""),
      signal,
    ),
  lanes: (brokerId: string, signal?: AbortSignal) =>
    request<LaneSummary[]>(`/brokers/${brokerId}/lanes`, signal),
};

export interface Resource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/**
 * Minimal data-fetching hook. Deliberately not react-query: one dependency
 * fewer, and nothing here needs caching or background refetching.
 *
 * `deps` controls refetching; `fetcher` is intentionally not a dependency so an
 * inline arrow function does not cause a fetch loop.
 */
export function useResource<T>(fetcher: (signal: AbortSignal) => Promise<T>, deps: unknown[]): Resource<T> {
  const [state, setState] = useState<Resource<T>>({ data: null, error: null, loading: true });

  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true, error: null }));

    fetcher(controller.signal)
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          data: null,
          error: error instanceof Error ? error.message : "Request failed",
          loading: false,
        });
      });

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
