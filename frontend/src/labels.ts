import type { CarrierRanking, ComponentScore, LoadDetail, PriceEstimate } from "@/api/types";
import { evidenceValue, money, perMile } from "@/format";

const COMPONENT_LABELS: Record<string, string> = {
  lane_familiarity: "Knows this lane",
  positioning: "Truck nearby",
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
  market_prior: "the broker average"
};

const EVIDENCE_LABELS: Record<string, string> = {
  effective_loads: "similar past loads",
  direct: "same direction",
  reverse: "reverse direction",
  last_delivery_deadhead_miles: "empty miles to pickup",
  observed_ppm: "similar-lane price",
  shrunk_ppm: "recommended lane price",
  prior_ppm: "your average price",
  price_effective_loads: "price history size",
  basis: "price source",
  point_usd: "expected price",
  observations: "on-time checks",
  measures: "timing checks used",
  total_loads: "loads together",
  recent_loads: "recent loads",
  same_customer_loads: "loads for this customer",
  corrections: "pricing corrections",
  fallthroughs: "carrier changes"
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
