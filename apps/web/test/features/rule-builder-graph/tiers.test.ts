// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  isOverBudget,
  NODE_BOX,
  SOFT_CAP,
  TIER_A_MAX,
  tierOf,
  zoomBandOf,
} from "../../../src/features/rule-builder-graph/model/tiers.js";

describe("the node-count tier (D03 §8 axis 1)", () => {
  it.each([
    [0, "a"],
    [60, "a"],
    [61, "b"],
    [120, "b"],
    [121, "c"],
    [200, "c"],
  ] as const)("puts %i nodes in Tier %s", (count, tier) => {
    expect(tierOf(count)).toBe(tier);
  });

  it("warns above the 120-node soft cap and never before it", () => {
    expect([TIER_A_MAX, SOFT_CAP]).toEqual([60, 120]);
    expect(isOverBudget(120)).toBe(false);
    expect(isOverBudget(121)).toBe(true);
  });

  it("gives Tier A the minimum card and Tiers B and C the compact one", () => {
    expect(NODE_BOX).toEqual({
      a: { width: 160, height: 40 },
      b: { width: 120, height: 32 },
      c: { width: 120, height: 32 },
    });
  });
});

describe("the zoom band (D03 §8 axis 2)", () => {
  it.each([
    [2, "z-1"],
    [1, "z-1"],
    [0.75, "z-1"],
    [0.74, "z-2"],
    [0.7499, "z-2"],
    [0.5, "z-2"],
    [0.49, "z-3"],
    [0.4999, "z-3"],
    [0.1, "z-3"],
  ] as const)("puts a zoom of %f in band %s", (zoom, band) => {
    expect(zoomBandOf(zoom)).toBe(band);
  });
});
