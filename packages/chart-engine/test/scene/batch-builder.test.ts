// E11-S01 PR3: the batch builder (26 §3.1/§3.2); the pan scenario is the pan-zero-upload scene's.
import { describe, expect, it } from "vitest";
import { bars } from "../../bench/scenes/pan-zero-upload.js";
import { BarStore } from "../../src/model/BarStore.js";
import { BatchBuilder, type RetainedBatch } from "../../src/scene/batch-builder.js";
import { FrameContext } from "../../src/scene/frame-context.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { PooledBatchSink } from "../../src/scene/pool.js";

function setup() {
  const graph = new SceneGraph();
  graph.addPane("p0");
  graph.addPane("p1");
  const uploads: string[] = [];
  const builder = new BatchBuilder(graph, {
    uploadSubRange: (b, from, to) => uploads.push(`${b.nodeId}[${from},${to})`),
  });
  const ctx = new FrameContext();
  const sink = new PooledBatchSink(4);
  const frame = (): readonly string[] => {
    sink.reset();
    ctx.begin(0, 16.7);
    graph.frame(ctx, sink);
    builder.build(sink);
    return builder.drawList.slice(0, builder.drawCount).map((b: RetainedBatch) => b.nodeId);
  };
  return { graph, builder, uploads, frame };
}

describe("BatchBuilder: sub-range patches", () => {
  it("an empty range adds nothing: [4, 4) then [0, 0) uploads nothing (E12-S06 regression)", () => {
    const { graph, builder, uploads, frame } = setup();
    const store = new BarStore({ maxBars: 64, initialCapacity: 64 });
    const s = new NullSeries("s");
    graph.addNode("p0", "series", s);
    s.count = store.append(bars(4)).to;
    frame();
    expect(uploads.splice(0)).toEqual(["s[0,4)"]);
    builder.patch("s", store.append(bars(0, store.indexToTime(3) + 60e6))); // [4, 4)
    builder.patch("s", store.prepend(bars(0))); // [0, 0)
    graph.markData("s");
    frame();
    expect(uploads.splice(0)).toEqual([]);
    builder.patch("s", store.patch(2, { ...bars(1, store.indexToTime(2)) })); // [2, 3)
    builder.patch("s", store.append(bars(0, store.indexToTime(3) + 60e6))); // [4, 4)
    graph.markData("s");
    frame();
    expect(uploads.splice(0)).toEqual(["s[2,3)"]);
  });

  it("uploads only the range each store mutation touched, rebased, once per frame", () => {
    const { graph, builder, uploads, frame } = setup();
    const store = new BarStore({ maxBars: 64, initialCapacity: 64 });
    const s = new NullSeries("s");
    graph.addNode("p0", "series", s);
    s.count = store.append(bars(10)).to;
    frame();
    expect(uploads.splice(0)).toEqual(["s[0,10)"]); // a new batch: in full, once
    const last = store.indexToTime(9);
    builder.patch("s", store.append(bars(2, last + 60e6)));
    builder.patch("s", store.patch(11, bars(1, last + 120e6)));
    graph.markData("s");
    frame();
    expect(uploads.splice(0)).toEqual(["s[10,12)"]); // the append and the live-bar patch, merged
    builder.patch("s", store.append(bars(1, last + 180e6)));
    builder.patch("s", store.prepend(bars(3, store.indexToTime(0) - 240e6))); // rebases by +3
    frame();
    expect(uploads.splice(0)).toEqual(["s[0,16)"]);
    builder.patch("s", store.append(bars(60, store.indexToTime(15) + 60e6))); // evicts 12
    frame();
    expect(uploads.splice(0)).toEqual(["s[4,64)"]);
    builder.patch("s", store.patch(5, bars(1, store.indexToTime(5))));
    builder.patch("s", store.replace(bars(5)));
    builder.patch("absent", store.patch(0, bars(1, store.indexToTime(0)))); // no batch: ignored
    graph.markViewport();
    frame();
    expect(uploads.splice(0)).toEqual(["s[0,5)"]); // a snapshot drops what it replaced
    graph.markViewport();
    frame();
    expect(uploads).toEqual([]); // a pan: nothing
  });
});

describe("BatchBuilder: the draw list", () => {
  it("is sorted by layer, then program, then texture; ties keep the walk (zIndex) order", () => {
    const { graph, frame } = setup();
    const rows = [
      ["p1", "a1", 0, 0],
      ["p0", "b2", 0, 0],
      ["p0", "c3", 2, 1],
      ["p0", "d4", 1, 9],
    ];
    const nodes = [...rows, ["p0", "e5", 1, 3], ["p0", "f6", 1, 3]].map(([pane, id, p, t]) => {
      const n = new NullSeries(`${id}`, { zIndex: Number(`${id}`.slice(1)) });
      [n.program, n.texture] = [Number(p), Number(t)];
      graph.addNode(`${pane}`, id === "b2" ? "overlays" : "series", n);
      return n;
    });
    expect(frame()).toEqual(["e5", "f6", "d4", "c3", "b2", "a1"]);
    (nodes[4] as NullSeries).program = 3; // a program change re-sorts
    graph.markData("e5");
    expect(frame()).toEqual(["f6", "d4", "c3", "e5", "b2", "a1"]);
  });

  it("drops hidden nodes and hidden panes from the draw list, keeping their batches", () => {
    const { graph, builder, frame } = setup();
    for (const id of ["x", "y", "z"])
      graph.addNode(id === "x" ? "p0" : "p1", "series", new NullSeries(id));
    expect(frame()).toEqual(["x", "y", "z"]);
    graph.setVisible("p1", false);
    graph.setVisible("x", false);
    expect(frame()).toEqual([]);
    graph.setVisible("p1", true);
    expect(frame()).toEqual(["y", "z"]);
    expect(builder.pool.created).toBe(16); // the prewarm: three batches, no growth
  });
});
