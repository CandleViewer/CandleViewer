/**
 * CMP-071 NavRail items (E10-S01 S5, #304). Each names a manifest route, so the rail asks
 * `evaluateAccess` about the route guard's own `RouteAccess`: no second role table.
 * The merged seven, in SCR-011 / E10-D02 :68 / D03 §5.1 order; Admin is owner-only in the rail
 * (sitemap §1.1 says the user menu, plan gap 1). PROPOSED for the owner (plan gap 3): the ticket
 * and sitemap §1.1 add Watchlist, Positions/Orders and Risk Dashboard (R-110, R-130, R-150).
 */
import type { IconName } from "@candleviewer/ui";

export interface NavItem {
  readonly id: string;
  /** The manifest route the item opens; its `access` decides whether the item renders. */
  readonly routeId: string;
  /** The CMP-019 glyph; `null` today: the registry (#4725) has no nav glyphs, the label stands in. */
  readonly icon: IconName | null;
  readonly label: string;
  /** Its `Alt+N` (`global.nav_rail`), fixed per item: a role without an item leaves a gap. */
  readonly digit: number;
}

export const NAV_ITEMS = [
  { id: "terminal", routeId: "R-100", icon: null, label: "Terminal", digit: 1 },
  { id: "rules", routeId: "R-160", icon: null, label: "Rules", digit: 2 },
  { id: "journal", routeId: "R-180", icon: null, label: "Journal", digit: 3 },
  { id: "replay", routeId: "R-170", icon: null, label: "Replay", digit: 4 },
  { id: "alerts", routeId: "R-190", icon: null, label: "Alerts", digit: 5 }, // D03 "Alerts · Alt+5"
  { id: "settings", routeId: "R-200", icon: null, label: "Settings", digit: 6 },
  { id: "admin", routeId: "R-300", icon: null, label: "Admin", digit: 7 },
] as const satisfies readonly NavItem[];

export type NavItemId = (typeof NAV_ITEMS)[number]["id"];

/** Badge words per item ("2 new", "3 armed"; E10-D02 :68). No count source exists yet. */
export type NavBadges = Readonly<Partial<Record<NavItemId, string>>>;
