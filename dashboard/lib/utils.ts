import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const nf = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 });
const nf0 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });

export function fmt(value: unknown, digits = 2): string {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "–";
  return (digits === 0 ? nf0 : nf).format(Number(value));
}

export function pct(value: unknown, digits = 1, isFraction = true): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "–";
  const v = isFraction ? Number(value) * 100 : Number(value);
  return `${new Intl.NumberFormat("de-DE", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v)} %`;
}

export function eur(value: unknown, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "–";
  return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: digits }).format(Number(value));
}

export function dateDe(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}
