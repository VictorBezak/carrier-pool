export type Broker = {
  broker_id: string;
  name: string;
  pool_opt_in: boolean;
  load_count: number;
  active_count: number;
};

export type Location = {
  city: string;
  state: string;
  zip_code: string;
};

export type LoadSummary = {
  broker_id: string;
  load_id: string;
  source_file: string;
  synced_at: string;
  status: string;
  customer: { id: string; name: string };
  equipment: string;
  pickup: Location;
  delivery: Location;
  distance_miles: number;
  weight_lbs: number | null;
  customer_rate_usd: number | null;
  carrier_rate_usd: number | null;
};

export type LoadDetail = LoadSummary & {
  pickup_window: { open_at: string | null; close_at: string | null };
  delivery_window: { open_at: string | null; close_at: string | null };
  actuals: Record<string, string | null>;
  versions: LoadSummary[];
};

export type SyncFile = {
  broker_id: string;
  source_file: string;
  filename: string;
  synced_at: string;
  processed_at: string | null;
};

export type PriceEstimate = {
  point_usd: number;
  low_usd: number;
  high_usd: number;
  point_ppm: number;
  observed_ppm: number;
  prior_ppm: number;
  basis: string;
  effective_loads: number;
  confidence: string;
  comparables: Comparable[];
  reasons: string[];
  limitations: string[];
};

export type Comparable = {
  load_id: string;
  source_file: string;
  carrier_id: string | null;
  origin: string;
  destination: string;
  equipment: string;
  weight: number;
  ppm: number;
  carrier_rate_usd: number;
};

export type ComponentScore = {
  name: string;
  score: number;
  weight: number;
  evidence: Record<string, string | number | null>;
};

export type MapPoint = {
  zip_code: string;
  lat: number;
  lon: number;
};

export type LaneGeometry = {
  target: { origin: MapPoint | null; destination: MapPoint | null };
  historical_lanes: Array<{
    origin: MapPoint | null;
    destination: MapPoint | null;
    weight: number;
    direct_weight: number;
    reverse_weight: number;
  }>;
  last_delivery: MapPoint | null;
};

export type CarrierRanking = {
  broker_id: string;
  load_id: string;
  carrier_id: string;
  carrier_name: string;
  score: number;
  confidence: string;
  components: ComponentScore[];
  reasons: string[];
  limitations: string[];
  geometry: LaneGeometry;
};

export type PoolCarrierRanking = {
  contributor_broker_id: string;
  contributor_broker_name: string;
  carrier_id: string;
  carrier_name: string;
  score: number;
  confidence: string;
  expected_carrier_cost_usd: number;
  reasons: string[];
  limitations: string[];
  payload: Record<string, string | string[] | null>;
  geometry: LaneGeometry;
};

export type Recommendation = {
  load: LoadSummary;
  price: PriceEstimate;
  own_carriers: CarrierRanking[];
  pool_carriers: PoolCarrierRanking[];
};

export type PoolPolicy = {
  fields: string[];
  eligible_brokers: string[];
  ineligible_brokers: Record<string, string>;
  never_shared: string[];
  matching_rule: string;
};
