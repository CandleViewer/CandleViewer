// E11-S06 through the runtime (README BQ-192 to BQ-201): the keyboard rescale, the `axes` message
// as the DOM mirror's source, the master clock, crisp hairlines and the measured gutter. Frames by
// hand on fake timers; the host stops and the announcer are test/api/axes.test.ts's.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AxisGrid, TIER } from "../../src/axes/grid.js";
import { Gestures } from "../../src/interaction/gestures.js";
import { REGION, regionAt } from "../../src/interaction/wheel.js";
import {
  ChartViewport,
  columnSource,
  createPaneUniforms,
  writePaneUniforms,
} from "../../src/viewport/index.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { INPUT, KEY, rejectReason, type FromWorker } from "../../src/worker/protocol.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap, rows } from "../interaction/fixtures.js";

type Axes = Extract<FromWorker, { t: "axes" }>;
type Viewport = Extract<FromWorker, { t: "viewport" }>;

let out: FromWorker[];
let rt: RenderRuntime;
const cols = {
  low: new Int32Array(2000).map((_, i) => 127_800 + (i % 50)),
  high: new Int32Array(2000).map((_, i) => 128_500 + (i % 50)),
  close: new Int32Array(2000).map((_, i) => 128_100 + (i % 50)),
  length: 2000,
};
const frame = (): void => void vi.advanceTimersByTime(16);
const axes = (): Axes[] => out.filter((m): m is Axes => m.t === "axes");
const viewport = (): Viewport | undefined =>
  out.filter((m): m is Viewport => m.t === "viewport").at(-1);
const key = (code: number, target: number, mods = 0): void =>
  rt.handle({
    t: "input",
    id: 1,
    kind: "key",
    events: rows([INPUT.key, code, target, 0, mods, 0]),
  });

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  const gl = new FakeGl({ params: ROOMY });
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap: minuteMap(),
    priceSources: [columnSource(() => cols)],
  });
  const canvas = { width: 1264, height: 624, getContext: () => gl };
  rt.handle({
    t: "init",
    id: 1,
    canvas,
    dpr: 1,
    theme: {},
    config: { bench: true, syncGroup: null },
  });
  rt.handle({
    t: "data",
    id: 1,
    store: "bars",
    op: "replace",
    layout: { count: 0, columns: [], params: [0, 0.5] }, // BTC-like: tick 0.5
    buffer: new ArrayBuffer(0),
  });
  frame();
  frame();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Scenario: The price axis rescales by keyboard", () => {
  it("Up ×5 compresses the range one 10 % step per press and Home restores auto-fit", () => {
    const span = (): number => (viewport()?.priceHigh ?? 0) - (viewport()?.priceLow ?? 0);
    const said: (string | undefined)[] = [];
    let before = span();
    for (let i = 0; i < 5; i += 1) {
      key(KEY.up, 2);
      frame();
      expect(span() / before).toBeCloseTo(0.9, 6);
      before = span();
      said.push(axes().at(-1)?.say);
    }
    expect(viewport()?.autoScale).toBe(false);
    expect(said[0]).toBe("Price scale locked"); // the first engagement, then the range
    expect(said[1]).toMatch(/^[\d,]+\.\d to [\d,]+\.\d$/);
    key(KEY.home, 2);
    frame();
    expect(viewport()?.autoScale).toBe(true);
    expect(axes().at(-1)?.say).toBe("Price scale: auto");
    expect(axes().at(-1)?.priceName).toMatch(/^Price axis, .+, linear, auto$/);
  });

  it("the time stop pans 10 % and zooms about the centre; the plot keys are unchanged", () => {
    const spacing = viewport()?.barSpacing ?? 0;
    key(KEY.zoomIn, 1);
    frame();
    expect(viewport()?.barSpacing).toBeCloseTo(spacing * 1.1, 6);
    expect(axes().at(-1)?.say).toBe(`${Math.round(spacing * 1.1)} pixels per bar`);
    const start = viewport()?.timeStart ?? 0;
    key(KEY.left, 1);
    frame();
    expect(viewport()?.timeStart).toBeLessThan(start);
    expect(axes().at(-1)?.say).toMatch(/ to /);
    key(KEY.up, 0); // the plot target ignores the axis codes
    frame();
    expect(viewport()?.autoScale).toBe(true);
  });

  it("an unknown target is rejected at the boundary", () => {
    expect(
      rejectReason({ t: "input", id: 1, kind: "key", events: rows([INPUT.key, 9, 3, 0, 0, 0]) }),
    ).toBe("a key row with an unknown target");
    const cfg = { bench: false, syncGroup: null, timeZone: 7 };
    const canvas = { width: 1, height: 1, getContext: () => null };
    expect(rejectReason({ t: "init", id: 2, canvas, dpr: 1, theme: {}, config: cfg })).toBe(
      "malformed init",
    );
  });
});

describe("Scenario: Tick labels are present in the accessibility tree", () => {
  it("the axes message carries the frame's retained labels, only when they change", () => {
    const msg = axes().at(-1) as Axes;
    expect(msg.price.length).toBeGreaterThan(2);
    expect(msg.time.length).toBeGreaterThan(2);
    expect(msg.timeZone).toBe("UTC");
    expect(msg.price.every((p) => /^[\d,]+\.\d$/.test(p))).toBe(true); // tick 0.5: one decimal
    const posted = out.length;
    frame(); // a still frame posts nothing new
    expect(out.slice(posted).filter((m) => m.t === "axes")).toHaveLength(0);
  });

  it("a slow pan posts `axes` only on frames whose labels or names changed (BQ-199)", () => {
    const posted = axes().length;
    const drag = (x: number, type: number): void =>
      rt.handle({ t: "input", id: 1, kind: "pointer", events: rows([type, x, 300, 1, 0, 0]) });
    drag(600, INPUT.down);
    for (let f = 1; f <= 40; f += 1) {
      drag(600 + f, INPUT.move); // 1 px a frame
      frame();
    }
    const moved = axes().slice(posted - 1); // the last pre-pan message, then the pan's
    expect(moved.length - 1).toBeGreaterThan(0);
    expect(moved.length - 1).toBeLessThan(40); // not one per frame
    for (let i = 1; i < moved.length; i += 1) {
      const [a, b] = [moved[i - 1] as Axes, moved[i] as Axes];
      const same =
        a.price.join("|") === b.price.join("|") &&
        a.time.join("|") === b.time.join("|") &&
        a.priceName === b.priceName &&
        a.timeName === b.timeName &&
        a.priceGutter === b.priceGutter &&
        b.say === undefined;
      expect(same).toBe(false); // every message carries a change
    }
  });

  it("the gutter is measured from the widest label and the regions follow it (BQ-201)", () => {
    const g = axes().at(-1)?.priceGutter ?? 0;
    expect(g).toBe(Math.ceil("99,999.9".length * 6.6) + 8);
    expect(regionAt(1264 - g, 10, 1264, 624, g)).toBe(REGION.price);
    expect(regionAt(1264 - g - 1, 10, 1264, 624, g)).toBe(REGION.plot);
  });
});

describe("Scenario: The time axis is the master clock for every pane", () => {
  it("one time-axis drag changes every pane's bar spacing in the same frame", () => {
    const vp = new ChartViewport(minuteMap(), 3);
    vp.setSize(1200, 900, 1);
    for (let p = 0; p < 3; p += 1) vp.setPanePlot(p, p * 300, 300);
    const gestures = new Gestures(
      vp,
      { width: 1264, height: 924 },
      {
        moved: () => undefined,
        hover: () => undefined,
        animate: () => undefined,
      },
    );
    const blocks = [0, 1, 2].map(() => createPaneUniforms());
    gestures.apply(false, rows([INPUT.down, 600, 910, 1, 0, 0], [INPUT.move, 660, 910, 1, 0, 16]));
    blocks.forEach((b, p) => writePaneUniforms(vp, p, b));
    expect(blocks.map((b) => b.floats[0])).toEqual([0, 0, 0].map(() => Math.fround(vp.barSpacing)));
    expect(vp.barSpacing).toBeGreaterThan(6);
  });
});

describe("Scenario: Hairlines are crisp at fractional DPR", () => {
  it.each([1, 1.25, 2])("dpr %d: every line covers whole device pixels", (dpr) => {
    const g = new AxisGrid("g");
    g.begin(dpr, Math.round(600 * dpr));
    for (const y of [10.3, 99.9, 333.33]) g.hLine(y, 0, 100, TIER.minor);
    for (const x of [7.7, 512.4]) g.vLine(x, 0, 600, TIER.major);
    g.vLine(40.2, 0, 600, TIER.boundary, true);
    const w = Math.max(1, Math.floor(dpr));
    for (let i = 0; i < g.count; i += 1) {
      const [x0, y0, x1, y1, width] = g.data.slice(i * 9, i * 9 + 5);
      expect(width).toBe(w);
      const across = y0 === y1 ? (y0 as number) : (x0 as number); // the axis the width spans
      expect(Number.isInteger(across - w / 2)).toBe(true); // edge on the device grid: no fringe
      expect(y0 === y1 || x0 === x1).toBe(true);
    }
    expect(g.count).toBeGreaterThan(5); // the boundary is dashed into segments
  });

  it.todo("golden: a single-pixel line with no grey fringe at dpr 1.25 (E11-T08, G-48)");
});
