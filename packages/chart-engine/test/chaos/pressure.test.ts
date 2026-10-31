// E11-Q04 chaos charter, groups 3 to 5: resource pressure (G7's 100 cycles, worker starvation),
// the backgrounded tab (G6's store and frame halves) and the degraded paths (WebGL2 absent at
// startup, the inline fallback of F-14). Fake DOM, fake worker, fake clock; nothing measured.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, setHostEnvFactory } from "../../src/api/chart.js";
import type { ChartEvents } from "../../src/api/types.js";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import { REDUCED_CAPABILITIES } from "../../src/gl/capability.js";
import { BarStore } from "../../src/model/index.js";
import { createChartHost, MAX_UNACKED, type HostEnv } from "../../src/worker/host.js";
import {
  ENGINE_CONTEXT_LOST,
  ENGINE_CONTEXT_RESTORED,
  ENGINE_NO_WEBGL2,
  INPUT,
  INPUT_MAX_ROWS,
  type FromWorker,
  type RunMode,
  type ToWorker,
} from "../../src/worker/protocol.js";
import { createRenderRuntime } from "../../src/worker/runtime.js";
import { asHtml, FakeDocument, FakeElement } from "../api/fake-dom.js";
import { FULL } from "../gl/fake-gl.js";
import { bars, STEP } from "../model/fixtures.js";
import { fakeEnv, FakeWorker } from "../worker/fake-worker.js";
import {
  candleBatch,
  dataMsg,
  fakeNow,
  frames,
  lossCanvas,
  rng,
  roomyGl,
  SEEDS,
} from "./harness.js";

const theme = { palette: "default" as const, convention: "standard" as const, colors: {} };

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  FakeWorker.created = [];
});

afterEach(() => {
  setHostEnvFactory(null);
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function docFor(mode: RunMode): FakeDocument {
  const doc = new FakeDocument();
  doc.offscreenAvailable = mode === "worker";
  doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
  return doc;
}

function containerIn(doc: FakeDocument): FakeElement {
  const el = new FakeElement("div", doc);
  el.clientWidth = 200;
  el.clientHeight = 100;
  return el;
}

const liveListeners = (t: { listeners: Map<string, Set<unknown>> }): number =>
  [...t.listeners.values()].reduce((n, s) => n + s.size, 0);

describe("Scenario: Repeated chart lifecycle leaks nothing (G7, engine-side parts)", () => {
  it.each(["inline", "worker"] as RunMode[])(
    "%s: 100 create / dispose cycles of two charts leave no GL object, listener, canvas or worker",
    (mode) => {
      setHostEnvFactory(() => fakeEnv());
      const doc = docFor(mode);
      const estimates: number[] = [];
      for (let cycle = 0; cycle < 100; cycle += 1) {
        const boxes = [containerIn(doc), containerIn(doc)];
        const charts = boxes.map((box) => {
          const chart = createChart({ container: asHtml(box), theme, runMode: mode });
          chart.subscribe("frameStats", (s: ChartEvents["frameStats"]) => {
            if (box === boxes[0]) estimates.push(s.gpuMemoryMbEstimate);
          });
          return chart;
        });
        frames(48);
        charts.forEach((c) => c.dispose());
        frames(32);
        for (const box of boxes) {
          expect([cycle, box.children.length, liveListeners(box)]).toEqual([cycle, 0, 0]);
        }
      }
      const canvases = doc.created.filter((e) => e.tagName === "CANVAS");
      expect(canvases.length).toBeGreaterThanOrEqual(200);
      expect(canvases.map(liveListeners).filter((n) => n > 0)).toEqual([]);
      expect([liveListeners(doc), liveListeners(doc.documentElement)]).toEqual([0, 0]);
      if (mode === "inline") {
        // The runtime released every GL object it created (a lost-free fake: alive = not deleted).
        expect(canvases.map((c) => c.webgl2?.alive.size ?? 0).filter((n) => n > 0)).toEqual([]);
      } else {
        // One worker per cycle (the last chart's dispose ends the link); every one terminated.
        expect(FakeWorker.created).toHaveLength(100);
        expect(FakeWorker.created.filter((w) => !w.terminated)).toEqual([]);
      }
      // "engine estimate, not measured GPU memory" (BQ-11): the first cycle's equals the last's.
      expect(estimates.length).toBeGreaterThanOrEqual(100);
      expect(estimates.at(-1)).toBe(estimates[0]);
    },
  );

  it.todo(
    "G7 JS heap within 5 % after 100 cycles (browser lane, cross-origin isolated page; else pending: E11-Q07 #519)",
  );
  it.todo(
    "G7 GPU memory within 5 % after 100 cycles (pending: E11-Q07 #519, real GPU; not observable on SwiftShader)",
  );
});

describe("Scenario: Backgrounding and restoring does not corrupt state (G6, store and frame halves)", () => {
  it("10 min of rAF stopped with a live feed: no frame backlog, one coalesced frame, no gap or duplicate", () => {
    for (const seed of SEEDS.slice(0, 5)) {
      vi.clearAllTimers();
      vi.setSystemTime(0);
      const r = rng(seed);
      const queued: (() => void)[] = [];
      const out: FromWorker[] = [];
      const rt = createRenderRuntime({
        runMode: "inline",
        post: (m) => out.push(m),
        requestFrame: (cb) => void queued.push(cb), // rAF: runs only while the tab is visible
        now: () => fakeNow(),
        setTimer: (cb, ms) => void setTimeout(cb, ms),
        probe: () => FULL,
      });
      const runFrames = (): number => {
        let n = 0;
        while (queued.length > 0 && n < 100) {
          queued.shift()?.();
          n += 1;
        }
        return n;
      };
      const c = lossCanvas(roomyGl());
      rt.handle({
        t: "init",
        id: 1,
        canvas: c,
        dpr: 1,
        theme: {},
        config: { bench: true, syncGroup: null },
      });
      runFrames();
      const store = new BarStore();
      store.append(bars(0, 100));
      let minute = 100;
      // Hidden: timers throttled to once a minute, rAF stopped; the feed keeps arriving.
      let backlog = 0;
      for (let tick = 0; tick < 10; tick += 1) {
        vi.advanceTimersByTime(60_000);
        const n = r.int(30, 90);
        store.append(bars(minute, n)); // the data layer applies the minute's bars as one batch
        rt.handle(dataMsg(candleBatch(r, minute, n)));
        minute += n;
        backlog = Math.max(backlog, queued.length);
      }
      expect(backlog, `seed ${seed}`).toEqual(1); // one frame requested, never a queue of them
      const before = out.filter((m) => m.t === "frame").length;
      expect(runFrames(), `seed ${seed}`).toEqual(1); // foregrounded: one frame catches up
      expect(out.filter((m) => m.t === "frame").length - before, `seed ${seed}`).toEqual(1);
      expect(out.filter((m) => m.t === "error")).toEqual([]);
      const v = store.view();
      const gaps = v.time.subarray(1).filter((t, i) => t - (v.time[i] as number) !== STEP).length;
      expect([v.length, gaps], `seed ${seed}`).toEqual([minute, 0]); // no gap, no duplicate
    }
  });

  it.todo(
    "G6 engine visibility handling: no replay of ten minutes of animation on foreground (pending: needs-owner, a row on #516's record for the E11 epic)",
  );
  it.todo("G6 the data-layer catch-up fetch after foregrounding (pending: E12-T06 #399)");
});

describe("Scope: worker starvation, the main thread blocked for 5 s (H-14)", () => {
  it("5 s of queued input and data go out bounded: one input batch per kind, two batches in flight", () => {
    setHostEnvFactory(() => fakeEnv());
    const doc = docFor("worker");
    const resyncs: string[] = [];
    let canvas = doc.createElement("canvas");
    const host = createChartHost({
      realm: doc,
      runMode: "worker",
      env: fakeEnv(),
      canvas: () => asHtml(canvas) as HTMLCanvasElement,
      replaceCanvas: () => (canvas = doc.createElement("canvas")) as unknown as HTMLCanvasElement,
      dpr: 1,
      theme: {},
      syncGroup: null,
      bench: false,
      listener: {
        deliver: () => undefined,
        lost: () => undefined,
        restored: () => undefined,
        resync: (s) => resyncs.push(s),
      },
    });
    vi.advanceTimersByTime(20);
    const worker = FakeWorker.created.at(-1) as FakeWorker;
    const inbox = (t: ToWorker["t"]): ToWorker[] =>
      (worker.inbox as ToWorker[]).filter((m) => m.t === t);
    // Blocked: no timer runs for 5 s while 1 kHz pointer moves and a 10 Hz feed pile up.
    for (let ms = 0; ms < 5000; ms += 1) {
      host.input("pointer", [INPUT.move, ms % 200, 50, 0, 0, 1]);
      if (ms % 100 === 0) {
        const b = candleBatch(rng(ms), ms, 4);
        host.data("bars", "patch", b.layout, b.buffer);
      }
    }
    vi.setSystemTime(fakeNow() + 5000);
    vi.advanceTimersByTime(17); // unblocked: the next frame flushes
    const inputs = inbox("input") as Extract<ToWorker, { t: "input" }>[];
    expect(inputs).toHaveLength(1); // one coalesced batch, not 5 000 messages
    expect(inputs[0]?.events.length).toBeLessThanOrEqual(INPUT_MAX_ROWS * 6);
    // 50 patches: two in flight, the other 48 folded into one held patch (last wins).
    expect(inbox("data").length).toBeLessThanOrEqual(MAX_UNACKED + 1);
    expect(host.counters.conflated).toBeGreaterThan(4000);
    vi.advanceTimersByTime(200);
    expect(resyncs).toEqual([]); // patches fold (last wins): nothing was lost, nothing to resync
    host.dispose();
  });

  it.todo(
    "worker starvation: the bounded inbound queue of F-04 under a stalled worker (pending: E11-X03 #524 shares H-14)",
  );
});

describe("Scope: degraded paths", () => {
  it.each(["inline", "worker"] as RunMode[])(
    "%s: no WebGL2 at startup posts ENGINE_NO_WEBGL2 once with its reductions, then draws 2D",
    (mode) => {
      setHostEnvFactory(() => fakeEnv());
      const submit = vi.spyOn(Canvas2DBackend.prototype, "submit");
      const doc = docFor(mode);
      doc.webgl2Available = false;
      const box = containerIn(doc);
      const chart = createChart({ container: asHtml(box), theme, runMode: mode });
      const errors: ChartEvents["error"][] = [];
      chart.subscribe("error", (e) => errors.push(e));
      frames(200);
      chart.timeScale.setVisibleRange({ from: 1, to: 2 });
      frames(200);
      expect(errors).toEqual([
        {
          code: ENGINE_NO_WEBGL2,
          message: expect.any(String),
          recoverable: true,
          details: { reducedCapabilities: [...REDUCED_CAPABILITIES], reason: expect.any(String) },
        },
      ]);
      expect(chart.getStats().renderProfile).toBe("degraded-2d");
      expect(submit.mock.calls.length).toBeGreaterThan(1); // still drawing, through Canvas 2D
      chart.dispose();
    },
  );

  const blocked: Record<string, (doc: FakeDocument) => Partial<HostEnv>> = {
    "worker creation blocked": () => ({
      createWorker: () => {
        throw new Error("blocked by policy");
      },
    }),
    "canvas transfer blocked": (doc) => ((doc.offscreenThrows = true), {}),
  };

  it.each(Object.keys(blocked))(
    "F-14, %s: the chart runs inline, and a context loss there recovers",
    (name) => {
      const doc = docFor("worker");
      const over = blocked[name]?.(doc) ?? {};
      setHostEnvFactory(() => fakeEnv(over));
      const box = containerIn(doc);
      const chart = createChart({ container: asHtml(box), theme });
      const errors: string[] = [];
      chart.subscribe("error", (e) => errors.push(e.code));
      expect((chart as unknown as { runMode: RunMode }).runMode).toBe("inline");
      frames(48);
      const canvas = box.children.find((e) => e.tagName === "CANVAS");
      canvas?.webgl2?.loseContext();
      canvas?.dispatch("webglcontextlost", {});
      frames(300);
      canvas?.webgl2?.restoreContext();
      canvas?.dispatch("webglcontextrestored", {});
      frames(48);
      expect(errors).toEqual([ENGINE_CONTEXT_LOST, ENGINE_CONTEXT_RESTORED]);
      chart.dispose();
    },
  );

  it.todo("F-14 runMode reported in the SCR-046 allowlist (pending: E11-T07 #523)");
  it.todo("IndexedDB unavailable during atlas caching (pending: E11-S11 #336)");
  it.todo(
    "memory pressure to the 70 % threshold emits ENGINE_MEMORY_PRESSURE once (pending: E11-S15 #448)",
  );
  it.todo("GPU memory exhaustion is handled, not a silent blank (pending: E11-S15 #448)");
  it.todo("DPR change mid-pan keeps the viewport and crispness (pending: E11-S10 #447)");
  it.todo(
    "focus and the data cursor survive every recovery; the DOM mirror announces it (pending: E11-S13 #520)",
  );
});
