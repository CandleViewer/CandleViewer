// E12-S07 PR B 2D parity for the line family at dpr 1, 1.5 and 2: the Canvas2D backend paints
// every instance of every drawn part where the geometry twin places it (a strip quad as its
// polygon, a disc as a 16-gon on the twin's circle), in the palette row the shader picks, and
// drops what the shader collapses: the segment into a `gap_before` bar (R-2), a baseline fill
// with nothing on its side. Over a ring whose bars wrap past physical slot 0.
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import { DISC_SIDES } from "../../src/canvas2d/painters.js";
import {
  CANDLE_STRIDE,
  CandleRing,
  isSegment,
  RIBBON_GEOM,
  RIBBON_PART,
  type RibbonKind,
  RibbonSeries,
  ribbonQuad,
  ribbonRow,
} from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { THEME } from "../layers/fixtures.js";
import { FakeCtx2D } from "./fake-ctx2d.js";

const LINE_THEME = { ...THEME, "color.chart.line": "#8b5cf6" };
const CLOSES = [10, 14, 12, 18, 9, 11, 7, 15, 13, 16];
const GAP_AT = 6;

function paint(kind: RibbonKind, dpr: number, plot?: { right: number; bottom: number }) {
  // maxBars 12 keeps a 16-slot ring: 22 bars appended keep the last 12, across the physical end.
  const store = new BarStore({ maxBars: 12, initialCapacity: 16 });
  const ring = new CandleRing();
  const n = 22;
  const close = Int32Array.from({ length: n }, (_, i) => CLOSES[(i + 2) % CLOSES.length] ?? 0);
  const flags = new Uint8Array(n);
  flags[n - CLOSES.length + GAP_AT] = 1;
  const batch = {
    time: Float64Array.from({ length: n }, (_, i) => i * 60e6),
    open: close.slice(),
    high: close.map((c) => c + 1),
    low: close.map((c) => c - 1),
    close,
    volume: new Float32Array(n).fill(1),
    flags,
    priceOrigin: 0,
    tickSize: 1,
  };
  for (const [a, b] of [
    [0, 11],
    [11, 22],
  ]) {
    const cut = <T extends Int32Array | Float64Array | Float32Array | Uint8Array>(c: T): T =>
      c.slice(a, b) as T;
    const part = { ...batch, time: cut(batch.time), open: cut(batch.open), high: cut(batch.high) };
    const rest = { low: cut(batch.low), close: cut(batch.close), volume: cut(batch.volume) };
    ring.sync(store, store.append({ ...part, ...rest, flags: cut(batch.flags) }));
  }
  const r = new RibbonSeries(ring, kind);
  const vp = new ChartViewport(store);
  vp.setSize(240, 100, dpr);
  vp.setPanePlot(0, 0, 100);
  vp.setPriceInfo(0, 0, 1);
  vp.setPriceRange(0, 0, 22);
  vp.setTimeRange(store.indexToTime(0) - 30e6, store.indexToTime(store.length - 1) + 30e6);
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  block.floats[4] = 240 * dpr;
  block.floats[5] = 100 * dpr;
  expect(r.setTheme(LINE_THEME)).toBeNull();
  r.baseTick = 12; // crossings on both sides
  r.frame(vp.barSpacing, dpr, 0, plot?.right ?? 0, plot?.bottom ?? 0);
  const ctx = new FakeCtx2D();
  const be = new Canvas2DBackend(ctx);
  const ids = r.blocks.map((_, i) => `h${i}`);
  for (const id of ids) be.attach(id, r.source);
  be.setPaneUniforms(() => block);
  be.setBatchUniforms((b) => r.blocks[ids.indexOf(b.nodeId)] ?? null);
  const list = ids.map(
    (nodeId, i) =>
      ({
        nodeId,
        program: PROGRAM.ribbon,
        texture: 0,
        first: 0,
        count: ring.capacity,
        layer: 0,
        seq: i,
        lo: 0,
        hi: 0,
      }) as RetainedBatch,
  );
  be.submit(list, ids.length, 240 * dpr, 100 * dpr);
  return { ring, block, r, ctx, be };
}

/** Painted paths as `style polygon` strings, one per subpath (a moveTo starts one). */
function polygons(ctx: FakeCtx2D): string[] {
  const out: string[] = [];
  for (const p of ctx.paths) {
    let cur: string[] = [];
    const flush = (): void => void (cur.length > 0 && out.push(`${p.style} ${cur.join(" ")}`));
    for (const part of p.parts) {
      if (part.startsWith("moveTo")) {
        flush();
        cur = [];
      }
      cur.push(part.split(" ").slice(1).join(","));
    }
    flush();
  }
  return out.sort();
}

describe("Canvas2D ribbon painter (parity with the geometry twin)", () => {
  for (const kind of ["line", "area", "baseline"] as const) {
    it.each([
      [1, false],
      [1.5, false],
      [2, false],
      [1.5, true], // with a plot rect: the base line and the area clip to it, twin and painter alike
    ])(`${kind}, dpr %f, plot rect %s: every instance's polygon and colour`, (dpr, rect) => {
      const { ring, block, r, ctx, be } = paint(
        kind,
        dpr,
        rect ? { right: 180, bottom: 70 } : undefined,
      );
      expect(ring.head + ring.length).toBeGreaterThan(ring.capacity); // wrapped
      const css = (row: number): string => {
        const b = (i: number): number => Math.round((r.palette[row * 4 + i] ?? 0) * 255);
        return `rgba(${b(0)}, ${b(1)}, ${b(2)}, ${b(3) / 255})`;
      };
      const want: string[] = [];
      const q = new Float64Array(8);
      const n = ring.length;
      const mask = ring.capacity - 1;
      const word = (i: number, w: number): number =>
        ring.ints[((ring.head + i) & mask) * CANDLE_STRIDE + w] ?? 0;
      let collapsed = 0;
      for (const blk of r.blocks) {
        if (blk.instances === 0) continue;
        const part = blk.ints[0] ?? 0;
        const single = part === RIBBON_PART.last || part === RIBBON_PART.base;
        const end = single ? 1 : isSegment(part) ? n - 1 : n;
        for (let j = 0; j < end; j += 1) {
          const i = single ? n - 1 : j;
          const ok = ribbonQuad(
            part,
            i,
            n,
            word(i, 3),
            word(i + 1, 3),
            word(i + 1, 4),
            blk.base ?? 0,
            block.floats,
            block.ints[0] ?? 0,
            block.ints[1] ?? 0,
            r.geom,
            q,
          );
          if (!ok) {
            collapsed += 1;
            continue;
          }
          const pts: number[][] = [];
          if (part === RIBBON_PART.join || part === RIBBON_PART.last) {
            const rad =
              r.geom[part === RIBBON_PART.join ? RIBBON_GEOM.join : RIBBON_GEOM.disc] ?? 0;
            const [cx, cy] = [((q[0] ?? 0) + (q[6] ?? 0)) / 2, ((q[1] ?? 0) + (q[7] ?? 0)) / 2];
            for (let s = 0; s < DISC_SIDES; s += 1) {
              const a = (2 * Math.PI * s) / DISC_SIDES;
              pts.push([cx + rad * Math.cos(a), cy + rad * Math.sin(a)]);
            }
          } else for (const v of [0, 1, 3, 2]) pts.push([q[v * 2] ?? 0, q[v * 2 + 1] ?? 0]);
          want.push(`${css(ribbonRow(part))} ${pts.map((p) => p.join(",")).join(" ")}`);
        }
      }
      expect(collapsed).toBeGreaterThan(0); // the gap (and, for a baseline, the far sides)
      expect(polygons(ctx)).toEqual(want.sort());
      expect(be.trace.draws).toBeLessThanOrEqual(r.blocks.filter((b) => b.instances).length);
    });
  }

  it("a plot rect stops the painted base line and area fill at its right and bottom edges", () => {
    const dpr = 2;
    const nums = (poly: string): number[][] =>
      poly
        .slice(poly.indexOf(" ", poly.indexOf(")")) + 1)
        .split(" ")
        .map((p) => p.split(",").map(Number));
    const base = paint("baseline", dpr, { right: 180, bottom: 70 });
    // The base line: the one quad from x 0 that is a hairline tall.
    const hairs = polygons(base.ctx).filter((p) => {
      const v = nums(p);
      const ys = v.map((c) => c[1] ?? 0);
      return v.some((c) => c[0] === 0) && Math.max(...ys) - Math.min(...ys) <= 2 * dpr;
    });
    expect(hairs).toHaveLength(1);
    const xs = hairs.flatMap((p) => nums(p).map((v) => v[0] ?? 0));
    expect(Math.max(...xs)).toBeGreaterThan(0);
    expect(Math.max(...xs)).toBeLessThanOrEqual(180 * dpr); // no ink in the price gutter
    const area = paint("area", dpr, { right: 180, bottom: 70 });
    const ys = polygons(area.ctx).flatMap((p) => nums(p).map((v) => v[1] ?? 0));
    expect(Math.max(...ys)).toBeLessThan(100 * dpr); // reverting: the fill reaches the canvas bottom
  });
});
