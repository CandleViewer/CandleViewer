/**
 * Feeds the server's appearance and accessibility settings (`GET /me/preferences`, and the
 * accessibility preferences once they load) to the theme runtime of `@candleviewer/ui` so the chrome
 * renders in the stored theme without a page reload (ticket AC "Preferences apply without reload").
 * The runtime owns the `data-theme`, `data-density`, `data-motion` and `data-text-scale` root
 * attributes (#3139): nothing in `apps/web` writes them, and this module owns no token values.
 */
import type { ThemeStore } from "@candleviewer/ui";
import { themeFromSettings, type ThemeSettings } from "./themeFromSettings.js";
import { HYDRATE, appThemeStore } from "./themeStore.js";

/**
 * Applies `settings` to the app's theme store (or `store`) as one change. Only what the server sent
 * is applied (see `themeFromSettings`), so missing or invalid values, and a failed load (`undefined`),
 * leave a persisted local choice or the pre-paint value in place instead of resetting it to a default.
 */
export function applyAppearance(
  settings: ThemeSettings | undefined,
  store: ThemeStore = appThemeStore(),
): void {
  store.apply(themeFromSettings(settings), HYDRATE);
}

export type ChartPalette = "default" | "cvd-safe";
export type ChartConvention = "standard" | "inverted";

/**
 * Root-level chart colour contract (E47-S06): `data-palette` selects the
 * CVD-safe `color.cvd.*` set and `data-convention` the buy/sell colour
 * convention. Every surface keys off these two attributes, so a change
 * reaches all views (including the canvas theme object) from one place.
 * The choice is persisted locally; server persistence needs a separate contract-first PR (C-6.1).
 */
export function applyChartColorMode(
  mode: { palette?: ChartPalette; convention?: ChartConvention },
  root: HTMLElement = document.documentElement,
): void {
  root.setAttribute("data-palette", mode.palette ?? "default");
  root.setAttribute("data-convention", mode.convention ?? "standard");
}

const MODE_KEY = "cv.chartColorMode";

/** Local (pre-SCR-116) persisted choice; invalid/missing values fall back to defaults. */
export function readStoredChartColorMode(
  storage: Pick<Storage, "getItem"> | undefined = typeof localStorage === "undefined"
    ? undefined
    : localStorage,
): { palette?: ChartPalette; convention?: ChartConvention } {
  try {
    const raw = JSON.parse(storage?.getItem(MODE_KEY) ?? "{}") as Record<string, unknown>;
    return {
      ...(raw["palette"] === "cvd-safe" ? { palette: "cvd-safe" as const } : {}),
      ...(raw["convention"] === "inverted" ? { convention: "inverted" as const } : {}),
    };
  } catch {
    return {};
  }
}
