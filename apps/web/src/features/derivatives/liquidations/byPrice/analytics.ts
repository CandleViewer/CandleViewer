// E24-S07 (#782) slice 2: the recorded layer's analytics on the app's seam (`cv:analytics`, as #780's): ids, enums
// and public symbols only, never a price or a notional. PROPOSED names: D02 §14 lists no event for (b), and
// `methodology.opened` is not emitted, as (b) has no chip and no SCR-058 link (BQ 12, ruled 6624627875).
import { THEME_ANALYTICS_EVENT } from "../../../../shell/bootstrap/themeStore";

export type Report = (detail: Readonly<Record<string, unknown>>) => void;

const CODE = /^[a-z0-9_]{1,40}$/;
const token = (code: string | null): string | null =>
  code === null ? null : CODE.test(code) ? code : "other";

const dispatch: Report = (detail) => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

export function createByPriceAnalytics(report: Report = dispatch) {
  return {
    /** The switch changed; `scope` says whether it was saved or is for the session only. */
    toggled: (symbol: string, enabled: boolean, scope: "persisted" | "session"): void =>
      report({ name: "liquidation.by_price_toggled", symbol, enabled, scope }),
    /** A read failed (`status` `null`: no answer) or its answer was refused (`status` 200). */
    readFailed: (symbol: string, status: number | null, code: string | null): void =>
      report({ name: "liquidation.by_price_failed", symbol, status, code: token(code) }),
  };
}

export type ByPriceAnalytics = ReturnType<typeof createByPriceAnalytics>;
