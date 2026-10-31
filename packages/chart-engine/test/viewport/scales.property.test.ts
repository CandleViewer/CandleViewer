// E11-S05 properties over 10 000 seeded cases each (BQ-81: mulberry32 loops, no fast-check). In
// every mode × invert: round-trip within half a tick, strictly monotone, never NaN or Infinity.
// The BQ-113 rider: the log shader path (its Math.fround stand-in) stays within 0.01 px of the
// float64 transform over BTC-scale and sub-cent tick series. A failure prints its seed.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  ChartViewport,
  createPaneUniforms,
  type PaneTransform,
  priceToScreen,
  screenToPrice,
  writePaneUniforms,
} from "../../src/viewport/index.js";
import { shaderY } from "./shader-stand-in.js";

const CASES = 10_000;
const BASE = 386_000;
const MODES = ["linear", "log", "percent", "indexed"] as const;

function forAll(check: (rng: () => number) => void): void {
  for (let c = 0; c < CASES; c += 1) {
    const rng = mulberry32(BASE + c);
    try {
      check(rng);
    } catch (e) {
      throw new Error(`seed ${BASE + c}: ${(e as Error).message}`);
    }
  }
}

/** A BTC-scale (0.1 to 0.5 ticks, 1k to 120k) or a sub-cent (1e-6 ticks, 0.001 to 2) series. */
function series(rng: () => number): { tick: number; low: number; high: number } {
  if (rng() < 0.5) {
    const tick = [0.1, 0.5][Math.floor(rng() * 2)] as number;
    const lowPrice = 1_000 + rng() * 100_000;
    const spanTicks = 50 + rng() * Math.min(1e6, (lowPrice * 9) / tick); // 50 ticks to ×10
    return { tick, low: lowPrice / tick, high: lowPrice / tick + spanTicks };
  }
  const lowPrice = 0.001 + rng() * 2;
  const low = lowPrice / 1e-6;
  return { tick: 1e-6, low, high: low + 50 + rng() * Math.min(1e6, low * 9) };
}

function random(rng: () => number, mode: PaneTransform["scaleMode"], inverted: boolean) {
  const s = series(rng);
  const vp = new ChartViewport();
  const dpr = 1 + Math.floor(rng() * 2);
  vp.setSize(1920, 1000, dpr);
  vp.setPanePlot(0, rng() * 40, 200 + rng() * 800);
  vp.setPriceInfo(0, 0, s.tick);
  (vp.panes[0] as PaneTransform).logReason = null;
  vp.setScale(0, { mode, inverted });
  vp.setPriceRange(0, s.low, s.high);
  return { vp, s, dpr };
}

describe("every mode × invert (10 000 cases each)", () => {
  it.each(MODES.flatMap((m) => [false, true].map((inv) => [m, inv] as const)))(
    "%s, inverted %s: round-trip within half a tick, strictly monotone, always finite",
    (mode, inverted) => {
      forAll((rng) => {
        const { vp, s } = random(rng, mode, inverted);
        const a = s.low + rng() * (s.high - s.low);
        const b = a + 1 + rng() * (s.high - a);
        const ya = priceToScreen(vp, 0, a);
        const yb = priceToScreen(vp, 0, b);
        expect(Number.isFinite(ya) && Number.isFinite(yb)).toBe(true);
        expect(Math.abs(screenToPrice(vp, 0, ya) - a)).toBeLessThanOrEqual(0.5);
        expect(inverted ? yb > ya : yb < ya).toBe(true);
      });
    },
    60_000,
  );
});

describe("BQ-113 rider: the log shader path within 0.01 px (10 000 cases)", () => {
  it("BTC-scale and sub-cent series, any dpr, in and around the window, inverted or not", () => {
    let worst = 0;
    forAll((rng) => {
      const { vp, s, dpr } = random(rng, "log", rng() < 0.3);
      const block = createPaneUniforms();
      writePaneUniforms(vp, 0, block);
      expect(block.floats[7]).toBe(1);
      const span = s.high - s.low;
      const tick = Math.round(s.low - 0.1 * span + rng() * 1.2 * span);
      const err = Math.abs(shaderY(tick, block, dpr) - priceToScreen(vp, 0, tick));
      worst = Math.max(worst, err);
      expect(err).toBeLessThanOrEqual(0.01);
    });
    expect(worst).toBeGreaterThan(0); // the stand-in is float32, not a copy of the float64 path
  }, 60_000);
});
