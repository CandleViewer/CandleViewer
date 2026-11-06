// E11-S08 unit: the precise distances against hand-computed cases, and the tolerances (BQ-130).
import { describe, expect, it } from "vitest";
import {
  clipToBox,
  distToCircle,
  distToEllipse,
  distToRay,
  distToRect,
  distToSegment,
  toleranceFor,
} from "../../src/hit/geometry.js";

describe("hit geometry", () => {
  it("distance to a segment: perpendicular inside, to the nearer end outside", () => {
    expect(distToSegment(5, 3, 0, 0, 10, 0)).toBe(3);
    expect(distToSegment(13, 4, 0, 0, 10, 0)).toBe(5);
    expect(distToSegment(-3, -4, 0, 0, 10, 0)).toBe(5);
    expect(distToSegment(0, 0, 0, 0, 3, 4)).toBe(0);
    expect(distToSegment(3, 4, 1, 1, 1, 1)).toBeCloseTo(Math.hypot(2, 3), 12); // a point
  });

  it("a ray is unbounded past its second point, bounded behind its origin", () => {
    expect(distToRay(1_000, 2, 0, 0, 10, 0)).toBe(2);
    expect(distToRay(-3, 4, 0, 0, 10, 0)).toBe(5);
  });

  it("a rect is 0 over its fill and the distance to its edge outside, corners in any order", () => {
    expect(distToRect(5, 5, 10, 10, 0, 0)).toBe(0);
    expect(distToRect(13, 5, 0, 0, 10, 10)).toBe(3);
    expect(distToRect(13, 14, 0, 0, 10, 10)).toBe(5);
  });

  it("a circle is 0 inside its radius, the distance to its rim outside", () => {
    expect(distToCircle(1, 1, 0, 0, 4)).toBe(0);
    expect(distToCircle(0, 10, 0, 0, 4)).toBe(6);
  });

  it("a non-finite projection is +Infinity: it never picks", () => {
    expect(distToSegment(0, 0, Number.NaN, 0, 1, 1)).toBe(Infinity);
    expect(distToRect(0, 0, 0, Number.NaN, 1, 1)).toBe(Infinity);
    expect(distToCircle(0, 0, 0, 0, Number.NaN)).toBe(Infinity);
  });

  it("tolerance comes from the pointer type: mouse and pen 10 px, touch 16 px", () => {
    expect([toleranceFor("mouse"), toleranceFor("pen"), toleranceFor("touch")]).toEqual([
      10, 10, 16,
    ]);
  });
});

describe("E14-T04 precise tests", () => {
  const out = new Float64Array(4);
  const box = [0, 0, 100, 50] as const;

  it("an ellipse is 0 inside, its rim distance outside, never under the true distance", () => {
    expect(distToEllipse(50, 25, 0, 0, 100, 50)).toBe(0);
    expect(distToEllipse(110, 25, 0, 0, 100, 50)).toBeCloseTo(10, 12); // on an axis: exact
    expect(distToEllipse(50, -5, 100, 50, 0, 0)).toBeCloseTo(5, 12); // corners in any order
    // Off-axis the rim point along the centre ray is on the ellipse: never closer than drawn.
    const d = distToEllipse(110, 60, 0, 0, 100, 50);
    expect(d).toBeGreaterThan(0);
    expect(d).toBeLessThan(Math.hypot(110 - 50, 60 - 25));
    expect(distToEllipse(5, 3, 0, 0, 10, 0)).toBe(3); // a flat box is its segment
  });

  it("clips a segment, a ray and an extended line to the box", () => {
    expect(clipToBox(-50, 25, 150, 25, 0, 1, box, out)).toBe(true);
    expect([...out]).toEqual([0, 25, 100, 25]);
    expect(clipToBox(10, 10, 20, 10, 0, Infinity, box, out)).toBe(true); // a ray, to the edge
    expect([...out]).toEqual([10, 10, 100, 10]);
    expect(clipToBox(10, 10, 20, 10, -Infinity, Infinity, box, out)).toBe(true);
    expect([...out]).toEqual([0, 10, 100, 10]);
    expect(clipToBox(-50, 60, 150, 60, -Infinity, Infinity, box, out)).toBe(false); // above
    expect(clipToBox(200, 10, 300, 10, 0, Infinity, box, out)).toBe(false); // ray away from it
    expect(clipToBox(5, 5, 5, 5, -Infinity, Infinity, box, out)).toBe(false); // a point line
  });
});
