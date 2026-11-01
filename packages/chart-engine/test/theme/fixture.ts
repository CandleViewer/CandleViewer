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
