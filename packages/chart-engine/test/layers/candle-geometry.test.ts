// E12-S06 geometry twin and palette (E12-D06 §2-§4, BQ-4). Seeded properties (BQ-30, no
// fast-check): the body is odd from 4 device px, centred on the wick and inside its slot for
// every spacing and DPR; doji and zero-range bars get their fixed marks.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  CANDLE_DIR,
  CANDLE_PART,
  candleGeometry,
  fullOutline,
  candlePalette,
  candleRect,
  GEOM,
  PALETTE,
  PaletteError,
  parseColor,
} from "../../src/layers/index.js";

const geom = (s: number, dpr: number): Float32Array => {
  const g = new Float32Array(8);
  candleGeometry(s, dpr, g);
  return g;
};
/** A pane block: 10 device px per bar, 2 px per tick, y = 500 - 2 t (linear). */
const K = Float64Array.of(10, -2, 500, 0, 0, 0, 0, 0);
const rect = (part: number, ohlc: number[], dir: number, g: Float32Array): number[] => {
  const out = new Float64Array(4);
  const [o, h, l, c] = ohlc as [number, number, number, number];
  candleRect(part, 3, o, h, l, c, dir, K, 0, 0, g, out);
  return [...out];
};

describe("candleGeometry", () => {
  // E12-D06 §3.1 / E12-D12 §5.2: "forced odd from 4 px (an even width takes the next odd value
  // when it is ≤ s − 1, else the previous one) … Ladder at the sample steps: 9 / 5 / 2 px; the
  // cap is reached from s = 48" (the sample steps s = 12, 6, 3).
  it.each([
    [12, 1, 9, 1], // sample step 1: 8 → 9
    [6, 1, 5, 1], // sample step 2: 4 → 5 (5 ≤ s − 1)
    [3, 1, 2, 1], // sample step 3: under 4 px, even stays
    [48, 1, 35, 1], // the cap reached: 34 → 35
    [47, 1, 33, 1], // not yet: 33 is odd already
    [1.5, 1, 1, 1],
    [5, 1, 3, 1], // 4 → 5 > s − 1, so the previous odd value
    [8, 1, 7, 1],
    [200, 1, 35, 1],
    [12, 2, 18, 2], // 9 CSS px × 2: even over an even hairline
    [12, 1.5, 13, 1], // 13.5 → 14, matched to the odd hairline
    [12, 3, 27, 3],
  ])("spacing %f at dpr %f: body %i, hairline %i", (s, dpr, body, hair) => {
    const g = geom(s, dpr);
    expect([g[GEOM.body], g[GEOM.hair], g[GEOM.spacing]]).toEqual([body, hair, s]);
  });

  it("property: the hairline's parity from 4 px, ≥ a hairline, inside the slot (5 000 cases)", () => {
    const rng = mulberry32(20261101);
    for (let c = 0; c < 5_000; c += 1) {
      const s = 0.05 + rng() * 250;
      const dpr = [1, 1.25, 1.5, 2, 3][Math.floor(rng() * 5)] as number;
      const g = geom(s, dpr);
      const body = g[GEOM.body] as number;
      const at = `case ${c}: s=${s} dpr=${dpr}`;
      expect(body >= 4 ? (body - (g[GEOM.hair] as number)) % 2 : 0, at).toBe(0);
      expect(body, at).toBeGreaterThanOrEqual(g[GEOM.hair] as number);
      if (s * dpr >= 3) expect(body, at).toBeLessThanOrEqual(Math.ceil(s * dpr));
      const wick = rect(0, [2, 9, 1, 5], CANDLE_DIR.up, g);
      const bod = rect(1, [2, 9, 1, 5], CANDLE_DIR.up, g);
      if (body < 4) continue; // under 4 px a body may be even over an odd wick (D06 §2)
      expect((wick[0] as number) + (wick[2] as number) / 2, at).toBe(
        (bod[0] as number) + (bod[2] as number) / 2,
      );
    }
  });
});

describe("candleRect", () => {
  const g = geom(12, 1); // body 9, hairline 1
  it("places the wick over [low, high] and the body over [open, close] at the bar's centre", () => {
    expect(rect(0, [2, 9, 1, 5], CANDLE_DIR.up, g)).toEqual([35, 482, 1, 16]);
    expect(rect(1, [2, 9, 1, 5], CANDLE_DIR.up, g)).toEqual([31, 490, 9, 6]);
  });

  it("D06 §3.1: a body of 9 px puts the up wick on column 4, the down wick on columns 4 and 5", () => {
    const body = rect(1, [5, 9, 1, 2], CANDLE_DIR.down, g);
    const up = rect(0, [2, 9, 1, 5], CANDLE_DIR.up, g);
    const down = rect(0, [5, 9, 1, 2], CANDLE_DIR.down, g);
    const columns = (r: number[]): number[] =>
      Array.from({ length: r[2] ?? 0 }, (_, c) => (r[0] ?? 0) + c - (body[0] ?? 0));
    expect([body[2], columns(up), columns(down)]).toEqual([9, [4], [4, 5]]);
  });

  it("D06 §3.2: the full up outline starts at 3 CSS px wide, whatever the DPR", () => {
    const narrow = geom(3, 1.5); // 2 CSS px → 3 device px: top and bottom only
    const wide = geom(6, 1.5); // 5 CSS px → 7 device px
    expect([narrow[GEOM.body], fullOutline(narrow[GEOM.body] ?? 0, narrow)]).toEqual([3, false]);
    expect([wide[GEOM.body], fullOutline(wide[GEOM.body] ?? 0, wide)]).toEqual([7, true]);
    expect(fullOutline(3, geom(3, 1))).toBe(true); // 3 CSS px at dpr 1
  });

  it("draws a doji 2 hairlines tall (1 below 8 px) and a zero-range bar 3 px wide at dpr 1", () => {
    expect(rect(1, [4, 9, 1, 4], CANDLE_DIR.doji, g)).toEqual([31, 491, 9, 2]);
    expect(rect(1, [4, 9, 1, 4], CANDLE_DIR.doji, geom(6, 1))[3]).toBe(1);
    expect(rect(1, [4, 4, 4, 4], CANDLE_DIR.zeroRange, geom(2, 1))[2]).toBe(3);
  });

  it("D06 §9: a zero-range bar is 2 hairlines tall always, max(body, roundHalfUp(3 dpr)) wide", () => {
    // dpr 1.5, s = 2: body 2 device px, hairline 1. Width roundHalfUp(4.5) = 5 (not 3 hairlines),
    // height 2 even below 8 px (the doji's 1-hairline rule is not the zero-range bar's).
    const z = rect(1, [4, 4, 4, 4], CANDLE_DIR.zeroRange, geom(2, 1.5));
    expect([z[2], z[3]]).toEqual([5, 2]);
    expect(rect(1, [4, 4, 4, 4], CANDLE_DIR.zeroRange, geom(6, 1))[3]).toBe(2);
    expect(rect(1, [4, 4, 4, 4], CANDLE_DIR.zeroRange, geom(48, 1))[2]).toBe(35); // body wins
  });

  // E12-D06 §9 (:295-296): only the doji drops to 1 px below s = 8; the zero-range mark is
  // "2 px tall (`2 × floor(dpr)` device px)" at every spacing, for candles and OHLC alike.
  it("D06 §9: a zero-range mark stays 2 hairlines tall below s = 8, candle body and OHLC stem", () => {
    expect(rect(CANDLE_PART.body, [4, 4, 4, 4], CANDLE_DIR.zeroRange, geom(6, 1))[3]).toBe(2);
    expect(rect(CANDLE_PART.stem, [4, 4, 4, 4], CANDLE_DIR.zeroRange, geom(6, 1))[3]).toBe(2);
    expect(rect(CANDLE_PART.stem, [4, 4, 4, 4], CANDLE_DIR.zeroRange, geom(6, 2))[3]).toBe(4);
    expect(rect(CANDLE_PART.body, [4, 9, 1, 4], CANDLE_DIR.doji, geom(6, 1))[3]).toBe(1);
  });
});

describe("candlePalette (BQ-4)", () => {
  const theme = {
    "color.candle.up": "#00ff00",
    "color.candle.down": "rgb(255, 0, 0)",
    "color.candle.wick": "#808080ff",
    "color.surface.canvas": "#000",
  };
  const row = (p: Float32Array, r: number): number[] =>
    [...p.subarray(r * 4, r * 4 + 4)].map((v) => Math.round(v * 1000) / 1000);

  it("resolves up, down and wick, and tints 42 % over the canvas", () => {
    const p = new Float32Array(24);
    candlePalette(theme, false, p);
    expect(row(p, PALETTE.up)).toEqual([0, 1, 0, 1]);
    expect(row(p, PALETTE.down)).toEqual([1, 0, 0, 1]);
    expect(row(p, PALETTE.upTint)).toEqual([0, 0.42, 0, 1]);
    expect(row(p, PALETTE.neutral)[0]).toBeCloseTo(0.42 * (128 / 255), 3);
  });

  it("the inverted convention swaps up and down, never the wick", () => {
    const [a, b] = [new Float32Array(24), new Float32Array(24)];
    candlePalette(theme, false, a);
    candlePalette(theme, true, b);
    expect(row(b, PALETTE.up)).toEqual(row(a, PALETTE.down));
    expect(row(b, PALETTE.down)).toEqual(row(a, PALETTE.up));
    expect(row(b, PALETTE.wick)).toEqual(row(a, PALETTE.wick));
  });

  it("a missing or unreadable token is a refusal that leaves the palette as it was", () => {
    const p = new Float32Array(24).fill(0.5);
    for (const bad of [
      { ...theme, "color.candle.up": undefined },
      { ...theme, "color.candle.wick": "red" },
    ]) {
      expect(() => candlePalette(bad as Record<string, string>, false, p)).toThrow(PaletteError);
    }
    expect([...p].every((v) => v === 0.5)).toBe(true);
  });

  it("parses #rgb, #rgba, #rrggbb, #rrggbbaa, rgb() and rgba(); refuses the rest", () => {
    const o = new Float32Array(4);
    for (const css of [
      "#fff",
      "#ffff",
      "#ffffff",
      "#ffffffff",
      "rgb(255,255,255)",
      "rgba(255, 255, 255, 1)",
    ]) {
      expect(parseColor(css, o, 0), css).toBe(true);
      expect([...o], css).toEqual([1, 1, 1, 1]);
    }
    for (const css of [undefined, "", "white", "#12", "rgb(300, 0, 0)", "hsl(0, 0%, 0%)"]) {
      expect(parseColor(css, o, 0), String(css)).toBe(false);
    }
  });
});
