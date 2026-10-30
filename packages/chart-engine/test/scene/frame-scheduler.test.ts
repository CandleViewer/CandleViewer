// E11-S01 PR2: the frame scheduler, named after the ticket's Gherkin scenarios (26 §3.2, 06 §4.4).
import { describe, expect, it } from "vitest";
import { DeferClass, Dirty } from "../../src/scene/dirty.js";
import { type Animation, FRAME_STAGES, FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { MutationQueue } from "../../src/scene/mutation-queue.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { FRAME_STAGES as BENCH_STAGES } from "../../bench/instrumentation.mjs";
import { TestClock } from "./test-clock.js";

function build(hooks: ConstructorParameters<typeof FrameScheduler>[2] = {}) {
  const graph = new SceneGraph();
  graph.addPane("p0");
  const series = new NullSeries("s");
  graph.addNode("p0", "series", series);
  const clock = new TestClock();
  const scheduler = new FrameScheduler(graph, clock, hooks);
  return { graph, series, clock, scheduler };
}

/** Exponential momentum decay in closed form per step, so any split of time lands the same. */
class Momentum implements Animation {
  x = 0;
  steps = 0;
  v = 2; // px per ms, decaying with a 120 ms time constant
  step(dtMs: number): boolean {
    const decay = Math.exp(-dtMs / 120);
    this.x += this.v * 120 * (1 - decay);
    this.v *= decay;
    this.steps += 1;
    return Math.abs(this.v * 120) > 0.01;
  }
}

/** Never rests, and re-marks every drawable node each frame (an animating node's re-mark). */
const forever = (graph: SceneGraph): Animation => ({
  step: (): boolean => {
    graph.markViewport();
    return true;
  },
});

describe("Scenario: The loop parks when there is nothing to do", () => {
  it("requests no frame after the last dirty one; a data message or pointer event resumes", () => {
    const { graph, series, clock, scheduler } = build();
    expect([scheduler.parked, clock.requests]).toEqual([true, 0]);
    scheduler.wake();
    scheduler.wake(); // one frame, never two
    expect(clock.tick()).toBe(true);
    expect([series.collects, scheduler.parked, clock.requests]).toEqual([1, true, 1]);
    for (let f = 0; f < 125; f += 1) expect(clock.tick()).toBe(false); // 2 s idle
    expect(clock.requests).toBe(1);
    scheduler.enqueue(() => graph.markData("s")); // a data message
    expect(scheduler.parkedMs).toBe(2000);
    expect(clock.tick()).toBe(true);
    expect([series.collects, series.lastFlags, scheduler.ctx.dt]).toEqual([2, Dirty.DATA, 0]);
    graph.markViewport(); // a pointer event: the input router marks, then wakes
    scheduler.wake();
    expect([clock.tick(), series.lastFlags]).toEqual([true, Dirty.TRANSFORM]);
    expect([clock.requests, clock.doubleRequests, scheduler.parked]).toEqual([3, 0, true]);
    scheduler.wake();
    scheduler.dispose();
    scheduler.wake(); // disposed: latched
    expect([clock.tick(), scheduler.parked]).toEqual([false, true]);
  });

  it("parks once after a frame that woke itself, so the next frame keeps its dt", () => {
    const { clock, scheduler } = build({ input: () => scheduler.frames === 0 && scheduler.wake() });
    scheduler.wake();
    clock.tick();
    expect([clock.tick(20), scheduler.ctx.dt, clock.doubleRequests]).toEqual([true, 20, 0]);
  });
});

describe("Scenario: Data mutations are bounded, not dropped", () => {
  it("applies at most 4 ms of a 12 ms burst per frame, in order, and loses none", () => {
    const { clock, scheduler } = build();
    const applied: number[] = [];
    for (let i = 0; i < 12; i += 1) {
      scheduler.enqueue(() => {
        applied.push(i);
        clock.advance(1); // each costs 1 ms
      });
    }
    const perFrame: number[] = [];
    while (clock.tick()) perFrame.push(scheduler.timings.ms[1] ?? -1);
    expect(perFrame).toEqual([4, 4, 4]); // then it parks: nothing queued, dirty or animating
    expect([applied, scheduler.deferredMutations]).toEqual([[...Array(12).keys()], 0]);
    expect(scheduler.parked).toBe(true);
  });

  it("never cuts an opaque mutation short, and the ring grows in order (BQ-37)", () => {
    const { clock, scheduler } = build();
    const applied: number[] = [];
    scheduler.enqueue(() => {
      applied.push(0);
      clock.advance(6);
    });
    scheduler.enqueue(() => applied.push(1));
    clock.tick();
    expect([applied, scheduler.deferredMutations]).toEqual([[0], 1]);
    const queue = new MutationQueue(2);
    for (let i = 2; i < 7; i += 1) queue.push(() => applied.push(i));
    expect([queue.length, queue.grown, queue.drain(clock, 4)]).toEqual([5, 2, 0]);
    expect(applied).toEqual([0, 2, 3, 4, 5, 6]);
  });
});

describe("Scenario: Animation is time-based, so dropped frames do not change the outcome", () => {
  it("lands within 0.5 px of an undropped run after three dropped frames", () => {
    const run = (drop: boolean): Momentum => {
      const { clock, scheduler } = build();
      const momentum = new Momentum();
      scheduler.wake();
      clock.tick(); // a first frame, so the animation's first dt is a real interval
      scheduler.animate(momentum);
      for (let f = 0; !scheduler.parked; f += 1) {
        if (drop && f === 10) clock.advance(48); // three frames' callbacks never ran
        clock.tick();
      }
      return momentum;
    };
    const [smooth, dropped] = [run(false), run(true)];
    expect(Math.abs(smooth.x - dropped.x)).toBeLessThan(0.5);
    expect([smooth.x > 200, smooth.steps - dropped.steps]).toEqual([true, 3]);
  });
});

describe("Scenario: Sustained over-budget frames trigger a step-down", () => {
  it("requests one LOD level down with the stage timings after the third frame over 16.7 ms", () => {
    let cost = 20;
    const { graph, clock, scheduler } = build({ submit: () => clock.advance(cost) });
    scheduler.animate(forever(graph));
    for (let f = 0; f < 3; f += 1) expect(scheduler.takeNotice() ?? clock.tick()).toBe(true); // none yet
    expect(scheduler.takeNotice()).toBe(scheduler.notice);
    const { code, recoverable, from, to, stage, timings } = scheduler.notice;
    const want = "ENGINE_LOD_STEPDOWN,true,0,1,compositePresent,0,0,0,0,0,0,0,0,20";
    expect(String([code, recoverable, from, to, stage, ...timings])).toBe(want);
    expect(scheduler.takeNotice()).toBeNull();
    clock.tick(); // the fourth frame runs at the new level
    expect([scheduler.ctx.lod, scheduler.shedLevel]).toEqual([1, 1]);
    for (let f = 0; f < 12; f += 1) clock.tick();
    expect([scheduler.lod, scheduler.shedLevel, scheduler.takeNotice()?.to]).toEqual([2, 4, 2]);
    cost = 15; // between 85 % and 100 % of budget: hold
    for (let f = 0; f < 6; f += 1) clock.tick();
    expect(scheduler.shedLevel).toBe(4);
    cost = 1; // under 85 % for 500 ms: one rung back; LOD recovery is E11-S12's
    for (let f = 0; f < 64; f += 1) clock.tick();
    expect([scheduler.shedLevel, scheduler.lod]).toEqual([2, 2]);
    expect(FRAME_STAGES).toEqual(BENCH_STAGES);
  });

  it("holds a rung whose shed work was the cost: no oscillation, one LOD step (BQ-38)", () => {
    const heat = new NullSeries("heat", { deferClass: DeferClass.HEATMAP_CADENCE });
    let last = 0;
    const { graph, clock, scheduler } = build({
      submit: () => clock.advance(heat.collects > last ? 20 : 2),
    });
    graph.addNode("p0", "heatmap", heat);
    scheduler.animate(forever(graph));
    for (let f = 0; f < 120; f += 1, last = heat.collects) clock.tick();
    expect([scheduler.shedLevel, scheduler.lod, heat.collects < 15]).toEqual([1, 1, true]);
  });
});

describe("06 §4.4 deferral order; critical nodes never deferred", () => {
  /** Frames cost 15 ms (between 85 % and 100 % of budget), so the level holds (BQ-38). */
  function ladder(level: number, layoutCost = 15) {
    const { graph, clock, scheduler } = build({ layout: () => clock.advance(layoutCost) });
    const nodes = ([1, 2, 3, 4] as const).map((d) => new NullSeries(`r${d}`, { deferClass: d }));
    const critical = new NullSeries("order-line", { critical: true });
    for (const n of [...nodes, critical]) graph.addNode("p0", "overlays", n);
    scheduler.animate(forever(graph));
    clock.tick();
    scheduler.shedLevel = level;
    const before = [...nodes, critical].map((n) => n.collects);
    for (let f = 0; f < 32; f += 1) clock.tick(1); // 16 ms apart with the layout's 15: 512 ms
    return [...nodes, critical].map((n, i) => n.collects - (before[i] ?? 0));
  }

  it.each([
    [0, [32, 32, 32, 32, 32]],
    [1, [2, 32, 32, 32, 32]], // heatmap every 250 ms
    [2, [2, 1, 32, 32, 32]], // footprint text at least every 500 ms, its flags kept
    [3, [2, 1, 16, 32, 32]], // indicators every second frame
    [4, [2, 1, 16, 1, 32]], // background panes every 500 ms; the order line never waits
  ])("shed level %i collects %j over 32 frames", (level, want) => {
    expect(ladder(level)).toEqual(want);
  });

  it("sheds every rung in-frame when the budget is gone before collect, never a critical node", () => {
    expect(ladder(0, 17)).toEqual([0, 0, 0, 0, 32]);
  });
});
