import type { ReactNode } from "react";
import type { Confidence, LoadStatus } from "../api/types";
import { STATUS_LABELS } from "../format";

export function StatusPill({ status }: { status: LoadStatus }) {
  return <span className={`pill pill-${status.toLowerCase()}`}>{STATUS_LABELS[status]}</span>;
}

export function ConfidencePill({ confidence }: { confidence: Confidence }) {
  return <span className={`pill pill-${confidence}`}>{confidence} confidence</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="state">{children}</p>;
}

export function Loading({ what }: { what: string }) {
  return <p className="state">Loading {what}…</p>;
}

export function ErrorNote({ message }: { message: string }) {
  return <p className="state state-error">Could not load: {message}</p>;
}
