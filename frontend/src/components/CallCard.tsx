import type { CarrierRecommendation, Recommendations } from "../api/types";
import { money, percent, phone } from "../format";
import { RateDial } from "./RateDial";

/**
 * One answer, at full size: who to ring, what to say, and the two or three things
 * worth knowing before they pick up.
 *
 * The number is the hero because the number is the product. Everything this system
 * computes exists to make one phone call better than the call a rep would have made
 * from memory, so the call is the thing the page is built around rather than a
 * detail inside a row of a ranked table.
 *
 * Reasons are capped at three and stripped of their point values. A dispatcher
 * deciding whether to dial needs the two facts that would change their mind, not the
 * full derivation - that lives in the proof drawer, one click away and reachable
 * whenever someone actually wants to argue with it.
 */
export function CallCard({
  carrier,
  result,
  onShowWork,
}: {
  carrier: CarrierRecommendation;
  result: Recommendations;
  onShowWork: () => void;
}) {
  const plan = carrier.offer_plan;
  const reprice = result.coverage?.decision === "REPRICE";
  // Only what this carrier is like. The dial above already states the rate, the odds,
  // the 90% point and the walk-away, and the strip below lists what they were already
  // offered, so the `offer` and `basis` reasons would just be this card describing
  // itself. They are shown in full in the work.
  const reasons = carrier.reasons.filter((reason) => reason.kind === "carrier").slice(0, 3);

  return (
    <article className={reprice ? "callcard is-muted" : "callcard"}>
      <div className="callcard-head">
        <span className="eyebrow">{reprice ? "Closest thing to a fit" : "Call first"}</span>
        {carrier.history_depth.is_thin && (
          <span className="flag flag-thin">{carrier.history_depth.label}</span>
        )}
      </div>

      <h2 className="callcard-name">{carrier.carrier_name}</h2>

      <div className="callcard-dial">
        {carrier.phone ? (
          <a className="fig callcard-phone" href={`tel:${carrier.phone}`}>
            {phone(carrier.phone)}
          </a>
        ) : (
          <span className="callcard-phone-missing">No number on file</span>
        )}
        {carrier.mc_number && <span className="fig callcard-mc">MC {carrier.mc_number}</span>}
      </div>

      {plan ? (
        <RateDial plan={plan} carrierName={carrier.carrier_name} />
      ) : (
        <div className="dial-readout dial-readout-bare">
          <div className="dial-primary">
            <span className="eyebrow">Open at</span>
            <span className="fig dial-rate">{money(carrier.suggested_rate_usd)}</span>
          </div>
          <div className="dial-secondary">
            <div>
              <span className="eyebrow">Score</span>
              <span className="fig dial-value">{carrier.score.toFixed(1)}</span>
              <span className="dial-caveat">ranking only, not dollars</span>
            </div>
          </div>
        </div>
      )}

      <ul className="callcard-reasons">
        {reasons.map((reason) => (
          <li key={reason.label} className={`cr cr-${reason.sentiment}`}>
            <strong>{reason.label}.</strong> {reason.detail}
          </li>
        ))}
      </ul>

      <footer className="callcard-foot">
        <span className="callcard-track">
          {carrier.loads_total} load{carrier.loads_total === 1 ? "" : "s"} for you
          {carrier.loads_on_lane > 0 && <>, {carrier.loads_on_lane} on this lane</>}
          {carrier.days_since_last_load != null && (
            <> · last ran {carrier.days_since_last_load}d ago</>
          )}
          {carrier.last_delivery_market_label && (
            <> · truck last dropped in {carrier.last_delivery_market_label}</>
          )}
        </span>
        <button type="button" className="linkish" onClick={onShowWork}>
          Show the work
        </button>
      </footer>

      {carrier.prior_offers.length > 0 && (
        <div className="callcard-asked">
          <span className="eyebrow">Already asked</span>
          {carrier.prior_offers.map((offer) => (
            <span key={offer.offered_at} className="fig">
              {money(offer.offered_rate_usd)} — {offer.outcome.toLowerCase().replace("_", " ")}
              {offer.counter_rate_usd != null && <>, wants {money(offer.counter_rate_usd)}</>}
            </span>
          ))}
        </div>
      )}
    </article>
  );
}

/**
 * Everyone else, one line each.
 *
 * The ranked list was the old page's centre of gravity, and it was the wrong centre:
 * a dispatcher makes one call at a time, and six fully-argued options is a way of
 * declining to answer. These are the fallbacks, sized like fallbacks, and they still
 * carry the two numbers that decide whether to move down the list.
 */
export function Bench({
  carriers,
  onSelect,
  selectedId,
}: {
  carriers: CarrierRecommendation[];
  onSelect: (carrierId: string) => void;
  selectedId: string;
}) {
  if (carriers.length === 0) return null;

  return (
    <section className="bench">
      <h3 className="eyebrow bench-title">Then</h3>
      <ul>
        {carriers.map((carrier) => {
          const plan = carrier.offer_plan;
          return (
            <li key={carrier.carrier_id}>
              <button
                type="button"
                className={carrier.carrier_id === selectedId ? "benchrow is-active" : "benchrow"}
                onClick={() => onSelect(carrier.carrier_id)}
                aria-pressed={carrier.carrier_id === selectedId}
              >
                {/* No rank numeral. The list is already in the engine's order, and
                    printing the ordinal made the numbers skip whenever the lead came
                    from the verdict rather than the top of the ranking — which reads
                    as a bug rather than as the honest thing it is. */}
                <span className="benchrow-name">
                  {carrier.carrier_name}
                  {carrier.history_depth.is_thin && <span className="benchrow-thin">thin</span>}
                </span>
                <span className="fig benchrow-rate">
                  {money(plan ? plan.offer_rate_usd : carrier.suggested_rate_usd)}
                </span>
                <span className="fig benchrow-odds">
                  {plan ? percent(plan.acceptance_probability) : `${carrier.score.toFixed(0)} pts`}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
