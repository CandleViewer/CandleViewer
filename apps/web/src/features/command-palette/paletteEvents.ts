/**
 * SCR-012's analytics (E10-S05, #5236) on the app's seam (`cv:analytics` on `window`, as `keymap/analytics.ts` and
 * `symbol-search/searchEvents.ts` report; nothing leaves the page). Two names, both PROPOSED (no merged spec names
 * them). An event carries ids, a group and the query's length: never the query text, never the user. A row the session
 * cannot see (an `/admin/*` route without `admin:read`) is never in the index, so its id can never be reported.
 */
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";

export type PaletteVia = "hotkey" | "trigger";

export type PaletteEvent =
  | { readonly name: "palette.opened"; readonly via: PaletteVia }
  | {
      readonly name: "palette.ran";
      readonly kind: "route" | "command";
      readonly id: string;
      readonly group: string;
      readonly dangerous: boolean;
      readonly query_length: number;
    };

export function reportPalette(event: PaletteEvent): void {
  window.dispatchEvent(new CustomEvent<PaletteEvent>(THEME_ANALYTICS_EVENT, { detail: event }));
}
