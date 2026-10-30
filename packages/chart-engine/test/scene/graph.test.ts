// E11-S01: the node contract, the dirty-propagation matrix, deferral and the pools.
import { describe, expect, it } from "vitest";
import { DeferClass, Dirty, DIRTY_ALL, LAYER_ORDER, shedUpTo } from "../../src/scene/dirty.js";
import type { LayerName } from "../../src/scene/dirty.js";
import { FrameContext } from "../../src/scene/frame-context.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { createPickPool, ObjectPool, PooledBatchSink } from "../../src/scene/pool.js";

/** One pane, a NullSeries `p0:<layer>` in every layer, and a first frame already run. */
function build() {
  const graph = new SceneGraph();
  graph.addPane("p0");
  const nodes = {} as Record<LayerName, NullSeries>;
  for (const layer of LAYER_ORDER) {
    graph.addNode("p0", layer, (nodes[layer] = new NullSeries(`p0:${layer}`)));
  }
  const ctx = new FrameContext();
  const sink = new PooledBatchSink();
  const frame = (t = 0, shed: DeferClass = DeferClass.NONE): void => {
    sink.reset();
    ctx.begin(t, 16.7);
    graph.frame(ctx, sink, shedUpTo(shed));
  };
  frame();
  return { graph, ctx, sink, nodes, frame };
}
const flags = (graph: SceneGraph, id: string): number | undefined => graph.get(id)?.dirty;

describe("the fixed tree (26 §3.1)", () => {
  it("walks Chart, TimeAxis, then each pane's PriceAxis and layers in the fixed order", () => {
    const { graph } = build();
    graph.addPane("p1");
    expect(graph.walk().map((n) => n.id)).toEqual([
      ...["chart", "chart/time-axis", "p0", "p0/price-axis"],
      ...LAYER_ORDER.flatMap((l) => [`p0/${l}`, `p0:${l}`]),
      ...["p1", "p1/price-axis", ...LAYER_ORDER.map((l) => `p1/${l}`)],
    ]);
    const rebuilds = graph.rebuilds; // only a LAYOUT change rebuilds the walk
    graph.markViewport();
    graph.markTheme();
    graph.markData("p0:series");
    graph.walk();
    graph.markResize();
    graph.walk();
    expect(graph.rebuilds).toBe(rebuilds + 1);
  });

  it("orders a layer by zIndex, ties by insertion (BQ-20)", () => {
    const graph = new SceneGraph();
    graph.addPane("pane");
    const zs = { a: 1, b: 0, c: 1, d: -2, e: 0 };
    for (const [id, zIndex] of Object.entries(zs)) {
      graph.addNode("pane", "series", new NullSeries(id, { zIndex }));
    }
    const series = (): string[] => graph.get("pane/series")?.children.map((n) => n.id) ?? [];
    expect(series()).toEqual(["d", "b", "e", "a", "c"]);
    const walked = graph.walk().map((n) => n.id);
    expect(walked.slice(-8, -3)).toEqual(series());
  });

  it("rejects bad ids, a non-finite zIndex and a deferrable critical node", () => {
    const graph = new SceneGraph();
    graph.addPane("p");
    graph.addNode("p", "series", new NullSeries("s"));
    expect(() => graph.addNode("p", "series", new NullSeries("s"))).toThrow(/duplicate/);
    expect(() => graph.addPane("chart")).toThrow(/duplicate/); // the root's id is reserved
    expect(() => graph.addNode("x", "series", new NullSeries("t"))).toThrow(/unknown pane/);
    expect(() => graph.addNode("p", "x" as LayerName, new NullSeries("u"))).toThrow(/layer/);
    expect(() => graph.markResize("x")).toThrow(/unknown pane/);
    expect(() => graph.setVisible("x", false)).toThrow(/unknown node/);
    expect(() => new NullSeries("z", { zIndex: Infinity })).toThrow(/finite/);
    const critical = { critical: true, deferClass: DeferClass.HEATMAP_CADENCE };
    expect(() => new NullSeries("c", critical)).toThrow(/never deferred/);
    expect([graph.markData("p"), graph.markData("gone")]).toEqual([false, false]);
  });
});

describe("dirty propagation matrix (26 §3.1)", () => {
  // [mark, the series, other content, both axes, pane and layer containers]
  it.each([
    ["data", Dirty.DATA, Dirty.NONE, Dirty.NONE, Dirty.NONE],
    ["viewport", Dirty.TRANSFORM, Dirty.TRANSFORM, Dirty.TRANSFORM, Dirty.NONE],
    ["theme", Dirty.STYLE, Dirty.STYLE, Dirty.STYLE, Dirty.NONE],
    ["resize", Dirty.LAYOUT, Dirty.LAYOUT, Dirty.LAYOUT, Dirty.LAYOUT],
  ] as const)("%s marks series %i, content %i, axes %i, containers %i", (mark, ...want) => {
    const { graph, nodes } = build();
    if (mark === "data") graph.markData("p0:series");
    if (mark === "viewport") graph.markViewport();
    if (mark === "theme") graph.markTheme();
    if (mark === "resize") graph.markResize("p0");
    expect([
      nodes.series.dirty,
      nodes.overlays.dirty | nodes.background.dirty | nodes.foreground.dirty,
      flags(graph, "chart/time-axis"),
      flags(graph, "p0/price-axis"),
      flags(graph, "p0"),
      flags(graph, "p0/overlays"),
    ]).toEqual([want[0], want[1], want[2], want[2], want[3], want[3]]);
  });
});

describe("collect and flag clearing", () => {
  it("collects new nodes once, clears their flags, then collects only dirty, visible ones", () => {
    const { graph, nodes, sink, frame } = build();
    expect(LAYER_ORDER.map((l) => nodes[l].lastFlags)).toEqual(LAYER_ORDER.map(() => DIRTY_ALL));
    expect(graph.walk().every((n) => n.dirty === Dirty.NONE)).toBe(true);
    expect(sink.pool.inUse).toBe(LAYER_ORDER.length);
    frame(16);
    expect(sink.pool.inUse).toBe(0);
    graph.markData("p0:series");
    frame(32);
    const counts = [nodes.series.collects, nodes.overlays.collects, nodes.series.updates];
    expect([...counts, nodes.series.cleanCollects]).toEqual([2, 1, 2, 0]);
    // A hidden pane keeps its subtree's flags; they are collected when it is shown again.
    graph.setVisible("p0", false);
    graph.markViewport();
    frame(48);
    expect([nodes.series.dirty, flags(graph, "chart/time-axis")]).toEqual([Dirty.TRANSFORM, 0]);
    graph.setVisible("p0", true);
    frame(64);
    expect(nodes.series.dirty).toBe(Dirty.NONE);
  });
});

describe("deferral under budget pressure (06 §4.4)", () => {
  it("defers rung by rung in 06 §4.4 order and the deferred node keeps its flags", () => {
    const { graph, ctx, frame } = build();
    const byRung = ([1, 2, 3, 4] as const).map((d) => new NullSeries(`r${d}`, { deferClass: d }));
    for (const n of byRung) graph.addNode("p0", "series", n);
    frame(16, DeferClass.INDICATOR_COALESCE);
    expect(byRung.map((n) => n.dirty)).toEqual([DIRTY_ALL, DIRTY_ALL, DIRTY_ALL, 0]);
    expect(ctx.stats.deferred).toBe(3);
    frame(32);
    expect(byRung.map((n) => n.dirty)).toEqual([0, 0, 0, 0]);
  });

  it("critical nodes (order line, DOM-mirror sync) are collected with every rung shed", () => {
    const { graph, frame } = build();
    const orderLine = new NullSeries("order-line", { critical: true });
    const mirror = new NullSeries("dom-mirror-sync", { critical: true });
    graph.addNode("p0", "overlays", orderLine);
    graph.addNode("p0", "foreground", mirror);
    graph.markData("order-line");
    graph.markViewport();
    frame(16, DeferClass.BACKGROUND_PANES);
    expect([orderLine.dirty, mirror.dirty, orderLine.collects]).toEqual([0, 0, 1]);
  });
});

describe("pools", () => {
  it("a pool hands out the same objects in the same order and counts what it creates", () => {
    const zero = (o: { v: number }): number => (o.v = 0);
    const pool = new ObjectPool(() => ({ v: 0 }), zero, 2);
    const taken = [pool.acquire(), pool.acquire(), pool.acquire()];
    taken.forEach((o) => (o.v = 7));
    expect([pool.created, pool.inUse]).toEqual([3, 3]);
    pool.releaseAll();
    const again = [pool.acquire(), pool.acquire(), pool.acquire()];
    expect(again.every((o, i) => o === taken[i])).toBe(true);
    expect([pool.created, ...taken.map((o) => o.v)]).toEqual([3, 0, 0, 0]);
    const picks = createPickPool();
    const hit = Object.assign(picks.acquire(), { nodeId: "s", index: 4, distancePx: 1.5 });
    picks.releaseAll();
    expect(picks.acquire()).toBe(hit);
    expect([hit, picks.created]).toEqual([{ nodeId: "", index: -1, distancePx: 0 }, 8]);
  });
});
