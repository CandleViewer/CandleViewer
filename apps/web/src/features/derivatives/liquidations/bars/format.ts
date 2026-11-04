// E24-S06 (#781): the bar's time cell. Times are UTC (the column header says so); a bar of a day or more is a date.
import { feedTime } from "../ui/format";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86_400_000;

const dateOf = (ms: number): string => {
  const d = new Date(ms);
  return `${String(d.getUTCDate())} ${MONTHS[d.getUTCMonth()] ?? ""}`;
};

/** "09:00" on the reference day's date, "21 Oct 09:00" on another; "21 Oct" for a bar of a day or more. */
export function barTime(ms: number, refMs: number, intervalMs: number): string {
  if (intervalMs >= DAY_MS) return `${dateOf(ms)} ${String(new Date(ms).getUTCFullYear())}`;
  const hm = feedTime(ms).slice(0, 5);
  return new Date(ms).toISOString().slice(0, 10) === new Date(refMs).toISOString().slice(0, 10)
    ? hm
    : `${dateOf(ms)} ${hm}`;
}

/** "1 h", "15 min", "1 d": the interval, for the caption and the legend. */
export function intervalLabel(intervalMs: number): string {
  if (intervalMs >= 7 * DAY_MS) return "1 w";
  if (intervalMs >= DAY_MS) return "1 d";
  return intervalMs >= 3_600_000
    ? `${String(intervalMs / 3_600_000)} h`
    : `${String(intervalMs / 60_000)} min`;
}
