import type { LoadDetail } from "../api/types";
import { Card, Empty } from "./atoms";
import { dateTime, money } from "../format";

/**
 * Every call the platform has made on this load.
 *
 * This is the only panel on the page whose data comes from nowhere in any TMS.
 * None of the three feeds record a tender, a refusal, or a reply — they show the
 * carrier that ended up on the load and nothing about how it got there. So this
 * is the platform's own log, and without it acceptance behaviour has no negative
 * class and cannot be estimated at all, no matter how good the model is.
 *
 * It is also where the selection bias lives, visibly: the only carriers with
 * refusals here are the ones somebody chose to call.
 */
export function OfferLog({ detail }: { detail: LoadDetail }) {
  const { offers } = detail;

  return (
    <Card
      title="Calls made on this load"
      subtitle="Recorded by the platform, not by the TMS — no feed in this dataset carries offers or refusals."
    >
      {offers.length === 0 ? (
        <Empty>No calls have been logged against this load.</Empty>
      ) : (
        <ol className="offer-log">
          {offers.map((offer) => (
            <li key={offer.offer_id} className={`offer outcome-${offer.outcome.toLowerCase()}`}>
              <div className="offer-head">
                <span className="offer-carrier">{offer.carrier_name}</span>
                <span className="offer-outcome">{offer.outcome.toLowerCase().replace("_", " ")}</span>
              </div>
              <div className="offer-money">
                offered {money(offer.offered_rate)}
                {offer.counter_rate != null && <> · countered at {money(offer.counter_rate)}</>}
              </div>
              <div className="muted offer-meta">
                {dateTime(offer.offered_at)}
                {offer.responded_at ? (
                  <> · replied in {minutesBetween(offer.offered_at, offer.responded_at)}</>
                ) : (
                  <> · never replied</>
                )}
                {offer.decline_reason && <> · “{offer.decline_reason}”</>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function minutesBetween(from: string, to: string): string {
  const minutes = Math.round(
    (new Date(to).getTime() - new Date(from).getTime()) / 60000,
  );
  if (minutes < 90) return `${minutes} min`;
  return `${(minutes / 60).toFixed(1)} h`;
}
