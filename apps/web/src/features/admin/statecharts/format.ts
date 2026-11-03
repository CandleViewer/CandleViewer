/**
 * The inspector's served values as words (E42-S08): times in UTC (E42-D03 §1) and a served list of
 * state ids. Formatting only: nothing here derives a state, a transition or the latch.
 */
import { hms } from "../overview/tileModels";
import { INSPECTOR_COPY as COPY } from "./copy";

const dayOf = (ms: number): string => new Date(ms).toISOString().slice(0, 10);

/**
 * "18:00:02 UTC", or "2026-10-14 23:59:57 UTC" when its UTC day is not `today`'s (the day the
 * answer came, so the words do not change while the page stays open).
 */
export function utcTime(ms: number, today: number): string {
  const time = hms(ms);
  return COPY.utc(dayOf(ms) === dayOf(today) ? time : `${dayOf(ms)} ${time}`);
}

/**
 * A served list of state ids, each without the chart root's leading segment when it has one:
 * `["order.lifecycle.triggered"]` reads "lifecycle.triggered" for an `order` machine.
 */
export function stateIds(ids: readonly string[], root: string): string {
  return ids.map((id) => (id.startsWith(`${root}.`) ? id.slice(root.length + 1) : id)).join(", ");
}
