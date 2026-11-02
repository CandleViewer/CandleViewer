/**
 * SCR-103's analytics (E08-D06 §12; `14` SCR-103) on the app's seam, `cv:analytics` on `window`, as SCR-102's
 * (`searchEvents`) and SCR-157's: ids, enums and public symbols only, never a value, a role's data or a `Problem.detail`
 * (D13 §6.2). The drawer changes nothing, so there is no audit record.
 */
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import type { DetailFailure } from "./instrumentDetail";
import type { Malformed } from "./format";

export type InfoSource =
  "search" | "quick_switcher" | "chart_empty" | "watchlist" | "palette" | "deep_link";
export type Dependency = "catalogue" | "coverage" | "recorder" | "ticker";
export type LoadOutcome =
  | "network"
  | "http_403"
  | "http_404"
  | "http_422"
  | "http_5xx"
  | "http_503_60s"
  | "subscription_limit";

export type Report = (detail: Readonly<Record<string, unknown>>) => void;

const dispatch: Report = (detail) => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

/** `outcome` for a status: 403, 404 and 422 by number, 5xx together; any other status is `http_5xx`'s nearest, never invented. */
export function outcomeForStatus(status: number): LoadOutcome {
  if (status === 403) return "http_403";
  if (status === 404) return "http_404";
  if (status === 422) return "http_422";
  return "http_5xx";
}

/** A contract failure's `outcome` (D-12): 503s for 60 s is its own value. */
export function outcomeForFailure(failure: DetailFailure): LoadOutcome {
  if (failure.cause === "network" || failure.cause === "malformed") return "network";
  if (failure.cause === "unavailable") return "http_503_60s";
  return outcomeForStatus(failure.status);
}

export interface InfoViewed {
  readonly symbol: string;
  readonly source: InfoSource;
  readonly section: string | null;
  readonly status: string | null;
  readonly catalogue: "warm" | "cold";
  readonly role: string;
}

export function createSymbolInfoAnalytics(report: Report = dispatch) {
  const seen = new Set<string>();
  return {
    /** First paint. */
    viewed: (e: InfoViewed): void => report({ name: "symbol.info_viewed", ...e }),
    /** Once per failure. */
    loadFailed: (symbol: string, dependency: Dependency, outcome: LoadOutcome): void =>
      report({ name: "symbol.info_load_failed", symbol, dependency, outcome }),
    /** When rows are marked; `fields` are `22`'s names. */
    rulesChanged: (
      symbol: string,
      fields: readonly string[],
      revisionFrom: number | null,
      revisionTo: number | null,
    ): void =>
      report({
        name: "symbol.info_rules_changed",
        symbol,
        fields,
        revision_from: revisionFrom,
        revision_to: revisionTo,
      }),
    /** Once per field per session. */
    malformed: (symbol: string, field: string, kind: Malformed): void => {
      const key = `${symbol}|${field}`;
      if (seen.has(key)) return;
      seen.add(key);
      report({ name: "symbol.info_value_malformed", symbol, field, kind });
    },
  };
}

export type SymbolInfoAnalytics = ReturnType<typeof createSymbolInfoAnalytics>;
