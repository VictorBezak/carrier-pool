import type { ReactNode } from "react";
import type { ChangeKind, Confidence, LoadStatus, Sentiment } from "../api/types";
import { STATUS_LABELS } from "../format";

export function StatusPill({ status }: { status: LoadStatus }) {
  return <span className={`pill pill-status pill-${status.toLowerCase()}`}>{STATUS_LABELS[status]}</span>;
}

export function ConfidencePill({ confidence }: { confidence: Confidence }) {
  return (
    <span className={`pill pill-confidence pill-${confidence}`}>{confidence} confidence</span>
  );
}

export function ChangeKindPill({ kind }: { kind: ChangeKind }) {
  const labels: Record<ChangeKind, string> = {
    PROGRESS: "progressed",
    REVEALED: "became known",
    CORRECTION: "corrected",
    // Named for the business event rather than the mechanism. The feed only shows
    // a status going backwards, but what happened is a carrier walking away.
    FALL_OFF: "carrier fell off",
    DETAIL: "detail changed",
  };
  return <span className={`pill pill-change pill-${kind.toLowerCase()}`}>{labels[kind]}</span>;
}

/** A reason with the points it contributed, so text and arithmetic stay together. */
export function ReasonRow({ label, detail, sentiment, points }: {
  label: string;
  detail: string;
  sentiment: Sentiment;
  points?: number | null;
}) {
  return (
    <li className={`reason reason-${sentiment}`}>
      {points != null && <span className="reason-points">{points.toFixed(1)}</span>}
      <span className="reason-body">
        <strong>{label}.</strong> {detail}
      </span>
    </li>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function Card({ title, subtitle, aside, children }: {
  title: string;
  subtitle?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      <header className="card-header">
        <div>
          <h2>{title}</h2>
          {subtitle && <p className="card-subtitle">{subtitle}</p>}
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function Loading({ what }: { what: string }) {
  return <p className="empty">Loading {what}…</p>;
}

export function ErrorNote({ message }: { message: string }) {
  return <p className="error">Could not load: {message}</p>;
}
