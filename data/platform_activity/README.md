# Platform activity log

**This is not TMS data.** Everything else under `data/` is a feed as one of the
three TMSs produced it. This directory is the platform's own record of what it
asked, of whom, at what price, and what came back.

It exists because of a gap in the brief's data, not in spite of it.

## Why it has to be separate

None of the three TMS schemas record a tender, an offer, a refusal, a counter, or
a response time. They record the carrier that ended up on the load. That means:

- there is no negative class for acceptance — every carrier ever observed on a
  load accepted it, by construction;
- the *rate that was refused* is never written down anywhere, so even the positive
  examples are missing their most important feature.

An acceptance model is therefore unidentifiable from TMS sync data no matter how
good the model is. The fix is not a better estimator, it is capturing the data,
and the capture has to happen at the platform because the platform is the only
party in the loop that sees the decision.

## What a record looks like

```json
{
  "offer_id": "OF-59-00040",
  "load_ref": "127472438",
  "carrier_ref": "835882",
  "carrier_mc": "1346382",
  "carrier_name": "IBRAHIM TRANSPORT INC",
  "offered_at": "2026-07-11T09:20:00-05:00",
  "offered_rate_usd": 1065.0,
  "outcome": "countered",
  "counter_rate_usd": 1165.0,
  "responded_at": "2026-07-11T10:09:00-05:00",
  "decline_reason": "rate below our floor"
}
```

`load_ref` and `carrier_ref` are the identifiers *that broker's TMS* uses, so the
log joins onto records the platform has already normalised.

## The bias that is baked in, on purpose

The only carriers with refusals recorded here are the ones somebody chose to call.
A carrier that was never called looks unknown rather than unsuitable, and nothing
in this log distinguishes "would have said no" from "was never asked". That is a
faithful reproduction of the real problem, and it is why the recommendation
responses carry an explicit limitation about selection bias instead of implying
the acceptance estimates are unbiased.

## Regenerating

Written by `data_gen/generate.py` alongside the TMS feeds, from per-carrier latent
parameters — a reservation price and a reply time — that are never written into any
file. The booked rates in the TMS feeds are derived from the same parameters, so
the log and the feeds cannot contradict each other, and the backend's estimated
price floors can be checked against a known truth in
`backend/tests/test_expected_value.py`.
