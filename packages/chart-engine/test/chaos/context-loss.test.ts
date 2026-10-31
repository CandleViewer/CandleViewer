// E11-Q04 chaos charter, group 1: context loss (Gherkin G1, G2, G3). Seeded loss points on the
// fake GL and the fake clock; every case asserts the state after recovery against a run that
// never lost the context, not merely that nothing threw. Golden pixels are E11-T08's (#391).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContextRestoreBench, RESTORE_BARS } from "../../bench/scenes/context-restore.js";
import { createChart, setHostEnvFactory } from "../../src/api/chart.js";
import type { ChartEvents } from "../../src/api/types.js";
import { RESTORE_BUDGET_MS } from "../../src/gl/context-loss.js";
import { createChartHost } from "../../src/worker/host.js";
import {
  ENGINE_CONTEXT_LOST,
  ENGINE_CONTEXT_RESTORE_FAILED,
  ENGINE_CONTEXT_RESTORED,
  ENGINE_NO_WEBGL2,
  type FromWorker,
} from "../../src/worker/protocol.js";
import { asHtml, fakeContainer, FakeDocument, type FakeElement } from "../api/fake-dom.js";
import { FakeGl } from "../gl/fake-gl.js";
import { fakeEnv } from "../worker/fake-worker.js";
import {
  candleBatch,
  codes,
  dataMsg,
  fakeNow,
  frames,
  last,
  lossCanvas,
  rng,
  roomyGl,
  runtimeOnFakeClock,
  SEEDS,
  type Rng,
} from "./harness.js";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
});

afterEach(() => {
  setHostEnvFactory(null);
  vi.useRealTimers();
});

type Phase = "idle" | "pan" | "storm";
const LOST = [ENGINE_CONTEXT_LOST, true] as const;
const RESTORED = [ENGINE_CONTEXT_RESTORED, true] as const;

/** One op of `phase`: nothing, a pan with the crosshair (sync), or a bars batch. */
function op(rt: ReturnType<typeof runtimeOnFakeClock>["rt"], phase: Phase, r: Rng, i: number) {
  const T0 = 1_700_000_000_000_000;
  if (phase === "pan") {
    const start = T0 + r.int(0, 500) * 60_000_000;
    const end = start + r.int(20, 200) * 60_000_000;
    rt.handle({ t: "sync", groupId: "g", timeRange: [start, end], crosshair: start + 60_000_000 });
  } else if (phase === "storm") {
    rt.handle(dataMsg(candleBatch(r, i * 50, r.int(1, 50))));
  }
}

/** A session of `phase` with a seeded loss point and restore delay (or none); the GL state. */
function session(seed: number, phase: Phase, lose: boolean) {
  vi.clearAllTimers();
  vi.setSystemTime(0);
  const r = rng(seed);
  const { rt, out, init } = runtimeOnFakeClock();
  const gl = roomyGl();
  const c = lossCanvas(gl);
  init(c);
  frames(32);
  const ops = 40;
  const lossAt = r.int(0, ops - 1);
  const restoreAfter = r.int(0, 300); // inside attempt 1's 1 s wait
  const opRng = rng(seed ^ 0x5bd1e995); // the same ops in both runs, whatever the loss draws
  for (let i = 0; i < ops; i += 1) {
    if (lose && i === lossAt) c.lose();
    op(rt, phase, opRng, i);
    frames(16);
  }
  if (lose) {
    frames(restoreAfter);
    c.restore();
  }
  frames(64);
  const uniforms = new Map(gl.uniforms.map(([name, ...v]) => [name, v]));
  return {
    out,
    gl: { live: gl.alive.size, clear: gl.clears.at(-1), uniforms: [...uniforms].sort() },
  };
}

/** What the app and the GPU see once the session has settled. */
const settled = (s: ReturnType<typeof session>) => ({
  viewport: last(s.out, "viewport"),
  a11y: last(s.out, "a11y"),
  frame: last(s.out, "frame"),
  acks: s.out.filter((m) => m.t === "ack").length,
  gl: s.gl,
});

describe("Scenario: Context loss restores a correct scene within the budget (G1)", () => {
  it.each(["idle", "pan", "storm"] as Phase[])(
    "loss during %s, 25 seeds: LOST then RESTORED once each; viewport, crosshair, data, GPU kept",
    (phase) => {
      for (const seed of SEEDS) {
        const ref = session(seed, phase, false);
        const hit = session(seed, phase, true);
        expect(codes(ref.out), `seed ${seed}`).toEqual([]);
        expect(codes(hit.out), `seed ${seed}`).toEqual([LOST, RESTORED]);
        expect(settled(hit), `seed ${seed}`).toEqual(settled(ref));
        // The budget is applied on the fake clock; the wall-clock measurement is the perf test's.
        const restored = hit.out.filter((m) => m.t === "error").at(-1);
        const ms = Number(
          /in (\d+) ms$/.exec(restored?.t === "error" ? restored.message : "")?.[1],
        );
        expect(ms <= RESTORE_BUDGET_MS, `seed ${seed}`).toEqual(true);
      }
    },
  );

  // The scene side at the ticket's scale: 100 000 bars over 3 panes (the context-restore scene).
  it("a seeded patch storm over 100 000 bars and 3 panes: the restored scene equals a no-loss run", () => {
    let t = 0;
    const clock = { now: () => t, setTimer: () => undefined }; // each restore lands in attempt 1
    // Texture definitions the GPU holds: since the last restore, or since the start.
    const textures = (gl: FakeGl, from: number): number =>
      gl.log.slice(from).filter((c) => c === "texImage2D").length;
    const state = (b: ContextRestoreBench, gl: FakeGl, from = 0) => ({
      textures: textures(gl, from),
      draws: [...b.scene.backend.trace.nodes],
      triangles: b.scene.backend.trace.triangles,
      live: b.scene.backend.registry.counts(),
      gpuMemoryMbEstimate: b.scene.backend.gpuMemoryMbEstimate,
      instances: b.scene.nodes.map((n) => n.count),
      clear: gl.clears.at(-1),
      alive: gl.alive.size,
    });
    const run = (seed: number, lose: boolean) => {
      t = 0;
      const r = rng(seed);
      const gl = new FakeGl();
      const b = new ContextRestoreBench(gl, clock, RESTORE_BARS);
      b.scene.backend.trace.enabled = true;
      b.scene.step();
      const candles = b.scene.nodes.filter((n) => n.id.endsWith("candles"));
      const lossAt = r.int(0, 29);
      for (let i = 0; i < 30; i += 1) {
        if (lose && i === lossAt) {
          b.ext.loseContext();
          b.loss.lost();
        }
        const from = r.int(0, RESTORE_BARS - 2);
        const node = r.pick(candles);
        b.scene.builder.patch(node.id, {
          op: "patch",
          from,
          to: r.int(from + 1, RESTORE_BARS),
          indexShift: 0,
        });
        b.scene.step();
        t += 16;
      }
      let mark = 0;
      if (lose) {
        t += r.int(0, 900);
        mark = gl.log.length;
        b.ext.restoreContext();
        b.loss.restored();
        b.scene.step();
        b.loss.framed();
      }
      b.scene.step();
      return { b, state: state(b, gl, mark) };
    };
    for (const seed of SEEDS.slice(0, 5)) {
      const ref = run(seed, false);
      const hit = run(seed, true);
      expect(hit.b.events, `seed ${seed}`).toEqual([ENGINE_CONTEXT_LOST, ENGINE_CONTEXT_RESTORED]);
      expect(hit.state, `seed ${seed}`).toEqual(ref.state);
      expect(hit.b.loss.stats.restoreMs).toBeLessThanOrEqual(RESTORE_BUDGET_MS);
    }
  });

  it.todo("G1 at 3 runtime panes with pane ratios kept (pending: E11-S09 #446)");
  it.todo(
    "G1 with an active crosshair series drawn, not only the a11y summary (pending: E11-S07 #388)",
  );
  it.todo("G1 golden: the post-restore frame matches the pre-loss frame (pending: E11-T08 #391)");
  it.todo("G1 loss during SDF atlas generation (pending: E11-S11 #336)");
  it.todo(
    "G1 SCR-048 announces the loss through role=alert in a mounted chart (pending: needs-owner, once a route mounts the chart)",
  );
});

describe("Scenario: Repeated context loss does not degrade into a broken state (G2)", () => {
  it("three losses inside 10 s, 25 seeds: each recovers; GPU objects and estimate back to the start", () => {
    for (const seed of SEEDS) {
      vi.clearAllTimers();
      vi.setSystemTime(0);
      const r = rng(seed);
      const { rt, out, init } = runtimeOnFakeClock();
      const gl = roomyGl();
      const c = lossCanvas(gl);
      init(c);
      frames(32);
      const before = { live: gl.alive.size, frame: last(out, "frame") };
      const firstLoss = fakeNow();
      for (let k = 0; k < 3; k += 1) {
        c.lose();
        frames(r.int(16, 800));
        c.restore();
        frames(r.int(200, 2000));
      }
      expect(fakeNow() - firstLoss).toBeLessThan(10_000);
      expect(codes(out), `seed ${seed}`).toEqual([LOST, RESTORED, LOST, RESTORED, LOST, RESTORED]);
      expect({ live: gl.alive.size, frame: last(out, "frame") }, `seed ${seed}`).toEqual(before);
      // Still fully functional: a pan after the third recovery reaches the viewport.
      rt.handle({ t: "command", id: 1, cmd: { k: "setViewport", timeStart: 5e15, timeEnd: 6e15 } });
      frames(32);
      expect(last(out, "viewport")).toMatchObject({ timeStart: 5e15 });
    }
  });

  it("the 3-pane, 100 000-bar scene: three cycles leave registry and GPU estimate unchanged", () => {
    let t = 0;
    const clock = { now: () => t, setTimer: () => undefined };
    const gl = new FakeGl();
    const b = new ContextRestoreBench(gl, clock);
    b.scene.step();
    const before = [
      b.scene.backend.registry.counts(),
      b.scene.backend.gpuMemoryMbEstimate,
      gl.alive.size,
    ];
    for (let k = 0; k < 3; k += 1) b.cycle(() => void (t += 250));
    const after = [
      b.scene.backend.registry.counts(),
      b.scene.backend.gpuMemoryMbEstimate,
      gl.alive.size,
    ];
    expect(after).toEqual(before);
    expect(b.loss.stats).toMatchObject({ losses: 3, failures: 0 });
  });

  it.todo("G2 golden-image comparison after each recovery (pending: E11-T08 #391)");
});

/** An inline chart on the fake DOM; its errors and frame stats as the app hears them. */
function mountedChart() {
  setHostEnvFactory(() => fakeEnv());
  const container = fakeContainer(200, 100);
  container.ownerDocument.defaultView = { devicePixelRatio: 1 };
  const chart = createChart({
    container: asHtml(container),
    theme: { palette: "default", convention: "standard", colors: {} },
    runMode: "inline",
  });
  const errors: ChartEvents["error"][] = [];
  chart.subscribe("error", (e) => errors.push(e));
  const canvas = (): FakeElement[] => container.children.filter((c) => c.tagName === "CANVAS");
  return { chart, errors, canvas };
}

/** The same inline host the facade builds, with every message the engine sent it. */
function hostedInline() {
  const doc = new FakeDocument();
  doc.defaultView = { devicePixelRatio: 1 };
  let canvas: FakeElement = doc.createElement("canvas");
  const canvases = [canvas];
  const seen: FromWorker[] = [];
  const noop = (): void => undefined;
  const host = createChartHost({
    realm: doc,
    runMode: "inline",
    env: fakeEnv(),
    canvas: () => asHtml(canvas) as HTMLCanvasElement,
    replaceCanvas: () => {
      canvas = doc.createElement("canvas");
      canvases.push(canvas);
      return asHtml(canvas) as HTMLCanvasElement;
    },
    dpr: 1,
    theme: {},
    syncGroup: null,
    bench: false,
    listener: { deliver: (m) => seen.push(m), lost: noop, restored: noop, resync: noop },
  });
  return { host, canvases, seen };
}

const loseForGood = (c: FakeElement | undefined): void => {
  c?.webgl2?.loseContext();
  c?.dispatch("webglcontextlost", {});
  frames(8000); // 1 + 2 + 4 s of attempts, then the handoff
};

describe("Scenario: A permanent loss falls back rather than failing (G3)", () => {
  it("ChartEvents.error: LOST once per attempt (1 / 2 / 4 s), RESTORE_FAILED once, nothing more", () => {
    const { chart, errors, canvas } = mountedChart();
    frames(48);
    const [first] = canvas();
    loseForGood(first);
    expect(errors.map((e) => [e.code, e.recoverable, e.details])).toEqual([
      [ENGINE_CONTEXT_LOST, true, { attempt: 1, maxAttempts: 3, nextTryMs: 1000 }],
      [ENGINE_CONTEXT_LOST, true, { attempt: 2, maxAttempts: 3, nextTryMs: 2000 }],
      [ENGINE_CONTEXT_LOST, true, { attempt: 3, maxAttempts: 3, nextTryMs: 4000 }],
      [ENGINE_CONTEXT_RESTORE_FAILED, false, undefined],
    ]);
    const now = canvas();
    expect(now).toHaveLength(1); // the old canvas is gone from the container
    expect(now[0]).not.toBe(first);
    expect(first?.listeners.get("webglcontextlost")?.size ?? 0).toBe(0);
    chart.timeScale.setVisibleRange({ from: 1, to: 2 });
    frames(2000);
    expect(errors).toHaveLength(4); // the 2D chart runs on with no further error
    chart.dispose();
  });

  it("the engine hands off automatically: a fresh canvas, ready and frames in degraded-2d", () => {
    const { host, canvases, seen } = hostedInline();
    frames(48);
    loseForGood(canvases[0]);
    // The ruled handoff (README BQ-53, BQ-90): no ENGINE_NO_WEBGL2; the app maps the profile.
    expect(seen.some((m) => m.t === "error" && m.code === ENGINE_NO_WEBGL2)).toBe(false);
    expect(canvases).toHaveLength(2);
    expect(canvases[1]?.webgl2?.log).toEqual([]); // the new canvas never held WebGL2
    const ready = seen.flatMap((m) => (m.t === "ready" ? [m.renderProfile] : []));
    expect(ready).toEqual(["full", "degraded-2d"]);
    const profiles = seen.flatMap((m) => (m.t === "frame" ? [m.renderProfile] : []));
    expect(profiles.at(-1)).toBe("degraded-2d");
    host.dispose();
  });

  // D-01 (record §6): the facade's FrameStats keeps the first frame's renderProfile, so after the
  // handoff `frameStats` / `getStats()` still say "full" while the engine draws degraded-2d.
  it.todo("G3 the facade reports degraded-2d in frameStats after the handoff (defect D-01, #5230)");
  it.todo(
    "G3 the manual retry and the SCR-118 renderer-settings link (finding F-01, needs-owner: the SCR-118 route ticket)",
  );
});
