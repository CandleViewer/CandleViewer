// E11-S09 (BQ-2, BQ-3, BQ-10, BQ-23) at the scene level: a pane leaves the graph with only its
// own subtree, chassis nodes span the stack and outlive any pane, the layout tiles the remaining
// panes by their normalised shares, and a dropped batch leaves the draw order and is reused.
import { describe, expect, it } from "vitest";
import { BatchBuilder, LayoutEngine, PooledBatchSink, SceneGraph } from "../../src/scene/index.js";
import { NullSeries } from "../../src/scene/null-series.js";

const series = (id: string) => Object.assign(new NullSeries(id), { count: 4 });

describe("the pane stack in the scene graph", () => {
  it("test_removePane_twoPanes_dropsOnlyThatSubtreeAndReturnsItsContent", () => {
    const g = new SceneGraph();
    g.addPane("a");
    g.addPane("b");
    const a = series("a/s");
    const b = series("b/s");
    g.addNode("a", "series", a);
    g.addNode("b", "series", b);
    expect([a.pane, b.pane]).toEqual(["a", "b"]);
    const before = g.rebuilds;
    g.walk();
    expect(g.removePane("b")).toEqual(["b/s"]);
    expect(g.get("b")).toBeUndefined();
    expect(g.get("b/price-axis")).toBeUndefined();
    expect(g.get("b/s")).toBeUndefined();
    expect(g.get("a/s")).toBe(a);
    const ids = g.walk().map((n) => n.id);
    expect(ids.some((id) => id.startsWith("b"))).toBe(false);
    expect(g.rebuilds).toBeGreaterThan(before);
    expect(() => g.removePane("b")).toThrow(RangeError);
  });

  it("test_addChassis_underAndOver_drawFirstAndLastAndSurviveAPaneRemoval", () => {
    const g = new SceneGraph();
    g.addPane("a");
    const grid = series("grid");
    const cross = series("cross");
    g.addChassis("under", grid);
    g.addChassis("over", cross);
    g.addPane("b"); // a later pane still lands between the chassis layers
    g.addNode("b", "foreground", series("b/s"));
    const ids = g.walk().map((n) => n.id);
    expect(ids.indexOf("grid")).toBeLessThan(ids.indexOf("a"));
    expect(ids.indexOf("cross")).toBeGreaterThan(ids.indexOf("b/s"));
    expect([grid.pane, cross.pane]).toEqual([null, null]);
    g.removePane("a");
    expect([g.get("grid"), g.get("cross")]).toEqual([grid, cross]);
  });

  it("test_layout_removeAndSetWeights_tilesThePlotBySharesSummingToOne", () => {
    const g = new SceneGraph();
    const layout = new LayoutEngine(g);
    for (const id of ["a", "b", "c"]) {
      g.addPane(id);
      layout.addPane(id);
    }
    layout.setSize(464, 324); // a 300 px plot under a 24 px time gutter
    layout.setWeights(
      new Map([
        ["a", 0.6],
        ["b", 0.2],
        ["c", 0.2],
        ["zz", 1],
      ]),
    );
    layout.run();
    expect(layout.panes.map((p) => p.rect[3])).toEqual([180, 60, 60]);
    expect(layout.panes.reduce((s, p) => s + p.share, 0)).toBe(1);
    expect(layout.removePane("b")).toBe(true);
    expect(layout.removePane("b")).toBe(false);
    g.removePane("b");
    layout.run();
    expect(layout.panes.map((p) => [p.id, p.rect[1], p.rect[3]])).toEqual([
      ["a", 0, 225],
      ["c", 225, 75],
    ]);
    expect(layout.panes.map((p) => p.share.toFixed(12))).toEqual([
      "0.750000000000",
      "0.250000000000",
    ]);
    expect(layout.timeAxis[1]).toBe(300); // under the last pane
  });

  it("test_batchBuilder_drop_leavesTheDrawOrderAndReusesTheBatch", () => {
    const g = new SceneGraph();
    g.addPane("a");
    g.addPane("b");
    g.addNode("a", "series", series("a/s"));
    g.addNode("b", "series", series("b/s"));
    const ranges: string[] = [];
    const builder = new BatchBuilder(g, { uploadSubRange: (b) => void ranges.push(b.nodeId) });
    const sink = new PooledBatchSink();
    const step = (): void => {
      sink.reset();
      for (const n of g.walk()) if (n.kind === "content") n.collect(sink);
      builder.build(sink);
    };
    step();
    expect(builder.drawCount).toBe(2);
    const created = builder.pool.created;
    ranges.length = 0;
    g.removePane("b");
    builder.drop("b/s");
    builder.drop("b/s"); // unknown now: nothing
    step();
    expect(builder.drawList.slice(0, builder.drawCount).map((b) => b.nodeId)).toEqual(["a/s"]);
    expect(ranges).toEqual([]); // the surviving batch is not re-uploaded
    g.addPane("c");
    g.addNode("c", "series", series("c/s"));
    step();
    expect(builder.pool.created).toBe(created); // the dropped batch object is reused
    expect(ranges).toEqual(["c/s"]); // only the new ring uploads
  });
});
