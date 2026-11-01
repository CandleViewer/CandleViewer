// E14-T03 slice 1 properties, 5 000 seeded cases per mode (BQ-81: mulberry32 loops; a failure
// prints its seed). Linear and log, inverted or not: every anchor of a visible drawing projects
// inside its screen bounds, and chart space -> screen -> chart space returns the anchor.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../../bench/fixtures/rng.mjs";
import { bars } from "../../../bench/scenes/pan-zero-upload.js";
import { DRAWING_KINDS, DRAWING_POINTS } from "../../../src/layers/drawings/model.js";
import { reindex, screenBounds, toRecord } from "../../../src/layers/drawings/project.js";
import { BarStore } from "../../../src/model/BarStore.js";
import * as tf from "../../../src/viewport/index.js";

const T0 = 1_790_000_000_000_000;
const store = new BarStore({ maxBars: 5_000 });
store.append(bars(5_000, T0));
const out = new Float32Array(4);
/** Float32 bounds: a relative slack of 1e-6 plus a thousandth of a px. */
const near = (v: number): number => Math.abs(v) * 1e-6 + 1e-3;

function random(rng: () => number, log: boolean, inverted: boolean): tf.ChartViewport {
  const vp = new tf.ChartViewport(store);
  vp.setSize(100 + rng() * 3000, 200 + rng() * 1500, 1 + Math.floor(rng() * 3));
  vp.setPanePlot(0, rng() * 40, 150 + rng() * 1500);
  vp.zoomAt(0, 0.05 + rng() * 40);
  vp.pan(-rng() * 5_000 * vp.barSpacing);
  vp.setPriceInfo(0, 0, 0.5);
  (vp.panes[0] as tf.PaneTransform).logReason = null;
  vp.setScale(0, { mode: log ? "log" : "linear", inverted });
  const low = 2_000 + rng() * 2e5; // positive prices
  vp.setPriceRange(0, low, low + 50 + rng() * 5e4);
  return vp;
}

/** A drawing of a random kind, anchors within two windows of the view on both axes. */
function drawing(rng: () => number, vp: tf.ChartViewport) {
  const kind = DRAWING_KINDS[Math.floor(rng() * DRAWING_KINDS.length)] ?? "segment";
  const [lo, hi] = DRAWING_POINTS[kind];
  const { priceLow, priceHigh } = vp.panes[0] as tf.PaneTransform;
  const points: number[] = [];
  for (let i = lo + Math.floor(rng() * Math.min(20, hi - lo + 1)); i > 0; i -= 1) {
    const idx = vp.leftIndex + (rng() * 3 - 1) * vp.visibleBars;
    const tick = priceLow + (rng() * 3 - 1) * (priceHigh - priceLow);
    points.push(T0 + idx * 60e6, Math.round(Math.max(10, tick)));
  }
  const style = { colour: 0, width: 1 + Math.floor(rng() * 8), dash: 0 } as const;
  const r = toRecord({ id: "d", kind, points, style });
  reindex(r, vp.map, 1);
  return r;
}

describe("Scenario: anchors project inside their bounds and round-trip (20 000 cases)", () => {
  it.each([
    [false, false],
    [false, true],
    [true, false],
    [true, true],
  ])(
    "log %s, inverted %s",
    (log, inverted) => {
      for (let c = 0; c < 5_000; c += 1) {
        const rng = mulberry32(358_000 + c);
        try {
          const vp = random(rng, log, inverted);
          const r = drawing(rng, vp);
          const { kind, style } = r.input;
          screenBounds(vp, r, out, 0);
          const [x0, y0, x1, y1] = [...out] as [number, number, number, number];
          expect(Math.min(x1 - x0, y1 - y0)).toBeGreaterThanOrEqual(style.width - near(x1 + y1));
          for (let a = 0; a < r.idx.length; a += 1) {
            const [i, k] = [r.idx[a] as number, r.tick[a] as number];
            const x = tf.indexToScreen(vp, i);
            const y = tf.priceToScreen(vp, 0, k);
            // An hline's time and a vline's price place nothing: each spans the plot on that axis.
            if (kind !== "hline") expect(x >= x0 - near(x) && x <= x1 + near(x), "x").toBe(true);
            if (kind !== "vline") expect(y >= y0 - near(y) && y <= y1 + near(y), "y").toBe(true);
            const t = tf.screenToTime(vp, x); // a bar's open time lands on its centre, both ways
            expect(Math.abs(t - (r.t[a] as number))).toBeLessThan(1e3); // 1 ms
            expect(Math.abs(tf.indexAt(vp.map, t) - i)).toBeLessThan(1e-6);
            expect(Math.abs(tf.screenToPrice(vp, 0, y) - k)).toBeLessThan(0.5);
          }
        } catch (e) {
          throw new Error(`seed ${358_000 + c}: ${(e as Error).message}`);
        }
      }
    },
    120_000,
  );

  it("a hidden drawing has NaN bounds", () => {
    const style = { colour: 0, width: 1, dash: 0 } as const;
    const r = toRecord({ id: "h", kind: "hline", points: [T0, 1e4], style, visible: false });
    screenBounds(random(mulberry32(1), false, false), r, out, 0);
    expect([...out].every(Number.isNaN)).toBe(true);
  });
});
