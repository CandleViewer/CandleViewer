// E24-S01 (#776) slice 1: the OI pane's analytics on the app's seam (`cv:analytics` on `window`, as
// SCR-103's): ids, enums and public symbols only, never a value (D02 §14; the ticket's Observability).
import type { HistoryAnomaly } from "./history";
import { THEME_ANALYTICS_EVENT } from "../../../shell/bootstrap/themeStore";

const CODE_TOKEN = /^[a-z0-9_]{1,40}$/;

export type Report = (detail: Readonly<Record<string, unknown>>) => void;

const dispatch: Report = (detail) => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

export function createOiAnalytics(sink: Report = dispatch) {
  // a throwing sink never breaks the feed: the event is dropped
  const report: Report = (detail) => {
    try {
      sink(detail);
    } catch {
      // analytics is best-effort
    }
  };
  return {
    /** D02 §14 `{mode, quadrant_colouring}`: the mode and colouring toggles call it. */
    metricToggled: (mode: "absolute" | "delta", quadrantColouring: boolean): void =>
      report({ name: "oi_panel.metric_toggled", mode, quadrant_colouring: quadrantColouring }),
    /** The chart interval re-aligning the series. */
    intervalChanged: (symbol: string, fromBarMs: number, toBarMs: number): void =>
      report({
        name: "oi_panel.interval_changed",
        symbol,
        from_bar_ms: fromBarMs,
        to_bar_ms: toBarMs,
      }),
    /**
     * PROPOSED name (the ticket's client-side error event; not in D02 §14 yet): the status, so the retry rate
     * is visible, `null` = no answer. `code` is the server's error token only if it reads as one, else "other".
     */
    backfillFailed: (symbol: string, status: number | null, code: string | null): void =>
      report({
        name: "oi_panel.backfill_failed",
        symbol,
        status,
        code: code === null ? null : CODE_TOKEN.test(code) ? code : "other",
      }),
    /** PROPOSED name: the read survived a server contract breach (`has_more` without a cursor); a counter, once per read. */
    backfillAnomaly: (symbol: string, anomaly: HistoryAnomaly): void =>
      report({ name: "oi_panel.backfill_anomaly", symbol, anomaly }),
  };
}

export type OiAnalytics = ReturnType<typeof createOiAnalytics>;

/** E24-S02 (#777): the unclassified counter, beside the feed's analytics (the feed never calls it). */
export function createQuadrantAnalytics(report: Report = dispatch) {
  return {
    /** A material change in the unclassified count (counts only, D02 §14). */
    unclassifiedCounted: (symbol: string, total: number, noSample: number): void =>
      report({ name: "oi_panel.unclassified_counted", symbol, total, no_sample: noSample }),
    /**
     * PROPOSED event name (not in D02 §14): the unclassified count a pane seeds with, once per symbol |
     * interval, so a steady gap present from the first render reaches telemetry (counts only).
     */
    unclassifiedSeeded: (symbol: string, total: number, noSample: number): void =>
      report({ name: "oi_panel.unclassified_seeded", symbol, total, no_sample: noSample }),
  };
}
