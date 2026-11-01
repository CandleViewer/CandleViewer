import { describe, expect, it } from "vitest";
import {
  placeTooltip,
  TOOLTIP_DOCK_SLACK_PX,
  TOOLTIP_EDGE_PX,
  TOOLTIP_OFFSET_PX,
} from "../../src/chart/placeTooltip";

const box = { width: 220, height: 120 };
const plot = { width: 800, height: 500 };

describe("placeTooltip", () => {
  it("sits 16 px right of and below the anchor by default", () => {
    expect(placeTooltip({ x: 100, y: 100 }, box, plot)).toEqual({
      x: 100 + TOOLTIP_OFFSET_PX,
      y: 100 + TOOLTIP_OFFSET_PX,
      docked: false,
      flippedX: false,
      flippedY: false,
    });
  });

  it("flips per axis at the plot's right and bottom edges", () => {
    const r = placeTooltip({ x: 700, y: 100 }, box, plot);
    expect(r).toMatchObject({ flippedX: true, flippedY: false, x: 700 - 16 - 220, y: 116 });
    const b = placeTooltip({ x: 100, y: 450 }, box, plot);
    expect(b).toMatchObject({ flippedX: false, flippedY: true, x: 116, y: 450 - 16 - 120 });
    expect(placeTooltip({ x: 790, y: 490 }, box, plot)).toMatchObject({
      flippedX: true,
      flippedY: true,
    });
  });

  it("clamps into the plot when neither side fits", () => {
    const r = placeTooltip(
      { x: 100, y: 250 },
      { width: 220, height: 120 },
      { width: 250, height: 300 },
    );
    expect(r.x).toBeGreaterThanOrEqual(0);
    expect(r.x + 220).toBeLessThanOrEqual(250);
  });

  it("docks top-right when the pane is shorter than the box plus 32 px", () => {
    const r = placeTooltip({ x: 100, y: 40 }, box, {
      width: 800,
      height: 120 + TOOLTIP_DOCK_SLACK_PX - 1,
    });
    expect(r).toEqual({
      x: 800 - 220 - TOOLTIP_EDGE_PX,
      y: 8,
      docked: true,
      flippedX: false,
      flippedY: false,
    });
    expect(placeTooltip({ x: 100, y: 40 }, box, { width: 800, height: 152 }).docked).toBe(false);
  });

  it("property: stays inside the plot and never covers the anchor, over seeded sizes and anchors", () => {
    let seed = 20261101;
    const rnd = (lo: number, hi: number): number => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return lo + (seed / 2 ** 32) * (hi - lo);
    };
    for (let i = 0; i < 2000; i += 1) {
      const p = { width: rnd(300, 1600), height: rnd(60, 900) };
      const b = { width: rnd(200, 260), height: rnd(60, 200) };
      const a = { x: rnd(0, p.width), y: rnd(0, p.height) };
      const r = placeTooltip(a, b, p);
      if (b.width <= p.width && b.height <= p.height) {
        expect(r.x).toBeGreaterThanOrEqual(0);
        expect(r.y).toBeGreaterThanOrEqual(0);
        expect(r.x + b.width).toBeLessThanOrEqual(p.width + 1e-9);
        expect(r.y + b.height).toBeLessThanOrEqual(p.height + 1e-9);
      }
      if (
        !r.docked &&
        p.width >= 2 * (b.width + TOOLTIP_OFFSET_PX) &&
        p.height >= 2 * (b.height + TOOLTIP_OFFSET_PX)
      ) {
        const covers = a.x >= r.x && a.x <= r.x + b.width && a.y >= r.y && a.y <= r.y + b.height;
        expect(covers).toBe(false);
      }
    }
  });
});
