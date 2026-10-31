/**
 * SCR-100's and SCR-101's analytics (`14` SCR-100 and SCR-101 "Analytics/audit", the names only): on the app's seam,
 * `cv:analytics` on `window`, as SCR-102 and SCR-157 report; nothing leaves the page. Payloads carry ids, counts,
 * positions, column ids and public symbols (E08-D07 §4.5), never a value or a list's name.
 */
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";

export type WatchlistEvent =
  | {
      readonly name:
        "watchlist.symbol_added" | "watchlist.symbol_removed" | "watchlist.symbol_activated";
      readonly watchlist_id: string;
      readonly symbol: string;
    }
  | {
      readonly name: "watchlist.reordered";
      readonly watchlist_id: string;
      readonly symbol: string;
      readonly position: number;
    }
  | {
      readonly name: "watchlist.column_changed";
      readonly watchlist_id: string;
      readonly column: string;
      readonly visible: boolean;
    }
  | {
      readonly name:
        | "watchlist.created"
        | "watchlist.renamed"
        | "watchlist.duplicated"
        | "watchlist.deleted"
        | "watchlist.exported";
      readonly watchlist_id: string;
    }
  | {
      readonly name: "watchlist.imported" | "watchlist.bulk_added";
      readonly watchlist_id: string;
      readonly count: number;
    }
  | {
      readonly name: "data_confidence.state_entered";
      readonly surface: "SCR-100";
      readonly state: "stale" | "disconnected";
    };

export function reportWatchlist(event: WatchlistEvent): void {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail: event }));
}
