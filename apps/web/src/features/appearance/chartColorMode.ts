import type { EngineHandle, EngineTheme } from "@candleviewer/chart-engine/compat";
import {
  applyChartColorMode,
  type ChartConvention,
  type ChartPalette,
} from "../../shell/bootstrap/preferencesApply.js";

/** Token names the engine palette texture carries (resolved from root CSS vars). */
export const ENGINE_TOKENS = [
  "color.buy.default",
  "color.sell.default",
  "color.candle.up",
  "color.candle.down",
  "color.footprint.bid",
  "color.footprint.ask",
] as const;

/** Builds the engine theme token object from the root's resolved custom properties. */
export function readEngineTheme(
  root: HTMLElement = document.documentElement,
  view: Window = window,
): EngineTheme {
  const style = view.getComputedStyle(root);
  const colors: Record<string, string> = {};
  for (const name of ENGINE_TOKENS) {
    colors[name] = style.getPropertyValue(`--${name.replace(/\./g, "-")}`).trim();
  }
  return {
    palette: root.getAttribute("data-palette") === "cvd-safe" ? "cvd-safe" : "default",
    convention: root.getAttribute("data-convention") === "inverted" ? "inverted" : "standard",
    colors,
  };
}

/**
 * Applies a chart colour mode to the root (DOM surfaces key off the
 * attributes) and passes the resulting token object to the engine host
 * adapter, which re-uploads its palette. The engine never imports the design
 * system: tokens cross only through `setTheme`.
 */
export function applyChartColorModeToSurfaces(
  mode: { palette: ChartPalette; convention: ChartConvention },
  engines: readonly Pick<EngineHandle, "setTheme">[],
  root: HTMLElement = document.documentElement,
): void {
  applyChartColorMode(mode, root);
  const theme = readEngineTheme(root);
  for (const e of engines) e.setTheme(theme);
}
