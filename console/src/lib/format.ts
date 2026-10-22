export const percent = (v: number | null | undefined, digits = 0): string =>
  v == null ? "-" : `${(v * 100).toFixed(digits)}%`;

export const ms = (v: number | null | undefined): string => {
  if (v == null) return "-";
  return v >= 1000 ? `${(v / 1000).toFixed(v >= 10_000 ? 1 : 2)} s` : `${Math.round(v)} ms`;
};

export const cost = (v: number | null | undefined): string =>
  v == null ? "-" : v < 0.01 && v > 0 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;

export const count = (v: number | null | undefined): string => (v == null ? "-" : v.toLocaleString());

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
  ["second", 1],
];
const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export const relativeTime = (iso: string, now = Date.now()): string => {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const [unit, size] = UNITS.find(([, s]) => Math.abs(seconds) >= s) ?? ["second", 1];
  return rtf.format(Math.round(seconds / size), unit);
};

export const absoluteTime = (iso: string): string => new Date(iso).toLocaleString();

export const json = (v: unknown): string => JSON.stringify(v, null, 2) ?? "null";

export const shortId = (id: string, len = 8): string => (id.length > len ? id.slice(0, len) : id);
