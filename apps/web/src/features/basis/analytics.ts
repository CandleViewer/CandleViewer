// E24-S08 (#783) slice 2: the basis readout's analytics on the app's seam (`cv:analytics` on `window`, as
// the OI pane's): ids, enums and public symbols only, never a value (the ticket's Observability: source
// toggles, a client error event with the status on source failure, a counter of retry-state renders).
// `deriv.basis.annualised` has no toggle (BQ 4), so no event for it.
//
// An analytics module pattern exists on main only as the `cv:analytics` seam (themeStore, gpuCrash); the
// sibling #776 `createOiAnalytics` is the shape followed here and is not imported (its PR is in flight).
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import type { BasisSource } from "./settings";

export type Report = (detail: Readonly<Record<string, unknown>>) => void;

const dispatch: Report = (detail) => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

export function createBasisAnalytics(report: Report = dispatch) {
  return {
    /** The source selector changed: `{source}`. */
    sourceToggled: (source: BasisSource): void => report({ name: "basis.source_toggled", source }),
    /** The ticket's client error event: the topic status that made the source fail. */
    sourceFailed: (symbol: string, status: string): void =>
      report({ name: "basis.source_failed", symbol, status }),
    /** The counter of retry-state renders: one per entry into the failed state. */
    retryShown: (symbol: string): void => report({ name: "basis.retry_shown", symbol }),
    retryClicked: (symbol: string): void => report({ name: "basis.retry_clicked", symbol }),
  };
}

export type BasisAnalytics = ReturnType<typeof createBasisAnalytics>;
