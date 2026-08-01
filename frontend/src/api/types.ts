/**
 * Mirror of the backend response models.
 *
 * Hand-written rather than generated so the shape stays readable, but it is a
 * deliberate mirror: `Reason`, `ScoreComponent` and `PriceEstimate` are the
 * contract the ranking engine promises to keep when its internals are replaced.
 */

export type LoadStatus =
  | "PLANNED"
  | "ACTIVE"
  | "COVERED"
  | "IN_TRANSIT"
  | "DELIVERED"
  | "COMPLETED";

export type Equipment = "DRY_VAN" | "REEFER" | "FLATBED" | "UNKNOWN";

export type Sentiment = "positive" | "neutral" | "negative";

export type Confidence = "high" | "medium" | "low";

export type ChangeKind =
  | "PROGRESS"
  | "REVEALED"
  | "CORRECTION"
  /** A carrier came off a load after accepting it. No TMS reports this; the
   * backend infers it from a status moving backwards out of COVERED. */
  | "FALL_OFF"
  | "DETAIL";

export type OfferOutcome = "ACCEPTED" | "DECLINED" | "COUNTERED" | "NO_RESPONSE";

/** One thing the platform asked a carrier. Comes from the platform's own log,
 * not from any TMS - see the backend's `domain.Offer`. */
export interface Offer {
  broker_id: string;
  offer_id: string;
  load_id: string;
  carrier_id: string;
  carrier_name: string;
  offered_at: string;
  offered_rate: number;
  outcome: OfferOutcome;
  counter_rate: number | null;
  responded_at: string | null;
  decline_reason: string | null;
}

export interface BrokerSummary {
  broker_id: string;
  name: string;
  tms_label: string;
  tms_style: string;
  load_count: number;
  active_load_count: number;
  carrier_count: number;
  sync_file_count: number;
  last_synced_at: string | null;
}

export interface LoadSummary {
  load_id: string;
  source_ref: string;
  reference: string;
  status: LoadStatus;
  equipment: Equipment;
  customer_name: string | null;
  origin_label: string | null;
  destination_label: string | null;
  lane: string;
  lane_label: string;
  distance_miles: number | null;
  weight_lbs: number | null;
  customer_rate: number | null;
  carrier_rate: number | null;
  carrier_name: string | null;
  margin: number | null;
  pickup_at: string | null;
  updated_at: string | null;
  sync_count: number;
  correction_count: number;
}

export interface Stop {
  sequence: number;
  kind: "PICKUP" | "DROPOFF" | "INTERMEDIATE";
  city: string;
  state: string;
  postal_code: string | null;
  location_name: string | null;
  market: string;
  market_label: string;
  scheduled_start: string | null;
  scheduled_end: string | null;
  actual_arrival: string | null;
  actual_departure: string | null;
}

export interface FieldChange {
  broker_id: string;
  load_id: string;
  reference: string;
  field: string;
  kind: ChangeKind;
  old_value: string | null;
  new_value: string | null;
  observed_at: string;
  source_file: string;
}

export interface LoadDetail extends LoadSummary {
  source_tms: string;
  commodity: string | null;
  carrier_rate_per_mile: number | null;
  stops: Stop[];
  created_at: string | null;
  first_seen_sync: string | null;
  last_seen_sync: string | null;
  history: FieldChange[];
  /** Tri-state: null means the outcome is not yet knowable, not that it was fine. */
  pickup_on_time: boolean | null;
  delivery_on_time: boolean | null;
  offers: Offer[];
}

export interface Reason {
  label: string;
  detail: string;
  sentiment: Sentiment;
  points: number | null;
}

export interface ScoreComponent {
  key: string;
  label: string;
  weight: number;
  value: number;
  points: number;
}

export interface HistoryDepth {
  loads_total: number;
  loads_on_lane: number;
  label: string;
  is_thin: boolean;
}

/** A carrier ruled out before scoring, with the gate that did it. */
export interface Exclusion {
  carrier_id: string;
  carrier_name: string;
  gate: string;
  gate_label: string;
  detail: string;
}

/** A hard constraint that should be enforced and cannot be, because no feed
 * carries the data. Rendered so the gap is visible rather than assumed away. */
export interface UncheckedGate {
  gate: string;
  gate_label: string;
  detail: string;
}

/** One component estimate. `prior_share` is how much of it came from the
 * population rather than this carrier - a prediction that is 80% prior is a
 * statement about carriers in general. */
export interface Prediction {
  key: string;
  label: string;
  value: number;
  display: string;
  observations: number;
  prior_share: number;
  prior_label: string;
  uncertainty: number;
  note: string | null;
}

/** One line of the expected-value arithmetic, in dollars. */
export interface ValueTerm {
  key: string;
  label: string;
  amount_usd: number;
  detail: string;
}

/** What to offer, and what it is worth. The rate is chosen by the engine, not
 * predicted: it is the value that maximises expected value. */
export interface OfferPlan {
  offer_rate_usd: number;
  acceptance_probability: number;
  expected_value_usd: number;
  value_terms: ValueTerm[];
  optimistic_value_usd: number;
  pessimistic_value_usd: number;
  expected_resolution_hours: number | null;
  value_per_hour_usd: number | null;
  rate_ceiling_usd: number;
  walk_away_rate_usd: number;
}

export interface PriorOffer {
  offered_rate_usd: number;
  outcome: OfferOutcome;
  counter_rate_usd: number | null;
  response_minutes: number | null;
  offered_at: string;
}

export interface CarrierRecommendation {
  rank: number;
  carrier_id: string;
  carrier_name: string;
  mc_number: string | null;
  phone: string | null;
  score: number;
  components: ScoreComponent[];
  reasons: Reason[];
  history_depth: HistoryDepth;
  loads_total: number;
  loads_on_lane: number;
  days_since_last_load: number | null;
  last_delivery_market_label: string | null;
  median_lane_rate_per_mile: number | null;
  suggested_rate_usd: number | null;
  /** Present only for expected-value engines; the heuristic leaves it null. */
  offer_plan: OfferPlan | null;
  predictions: Prediction[];
  prior_offers: PriorOffer[];
  surfaced_by: string[];
}

export interface Comparable {
  load_id: string;
  /** Addresses the load in the API; differs from `reference` on BrokerOS. */
  source_ref: string;
  reference: string;
  lane_label: string;
  equipment: Equipment;
  carrier_name: string | null;
  distance_miles: number | null;
  carrier_rate: number | null;
  rate_per_mile: number | null;
  delivered_at: string | null;
}

export interface PriceEstimate {
  point_usd: number;
  low_usd: number;
  high_usd: number;
  rate_per_mile: number;
  basis: string;
  basis_label: string;
  sample_size: number;
  confidence: Confidence;
  reasons: Reason[];
  comparables: Comparable[];
}

export interface EngineInfo {
  key: string;
  name: string;
  version: string;
  description: string;
  objective: string | null;
}

export interface Recommendations {
  load_id: string;
  lane: string;
  lane_label: string;
  engine: EngineInfo;
  generated_at: string;
  as_of: string;
  price_estimate: PriceEstimate | null;
  carriers: CarrierRecommendation[];
  carriers_considered: number;
  notes: string[];
  exclusions: Exclusion[];
  unchecked_gates: UncheckedGate[];
  limitations: string[];
}

export interface LaneSummary {
  lane: string;
  lane_label: string;
  load_count: number;
  median_rate_per_mile: number | null;
  carrier_count: number;
}
