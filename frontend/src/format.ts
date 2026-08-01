import type { Equipment, LoadStatus } from "./api/types";

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const usdCents = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
});

export function money(value: number | null | undefined): string {
  return value == null ? "—" : usd.format(value);
}

export function perMile(value: number | null | undefined): string {
  return value == null ? "—" : `${usdCents.format(value)}/mi`;
}

export function miles(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value).toLocaleString()} mi`;
}

export function pounds(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value).toLocaleString()} lbs`;
}

/**
 * Freight phone numbers arrive as +1XXXXXXXXXX. A dispatcher reads them grouped,
 * and on this page the number is something they are about to dial, so it is worth
 * setting properly rather than printing the raw field.
 */
export function phone(value: string | null | undefined): string {
  if (!value) return "—";
  const digits = value.replace(/\D/g, "");
  const ten = digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
  if (ten.length !== 10) return value;
  return `(${ten.slice(0, 3)}) ${ten.slice(3, 6)}-${ten.slice(6)}`;
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export const STATUS_LABELS: Record<LoadStatus, string> = {
  PLANNED: "Planned",
  ACTIVE: "Needs a carrier",
  COVERED: "Covered",
  IN_TRANSIT: "In transit",
  DELIVERED: "Delivered",
  COMPLETED: "Completed",
};

export const EQUIPMENT_LABELS: Record<Equipment, string> = {
  DRY_VAN: "Dry van",
  REEFER: "Reefer",
  FLATBED: "Flatbed",
  UNKNOWN: "Not recorded",
};

/** Human-readable name for a load field in the change log. */
export const FIELD_LABELS: Record<string, string> = {
  status: "Status",
  equipment: "Equipment",
  weight_lbs: "Weight",
  distance_miles: "Distance",
  customer_rate: "Customer rate",
  carrier_rate: "Carrier rate",
  carrier_name: "Carrier",
};

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}
