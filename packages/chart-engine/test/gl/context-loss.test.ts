// E11-S02 PR3: context-loss recovery on the fake GL (README BQ-49, BQ-56), on an injected clock.
import { beforeEach, describe, expect, it } from "vitest";
import { ContextRestoreBench } from "../../bench/scenes/context-restore.js";
import {
  ContextLoss,
  ENGINE_CONTEXT_LOST,
  ENGINE_CONTEXT_RESTORE_FAILED,
  ENGINE_CONTEXT_RESTORED,
  RESTORE_BUDGET_MS,
} from "../../src/gl/context-loss.js";
import { RESTART_BACKOFF_MS } from "../../src/worker/protocol.js";
import { FakeGl } from "./fake-gl.js";

let t = 0;
let due: { at: number; cb: () => void }[] = [];
const clock = {
  now: (): number => t,
  setTimer: (cb: () => void, ms: number): void => void due.push({ at: t + ms, cb }),
};
/** Moves the injected clock, running each timer that falls due, in time order. */
function advance(ms: number): void {
  const end = t + ms;
  for (;;) {
    due.sort((a, b) => a.at - b.at);
    const next = due[0];
    if (next === undefined || next.at > end) break;
    due.shift();
    t = next.at;
    next.cb();
  }
  t = end;
}

beforeEach(() => {
  t = 0;
  due = [];
});

/** What the GPU holds and draws: equal before a loss and after the restore (BQ-56). */
function state(bench: ContextRestoreBench, gl: FakeGl) {
  const { trace, registry, gpuMemoryMbEstimate } = bench.scene.backend;
  return {
    draws: [...trace.nodes],
    triangles: trace.triangles,
    switches: [trace.programSwitches, trace.textureSwitches],
    live: registry.counts(),
    gpuMemoryMbEstimate,
    clear: gl.clears.at(-1),
    instances: bench.scene.nodes.map((n) => n.count), // the CPU side: never touched
  };
}

describe("Scenario: Context loss recovers within the R1 exit budget", () => {
  it("rebuilds programs, then textures, then buffers: same draws, same buffer digest", () => {
    const gl = new FakeGl();
    const bench = new ContextRestoreBench(gl, clock);
    bench.scene.backend.trace.enabled = true;
    bench.scene.step();
    const before = state(bench, gl);
    const digest = [...gl.writes].sort();
    const { programs } = bench.scene.backend;
    const linked = programs.stats.compiles; // line, bar-cell and sdf-text: relinked, once each
    gl.writes.length = 0;
    const from = gl.log.length;
    expect(bench.cycle(() => advance(250))).toBe(250);
    expect(bench.loss.stats.restoreMs).toBeLessThanOrEqual(RESTORE_BUDGET_MS);
    const log = gl.log.slice(from);
    const first = (name: string): number => log.indexOf(name);
    expect(first("linkProgram")).toBeGreaterThan(-1);
    expect(first("linkProgram")).toBeLessThan(first("texImage2D"));
    expect(first("texImage2D")).toBeLessThan(first("bufferData"));
    expect(log).not.toContain("deleteBuffer"); // a lost context's objects are dropped, not deleted
    expect(state(bench, gl)).toEqual(before);
    expect([...gl.writes].sort()).toEqual(digest); // 100 000 bars + 17 rings, in full, once
    expect(bench.events).toEqual([ENGINE_CONTEXT_LOST, ENGINE_CONTEXT_RESTORED]);
    expect(bench.loss.stats).toMatchObject({ losses: 1, failures: 0 });
    expect(programs.stats.compiles).toBe(2 * linked);
  });

  it("recovers or reports at 50 seeded loss points, never hanging (fuzz)", () => {
    const pixels = new Uint8Array(64 * 64 * 4);
    const session = (bench: ContextRestoreBench, gl: FakeGl): void => {
      const { scene } = bench;
      scene.backend.trace.enabled = true;
      const [candles] = scene.nodes.filter((n) => n.id.endsWith("candles"));
      const ops = [
        () => scene.step(),
        () =>
          scene.builder.patch(candles?.id ?? "", { op: "patch", from: 8, to: 40, indexShift: 0 }),
        () => scene.step(), // mid-bufferSubData
        () => scene.backend.textures.define(2, 64, 64, pixels), // mid-atlas upload
        () => scene.backend.textures.patch(2, 0, 0, 8, 8, pixels),
        () => scene.backend.submit(scene.builder.drawList, scene.builder.drawCount, 0, 0), // 0 × 0
        () => scene.backend.submit(scene.builder.drawList, scene.builder.drawCount, 3840, 2160), // DPR 2
        () => scene.step(),
      ];
      for (const op of ops) {
        op();
        if (gl.lost && bench.loss.phase === "live") bench.loss.lost(); // the event is async
      }
    };
    const refGl = new FakeGl();
    const ref = new ContextRestoreBench(refGl, clock, 4096);
    session(ref, refGl);
    const calls = refGl.log.length; // every loss point falls inside the session
    ref.scene.step();
    for (let seed = 0; seed < 50; seed += 1) {
      const gl = new FakeGl();
      gl.loseAt = 2 + ((seed * 7919) % (calls - 1)); // call 1 fetches the extension
      const bench = new ContextRestoreBench(gl, clock, 4096);
      session(bench, gl);
      expect(bench.loss.phase).toBe("lost"); // every seed's loss point is inside the session
      if (seed % 10 === 9) gl.failAt = gl.log.length + 3; // a driver fault mid-rebuild
      advance(100);
      for (let k = 0; k < 3 && bench.loss.phase === "lost"; k += 1) {
        bench.ext.restoreContext();
        bench.loss.restored();
      }
      bench.scene.step();
      bench.loss.framed();
      advance(10_000);
      // Every seed recovers: the 5 fault seeds (seed % 10 === 9) still have tries left.
      expect([seed, bench.loss.phase]).toEqual([seed, "live"]);
      expect(state(bench, gl)).toEqual(state(ref, refGl));
    }
  });

  // The 0.1 % golden image needs E11-T08's Playwright + SwiftShader harness (#391): a C-row.
  it.todo("golden: the post-restore frame matches the pre-loss frame within 0.1 % (E11-T08)");
});

describe("Scenario: Repeated loss gives up gracefully rather than looping", () => {
  const machine = (rebuild: () => boolean) => {
    const seen: [number, string, string][] = [];
    const calls: string[] = [];
    const m = new ContextLoss({
      backoffMs: RESTART_BACKOFF_MS,
      ...clock,
      park: () => calls.push("park"),
      rebuild,
      resume: () => calls.push("resume"),
      giveUp: () => calls.push("giveUp"),
      emit: (code, message) => seen.push([t, code, message]),
    });
    return { m, seen, calls };
  };

  it("fails three attempts at 1 / 2 / 4 s, then RESTORE_FAILED, parked for good", () => {
    const { m, seen, calls } = machine(() => true);
    let prevented = 0;
    m.lost({ preventDefault: () => (prevented += 1) });
    advance(60_000);
    expect(seen.map(([at, code]) => [at, code])).toEqual([
      [0, ENGINE_CONTEXT_LOST],
      [1000, ENGINE_CONTEXT_LOST],
      [3000, ENGINE_CONTEXT_LOST],
      [7000, ENGINE_CONTEXT_RESTORE_FAILED],
    ]);
    expect(seen[0]?.[2]).toBe("Graphics context lost: restoring, attempt 1 of 3, next try in 1 s");
    expect(seen[2]?.[2]).toMatch(/attempt 3 of 3, next try in 4 s$/);
    expect([prevented, m.phase, m.stats.failures]).toEqual([1, "failed", 3]);
    m.restored(); // too late: nothing rebuilds, nothing loops
    m.lost();
    m.framed();
    advance(60_000);
    expect(seen).toHaveLength(4);
    expect(calls.filter((c) => c === "giveUp")).toHaveLength(1);
    expect(calls).not.toContain("resume");
  });

  it("counts a rebuild that loses again, and a loss before the first frame, as failures", () => {
    let ok = false;
    const { m, seen } = machine(() => ok);
    m.lost();
    m.restored(); // the rebuild lost the context again: attempt 2 at once
    expect([m.phase, m.attempt]).toEqual(["lost", 2]);
    ok = true;
    m.restored();
    m.lost(); // lost again before a complete frame: attempt 3
    expect([m.phase, m.attempt]).toEqual(["lost", 3]);
    m.restored();
    advance(500);
    m.framed();
    expect(seen.map(([, code]) => code).at(-1)).toBe(ENGINE_CONTEXT_RESTORED);
    expect([m.phase, m.attempt, m.stats.restoreMs]).toEqual(["live", 0, 500]);
    m.lost(); // a later loss is a new episode with a fresh budget
    expect([m.attempt, m.stats.losses]).toEqual([1, 2]);
  });
});
