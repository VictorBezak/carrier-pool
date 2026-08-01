import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import type { CarrierRecommendation, LoadDetail, Offer, Recommendations } from "../api/types";
import { ConfidencePill } from "./atoms";
import {
  EQUIPMENT_LABELS,
  dateTime,
  fieldLabel,
  miles,
  money,
  perMile,
  percent,
  pounds,
  shortDate,
} from "../format";

export const TABS = [
  { key: "call", label: "This call" },
  { key: "ruled-out", label: "Ruled out" },
  { key: "price", label: "The price" },
  { key: "load", label: "The load" },
  { key: "engine", label: "Engine" },
] as const;

export type WorkTab = (typeof TABS)[number]["key"];

/**
 * Everything the old page showed at once, kept in full and moved one click away.
 *
 * The depth here is the reason to believe the answer, so none of it is deleted - the
 * prior shares, the unchecked gates, the audit trail and the arithmetic are all still
 * reachable. What changed is that they are no longer competing with the answer for
 * attention. Eighteen separate disclosure toggles scattered down a page read as dense
 * even while collapsed, because every summary line is one more thing to decide whether
 * to read.
 *
 * A sheet rather than an inline expansion, so the call stays on screen behind it: the
 * point of opening this is usually to check one number against the recommendation, not
 * to leave it.
 */
export function ShowTheWork({
  result,
  detail,
  carrier,
  brokerId,
  engine,
  onEngineChange,
  tab,
  onTab,
  onClose,
}: {
  result: Recommendations;
  detail: LoadDetail;
  carrier: CarrierRecommendation | undefined;
  brokerId: string;
  engine: string;
  onEngineChange: (key: string) => void;
  tab: WorkTab;
  onTab: (tab: WorkTab) => void;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<Element | null>(null);

  useEffect(() => {
    restoreTo.current = document.activeElement;
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      // Keep Tab inside the sheet. Without this the focus ring walks off into the page
      // behind it, which is invisible to a mouse user and completely disorienting to
      // anyone on a keyboard.
      if (event.key !== "Tab" || !panel.current) return;
      const focusable = panel.current.querySelectorAll<HTMLElement>(
        'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      const active = document.activeElement;
      if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && (active === first || active === panel.current)) {
        event.preventDefault();
        last.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    // Nothing behind the sheet should scroll while it is open.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
      (restoreTo.current as HTMLElement | null)?.focus?.();
    };
  }, [onClose]);

  return (
    <div className="sheet-scrim" onMouseDown={onClose}>
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="How this answer was produced"
        tabIndex={-1}
        ref={panel}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="sheet-head">
          <div>
            <span className="eyebrow">How this answer was produced</span>
            <h2>Load {detail.reference}</h2>
          </div>
          <button type="button" className="sheet-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="sheet-tabs" role="tablist">
          {TABS.map((entry) => (
            <button
              key={entry.key}
              role="tab"
              type="button"
              aria-selected={entry.key === tab}
              className={entry.key === tab ? "sheet-tab is-active" : "sheet-tab"}
              onClick={() => onTab(entry.key)}
            >
              {entry.label}
            </button>
          ))}
        </div>

        <div className="sheet-body">
          {tab === "call" && <CallWork carrier={carrier} />}
          {tab === "ruled-out" && <RuledOut result={result} />}
          {tab === "price" && (
            <PriceWork result={result} detail={detail} brokerId={brokerId} />
          )}
          {tab === "load" && <LoadWork detail={detail} />}
          {tab === "engine" && (
            <EngineWork result={result} engine={engine} onEngineChange={onEngineChange} />
          )}
        </div>
      </div>
    </div>
  );
}

/* ---- this call ------------------------------------------------------- */

function CallWork({ carrier }: { carrier: CarrierRecommendation | undefined }) {
  if (!carrier) return <p className="prose">No carrier selected.</p>;
  const plan = carrier.offer_plan;

  return (
    <>
      <h3 className="work-title">{carrier.carrier_name}</h3>

      {carrier.predictions.length > 0 && (
        <section className="work-block">
          <h4>What we predict, and how much of it we actually know</h4>
          <p className="prose">
            The right column is the one that keeps this honest. "97% on time" and "97% on time, of
            which most is just the average carrier" are different claims, and only one of them
            should move a decision.
          </p>
          <table className="grid">
            <thead>
              <tr>
                <th>Component</th>
                <th className="numeric">Estimate</th>
                <th className="numeric">From their own record</th>
                <th>Otherwise leaning on</th>
              </tr>
            </thead>
            <tbody>
              {carrier.predictions.map((prediction) => (
                <tr key={prediction.key}>
                  <td>
                    {prediction.label}
                    {prediction.note && <div className="cell-note">{prediction.note}</div>}
                  </td>
                  <td className="numeric fig">{prediction.display}</td>
                  <td className="numeric fig">
                    {percent(1 - prediction.prior_share)}
                    <div className="cell-note">{prediction.observations} obs</div>
                  </td>
                  <td className={prediction.prior_share >= 0.5 ? "cell-warn" : "cell-quiet"}>
                    {prediction.prior_share >= 0.5 ? "mostly " : ""}
                    {prediction.prior_label}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="work-block">
        <h4>{plan ? "How the expected value was arrived at" : "How the score was arrived at"}</h4>
        <table className="grid">
          <thead>
            <tr>
              <th>Term</th>
              <th className="numeric">{plan ? "Dollars" : "Points"}</th>
              <th>What it is</th>
            </tr>
          </thead>
          <tbody>
            {carrier.components.map((component) => (
              <tr key={component.key}>
                <td>{component.label}</td>
                <td
                  className={component.points < 0 ? "numeric fig is-negative" : "numeric fig"}
                >
                  {plan ? money(component.points) : component.points.toFixed(1)}
                </td>
                <td className="cell-quiet">
                  {plan?.value_terms.find((term) => term.key === component.key)?.detail ??
                    (component.key === "time_to_resolve"
                      ? `Spread over the ${component.value}h this call is likely to take, so a fast answer outranks a slightly richer slow one.`
                      : component.key === "uncertainty_credit"
                        ? `${percent(component.weight)} of the ${money(component.value)} upside, because a phone call is a cheap way to find out.`
                        : `Weight ${percent(component.weight)}, strength ${percent(component.value)}.`)}
                </td>
              </tr>
            ))}
            <tr className="grid-total">
              <td>{plan ? "Ranking score" : "Total"}</td>
              <td className="numeric fig">
                {plan ? money(carrier.score) : carrier.score.toFixed(1)}
              </td>
              <td className="cell-quiet">
                {plan
                  ? "Per hour of broker time, credited for resolvable upside."
                  : "Ordinal. These points have no units and are not dollars."}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      {carrier.median_lane_rate_per_mile != null && (
        <p className="prose work-aside">
          This carrier's own median on this lane is{" "}
          <strong className="fig">{perMile(carrier.median_lane_rate_per_mile)}</strong>, which is
          what pulls their opening rate away from the lane estimate.
        </p>
      )}

      <section className="work-block">
        <h4>Every reason, in full</h4>
        <ul className="work-reasons">
          {carrier.reasons.map((reason) => (
            <li key={reason.label} className={`cr cr-${reason.sentiment}`}>
              <strong>{reason.label}.</strong> {reason.detail}
            </li>
          ))}
        </ul>
      </section>

      {carrier.surfaced_by.length > 0 && (
        <section className="work-block">
          <h4>Why this carrier was considered at all</h4>
          <ul className="work-rules">
            {carrier.surfaced_by.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
          <p className="prose">
            At this scale every carrier is a candidate, so these rules change nothing today. They
            are the recall filter that would run instead of scoring thirty thousand carriers per
            load, and the record of which rule surfaced a carrier is how a recall failure gets
            diagnosed later.
          </p>
        </section>
      )}
    </>
  );
}

/* ---- ruled out ------------------------------------------------------- */

function RuledOut({ result }: { result: Recommendations }) {
  const { exclusions, unchecked_gates: unchecked } = result;

  return (
    <>
      <section className="work-block">
        <h4>Ruled out, with the reason</h4>
        <p className="prose">
          A carrier missing from a list with no explanation is indistinguishable from a bug, and a
          dispatcher who looks for someone they expected and can't find them stops trusting the
          whole list.
        </p>
        {exclusions.length === 0 ? (
          <p className="prose cell-quiet">Nobody was ruled out on this load.</p>
        ) : (
          <ul className="ruled">
            {exclusions.map((exclusion) => (
              <li key={exclusion.carrier_id}>
                <div className="ruled-head">
                  <strong>{exclusion.carrier_name}</strong>
                  <span className="flag">{exclusion.gate_label}</span>
                </div>
                <p>{exclusion.detail}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {unchecked.length > 0 && (
        <section className="work-block work-block-warn">
          <h4>{unchecked.length} hard gates nothing here can check</h4>
          <p className="prose">
            These are not enforced anywhere in the pipeline, because no TMS feed carries them. A
            carrier whose insurance lapsed looks identical to one in good standing, so nothing on
            this page is a compliance check.
          </p>
          <ul className="ruled">
            {unchecked.map((gate) => (
              <li key={gate.gate}>
                <div className="ruled-head">
                  <strong>{gate.gate_label}</strong>
                </div>
                <p>{gate.detail}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

/* ---- the price ------------------------------------------------------- */

function PriceWork({
  result,
  detail,
  brokerId,
}: {
  result: Recommendations;
  detail: LoadDetail;
  brokerId: string;
}) {
  const estimate = result.price_estimate;
  if (!estimate) {
    return (
      <p className="prose">
        Not enough history to estimate a rate for this load. That is a real answer rather than a
        bug — this broker has no comparable priced loads to reason from.
      </p>
    );
  }

  const impliedMargin =
    detail.customer_rate == null ? null : detail.customer_rate - estimate.point_usd;

  return (
    <>
      <section className="work-block">
        <h4>What the lane says this should cost</h4>
        <div className="priceband">
          <div>
            <span className="eyebrow">Expected</span>
            <span className="fig priceband-point">{money(estimate.point_usd)}</span>
            <span className="cell-quiet">{perMile(estimate.rate_per_mile)}</span>
          </div>
          <div>
            <span className="eyebrow">Range</span>
            <span className="fig priceband-range">
              {money(estimate.low_usd)} – {money(estimate.high_usd)}
            </span>
            <span className="cell-quiet">
              {estimate.sample_size} comparable load{estimate.sample_size === 1 ? "" : "s"} from{" "}
              {estimate.basis_label}
            </span>
          </div>
          {impliedMargin != null && (
            <div>
              <span className="eyebrow">Margin at current rate</span>
              <span className="fig priceband-margin">{money(impliedMargin)}</span>
            </div>
          )}
          <div className="priceband-confidence">
            <ConfidencePill confidence={estimate.confidence} />
          </div>
        </div>
        <ul className="work-reasons">
          {estimate.reasons.map((reason) => (
            <li key={reason.label} className={`cr cr-${reason.sentiment}`}>
              <strong>{reason.label}.</strong> {reason.detail}
            </li>
          ))}
        </ul>
      </section>

      <section className="work-block">
        <h4>The {estimate.comparables.length} loads it came from</h4>
        <table className="grid">
          <thead>
            <tr>
              <th>Load</th>
              <th>Lane</th>
              <th>Carrier</th>
              <th className="numeric">Paid</th>
              <th className="numeric">Rate</th>
              <th>Delivered</th>
            </tr>
          </thead>
          <tbody>
            {estimate.comparables.map((comparable) => (
              <tr key={comparable.load_id}>
                <td className="fig">
                  <Link
                    to={`/brokers/${brokerId}/loads/${encodeURIComponent(comparable.source_ref)}`}
                  >
                    {comparable.reference}
                  </Link>
                </td>
                <td>{comparable.lane_label}</td>
                <td>{comparable.carrier_name ?? "—"}</td>
                <td className="numeric fig">{money(comparable.carrier_rate)}</td>
                <td className="numeric fig">{perMile(comparable.rate_per_mile)}</td>
                <td>{shortDate(comparable.delivered_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

/* ---- the load -------------------------------------------------------- */

function LoadWork({ detail }: { detail: LoadDetail }) {
  return (
    <>
      <section className="work-block">
        <h4>Load details</h4>
        <dl className="facts">
          <Fact label="Reference">{detail.reference}</Fact>
          <Fact label="Customer">{detail.customer_name ?? "—"}</Fact>
          <Fact label="Equipment">{EQUIPMENT_LABELS[detail.equipment]}</Fact>
          {detail.commodity && <Fact label="Commodity">{detail.commodity}</Fact>}
          <Fact label="Weight">{pounds(detail.weight_lbs)}</Fact>
          <Fact label="Distance">{miles(detail.distance_miles)}</Fact>
          <Fact label="Booked carrier">{detail.carrier_name ?? "—"}</Fact>
          <Fact label="Paid rate">{money(detail.carrier_rate)}</Fact>
          <Fact label="Source TMS">{detail.source_tms}</Fact>
          <Fact label="Seen in syncs">{String(detail.sync_count)}</Fact>
        </dl>
      </section>

      <section className="work-block">
        <h4>Stops</h4>
        <p className="prose">
          Each stop resolves to a metro market, which is the unit lane history is grouped by.
        </p>
        <ol className="stops">
          {detail.stops.map((stop) => {
            const onTime = stop.kind === "PICKUP" ? detail.pickup_on_time : detail.delivery_on_time;
            return (
              <li key={stop.sequence} className={`stop stop-${stop.kind.toLowerCase()}`}>
                <span className="eyebrow">{stop.kind.toLowerCase()}</span>
                <div>
                  {stop.location_name && <div className="stop-name">{stop.location_name}</div>}
                  <div>
                    {stop.city}, {stop.state} {stop.postal_code}
                  </div>
                  <div className="cell-quiet">
                    {stop.market_label}
                    {stop.scheduled_start && ` · scheduled ${shortDate(stop.scheduled_start)}`}
                  </div>
                  {stop.actual_arrival && (
                    <div className="cell-quiet">arrived {dateTime(stop.actual_arrival)}</div>
                  )}
                  {onTime !== null && (
                    <div className={onTime ? "ontime is-good" : "ontime is-bad"}>
                      {onTime ? "hit the appointment" : "missed the appointment day"}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {detail.offers.length > 0 && (
        <section className="work-block">
          <h4>Offers already made on this load</h4>
          <p className="prose">
            Platform activity, not TMS data. No TMS records the calls that didn't land, which is
            exactly the evidence a price floor has to be estimated from.
          </p>
          <table className="grid">
            <thead>
              <tr>
                <th>Carrier</th>
                <th className="numeric">Offered</th>
                <th>Outcome</th>
                <th className="numeric">Countered</th>
                <th className="numeric">Replied in</th>
              </tr>
            </thead>
            <tbody>
              {detail.offers.map((offer) => (
                <tr key={offer.offer_id}>
                  <td>{offer.carrier_name}</td>
                  <td className="numeric fig">{money(offer.offered_rate)}</td>
                  <td>{offer.outcome.toLowerCase().replace("_", " ")}</td>
                  <td className="numeric fig">
                    {offer.counter_rate == null ? "—" : money(offer.counter_rate)}
                  </td>
                  <td className="numeric fig">{replyTime(offer)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="work-block">
        <h4>How this load arrived</h4>
        <p className="prose">
          Freight data is messy and amounts get restated, so every change is kept with the sync file
          that carried it.
        </p>
        {detail.history.length === 0 ? (
          <p className="prose cell-quiet">This load has only ever appeared in one sync.</p>
        ) : (
          <ol className="changelog">
            {detail.history.map((entry, index) => (
              <li
                key={`${entry.field}-${entry.observed_at}-${index}`}
                className={`change change-${entry.kind.toLowerCase()}`}
              >
                <div className="change-head">
                  <strong>{fieldLabel(entry.field)}</strong>
                  <span className="flag">{entry.kind.toLowerCase().replace("_", " ")}</span>
                </div>
                <div className="fig change-values">
                  {entry.old_value ?? "not set"} → {entry.new_value ?? "cleared"}
                </div>
                <div className="cell-quiet">
                  {dateTime(entry.observed_at)} · {entry.source_file}
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
    </>
  );
}

/**
 * How long a carrier took to reply. Silence has no duration, which is different from
 * a fast reply and different again from a slow one, so it stays blank rather than
 * being rendered as zero.
 */
function replyTime(offer: Offer): string {
  if (!offer.responded_at) return "—";
  const minutes =
    (new Date(offer.responded_at).getTime() - new Date(offer.offered_at).getTime()) / 60000;
  if (minutes < 60) return `${Math.round(minutes)}m`;
  return `${(minutes / 60).toFixed(1)}h`;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="fact">
      <dt className="eyebrow">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/* ---- engine ---------------------------------------------------------- */

function EngineWork({
  result,
  engine,
  onEngineChange,
}: {
  result: Recommendations;
  engine: string;
  onEngineChange: (key: string) => void;
}) {
  return (
    <>
      <section className="work-block">
        <h4>Which model produced this</h4>
        <p className="prose">
          Two engines run on identical data through one contract, so switching is a real comparison
          rather than a claim. Their scores are not comparable — the heuristic's are ordinal and the
          expected-value engine's are dollars per hour — only the resulting order is.
        </p>
        <div className="enginepick">
          {(
            [
              ["expected-value", "Expected value"],
              ["simple-heuristic", "Weighted heuristic"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={engine === key ? "enginepick-tab is-active" : "enginepick-tab"}
              onClick={() => onEngineChange(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <dl className="facts">
          <Fact label="Running">
            {result.engine.name} v{result.engine.version}
          </Fact>
          <Fact label="Carriers considered">{String(result.carriers_considered)}</Fact>
          <Fact label="History current as of">{dateTime(result.as_of)}</Fact>
        </dl>
        {result.engine.objective && (
          <p className="prose">
            <strong>Optimising:</strong> {result.engine.objective}
          </p>
        )}
        <p className="prose cell-quiet">{result.engine.description}</p>
      </section>

      {result.limitations.length > 0 && (
        <section className="work-block work-block-warn">
          <h4>Known limits of this answer</h4>
          <ul className="work-rules">
            {result.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
