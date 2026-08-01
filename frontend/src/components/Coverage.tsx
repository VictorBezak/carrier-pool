import type { Recommendations } from "../api/types";
import { money } from "../format";

/**
 * Cover or reprice, answered before the call list.
 *
 * A ranked list of carriers quietly asserts that the load is worth covering. When
 * it is not, the ranking is not merely unhelpful but actively misleading: on a load
 * that loses money at every rate, expected value favours carriers *unlikely to
 * accept*, since one that declines costs only the phone call while one that accepts
 * locks in the loss. Worked top-down, the list sends a dispatcher after carriers who
 * will say no.
 *
 * So this sits above the list and, when the answer is "do not cover", replaces the
 * question "who do I call" with the only actionable number on such a load: what it
 * has to bill to be worth calling anyone about.
 */
export function Coverage({ result }: { result: Recommendations }) {
  const coverage = result.coverage;
  // Null for engines with no notion of value; they cannot tell a load worth
  // covering from one that is not, and should not pretend to.
  if (!coverage) return null;

  const reprice = coverage.decision === "REPRICE";
  const target = coverage.target;

  return (
    <section className={`coverage coverage-${coverage.decision.toLowerCase()}`}>
      <div className="coverage-head">
        <span className="coverage-verdict">{reprice ? "Do not cover" : "Cover"}</span>
        <h2>{coverage.headline}</h2>
      </div>
      <p className="coverage-detail">{coverage.detail}</p>

      {reprice && target && (
        <dl className="coverage-numbers">
          <div>
            <dt>Bills now</dt>
            <dd>{money(target.current_revenue_usd)}</dd>
          </div>
          <div>
            <dt>Needs to bill</dt>
            <dd className="coverage-required">{money(target.required_revenue_usd)}</dd>
          </div>
          <div>
            <dt>Short by</dt>
            <dd>
              {money(target.shortfall_usd)}
              <span className="muted"> ({target.shortfall_pct.toFixed(0)}%)</span>
            </dd>
          </div>
          <div>
            <dt>Then offer</dt>
            <dd>
              {money(target.offer_rate_usd)}
              <span className="muted">
                {" "}
                to {target.carrier_name}, {(target.acceptance_probability * 100).toFixed(0)}% likely
              </span>
            </dd>
          </div>
        </dl>
      )}

      {reprice && target && (
        <p className="muted coverage-note">
          {target.carrier_name} is the cheapest route back to viability rather than the top of the
          list below, which is a different question. Carriers unlikely to have the trailer need far
          more revenue to justify calling them, because most of those calls are wasted.
        </p>
      )}
    </section>
  );
}
