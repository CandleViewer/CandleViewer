// E12-S09 the L1 mark (BQ-04, E12-D06 §5.3 / §4.1 / §4.3 / §5.5): from L1 every wick is one
// hairline (weight is no channel), the body 1–2 CSS px; an up body is outline-only from 2 device
// px, else `dash.1-1`; down stays solid. Hollow and OHLC draw the candle mark at L1 and L2. The
// tier rides `u_geom[1].w`. The twin ↔ shader rows pin the shader's lines for each rule (no GLSL
// runs in CI: the SwiftShader goldens are #391's).
import { describe, expect, it } from "vitest";
import { CANDLE } from "../../src/gl/shaders/candle.js";
import {
  CANDLE_DIR,
  CANDLE_PART,
  CandleRing,
  CandleSeries,
  candleGeometry,
  candleRect,
  dashOn,
  FILL,
  fillMode,
  GEOM,
  L1_OUTLINE_MIN,
  MARK,
  type SeriesShape,
} from "../../src/layers/index.js";

const K = Float64Array.of(10, -2, 500, 0, 0, 600, 0, 0);
const geom = (s: number, dpr: number, tier: number): Float32Array => {
  const g = new Float32Array(8);
  candleGeometry(s, dpr, g, tier);
  return g;
};

describe("the L1 mark in the geometry twin", () => {
  it.each([1, 1.5, 2])("dpr %f: up and down wicks are both one hairline at L1", (dpr) => {
    const hair = Math.max(1, Math.floor(dpr));
    const out = new Float64Array(4);
    const weights = (tier: number): number[] =>
      [CANDLE_DIR.up, CANDLE_DIR.down].map((d) => {
        candleRect(CANDLE_PART.wick, 3, 10, 16, 8, 14, d, K, 0, 0, geom(2, dpr, tier), out);
        return out[2] ?? 0;
      });
    expect(weights(1)).toEqual([hair, hair]);
    expect(weights(0)).toEqual([hair, 2 * hair]); // L0 keeps the 1 / 2 weight channel
  });

  it("body 1–2 CSS px across [1.5, 3); up outline-only from 2 device px, else dash.1-1", () => {
    const rows = [1.5, 2, 2.9].flatMap((s) =>
      [1, 1.5, 2].map((dpr) => {
        const g = geom(s, dpr, 1);
        const w = g[GEOM.body] ?? 0;
        return [s, dpr, w, fillMode(CANDLE_PART.body, CANDLE_DIR.up, w, g)];
      }),
    );
    for (const [s, dpr, w, mode] of rows as [number, number, number, number][]) {
      expect(w / dpr, `s ${s} dpr ${dpr}`).toBeGreaterThanOrEqual(1);
      expect(w / dpr, `s ${s} dpr ${dpr}`).toBeLessThanOrEqual(2);
      expect(mode).toBe(w >= L1_OUTLINE_MIN ? (mode & 3) + FILL.hollow : FILL.dash);
    }
    expect(rows.map((r) => r[3])).toContain(FILL.dash); // s 1.5 at dpr 1: a 1 px body
    const g = geom(2, 1, 1);
    expect(fillMode(CANDLE_PART.body, CANDLE_DIR.down, 2, g)).toBe(FILL.solid);
    expect(fillMode(CANDLE_PART.body, CANDLE_DIR.doji, 2, g)).toBe(FILL.solid);
    expect(fillMode(CANDLE_PART.body, CANDLE_DIR.up, 2, geom(2, 1, 0))).toBe(1); // L0: the tint
    const hollowUp = CANDLE_DIR.up | MARK.hollow;
    expect(fillMode(CANDLE_PART.hollowBody, hollowUp, 9, geom(12, 1, 0))).toBe(2 + FILL.hollow);
  });

  it("dash.1-1 alternates by window row, the shader's even floor(gl_FragCoord.y)", () => {
    const H = 7;
    expect(Array.from({ length: H }, (_, r) => dashOn(r, H))).toEqual([
      true,
      false,
      true,
      false,
      true,
      false,
      true,
    ]);
    expect(dashOn(0, 8)).toBe(false);
  });

  it("the tier clamps to 0..2; NaN and negatives are L0", () => {
    const tiers = [-1, Number.NaN, 0, 0.5, 1, 1.9, 2, 7].map((t) => geom(2, 1, t)[GEOM.tier]);
    expect(tiers).toEqual([0, 0, 0, 0, 1, 1, 2, 2]);
  });
});

describe("hollow and OHLC take the candle mark from L1 (D06 §5.5)", () => {
  it.each<[SeriesShape, number[]]>([
    ["hollow", [CANDLE_PART.hollowWick, CANDLE_PART.hollowBody]],
    ["bars", [CANDLE_PART.stem, CANDLE_PART.ticks]],
  ])("%s: its L0 parts at 3.2 px, the candle's wick and body at L1 there", (shape, l0) => {
    const c = new CandleSeries(new CandleRing(), shape);
    c.frame(shape === "bars" ? 6 : 3.2, 1);
    expect(c.blocks.slice(0, 2).map((b) => b.ints[0])).toEqual(l0);
    c.frame(3.2, 1, 0, -1, 0, 0, 1); // L1 held by the band up to 3.45 px (D06 §5.1)
    expect(c.blocks.slice(0, 2).map((b) => b.ints[0])).toEqual([
      CANDLE_PART.wick,
      CANDLE_PART.body,
    ]);
  });
});

describe("twin ↔ shader: the shader carries each rule the twin computes", () => {
  const v = CANDLE.vertex;
  const f = CANDLE.fragment;
  it.each([
    ["the tier is u_geom[1].w; from L1 every wick a hairline", v, "u_geom[1].w >= 1.0\n      ? h"],
    ["an L1 up body: outline-only from 2 px, else the dash", v, "w >= 2.0 ? outline + 4 : 3"],
    ["the dash by window row", f, "mod(floor(gl_FragCoord.y), 2.0) >= 1.0) discard"],
  ])("%s", (_, src, line) => {
    expect(src).toContain(line);
  });
});
