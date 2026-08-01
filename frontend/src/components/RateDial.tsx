import { useId, useState } from "react";
import type { OfferPlan } from "../api/types";
import { money, percent } from "../format";

/**
 * The offered rate, as a lever rather than a number to trust.
 *
 * This is the one claim in the product a broker will not take on faith, because
 * negotiating rate is the part of the job they believe they are good at. Handing
 * them a single figure invites an argument. Handing them the curve it came from
 * turns the argument into the demo: drag the rate, watch the odds climb and the
 * expected value peak and roll over, and the recommendation stops being an opinion
 * and becomes the top of a hill you can see.
 *
 * The curve is sampled by the engine and rendered here as-is, never refitted in the
 * browser. A second implementation of the acceptance model could disagree with the
 * one that chose the offer, and then the page would be inviting a broker to
 * "correct" the engine toward a worse number.
 */
export function RateDial({ plan, carrierName }: { plan: OfferPlan; carrierName: string }) {
  const curve = plan.rate_curve;
  const recommended = Math.max(
    0,
    curve.findIndex((point) => point.rate_usd === plan.offer_rate_usd),
  );
  const [index, setIndex] = useState(recommended);
  const labelId = useId();

  if (curve.length < 2) return null;

  const point = curve[Math.min(index, curve.length - 1)]!;
  const moved = index !== recommended;
  const best = curve[recommended]!;
  const lost = best.expected_value_usd - point.expected_value_usd;

  // Expected value drives the shape. Acceptance rises monotonically and so has no
  // shape worth drawing, but the value curve has a peak, and the peak is the
  // argument.
  const values = curve.map((p) => p.expected_value_usd);
  const top = Math.max(...values);
  const bottom = Math.min(...values);
  const span = top - bottom || 1;
  const x = (i: number) => (i / (curve.length - 1)) * 100;
  const y = (value: number) => 100 - ((value - bottom) / span) * 100;

  const line = curve.map((p, i) => `${x(i)},${y(p.expected_value_usd)}`).join(" ");
  const area = `0,100 ${line} 100,100`;

  return (
    <div className="dial">
      <div className="dial-readout">
        <div className="dial-primary">
          <span className="eyebrow" id={labelId}>
            Open at
          </span>
          <output className="fig dial-rate" htmlFor={labelId}>
            {money(point.rate_usd)}
          </output>
        </div>
        <div className="dial-secondary">
          <div>
            <span className="eyebrow">Odds it lands</span>
            <span className="fig dial-value">{percent(point.acceptance_probability)}</span>
          </div>
          <div>
            <span className="eyebrow">Expected value</span>
            <span
              className={
                point.expected_value_usd >= 0 ? "fig dial-value" : "fig dial-value is-negative"
              }
            >
              {money(point.expected_value_usd)}
            </span>
          </div>
        </div>
      </div>

      <div className="dial-plot">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <polygon className="dial-area" points={area} />
          <polyline className="dial-line" points={line} />
          <line className="dial-peak" x1={x(recommended)} x2={x(recommended)} y1="0" y2="100" />
          <line className="dial-cursor" x1={x(index)} x2={x(index)} y1="0" y2="100" />
        </svg>
        {/* The grip lives outside the SVG: the plot is stretched to fill its box, so
            anything round drawn inside it would come out an ellipse. */}
        <span className="dial-grip" style={{ left: `${x(index)}%` }} aria-hidden="true" />
        <input
          className="dial-input"
          type="range"
          min={0}
          max={curve.length - 1}
          step={1}
          value={index}
          onChange={(event) => setIndex(Number(event.target.value))}
          aria-label={`Rate to offer ${carrierName}`}
          aria-valuetext={`${money(point.rate_usd)}, ${percent(
            point.acceptance_probability,
          )} likely to be accepted`}
        />
      </div>

      <div className="dial-scale">
        <span className="fig">{money(curve[0]!.rate_usd)}</span>
        <span className="dial-scale-mid">drag to test a rate — expected value is the curve</span>
        <span className="fig">{money(curve[curve.length - 1]!.rate_usd)}</span>
      </div>

      <p className="dial-note">
        {moved ? (
          <>
            {lost > 0 ? (
              <>
                Costs about <strong className="fig">{money(lost)}</strong> against the engine's
                pick.{" "}
              </>
            ) : (
              <>Level with the engine's pick. </>
            )}
            <button type="button" className="linkish" onClick={() => setIndex(recommended)}>
              Back to {money(best.rate_usd)}
            </button>
          </>
        ) : point.expected_value_usd <= 0 ? (
          // Telling someone where the walk-away rate is would be strange advice on a
          // load that is already past it at every rate. The useful fact is that this
          // is the best the curve gets.
          <>
            This is the best rate available and it still loses{" "}
            <strong className="fig">{money(Math.abs(point.expected_value_usd))}</strong>. Their
            price is estimated to start near{" "}
            <strong className="fig">{money(plan.estimated_floor_usd)}</strong>, which is more than
            the load can carry.
          </>
        ) : (
          <>
            Their price is estimated to start near{" "}
            <strong className="fig">{money(plan.estimated_floor_usd)}</strong>.{" "}
            <strong className="fig">{money(plan.rate_ceiling_usd)}</strong> would make it 90%
            likely. Past <strong className="fig">{money(plan.walk_away_rate_usd)}</strong> the load
            stops being worth covering with them.
          </>
        )}
      </p>
    </div>
  );
}
