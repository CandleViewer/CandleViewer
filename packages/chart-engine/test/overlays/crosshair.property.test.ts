// E11-S07 properties (C-38: seeded mulberry32 loops; fast-check is not in the lockfile, BQ-30).
// Over 5 000 seeded cases across bar spacings 0.05..200 px and fractional left indices: the
// vertical line lands exactly on the centre of the bar under the pointer (never more than half
// a bar away), the bar is the floor of the index under x, and with the magnet off the tick is
// the nearest one to y. Strong always snaps to the field nearest in y. A failure prints its seed.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { createCrosshair, resolvePointer } from "../../src/overlays/crosshair.js";
import {
  BAR_SPACING_MAX,
  BAR_SPACING_MIN,
  indexToScreen,
  priceToScreen,
  screenToPrice,
} from "../../src/viewport/index.js";
import { source, viewport } from "./fixture.js";

const CASES = 5_000;
const BASE = 388_000;

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

describe("crosshair properties", () => {
  it("test_resolvePointer_anySpacing_barCentreWithinHalfBar", () => {
    const s = createCrosshair();
    forAll((rng) => {
      const spacing = BAR_SPACING_MIN + rng() ** 3 * (BAR_SPACING_MAX - BAR_SPACING_MIN);
      const vp = viewport(1000, spacing, rng() * 400 - 50);
      const x = rng() * vp.plotWidth;
      const y = rng() * 600;
      resolvePointer(s, vp, 0, null, x, y, "off");
      expect(s.bar).toBe(Math.floor(x / spacing + vp.leftIndex));
      expect(s.x).toBe(indexToScreen(vp, s.bar));
      expect(Math.abs(s.x - x)).toBeLessThanOrEqual(spacing / 2 + 1e-9 * spacing);
      expect(s.tick).toBe(Math.round(screenToPrice(vp, 0, y)));
      expect(s.y).toBe(y);
    });
  });

  it("test_strongMagnet_anyPointer_snapsToNearestFieldInY", () => {
    const s = createCrosshair();
    const bars = source(200);
    forAll((rng) => {
      const vp = viewport(200, 4 + rng() * 40, rng() * 20);
      const x = rng() * vp.plotWidth;
      const y = rng() * 600;
      resolvePointer(s, vp, 0, bars, x, y, "strong");
      if (s.bar < 0 || s.bar >= bars.length) {
        expect(s.snap).toBeNull();
        return;
      }
      expect(s.snap).not.toBeNull();
      const d = Math.abs(s.y - y);
      for (const col of [bars.open, bars.high, bars.low, bars.close]) {
        expect(d).toBeLessThanOrEqual(Math.abs(priceToScreen(vp, 0, col[s.bar] as number) - y));
      }
      expect(s.y).toBe(priceToScreen(vp, 0, s.tick));
    });
  });
});
