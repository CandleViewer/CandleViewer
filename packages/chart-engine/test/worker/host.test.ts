// The main-thread host over the real worker entry on a fake async bus (E11-T02): run mode, the
// zero-copy transfer, backpressure, frame coalescing, input capture and worker crash recovery.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, setHostEnvFactory, type ChartInternal } from "../../src/api/chart.js";
import {
  captureInput,
  createChartHost,
  defaultHostEnv,
  HEALTHY_RESET_MS,
  MAX_QUEUED,
  type ChartHost,
  type HostEnv,
} from "../../src/worker/host.js";
import {
  ENGINE_WORKER_LOST,
  INPUT,
  INPUT_MAX_ROWS,
  type FromWorker,
  type StoreId,
  type ToWorker,
} from "../../src/worker/protocol.js";
import type { CandleData, ChartEvents, ThemeTokens } from "../../src/index.js";
import { asHtml, FakeDocument, FakeElement, FakeOffscreen } from "../api/fake-dom.js";
import { fakeEnv, FakeWorker } from "./fake-worker.js";

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: { "color.chart.background": "#0b0e11" },
};

function workerDoc(): FakeElement {
  const doc = new FakeDocument();
  doc.offscreenAvailable = true;
  doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
  const el = new FakeElement("div", doc);
  el.clientWidth = 200;
  el.clientHeight = 100;
  return el;
}

const settle = (): void => {
  vi.advanceTimersByTime(20);
};
const lastWorker = (): FakeWorker => FakeWorker.created.at(-1) as FakeWorker;
const inboxOf = (w: FakeWorker, t: ToWorker["t"]): ToWorker[] =>
  (w.inbox as ToWorker[]).filter((m) => m.t === t);

function record(chart: ChartInternal): Record<string, unknown[]> {
  const seen: Record<string, unknown[]> = {};
  for (const e of ["error", "frameStats", "visibleRangeNeedsData", "viewportChanged"] as const) {
    seen[e] = [];
    chart.subscribe(e, (p: ChartEvents[typeof e]) => seen[e]?.push(p));
  }
  return seen;
}

let env: HostEnv;

beforeEach(() => {
  vi.useFakeTimers();
  FakeWorker.created = [];
  env = fakeEnv();
  setHostEnvFactory(() => env);
});

afterEach(() => {
  setHostEnvFactory(null);
  vi.useRealTimers();
});

describe("Scenario: Rendering runs off the main thread", () => {
  it("transfers the canvas to the shared worker and reports RunMode worker in ready", () => {
    const container = workerDoc();
    const chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
    const seen = record(chart);
    expect(chart.runMode).toBe("worker");
    settle();
    const [init] = inboxOf(lastWorker(), "init");
    expect(init).toMatchObject({ t: "init", dpr: 1, config: { bench: false, syncGroup: null } });
    expect((init as { canvas: unknown }).canvas).toBeInstanceOf(FakeOffscreen);
    expect(seen["frameStats"]).toEqual([expect.objectContaining({ renderProfile: "full" })]);
    expect(chart.getStats().renderProfile).toBe("full");

    const ready: FromWorker[] = [];
    const host = createChartHost({
      realm: container.ownerDocument,
      runMode: "worker",
      env,
      canvas: () => asHtml(container.ownerDocument.createElement("canvas")) as HTMLCanvasElement,
      replaceCanvas: () =>
        asHtml(container.ownerDocument.createElement("canvas")) as HTMLCanvasElement,
      dpr: 1,
      theme: {},
      syncGroup: null,
      bench: false,
      listener: {
        deliver: (m) => ready.push(m),
        lost: () => undefined,
        restored: () => undefined,
        resync: () => undefined,
      },
    });
    settle();
    expect(ready).toContainEqual(expect.objectContaining({ t: "ready", runMode: "worker" }));
    expect(FakeWorker.created).toHaveLength(1); // one worker per page, shared (§3.2 rule 1)
    host.dispose();
    expect(lastWorker().terminated).toBe(false); // the chart still holds it
    chart.dispose();
    expect(lastWorker().terminated).toBe(true);
    createChart({ container: asHtml(workerDoc()), theme }).dispose();
    expect(FakeWorker.created).toHaveLength(2);
  });

  it("takes a screenshot through the worker's export", async () => {
    const container = workerDoc();
    const chart = createChart({ container: asHtml(container), theme });
    const canvas = container.children.find((c) => c.tagName === "CANVAS") as FakeElement;
    const blob = new Blob(["png"]);
    canvas.blob = blob;
    const ok = chart.takeScreenshot();
    await vi.runAllTimersAsync();
    await expect(ok).resolves.toBe(blob);
    canvas.blob = null;
    const failed = chart.takeScreenshot().catch((e: Error) => e.message);
    await vi.runAllTimersAsync();
    await expect(failed).resolves.toMatch(/could not be encoded/);
    chart.dispose();
  });
});

function candles(n: number): CandleData {
  const buf = new ArrayBuffer(n * 28);
  return {
    time: new Float64Array(buf, 0, n),
    open: new Int32Array(buf, n * 8, n),
    high: new Int32Array(buf, n * 12, n),
    low: new Int32Array(buf, n * 16, n),
    close: new Int32Array(buf, n * 20, n),
    volume: new Float32Array(buf, n * 24, n),
    priceOrigin: 0,
    tickSize: 0.5,
  };
}

describe("Scenario: Data buffers are transferred, never copied", () => {
  it.each(["worker", "inline"] as const)(
    "%s: a 3.2 MB CandleData batch leaves the sender's ArrayBuffer at byteLength 0",
    (runMode) => {
      const chart = createChart({ container: asHtml(workerDoc()), theme, runMode });
      const series = chart
        .addPane({})
        .addSeries("candles", { upColorToken: "u", downColorToken: "d" });
      const n = Math.ceil(3_200_000 / 28);
      const data = candles(n);
      const sent = data.time.buffer;
      series.setData(data);
      expect(sent.byteLength).toBe(0);
      expect(data.close.length).toBe(0); // every column view is detached with it
      settle();
      if (runMode === "worker") {
        const [msg] = inboxOf(lastWorker(), "data") as Extract<ToWorker, { t: "data" }>[];
        expect(msg?.buffer.byteLength).toBe(n * 28);
        expect(msg?.layout.count).toBe(n);
      }
      series.append(candles(1));
      series.prependHistory(candles(2));
      settle();
      chart.dispose();
    },
  );

  it("non-candle series stay inert until their stores land", () => {
    const chart = createChart({ container: asHtml(workerDoc()), theme });
    const line = chart.addPane({}).addSeries("line", { colorToken: "x", lineWidth: 1 });
    expect(() =>
      line.setData({ time: new Float64Array(1), value: new Float64Array(1) }),
    ).not.toThrow();
    chart.dispose();
  });
});

function hostOn(
  container: FakeElement,
  e: HostEnv = env,
  events: FromWorker[] = [],
  resyncs: StoreId[] = [],
): ChartHost {
  const doc = container.ownerDocument;
  let canvas = doc.createElement("canvas");
  return createChartHost({
    realm: doc,
    runMode: "worker",
    env: e,
    canvas: () => asHtml(canvas) as HTMLCanvasElement,
    replaceCanvas: () => {
      canvas = doc.createElement("canvas");
      return asHtml(canvas) as HTMLCanvasElement;
    },
    dpr: 1,
    theme: {},
    syncGroup: "g",
    bench: false,
    listener: {
      deliver: (m) => events.push(m),
      lost: () => undefined,
      restored: () => undefined,
      resync: (store) => resyncs.push(store),
    },
  });
}

const one = (): {
  layout: { count: number; columns: { offset: number; bytes: 8 }[]; params: number[] };
  buffer: ArrayBuffer;
} => ({
  layout: { count: 1, columns: [{ offset: 0, bytes: 8 }], params: [] },
  buffer: new ArrayBuffer(8),
});

describe("backpressure", () => {
  it("keeps at most two batches in flight per store and conflates the overrun", () => {
    const host = hostOn(workerDoc());
    settle();
    const w = lastWorker();
    for (let i = 0; i < 6; i += 1) {
      const b = one();
      host.data("bars", "append", b.layout, b.buffer);
    }
    host.data("footprint", "replace", one().layout, one().buffer); // another store: own budget
    vi.advanceTimersByTime(0);
    expect(inboxOf(w, "data")).toHaveLength(3); // 2 bars + 1 footprint before any ack
    settle();
    const bars = (inboxOf(w, "data") as Extract<ToWorker, { t: "data" }>[]).filter(
      (m) => m.store === "bars",
    );
    expect(bars.map((m) => m.layout.count)).toEqual([1, 1, 4]); // the 3x overrun, concatenated
    expect(host.counters.conflated).toBe(3);
    expect(host.counters.messagesDropped).toBe(0);
    host.dispose();
  });

  it("drops the oldest held-back batch beyond the queue bound", () => {
    const host = hostOn(workerDoc());
    settle();
    const ops = [
      "append",
      "append",
      "append",
      "patch",
      "append",
      "patch",
      "append",
      "patch",
    ] as const;
    const resyncs: StoreId[] = [];
    const host2 = hostOn(workerDoc(), env, [], resyncs);
    for (const op of ops) host.data("bars", op, one().layout, one().buffer);
    expect(host.counters.messagesDropped).toBe(ops.length - 2 - MAX_QUEUED);
    for (const op of [...ops, ...ops]) host2.data("bars", op, one().layout, one().buffer);
    expect(resyncs).toEqual(["bars"]); // one request per overload episode
    settle(); // the acks drain the queue: the next drop asks again
    for (const op of [...ops, ...ops]) host2.data("bars", op, one().layout, one().buffer);
    expect(resyncs).toEqual(["bars", "bars"]);
    host2.dispose();
    host.dispose();
    host.data("bars", "append", one().layout, one().buffer); // after dispose: ignored
  });
});

describe("one message per frame", () => {
  it("coalesces input rows per kind, resizes and syncs", () => {
    const host = hostOn(workerDoc());
    settle();
    const w = lastWorker();
    for (let i = 0; i < 10; i += 1) host.input("pointer", [INPUT.move, i, 0, 0, 0, 1]);
    host.input("wheel", [INPUT.wheel, 0, 0, 3, 0, 1]);
    host.resize(10, 10, 1);
    host.resize(30, 20, 2);
    host.sync("g", [1, 2], null);
    host.sync("g", [3, 4], 3);
    settle();
    const inputs = inboxOf(w, "input") as Extract<ToWorker, { t: "input" }>[];
    expect(inputs.map((m) => [m.kind, m.events.length])).toEqual([
      ["pointer", 60],
      ["wheel", 6],
    ]);
    expect(inboxOf(w, "resize")).toEqual([{ t: "resize", id: 1, width: 30, height: 20, dpr: 2 }]);
    expect(inboxOf(w, "sync")).toEqual([
      { t: "sync", groupId: "g", timeRange: [3, 4], crosshair: 3 },
    ]);
    for (let i = 0; i < INPUT_MAX_ROWS + 5; i += 1)
      host.input("pointer", [INPUT.move, i, 0, 0, 0, 1]);
    expect(host.counters.conflated).toBe(5);
    // A button release on a full batch is never folded away: the batch goes out early.
    host.input("pointer", [INPUT.up, 9, 0, 0, 0, 1]);
    host.input("pointer", [INPUT.move, 10, 0, 0, 0, 1]);
    expect(host.counters.conflated).toBe(5);
    settle();
    const sent = (inboxOf(w, "input") as Extract<ToWorker, { t: "input" }>[]).slice(2);
    expect(sent.map((m) => m.events.length / 6)).toEqual([INPUT_MAX_ROWS, 2]);
    expect(sent[1]?.events[0]).toBe(INPUT.up);
    host.dispose();
    host.input("pointer", [0, 0, 0, 0, 0, 0]);
    host.resize(1, 1, 1);
    host.sync("g", [1, 2], null);
    host.command({ k: "release" });
    expect(host.exportPng()).resolves.toBeNull();
  });

  it("captures pointer (coalesced), wheel and size changes from the container", () => {
    const container = workerDoc();
    let onResize: (() => void) | null = null;
    const observed: unknown[] = [];
    (container.ownerDocument.defaultView as { ResizeObserver?: unknown }).ResizeObserver = class {
      constructor(cb: () => void) {
        onResize = cb;
      }
      observe(t: unknown): void {
        observed.push(t);
      }
      disconnect(): void {
        observed.length = 0;
      }
    };
    const host = hostOn(container);
    settle();
    const detach = captureInput(asHtml(container), host);
    const ev = (x: number, t: number): object => ({
      offsetX: x,
      offsetY: 1,
      buttons: 1,
      shiftKey: true,
      ctrlKey: false,
      altKey: true,
      metaKey: false,
      timeStamp: t,
      pointerType: "mouse",
    });
    container.dispatch("pointerdown", ev(1, 10));
    container.dispatch("pointermove", {
      ...ev(2, 11),
      getCoalescedEvents: () => [ev(2, 11), ev(3, 12)],
    });
    container.dispatch("pointermove", { ...ev(4, 13), getCoalescedEvents: () => [] });
    container.dispatch("pointerup", { ...ev(4, 14), pointerType: "touch" });
    container.dispatch("wheel", { ...ev(5, 15), deltaY: -40 });
    container.clientWidth = 300;
    (onResize as (() => void) | null)?.();
    settle();
    const w = lastWorker();
    const rows = (k: string): number[][] => {
      const m = (inboxOf(w, "input") as Extract<ToWorker, { t: "input" }>[]).find(
        (i) => i.kind === k,
      );
      const out: number[][] = [];
      for (let i = 0; i < (m?.events.length ?? 0); i += 6)
        out.push([...(m?.events.slice(i, i + 6) ?? [])]);
      return out;
    };
    expect(rows("pointer")).toEqual([
      [INPUT.down, 1, 1, 1, 5, 0],
      [INPUT.move, 2, 1, 1, 5, 1],
      [INPUT.move, 3, 1, 1, 5, 1],
      [INPUT.move, 4, 1, 1, 5, 1],
    ]);
    expect(rows("touch")).toEqual([[INPUT.up, 4, 1, 1, 5, 1]]);
    expect(rows("wheel")).toEqual([[INPUT.wheel, 5, 1, -40, 5, 1]]);
    expect(inboxOf(w, "resize")).toEqual([{ t: "resize", id: 1, width: 300, height: 100, dpr: 1 }]);
    expect(observed).toHaveLength(1);
    detach();
    expect(container.listeners.get("wheel")?.size).toBe(0);
    expect(observed).toHaveLength(0);
    host.dispose();
  });
});

describe("Scenario: Worker death is recovered", () => {
  it("re-initialises the worker on a fresh canvas and restores the scene within 2 s", async () => {
    const container = workerDoc();
    const chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
    const seen = record(chart);
    chart.timeScale.setVisibleRange({ from: 100, to: 200 });
    settle();
    const first = lastWorker();
    const oldCanvas = container.children[0];
    // An export in flight when the worker dies resolves null, so the screenshot rejects.
    const pending = chart.takeScreenshot().catch((e: Error) => e.message);
    first.kill();
    expect(seen["error"]).toEqual([
      expect.objectContaining({ code: ENGINE_WORKER_LOST, recoverable: true }),
    ]);
    expect((seen["error"]?.[0] as { message: string }).message).toMatch(
      /correlation id cv-test-\d+/,
    );
    vi.advanceTimersByTime(999);
    expect(FakeWorker.created).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeWorker.created).toHaveLength(2);
    const fresh = container.children[0] as FakeElement;
    expect(fresh).not.toBe(oldCanvas);
    expect(fresh.transferred).toBe(true);
    settle();
    const second = lastWorker();
    expect(inboxOf(second, "init")).toHaveLength(1);
    expect(inboxOf(second, "command")).toContainEqual(
      expect.objectContaining({ cmd: { k: "setViewport", timeStart: 100, timeEnd: 200 } }),
    );
    // The data layer pages the range the runtime derived (E11-S03: clamped in bar space).
    const r = chart.timeScale.getVisibleRange();
    expect(seen["visibleRangeNeedsData"]).toEqual([{ fromTime: r?.from, toTime: r?.to }]);
    expect((r?.from ?? 0) - 100).toBeCloseTo(0, 6);
    expect(chart.getStats().renderProfile).toBe("full");
    await expect(pending).resolves.toMatch(/could not be encoded/);
    chart.dispose();
  });

  it("surfaces the SCR-048 error with a correlation id after three failed restarts", () => {
    let calls = 0;
    env = fakeEnv({
      createWorker: () => {
        calls += 1;
        if (calls > 1) throw new Error("spawn failed");
        return new FakeWorker();
      },
    });
    const chart = createChart({ container: asHtml(workerDoc()), theme }) as ChartInternal;
    const seen = record(chart);
    settle();
    lastWorker().kill();
    vi.advanceTimersByTime(1000 + 2000 + 4000 - 1);
    expect(seen["error"]?.every((e) => (e as { recoverable: boolean }).recoverable)).toBe(true);
    vi.advanceTimersByTime(1);
    expect(calls).toBe(4); // the first worker plus three restarts
    const last = seen["error"]?.at(-1) as { code: string; message: string; recoverable: boolean };
    expect(last).toMatchObject({ code: ENGINE_WORKER_LOST, recoverable: false });
    expect(last.message).toMatch(/could not be restarted \(correlation id cv-test-\d+\)/);
    vi.advanceTimersByTime(10_000);
    expect(calls).toBe(4);
    chart.dispose();
  });

  it("counts a worker that dies before ready, or soon after it, against the budget", () => {
    const host = hostOn(workerDoc());
    settle();
    lastWorker().kill();
    vi.advanceTimersByTime(1000);
    lastWorker().kill(); // dies before its ready: the next wait is 2 s
    vi.advanceTimersByTime(1999);
    expect(FakeWorker.created).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeWorker.created).toHaveLength(3);
    settle(); // ready, then dies at once: no fresh budget, the next wait is 4 s
    lastWorker().kill();
    vi.advanceTimersByTime(3999);
    expect(FakeWorker.created).toHaveLength(3);
    vi.advanceTimersByTime(1);
    expect(FakeWorker.created).toHaveLength(4);
    settle();
    vi.advanceTimersByTime(HEALTHY_RESET_MS); // healthy for a while: the budget resets
    lastWorker().kill();
    vi.advanceTimersByTime(1000);
    expect(FakeWorker.created).toHaveLength(5);
    expect(host.counters.restarts).toBe(4);
    lastWorker().onmessageerror?.({});
    host.dispose();
    vi.advanceTimersByTime(1000); // no client left: no restart
    expect(FakeWorker.created).toHaveLength(5);
  });

  it("restores the last size, backing store and CSS box, after a resize and a worker loss", () => {
    const container = workerDoc();
    let onResize: () => void = () => undefined;
    const view = container.ownerDocument.defaultView as { devicePixelRatio: number } & Record<
      string,
      unknown
    >;
    view["ResizeObserver"] = class {
      constructor(cb: () => void) {
        onResize = cb;
      }
      observe(): void {}
      disconnect(): void {}
    };
    const chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
    chart.timeScale.setVisibleRange({ from: 1, to: 2 });
    settle();
    const canvasOf = (): FakeElement =>
      container.children.find((c) => c.tagName === "CANVAS") as FakeElement;
    const box = (c: FakeElement): unknown[] => [
      c.width,
      c.height,
      c.style["width"],
      c.style["height"],
    ];
    expect(box(canvasOf())).toEqual([200, 100, "200px", "100px"]);
    container.clientWidth = 300;
    container.clientHeight = 150;
    view.devicePixelRatio = 2;
    onResize();
    settle();
    expect(box(canvasOf())).toEqual([600, 300, "300px", "150px"]);
    lastWorker().kill();
    container.clientWidth = 320; // the container moves on while the worker is down
    vi.advanceTimersByTime(1000);
    settle();
    const second = lastWorker();
    expect(inboxOf(second, "init")).toEqual([expect.objectContaining({ dpr: 2 })]);
    expect(inboxOf(second, "resize")).toEqual([
      { t: "resize", id: 1, width: 300, height: 150, dpr: 2 },
    ]);
    // The last size sent wins until the observer reports the new one.
    expect(box(canvasOf())).toEqual([600, 300, "300px", "150px"]);
    onResize();
    settle();
    expect(box(canvasOf())).toEqual([640, 300, "320px", "150px"]);
    chart.dispose();
  });

  it("replays the retained LOD and series options and counts the batches a restart discards", () => {
    const host = hostOn(workerDoc());
    settle();
    host.command({ k: "setLod", candles: 1, footprint: 2 });
    host.command({ k: "setSeriesOptions", series: 0, options: { a: 1 } });
    host.command({ k: "setSeriesOptions", series: 0, options: { a: 2 } });
    host.command({ k: "addDrawing", drawingId: "d1", kind: "trend" });
    host.command({ k: "pickAt", x: 1, y: 1 }); // transient: never replayed
    for (const op of ["append", "patch", "append"] as const)
      host.data("bars", op, one().layout, one().buffer);
    lastWorker().kill(); // one batch held back when the worker died
    vi.advanceTimersByTime(1000);
    expect(host.counters.messagesDropped).toBe(1);
    settle();
    const cmds = (inboxOf(lastWorker(), "command") as Extract<ToWorker, { t: "command" }>[]).map(
      (m) => m.cmd,
    );
    expect(cmds).toEqual([
      { k: "setLod", candles: 1, footprint: 2 },
      { k: "setSeriesOptions", series: 0, options: { a: 2 } },
      { k: "addDrawing", drawingId: "d1", kind: "trend" },
    ]);
    host.dispose();
  });

  it("resolves a pending screenshot null once the worker is lost for good", async () => {
    let calls = 0;
    env = fakeEnv({
      createWorker: () => {
        calls += 1;
        if (calls > 1) throw new Error("spawn failed");
        return new FakeWorker();
      },
    });
    const chart = createChart({ container: asHtml(workerDoc()), theme });
    settle();
    const pending = chart.takeScreenshot().catch((e: Error) => e.message);
    lastWorker().kill();
    vi.advanceTimersByTime(7000);
    await expect(pending).resolves.toMatch(/could not be encoded/);
    chart.dispose();
  });

  it("a dead link's late dispose does not evict the page's new worker", () => {
    let fail = false;
    env = fakeEnv({
      createWorker: () => {
        if (fail) throw new Error("spawn failed");
        return new FakeWorker();
      },
    });
    // Charts on one document share a link: the dead one and its successor are on the same realm.
    const doc = workerDoc().ownerDocument;
    const onDoc = (): FakeElement => {
      const el = new FakeElement("div", doc);
      el.clientWidth = 100;
      el.clientHeight = 100;
      return el;
    };
    const first = createChart({ container: asHtml(onDoc()), theme });
    settle();
    fail = true;
    lastWorker().kill();
    vi.advanceTimersByTime(7000); // the budget is spent: the link is dead
    fail = false;
    const created = FakeWorker.created.length;
    const second = createChart({ container: asHtml(onDoc()), theme });
    expect(FakeWorker.created).toHaveLength(created + 1);
    first.dispose(); // the dead link's last client leaves
    const third = createChart({ container: asHtml(onDoc()), theme });
    expect(FakeWorker.created).toHaveLength(created + 1); // still the one new worker
    third.dispose();
    second.dispose();
  });
});

describe("worker mode falls back to inline when the worker cannot start", () => {
  it("runs inline when the worker cannot be created", () => {
    env = fakeEnv({
      createWorker: () => {
        throw new Error("SecurityError: blocked by CSP");
      },
    });
    const container = workerDoc();
    const chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
    expect(chart.runMode).toBe("inline");
    settle();
    const canvas = container.children.find((c) => c.tagName === "CANVAS") as FakeElement;
    expect(canvas.webgl2?.clears.length).toBeGreaterThan(0);
    chart.dispose();
  });

  it("runs inline on a fresh canvas when the canvas will not transfer", () => {
    const container = workerDoc();
    container.ownerDocument.offscreenThrows = true;
    const chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
    expect(chart.runMode).toBe("inline");
    expect(lastWorker().terminated).toBe(true); // the worker it spawned had no other chart
    settle();
    const canvases = container.children.filter((c) => c.tagName === "CANVAS");
    expect(canvases).toHaveLength(1);
    expect(canvases[0]?.webgl2?.clears.length).toBeGreaterThan(0);
    chart.dispose();
  });
});

describe("the page's host env", () => {
  it("loads the bundled worker from a same-origin module URL, never blob:", () => {
    const made: { url: unknown; opts: unknown }[] = [];
    vi.stubGlobal(
      "Worker",
      class {
        constructor(url: unknown, opts: unknown) {
          made.push({ url, opts });
        }
      },
    );
    try {
      const doc = new FakeDocument();
      const frames: unknown[] = [];
      (doc.defaultView as unknown as { requestAnimationFrame: unknown }).requestAnimationFrame = (
        cb: unknown,
      ) => frames.push(cb);
      const page = defaultHostEnv(doc as unknown as Document);
      page.createWorker();
      const url = made[0]?.url as URL;
      expect(url.protocol).not.toBe("blob:");
      expect(url.pathname.endsWith("/render-worker.js")).toBe(true);
      expect(made[0]?.opts).toEqual({ type: "module" });
      const cb = vi.fn();
      page.requestFrame(cb);
      expect(frames).toEqual([cb]);
      doc.defaultView = null;
      const bare = defaultHostEnv(doc as unknown as Document);
      bare.requestFrame(cb);
      bare.setTimer(cb, 5);
      vi.advanceTimersByTime(16);
      expect(cb).toHaveBeenCalledTimes(2);
      expect(typeof bare.now()).toBe("number");
      expect(bare.probe().profile).toBe("full");
      expect(bare.correlationId()).toMatch(/^cv-[0-9a-f]{12}-\d+$/);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
