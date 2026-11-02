// E11-T04 (BQ-T04-03, BQ-T04-04; AC4): the host's token object → a frozen engine theme. Pure: no
// DOM, no design-system import (C-2.16). It runs once per theme change, never per frame; the frame
// path reads the result through `packTheme` into a caller-owned buffer (no allocation).
//
// The output is straight sRGB 0..1 (ADR-0024 §5: linearised in the shader), not premultiplied as
// the ticket's interface says (BQ-T04-03). Unknown colour keys are ignored: the host may pass the
// whole engine export. A missing or invalid slot throws ENGINE_THEME_INVALID naming it, and the
// caller's installed theme is untouched (`ThemeState.apply` swaps only on success).

import { ENGINE_THEME_INVALID } from "./codes.js";
import { SLOT_COUNT, THEME_SLOTS, type ThemeSlot } from "./slots.js";

export type ThemeName = "dark" | "light" | "high-contrast";
export type ThemePalette = "default" | "cvd-safe";
export type ThemeConvention = "standard" | "inverted";

/** Structurally §8 `ThemeTokens` plus BQ-T04-03's optional `name` (additive; §8 must-not-break). */
export interface ThemeIngestInput {
  readonly name?: ThemeName;
  readonly palette: ThemePalette;
  readonly convention: ThemeConvention;
  readonly colors: Readonly<Record<string, string>>;
}

/** One straight-sRGB colour, each channel in [0, 1]. Frozen. */
export type Rgba = readonly [r: number, g: number, b: number, a: number];

/** The resolved theme: every slot present, deep-frozen. Internal (never a root export, BQ-2). */
export interface EngineTheme {
  readonly name: ThemeName | null;
  readonly palette: ThemePalette;
  readonly convention: ThemeConvention;
  readonly slots: Readonly<Record<ThemeSlot, Rgba>>;
}

export type ThemeInvalidReason = "missing" | "invalid";

/** ENGINE_THEME_INVALID: `key` is the offending slot or field; nothing was installed. */
export class ThemeIngestError extends Error {
  readonly code = ENGINE_THEME_INVALID;
  constructor(
    readonly key: string,
    readonly reason: ThemeInvalidReason,
  ) {
    super(`${ENGINE_THEME_INVALID}: ${reason} "${key}"`);
    this.name = "ThemeIngestError";
  }
}

const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
const NAMES: readonly string[] = ["dark", "light", "high-contrast"];
const PALETTES: readonly string[] = ["default", "cvd-safe"];
const CONVENTIONS: readonly string[] = ["standard", "inverted"];

/** `#rgb`, `#rrggbb` or `#rrggbbaa` → straight sRGB 0..1; anything else is null. */
export function parseHexColor(value: unknown): Rgba | null {
  if (typeof value !== "string" || !HEX.test(value)) return null;
  const h = value.slice(1);
  const wide = h.length === 3 ? h.replace(/./g, "$&$&") : h;
  const byte = (i: number): number => Number.parseInt(wide.slice(i * 2, i * 2 + 2), 16) / 255;
  return Object.freeze([byte(0), byte(1), byte(2), wide.length === 8 ? byte(3) : 1] as const);
}

function field(input: Record<string, unknown>, key: string, allowed: readonly string[]): string {
  const v = input[key];
  if (v === undefined) throw new ThemeIngestError(key, "missing");
  if (typeof v !== "string" || !allowed.includes(v)) throw new ThemeIngestError(key, "invalid");
  return v;
}

/**
 * Validates and resolves a token object. Throws `ThemeIngestError` naming the first bad key, in
 * the order: `palette`, `convention`, `name`, `colors`, then the slots in `THEME_SLOTS` order.
 */
export function ingestTheme(input: unknown): EngineTheme {
  if (typeof input !== "object" || input === null) throw new ThemeIngestError("theme", "invalid");
  const rec = input as Record<string, unknown>;
  const palette = field(rec, "palette", PALETTES) as ThemePalette;
  const convention = field(rec, "convention", CONVENTIONS) as ThemeConvention;
  const name = rec["name"] === undefined ? null : (field(rec, "name", NAMES) as ThemeName);
  const colors = rec["colors"];
  if (colors === undefined) throw new ThemeIngestError("colors", "missing");
  if (typeof colors !== "object" || colors === null) {
    throw new ThemeIngestError("colors", "invalid");
  }
  const map = colors as Record<string, unknown>;
  const slots = {} as Record<ThemeSlot, Rgba>;
  for (const slot of THEME_SLOTS) {
    if (!Object.hasOwn(map, slot)) throw new ThemeIngestError(slot, "missing");
    const rgba = parseHexColor(map[slot]);
    if (rgba === null) throw new ThemeIngestError(slot, "invalid");
    slots[slot] = rgba;
  }
  return Object.freeze({ name, palette, convention, slots: Object.freeze(slots) });
}

/** Floats `packTheme` writes: one RGBA quad per slot, in `THEME_SLOTS` order. */
export const PACKED_THEME_LENGTH = SLOT_COUNT * 4;

/** Writes every slot into `out` (length ≥ PACKED_THEME_LENGTH) from `offset`; allocates nothing. */
export function packTheme(theme: EngineTheme, out: Float32Array, offset = 0): Float32Array {
  if (!Number.isInteger(offset) || offset < 0) {
    throw new RangeError("packTheme: offset must be a non-negative integer");
  }
  if (out.length - offset < PACKED_THEME_LENGTH) throw new RangeError("packTheme: out too short");
  for (let i = 0; i < SLOT_COUNT; i += 1) {
    const c = theme.slots[THEME_SLOTS[i] as ThemeSlot];
    const o = offset + i * 4;
    out[o] = c[0];
    out[o + 1] = c[1];
    out[o + 2] = c[2];
    out[o + 3] = c[3];
  }
  return out;
}

/** Holds the installed theme; `apply` installs all of a valid theme or nothing (AC4). */
export class ThemeState {
  #current: EngineTheme | null = null;

  get current(): EngineTheme | null {
    return this.#current;
  }

  apply(input: unknown): EngineTheme {
    const next = ingestTheme(input);
    this.#current = next;
    return next;
  }
}
