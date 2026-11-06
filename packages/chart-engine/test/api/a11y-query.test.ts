// E11-S13 PR-1: the query surface returns engine truth. The render runtime computes the a11y
// window from its own state and posts it; the facade's getters serve the decoded message.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readA11yUpdate } from "../../src/a11y/window.js";
import { createChart } from "../../src/api/chart.js";
import type { A11yWindow, CursorOrigin, ThemeTokens } from "../../src/index.js";
import type { ChartHostOptions } from "../../src/worker/host.js";
import { BACKGROUND_TOKEN, type FromWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FULL } from "../gl/fake-gl.js";
import { asHtml, fakeContainer } from "./fake-dom.js";
import type * as HostModule from "../../src/worker/host.js";

const captured: { deliver: ((m: FromWorker) => void) | null } = { deliver: null };
vi.mock("../../src/worker/host.js", async (importOriginal) => {
  const actual = await importOriginal<typeof HostModule>();
  return {
    ...actual,
    createChartHost: (o: ChartHostOptions) => {
      captured.deliver = o.listener.deliver;
      return actual.createChartHost(o);
    },
  };
});

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: { "color.chart.background": "#0b0e11" },
};

const MIN = 60e6;
const N = 1000;
const timeMap = {
  length: N,
  indexToTime: (i: number) => (i >= 0 && i < N ? i * MIN : Number.NaN),
  timeToIndex: (t: number) => Math.min(N - 1, Math.floor(t / MIN)),
};
let out: FromWorker[];
let rt: RenderRuntime;
const a11y = (): Extract<FromWorker, { t: "a11y" }>[] =>
  out.filter((m): m is Extract<FromWorker, { t: "a11y" }> => m.t === "a11y");
const frame = (): void => {
  vi.advanceTimersByTime(16);
};

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Date.now(),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap,
  });
  const ctx = new FakeCtx2D();
  rt.handle({
    t: "init",
    id: 1,
    canvas: { width: 400, height: 100, getContext: () => ctx },
    dpr: 1,
    theme: { [BACKGROUND_TOKEN]: "#000000" },
    config: { bench: false, syncGroup: null },
  });
  frame();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the worker posts the a11y window from its own state", () => {
  it("follows the latest bar with the 60-row window on the first frame", () => {
    expect(a11y()).toHaveLength(1);
    expect(a11y()[0]).toMatchObject({ cursorBar: 999, cursorTime: 999 * MIN, firstBar: 940 });
    expect(a11y()[0]).toMatchObject({ lastBar: 999, candleTier: "L0", origin: "data" });
  });

  it("posts a visible-range-only change on its frame, frame-synchronized (05 §6.1)", () => {
    for (let k = 1; k <= 5; k += 1) {
      rt.handle({
        t: "command",
        id: 1,
        cmd: { k: "setViewport", timeStart: k * 10 * MIN, timeEnd: (k * 10 + 50) * MIN },
      });
      frame();
      expect(a11y()).toHaveLength(1 + k);
      expect(a11y().at(-1)).toMatchObject({ viewFirstBar: k * 10, cursorBar: 999, firstBar: 940 });
    }
    vi.advanceTimersByTime(4000);
    expect(a11y()).toHaveLength(6); // no trailing timer: nothing posts without a change
  });

  it("posts a tier change on its frame and nothing after a release", () => {
    rt.handle({ t: "command", id: 1, cmd: { k: "setLod", candles: 2, footprint: 3 } });
    frame();
    expect(a11y().at(-1)).toMatchObject({ candleTier: "L2", footprintTier: "L3" });
    rt.handle({ t: "command", id: 1, cmd: { k: "setViewport", timeStart: 0, timeEnd: 9 * MIN } });
    frame();
    const posted = a11y().length;
    rt.handle({ t: "command", id: 1, cmd: { k: "release" } });
    vi.advanceTimersByTime(4000);
    expect(a11y()).toHaveLength(posted);
  });
});

describe("the facade serves the worker's message (E06-D03 D9)", () => {
  it("answers every query from the last a11y message and feeds each one once", () => {
    const chart = createChart({ container: asHtml(fakeContainer(400, 300)), theme });
    expect(chart.getA11yWindow().lastBar).toBe(-1);
    const seen: [A11yWindow, unknown, CursorOrigin][] = [];
    const off = chart.onA11yWindowChange((w, rows, o) => seen.push([w, rows, o]));
    const msg = a11y()[0];
    if (msg === undefined) throw new Error("no a11y message");
    const truth = readA11yUpdate(msg);
    captured.deliver?.(msg);
    expect(chart.getA11yWindow()).toEqual(truth?.window);
    expect(seen).toEqual([[truth?.window, null, "data"]]);
    expect(chart.getVisibleWindow()).toEqual({
      timeStart: msg.viewTimeStart,
      timeEnd: msg.viewTimeEnd,
      firstBarIndex: msg.viewFirstBar,
      lastBarIndex: msg.viewLastBar,
    });
    expect(chart.getFocusedUnit()).toBeNull(); // no pane yet
    const pane = chart.addPane({});
    expect(chart.getFocusedUnit()).toEqual({ kind: "bar", paneId: pane.id, barIndex: 999 });
    captured.deliver?.({ t: "a11y", id: 0, cursorSummary: "old worker" });
    expect(chart.getA11yWindow()).toEqual(truth?.window); // the cache is kept
    off();
    captured.deliver?.(msg);
    expect(seen).toHaveLength(1);
    chart.dispose();
  });

  it("never feeds listeners a hover-only summary change (E06-D03 D6)", () => {
    const chart = createChart({ container: asHtml(fakeContainer(400, 300)), theme });
    const msg = a11y()[0];
    if (msg === undefined) throw new Error("no a11y message");
    captured.deliver?.(msg);
    const cb = vi.fn();
    chart.onA11yWindowChange(cb);
    captured.deliver?.({ ...msg, cursorSummary: "hovered bar 12" });
    captured.deliver?.({ ...msg, cursorSummary: "" });
    expect(cb).not.toHaveBeenCalled();
    captured.deliver?.({ ...msg, viewFirstBar: (msg.viewFirstBar ?? 0) + 1 });
    expect(cb).toHaveBeenCalledTimes(1);
    chart.dispose();
  });

  it("tears down: unsubscribe and dispose stop the feed; a late subscribe is a no-op", () => {
    const chart = createChart({ container: asHtml(fakeContainer(400, 300)), theme });
    const msg = a11y()[0];
    if (msg === undefined) throw new Error("no a11y message");
    const off = vi.fn();
    const kept = vi.fn();
    chart.onA11yWindowChange(off)();
    chart.onA11yWindowChange(kept);
    captured.deliver?.(msg);
    expect([off.mock.calls.length, kept.mock.calls.length]).toEqual([0, 1]);
    chart.dispose();
    captured.deliver?.({ ...msg, viewFirstBar: (msg.viewFirstBar ?? 0) + 1 });
    expect(kept).toHaveBeenCalledTimes(1);
    const late = vi.fn();
    const unsubscribe = chart.onA11yWindowChange(late);
    captured.deliver?.({ ...msg, viewFirstBar: (msg.viewFirstBar ?? 0) + 2 });
    expect(late).not.toHaveBeenCalled();
    expect(unsubscribe()).toBeUndefined();
  });
});
