// B8, the wall-clock half of the `drawings-drag` scene (E14-T03 PR 2, #358 BQ-2: inside the
// existing engine-bench job, no new required check), run ONLY by `vitest --project perf` (no
// coverage). Scenario 1 on the fixed dataset: 100 000 bars, 200 seeded drawings + 50 order lines,
// every one labelled; one drawing dragged for 180 frames (a `patch`, then a frame: collect, encode,
// build, upload, submit). Each frame is timed alone; the p95 is bound at 12 ms (26 §13 B8) and the
// price and footprint stand-ins see no redraw. CPU side on the GL fake and on a silent 2D context:
// the GPU half waits for E11-T08's SwiftShader runner (#391), as every engine-bench scene's does.
import { describe, expect, it } from "vitest";
import { DRAG_FRAMES, DrawingsDragBench } from "../../../bench/scenes/drawings-drag.js";
import { percentile } from "../../../bench/stats.mjs";
import { Canvas2DBackend } from "../../../src/canvas2d/backend.js";
import type { Ctx2DLike } from "../../../src/canvas2d/ctx2d.js";
import type { RenderBackend } from "../../../src/gl/backend.js";
import { GLBackend } from "../../../src/gl/backend.js";
import { FakeGl } from "../../gl/fake-gl.js";
import { budget, why } from "@candleviewer/config/perf-calibration";

const nop = (): undefined => undefined;
/** A 2D context that does nothing (labels included): the timing is the engine's CPU side alone. */
const silent = (): Ctx2DLike => ({
  ...{ fillStyle: "", strokeStyle: "", lineWidth: 1, setLineDash: nop, fillText: nop },
  ...{ clearRect: nop, fillRect: nop, beginPath: nop, rect: nop, moveTo: nop, lineTo: nop },
  ...{ fill: nop, stroke: nop, ellipse: nop },
});

/** 5 timed drags of 180 frames after a warm-up drag: each frame's ms, and the stand-ins' redraws. */
function drag(backend: () => RenderBackend): { p95: number; redraws: number } {
  const frames: number[] = [];
  let redraws = 0;
  for (let r = -1; r < 5; r += 1) {
    const bench = new DrawingsDragBench(100_000, 358, backend());
    const before = bench.price.updates + bench.footprint.updates;
    for (let f = 0; f < DRAG_FRAMES; f += 1) {
      const start = performance.now();
      bench.step(f);
      if (r >= 0) frames.push(performance.now() - start); // run -1 is the warm-up
    }
    redraws += bench.price.updates + bench.footprint.updates - before;
  }
  return { p95: percentile(frames, 95) ?? Number.NaN, redraws };
}

describe("perf budgets: B8 drawings drag (200 drawings + 50 order lines, 100 000 bars)", () => {
  it.each([
    ["the GL fake", () => new GLBackend(new FakeGl(), null)],
    ["Canvas 2D", () => new Canvas2DBackend(silent())],
  ] as const)("%s: a drag frame p95 <= 12 ms; price / footprint redraws 0", (_, backend) => {
    const r = drag(backend);
    expect(r.redraws).toBe(0);
    expect(r.p95, why(r.p95, 12)).toBeLessThanOrEqual(budget(12));
  });
});
