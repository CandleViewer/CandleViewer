// E24-S03 (#778): the funding pane's analytics on the app's seam (`cv:analytics` on `window`): ids, enums
// and public symbols only, never a value (D02 §14; the ticket's Observability).
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";

export type Report = (detail: Readonly<Record<string, unknown>>) => void;

const dispatch: Report = (detail) => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

export function createFundingAnalytics(report: Report = dispatch) {
  return {
    /** The ticket's client error event on a failed funding read; `null` = no answer. */
    historyFailed: (symbol: string, status: number | null, code: string | null): void =>
      report({ name: "funding.history_failed", symbol, status, code }),
  };
}

export type FundingAnalytics = ReturnType<typeof createFundingAnalytics>;
