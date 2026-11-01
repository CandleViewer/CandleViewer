// E11-T04 PR-3 (E11-D05 §5.3 / §5.5; 26 §3.8, §5 rule 1): the colour LUTs, computed from the
// ingested theme's stop slots — 256 RGBA8 entries per ramp, interpolated piecewise-linearly in
// OkLab between adjacent stops and clamped to sRGB after conversion. Output is straight sRGB
// (ADR-0024: linearised in the shader), never premultiplied.
//
// Rows (one 256 × LUT_ROWS texture, so a theme switch is one upload, BQ-T04-06):
//   LUT_ROW.bid   — `ramp.intensity.bid`, t in [0, 1]: zero · .2 bid.1 · … · 1 bid.5
//   LUT_ROW.ask   — `ramp.intensity.ask`, the same positions over ask.1..5
//   LUT_ROW.delta — `ramp.delta`, t in [−1, 1]: sell · −ε ask.1 · 0 canvas · +ε bid.1 · buy
// The "inverted" convention (owner decision #10) swaps the bid and ask rows, never their stops.
// The delta row's ±1 ends arrive already swapped (the host's `DIRECTIONAL_PAIRS` remap swaps
// `color.buy.default` / `color.sell.default`, not `color.heatmap.*`), so under "inverted" the
// engine swaps the ±ε stops (`bid.1` at −ε, `ask.1` at +ε) and each half keeps one hue.
// The imbalance LUT is dropped (G8 / C16: imbalance is the binary `pattern.outline.imbalance`).
// The canvas stop is `color.heatmap.zero` (D05 §5.3: "= the canvas"; `color.surface.canvas` is
// not an engine slot). The CVD-safe twins need G16's `color.cvd.` route; until it lands the
// palette changes nothing here (the host's directional remap still swaps the ±1 ends).
//
// Shader contract: sample texel centres only (`intensityU` / `deltaU` / `lutV`) — the texture is
// LINEAR-filtered, so an off-centre v blends the neighbouring row. t = 0 (intensity entry 0, delta
// entry 128) is the opaque canvas: consumers emit no fragment there (D05 "no ink at exactly zero").
//
// No allocation per call: a `ColorLutWriter` owns its scratch and writes into a caller-owned
// Uint8Array. It runs once per theme change, never per frame.

import { oklabToSrgb, srgbToOklab } from "./oklab.js";
import type { EngineTheme } from "./ThemeIngest.js";
import type { ThemeSlot } from "./slots.js";

/** Entries per ramp (26 §3.8 "256×1 LUT texture"). */
export const LUT_WIDTH = 256;
/** Row of each ramp in the LUT texture; the indices are append-only. */
export const LUT_ROW = Object.freeze({ bid: 0, ask: 1, delta: 2 } as const);
export const LUT_ROWS = 3;
/** Bytes of one row and of the whole LUT image. */
export const LUT_ROW_BYTES = LUT_WIDTH * 4;
export const LUT_BYTES = LUT_ROW_BYTES * LUT_ROWS;
/** The delta ramp's first visible stop, as a fraction of each half (D05 §5.3, PROPOSED). */
export const DELTA_EPSILON = 1 / 8;
/** The delta row's entry for t = 0 exactly: the canvas, the only entry with no ink. */
export const DELTA_ZERO_INDEX = 128;

/** An intensity entry's t: `i / 255`, so entry 0 is t = 0 and entry 255 is t = 1 exactly. */
export function intensityT(i: number): number {
  return i / (LUT_WIDTH - 1);
}

/**
 * A delta entry's t. The negative half spans entries 0..128 (128 steps, entry 0 = −1) and the
 * positive half 128..255 (127 steps, entry 255 = +1), so −1, 0 and +1 each land on an entry.
 */
export function deltaT(i: number): number {
  const d = i - DELTA_ZERO_INDEX;
  return d < 0 ? d / DELTA_ZERO_INDEX : d / (LUT_WIDTH - 1 - DELTA_ZERO_INDEX);
}

/** The horizontal texel-centre coordinate of intensity `t` in [0, 1] (inverse of `intensityT`). */
export function intensityU(t: number): number {
  return (t * (LUT_WIDTH - 1) + 0.5) / LUT_WIDTH;
}

/** The horizontal texel-centre coordinate of delta `t` in [−1, 1] (the inverse of `deltaT`). */
export function deltaU(t: number): number {
  const steps = t < 0 ? DELTA_ZERO_INDEX : LUT_WIDTH - 1 - DELTA_ZERO_INDEX;
  return (DELTA_ZERO_INDEX + t * steps + 0.5) / LUT_WIDTH;
}

/** The vertical texel-centre coordinate of LUT row `row`. */
export function lutV(row: number): number {
  return (row + 0.5) / LUT_ROWS;
}

type Side = "bid" | "ask";
type Stops = readonly (readonly [slot: ThemeSlot, t: number])[];

const intensityStops = (side: Side): Stops =>
  Object.freeze([
    ["color.heatmap.zero", 0],
    [`color.heatmap.${side}.1`, 0.2],
    [`color.heatmap.${side}.2`, 0.4],
    [`color.heatmap.${side}.3`, 0.6],
    [`color.heatmap.${side}.4`, 0.8],
    [`color.heatmap.${side}.5`, 1],
  ] as const);

/** The ramps' stop slots and positions (D05 §5.3), as data. */
export const RAMP_STOPS: Readonly<Record<"bid" | "ask" | "delta", Stops>> = Object.freeze({
  bid: intensityStops("bid"),
  ask: intensityStops("ask"),
  delta: Object.freeze([
    ["color.sell.default", -1],
    ["color.heatmap.ask.1", -DELTA_EPSILON],
    ["color.heatmap.zero", 0],
    ["color.heatmap.bid.1", DELTA_EPSILON],
    ["color.buy.default", 1],
  ] as const),
});

/** The delta stops under "inverted": the ±ε stops swap with the host-swapped ±1 ends. */
export const DELTA_STOPS_INVERTED: Stops = Object.freeze([
  ["color.sell.default", -1],
  ["color.heatmap.bid.1", -DELTA_EPSILON],
  ["color.heatmap.zero", 0],
  ["color.heatmap.ask.1", DELTA_EPSILON],
  ["color.buy.default", 1],
] as const);

const deltaStops = (theme: EngineTheme): Stops =>
  theme.convention === "inverted" ? DELTA_STOPS_INVERTED : RAMP_STOPS.delta;

const MAX_STOPS = 6;

export class ColorLutWriter {
  /** Per stop: OkLab L, a, b, then straight alpha. */
  readonly #lab = new Float64Array(MAX_STOPS * 4);
  readonly #pos = new Float64Array(MAX_STOPS);
  readonly #rgb = new Float64Array(3);

  /**
   * Writes every row (bid, ask, delta; `LUT_BYTES`) into `out` from byte `offset`. Under the
   * "inverted" convention the bid row holds the ask ramp and the ask row the bid ramp, and the
   * delta row uses `DELTA_STOPS_INVERTED`.
   */
  writeAll(theme: EngineTheme, out: Uint8Array, offset = 0): Uint8Array {
    checkRange(out, offset, LUT_BYTES);
    const swap = theme.convention === "inverted";
    this.#write(theme, RAMP_STOPS[swap ? "ask" : "bid"], false, out, offset);
    this.#write(theme, RAMP_STOPS[swap ? "bid" : "ask"], false, out, offset + LUT_ROW_BYTES);
    this.#write(theme, deltaStops(theme), true, out, offset + 2 * LUT_ROW_BYTES);
    return out;
  }

  /** Writes one intensity ramp (`LUT_ROW_BYTES`), unswapped, into `out` from `offset`. */
  writeIntensity(theme: EngineTheme, side: Side, out: Uint8Array, offset = 0): Uint8Array {
    checkRange(out, offset, LUT_ROW_BYTES);
    this.#write(theme, RAMP_STOPS[side], false, out, offset);
    return out;
  }

  /** Writes the delta ramp (`LUT_ROW_BYTES`, per the convention) into `out` from `offset`. */
  writeDelta(theme: EngineTheme, out: Uint8Array, offset = 0): Uint8Array {
    checkRange(out, offset, LUT_ROW_BYTES);
    this.#write(theme, deltaStops(theme), true, out, offset);
    return out;
  }

  #write(theme: EngineTheme, stops: Stops, delta: boolean, out: Uint8Array, offset: number): void {
    const lab = this.#lab;
    const pos = this.#pos;
    const n = stops.length;
    for (let k = 0; k < n; k += 1) {
      const [slot, t] = stops[k] as Stops[number];
      const c = theme.slots[slot];
      srgbToOklab(c[0], c[1], c[2], lab, k * 4);
      lab[k * 4 + 3] = c[3];
      pos[k] = t;
    }
    const rgb = this.#rgb;
    let seg = 0;
    for (let i = 0; i < LUT_WIDTH; i += 1) {
      const t = delta ? deltaT(i) : intensityT(i);
      while (seg < n - 2 && t > (pos[seg + 1] as number)) seg += 1;
      const t0 = pos[seg] as number;
      const f = (t - t0) / ((pos[seg + 1] as number) - t0);
      const a = seg * 4;
      const b = a + 4;
      const L = lerp(lab[a] as number, lab[b] as number, f);
      const A = lerp(lab[a + 1] as number, lab[b + 1] as number, f);
      const B = lerp(lab[a + 2] as number, lab[b + 2] as number, f);
      oklabToSrgb(L, A, B, rgb);
      const o = offset + i * 4;
      out[o] = toByte(rgb[0] as number);
      out[o + 1] = toByte(rgb[1] as number);
      out[o + 2] = toByte(rgb[2] as number);
      // Straight alpha (ADR-0024, no premultiply): exact for the opaque stops the tokens ship; a
      // translucent stop would fringe the segment toward its own RGB.
      out[o + 3] = toByte(lerp(lab[a + 3] as number, lab[b + 3] as number, f));
    }
  }
}

/** Exact at f = 0 and f = 1, so an entry on a stop position reproduces that stop. */
function lerp(x: number, y: number, f: number): number {
  return f <= 0 ? x : f >= 1 ? y : x + (y - x) * f;
}

function toByte(v: number): number {
  return Math.round((v <= 0 ? 0 : v >= 1 ? 1 : v) * 255);
}

function checkRange(out: Uint8Array, offset: number, bytes: number): void {
  if (!Number.isInteger(offset) || offset < 0) {
    throw new RangeError("ColorLutWriter: offset must be a non-negative integer");
  }
  if (out.length - offset < bytes) throw new RangeError("ColorLutWriter: out too short");
}
