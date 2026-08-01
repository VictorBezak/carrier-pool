import type { Recommendations } from "../api/types";
import { Card } from "./atoms";

/**
 * What was ruled out, and what could not be checked at all.
 *
 * A carrier missing from a recommendation list with no explanation is
 * indistinguishable from a bug, and a dispatcher who looks for a carrier they
 * expected and cannot find it stops trusting the whole list. So exclusions are
 * shown as first-class output rather than filtered away.
 *
 * The second half is the more uncomfortable one. Authority, insurance, safety
 * scores and blocklists are hard gates any real system must enforce, and nothing
 * in these three TMS feeds carries them. Rendering that absence is the difference
 * between a known gap and an unstated assumption.
 */
export function Eligibility({ result }: { result: Recommendations }) {
  const { exclusions, unchecked_gates: unchecked, limitations } = result;
  if (exclusions.length === 0 && unchecked.length === 0 && limitations.length === 0) {
    return null;
  }

  return (
    <Card
      title="Who was ruled out, and what we could not check"
      subtitle="Eligibility is a gate, not a penalty: a carrier that cannot take the load is removed rather than ranked last."
    >
      {exclusions.length > 0 && (
        <ul className="exclusions">
          {exclusions.map((exclusion) => (
            <li key={exclusion.carrier_id} className="exclusion">
              <span className="exclusion-name">{exclusion.carrier_name}</span>
              <span className="exclusion-gate">{exclusion.gate_label}</span>
              <span className="exclusion-detail">{exclusion.detail}</span>
            </li>
          ))}
        </ul>
      )}

      {unchecked.length > 0 && (
        <details className="breakdown" open={exclusions.length === 0}>
          <summary>
            {unchecked.length} hard gate{unchecked.length === 1 ? "" : "s"} could not be evaluated
          </summary>
          <ul className="exclusions">
            {unchecked.map((gate) => (
              <li key={gate.gate} className="exclusion exclusion-unchecked">
                <span className="exclusion-name">{gate.gate_label}</span>
                <span className="exclusion-detail">{gate.detail}</span>
              </li>
            ))}
          </ul>
          <p className="muted">
            These are not enforced anywhere in the pipeline. A carrier whose insurance lapsed looks
            identical to one in good standing, so nothing here should be treated as a compliance
            check.
          </p>
        </details>
      )}

      {limitations.length > 0 && (
        <details className="breakdown">
          <summary>Known limits of this answer</summary>
          <ul className="limitations">
            {limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}
