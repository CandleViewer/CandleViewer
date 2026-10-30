// E11-S01 PR2, 10 000 seeded cases (mulberry32, BQ-21) of random marks, bursts and costs: no mutation
// lost, reordered or started past the clamp, no double request, no critical node deferred, the shed
// level moves one rung at a time, and with the pressure off it drains, collects and parks.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { DeferClass, Dirty, LAYER_ORDER } from "../../src/scene/dirty.js";
import { FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { TestClock } from "./test-clock.js";

const BASE_SEED = 20261030;
const seen = { shed: 0, carried: 0, stepDowns: 0 }; // each path must run

function runCase(seed: number): string | null {
  const rng = mulberry32(seed);
  const int = (n: number): number => Math.floor(rng() * n);
  const graph = new SceneGraph();
  const clock = new TestClock();
  let cost = 0; // the submit stage's cost this frame
  const scheduler = new FrameScheduler(graph, clock, { submit: () => clock.advance(cost) });
  const nodes: NullSeries[] = [];
  for (let p = 0, panes = 1 + int(3); p < panes; p += 1) {
    graph.addPane(`p${p}`);
    for (let k = 1 + int(4); k > 0; k -= 1) {
      const critical = rng() < 0.2;
      const deferClass = critical ? DeferClass.NONE : (int(5) as DeferClass);
      const node = new NullSeries(`p${p}:${k}`, { critical, deferClass });
      graph.addNode(`p${p}`, LAYER_ORDER[int(6)] ?? "series", node);
      nodes.push(node);
    }
  }
  const applied: number[] = [];
  let queued = 0;
  let [late, drainStart, lastFrames, level] = [0, 0, -1, 0]; // late: started at or after the clamp
  for (let s = 0; s < 24; s += 1) {
    const op = int(4);
    if (op === 0) graph.markViewport();
    if (op === 1) graph.markData((nodes[int(nodes.length)] as NullSeries).id);
    if (op <= 1) scheduler.wake();
    if (op === 2) {
      for (let n = int(8); n > 0; n -= 1) {
        const [id, ms] = [queued++, int(4)];
        scheduler.enqueue(() => {
          if (scheduler.frames !== lastFrames) drainStart = clock.t; // the frame's first mutation
          lastFrames = scheduler.frames;
          if (clock.t - drainStart >= scheduler.drainMs) late += 1;
          applied.push(id);
          clock.advance(ms);
        });
      }
    }
    cost = rng() < 0.4 ? 18 + int(10) : int(16);
    const before = nodes.map((n) => (n.critical && n.dirty !== Dirty.NONE ? n.collects : -1));
    if (!clock.tick(1 + int(30))) continue;
    for (let i = 0; i < nodes.length; i += 1) {
      const n = nodes[i] as NullSeries;
      if ((before[i] ?? -1) >= 0 && n.collects === before[i]) {
        return `step ${s}: critical ${n.id} deferred`;
      }
    }
    if (Math.abs(scheduler.shedLevel - level) > 1) return `step ${s}: shed level jumped`;
    level = scheduler.shedLevel;
    seen.shed += level > 0 ? 1 : 0;
    seen.carried += scheduler.deferredMutations > 0 ? 1 : 0;
  }
  seen.stepDowns += scheduler.lod;
  cost = 0;
  for (let f = 0; f < 400 && clock.tick(); f += 1);
  if (clock.doubleRequests !== 0) return "a frame was requested twice";
  if (late !== 0) return `${late} mutations started after the clamp`;
  if (applied.length !== queued || applied.some((id, i) => id !== i)) return "lost or reordered";
  if (!scheduler.parked) return "did not park"; // only once no deferred node is left
  const dirty = nodes.find((n) => n.dirty !== Dirty.NONE || n.cleanCollects !== 0);
  return dirty === undefined ? null : `${dirty.id} left dirty or collected clean`;
}

describe("property: the scheduler drains, defers and parks correctly", () => {
  it("holds for 10 000 seeded random sequences", { timeout: 120_000 }, () => {
    const failures: string[] = [];
    for (let c = 0; c < 10_000 && failures.length < 5; c += 1) {
      const failure = runCase(BASE_SEED + c);
      if (failure !== null) failures.push(`seed ${BASE_SEED + c}: ${failure}`); // re-run one seed
    }
    expect(failures).toEqual([]);
    expect(Math.min(seen.shed / 10, seen.carried, seen.stepDowns)).toBeGreaterThan(1000);
  });
});
