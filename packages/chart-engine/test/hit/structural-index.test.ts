// E11-S08 unit (BQ-137): the pane, region, bar and level under a point, O(1), and the resolvers.
import { describe, expect, it } from "vitest";
import { StructuralIndex, createStructuralHit } from "../../src/hit/index.js";
import { priceToScreen, screenToIndex } from "../../src/viewport/index.js";
import { hitViewport } from "../../bench/scenes/hit-pick.js";

const layout = {
  panes: [{ id: "main", rect: [0, 0, 1216, 720] as const, priceAxis: [1216, 0, 64, 720] as const }],
  timeAxis: [0, 720, 1216, 24] as const,
};

describe("the structural index", () => {
  const { viewport } = hitViewport();
  const index = new StructuralIndex(viewport, layout);
  const out = createStructuralHit();

  it("the plot answers the bar (floor) and the integer price level of the shared transform", () => {
    const y = priceToScreen(viewport, 0, 1_234);
    expect(index.pickStructural(300, y, out)).toMatchObject({
      paneId: "main",
      pane: 0,
      region: "plot",
      barIndex: screenToIndex(viewport, 300),
      priceLevel: 1_234,
      objectId: null,
    });
  });

  it("the price gutter reports its level, the time axis its bar, elsewhere none", () => {
    expect(index.pickStructural(1_250, priceToScreen(viewport, 0, 500), out)).toMatchObject({
      region: "price",
      priceLevel: 500,
    });
    expect(index.pickStructural(300, 730, out)).toMatchObject({
      region: "time",
      paneId: null,
      barIndex: screenToIndex(viewport, 300),
    });
    expect(index.pickStructural(1_250, 730, out).region).toBe("none");
  });

  it("a pane's resolver names the cell under the plot point, and stops once removed (G-26)", () => {
    const seen: number[] = [];
    const off = index.registerStructural("main", (bar, level) => {
      seen.push(bar, level);
      return level > 1_000 ? `cell:${bar}:${level}` : null;
    });
    const y = priceToScreen(viewport, 0, 1_500);
    const bar = screenToIndex(viewport, 10);
    expect(index.pickStructural(10, y, out).objectId).toBe(`cell:${bar}:1500`);
    expect(index.pickStructural(10, priceToScreen(viewport, 0, 10), out).objectId).toBeNull();
    expect(index.pickStructural(1_250, y, out).objectId).toBeNull(); // the gutter: no resolver
    off();
    off(); // idempotent
    expect(index.pickStructural(10, y, out).objectId).toBeNull();
    expect(seen).toEqual([bar, 1_500, bar, 10]);
  });
});
