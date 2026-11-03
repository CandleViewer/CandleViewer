// E12-S10 marks geometry (E12-D06 §7.1 / §7.3, at DPR 1 / 1.5 / 2): the forming ring is one
// hairline wide, one hairline outside the union of the bar's wick and body, dashed 2 / 2 hairlines
// along its perimeter; the corrected square is 3 × 3 hairlines, 2 above the high, centred on the
// hairline column. The shader spells the twin's numbers; every `in` it declares is bound by
// `CANDLE_ATTRIBUTES` at the instance layout's offset. Seeded properties (BQ-30).
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { CANDLE } from "../../src/gl/shaders/candle.js";
import {
  CANDLE_ATTRIBUTES,
  CANDLE_DIR,
  CANDLE_PART,
  candleDir,
  candleGeometry,
  candleRect,
  GEOM,
  MARK_GEOM,
  MARK_HEAVY,
  MARKS_FROM,
  markRect,
  PART_VERTICES,
  partColor,
  PALETTE,
  ringOn,
} from "../../src/layers/index.js";
import { BAR_FLAG } from "../../src/model/index.js";
import { INSTANCE_LAYOUTS, PROGRAM } from "../../src/scene/instance-layout.js";

const { forming: FORMING, amended: AMENDED } = BAR_FLAG;
const geom = (s: number, dpr: number): Float32Array => {
  const g = new Float32Array(8);
  candleGeometry(s, dpr, g);
  return g;
};
/** A pane block: 10 device px per bar, 2 px per tick, y = 500 - 2 t (linear). */
const K = Float64Array.of(10, -2, 500, 0, 0, 0, 0, 0);
const part = (p: number, [o, h, l, c]: number[], g: Float32Array, k = K): number[] => {
  const out = new Float64Array(4);
  const dir = candleDir(o as number, h as number, l as number, c as number);
  candleRect(p, 3, o as number, h as number, l as number, c as number, dir, k, 0, 0, g, out);
  return [...out];
};
const mark = (kind: number, [o, h, l, c]: number[], g: Float32Array, k = K): number[] => {
  const out = new Float64Array(4);
  const dir = candleDir(o as number, h as number, l as number, c as number);
  const meta = (dir << 4) | (dir === CANDLE_DIR.down ? MARK_HEAVY : 0); // a candle entry's word
  markRect(kind, 3, h as number, l as number, o as number, meta, k, 0, 0, g, out);
  return [...out];
};
/** The inked pixels of a w × h ring, row by row: `#` on, `.` off (the interior is all off). */
const ring = (w: number, h: number, hair: number): string[] =>
  Array.from({ length: h }, (_, y) =>
    Array.from({ length: w }, (_, x) => (ringOn(x, y, w, h, hair) ? "#" : ".")).join(""),
  );

const BARS: Record<string, number[]> = {
  up: [20, 30, 10, 25],
  down: [25, 30, 10, 20],
  doji: [20, 30, 10, 20],
  "zero-range": [20, 20, 20, 20],
  "doji at its high": [30, 30, 10, 30],
};

describe("the forming ring (D06 §7.1)", () => {
  it.each([1, 1.5, 2])("dpr %f: 1 hairline wide, 1 outside the wick and body union", (dpr) => {
    const g = geom(12, dpr);
    const hair = g[GEOM.hair] as number;
    for (const [name, bar] of Object.entries(BARS)) {
      const [rx, ry, rw, rh] = mark(FORMING, bar, g) as [number, number, number, number];
      const wick = part(CANDLE_PART.wick, bar, g);
      const body = part(CANDLE_PART.body, bar, g);
      const dir = candleDir(...(bar as [number, number, number, number]));
      const x0 = Math.min(wick[0] as number, body[0] as number);
      const x1 = Math.max(
        (wick[0] as number) + (wick[2] as number),
        (body[0] as number) + (body[2] as number),
      );
      // An up / down body lies inside the wick's span; a doji or zero-range body may not.
      const ys = dir >= CANDLE_DIR.doji ? [wick, body] : [wick];
      const top = Math.floor(Math.min(...ys.map((r) => r[1] as number)));
      const bottom = Math.ceil(Math.max(...ys.map((r) => (r[1] as number) + (r[3] as number))));
      const pad = (MARK_GEOM.ringOffset + MARK_GEOM.ringWeight) * hair;
      expect([rx, ry, rw, rh], name).toEqual([
        x0 - pad,
        top - pad,
        x1 - x0 + 2 * pad,
        bottom - top + 2 * pad,
      ]);
      // Whole device pixels, so the dashes sit on the grid and never shimmer on a pan.
      expect([rx, ry, rw, rh].every(Number.isInteger), name).toBe(true);
    }
  });

  it("dpr 1: dashes 2 on / 2 off clockwise from the top-left corner, the inside empty", () => {
    expect(ring(9, 6, 1)).toEqual([
      "##..##..#",
      "#........",
      ".........",
      "........#",
      "#.......#",
      "..##..##.",
    ]);
  });

  it("dpr 2: the band and the dashes double (2 device px wide, 4 on / 4 off)", () => {
    expect(ring(12, 8, 2)).toEqual([
      "####....####",
      "####....####",
      "............",
      "............",
      "##........##",
      "##........##",
      "....####..##",
      "....####..##",
    ]);
  });

  it("dpr 1.5: floor(dpr) = 1, so the dpr-1 pattern (D06 §2)", () => {
    const g = geom(12, 1.5);
    expect(g[GEOM.hair]).toBe(1);
    expect(ring(9, 6, g[GEOM.hair] as number)).toEqual(ring(9, 6, 1));
  });
});

describe("the corrected square (D06 §7.3)", () => {
  it.each([1, 1.5, 2])(
    "dpr %f: 3 × 3 hairlines, 2 above the high, on the hairline column",
    (dpr) => {
      const g = geom(12, dpr);
      const hair = g[GEOM.hair] as number;
      for (const [name, bar] of Object.entries(BARS)) {
        const [x, y, w, h] = mark(AMENDED, bar, g) as [number, number, number, number];
        const body = geom(12, dpr)[GEOM.body] as number;
        const wick = part(CANDLE_PART.wick, bar, g);
        const left = Math.floor((3 + 0.5) * 10 - body * 0.5 + 0.5);
        const stem = left + Math.floor((body - hair) * 0.5);
        expect([w, h], name).toEqual([3 * hair, 3 * hair]);
        expect(x + hair, name).toBe(stem); // centred on the hairline column
        expect(y + h, name).toBe(Math.floor((wick[1] as number) + 0.5) - 2 * hair);
      }
    },
  );

  it("an inverted scale puts it 2 hairlines below the high (the side away from the low)", () => {
    const inv = Float64Array.of(10, 2, 0, 0, 0, 0, 0, 0); // y = 2 t: the high is lower
    const g = geom(12, 1);
    const [, y] = mark(AMENDED, BARS["up"] as number[], g, inv);
    expect(y).toBe(30 * 2 + 2);
  });
});

describe("property: the marks never alter the bar (2 000 seeded bars)", () => {
  it("dir and every part's rect are the same with any state bits; the ring clears the mark", () => {
    const rng = mulberry32(20261101);
    for (let c = 0; c < 2_000; c += 1) {
      const dpr = [1, 1.25, 1.5, 2, 3][Math.floor(rng() * 5)] as number;
      const s = MARKS_FROM + rng() * 60;
      const g = geom(s, dpr);
      const lo = Math.floor(rng() * 50);
      const hi = lo + Math.floor(rng() * 30);
      const o = lo + Math.floor(rng() * (hi - lo + 1));
      const cl = rng() < 0.2 ? o : lo + Math.floor(rng() * (hi - lo + 1));
      const bar = [o, hi, lo, cl];
      const flags = Math.floor(rng() * 16);
      // The ring packs flags | dir << 4: no flag bit reaches dir.
      expect(((flags | (candleDir(o, hi, lo, cl) << 4)) >> 4) & 3).toBe(candleDir(o, hi, lo, cl));
      const hair = g[GEOM.hair] as number;
      const [rx, ry, rw, rh] = mark(FORMING, bar, g) as [number, number, number, number];
      const clear = (MARK_GEOM.ringOffset + MARK_GEOM.ringWeight) * hair;
      for (const p of [CANDLE_PART.wick, CANDLE_PART.body]) {
        const [x, y, w, h] = part(p, bar, g) as [number, number, number, number];
        const msg = `case ${c}: part ${p} of ${bar.join()} at s ${s}, dpr ${dpr}`;
        expect(x - rx >= clear && rx + rw - (x + w) >= clear, msg).toBe(true);
        if (p === CANDLE_PART.wick || candleDir(o, hi, lo, cl) >= CANDLE_DIR.doji) {
          expect(y - ry >= clear - 1e-9 && ry + rh - (y + h) >= clear - 1e-9, msg).toBe(true);
        }
      }
    }
  });
});

describe("the shader and the twin agree (E12-S10)", () => {
  it("part 7 (after S07's hollow 5 / 6) is a 4-vertex quad in the wick colour", () => {
    expect([CANDLE_PART.marks, PART_VERTICES[CANDLE_PART.marks]]).toEqual([7, 4]);
    expect(PART_VERTICES).toHaveLength(8);
    for (const dir of [CANDLE_DIR.up, CANDLE_DIR.down, CANDLE_DIR.doji, CANDLE_DIR.zeroRange]) {
      expect(partColor(CANDLE_PART.marks, dir | 0x30)).toBe(PALETTE.wick);
    }
    expect(CANDLE.vertex).toContain("int row = base == 0 || part == 4 || part == 7");
    expect(CANDLE.vertex).toContain("(part == 4 || part == 7 ? a_ohlc.x : gl_InstanceID)");
  });

  it("the heavy bit is the drawn wick's 2 hairlines: the ring clears a hollow colour-down wick", () => {
    expect(CANDLE.vertex).toContain(`float weight = (a_meta & ${MARK_HEAVY}) != 0 ? 2.0 * h : h;`);
    const g = geom(3, 2); // the narrowest L0 body at dpr 2: a 2-hairline wick passes its edge
    // Bar o 10, h 20, l 5, c 15: up (close > open), but colour-down under hollow.
    const out = new Float64Array(4);
    const up = CANDLE_DIR.up << 4;
    markRect(FORMING, 3, 20, 5, 10, up | MARK_HEAVY, K, 0, 0, g, out);
    const [rx, , rw] = [...out] as [number, number, number];
    const wick = new Float64Array(4);
    // The hollow wick of a colour-down bar (mark bits: up dir, hollow, no colour-up).
    candleRect(CANDLE_PART.hollowWick, 3, 10, 20, 5, 15, up | 0x10, K, 0, 0, g, wick);
    const clear = (MARK_GEOM.ringOffset + MARK_GEOM.ringWeight) * (g[GEOM.hair] as number);
    expect(rx + rw - ((wick[0] as number) + (wick[2] as number))).toBeGreaterThanOrEqual(clear);
    markRect(FORMING, 3, 20, 5, 10, up, K, 0, 0, g, out);
    expect(out[2]).toBeLessThan(rw); // without it the ring is the 1-hairline wick's
  });

  it("spells MARK_GEOM's numbers: offset + weight, the square, the lift, the 2 / 2 dash", () => {
    const pad = MARK_GEOM.ringOffset + MARK_GEOM.ringWeight;
    expect(CANDLE.vertex).toContain(`float pad = ${pad}.0 * h;`);
    expect(CANDLE.vertex).toContain(`float side = ${MARK_GEOM.square}.0 * h;`);
    expect(CANDLE.vertex).toContain(
      `at - ${MARK_GEOM.lift}.0 * h - side : at + ${MARK_GEOM.lift}.0 * h`,
    );
    expect(MARK_GEOM.ringWeight).toBe(1); // the fragment's band is `t` = one hairline
    expect(CANDLE.fragment).toContain(`((s / (${MARK_GEOM.dash} * t)) & 1) != 0`);
  });

  it("a zero-range bar's ring is as wide as its body at fractional dpr: one expression", () => {
    const expr = "floor(3.0 * u_geom[1].x + 0.5)"; // roundHalfUp(3 dpr), the twin's `floor(3 * dpr + 0.5)`
    expect(CANDLE.vertex.split(expr)).toHaveLength(3); // the body part's min width and the ring's
    expect(CANDLE.vertex).toContain(`dir == 3 ? max(body, ${expr}) : body`);
    expect(CANDLE.vertex).not.toContain("max(body, 3.0 * h)");
    const out = new Float64Array(4);
    const body = new Float64Array(4);
    for (const dpr of [1, 1.25, 1.5, 1.75, 2, 2.5]) {
      const g = geom(3, dpr);
      const hair = g[GEOM.hair] as number;
      const pad = (MARK_GEOM.ringOffset + MARK_GEOM.ringWeight) * hair;
      const bar = [100, 100, 100, 100] as const; // o = h = l = c: zero range
      const dir = candleDir(...bar);
      expect(dir, `dpr ${dpr}`).toBe(CANDLE_DIR.zeroRange);
      candleRect(CANDLE_PART.body, 3, 100, 100, 100, 100, dir, K, 0, 0, g, body);
      markRect(FORMING, 3, 100, 100, 100, dir << 4, K, 0, 0, g, out); // the entry's word 4
      const minWidth = Math.floor(3 * dpr + 0.5);
      expect(body[2], `body at dpr ${dpr}`).toBeGreaterThanOrEqual(minWidth);
      expect(out[2], `ring at dpr ${dpr}`).toBe((body[2] as number) + 2 * pad);
      expect(out[0], `ring x at dpr ${dpr}`).toBe((body[0] as number) - pad);
    }
  });

  it("every `in` the vertex shader declares is bound by CANDLE_ATTRIBUTES, as an int", () => {
    const declared = [
      ...CANDLE.vertex.matchAll(/^layout\(location = (\d+)\) in (ivec4|int) (\w+);$/gm),
    ];
    expect([...CANDLE.vertex.matchAll(/^.*\bin \w+ \w+;$/gm)]).toHaveLength(declared.length);
    const layout = INSTANCE_LAYOUTS[PROGRAM.candle]?.attributes ?? [];
    const bound = declared.map(([, at, type, name]) => {
      const row = layout.find(([n]) => n === name);
      return [Number(at), row?.[1] ?? -1, type === "ivec4" ? 4 : 1, row?.[3] ?? false];
    });
    expect(bound.map(([at, offset, size]) => [at, offset, size])).toEqual(CANDLE_ATTRIBUTES.ints);
    expect(bound.every(([, , , int]) => int === true)).toBe(true);
    expect(CANDLE_ATTRIBUTES.stride).toBe(INSTANCE_LAYOUTS[PROGRAM.candle]?.stride);
  });
});
