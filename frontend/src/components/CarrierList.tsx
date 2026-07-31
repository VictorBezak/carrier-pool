import type { CarrierRecommendation, EngineInfo } from "../api/types";
import { Card, Empty, ReasonRow } from "../components/atoms";
import { dateTime, money, perMile } from "../format";

/**
 * "Which of my carriers should I call first, and why?"
 *
 * The ranking is only half the answer. Each card carries the reasons that
 * produced the score, the points each reason was worth, and an honest note about
 * how much evidence sits behind it — so a dispatcher can disagree with the order
 * for a stated reason rather than just distrusting it.
 */
export function CarrierList({
  carriers,
  considered,
  engine,
  asOf,
}: {
  carriers: CarrierRecommendation[];
  considered: number;
  engine: EngineInfo;
  asOf: string;
}) {
  if (carriers.length === 0) {
    return (
      <Card title="Who to call">
        <Empty>
          This broker has no carrier with any booked history, so there is nothing to rank yet.
        </Empty>
      </Card>
    );
  }

  return (
    <Card
      title="Who to call, in order"
      subtitle={
        <>
          {considered} carrier{considered === 1 ? "" : "s"} with booked history were scored using{" "}
          <strong>{engine.name}</strong> v{engine.version}. History is current as of{" "}
          {dateTime(asOf)}.
        </>
      }
    >
      <ol className="carriers">
        {carriers.map((carrier) => (
          <CarrierCard key={carrier.carrier_id} carrier={carrier} />
        ))}
      </ol>
      <p className="engine-note">{engine.description}</p>
    </Card>
  );
}

function CarrierCard({ carrier }: { carrier: CarrierRecommendation }) {
  return (
    <li className="carrier">
      <div className="carrier-head">
        <div className="carrier-rank">{carrier.rank}</div>
        <div className="carrier-identity">
          <div className="carrier-name">{carrier.carrier_name}</div>
          <div className="muted carrier-contact">
            {carrier.mc_number && <>MC {carrier.mc_number}</>}
            {carrier.mc_number && carrier.phone && " · "}
            {carrier.phone}
          </div>
        </div>
        <div className="carrier-numbers">
          <div className="carrier-open">
            <span className="label">Open the call at</span>
            <span className="value">{money(carrier.suggested_rate_usd)}</span>
          </div>
          <div className="carrier-score">
            <span className="label">Score</span>
            <span className="value">{carrier.score.toFixed(1)}</span>
          </div>
        </div>
      </div>

      <div className="score-bar" role="img" aria-label={`Score ${carrier.score} out of 100`}>
        {carrier.components.map((component) => (
          <span
            key={component.key}
            className={`score-seg seg-${component.key}`}
            style={{ width: `${component.points}%` }}
            title={`${component.label}: ${component.points.toFixed(1)} of ${(component.weight * 100).toFixed(0)} possible`}
          />
        ))}
      </div>

      <div className={carrier.history_depth.is_thin ? "depth depth-thin" : "depth"}>
        {carrier.history_depth.label}
        {" · "}
        {carrier.loads_total} booked load{carrier.loads_total === 1 ? "" : "s"} total,{" "}
        {carrier.loads_on_lane} on this lane
        {carrier.days_since_last_load != null && <> · last ran {carrier.days_since_last_load}d ago</>}
        {carrier.last_delivery_market_label && <> · truck last dropped in {carrier.last_delivery_market_label}</>}
      </div>

      <ul className="reasons">
        {carrier.reasons.map((reason) => (
          <ReasonRow key={reason.label} {...reason} />
        ))}
      </ul>

      <details className="breakdown">
        <summary>Score breakdown</summary>
        <table className="table table-compact">
          <thead>
            <tr>
              <th>Signal</th>
              <th className="numeric">Weight</th>
              <th className="numeric">Strength</th>
              <th className="numeric">Points</th>
            </tr>
          </thead>
          <tbody>
            {carrier.components.map((component) => (
              <tr key={component.key}>
                <td>{component.label}</td>
                <td className="numeric">{(component.weight * 100).toFixed(0)}</td>
                <td className="numeric">{(component.value * 100).toFixed(0)}%</td>
                <td className="numeric">{component.points.toFixed(1)}</td>
              </tr>
            ))}
            <tr className="total-row">
              <td colSpan={3}>Total</td>
              <td className="numeric">{carrier.score.toFixed(1)}</td>
            </tr>
          </tbody>
        </table>
        {carrier.median_lane_rate_per_mile != null && (
          <p className="muted">
            This carrier's median rate on this lane is {perMile(carrier.median_lane_rate_per_mile)},
            which is what pulls its suggested opening rate away from the lane estimate.
          </p>
        )}
      </details>
    </li>
  );
}
