import type { CarrierRanking, ComponentScore, LoadDetail, PriceEstimate } from "@/api/types";
import { evidenceValue, money, perMile } from "@/format";

const COMPONENT_LABELS: Record<string, string> = {
  positioning: "Empty miles",
  lane_familiarity: "Knows this lane",
  price: "Price history",
  reliability: "On-time record",
  relationship: "Works with you",
  customer_affinity: "Knows this customer",
  stability: "No surprises"
};

const BASIS_LABELS: Record<string, string> = {
  similar_lane: "similar lanes",
  carrier_similar_lane: "this carrier on similar lanes",
  broker_prior: "your overall history",
  market_prior: "the broker average",
  last_delivery: "where they just delivered",
  pooled_last_delivery: "pooled last delivery",
  operating_footprint: "where they usually run",
  blended: "recent delivery and usual area",
  unknown: "no position on record"
};

const EVIDENCE_LABELS: Record<string, string> = {
  effective_loads: "similar past loads",
  direct: "same direction",
  reverse: "reverse direction",
  expected_deadhead_miles: "expected empty miles",
  deadhead_ratio: "empty vs loaded miles",
  last_delivery_deadhead_miles: "empty miles from last delivery",
  footprint_deadhead_miles: "empty miles where they usually run",
  position_age_days: "age of last known position",
  position_observations: "deliveries behind this estimate",
  position_own_observations: "your position observations",
  position_pooled_observations: "pooled position observations",
  pickups_within_50mi: "past pickups within 50 mi",
  pooled_lane_cells: "pooled lane cells",
  observed_ppm: "similar-lane price",
  shrunk_ppm: "recommended lane price",
  prior_ppm: "your average price",
  price_effective_loads: "price history size",
  basis: "source",
  point_usd: "expected price",
  all_in_ppm_with_deadhead: "carrier earns per mile driven",
  observations: "on-time checks",
  broker_local_observations: "your on-time checks",
  pooled_observations: "pooled on-time checks",
  pooled_on_time: "pooled on-time successes",
  measures: "timing checks used",
  total_loads: "loads together",
  recent_loads: "recent loads",
  same_customer_loads: "loads for this customer",
  corrections: "pricing corrections",
  fallthroughs: "carrier changes",
  broker_local_fallthroughs: "your carrier changes",
  pooled_fallthroughs: "pooled carrier changes",
  appointment_observations: "appointment checks",
  appointment_on_time: "on-time appointments",
  fallthrough_count: "carrier changes",
  recency_band: "recency band",
  on_time_band: "on-time band",
  equipment_types: "equipment",
  lane_cells: "lane cells",
  mc_number: "MC number",
  dot_number: "DOT number",
  home_city: "home city",
  home_state: "home state",
  carrier_name: "carrier",
  stops: "stop sightings"
};

export function componentName(name: string) {
  return COMPONENT_LABELS[name] ?? titleize(name);
}

export function basisName(name: string) {
  return BASIS_LABELS[name] ?? titleize(name);
}

export function evidenceName(name: string) {
  return EVIDENCE_LABELS[name] ?? titleize(name);
}

export function matchScore(value: number) {
  return Math.round(value * 100);
}

export function matchLabel(value: number) {
  return `${matchScore(value)} match`;
}

export function evidenceDisplay(key: string, value: string | number | null) {
  if (key === "point_usd" && typeof value === "number") return money(value);
  if (key.endsWith("_ppm") && typeof value === "number") return perMile(value);
  if (key === "basis" && typeof value === "string") return basisName(value);
  if (key === "deadhead_ratio" && typeof value === "number") return `${Math.round(value * 100)}%`;
  if (key.endsWith("_days") && typeof value === "number") return `${Math.round(value)} days`;
  if (key.includes("miles") && typeof value === "number") return `${Math.round(value)} mi`;
  return evidenceValue(value);
}

export function topReason(carrier: CarrierRanking) {
  return carrier.reasons[0]?.replace(/broker-local /g, "").replace(/effective similar-lane/g, "similar-lane") ?? "Relevant carrier history";
}

export function priceStory(price: PriceEstimate, detail: LoadDetail) {
  const similarLane = price.observed_ppm * detail.distance_miles;
  const brokerAverage = price.prior_ppm * detail.distance_miles;
  return `Similar lanes in your history ran ${money(similarLane)}. Your average across all lanes is ${money(brokerAverage)}. We suggest ${money(price.point_usd)}.`;
}

export function componentTooltip(component: ComponentScore) {
  return `${componentName(component.name)}: ${matchScore(component.score)} strength, ${Math.round(component.weight * 100)}% of the score`;
}

function titleize(value: string) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}
