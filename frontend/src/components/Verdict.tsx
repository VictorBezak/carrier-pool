import type { Recommendations } from "../api/types";
import { money, percent } from "../format";

/**
 * Cover or reprice, in the road's own signalling vocabulary.
 *
 * Whether to work a load is decided before who to call, so it sits above the call
 * and takes the width of the page. Amber rather than red for "do not cover": nothing
 * has gone wrong, the load is simply priced below what it costs to move, and the next
 * action is a conversation with the customer rather than an error to clear.
 */
export function Verdict({ result }: { result: Recommendations }) {
  const coverage = result.coverage;
  // Null for engines with no notion of value; they cannot tell a load worth covering
  // from one that is not, and should not imply otherwise.
  if (!coverage) return null;

  const reprice = coverage.decision === "REPRICE";
  const target = coverage.target;

  if (!reprice) {
    return (
      <div className="verdict verdict-cover">
        <span className="verdict-mark" aria-hidden="true" />
        <p>
          <strong>Worth covering.</strong> Best expected value is{" "}
          <span className="fig">{money(coverage.best_expected_value_usd)}</span> on this load.
        </p>
      </div>
    );
  }

  return (
    <div className="verdict verdict-reprice">
      <div className="verdict-head">
        <span className="verdict-mark" aria-hidden="true" />
        <div>
          <h2>Don't cover this — reprice it</h2>
          <p>
            Every carrier who could haul this loses money at every rate they'd accept. Working down
            a call list is the wrong move here.
          </p>
        </div>
      </div>

      {target && (
        <div className="reprice">
          <div className="reprice-flow">
            <div>
              <span className="eyebrow">Bills now</span>
              <span className="fig reprice-from">{money(target.current_revenue_usd)}</span>
            </div>
            <span className="reprice-arrow" aria-hidden="true">
              →
            </span>
            <div>
              <span className="eyebrow">Needs to bill</span>
              <span className="fig reprice-to">{money(target.required_revenue_usd)}</span>
            </div>
            <div className="reprice-gap">
              <span className="eyebrow">Ask for</span>
              <span className="fig reprice-delta">
                {money(target.shortfall_usd)}
                <span className="reprice-pct"> · {target.shortfall_pct.toFixed(0)}%</span>
              </span>
            </div>
          </div>
          <p className="reprice-note">
            At that rate <strong>{target.carrier_name}</strong> becomes worth calling, at{" "}
            <span className="fig">{percent(target.acceptance_probability)}</span> to accept — the
            cheapest of the eligible carriers to make this load viable. Carriers unlikely to have
            the right trailer need far more revenue to justify a call, because most of those calls
            are wasted.
          </p>
        </div>
      )}
    </div>
  );
}
