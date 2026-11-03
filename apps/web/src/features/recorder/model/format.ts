/**
 * SCR-140's figures as text (E16-D02 §1, §8, §9.1): bytes as GB with one decimal (MB under 1 GB),
 * the budget in whole GB when whole, a rate in GB a day, policy durations ("60 s", "30 min",
 * "1 h 30 min") and UTC text from `toISOString`, never the local zone ("—" for no time). Fixed
 * decimals keep a figure's width, so the cells' tabular `type.num.sm` never shifts a neighbour (§9.1).
 */

/** `cap_bytes` is `CV_DISK_CAP_GB` × 10^9 (23 §15.8): decimal units. */
export const GB = 1e9;
const MB = 1e6;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const formats = new Map<number, Intl.NumberFormat>();

/** en-US grouping and exactly `digits` decimals: "1,188.0" (E16-D04 §14's figures). */
export function fixed(value: number, digits: number): string {
  let format = formats.get(digits);
  if (format === undefined) {
    format = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    formats.set(digits, format);
  }
  return format.format(value);
}

/** From here a size prints "1,000.0 MB" at one decimal: it is "1.0 GB" instead (A-5309-10). */
const GB_FROM = GB - 0.05 * MB;

/** "34.8 GB", "1,188.0 GB"; under 1 GB "1.3 MB" (§1's Size cells). */
export function formatBytes(bytes: number): string {
  return bytes >= GB_FROM ? `${fixed(bytes / GB, 1)} GB` : `${fixed(bytes / MB, 1)} MB`;
}

/** The budget: "200 GB" when whole, else one decimal ("61.4 GB of 200 GB", §1). */
export function formatCap(bytes: number): string {
  const gb = bytes / GB;
  return `${fixed(gb, Number.isInteger(gb) ? 0 : 1)} GB`;
}

/** The projection's growth, "0.93 GB" (§8.3's "{growth}/day"). */
export const formatGrowth = (bytesPerDay: number): string => `${fixed(bytesPerDay / GB, 2)} GB`;

/** A policy duration in seconds (§8: "60 s", "30 min", "1 h 30 min"; never hard-coded, decision 1). */
export function formatDuration(seconds: number): string {
  if (seconds <= 60 || seconds % 60 !== 0) return `${seconds} s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${minutes} min`;
  const rest = minutes % 60;
  return `${Math.floor(minutes / 60)} h${rest === 0 ? "" : ` ${rest} min`}`;
}

/** An ISO time from the contract as epoch ms; null when absent or unreadable. */
export function parseMs(iso: string | null | undefined): number | null {
  const ms = iso == null ? Number.NaN : Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

/** No time to show: a value past `Date`'s range (±8.64e15 ms) or not a number (A-5309-10). */
const NO_TIME = "—";
/** The UTC instant's ISO text, or null where `toISOString` would throw a RangeError. */
const iso = (ms: number): string | null => {
  const date = new Date(ms);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
};
/** "10:31:02" (the page adds " UTC" where its copy writes it). */
export const formatClock = (ms: number): string => iso(ms)?.slice(11, 19) ?? NO_TIME;
/** "10:42" (`storage.compact.succeeded`'s "{HH:MM}"). */
export const formatHourMinute = (ms: number): string => iso(ms)?.slice(11, 16) ?? NO_TIME;
/** "2026-09-01" (the Since column, §1). */
export const formatDate = (ms: number): string => iso(ms)?.slice(0, 10) ?? NO_TIME;
/** "18 Oct" (a stopped row, §4.1). */
export function formatDayMonth(ms: number): string {
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return NO_TIME;
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()] ?? ""}`;
}
