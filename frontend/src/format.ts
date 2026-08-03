import type { LoadStatus, Location } from "@/api/types";

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usdExact = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

export function money(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : usd.format(value);
}

export function perMile(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${usdExact.format(value)}/mi`;
}

export function miles(value: number) {
  return `${Math.round(value).toLocaleString("en-US")} mi`;
}

export function pounds(value: number | null) {
  return value === null ? "—" : `${Math.round(value).toLocaleString("en-US")} lb`;
}

export function place(value: Location) {
  return `${value.city}, ${value.state} ${value.zip_code}`;
}

export function equipment(value: string) {
  return value.replace(/_/g, " ");
}

export function componentLabel(value: string) {
  return value.replace(/_/g, " ");
}

export function statusLabel(value: LoadStatus) {
  return value.replace(/_/g, " ");
}

export function timestamp(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}

export function day(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function margin(customerRate: number | null, carrierRate: number | null) {
  if (customerRate === null || carrierRate === null) return null;
  return customerRate - carrierRate;
}

export function evidenceValue(value: string | number | null) {
  if (value === null) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString("en-US") : value.toFixed(2);
  return value.replace(/_/g, " ");
}
