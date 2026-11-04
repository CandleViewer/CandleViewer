// E24-S02 (#777) slice 1: when the unclassified count is announced. D04 §9.2 LR-5, quoted:
//   "unclassified OI count | polite | a material change (E24-S02 sets it) | once per material change |
//    AN-5 (PROPOSED wording in D03)"
// D04 leaves the threshold to this ticket, so it is PROPOSED here, in one place: the count is announced when
// it has moved by at least `MATERIAL_MIN_BARS` bars or `MATERIAL_FRACTION` of the bars in view since the last
// announcement, whichever is larger. The same rule applies at 0 and N, so a count flapping 0, 1, 0, 1 never
// speaks (hysteresis). The first reading with bars sets the baseline and is not announced (as LR-1: not on a
// mount inside the window), and a symbol or interval change re-seeds it.
import { useEffect, useRef, useState } from "react";

/** PROPOSED (D04 LR-5, set by E24-S02). */
export const MATERIAL_MIN_BARS = 3;
/** PROPOSED (D04 LR-5, set by E24-S02). */
export const MATERIAL_FRACTION = 0.1;

export function isMaterialChange(announced: number, current: number, barsInView: number): boolean {
  if (current === announced) return false;
  const threshold = Math.max(MATERIAL_MIN_BARS, Math.ceil(barsInView * MATERIAL_FRACTION));
  return Math.abs(current - announced) >= threshold;
}

/** AN-5, wording PROPOSED (D03 §13; E24-S02 sets it), as is "All bars classified." and the generic form: "3 bars unclassified, no open-interest sample." */
export function announcement(total: number, noSample: number): string {
  if (total === 0) return "All bars classified.";
  const bars = `${String(total)} ${total === 1 ? "bar" : "bars"} unclassified`;
  return noSample === total ? `${bars}, no open-interest sample.` : `${bars}.`;
}

export interface AnnounceOptions {
  /** True from the first render that has the served bars; nothing is seeded or announced before. */
  readonly ready: boolean;
  /** False while the counts are hidden (colouring off): the baseline follows silently. */
  readonly enabled: boolean;
  /** A change (symbol, interval) re-seeds the baseline. */
  readonly resetKey: string;
  /** Once per seed (symbol | interval), when the seeded count is above zero: a steady gap is reported. */
  readonly onSeed?: ((total: number, noSample: number) => void) | undefined;
  /** A change (the history phase) clears the spoken text, so a retry never re-announces a stale one. */
  readonly clearKey: string;
}

/**
 * The text for the pane's one polite status node: empty until a material change, then the sentence (the
 * node stays in the DOM). `onAnnounce` (memoised by the caller) is for the analytics counter.
 */
export function useUnclassifiedAnnouncement(
  total: number,
  noSample: number,
  barsInView: number,
  onAnnounce: ((total: number, noSample: number) => void) | undefined,
  { ready, enabled, resetKey, clearKey, onSeed }: AnnounceOptions,
): string {
  const baseline = useRef<number | null>(null);
  const seenReset = useRef(resetKey);
  const [text, setText] = useState("");
  useEffect(() => {
    setText("");
  }, [clearKey]);
  useEffect(() => {
    if (seenReset.current !== resetKey) {
      seenReset.current = resetKey;
      baseline.current = null;
      setText("");
    }
    if (!ready) return;
    if (baseline.current === null) {
      // the first reading is silent for the user; a steady gap still reaches telemetry, once per seed
      baseline.current = total;
      if (total > 0) onSeed?.(total, noSample);
      if (!enabled) setText("");
      return;
    }
    if (!enabled) {
      baseline.current = total;
      setText("");
      return;
    }
    if (!isMaterialChange(baseline.current, total, barsInView)) return;
    baseline.current = total;
    setText(announcement(total, noSample));
    onAnnounce?.(total, noSample);
  }, [total, noSample, barsInView, onAnnounce, onSeed, ready, enabled, resetKey]);
  return text;
}
