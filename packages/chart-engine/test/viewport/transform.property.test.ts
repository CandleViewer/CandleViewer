// E11-S03 properties over 10 000 seeded cases each (BQ-81: mulberry32 loops, the BQ-21 precedent,
// no fast-check). A failure prints its seed (BASE + case) so the case replays alone.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { bars } from "../../bench/scenes/pan-zero-upload.js";
import { BarStore } from "../../src/model/BarStore.js";
import {
  ChartViewport,
  indexToScreen,
  priceToScreen,
  screenToIndex,
  screenToPrice,
} from "../../src/viewport/index.js";

const CASES = 10_000;
const BASE = 335_000;
const N = 5_000;
const store = new BarStore({ maxBars: N });
store.append(bars(N, 1_790_000_000_000_000));

/** A random viewport over the loaded range: any width, spacing, offset and price window. */
function random(rng: () => number): ChartViewport {
  const vp = new ChartViewport(store);
  vp.setSize(1 + rng() * 3839, 50 + rng() * 2000, 1 + Math.floor(rng() * 3));
  vp.setPanePlot(0, rng() * 40, 50 + rng() * 2000);
  vp.zoomAt(0, 0.05 + rng() * 40); // from 6 px: spacing anywhere in [0.3, 200] px
  vp.pan(-rng() * N * vp.barSpacing);
  const low = (rng() - 0.5) * 2e6; // ticks from priceOrigin, both signs
  vp.setPriceRange(0, low, low + 1 + rng() * 5e4);
  return vp;
}

function forAll(check: (rng: () => number, vp: ChartViewport) => void): void {
  for (let c = 0; c < CASES; c += 1) {
    const rng = mulberry32(BASE + c);
    try {
      check(rng, random(rng));
    } catch (e) {
      throw new Error(`seed ${BASE + c}: ${(e as Error).message}`);
    }
  }
}

describe("Scenario: Round-trips are exact", () => {
  it("screenToIndex(indexToScreen(i)) === i for 10 000 cases", () => {
    forAll((rng, vp) => {
      const i = Math.floor(rng() * N);
      expect(screenToIndex(vp, indexToScreen(vp, i))).toBe(i);
    });
  });

  it("screenToPrice(priceToScreen(p)) is within half a tick for 10 000 cases", () => {
    forAll((rng, vp) => {
      const pane = vp.panes[0];
      const p = (pane?.priceLow ?? 0) + rng() * ((pane?.priceHigh ?? 0) - (pane?.priceLow ?? 0));
      const tick = Math.round(p);
      expect(Math.abs(screenToPrice(vp, 0, priceToScreen(vp, 0, tick)) - tick)).toBeLessThan(0.5);
    });
  });

  it("priceToScreen is monotone decreasing in price for 10 000 cases", () => {
    forAll((rng, vp) => {
      const a = Math.round((rng() - 0.5) * 4e6);
      expect(priceToScreen(vp, 0, a + 1)).toBeLessThan(priceToScreen(vp, 0, a));
    });
  });

  it("zoomAt keeps the anchor's index for random anchors and factors in [0.1, 10]", () => {
    forAll((rng, vp) => {
      const x = rng() * vp.plotWidth;
      const at = x / vp.barSpacing + vp.leftIndex;
      const factor = 0.1 + rng() * 9.9;
      vp.zoomAt(x, factor);
      const free = at - x / vp.barSpacing; // the left edge that keeps the anchor
      if (free > N - 1 || free < 1 - vp.visibleBars) {
        // BQ-70: the rightOffset clamp wins and the anchor yields to it.
        expect(vp.leftIndex).toBe(free > N - 1 ? N - 1 : 1 - vp.visibleBars);
      } else expect(Math.abs(indexToScreen(vp, at - 0.5) - x)).toBeLessThan(1e-6);
    });
  });
});
