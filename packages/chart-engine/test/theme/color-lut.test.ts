// E11-T04 PR-3 (E11-D05 §5.3 / §5.5): the colour LUT rows — exact endpoints, monotone lightness
// within each intensity half, the delta ramp continuous through zero with t = 0 the canvas, and
// the convention swapping the intensity rows and the delta row's ±ε stops (the host swaps its ±1
// ends), the texel-centre mapping. No allocation per call: one caller-owned buffer.
import { describe, expect, it } from "vitest";
import {
  ColorLutWriter,
  DELTA_EPSILON,
  DELTA_STOPS_INVERTED,
  DELTA_ZERO_INDEX,
  LUT_BYTES,
  LUT_ROW,
  LUT_ROW_BYTES,
  LUT_ROWS,
  LUT_WIDTH,
  RAMP_STOPS,
  deltaT,
  deltaU,
  intensityT,
  intensityU,
  lutV,
} from "../../src/theme/ColorLut.js";
import { srgbToOklab } from "../../src/theme/oklab.js";
import { ingestTheme, type EngineTheme } from "../../src/theme/ThemeIngest.js";
import type { ThemeSlot } from "../../src/theme/slots.js";
import { rampInput } from "./fixture.js";

const THEMES = ["dark", "light", "hc"] as const;
const writer = new ColorLutWriter();

function luts(theme: EngineTheme): Uint8Array {
  return writer.writeAll(theme, new Uint8Array(LUT_BYTES));
}

const entry = (lut: Uint8Array, row: number, i: number): number[] =>
  Array.from(lut.subarray(row * LUT_ROW_BYTES + i * 4, row * LUT_ROW_BYTES + i * 4 + 4));

const bytesOf = (theme: EngineTheme, slot: ThemeSlot): number[] =>
  theme.slots[slot].map((c) => Math.round(c * 255));

/** OkLab L of an RGBA8 entry. */
function lightness(lut: Uint8Array, row: number, i: number): number {
  const [r, g, b] = entry(lut, row, i) as [number, number, number];
  const v = new Float64Array(3);
  srgbToOklab(r / 255, g / 255, b / 255, v);
  return v[0] as number;
}

/** 0 when `xs` is monotone (either direction); else the largest step against the trend. */
function reversal(xs: readonly number[]): number {
  const dir = Math.sign((xs.at(-1) as number) - (xs[0] as number));
  let worst = 0;
  for (let i = 1; i < xs.length; i += 1) {
    worst = Math.max(worst, -dir * ((xs[i] as number) - (xs[i - 1] as number)));
  }
  return worst;
}

describe("LUT index ↔ t", () => {
  it("intensity entries span [0, 1] with exact ends", () => {
    expect([intensityT(0), intensityT(51), intensityT(255)]).toEqual([0, 0.2, 1]);
  });

  it("delta entries put −1, −ε, 0 and +1 on entries", () => {
    expect([deltaT(0), deltaT(112), deltaT(DELTA_ZERO_INDEX), deltaT(255)]).toEqual([
      -1,
      -DELTA_EPSILON,
      0,
      1,
    ]);
  });

  it("intensityU / deltaU map every entry's t to that texel's centre", () => {
    for (let i = 0; i < LUT_WIDTH; i += 1) {
      expect(intensityU(intensityT(i))).toBeCloseTo((i + 0.5) / LUT_WIDTH, 12);
      expect(deltaU(deltaT(i))).toBeCloseTo((i + 0.5) / LUT_WIDTH, 12);
    }
    expect(deltaU(0)).toBe((DELTA_ZERO_INDEX + 0.5) / LUT_WIDTH);
  });

  it("lutV is each row's centre", () => {
    expect([LUT_ROW.bid, LUT_ROW.ask, LUT_ROW.delta].map(lutV)).toEqual(
      [0.5, 1.5, 2.5].map((v) => v / LUT_ROWS),
    );
  });
});

describe.each(THEMES)("ColorLutWriter, %s ramp stops", (name) => {
  const theme = ingestTheme(rampInput(name));
  const lut = luts(theme);

  it("intensity rows: entry 0 is heatmap.zero, entry 255 the .5 stop, each .n stop exact", () => {
    for (const side of ["bid", "ask"] as const) {
      const row = LUT_ROW[side];
      expect(entry(lut, row, 0)).toEqual(bytesOf(theme, "color.heatmap.zero"));
      expect(entry(lut, row, 255)).toEqual(bytesOf(theme, `color.heatmap.${side}.5`));
      for (let n = 1; n <= 4; n += 1) {
        expect(entry(lut, row, n * 51)).toEqual(
          bytesOf(theme, `color.heatmap.${side}.${n}` as ThemeSlot),
        );
      }
    }
  });

  it("delta row: −1 is sell, +1 is buy, −ε is ask.1, t = 0 is the canvas", () => {
    const row = LUT_ROW.delta;
    expect(entry(lut, row, 0)).toEqual(bytesOf(theme, "color.sell.default"));
    expect(entry(lut, row, 255)).toEqual(bytesOf(theme, "color.buy.default"));
    expect(entry(lut, row, 112)).toEqual(bytesOf(theme, "color.heatmap.ask.1"));
    expect(entry(lut, row, DELTA_ZERO_INDEX)).toEqual(bytesOf(theme, "color.heatmap.zero"));
  });

  it("only t = 0 is the canvas: its neighbours are tints, never clamped to it (§5.5)", () => {
    const canvas = bytesOf(theme, "color.heatmap.zero");
    const row = LUT_ROW.delta;
    expect(entry(lut, row, DELTA_ZERO_INDEX - 1)).not.toEqual(canvas);
    expect(entry(lut, row, DELTA_ZERO_INDEX + 1)).not.toEqual(canvas);
  });

  it("the delta row is continuous through 0: no step across the zero band exceeds its slope", () => {
    const lab = (i: number): Float64Array => {
      const [r, g, b] = entry(lut, LUT_ROW.delta, i) as [number, number, number];
      const v = new Float64Array(3);
      srgbToOklab(r / 255, g / 255, b / 255, v);
      return v;
    };
    const dist = (p: Float64Array, q: Float64Array): number =>
      Math.hypot(...[0, 1, 2].map((k) => (p[k] as number) - (q[k] as number)));
    const zero = lab(DELTA_ZERO_INDEX);
    // The band's per-entry slope: canvas → ask.1 over 16 entries, canvas → bid.1 over 15.875.
    const slope = Math.max(dist(zero, lab(112)) / 16, dist(zero, lab(144)) / 15);
    for (let i = 112; i < 144; i += 1) {
      expect(dist(lab(i), lab(i + 1))).toBeLessThan(slope * 1.1 + 4e-3); // + 8-bit rounding
    }
  });

  it("lightness is monotone within each intensity row and each delta half", () => {
    const L = (row: number, from: number, to: number): number[] =>
      Array.from({ length: to - from + 1 }, (_, k) => lightness(lut, row, from + k));
    const tol = 2e-3; // one 8-bit step of quantisation
    expect(reversal(L(LUT_ROW.bid, 0, 255))).toBeLessThan(tol);
    expect(reversal(L(LUT_ROW.ask, 0, 255))).toBeLessThan(tol);
    expect(reversal(L(LUT_ROW.delta, 0, DELTA_ZERO_INDEX))).toBeLessThan(tol);
    expect(reversal(L(LUT_ROW.delta, DELTA_ZERO_INDEX, 255))).toBeLessThan(tol);
  });

  it("the inverted convention swaps the bid and ask rows", () => {
    const inv = luts(ingestTheme(rampInput(name, { convention: "inverted" })));
    const row = (l: Uint8Array, r: number): Uint8Array =>
      l.subarray(r * LUT_ROW_BYTES, (r + 1) * LUT_ROW_BYTES);
    expect(row(inv, LUT_ROW.bid)).toEqual(row(lut, LUT_ROW.ask));
    expect(row(inv, LUT_ROW.ask)).toEqual(row(lut, LUT_ROW.bid));
  });

  it("inverted delta: the ±ε stops swap with the host-swapped ends, so each half keeps one hue", () => {
    const invTheme = ingestTheme(rampInput(name, { convention: "inverted" }));
    const inv = luts(invTheme);
    const row = LUT_ROW.delta;
    // The host delivered buy.default / sell.default swapped: −1 is the standard +1 colour.
    expect(entry(inv, row, 0)).toEqual(entry(lut, row, 255));
    expect(entry(inv, row, 255)).toEqual(entry(lut, row, 0));
    expect(entry(inv, row, 112)).toEqual(bytesOf(invTheme, "color.heatmap.bid.1"));
    expect(entry(inv, row, DELTA_ZERO_INDEX)).toEqual(bytesOf(invTheme, "color.heatmap.zero"));
    // Each half's hue (OkLab a sign) matches its end: no colour flip mid-ramp.
    const a = (i: number): number => {
      const [r, g, b] = entry(inv, row, i) as [number, number, number];
      const v = new Float64Array(3);
      srgbToOklab(r / 255, g / 255, b / 255, v);
      return v[1] as number;
    };
    for (let i = 0; i < 112; i += 1) expect(Math.sign(a(i))).toBe(Math.sign(a(0)));
    for (let i = 144; i < 256; i += 1) expect(Math.sign(a(i))).toBe(Math.sign(a(255)));
    expect(Math.sign(a(0))).not.toBe(Math.sign(a(255)));
    expect(writer.writeDelta(invTheme, new Uint8Array(LUT_ROW_BYTES))).toEqual(
      inv.subarray(row * LUT_ROW_BYTES),
    );
  });

  it("writeIntensity / writeDelta write the same bytes as the matching writeAll rows", () => {
    const one = new Uint8Array(LUT_ROW_BYTES);
    expect(writer.writeIntensity(theme, "ask", one)).toEqual(
      lut.subarray(LUT_ROW.ask * LUT_ROW_BYTES, (LUT_ROW.ask + 1) * LUT_ROW_BYTES),
    );
    expect(writer.writeDelta(theme, one)).toEqual(lut.subarray(LUT_ROW.delta * LUT_ROW_BYTES));
  });
});

describe("ColorLutWriter buffers", () => {
  const theme = ingestTheme(rampInput("dark"));

  it("writes into the caller's buffer at the offset and returns it (no allocation)", () => {
    const out = new Uint8Array(LUT_BYTES + 8).fill(7);
    expect(writer.writeAll(theme, out, 4)).toBe(out);
    expect([out[0], out[3], out[LUT_BYTES + 4], out[LUT_BYTES + 7]]).toEqual([7, 7, 7, 7]);
    expect(out.subarray(4, 4 + LUT_BYTES)).toEqual(luts(theme));
  });

  it("straight alpha: a translucent stop keeps its alpha (not premultiplied)", () => {
    const input = rampInput("dark");
    const colors = { ...input.colors, "color.heatmap.bid.5": "#6BD48A80" };
    const t = ingestTheme({ ...input, colors });
    const lut = luts(t);
    expect(entry(lut, LUT_ROW.bid, 255)).toEqual([0x6b, 0xd4, 0x8a, 0x80]);
    expect(entry(lut, LUT_ROW.bid, 0)[3]).toBe(255);
  });

  it.each([
    ["short buffer", LUT_BYTES - 1, 0],
    ["negative offset", LUT_BYTES, -1],
    ["fractional offset", LUT_BYTES + 4, 0.5],
  ])("throws RangeError on a %s and writes nothing", (_, size, offset) => {
    const out = new Uint8Array(size);
    expect(() => writer.writeAll(theme, out, offset)).toThrow(RangeError);
    expect(() => writer.writeDelta(theme, new Uint8Array(LUT_ROW_BYTES - 1))).toThrow(RangeError);
    expect(() => writer.writeIntensity(theme, "bid", new Uint8Array(4))).toThrow(RangeError);
    expect(out.every((b) => b === 0)).toBe(true);
  });

  it("the stop table is D05 §5.3's: six intensity stops, five delta stops, ε = 1/8", () => {
    expect(RAMP_STOPS.bid.map(([, t]) => t)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
    expect(RAMP_STOPS.delta.map(([s]) => s)).toEqual([
      "color.sell.default",
      "color.heatmap.ask.1",
      "color.heatmap.zero",
      "color.heatmap.bid.1",
      "color.buy.default",
    ]);
    expect(DELTA_STOPS_INVERTED.map(([s, t]) => `${s}@${t}`)).toEqual([
      "color.sell.default@-1",
      `color.heatmap.bid.1@${-DELTA_EPSILON}`,
      "color.heatmap.zero@0",
      `color.heatmap.ask.1@${DELTA_EPSILON}`,
      "color.buy.default@1",
    ]);
    expect(Object.keys(LUT_ROW)).toEqual(["bid", "ask", "delta"]); // no imbalance LUT (G8)
  });
});
