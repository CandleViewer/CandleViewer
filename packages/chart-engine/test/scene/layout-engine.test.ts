// E11-S01 PR3: the layout engine and a 600-frame draw-trace determinism run (26 §3.1, §14).
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import { LAYER_ORDER } from "../../src/scene/dirty.js";
import { FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { LayoutEngine } from "../../src/scene/layout-engine.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { TestClock } from "./test-clock.js";

function chart(panes: number, nodes = 0) {
  const graph = new SceneGraph();
  const layout = new LayoutEngine(graph);
  const trace: string[] = [];
  const builder = new BatchBuilder(graph, {
    uploadSubRange: (b, from, to) => trace.push(`u ${b.nodeId} ${from} ${to}`),
  });
  const clock = new TestClock();
  const hooks = { layout: () => layout.run(), build: builder.build.bind(builder) };
  const scheduler = new FrameScheduler(graph, clock, hooks);
  const all: NullSeries[] = [];
  for (let p = 0; p < panes; p += 1) graph.addPane(`p${p}`);
  for (let k = 0; k < nodes; k += 1) all.push(new NullSeries(`n${k}`));
  const frame = (): void => {
    scheduler.wake();
    clock.tick();
  };
  return { graph, layout, builder, trace, clock, scheduler, all, frame };
}

describe("LayoutEngine: pane rects, gutters and height ratios", () => {
  it("recomputes only on LAYOUT: pans, themes and data never relayout", () => {
    const { graph, layout, frame } = chart(1);
    graph.addNode("p0", "series", new NullSeries("s"));
    layout.addPane("p0");
    layout.setSize(800, 600);
    frame();
    for (const mark of [
      () => graph.markViewport(),
      () => graph.markTheme(),
      () => graph.markData("s"),
    ]) {
      mark();
      frame();
    }
    layout.setSize(800, 600); // unchanged: no mark
    frame();
    expect([layout.computes, graph.rebuilds]).toEqual([1, 1]);
    layout.setSize(1000, 600);
    frame();
    expect([layout.computes, layout.panes[0]?.rect[2]]).toEqual([2, 936]);
  });

  it("normalises the ratios over the panes, which tile the plot exactly above the time axis", () => {
    const { layout, frame } = chart(3);
    for (const [p, r] of [
      [0, 1],
      [1, 0.5],
      [2, 0.25],
    ] as const)
      layout.addPane(`p${p}`, r);
    layout.setSize(864, 724);
    frame();
    expect(layout.panes.map((p) => [...p.rect, ...p.priceAxis])).toEqual([
      [0, 0, 800, 400, 800, 0, 64, 400],
      [0, 400, 800, 200, 800, 400, 64, 200],
      [0, 600, 800, 100, 800, 600, 64, 100],
    ]);
    expect(layout.timeAxis).toEqual([0, 700, 800, 24]);
    layout.setHeightRatio("p2", 1);
    frame();
    expect(layout.panes.map((p) => p.rect[3])).toEqual([280, 140, 280]); // sums to 700
    expect(() => layout.addPane("nope")).toThrow(RangeError);
    expect(() => layout.addPane("p0", 0)).toThrow(RangeError);
    expect(() => layout.setHeightRatio("p0", 1.5)).toThrow(RangeError);
    expect(() => layout.setHeightRatio("p9", 1)).toThrow(RangeError);
  });
});

/** A scripted 600-frame session: seeded marks, data patches, resizes and frame gaps; its trace. */
function session(seed: number): string[] {
  const rng = mulberry32(seed);
  const int = (n: number): number => Math.floor(rng() * n);
  const { graph, layout, builder, trace, clock, scheduler, all } = chart(3, 12);
  all.forEach((n, k) => {
    [n.program, n.texture, n.count] = [int(3), int(2), 1 + int(500)];
    graph.addNode(`p${k % 3}`, LAYER_ORDER[int(6)] ?? "series", n);
    if (k < 3) layout.addPane(`p${k}`, 1 / (k + 1));
  });
  for (let f = 0; f < 600; f += 1) {
    const [op, n] = [int(10), all[int(12)] as NullSeries];
    if (op < 6) graph.markViewport();
    if (op === 8) layout.setSize(1280, 700 + int(200));
    if (op === 9)
      builder.patch(n.id, { op: "patch", from: int(n.count), to: n.count, indexShift: 0 });
    if (op === 9) graph.markData(n.id);
    scheduler.wake();
    clock.tick(1 + int(20));
    const list = builder.drawList
      .slice(0, builder.drawCount)
      .map((b) => `${b.nodeId}:${b.program}`);
    trace.push(`f ${f} lod ${scheduler.lod} shed ${scheduler.shedLevel} ${list}`);
  }
  return trace;
}

describe("Determinism: TestClock + seeded RNG", () => {
  it("a 600-frame scripted session produces an identical draw trace across runs", () => {
    const a = session(20261030);
    expect(session(20261030)).toEqual(a);
    expect([a.filter((l) => l.startsWith("f ")).length, a.some((l) => l.startsWith("u "))]).toEqual(
      [600, true],
    );
    expect(session(20261031)).not.toEqual(a); // the trace does depend on the script
  });
});
