// E14-T03 slice 3: the `drawing-fill` ring (which kinds draw, the three chart-space corners, fill
// and stroke colours, style, compare-first change ranges) and the two backends in parity at dpr 1,
// 1.5 and 2, linear and log: the float32 shader stand-in puts corners A, B, C where the transform
// does; the 2D painter fills a rect or band inset by exactly half its stroke (the outline is
// `drawing-line`'s, sharing the chart-space fourth corner D = B + C − A), and fills an ellipse
// inside its ring, which it strokes with the dash pattern. Pixel-level parity defers to E11-T08.
import { describe, expect, it } from "vitest";
import { FILL_STRIDE, FillInstances, fillCount } from "../../../src/layers/drawings/fills.js";
import { corner } from "../../../src/layers/drawings/lines.js";
import type { DrawingInput } from "../../../src/layers/drawings/model.js";
import { reindex, toRecord, type DrawingRecord } from "../../../src/layers/drawings/project.js";
import * as tf from "../../../src/viewport/index.js";
import { minuteMap } from "../../interaction/fixtures.js";
import { harness, nums, standIn } from "./harness.js";

const T = (i: number): number => minuteMap().indexToTime(i);
const style = { colour: 0x2962ffff, fill: 0x2962ff33, width: 4, dash: 1 } as const;
const input = (kind: DrawingInput["kind"], points: number[], extra = {}): DrawingInput => ({
  ...{ id: kind, kind, points, style },
  ...extra,
});
const rec = (d: DrawingInput): DrawingRecord => {
  const r = toRecord(d);
  reindex(r, minuteMap(), 1);
  return r;
};
const RECT = [T(20) + 30e6, 1012.25, T(60), 1047];
const BAND = [T(20), 1010, T(60), 1030, T(30), 1045];

describe("the drawing-fill ring", () => {
  it("a rect or band draws with a fill colour only; an ellipse always; others never", () => {
    const counts = [
      input("rect", RECT),
      input("rect", RECT, { style: { ...style, fill: undefined } }),
      input("band", BAND),
      input("ellipse", RECT, { style: { ...style, fill: undefined } }),
      input("segment", RECT),
      input("rect", RECT, { visible: false }),
    ].map((d) => fillCount(rec(d)));
    expect(counts).toEqual([1, 0, 1, 1, 0, 0]);
  });

  it("writes corners A, B, C (a rect's mixing its anchors), colours and the style", () => {
    const ring = new FillInstances();
    const noFill = { ...style, fill: undefined };
    ring.encode([rec(input("rect", RECT)), rec(input("ellipse", RECT, { style: noFill }))], 1.5);
    const [f, i] = [ring.data, ring.ints];
    // A = (i0, t0), B = (i1, t0), C = (i0, t1): ints, then the fractions' bits.
    expect([i[0], i[1], f[2], f[3], i[4], i[5], i[8], i[9], f[11]]).toEqual([
      20, 1012, 0.5, 0.25, 60, 1012, 20, 1047, 0,
    ]);
    // Premultiplied colours, un-premultiplied here back to bytes: the fill, then the stroke.
    const byte = (o: number): number[] => {
      const al = f[o + 3] ?? 0;
      return [0, 1, 2]
        .map((c) => Math.round(((f[o + c] ?? 0) / al) * 255))
        .concat(Math.round(al * 255));
    };
    expect([byte(12), byte(16)]).toEqual([
      [0x29, 0x62, 0xff, 0x33],
      [0x29, 0x62, 0xff, 0xff],
    ]);
    expect([...f.slice(20, 24)]).toEqual([0, 6, 1, 0]); // rect; 4 CSS px × 1.5; dashed
    expect([f[FILL_STRIDE + 15], f[FILL_STRIDE + 20]]).toEqual([0, 1]); // no fill: alpha 0; ellipse
  });

  it("reports only the changed instance; a band's D is p2 + (p1 − p0) in chart space", () => {
    const ring = new FillInstances();
    const set = (y: number) => [
      rec(input("rect", RECT)),
      rec(input("band", [...BAND.slice(0, 5), y])),
    ];
    ring.encode(set(1045), 1);
    ring.encode(set(1045), 1);
    expect([ring.lo, ring.hi]).toEqual([0, 0]);
    ring.encode(set(1050), 1);
    expect([ring.lo, ring.hi]).toEqual([1, 2]);
    const d = new Float64Array(2);
    corner(rec(input("band", BAND)), 3, d);
    expect([...d]).toEqual([30 + 40, 1045 + 20]); // p2 + (p1 − p0)
  });
});

/** The transform's corner `c` (0 A, 1 B, 2 C, 3 D) of `r` in device px. */
function want(vp: tf.ChartViewport, r: DrawingRecord, c: number, dpr: number): number[] {
  const p = new Float64Array(2);
  corner(r, c, p);
  return [
    tf.indexToScreen(vp, p[0] as number) * dpr,
    tf.priceToScreen(vp, 0, p[1] as number) * dpr,
  ];
}

/** Each inset vertex lies exactly `hw` inside the two quad edges it sits between. */
function insetBy(quad: number[][], got: number[][], hw: number): void {
  const m = [(quad[0]![0]! + quad[2]![0]!) / 2, (quad[0]![1]! + quad[2]![1]!) / 2];
  const dist = (p: number[], a: number[], b: number[]): number => {
    const [ex, ey] = [b[0]! - a[0]!, b[1]! - a[1]!];
    const n = [-ey / Math.hypot(ex, ey), ex / Math.hypot(ex, ey)];
    const s = Math.sign((m[0]! - a[0]!) * n[0]! + (m[1]! - a[1]!) * n[1]!);
    return s * ((p[0]! - a[0]!) * n[0]! + (p[1]! - a[1]!) * n[1]!);
  };
  got.forEach((p, v) => {
    const [prev, at, next] = [quad[(v + 3) % 4]!, quad[v]!, quad[(v + 1) % 4]!];
    expect(dist(p, prev, at)).toBeCloseTo(hw, 3);
    expect(dist(p, at, next)).toBeCloseTo(hw, 3);
  });
}

describe("Scenario: fills in parity (2D and the GL stand-in) at dpr 1, 1.5 and 2", () => {
  const MODES = [
    [1, false],
    [1.5, false],
    [2, false],
    [1, true],
    [2, true],
  ] as const;

  it.each(MODES)(
    "dpr %s, log %s: a rect's and a band's fill sit half a stroke inside",
    (dpr, log) => {
      for (const shape of [input("rect", RECT), input("band", BAND)]) {
        const { vp, node, ctx2d, block } = harness(dpr, log, [shape]);
        const r = node.set.order[0] as DrawingRecord;
        for (const c of [0, 1, 2]) {
          const gl = standIn(node.fills, 0, c, block);
          const w = want(vp, r, c, dpr);
          expect(Math.abs(gl[0] - w[0]!) + Math.abs(gl[1] - w[1]!), `GL corner ${c}`).toBeLessThan(
            0.1,
          );
        }
        const fill = ctx2d.paths.find((p) => p.op === "fill");
        expect(fill?.style).toBe("rgba(41, 98, 255, 0.2)");
        const quad = [0, 1, 3, 2].map((c) => want(vp, r, c, dpr)); // A, B, D, C: edge order
        insetBy(quad, (fill?.parts ?? []).map(nums), 2 * dpr); // half of 4 CSS px
        // The outline's edges end on the same chart-space corners (a band's C → D included).
        const strokes = ctx2d.paths
          .filter((p) => p.op === "stroke")
          .flatMap((p) => p.parts.map(nums));
        for (const q of quad) {
          expect(
            strokes.some((s) => Math.hypot(s[0]! - q[0]!, s[1]! - q[1]!) < 0.01),
            `${q}`,
          ).toBe(true);
        }
      }
    },
  );

  it.each(MODES)(
    "dpr %s, log %s: an ellipse fills inside its ring and strokes it dashed",
    (dpr, log) => {
      const { vp, node, ctx2d } = harness(dpr, log, [input("ellipse", RECT)]);
      const r = node.set.order[0] as DrawingRecord;
      const [a, d] = [want(vp, r, 0, dpr), want(vp, r, 3, dpr)];
      const [cx, cy] = [(a[0]! + d[0]!) / 2, (a[1]! + d[1]!) / 2];
      const [rx, ry] = [Math.abs(d[0]! - a[0]!) / 2, Math.abs(d[1]! - a[1]!) / 2];
      const hw = 2 * dpr;
      const near = (got: number[] | undefined, w: number[]): void =>
        got!.forEach((v, k) => expect(Math.abs(v - w[k]!)).toBeLessThan(0.01));
      expect(ctx2d.ellipses).toHaveLength(2);
      near(ctx2d.ellipses[0], [cx, cy, rx - hw, ry - hw]); // the fill, inside the ring
      near(ctx2d.ellipses[1], [cx, cy, rx, ry]); // the ring
      expect(ctx2d.paths.map((p) => [p.op, p.lineWidth])).toEqual([
        ["fill", expect.anything()],
        ["stroke", 4 * dpr],
      ]);
      expect(ctx2d.dashes.at(-1)).toEqual([12 * dpr, 12 * dpr]);
    },
  );

  it("a pan or a 100x zoom re-encodes neither ring", () => {
    const { vp, graph, node, frame } = harness(2, false, [
      input("rect", RECT),
      input("ellipse", RECT),
    ]);
    const encodes = node.encodes;
    vp.zoomAt(600, 100);
    vp.pan(-50);
    graph.markViewport();
    frame();
    expect(node.encodes).toBe(encodes);
  });
});
