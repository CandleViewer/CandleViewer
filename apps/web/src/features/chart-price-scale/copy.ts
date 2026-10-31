/**
 * SCR-043's price-scale menu copy, verbatim from E11-D03 §13 (the copy deck) unless marked
 * PROPOSED. The engine reports `logReason` as a code; the words are the UI's (README BQ-120, C-32).
 */
import type { PriceScale } from "@candleviewer/chart-engine";

export type ScaleMode = ReturnType<PriceScale["getState"]>["mode"];
type LogReason = NonNullable<ReturnType<PriceScale["getState"]>["logReason"]>;

export const PRICE_SCALE_COPY = {
  menu: "Price scale menu",
  modeGroup: "Scale mode",
  scaleGroup: "Scale",
  modes: {
    linear: "Linear",
    log: "Logarithmic",
    percent: "Percent",
    indexed: "Indexed to 100",
  } satisfies Record<ScaleMode, string>,
  lock: "Lock scale",
  lockDescription: "Unchecked: auto-scale fits the visible bars",
  invert: "Invert scale",
  merge: "Merge indicator scales",
  mergeReason: "No indicator scales on this pane",
  priceOnly: "Scale price only",
  priceOnlyDescription: "Unchecked: overlay indicators count toward the range",
  reset: "Reset scale",
  resetReason: "Already auto-scaled",
  /** D5: the second clause the reason gains after a fallback. */
  kept: "Your Logarithmic preference is kept",
  said: {
    modes: {
      linear: "Price scale: linear",
      log: "Price scale: logarithmic",
      percent: "Price scale: percent",
      indexed: "Price scale: indexed to 100",
    } satisfies Record<ScaleMode, string>,
    locked: "Price scale locked",
    auto: "Price scale: auto",
    inverted: "Price scale inverted",
    upright: "Price scale upright",
    priceOnly: "Price scale: price only",
    overlays: "Price scale: includes overlays",
    fallback: "Log scale unavailable — switched to linear: this series now contains a value <= 0",
  },
} as const;

const LOG_REASONS: Record<LogReason, string> = {
  // #309's string (E11-D03 §3.5 D4).
  "non-positive": "Log scale needs all-positive values; this series contains a value <= 0",
  // PROPOSED (owner E11-D03, to route on #309): D03 has no string for a pane with no bars yet
  // (README BQ-115); a PR Deviation until D03 adopts or replaces it.
  "no-price-origin": "Log scale needs prices; this pane has no bars yet",
};

/** The Logarithmic item's T2 reason; after a D5 fallback (log still asked) it adds D5's clause. */
export function logReasonText(reason: LogReason, requested: ScaleMode): string {
  const text = LOG_REASONS[reason];
  return requested === "log" ? `${text}. ${PRICE_SCALE_COPY.kept}` : text;
}
