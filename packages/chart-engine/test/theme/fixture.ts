// E11-T04 test fixture: a synthetic, complete token map (deterministic hexes, not the design
// system's values — the engine never copies token values, BQ-T04-07).
import { THEME_SLOTS } from "../../src/theme/slots.js";
import type { ThemeIngestInput } from "../../src/theme/ThemeIngest.js";

export function hexFor(i: number): string {
  const v = (i * 0x0a1b2c + 0x102030) & 0xffffff;
  return `#${v.toString(16).padStart(6, "0")}`;
}

export function fullColors(): Record<string, string> {
  return Object.fromEntries(THEME_SLOTS.map((s, i) => [s, hexFor(i)]));
}

export function validInput(overrides: Partial<ThemeIngestInput> = {}): ThemeIngestInput {
  return { palette: "default", convention: "standard", colors: fullColors(), ...overrides };
}

// E11-T04 PR-3: the ramp stops D05 §5.2 measured (dark, light, hc), over the synthetic map, so the
// LUT tests run on real ramp shapes. Measurement vectors, not the theme: the engine copies no value.
// hc shares dark's heatmap stops; its ±1 ends are the lighter green / red (L .7882 / .7425).
const RAMP_STOPS = {
  dark: ["#11151A", "#1B7539", "#23994A", "#2AAF53", "#4FC86F", "#6BD48A"],
  darkAsk: ["#B83539", "#D8474B", "#EA6363", "#F08A8A", "#F5B0B0"],
  light: ["#F6F7F9", "#2E9A55", "#1C7A3C", "#136B30", "#0A4A20", "#0A3018"],
  lightAsk: ["#D14A4E", "#B8353A", "#962C30", "#7A1E22", "#4E1518"],
} as const;

const ENDS = {
  dark: { buy: "#2EBD59", sell: "#E5484D" },
  light: { buy: "#1C7A3C", sell: "#C7373C" },
  hc: { buy: "#6BD48A", sell: "#F08A8A" },
} as const;

/**
 * A ramp theme. With `convention: "inverted"` the ±1 ends are swapped as the host's
 * `DIRECTIONAL_PAIRS` remap delivers them (buy ↔ sell; `color.heatmap.*` untouched).
 */
export function rampInput(
  theme: "dark" | "light" | "hc",
  overrides: Partial<ThemeIngestInput> = {},
): ThemeIngestInput {
  const bid = RAMP_STOPS[theme === "light" ? "light" : "dark"];
  const ask = RAMP_STOPS[theme === "light" ? "lightAsk" : "darkAsk"];
  const colors = fullColors();
  colors["color.heatmap.zero"] = bid[0];
  for (let n = 1; n <= 5; n += 1) {
    colors[`color.heatmap.bid.${n}`] = bid[n] as string;
    colors[`color.heatmap.ask.${n}`] = ask[n - 1] as string;
  }
  const inverted = overrides.convention === "inverted";
  colors["color.buy.default"] = inverted ? ENDS[theme].sell : ENDS[theme].buy;
  colors["color.sell.default"] = inverted ? ENDS[theme].buy : ENDS[theme].sell;
  return validInput({ colors, ...overrides });
}
