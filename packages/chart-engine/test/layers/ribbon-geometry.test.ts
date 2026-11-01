// E12-S07 PR B: the line-family geometry twin (E12-D06 §3.2, §5.5, R-2) and its palette (§14).
// Unit rows pin the D06 numbers per DPR; seeded properties (mulberry32, BQ-30) check the twin
// against a float32 stand-in of the `ribbon` vertex shader over random pans and zooms (the
// BQ-78 precedent until #391's SwiftShader rows), and the baseline split: the crossing lies on
// the segment and on B exactly, and the above and below fills tile the area between them.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  AREA_TINT,
  BASELINE_TINT,
  FLAG_GAP_BEFORE,
  PaletteError,
  RIBBON_GEOM,
  RIBBON_GEOM_FLOATS,
  RIBBON_PALETTE,
  RIBBON_PALETTE_FLOATS,
  RIBBON_PART,
  ribbonCorner,
  ribbonGeometry,
  ribbonPalette,
  ribbonQuad,
  ribbonRow,
  ribbonX,
} from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import {
  ChartViewport,
  createPaneUniforms,
  type PaneUniforms,
  writePaneUniforms,
} from "../../src/viewport/index.js";
import { RIBBON } from "../../src/gl/shaders/ribbon.js";
import { bars } from "../model/fixtures.js";

const fr = Math.fround;
const THEME = {
  "color.candle.up": "#26a69a",
  "color.candle.down": "#ef5350",
  "color.candle.wick": "#787b86",
  "color.surface.canvas": "#131722",
  "color.chart.line": "#8b5cf6",
};

function block(spacing: number, dpr: number, left = 0, lo = 0, hi = 100): PaneUniforms {
  const store = new BarStore();
  store.append(bars(0, 400, 0, 1));
  const vp = new ChartViewport(store);
  vp.setSize(400, 200, dpr);
  vp.setPanePlot(0, 0, 200);
  vp.setPriceInfo(0, 0, 1);
  vp.setPriceRange(0, lo, hi);
  const t0 = store.indexToTime(0);
  vp.setTimeRange(t0 + left * 60e6, t0 + (left + 400 / spacing) * 60e6);
  const b = createPaneUniforms();
  writePaneUniforms(vp, 0, b);
  b.floats[4] = 400 * dpr;
  b.floats[5] = 200 * dpr;
  return b;
}

const geomOf = (spacing: number, dpr: number): Float32Array => {
  const g = new Float32Array(RIBBON_GEOM_FLOATS);
  ribbonGeometry(spacing, dpr, g);
  return g;
};

describe("ribbon geometry (D06 §2, §3.2, §5.5)", () => {
  it.each([
    [1, 2, 1, 3.5, 1],
    [1.5, 2, 1, 5.25, 1],
    [2, 4, 2, 7, 2],
  ])("dpr %f: a 2 px stroke (2 × floor(dpr)), round joins, the 3.5 px disc", (dpr, s, j, d, h) => {
    const g = geomOf(12, dpr);
    expect([g[0], g[1], g[2], g[3], g[4]]).toEqual([s, j, d, h, dpr]);
    expect(g[RIBBON_GEOM.join]).toBe((g[RIBBON_GEOM.stroke] ?? 0) / 2);
  });

  it("L2 below 1.5 CSS px: x snaps to the device-pixel column's centre; L1 and L0 do not", () => {
    expect([1.49, 1.5, 3].map((s) => geomOf(s, 1)[RIBBON_GEOM.l2])).toEqual([1, 0, 0]);
    const b = block(0.6, 2);
    const raw = ribbonX(7, b.floats, b.ints[0] ?? 0, false);
    expect(ribbonX(7, b.floats, b.ints[0] ?? 0, true)).toBe(Math.floor(raw) + 0.5);
  });

  it("palette rows: line for the stroke, joins and disc; the tints; the base line", () => {
    const R = RIBBON_PALETTE;
    expect([0, 1, 2, 3, 4, 5, 6].map(ribbonRow)).toEqual([
      R.line,
      R.line,
      R.line,
      R.area,
      R.above,
      R.below,
      R.base,
    ]);
    // The shader's `row = part <= 2 ? 0 : part - 2`.
    expect(RIBBON.vertex).toContain("int row = part <= 2 ? 0 : part - 2;");
  });

  it("the stroke: a butt-capped rectangle `stroke` wide, perpendicular to the segment", () => {
    const b = block(12, 2);
    const g = geomOf(12, 2);
    const q = new Float64Array(8);
    expect(ribbonQuad(0, 10, 50, 40, 60, 0, 0, b.floats, b.ints[0] ?? 0, 0, g, q)).toBe(true);
    const p0 = [(q[0]! + q[4]!) / 2, (q[1]! + q[5]!) / 2];
    const p1 = [(q[2]! + q[6]!) / 2, (q[3]! + q[7]!) / 2];
    expect(p0[0]).toBeCloseTo(ribbonX(10, b.floats, b.ints[0] ?? 0, false), 4);
    expect(p1[0]).toBeCloseTo(ribbonX(11, b.floats, b.ints[0] ?? 0, false), 4);
    expect(Math.hypot(q[4]! - q[0]!, q[5]! - q[1]!)).toBeCloseTo(4, 9); // 2 × floor(2)
    const along = [p1[0]! - p0[0]!, p1[1]! - p0[1]!];
    expect(along[0]! * (q[4]! - q[0]!) + along[1]! * (q[5]! - q[1]!)).toBeCloseTo(0, 3);
  });

  it("R-2: no segment into a gap_before bar or past the last bar; joins and the disc stay", () => {
    const b = block(12, 1);
    const g = geomOf(12, 1);
    const q = new Float64Array(8);
    const args = [b.floats, b.ints[0] ?? 0, 0, g, q] as const;
    for (const part of [RIBBON_PART.stroke, RIBBON_PART.fill, RIBBON_PART.above]) {
      expect(ribbonQuad(part, 3, 10, 50, 50, FLAG_GAP_BEFORE, 10, ...args)).toBe(false);
      expect(ribbonQuad(part, 9, 10, 50, 50, 0, 10, ...args)).toBe(false); // the last bar
      expect(ribbonQuad(part, 3, 10, 50, 50, 0, 10, ...args)).toBe(true);
    }
    expect(ribbonQuad(RIBBON_PART.join, 3, 10, 50, 50, FLAG_GAP_BEFORE, 10, ...args)).toBe(true);
    expect(ribbonQuad(RIBBON_PART.join, 10, 10, 50, 50, 0, 10, ...args)).toBe(false);
    // The disc is the last bar's, at `base` (u_base = the last close), whatever the instance.
    expect(ribbonQuad(RIBBON_PART.last, 0, 10, 1, 1, 0, 70, ...args)).toBe(true);
    const cx = (q[0]! + q[6]!) / 2;
    expect(cx).toBeCloseTo(ribbonX(9, b.floats, b.ints[0] ?? 0, false), 9);
    expect(q[6]! - q[0]!).toBe(2 * (3.5 + 1)); // the disc's quad: radius + 1 px each side
  });

  it("the base line: one hairline at B across the viewport; the area fill to the bottom", () => {
    const b = block(12, 2);
    const g = geomOf(12, 2);
    const q = new Float64Array(8);
    ribbonQuad(RIBBON_PART.base, 0, 10, 0, 0, 0, 40, b.floats, b.ints[0] ?? 0, 0, g, q);
    expect([q[0], q[2], q[5]! - q[1]!]).toEqual([0, 800, 2]);
    expect(Number.isInteger(q[1])).toBe(true);
    ribbonQuad(RIBBON_PART.fill, 4, 10, 40, 60, 0, 0, b.floats, b.ints[0] ?? 0, 0, g, q);
    expect([q[5], q[7]]).toEqual([400, 400]); // u_viewport.y: the pane scissor clips it
  });
});

/** The `ribbon` vertex shader's corner in float32 (Math.fround each step), y as `yOf`. */
function shaderCorner(
  part: number,
  vid: number,
  i: number,
  c0: number,
  c1: number,
  base: number,
  b: PaneUniforms,
  g: Float32Array,
): [number, number] {
  const f = b.floats;
  const [kx, ky, kz, kw, vw, vh, lx, on] = [0, 1, 2, 3, 4, 5, 6, 7].map((j) => fr(f[j] ?? 0));
  const ib = b.ints[0] ?? 0;
  const tb = b.ints[1] ?? 0;
  const yOf = (tick: number): number => {
    const t = fr(tick - tb);
    const r = fr(Math.max(fr(t * lx!), fr(-0.999999)));
    const third = fr(0.33333333);
    const series = fr(r * fr(1 - fr(r * fr(0.5 - fr(r * fr(third - fr(r * 0.25)))))));
    const l = Math.abs(r) <= 0.05 ? series : fr(Math.log(fr(1 + r)));
    return fr(fr(fr(fr(t * fr(1 - on!)) + fr(l * on!)) * ky!) + kz!);
  };
  const l2 = (g[RIBBON_GEOM.l2] ?? 0) > 0.5;
  const xOf = (j: number): number => {
    const x = fr(fr(fr(j - ib) + 0.5 - kw!) * kx!);
    return l2 ? fr(Math.floor(x) + 0.5) : x;
  };
  const cx = vid & 1;
  const cy = vid >> 1;
  const x0 = xOf(i);
  if (part === 1 || part === 2) {
    const r = fr(g[part === 1 ? 1 : 2] ?? 0);
    const m = fr(r + 1);
    return [fr(x0 + fr((cx * 2 - 1) * m)), fr(yOf(part === 2 ? base : c0) + fr((cy * 2 - 1) * m))];
  }
  if (part === 6) {
    const h = fr(g[3] ?? 1);
    return [fr(cx * vw!), fr(Math.floor(fr(fr(yOf(base) - fr(h * 0.5)) + 0.5)) + fr(cy * h))];
  }
  const y0 = yOf(c0);
  const x1 = xOf(i + 1);
  const y1 = yOf(c1);
  if (part === 0) {
    const vx = fr(fr(x1 - x0) + fr(1e-6));
    const vy = fr(y1 - y0);
    const len = fr(Math.hypot(vx, vy));
    const w = fr(fr(fr(g[0] ?? 0) * 0.5) * (cy * 2 - 1));
    return [
      fr(fr(x0 + fr(fr(x1 - x0) * cx)) - fr(fr(vy / len) * w)),
      fr(fr(y0 + fr(fr(y1 - y0) * cx)) + fr(fr(vx / len) * w)),
    ];
  }
  const yb = part === 3 ? vh! : yOf(base);
  const s = part === 5 ? -1 : 1;
  const in0 = part === 3 || fr(yb - y0) * s >= 0;
  const in1 = part === 3 || fr(yb - y1) * s >= 0;
  const dy = fr(y1 - y0);
  const xc = dy !== 0 ? fr(x0 + fr(fr(fr(x1 - x0) * fr(yb - y0)) / dy)) : x0;
  const ex = cx === 0 ? (in0 ? x0 : xc) : in1 ? x1 : xc;
  const ey = cx === 0 ? (in0 ? y0 : yb) : in1 ? y1 : yb;
  return [ex, cy === 0 ? ey : yb];
}

describe("property: the twin is the shader's arithmetic (float32 stand-in, pans and zooms)", () => {
  it("every corner of every part agrees within 0.02 px over 400 seeded viewports", () => {
    const rng = mulberry32(20261103);
    const out = new Float64Array(2);
    let worst = 0;
    let checked = 0;
    for (let c = 0; c < 400; c += 1) {
      const spacing = 0.3 + rng() * 40;
      const dpr = [1, 1.5, 2][Math.floor(rng() * 3)] ?? 1;
      const b = block(
        spacing,
        dpr,
        Math.floor(rng() * 300) - 50,
        -20 + rng() * 40,
        80 + rng() * 60,
      );
      const g = geomOf(spacing, dpr);
      const i = Math.floor(rng() * 380);
      const [c0, c1, base] = [0, 0, 0].map(() => Math.floor(rng() * 140) - 10) as number[];
      for (let part = 0; part <= 6; part += 1) {
        for (let vid = 0; vid < 4; vid += 1) {
          const ok = ribbonCorner(
            part,
            vid,
            i,
            390,
            c0!,
            c1!,
            0,
            base!,
            b.floats,
            b.ints[0] ?? 0,
            b.ints[1] ?? 0,
            g,
            out,
          );
          if (!ok) continue;
          const [sx, sy] = shaderCorner(
            part,
            vid,
            part === 2 || part === 6 ? 389 : i,
            c0!,
            c1!,
            base!,
            b,
            g,
          );
          worst = Math.max(worst, Math.abs(sx - out[0]!), Math.abs(sy - out[1]!));
          checked += 1;
        }
      }
    }
    expect(checked).toBeGreaterThan(8_000);
    expect(worst).toBeLessThan(0.02);
  });
});

/** The polygon v0 v1 v3 v2's signed area (the strip's two triangles). */
const area = (q: Float64Array): number => {
  const xs = [q[0]!, q[2]!, q[6]!, q[4]!];
  const ys = [q[1]!, q[3]!, q[7]!, q[5]!];
  let a = 0;
  for (let j = 0; j < 4; j += 1) a += xs[j]! * ys[(j + 1) % 4]! - xs[(j + 1) % 4]! * ys[j]!;
  return a / 2;
};

describe("property: the baseline split (D06 §3.2: split exactly at crossings)", () => {
  it("2 000 seeded segments: the crossing is on the segment and on B; the fills tile the band", () => {
    const rng = mulberry32(20261104);
    const above = new Float64Array(8);
    const below = new Float64Array(8);
    let crossings = 0;
    for (let c = 0; c < 2_000; c += 1) {
      const dpr = [1, 1.5, 2][c % 3] ?? 1;
      const b = block(2 + rng() * 30, dpr);
      const g = geomOf(8, dpr);
      const [ib, tb] = [b.ints[0] ?? 0, b.ints[1] ?? 0];
      const i = Math.floor(rng() * 20);
      const [c0, c1, base] = [0, 0, 0].map(() => Math.floor(rng() * 100)) as number[];
      const hasA = ribbonQuad(
        RIBBON_PART.above,
        i,
        30,
        c0!,
        c1!,
        0,
        base!,
        b.floats,
        ib,
        tb,
        g,
        above,
      );
      const hasB = ribbonQuad(
        RIBBON_PART.below,
        i,
        30,
        c0!,
        c1!,
        0,
        base!,
        b.floats,
        ib,
        tb,
        g,
        below,
      );
      const x0 = ribbonX(i, b.floats, ib, false);
      const x1 = ribbonX(i + 1, b.floats, ib, false);
      const y = (t: number): number => (b.floats[1] ?? 0) * (t - tb) + (b.floats[2] ?? 0);
      const [y0, y1, yb] = [y(c0!), y(c1!), y(base!)];
      // The band between the segment and B, integrated exactly.
      const xc = y1 !== y0 ? x0 + ((x1 - x0) * (yb - y0)) / (y1 - y0) : x0;
      const crosses = (y0 - yb) * (y1 - yb) < 0;
      const want = crosses
        ? (Math.abs(y0 - yb) * (xc - x0) + Math.abs(y1 - yb) * (x1 - xc)) / 2
        : ((Math.abs(y0 - yb) + Math.abs(y1 - yb)) * (x1 - x0)) / 2;
      const got = (hasA ? Math.abs(area(above)) : 0) + (hasB ? Math.abs(area(below)) : 0);
      expect(got).toBeCloseTo(want, 6);
      if (!crosses) continue;
      crossings += 1;
      expect(hasA && hasB).toBe(true);
      // Above (y ≤ B): the clamped end sits at the crossing; below shares it.
      const endA = y0 <= yb ? [above[2]!, above[3]!] : [above[0]!, above[1]!];
      const endB = y0 >= yb ? [below[2]!, below[3]!] : [below[0]!, below[1]!];
      expect(endA).toEqual(endB);
      expect(endA[1]).toBe(yb);
      // On the segment: the line's y at the crossing's x is B.
      expect(y0 + ((y1 - y0) * (endA[0]! - x0)) / (x1 - x0)).toBeCloseTo(yb, 9);
    }
    expect(crossings).toBeGreaterThan(300);
  });

  it("moving B past both ends moves the whole band to one side (no sliver on the other)", () => {
    const b = block(12, 1);
    const g = geomOf(12, 1);
    const q = new Float64Array(8);
    const args = [b.floats, b.ints[0] ?? 0, b.ints[1] ?? 0, g, q] as const;
    expect(ribbonQuad(RIBBON_PART.above, 2, 9, 40, 60, 0, 10, ...args)).toBe(true);
    expect(ribbonQuad(RIBBON_PART.below, 2, 9, 40, 60, 0, 10, ...args)).toBe(false);
    expect(ribbonQuad(RIBBON_PART.above, 2, 9, 40, 60, 0, 90, ...args)).toBe(false);
    expect(ribbonQuad(RIBBON_PART.below, 2, 9, 40, 60, 0, 90, ...args)).toBe(true);
  });
});

describe("ribbon palette (D06 §14, BQ-7)", () => {
  const rgb = (hex: string): number[] =>
    [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const mix = (c: string, f: number): number[] => {
    const base = rgb(THEME["color.surface.canvas"]);
    return rgb(c).map((v, i) => base[i]! + (v - base[i]!) * f);
  };

  it("line, the area tint (16 %), up / down at 22 % above / below, the neutral base", () => {
    const out = new Float32Array(RIBBON_PALETTE_FLOATS);
    ribbonPalette(THEME, false, out);
    const row = (r: number): number[] => Array.from(out.subarray(r * 4, r * 4 + 3));
    const near = (a: number[], b: number[]): void =>
      a.forEach((v, i) => expect(v).toBeCloseTo(b[i]!, 6));
    expect([AREA_TINT, BASELINE_TINT]).toEqual([0.16, 0.22]);
    near(row(RIBBON_PALETTE.line), rgb("#8b5cf6"));
    const area = new Float32Array(RIBBON_PALETTE_FLOATS);
    ribbonPalette(THEME, false, area, "area"); // the area row is the area kind's
    near(Array.from(area.subarray(4, 7)), mix("#8b5cf6", 0.16));
    expect(row(RIBBON_PALETTE.area)).toEqual([0, 0, 0]); // a baseline draws no area fill
    near(row(RIBBON_PALETTE.above), mix("#26a69a", 0.22));
    near(row(RIBBON_PALETTE.below), mix("#ef5350", 0.22));
    near(row(RIBBON_PALETTE.base), rgb("#787b86"));
    for (const r of [0, 2, 3, 4]) expect(out[r * 4 + 3]).toBe(1); // opaque, no per-bar alpha
    expect(area[7]).toBe(1);
    // The inverted convention swaps up and down only; the base line is never remapped (R-6).
    const inv = new Float32Array(RIBBON_PALETTE_FLOATS);
    ribbonPalette(THEME, true, inv);
    expect(Array.from(inv.subarray(8, 12))).toEqual(Array.from(out.subarray(12, 16)));
    expect(Array.from(inv.subarray(12, 16))).toEqual(Array.from(out.subarray(8, 12)));
    expect(Array.from(inv.subarray(16, 20))).toEqual(Array.from(out.subarray(16, 20)));
  });

  // E12-D06 §3.2's Ink column per kind: a line is `color.chart.line` alone; an area adds its
  // 16 % fill over `color.surface.canvas`; a baseline adds the 22 % up / down fills and the
  // `color.candle.wick` base line. A kind never requires a token it does not draw.
  it.each([
    ["line", ["color.chart.line"]],
    ["area", ["color.chart.line", "color.surface.canvas"]],
    [
      "baseline",
      [
        "color.chart.line",
        "color.surface.canvas",
        "color.candle.wick",
        "color.candle.up",
        "color.candle.down",
      ],
    ],
  ] as const)("%s needs exactly %j", (kind, needs) => {
    const only = Object.fromEntries(needs.map((t) => [t, THEME[t]]));
    const out = new Float32Array(RIBBON_PALETTE_FLOATS);
    expect(() => ribbonPalette(only, false, out, kind)).not.toThrow();
    for (const t of needs) {
      const less: Record<string, string> = { ...only };
      delete less[t];
      expect(() => ribbonPalette(less, false, out, kind)).toThrow(PaletteError);
    }
    const full = new Float32Array(RIBBON_PALETTE_FLOATS);
    ribbonPalette(THEME, false, full, kind);
    expect(Array.from(out)).toEqual(Array.from(full)); // nothing unneeded leaks in
  });

  it.each(["color.chart.line", "color.candle.wick", "color.surface.canvas"])(
    "a theme without %s is refused, never a fallback colour; the palette is kept",
    (token) => {
      const out = new Float32Array(RIBBON_PALETTE_FLOATS).fill(0.5);
      const theme: Record<string, string> = { ...THEME };
      delete theme[token];
      expect(() => ribbonPalette(theme, false, out)).toThrow(PaletteError);
      try {
        ribbonPalette(theme, false, out);
      } catch (e) {
        expect((e as PaletteError).token).toBe(token);
      }
      expect(out.every((v) => v === 0.5)).toBe(true);
    },
  );
});
