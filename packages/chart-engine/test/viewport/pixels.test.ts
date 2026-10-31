// E11-S10 (BQ-143, BQ-144, BQ-151): device-pixel snapping over seeded cases (BQ-81: mulberry32
// loops, no fast-check) at the ticket's ratios, the hairline width and the heatmap cap.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  backingPx,
  HEATMAP_DPR_CAP,
  hairlineDevicePx,
  layerDpr,
  snapHairline,
  snapStroke,
} from "../../src/viewport/pixels.js";

const RATIOS = [1, 1.25, 1.5, 2, 3];
const CASES = 2_000;
/** The device pixels a stroke centred at `cssPx`, `width` device px wide, covers in part. */
const covered = (cssPx: number, dpr: number, width: number): [number, number] => {
  const c = cssPx * dpr;
  return [c - width / 2, c + width / 2];
};

describe("Scenario: Hairlines are crisp at fractional DPI", () => {
  it.each(RATIOS)("snapHairline lands on a device-pixel centre at dpr %s", (dpr) => {
    const rng = mulberry32(447 + dpr * 100);
    for (let i = 0; i < CASES; i += 1) {
      const v = (rng() - 0.2) * 5000;
      const s = snapHairline(v, dpr);
      const d = s * dpr;
      expect(d - Math.floor(d)).toBeCloseTo(0.5, 9);
      expect(Math.abs(s - v)).toBeLessThanOrEqual(0.5 / dpr + 1e-9); // the nearest centre
      expect(snapHairline(s, dpr)).toBeCloseTo(s, 9); // idempotent
    }
  });

  it.each(RATIOS)("a snapped stroke of 1 to 4 device px covers whole pixels at dpr %s", (dpr) => {
    const rng = mulberry32(4470 + dpr * 100);
    for (let i = 0; i < CASES; i += 1) {
      const width = 1 + Math.floor(rng() * 4);
      const [a, b] = covered(snapStroke(rng() * 3000, dpr, width), dpr, width);
      expect(a - Math.round(a)).toBeCloseTo(0, 9);
      expect(Math.round(b) - Math.round(a)).toBe(width); // exactly N pixels, no fringe
    }
  });

  it("a hairline is max(1, floor(dpr)) device px (E11-D02 §4.4, C-42)", () => {
    expect(RATIOS.map(hairlineDevicePx)).toEqual([1, 1, 1, 2, 3]);
    expect(hairlineDevicePx(0.5)).toBe(1);
  });

  it("the backing store is the device-pixel box when known, round(css * dpr) otherwise", () => {
    expect(backingPx(320.4, 1.25)).toBe(401);
    expect(backingPx(320.4, 1.25, 400)).toBe(400);
    expect(backingPx(0, 2)).toBe(0);
    expect(backingPx(10, 2, Number.NaN)).toBe(20);
    expect(backingPx(-3, 1)).toBe(0);
    expect(backingPx(5000, 2, undefined, 8192)).toBe(8192); // F-12's cap seam (G-34)
    expect(backingPx(10, 2, 9000, 8192)).toBe(8192);
  });
});

describe("Scenario: Heatmap layer is capped at 2x", () => {
  it("allocates at an effective ratio of 2 while other layers use 3", () => {
    expect(HEATMAP_DPR_CAP).toBe(2);
    expect(layerDpr(3, HEATMAP_DPR_CAP)).toBe(2);
    expect(layerDpr(1.25, HEATMAP_DPR_CAP)).toBe(1.25);
    expect(layerDpr(3)).toBe(3);
  });
});
