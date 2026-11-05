// E14-T04 (#359) at the facade: the §8 selection methods become their §6 commands, and the
// worker's `selection`, `drawingsChanged`, `refused` and `bounds` messages become the §8 events
// and the `getDrawingBounds` reply (anchors as { time, price }, handles as 24 px target squares).
// Worker mode over the fake worker, so the test can play the worker's side of the boundary.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, setHostEnvFactory } from "../../src/api/chart.js";
import { ThemeIngestError } from "../../src/theme/ThemeIngest.js";
import type { Chart, ChartEvents, ThemeTokens } from "../../src/index.js";
import type { FromWorker } from "../../src/worker/protocol.js";
import { asHtml, FakeDocument, FakeElement } from "./fake-dom.js";
import { fakeEnv, FakeWorker } from "../worker/fake-worker.js";

const theme: ThemeTokens = { palette: "default", convention: "standard", colors: {} };

function mount(t = theme): { chart: Chart; worker: FakeWorker; reply: (m: object) => void } {
  const doc = new FakeDocument();
  doc.offscreenAvailable = true;
  const ResizeObserver = class {
    observe(): void {}
    disconnect(): void {}
  };
  doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {}, ResizeObserver };
  const el = new FakeElement("div", doc);
  el.clientWidth = 400;
  el.clientHeight = 200;
  const chart = createChart({ container: asHtml(el), theme: t, runMode: "worker" });
  vi.advanceTimersByTime(20);
  const worker = FakeWorker.created[0] as FakeWorker;
  const init = worker.inbox.find((m) => (m as { t: string }).t === "init") as { id: number };
  const reply = (m: object): void => worker.onmessage?.({ data: { id: init.id, ...m } });
  return { chart, worker, reply };
}

const commands = (w: FakeWorker): unknown[] =>
  w.inbox
    .filter((m) => (m as { t: string }).t === "command")
    .map((m) => (m as { cmd: unknown }).cmd);

beforeEach(() => {
  vi.useFakeTimers();
  FakeWorker.created = [];
  setHostEnvFactory(() => fakeEnv());
});

afterEach(() => {
  setHostEnvFactory(null);
  vi.useRealTimers();
});

describe("the selection methods", () => {
  it("each is one command; a fractional nudge throws", () => {
    const { chart, worker } = mount();
    chart.setSelection(["a"], "replace");
    chart.selectAll();
    chart.setInteractionMode("select-area", { readOnly: true });
    chart.setInteractionMode("cursor");
    chart.focusObject("a", 1);
    chart.focusObject(null);
    chart.nudgeSelection(1, -2);
    chart.deleteSelection();
    chart.cancelDrag();
    chart.setTheme({ ...theme, metrics: { dragThresholdPx: 6 } });
    expect(() => chart.nudgeSelection(0.5, 0)).toThrow(RangeError);
    vi.advanceTimersByTime(20);
    expect(commands(worker)).toEqual([
      { k: "setSelection", ids: ["a"], op: "replace" },
      { k: "selectAll", pane: 0 },
      { k: "setInteractionMode", mode: "select-area", readOnly: true },
      { k: "setInteractionMode", mode: "cursor" },
      { k: "focusObject", drawingId: "a", handle: 1 },
      { k: "focusObject", drawingId: null },
      { k: "nudgeSelection", bars: 1, ticks: -2 },
      { k: "deleteSelection" },
      { k: "cancelDrag" },
      { k: "setTheme", theme: {}, metrics: { dragThresholdPx: 6 } },
    ]);
    chart.dispose();
    chart.setSelection(["a"], "add"); // a disposed chart ignores them
    chart.cancelDrag();
  });
});

describe("the worker's messages as §8 events", () => {
  it("selection, drawingsChanged and refused, copied per event", () => {
    const { chart, reply } = mount();
    const seen: unknown[] = [];
    chart.subscribe("selection", (e) => seen.push(["selection", e]));
    chart.subscribe("drawingsChanged", (e) => seen.push(["changed", e]));
    chart.subscribe("refused", (e) => seen.push(["refused", e]));
    reply({ t: "selection", ids: ["a"], focused: "a", handle: 1, mode: "cursor" });
    reply({ t: "selection", ids: [], focused: null, handle: -1, mode: "select-area" });
    const changes = [{ id: "a", anchors: [1e15, 10, 1e15 + 6e7, 12] }];
    reply({ t: "drawingsChanged", phase: "commit", intent: "move", changes });
    reply({ t: "refused", ids: ["l"], reason: "locked", intent: "resize" });
    expect(seen).toEqual([
      ["selection", { ids: ["a"], focused: { id: "a", handle: 1 }, mode: "cursor" }],
      ["selection", { ids: [], focused: null, mode: "select-area" }],
      [
        "changed",
        {
          phase: "commit",
          intent: "move",
          changes: [
            {
              id: "a",
              anchors: [
                { time: 1e15, price: 10 },
                { time: 1e15 + 6e7, price: 12 },
              ],
            },
          ],
        } satisfies ChartEvents["drawingsChanged"],
      ],
      ["refused", { ids: ["l"], reason: "locked", intent: "resize" }],
    ]);
    chart.dispose();
  });

  it("getDrawingBounds resolves its own reply; dispose resolves the rest empty", async () => {
    const { chart, reply } = mount();
    const first = chart.getDrawingBounds(["a"]); // reqId 1
    const second = chart.getDrawingBounds(["b"]); // reqId 2
    // Answered here, before the real worker's own (empty) replies arrive and find none pending.
    const item = { id: "a", rect: [10, 20, 110, 70], handles: [10, 20, 110, 70] };
    reply({ t: "bounds", reqId: 1, items: [item] } satisfies Omit<
      Extract<FromWorker, { t: "bounds" }>,
      "id"
    >);
    await expect(first).resolves.toEqual([
      {
        id: "a",
        rect: { x: 10, y: 20, w: 100, h: 50 },
        handles: [
          { x: -2, y: 8, w: 24, h: 24 },
          { x: 98, y: 58, w: 24, h: 24 },
        ],
      },
    ]);
    chart.dispose();
    await expect(second).resolves.toEqual([]);
    await expect(chart.getDrawingBounds(["c"])).resolves.toEqual([]);
  });
});

describe("ThemeTokens.metrics at the facade (BQ-02)", () => {
  it("init forwards them as one setTheme; the bounds use the resolved target size", async () => {
    const { chart, worker, reply } = mount({ ...theme, metrics: { handleTargetPx: 40 } });
    vi.advanceTimersByTime(20);
    expect(commands(worker)).toEqual([
      { k: "setTheme", theme: {}, metrics: { handleTargetPx: 40 } },
    ]);
    const box = chart.getDrawingBounds(["a"]);
    reply({ t: "bounds", reqId: 1, items: [{ id: "a", rect: [0, 0, 1, 1], handles: [50, 50] }] });
    await expect(box).resolves.toMatchObject([{ handles: [{ x: 30, y: 30, w: 40, h: 40 }] }]);
    chart.dispose();
  });

  it("a field out of range throws ENGINE_THEME_INVALID and changes nothing", () => {
    const { chart, worker } = mount();
    expect(() => chart.setTheme({ ...theme, metrics: { handleTargetPx: 12 } })).toThrow(
      ThemeIngestError,
    );
    vi.advanceTimersByTime(20);
    expect(commands(worker)).toEqual([]);
    chart.dispose();
  });
});
