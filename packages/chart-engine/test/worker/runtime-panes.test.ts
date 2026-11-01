// E11-S09 PR 1 in the render runtime (#446; README BQ-1 to BQ-6, BQ-10, BQ-14, BQ-23): panes
// stack on one shared time axis. Frames run on the `TestClock`; nothing reads the wall clock.
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { GLBackend } from "../../src/gl/backend.js";
import { CROSSHAIR_NODE_ID, type CrosshairNode } from "../../src/overlays/crosshair-node.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { SceneGraph } from "../../src/scene/index.js";
import { NullSeries } from "../../src/scene/null-series.js";
import {
  ChartViewport,
  columnSource,
  priceToScreen,
  type PriceExtentSource,
} from "../../src/viewport/index.js";
import {
  ENGINE_LAST_PANE,
  INPUT,
  KEY,
  PANE_LIMIT,
  type Command,
  type FromWorker,
} from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap, rows } from "../interaction/fixtures.js";
import { TestClock } from "../scene/test-clock.js";

type Of<T extends FromWorker["t"]> = Extract<FromWorker, { t: T }>;

/** A 2000-bar ladder of prices from `base` ticks. */
function ladder(base: number) {
  const cols = {
    low: new Int32Array(2000).map((_, i) => base + i),
    high: new Int32Array(2000).map((_, i) => base + 10 + i),
    close: new Int32Array(2000).map((_, i) => base + 5 + i),
    length: 2000,
  };
  return { cols, source: columnSource(() => cols) };
}

let out: FromWorker[];
let rt: RenderRuntime;
let gl: FakeGl;
let clock: TestClock;
let timers: { at: number; cb: () => void }[];
let sources: Map<number, PriceExtentSource[]>;
let graphs: MockInstance<SceneGraph["addPane"]>;

const of = <T extends FromWorker["t"]>(t: T): Of<T>[] => out.filter((m): m is Of<T> => m.t === t);
const cmd = (c: Command): void => rt.handle({ t: "command", id: 1, cmd: c });
const input = (kind: "pointer" | "wheel" | "key", ...r: number[][]): void =>
  rt.handle({ t: "input", id: 1, kind, events: rows(...r) });

/** One 16 ms frame, then any timer that fell due (the crosshair's rest). */
function step(n = 1): void {
  for (let i = 0; i < n; i += 1) {
    clock.tick(16);
    const due = timers.filter((t) => t.at <= clock.now());
    timers = timers.filter((t) => t.at > clock.now());
    for (const t of due) t.cb();
  }
}

function init(): void {
  rt.handle({
    t: "init",
    id: 1,
    canvas: { width: 1064, height: 624, getContext: () => gl },
    dpr: 1,
    theme: { "color.chart.background": "#0b0e11" },
    config: { bench: true, syncGroup: null },
  });
}

/** The main series' params (BQ-115): the axes and the grid need its tick size. */
function bars(): void {
  rt.handle({
    t: "data",
    id: 1,
    store: "bars",
    op: "replace",
    layout: { count: 0, columns: [], params: [0, 0.5] },
    buffer: new ArrayBuffer(0),
  });
}

/** Panes 1 and 2 below the first, at 60 / 20 / 20. */
function stack3(): void {
  cmd({ k: "addPane", pane: 1, share: 0.2, label: "Volume pane" });
  cmd({ k: "addPane", pane: 2, share: 0.2, label: "CVD pane" });
  cmd({
    k: "setPaneShares",
    shares: [
      [0, 0.6],
      [1, 0.2],
      [2, 0.2],
    ],
  });
}

const graph = (): SceneGraph => graphs.mock.contexts[0] as SceneGraph;
const lastFrame = (): Of<"frame"> | undefined => of("frame").at(-1);
const viewportOf = (pane: number) => of("viewport").filter((v) => v.pane === pane);

beforeEach(() => {
  out = [];
  timers = [];
  gl = new FakeGl({ params: ROOMY });
  clock = new TestClock();
  sources = new Map([[0, [ladder(100_000).source]]]);
  graphs = vi.spyOn(SceneGraph.prototype, "addPane");
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void clock.requestFrame(() => cb()),
    now: () => clock.now(),
    setTimer: (cb, ms) => void timers.push({ at: clock.now() + ms, cb }),
    probe: () => FULL,
    timeMap: minuteMap(),
    priceSources: (key) => sources.get(key) ?? [],
  });
  init();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Scenario: Panes cannot drift", () => {
  it("3 panes through a seeded 10 s pan, zoom and glide: one time state in every pane, every frame", () => {
    bars();
    stack3();
    step();
    const next = mulberry32(446_001);
    let glides = 0;
    for (let f = 0; f < 625; f += 1) {
      const op = Math.floor(next() * 8);
      const x = 40 + next() * 900;
      const y = 10 + next() * 560;
      if (op === 0) {
        // A drag with a fast release: the glide coasts over the next frames.
        const dx = (next() - 0.5) * 300;
        input("pointer", [INPUT.down, x, y, 1, 0, 0], [INPUT.move, x + dx / 2, y, 1, 0, 16]);
        input("pointer", [INPUT.move, x + dx, y, 1, 0, 16], [INPUT.up, x + dx, y, 0, 0, 4]);
        glides += 1;
      } else if (op === 1) input("wheel", [INPUT.wheel, x, y, (next() - 0.5) * 400, 0, 0]);
      else if (op === 2)
        input("key", [INPUT.key, next() < 0.5 ? KEY.zoomIn : KEY.zoomOut, 0, 0, 0, 0]);
      else if (op === 3) input("pointer", [INPUT.move, x, y, 0, 0, 16]);
      const before = of("layout").length;
      step();
      expect(of("layout").length - before, `frame ${f}`).toBeLessThanOrEqual(1);
      const stats = rt.paneStats(1) ?? [];
      expect(stats.map((s) => s.key)).toEqual([0, 1, 2]);
      const [first] = stats;
      for (const s of stats) {
        expect([s.timeStart, s.timeEnd, ...s.xWords], `frame ${f}, pane ${s.key}`).toEqual([
          first?.timeStart,
          first?.timeEnd,
          ...(first?.xWords ?? []),
        ]);
      }
    }
    expect(glides).toBeGreaterThan(20);
    // One shared time axis: one node, under the last pane, and one time label list.
    const timeAxes = graph()
      .walk()
      .filter((n) => n.kind === "time-axis");
    expect(timeAxes).toHaveLength(1);
    const layout = of("layout").at(-1);
    const lastPane = layout?.panes.at(-1);
    expect(layout?.timeAxis[0]).toBe((lastPane?.top ?? 0) + (lastPane?.height ?? 0));
    const axes = of("axes").at(-1);
    expect(axes?.time.length).toBeGreaterThan(0);
    expect(axes?.panes?.map((p) => [p.pane, Object.keys(p).sort()])).toEqual([
      [1, ["pane", "price"]],
      [2, ["pane", "price"]],
    ]);
  });

  it("the layout reports shares summing to exactly 1, the stack's rows and the labels", () => {
    stack3();
    step();
    const layout = of("layout").at(-1);
    expect(layout?.panes.map((p) => [p.pane, p.top, p.height, p.collapsed])).toEqual([
      [0, 0, 360, false],
      [1, 360, 120, false],
      [2, 480, 120, false],
    ]);
    expect(layout?.panes.reduce((s, p) => s + p.share, 0)).toBe(1);
    expect(layout?.timeAxis).toEqual([600, 24]);
    expect(rt.paneStats(1)?.map((s) => s.label)).toEqual(["Price pane", "Volume pane", "CVD pane"]);
    const posted = of("layout").length;
    cmd({ k: "setLod", candles: 0, footprint: 0 }); // a frame with no layout change
    step(3);
    expect(of("layout")).toHaveLength(posted);
    cmd({ k: "addPane", pane: 1, label: "Volume", share: 0.6 }); // a known key: relabel, reweigh
    step();
    // Weights 0.6 / 0.6 / 0.2 of a 600 px plot.
    expect(
      of("layout")
        .at(-1)
        ?.panes.map((p) => p.height),
    ).toEqual([257, 257, 86]);
    expect(rt.paneStats(1)?.[1]?.label).toBe("Volume");
  });
});

describe("Scenario: Adding or removing a pane re-uploads nothing", () => {
  /** A drawing node in `pane` with its own 2-instance ring. */
  function ring(pane: string): NullSeries {
    const s = Object.assign(new NullSeries(`${pane}/s`), { program: PROGRAM.quad, count: 2 });
    graph().addNode(pane, "series", s);
    const backend = vi.mocked(GLBackend.prototype.submit).mock.contexts[0] as GLBackend;
    backend.attach(s.id, { data: new Float32Array(16), head: 0, stride: 8 });
    cmd({ k: "setLod", candles: 0, footprint: 0 }); // wakes the scheduler: a frame collects it
    return s;
  }

  it("existing rings stay attached; removal frees only that pane's", () => {
    vi.spyOn(GLBackend.prototype, "submit");
    step();
    ring("main");
    step();
    expect(lastFrame()?.uploadedBytes).toBe(64); // the new ring, in full
    cmd({ k: "addPane", pane: 1, label: "Volume pane" });
    step();
    expect(lastFrame()?.uploadedBytes).toBe(0);
    expect(lastFrame()?.drawCalls).toBe(1);
    ring("pane-1");
    step();
    expect(lastFrame()?.uploadedBytes).toBe(64); // only the new pane's ring
    expect(lastFrame()?.drawCalls).toBe(2);
    const backend = vi.mocked(GLBackend.prototype.submit).mock.contexts[0] as GLBackend;
    const live = backend.registry.counts().live;
    cmd({ k: "removePane", pane: 1 });
    cmd({ k: "removePane", pane: 1 }); // unknown now: nothing
    step();
    expect(lastFrame()?.uploadedBytes).toBe(0);
    expect(lastFrame()?.drawCalls).toBe(1); // main/s still draws
    expect(backend.registry.counts().live).toBe(live - 2); // its buffer and VAO only
    expect(graph().get("pane-1/s")).toBeUndefined();
    expect(rt.paneStats(1)?.map((s) => s.key)).toEqual([0]);
  });

  it("removing the first pane keeps the chassis and moves the main series' scale to the next", () => {
    bars();
    cmd({ k: "addPane", pane: 1, label: "Volume pane" });
    step();
    cmd({ k: "removePane", pane: 0 });
    input("pointer", [INPUT.move, 300, 200, 0, 0, 16]);
    step(2);
    expect(rt.paneStats(1)?.map((s) => s.key)).toEqual([1]);
    expect(of("layout").at(-1)?.panes).toEqual([
      { pane: 1, top: 0, height: 600, share: 1, collapsed: false },
    ]);
    expect(of("crosshair").at(-1)).toMatchObject({ visible: true, pane: 1 });
    expect(of("error")).toEqual([]);
  });
});

describe("Scenario: The stack never drops to zero panes (lens M1)", () => {
  it("refuses the last pane's removal with a recoverable ENGINE_LAST_PANE", () => {
    cmd({ k: "removePane", pane: 0 });
    step();
    expect(of("error").map((e) => [e.code, e.recoverable])).toEqual([[ENGINE_LAST_PANE, true]]);
    expect(rt.paneStats(1)?.map((p) => p.key)).toEqual([0]);
    cmd({ k: "addPane", pane: 1, label: "Volume pane" });
    cmd({ k: "removePane", pane: 0 });
    cmd({ k: "removePane", pane: 1 }); // now the last one
    step();
    expect(rt.paneStats(1)?.map((p) => p.key)).toEqual([1]);
    expect(of("error")).toHaveLength(2);
  });

  it("seeded add / remove sequences: ladders, rows and slots stay in step; no pane -1 posted", () => {
    bars();
    const next = mulberry32(446_002);
    let key = 1;
    const live = [0];
    for (let n = 0; n < 200; n += 1) {
      if (live.length < 2 || (live.length < 6 && next() < 0.5)) {
        cmd({ k: "addPane", pane: key, label: `Pane ${key + 1}` });
        live.push(key);
        key += 1;
      } else {
        const gone = live.splice(Math.floor(next() * live.length), 1)[0] as number;
        cmd({ k: "removePane", pane: gone });
      }
      if (next() < 0.3) input("pointer", [INPUT.move, 300, next() * 600, 0, 0, 16]);
      const from = out.length;
      step();
      expect(
        rt.paneStats(1)?.map((p) => p.key),
        `step ${n}`,
      ).toEqual(live);
      expect(
        of("layout")
          .at(-1)
          ?.panes.map((p) => p.pane),
        `step ${n}`,
      ).toEqual(live);
      for (const m of out.slice(from)) {
        if (m.t === "axes")
          expect(m.panes?.map((p) => p.pane) ?? [], `step ${n}`).toEqual(live.slice(1));
      }
    }
    const keys = out.flatMap((m) => {
      if (m.t === "viewport" || m.t === "crosshair") return m.pane === undefined ? [] : [m.pane];
      if (m.t === "layout" || m.t === "axes") return (m.panes ?? []).map((p) => p.pane);
      return [];
    });
    expect(keys.length).toBeGreaterThan(200);
    expect(keys.every((k) => k >= 0)).toBe(true);
    expect(of("error")).toEqual([]);
  });
});

describe("Scenario: Each pane scales on its own", () => {
  it("autoscale fits each pane to its own sources; a change in one moves only that one", () => {
    const b = ladder(5_000);
    sources.set(1, [b.source]);
    cmd({ k: "addPane", pane: 1, label: "Volume pane" });
    step(2);
    const a0 = viewportOf(0).at(-1);
    const b0 = viewportOf(1).at(-1);
    expect(a0?.priceLow).toBeGreaterThan(99_000);
    expect(b0?.priceLow).toBeGreaterThan(4_000);
    expect(b0?.priceHigh).toBeLessThan(10_000);
    b.cols.high.fill(9_000);
    b.source.version += 1;
    cmd({ k: "setLod", candles: 0, footprint: 0 });
    step();
    expect(viewportOf(0).at(-1)?.priceLow).toBe(a0?.priceLow);
    expect(viewportOf(1).at(-1)?.priceHigh).toBeGreaterThan(b0?.priceHigh ?? 0);
  });

  it("a gutter drag, wheel and key act on the pane under the pointer", () => {
    cmd({ k: "addPane", pane: 1, label: "Volume pane" });
    step(2);
    const layout = of("layout").at(-1);
    const gx = (layout?.plotWidth ?? 0) + 10;
    const y1 = (layout?.panes[1]?.top ?? 0) + 40;
    input("pointer", [INPUT.down, gx, y1, 1, 0, 0], [INPUT.move, gx, y1 + 30, 1, 0, 16]);
    input("pointer", [INPUT.up, gx, y1 + 30, 0, 0, 16]);
    step();
    expect(viewportOf(1).at(-1)?.autoScale).toBe(false);
    expect(viewportOf(0).at(-1)?.autoScale).toBe(true);
    input("wheel", [INPUT.wheel, gx, 40, 120, 0, 0]); // over the first pane's gutter
    step();
    expect(viewportOf(0).at(-1)?.autoScale).toBe(false);
    input("pointer", [INPUT.dblclick, gx, y1, 0, 0, 0]); // the second pane's gutter: auto
    step();
    expect(viewportOf(1).at(-1)?.autoScale).toBe(true);
    input("pointer", [INPUT.move, 200, y1, 0, 0, 16]); // the price stop's keys follow the pointer
    input("key", [INPUT.key, KEY.up, 2, 0, 0, 0]);
    step();
    expect(viewportOf(1).at(-1)?.autoScale).toBe(false);
    expect(viewportOf(0).at(-1)?.autoScale).toBe(false);
  });

  it("setPriceScale addresses the stable key, never an index (BQ-1)", () => {
    cmd({ k: "addPane", pane: 1, label: "a" });
    cmd({ k: "addPane", pane: 2, label: "b" });
    cmd({ k: "removePane", pane: 1 });
    step();
    const posted = viewportOf(1).length;
    cmd({ k: "setPriceScale", pane: 2, inverted: true });
    cmd({ k: "setPriceScale", pane: 1, inverted: true }); // removed: nothing
    step();
    expect(viewportOf(2).at(-1)?.inverted).toBe(true);
    expect(viewportOf(0).at(-1)?.inverted).toBe(false);
    expect(viewportOf(1)).toHaveLength(posted);
  });
});

describe("Scenario: One pane ends above the time strip (lens M2, a deliberate correction)", () => {
  it("pane 0's rows are the canvas height minus the 24 px strip, and its prices map above it", () => {
    const sizes = vi.spyOn(ChartViewport.prototype, "setSize");
    init(); // a fresh chart, so the spy sees its viewport
    bars();
    step(2);
    const vp = sizes.mock.contexts.at(-1) as ChartViewport;
    const p = vp.panes[0];
    expect(p?.plotTop).toBe(0);
    expect(p?.plotHeight).toBe(624 - 24);
    for (const tick of [p?.priceLow ?? 0, p?.priceHigh ?? 0]) {
      const y = priceToScreen(vp, 0, tick);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(600); // never under the time strip
    }
  });
});

describe("the crosshair and the chassis across the stack", () => {
  it("the crosshair names the pane under the pointer and prices in its ticks (BQ-6)", () => {
    bars();
    stack3();
    step();
    input("pointer", [INPUT.move, 300, 400, 0, 0, 16]);
    step();
    expect(of("crosshair").at(-1)).toMatchObject({ visible: true, pane: 1 });
    input("pointer", [INPUT.move, 300, 100, 0, 0, 16]);
    step();
    expect(of("crosshair").at(-1)).toMatchObject({ visible: true, pane: 0 });
    input("pointer", [INPUT.leave, 0, 0, 0, 0, 0]);
    step();
    expect(of("crosshair").at(-1)?.visible).toBe(false);
    expect(of("crosshair").at(-1)?.pane).toBeUndefined();
  });

  it("3 panes: the lazy crosshair joins the over chassis, hides once, then idles without a write (BQ-6)", () => {
    bars();
    stack3();
    step();
    expect(graph().get(CROSSHAIR_NODE_ID)).toBeUndefined();
    input("pointer", [INPUT.move, 300, 540, 0, 0, 16]);
    step(2);
    const node = graph().get(CROSSHAIR_NODE_ID) as unknown as CrosshairNode;
    expect(node.count).toBeGreaterThan(0);
    expect(node.parent?.id).toBe("chart/over");
    expect(node.pane).toBeNull();
    expect(of("crosshair").at(-1)).toMatchObject({ visible: true, pane: 2 });

    const before = of("crosshair").length;
    input("pointer", [INPUT.leave, 0, 0, 0, 0, 0]);
    step();
    const hidden = of("crosshair").slice(before);
    expect(hidden).toHaveLength(1);
    expect(hidden[0]?.visible).toBe(false);
    expect(hidden[0]?.pane).toBeUndefined();
    expect(node.count).toBe(0);

    const write = vi.spyOn(node, "write");
    const posted = out.length;
    // A frame that does run the layout hook (a share change), with no crosshair to draw.
    cmd({
      k: "setPaneShares",
      shares: [
        [0, 0.5],
        [1, 0.25],
        [2, 0.25],
      ],
    });
    const frames = of("frame").length;
    step();
    expect(of("frame").length).toBeGreaterThan(frames);
    expect(write).not.toHaveBeenCalled();
    expect(out.slice(posted).filter((m) => m.t === "crosshair")).toEqual([]);
    expect(graph().get(CROSSHAIR_NODE_ID)).toBe(node);
    expect(node.parent?.id).toBe("chart/over");

    cmd({ k: "removePane", pane: 1 });
    step();
    expect(graph().get(CROSSHAIR_NODE_ID)).toBe(node);
    input("pointer", [INPUT.move, 300, 540, 0, 0, 16]);
    write.mockClear();
    step();
    expect(write).toHaveBeenCalledTimes(1);
    expect(of("crosshair").at(-1)).toMatchObject({ visible: true, pane: 2 });
  });

  it.each([1, 2, 3, 4])(
    "the grid and the crosshair cost 2 draws with %d pane(s) (BQ-23 guard)",
    (n) => {
      bars();
      for (let k = 1; k < n; k += 1) cmd({ k: "addPane", pane: k, label: `Pane ${k + 1}` });
      step();
      input("pointer", [INPUT.move, 300, 30, 0, 0, 16]);
      step(2);
      expect(of("crosshair").at(-1)?.visible).toBe(true);
      expect(lastFrame()?.drawCalls).toBe(2);
    },
  );

  it("the degraded-2d re-init keeps the panes, their labels and shares (BQ-10)", () => {
    stack3();
    cmd({ k: "removePane", pane: 0 });
    step();
    const before = of("layout").at(-1)?.panes;
    const ctx = new FakeCtx2D();
    rt.handle({
      t: "init",
      id: 1,
      canvas: { width: 1064, height: 624, getContext: () => ctx },
      dpr: 1,
      theme: {},
      config: { bench: true, syncGroup: null },
      profile: "degraded-2d",
    });
    step();
    expect(rt.paneStats(1)?.map((s) => [s.key, s.label])).toEqual([
      [1, "Volume pane"],
      [2, "CVD pane"],
    ]);
    expect(of("layout").at(-1)?.panes).toEqual(before);
  });

  it("refuses a pane past the limit with a recoverable error", () => {
    for (let k = 1; k <= PANE_LIMIT; k += 1) cmd({ k: "addPane", pane: k, label: "p" });
    expect(rt.paneStats(1)).toHaveLength(PANE_LIMIT);
    expect(of("error").map((e) => e.recoverable)).toEqual([true]);
  });
});
