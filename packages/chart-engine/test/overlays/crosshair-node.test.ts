// E11-S07 crosshair node (CMP-190; E11-D02 §7.3, E11-D06 §5.2): dashed 4 / 4 hairlines snapped to
// whole device pixels, a muted remote vertical only without a local cursor, an instant hide, a
// rewrite only when something moved, and a ring that never reallocates while the plot keeps its
// size (no per-frame allocation).
import { describe, expect, it } from "vitest";
import {
  CROSSHAIR_NODE_ID,
  CrosshairNode,
  MUTED_DEFAULT,
} from "../../src/overlays/crosshair-node.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { PooledBatchSink } from "../../src/scene/pool.js";

const THEME = { "color.crosshair": "#ff0000" };
const PLOT = [0, 0, 400, 300] as const;

/** Segments as [x0, y0, x1, y1, width, alpha]. */
function segments(n: CrosshairNode): number[][] {
  const out: number[][] = [];
  for (let i = 0; i < n.count; i += 1) {
    const r = Array.from(n.data.slice(i * 9, i * 9 + 9));
    out.push([...r.slice(0, 5), r[8] as number]);
  }
  return out;
}

describe("crosshair node: geometry", () => {
  it.each([1, 1.25, 2])("dpr %d: dashed 4 / 4 × the hairline, on the device grid", (dpr) => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    expect(n.write(THEME, dpr, Math.round(300 * dpr), PLOT, true, 100.3, 50.7, Number.NaN)).toBe(
      true,
    );
    const w = Math.max(1, Math.floor(dpr));
    const segs = segments(n);
    const vertical = segs.filter(([x0, , x1]) => x0 === x1);
    const horizontal = segs.filter(([, y0, , y1]) => y0 === y1);
    expect(vertical.length + horizontal.length).toBe(segs.length);
    expect(vertical.length).toBe(Math.ceil((300 * dpr) / (8 * w)));
    expect(horizontal.length).toBe(Math.ceil((400 * dpr) / (8 * w)));
    for (const [x0, y0, x1, y1, width, alpha] of segs) {
      expect(width).toBe(w);
      expect(alpha).toBe(1);
      const across = y0 === y1 ? (y0 as number) : (x0 as number);
      expect(Number.isInteger(across - w / 2)).toBe(true); // no grey fringe
      const len =
        Math.abs((x1 as number) - (x0 as number)) + Math.abs((y1 as number) - (y0 as number));
      expect(len).toBeLessThanOrEqual(4 * w + 1e-9);
    }
  });

  it("test_write_cursorOutsideThePlot_drawsNeitherLine_andAllocatesNothing", () => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    n.write(THEME, 1, 300, PLOT, true, 500, 400, Number.NaN);
    expect(n.count).toBe(0);
    expect(n.data.length).toBe(0); // an axis-less, cursor-less chart holds no GPU bytes
    n.write(THEME, 1, 300, PLOT, true, 100, Number.NaN, Number.NaN); // a key cursor before a price
    expect(segments(n).every(([x0, , x1]) => x0 === x1)).toBe(true);
  });
});

describe("crosshair node: the remote line (BQ-5)", () => {
  it("test_write_remoteOnly_mutedVertical_neverWithALocalCursor", () => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    n.write(THEME, 1, 300, PLOT, false, Number.NaN, Number.NaN, 120);
    const segs = segments(n);
    expect(segs.length).toBe(Math.ceil(300 / 8));
    expect(new Set(segs.map((s) => s[5]))).toEqual(new Set([Math.fround(MUTED_DEFAULT)]));
    n.write(THEME, 1, 300, PLOT, true, 200, 100, 120); // a local cursor wins
    expect(segments(n).every((s) => s[5] === 1)).toBe(true);
  });

  it.each([
    ["0.5", 0.5],
    ["abc", MUTED_DEFAULT],
    ["2", MUTED_DEFAULT],
  ])("opacity.muted %s gives alpha %d", (token, alpha) => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    n.write({ ...THEME, "opacity.muted": token }, 1, 300, PLOT, false, 0, 0, 120);
    expect(n.data[8]).toBe(Math.fround(alpha));
  });
});

describe("crosshair node: change detection and allocation", () => {
  it("test_write_sameInputs_noRewrite_newTheme_rewrites", () => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    n.write(THEME, 1, 300, PLOT, true, 100, 50, Number.NaN);
    expect(n.write(THEME, 1, 300, PLOT, true, 100, 50, Number.NaN)).toBe(false);
    expect(n.write(THEME, 1, 300, PLOT, true, 100, 50, 77)).toBe(false); // remote ignored: local
    const copy = { ...THEME };
    expect(n.write(copy, 1, 300, PLOT, true, 100, 50, Number.NaN)).toBe(true);
    n.invalidate(); // a restored context
    expect(n.write(copy, 1, 300, PLOT, true, 100, 50, Number.NaN)).toBe(true);
    expect(n.writes).toBe(3);
  });

  it("test_write_nothingToDraw_trueWhenLinesWereShown_falseWhenAlreadyEmpty", () => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    n.write(THEME, 1, 300, PLOT, true, 100, 50, Number.NaN);
    expect(n.count).toBeGreaterThan(0);
    // Off the plot: the lines go, so the caller re-uploads (and collects) once.
    expect(n.write(THEME, 1, 300, PLOT, true, 500, 400, Number.NaN)).toBe(true);
    expect(n.count).toBe(0);
    // Still nothing, though the plot moved: an empty ring stays, nothing to upload or collect.
    expect(n.write(THEME, 1, 320, [0, 0, 420, 320], true, 500, 400, Number.NaN)).toBe(false);
    expect(n.write(THEME, 1, 320, [0, 0, 420, 320], false, 0, 0, Number.NaN)).toBe(false);
    expect(n.count).toBe(0);
  });

  it("test_write_hide_isInstant", () => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    n.write(THEME, 1, 300, PLOT, true, 100, 50, Number.NaN);
    expect(n.write(THEME, 1, 300, PLOT, false, 100, 50, Number.NaN)).toBe(true);
    expect(n.count).toBe(0);
  });

  it("test_write_1000MovingFrames_keepTheRing_noReallocation", () => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    n.write(THEME, 2, 600, PLOT, true, 0, 0, Number.NaN);
    const ring = n.data;
    for (let f = 0; f < 1000; f += 1) {
      n.write(THEME, 2, 600, PLOT, true, f % 400, (f * 7) % 300, Number.NaN);
      expect(n.data).toBe(ring);
    }
  });

  it("test_collect_oneLineBatchOverTheRing", () => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    n.write(THEME, 1, 300, PLOT, true, 100, 50, Number.NaN);
    const sink = new PooledBatchSink();
    expect(n.collect(sink)).toBe(true);
    expect(sink.at(0)).toMatchObject({
      nodeId: CROSSHAIR_NODE_ID,
      program: PROGRAM.line,
      first: 0,
      count: n.count,
    });
  });
});

describe("E06-D03 D10: the keyboard column while the chart root has focus (BQ-7)", () => {
  const FOCUS = { ...THEME, "color.focus.ring": "#00ff00", "color.chart.background": "#000000" };
  /** Segment rows with their RGB: [x0, y0, x1, y1, width, r, g, b]. */
  const rgb = (n: CrosshairNode): number[][] =>
    Array.from({ length: n.count }, (_, i) => {
      const r = Array.from(n.data.slice(i * 9, i * 9 + 9));
      return [...r.slice(0, 8)];
    });

  it.each([1, 2])(
    "dpr %d: a solid 2 px core over 1 px halos, full height, under the lines",
    (dpr) => {
      const n = new CrosshairNode(CROSSHAIR_NODE_ID);
      const h = 300 * dpr;
      expect(n.write(FOCUS, dpr, h, PLOT, true, 150, 40, Number.NaN, 150)).toBe(true);
      const [halo, core, ...lines] = rgb(n);
      expect(halo).toEqual([150 * dpr, 0, 150 * dpr, h, 4 * dpr, 0, 0, 0]); // the pane colour
      expect(core).toEqual([150 * dpr, 0, 150 * dpr, h, 2 * dpr, 0, 1, 0]); // color.focus.ring
      // The column replaces the dashed vertical at its bar; the horizontal keeps its treatment.
      expect(lines.every(([, y0, , y1]) => y0 === y1)).toBe(true);
      expect(lines.length).toBe(Math.ceil((400 * dpr) / (8 * Math.max(1, Math.floor(dpr)))));
    },
  );

  it("test_column_pointerElsewhere_bothTheColumnAndThePointerVerticalDraw", () => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    n.write(FOCUS, 1, 300, PLOT, true, 250.5, 40, Number.NaN, 150);
    const segs = rgb(n);
    expect(segs.filter(([x0, , x1]) => x0 === 150 && x1 === 150)).toHaveLength(2);
    expect(segs.some(([x0, , x1]) => x0 === x1 && x0 !== 150)).toBe(true); // the pointer's
  });

  it("test_column_noLocalCursor_drawsAlone_andNeverEases", () => {
    const n = new CrosshairNode(CROSSHAIR_NODE_ID);
    expect(n.write(FOCUS, 1, 300, PLOT, false, Number.NaN, Number.NaN, Number.NaN, 150)).toBe(true);
    expect(n.count).toBe(2);
    const writes = n.writes;
    n.write(FOCUS, 1, 300, PLOT, false, Number.NaN, Number.NaN, Number.NaN, 150);
    expect(n.writes).toBe(writes); // a steady frame rewrites nothing (no easing frames)
    expect(n.write(FOCUS, 1, 300, PLOT, false, Number.NaN, Number.NaN, Number.NaN, 170)).toBe(true);
    expect(rgb(n)[1]?.[0]).toBe(170); // the next frame lands on the new bar: a snap
    // Focus lost: the column goes at once.
    expect(n.write(FOCUS, 1, 300, PLOT, false, Number.NaN, Number.NaN, Number.NaN)).toBe(true);
    expect(n.count).toBe(0);
  });
});
