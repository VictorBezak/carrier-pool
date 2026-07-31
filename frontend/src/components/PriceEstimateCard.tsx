import { Link } from "react-router-dom";
import type { PriceEstimate } from "../api/types";
import { Card, ConfidencePill, Empty, ReasonRow } from "../components/atoms";
import { EQUIPMENT_LABELS, miles, money, perMile, shortDate } from "../format";

/**
 * "What should I expect to pay a carrier for this load?"
 *
 * The number on its own is not the answer. What makes it usable is the band
 * around it, the basis it was drawn from, and the actual past loads underneath -
 * all of which are shown, because a broker has to be able to check the work.
 */
export function PriceEstimateCard({
  estimate,
  customerRate,
  brokerId,
}: {
  estimate: PriceEstimate | null;
  customerRate: number | null;
  brokerId: string;
}) {
  if (!estimate) {
    return (
      <Card title="What to expect to pay">
        <Empty>
          Not enough history to estimate a rate for this load. That is a real answer, not a bug —
          this broker has no comparable priced loads to reason from.
        </Empty>
      </Card>
    );
  }

  const impliedMargin = customerRate == null ? null : customerRate - estimate.point_usd;

  return (
    <Card
      title="What to expect to pay"
      subtitle={`Based on ${estimate.sample_size} comparable load${estimate.sample_size === 1 ? "" : "s"} from ${estimate.basis_label}.`}
      aside={<ConfidencePill confidence={estimate.confidence} />}
    >
      <div className="estimate">
        <div className="estimate-point">
          <div className="estimate-value">{money(estimate.point_usd)}</div>
          <div className="estimate-meta">{perMile(estimate.rate_per_mile)}</div>
        </div>
        <div className="estimate-band">
          <div className="band-label">Expected range</div>
          <div className="band-values">
            {money(estimate.low_usd)} – {money(estimate.high_usd)}
          </div>
          {impliedMargin != null && (
            <div className="band-label">
              Leaves roughly <strong>{money(impliedMargin)}</strong> margin at the current customer
              rate
            </div>
          )}
        </div>
      </div>

      <h3 className="section-heading">Why this number</h3>
      <ul className="reasons">
        {estimate.reasons.map((reason) => (
          <ReasonRow key={reason.label} {...reason} />
        ))}
      </ul>

      <details className="comparables">
        <summary>
          Show the {estimate.comparables.length} load
          {estimate.comparables.length === 1 ? "" : "s"} this came from
        </summary>
        <table className="table table-compact">
          <thead>
            <tr>
              <th>Load</th>
              <th>Lane</th>
              <th>Equipment</th>
              <th>Carrier</th>
              <th className="numeric">Distance</th>
              <th className="numeric">Paid</th>
              <th className="numeric">Rate</th>
              <th>Delivered</th>
            </tr>
          </thead>
          <tbody>
            {estimate.comparables.map((comparable) => (
              <tr key={comparable.load_id}>
                <td>
                  <Link to={`/brokers/${brokerId}/loads/${encodeURIComponent(comparable.source_ref)}`}>
                    {comparable.reference}
                  </Link>
                </td>
                <td>{comparable.lane_label}</td>
                <td>{EQUIPMENT_LABELS[comparable.equipment]}</td>
                <td>{comparable.carrier_name ?? "—"}</td>
                <td className="numeric">{miles(comparable.distance_miles)}</td>
                <td className="numeric">{money(comparable.carrier_rate)}</td>
                <td className="numeric">{perMile(comparable.rate_per_mile)}</td>
                <td>{shortDate(comparable.delivered_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </Card>
  );
}
