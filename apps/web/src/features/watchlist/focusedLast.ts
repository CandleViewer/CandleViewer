/**
 * SR-31 / BG-02 (E08-D12; E08-D07 §4.5): with SCR-117's price announcements on, the focused row's Last is spoken,
 * politely, through the app's region (the panel owns none, D17): the latest value as its cell draws it, at most once per
 * 2 s (`05` §6.2's "1 update / 2s per field"), never a queue of the values in between. PREF's `shouldAnnounce` decides
 * each update, so no E08 row widens it: E08 names no significant change of a Last, so "On significant change" speaks
 * none of them and "Always" (with a verbosity above low) speaks it. The value a row shows as focus lands on it is the
 * row's own reading; only a later change is spoken. No other row and no other value is ever spoken per tick (SR-32).
 * Plain code: the caller passes the words and the time.
 */
import { formatWatchlistPrice } from "@candleviewer/ui";
import { shouldAnnounce, type A11yPreferences } from "../a11y-preferences/model";
import type { Instrument } from "../symbol-search/ranking";
import { priceScaleOf } from "./LiveRow";

/** `05` §6.2: one update per 2 s per field. */
export const LAST_CADENCE_MS = 2_000;

/** What of SCR-117's preferences the gate reads. */
export type PricePrefs = Pick<A11yPreferences, "announce_prices" | "verbosity">;

/** A Last as its cell draws it (D9: the instrument's price scale, grouped), or `undefined` with no value. */
export const lastWordsOf = (
  value: number | undefined,
  instrument: Instrument | undefined,
): string | undefined =>
  value === undefined ? undefined : formatWatchlistPrice(value, priceScaleOf(instrument));

export interface FocusedLast {
  /** Focus lands on `symbol`'s row (or on no row: `null`) at `now`, the row showing `shown` (its Last's words). */
  focus(symbol: string | null, shown: string | undefined, now: number): void;
  /** The shared clock's second: the focused row's Last as it shows at `now`, spoken if it changed and PREF lets it. */
  update(shown: string | undefined, now: number): void;
}

export function createFocusedLast(
  say: (text: string) => void,
  prefs: () => PricePrefs,
): FocusedLast {
  let symbol: string | null = null;
  /** The words last spoken, or shown when focus landed: a value equal to them is not news. */
  let heard: string | undefined;
  let at = Number.NEGATIVE_INFINITY;
  return {
    focus(next, shown, now) {
      if (next === symbol) return;
      symbol = next;
      heard = shown;
      at = now;
    },
    update(shown, now) {
      if (symbol === null || shown === undefined || shown === heard) return;
      const cadenceElapsed = now - at >= LAST_CADENCE_MS;
      if (!shouldAnnounce(prefs(), { significant: false, cadenceElapsed })) return;
      heard = shown;
      at = now;
      say(shown);
    },
  };
}
