// E12-S11 PR A1: the §8 facade routes series. `Pane.addSeries` of a bar kind (candles, hollow,
// OHLC bars) registers a runtime-backed series (`addSeries`, 26 §6) under a chart-unique id;
// its handle's `setData` / `append` / `prependHistory` send `data` tagged with that id (one host
// lane per series), and `remove` sends `removeSeries` once. Other kinds stay inert stubs. The
// host retains a live series' definition and replays it on a worker restart (not on the
// degraded-2d handoff, whose runtime keeps the DataModel), and drops a removed series' lane.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, setHostEnvFactory } from "../../src/api/chart.js";
import { createPane, type PaneHost } from "../../src/api/pane.js";
import type { CandleData, PaneId, ThemeTokens } from "../../src/index.js";
import type { HostEnv } from "../../src/worker/host.js";
import { ENGINE_SHADER_COMPILE_FAILED, type ToWorker } from "../../src/worker/protocol.js";
import { fakeEnv, FakeWorker } from "../worker/fake-worker.js";
import { asHtml, fakeContainer, FakeDocument, FakeElement } from "./fake-dom.js";

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: { "color.chart.background": "#0b0e11" },
};
const T0 = 1_700_000_000_000_000;
const MIN = 60e6;

const candles = (n: number, level = 1000): CandleData => ({
  time: Float64Array.from({ length: n }, (_, i) => T0 + i * MIN),
  open: new Int32Array(n).fill(level),
  high: new Int32Array(n).fill(level + 4),
  low: new Int32Array(n).fill(level),
  close: new Int32Array(n).fill(level + 4),
  volume: new Float32Array(n).fill(1),
  priceOrigin: 50_000,
  tickSize: 0.1,
});

type Call = [string, ...unknown[]];

function fakeHost(calls: Call[]): PaneHost {
  let seq = 0;
  return {
    onRemoved: (id) => void calls.push(["onRemoved", id]),
    assertLive: () => undefined,
    data: (store, op, _layout, _buffer, series) => void calls.push(["data", store, op, series]),
    addSeries(pane, kind): number {
      calls.push(["addSeries", pane, kind, seq]);
      return seq++;
    },
    removeSeries: (series) => void calls.push(["removeSeries", series]),
  };
}

describe("the pane facade routes series by id", () => {
  it("two series get their own ids and batches; other kinds stay inert", () => {
    const calls: Call[] = [];
    const pane = createPane("p" as PaneId, {}, fakeHost(calls));
    const a = pane.addSeries("candles", { upColorToken: "u", downColorToken: "d" });
    const b = pane.addSeries("bars", { upColorToken: "u", downColorToken: "d" });
    const fp = pane.addSeries("histogram", { colorToken: "x" });
    a.setData(candles(3));
    b.setData(candles(2));
    a.append(candles(1));
    b.prependHistory(candles(1));
    fp.remove();
    expect(calls).toEqual([
      ["addSeries", "p", "candles", 0],
      ["addSeries", "p", "bars", 1],
      ["data", "bars", "replace", 0],
      ["data", "bars", "replace", 1],
      ["data", "bars", "append", 0],
      ["data", "bars", "prepend", 1],
    ]);
  });

  it("remove sends removeSeries once and a removed handle refuses data", () => {
    const calls: Call[] = [];
    const pane = createPane("p" as PaneId, {}, fakeHost(calls));
    const a = pane.addSeries("hollow", { upColorToken: "u", downColorToken: "d" });
    a.remove();
    a.remove();
    expect(calls.filter((c) => c[0] === "removeSeries")).toEqual([["removeSeries", 0]]);
    expect(() => a.setData(candles(1))).toThrow(/series was removed/);
    expect(pane.seriesCount).toBe(0);
  });

  it("removing the pane removes its live series first", () => {
    const calls: Call[] = [];
    const pane = createPane("p" as PaneId, {}, fakeHost(calls));
    pane.addSeries("candles", { upColorToken: "u", downColorToken: "d" });
    pane.addSeries("bars", { upColorToken: "u", downColorToken: "d" }).remove();
    pane.addSeries("candles", { upColorToken: "u", downColorToken: "d" });
    pane.remove();
    expect(calls.slice(-3)).toEqual([
      ["removeSeries", 0],
      ["removeSeries", 2],
      ["onRemoved", "p"],
    ]);
  });
});

describe("Scenario: autoscale follows the main series through the facade (inline)", () => {
  beforeEach(() => void vi.useFakeTimers());
  afterEach(() => void vi.useRealTimers());

  it("setData reaches the series' store and the price scale fits it", () => {
    const chart = createChart({ container: asHtml(fakeContainer(400, 300)), theme });
    const pane = chart.addPane({});
    const s = pane.addSeries("candles", { upColorToken: "u", downColorToken: "d" });
    s.setData(candles(40, 1000));
    vi.advanceTimersByTime(16);
    const r = pane.priceScale.getVisibleRange();
    expect(r?.low).toBeGreaterThan(999);
    expect(r?.low).toBeLessThanOrEqual(1000);
    expect(r?.high).toBeGreaterThanOrEqual(1004);
    expect(r?.high).toBeLessThan(1005);
    s.remove();
    const t = pane.addSeries("candles", { upColorToken: "u", downColorToken: "d" });
    t.setData(candles(40, 3000));
    vi.advanceTimersByTime(16);
    expect(pane.priceScale.getVisibleRange()?.low).toBeGreaterThan(2999);
    chart.dispose();
  });
});

describe("the host keeps series definitions across a worker restart", () => {
  let env: HostEnv;

  function workerDoc(): FakeElement {
    const doc = new FakeDocument();
    doc.offscreenAvailable = true;
    doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
    const el = new FakeElement("div", doc);
    el.clientWidth = 200;
    el.clientHeight = 100;
    return el;
  }
  const settle = (): void => void vi.advanceTimersByTime(20);
  const lastWorker = (): FakeWorker => FakeWorker.created.at(-1) as FakeWorker;
  const sent = (w: FakeWorker): ToWorker[] => w.inbox as ToWorker[];
  const commands = (w: FakeWorker): object[] =>
    sent(w).flatMap((m) => (m.t === "command" ? [m.cmd] : []));
  const data = (w: FakeWorker): (number | undefined)[] =>
    sent(w).flatMap((m) => (m.t === "data" ? [m.series] : []));

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

  it("posts addSeries and per-series data, replays live series only after a restart", () => {
    const chart = createChart({ container: asHtml(workerDoc()), theme });
    const pane = chart.addPane({});
    const a = pane.addSeries("candles", { upColorToken: "u", downColorToken: "d" });
    const b = pane.addSeries("bars", { upColorToken: "u", downColorToken: "d" });
    a.setData(candles(5));
    b.setData(candles(5));
    settle();
    expect(commands(lastWorker())).toEqual([
      { k: "addSeries", series: 0, kind: "candles", pane: 0 },
      { k: "addSeries", series: 1, kind: "bars", pane: 0 },
    ]);
    expect(data(lastWorker())).toEqual([0, 1]);
    b.remove();
    settle();
    expect(commands(lastWorker()).at(-1)).toEqual({ k: "removeSeries", series: 1 });
    lastWorker().kill();
    vi.advanceTimersByTime(1000);
    settle();
    expect(commands(lastWorker())).toEqual([
      { k: "addSeries", series: 0, kind: "candles", pane: 0 },
    ]);
    chart.dispose();
  });

  it("drops a removed series' held batches, and the handoff replays no definition", () => {
    const chart = createChart({ container: asHtml(workerDoc()), theme });
    const pane = chart.addPane({});
    const a = pane.addSeries("candles", { upColorToken: "u", downColorToken: "d" });
    for (let i = 0; i < 4; i += 1) a.append(candles(1)); // two in flight, two held
    a.remove();
    settle();
    settle();
    expect(data(lastWorker())).toEqual([0, 0]); // the held two were never sent
    const w = lastWorker();
    const init = sent(w).find((m) => m.t === "init") as { id: number };
    pane.addSeries("candles", { upColorToken: "u", downColorToken: "d" });
    settle();
    const before = commands(w).length;
    const fail = { t: "error", id: init.id, code: ENGINE_SHADER_COMPILE_FAILED, message: "x" };
    w.onmessage?.({ data: { ...fail, recoverable: true } });
    settle();
    expect(sent(w).filter((m) => m.t === "init")).toHaveLength(2);
    expect(commands(w).slice(before)).not.toContainEqual(
      expect.objectContaining({ k: "addSeries" }),
    );
    chart.dispose();
  });
});
