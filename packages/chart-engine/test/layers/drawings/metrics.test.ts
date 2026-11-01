// E14-T03 PR 2: `engine_drawing_*` on the drawings node (ticket Observability): the layer-time
// histogram's buckets under an injected clock, the drawing count, the instance uploads a drag adds
// (its segment and its label's glyphs, nothing else) and the label draw (≤ 1 a pane).
import { describe, expect, it } from "vitest";
import { DRAG_FRAMES, DrawingsDragBench } from "../../../bench/scenes/drawings-drag.js";
import { DrawingCounters, LAYER_MS_BUCKETS } from "../../../src/layers/drawings/metrics.js";

describe("engine_drawing_* counters", () => {
  it("files each layer time in the first bucket at or above it; the last bucket is open", () => {
    const c = new DrawingCounters();
    for (const ms of [0, 0.1, 0.11, 3, 12, 12.5, 1e9]) c.observe(ms);
    const at = (ms: number): number => LAYER_MS_BUCKETS.findIndex((b) => ms <= b);
    expect([...c.layerFrameHistogram]).toEqual(
      LAYER_MS_BUCKETS.map(
        (_, i) => [0, 0.1, 0.11, 3, 12, 12.5, 1e9].filter((m) => at(m) === i).length,
      ),
    );
    expect(c.layerFrameMs).toBe(1e9);
    expect(c).toEqual({
      layerFrameHistogram: c.layerFrameHistogram,
      count: 0,
      layerFrameMs: 1e9,
      instanceUploads: 0,
      textDrawCalls: 0,
      tokenFallbacks: 0,
      missingToken: null,
    });
  });

  it("the B8 drag: 250 drawings, each frame one segment and 6 glyphs uploaded, one label draw", () => {
    const bench = new DrawingsDragBench();
    let t = 0;
    bench.drawings.now = () => (t += 0.5); // each update reads it twice: 0.5 ms a frame
    const first = bench.drawings.metrics().instanceUploads;
    bench.run();
    const m = bench.drawings.metrics();
    expect([m.count, m.instanceUploads - first, m.textDrawCalls]).toEqual([
      250,
      DRAG_FRAMES * (1 + 6),
      1,
    ]);
    expect(m.layerFrameMs).toBe(0.5);
    const half = LAYER_MS_BUCKETS.findIndex((b) => 0.5 <= b);
    expect(bench.drawings.counters.layerFrameHistogram[half]).toBe(DRAG_FRAMES);
  });
});
