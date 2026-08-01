import type {
  CarrierRecommendation,
  OfferPlan,
  Prediction,
  PriorOffer,
  Recommendations,
} from "../api/types";
import { Card, Empty, ReasonRow } from "../components/atoms";
import { dateTime, money, perMile } from "../format";

/**
 * "Which of my carriers should I call first, what should I offer, and why?"
 *
 * The order is the least interesting part of the answer. What a dispatcher can
 * actually act on is the rate to open at and the odds it lands, and what lets
 * them disagree with the ranking for a *stated reason* is seeing the arithmetic
 * that produced it — including how much of each estimate is really just the
 * population average wearing a carrier's name.
 *
 * Two engines feed this component. The expected-value engine fills in
 * `offer_plan`; the heuristic leaves it null and only has an ordinal score. The
 * card renders whichever is present rather than pretending they are the same
 * kind of number.
 */
export function CarrierList({ result }: { result: Recommendations }) {
  const { carriers, engine, carriers_considered: considered, as_of: asOf } = result;

  if (carriers.length === 0) {
    return (
      <Card title="Who to call">
        <Empty>
          No carrier passed the eligibility gates for this load. The exclusions below say why.
        </Empty>
      </Card>
    );
  }

  return (
    <Card
      title="Who to call, in order"
      subtitle={
        <>
          {considered} eligible carrier{considered === 1 ? "" : "s"} ranked by{" "}
          <strong>{engine.name}</strong> v{engine.version}. History is current as of{" "}
          {dateTime(asOf)}.
        </>
      }
    >
      {engine.objective && <p className="engine-objective">Optimising: {engine.objective}</p>}
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
  const plan = carrier.offer_plan;
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
        {plan ? <OfferHeadline plan={plan} /> : <ScoreHeadline carrier={carrier} />}
      </div>

      {plan ? <ValueBar plan={plan} /> : <ScoreBar carrier={carrier} />}

      <div className={carrier.history_depth.is_thin ? "depth depth-thin" : "depth"}>
        {carrier.history_depth.label}
        {" · "}
        {carrier.loads_total} booked load{carrier.loads_total === 1 ? "" : "s"} total,{" "}
        {carrier.loads_on_lane} on this lane
        {carrier.days_since_last_load != null && <> · last ran {carrier.days_since_last_load}d ago</>}
        {carrier.last_delivery_market_label && (
          <> · truck last dropped in {carrier.last_delivery_market_label}</>
        )}
      </div>

      {carrier.prior_offers.length > 0 && <PriorOffers offers={carrier.prior_offers} />}

      <ul className="reasons">
        {carrier.reasons.map((reason) => (
          <ReasonRow key={reason.label} {...reason} />
        ))}
      </ul>

      {carrier.predictions.length > 0 && <Predictions predictions={carrier.predictions} />}

      {plan ? (
        <ValueBreakdown carrier={carrier} plan={plan} />
      ) : (
        <ScoreBreakdown carrier={carrier} />
      )}

      {carrier.surfaced_by.length > 0 && (
        <details className="breakdown">
          <summary>Why this carrier was considered at all</summary>
          <ul className="rule-list">
            {carrier.surfaced_by.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
          <p className="muted">
            At this scale every carrier is a candidate, so these rules change nothing today. They
            are the recall filter that would run instead of scoring thirty thousand carriers per
            load, and the record of which one surfaced a carrier is how a recall failure gets
            diagnosed later.
          </p>
        </details>
      )}
    </li>
  );
}

function OfferHeadline({ plan }: { plan: OfferPlan }) {
  return (
    <div className="carrier-numbers">
      <div className="carrier-open">
        <span className="label">Offer</span>
        <span className="value">{money(plan.offer_rate_usd)}</span>
        <span className="sub">{(plan.acceptance_probability * 100).toFixed(0)}% likely to land</span>
      </div>
      <div className="carrier-score">
        <span className="label">Expected value</span>
        <span className={plan.expected_value_usd >= 0 ? "value" : "value negative"}>
          {money(plan.expected_value_usd)}
        </span>
        {plan.value_per_hour_usd != null && (
          <span className="sub">{money(plan.value_per_hour_usd)}/hr of your time</span>
        )}
      </div>
    </div>
  );
}

function ScoreHeadline({ carrier }: { carrier: CarrierRecommendation }) {
  return (
    <div className="carrier-numbers">
      <div className="carrier-open">
        <span className="label">Open the call at</span>
        <span className="value">{money(carrier.suggested_rate_usd)}</span>
      </div>
      <div className="carrier-score">
        <span className="label">Score</span>
        <span className="value">{carrier.score.toFixed(1)}</span>
        <span className="sub">ordinal, no units</span>
      </div>
    </div>
  );
}

/**
 * The expected-value bar shows the *range* rather than a point, because with this
 * little data the range is the honest answer. A wide bar on an unfamiliar carrier
 * is the reason it is worth calling, not a reason to skip it.
 */
function ValueBar({ plan }: { plan: OfferPlan }) {
  const low = Math.min(plan.pessimistic_value_usd, 0);
  const high = Math.max(plan.optimistic_value_usd, 0);
  const span = high - low || 1;
  const pct = (value: number) => ((value - low) / span) * 100;

  return (
    <div className="value-bar" title={`${money(plan.pessimistic_value_usd)} to ${money(plan.optimistic_value_usd)}`}>
      <span
        className="value-range"
        style={{
          left: `${pct(plan.pessimistic_value_usd)}%`,
          width: `${pct(plan.optimistic_value_usd) - pct(plan.pessimistic_value_usd)}%`,
        }}
      />
      <span className="value-point" style={{ left: `${pct(plan.expected_value_usd)}%` }} />
      {low < 0 && <span className="value-zero" style={{ left: `${pct(0)}%` }} />}
    </div>
  );
}

function ScoreBar({ carrier }: { carrier: CarrierRecommendation }) {
  return (
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
  );
}

function PriorOffers({ offers }: { offers: PriorOffer[] }) {
  return (
    <div className="prior-offers">
      <span className="prior-offers-label">Already asked</span>
      {offers.map((offer) => (
        <span key={offer.offered_at} className={`prior-offer outcome-${offer.outcome.toLowerCase()}`}>
          {money(offer.offered_rate_usd)} · {offer.outcome.toLowerCase().replace("_", " ")}
          {offer.counter_rate_usd != null && <> · wants {money(offer.counter_rate_usd)}</>}
          {offer.response_minutes != null && <> · replied in {Math.round(offer.response_minutes)}m</>}
        </span>
      ))}
    </div>
  );
}

/**
 * Component predictions with the share of each that is really the prior.
 *
 * This column is the one that keeps the whole thing honest: "97% on-time" and
 * "97% on-time, of which 80% is just the average carrier" are very different
 * claims, and only one of them should move a decision.
 */
function Predictions({ predictions }: { predictions: Prediction[] }) {
  return (
    <details className="breakdown">
      <summary>What we predict, and how much we actually know</summary>
      <table className="table table-compact">
        <thead>
          <tr>
            <th>Component</th>
            <th className="numeric">Estimate</th>
            <th className="numeric">Own data</th>
            <th>Leaning on</th>
          </tr>
        </thead>
        <tbody>
          {predictions.map((prediction) => (
            <tr key={prediction.key}>
              <td>
                {prediction.label}
                {prediction.note && <div className="muted small">{prediction.note}</div>}
              </td>
              <td className="numeric">{prediction.display}</td>
              <td className="numeric">
                {((1 - prediction.prior_share) * 100).toFixed(0)}%
                <div className="muted small">{prediction.observations} obs</div>
              </td>
              <td className="small">
                {prediction.prior_share >= 0.5 ? (
                  <span className="prior-heavy">mostly {prediction.prior_label}</span>
                ) : (
                  <span className="muted">{prediction.prior_label}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function ValueBreakdown({
  carrier,
  plan,
}: {
  carrier: CarrierRecommendation;
  plan: OfferPlan;
}) {
  return (
    <details className="breakdown">
      <summary>How the expected value was arrived at</summary>
      <table className="table table-compact">
        <thead>
          <tr>
            <th>Term</th>
            <th className="numeric">Dollars</th>
            <th>What it is</th>
          </tr>
        </thead>
        <tbody>
          {carrier.components.map((component) => (
            <tr key={component.key}>
              <td>{component.label}</td>
              <td className={component.points < 0 ? "numeric negative" : "numeric"}>
                {money(component.points)}
              </td>
              <td className="small muted">
                {plan.value_terms.find((term) => term.key === component.key)?.detail ??
                  (component.key === "time_to_resolve"
                    ? `Expected value spread over the ${component.value}h this call is likely to take, so a fast answer outranks a slightly richer slow one.`
                    : component.key === "uncertainty_credit"
                      ? `${(component.weight * 100).toFixed(0)}% of the ${money(component.value)} upside, because a phone call is a cheap way to find out.`
                      : "")}
              </td>
            </tr>
          ))}
          <tr className="total-row">
            <td>Ranking score</td>
            <td className="numeric">{money(carrier.score)}</td>
            <td className="small muted">Per hour of broker time, credited for resolvable upside.</td>
          </tr>
        </tbody>
      </table>
      <p className="muted">
        Offer {money(plan.offer_rate_usd)} for {(plan.acceptance_probability * 100).toFixed(0)}%
        odds; {money(plan.rate_ceiling_usd)} would make it 90%. Past{" "}
        {money(plan.walk_away_rate_usd)} this load stops being worth covering with them at all.
      </p>
    </details>
  );
}

function ScoreBreakdown({ carrier }: { carrier: CarrierRecommendation }) {
  return (
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
  );
}
