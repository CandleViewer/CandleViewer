/**
 * E40 alert surfaces x theme x zoom matrix for the a11y collectors (E40-Q02 Part B pre-stage, BQ-08).
 * None of the five surfaces is on main, so every entry carries `blockedBy` and the collectors only
 * REPORT it as skipped (a `skipped` list in axe.json / keyboard.json); nothing is opened, so no
 * collector can fail on a screen that does not exist. A surface slice un-skips its own entries in
 * the PR that ships the surface: it deletes `blockedBy` and adds the theme / zoom applier to
 * open.ts, then moves the entry into SIGNED_IN (screens.ts). Contract:
 * docs/design/a11y/e40-alerts-a11y-review.md; audit: docs/qa/a11y/e40-alerts-audit.md.
 */
export const ALERT_THEMES = ["dark", "light", "high-contrast"] as const;
export const ALERT_ZOOMS = [100, 200] as const;
export type AlertTheme = (typeof ALERT_THEMES)[number];
export type AlertZoom = (typeof ALERT_ZOOMS)[number];

export interface AlertSurface {
  readonly scr: string;
  readonly name: string;
  /** Route for a page surface; a modal or drawer is opened from its host route instead. */
  readonly path: string;
  readonly blockedBy: string;
}

export interface AlertSurfaceEntry extends AlertSurface {
  readonly id: string;
  readonly theme: AlertTheme;
  readonly zoom: AlertZoom;
}

const S01 = "E40-S01 #1129 (alert surfaces not on main)";
const S02 = "E40-S02 #1130 (notification surfaces not on main)";

export const ALERT_SURFACES: readonly AlertSurface[] = [
  { scr: "SCR-090", name: "alerts centre", path: "/alerts", blockedBy: S01 },
  { scr: "SCR-091", name: "alert editor modal", path: "/alerts", blockedBy: S01 },
  { scr: "SCR-014", name: "notification centre drawer", path: "/terminal/last", blockedBy: S02 },
  { scr: "SCR-092", name: "alert detail drawer", path: "/alerts", blockedBy: S02 },
  {
    scr: "SCR-115",
    name: "notifications settings section",
    path: "/settings/notifications",
    blockedBy: S02,
  },
];

export const ALERT_SURFACE_ENTRIES: readonly AlertSurfaceEntry[] = ALERT_SURFACES.flatMap((s) =>
  ALERT_THEMES.flatMap((theme) =>
    ALERT_ZOOMS.map((zoom) => ({ ...s, id: `${s.scr}/${theme}/${zoom}`, theme, zoom })),
  ),
);

/** What a collector writes under `skipped`: id plus the named blocker. */
export const skippedAlertEntries = (): { id: string; reason: string }[] =>
  ALERT_SURFACE_ENTRIES.map((e) => ({ id: e.id, reason: `skipped: blocked by ${e.blockedBy}` }));
