// E24-S05 (#780) PR 4: the feed's analytics on the app's seam (`cv:analytics` on `window`, as SCR-103's and
// E24-S01's): ids, enums and public symbols only, never a price, size or notional (D02 §14; the ticket's
// Observability).
import { THEME_ANALYTICS_EVENT } from "../../../shell/bootstrap/themeStore";
import type { LiquidatedSide } from "./side";

export type Report = (detail: Readonly<Record<string, unknown>>) => void;

const dispatch: Report = (detail) => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

export function createLiqAnalytics(report: Report = dispatch) {
  return {
    /** D02 §6 / §14: a feed row activated (the crosshair moves to its time). */
    printClicked: (symbol: string, side: LiquidatedSide, clusterSize: number): void =>
      report({ name: "liquidation.print_clicked", symbol, side, cluster_size: clusterSize }),
    /** The ticket's error event when the backfill read fails; `null` = no answer. */
    backfillFailed: (symbol: string, status: number | null, code: string | null): void =>
      report({ name: "liquidation.backfill_failed", symbol, status, code }),
  };
}

export type LiqAnalytics = ReturnType<typeof createLiqAnalytics>;
