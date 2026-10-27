/**
 * CMP-071 NavRail items (E10-S01 S5, #304). Each names a manifest route, so the rail asks
 * `evaluateAccess` about the route guard's own `RouteAccess`: no second role table.
 * The set and order are the ticket's ten; SCR-011, E10-D02 :68 and D03 §5.1 draw seven, sitemap
 * §1.1 lists ten with Admin before Settings (plan gap 3). Labels are SCR-011's, else sitemap
 * §1.1's. Admin is owner-only in the rail (ticket, SCR-011); sitemap §1.1 says the user menu (gap 1).
 */
import type { IconName } from "@candleviewer/ui";

export interface NavItem {
  readonly id: string;
  /** The manifest route the item opens; its `access` decides whether the item renders. */
  readonly routeId: string;
  /** The CMP-019 glyph; `null` today: the registry (#4725) has no nav glyphs, the label stands in. */
  readonly icon: IconName | null;
  readonly label: string;
}

export const NAV_ITEMS = [
  { id: "terminal", routeId: "R-100", icon: null, label: "Terminal" },
  { id: "watchlist", routeId: "R-110", icon: null, label: "Watchlist" },
  { id: "positions", routeId: "R-130", icon: null, label: "Positions/Orders" },
  { id: "risk", routeId: "R-150", icon: null, label: "Risk Dashboard" },
  { id: "rules", routeId: "R-160", icon: null, label: "Rules" },
  { id: "replay", routeId: "R-170", icon: null, label: "Replay" },
  { id: "journal", routeId: "R-180", icon: null, label: "Journal" },
  { id: "alerts", routeId: "R-190", icon: null, label: "Alerts" },
  { id: "settings", routeId: "R-200", icon: null, label: "Settings" },
  // Last, so it is the tenth item: `Alt+1..9` has nine digits and Admin gets none (plan gap 3).
  { id: "admin", routeId: "R-300", icon: null, label: "Admin" },
] as const satisfies readonly NavItem[];

export type NavItemId = (typeof NAV_ITEMS)[number]["id"];

/** Badge words per item ("2 new", "3 armed"; E10-D02 :68). No count source exists yet. */
export type NavBadges = Readonly<Partial<Record<NavItemId, string>>>;
