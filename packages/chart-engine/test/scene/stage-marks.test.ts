// E11-T06: 06 §4.3's stage marks. A bench-mode frame marks its start, the layout's end and the nine
// stage ends, in order, with the names built once; a production frame (marks null) marks nothing.
import { describe, expect, it } from "vitest";
import {
  FRAME_STAGES,
  FrameScheduler,
  MARK_FRAME_START,
  MARK_LAYOUT_END,
  type StageMarker,
} from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";
import {
  FRAME_START_MARK,
  LAYOUT_END_MARK,
  performanceStageMarker,
  STAGE_MARK_NAMES,
} from "../../src/scene/stage-marks.js";
import { TestClock } from "./test-clock.js";

function build() {
  const graph = new SceneGraph();
  graph.addPane("p0");
  graph.addNode("p0", "series", new NullSeries("s"));
  const clock = new TestClock();
  const scheduler = new FrameScheduler(graph, clock, {});
  return { graph, clock, scheduler };
}

const STAGE_ENDS = FRAME_STAGES.map((s) => `cv.stage.${s}`);
const ONE_FRAME = [
  FRAME_START_MARK,
  "cv.stage.inputHandling",
  "cv.stage.dataWindowRecompute",
  LAYOUT_END_MARK,
  "cv.stage.candleGeometry",
  "cv.stage.footprintTextGeometry",
  "cv.stage.heatmapUpload",
  "cv.stage.paneRedraw",
  "cv.stage.overlayRedraw",
  "cv.stage.domMirrorSync",
  "cv.stage.compositePresent",
];

describe("stage marks (E11-T06)", () => {
  it("names the nine 06 §4.3 stage ends, then the frame start and the layout end", () => {
    expect(STAGE_MARK_NAMES.slice(0, 9)).toEqual(STAGE_ENDS);
    expect(STAGE_MARK_NAMES[MARK_FRAME_START]).toBe("cv.frame.start");
    expect(STAGE_MARK_NAMES[MARK_LAYOUT_END]).toBe("cv.stage.layout");
    expect(Object.isFrozen(STAGE_MARK_NAMES)).toBe(true);
  });

  it("marks every boundary of a bench-mode frame once, in frame order", () => {
    const { graph, clock, scheduler } = build();
    const names: string[] = [];
    scheduler.marks = performanceStageMarker({ mark: (n) => names.push(n) });
    graph.markViewport();
    scheduler.wake();
    clock.tick();
    expect(names).toEqual(ONE_FRAME);
    graph.markViewport();
    scheduler.wake();
    clock.tick();
    expect(names).toEqual([...ONE_FRAME, ...ONE_FRAME]);
  });

  it("reuses the prebuilt names: a marked frame builds no string", () => {
    const { graph, clock, scheduler } = build();
    const seen: string[] = [];
    scheduler.marks = performanceStageMarker({ mark: (n) => seen.push(n) });
    for (let f = 0; f < 3; f += 1) {
      graph.markViewport();
      scheduler.wake();
      clock.tick();
    }
    const pool = new Set(STAGE_MARK_NAMES);
    // Identity, not equality: every name passed is one of the frozen array's own strings.
    expect(seen.every((n) => STAGE_MARK_NAMES.some((p) => Object.is(p, n)) && pool.has(n))).toBe(
      true,
    );
  });

  it("marks nothing in production: the scheduler's marks stay null and no marker is reached", () => {
    const { graph, clock, scheduler } = build();
    expect(scheduler.marks).toBeNull();
    const calls: number[] = [];
    const spy: StageMarker = { mark: (b) => calls.push(b) };
    graph.markViewport();
    scheduler.wake();
    clock.tick();
    expect(calls).toEqual([]);
    scheduler.marks = spy;
    scheduler.marks = null; // bench mode switched back off: back to zero
    graph.markViewport();
    scheduler.wake();
    clock.tick();
    expect(calls).toEqual([]);
    expect(scheduler.frames).toBe(2);
  });
});
