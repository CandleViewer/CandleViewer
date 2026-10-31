// E11-S08 unit: the precise distances against hand-computed cases, and the tolerances (BQ-130).
import { describe, expect, it } from "vitest";
import {
  distToCircle,
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
