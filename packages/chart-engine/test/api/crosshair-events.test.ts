// E11-S07 through the §8 facade (BQ-9, BQ-10, BQ-11, BQ-23): the crosshair event fires on a bar
// edge only, the readout event on every crosshair or readout change, the magnet is an option and
// a setter announced politely under its own key, and the focused unit waits for a key cursor.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, magnetText, setHostEnvFactory } from "../../src/api/chart.js";
import type { ChartEvents, ReadoutEvent } from "../../src/api/types.js";
import { ANNOUNCE_EVENT, MAGNET_ANNOUNCE_KEY } from "../../src/host/axis-stop.js";
import type { FromWorker, ToWorker } from "../../src/worker/protocol.js";
import { fakeEnv, FakeWorker } from "../worker/fake-worker.js";
import { asHtml, fakeContainer, FakeDocument, FakeElement } from "./fake-dom.js";

const theme = { palette: "default", convention: "standard", colors: {} } as const;
const frames = (n = 1): void => void vi.advanceTimersByTime(16 * n);
const pointer = (x: number, y: number, t: number): object => ({
  offsetX: x,
  offsetY: y,
  buttons: 0,
  shiftKey: false,
  ctrlKey: false,
  altKey: false,
  metaKey: false,
  timeStamp: t,
  pointerType: "mouse",
});

/** A container whose view can build the announce event (the shell's listener reads `detail`). */
function container(): FakeElement {
  const c = fakeContainer(800, 400);
  const view = c.ownerDocument.defaultView as { CustomEvent?: unknown };
  view.CustomEvent = class {
    readonly detail: unknown;
    constructor(
      readonly type: string,
      init: { detail: unknown },
    ) {
      this.detail = init.detail;
    }
  };
  return c;
}

function bars(chart: ReturnType<typeof createChart>): void {
  const n = 4;
  const close = new Int32Array(n).fill(128_000);
  chart
    .addPane({})
    .addSeries("candles", { upColorToken: "u", downColorToken: "d" })
    .setData({
      time: Float64Array.from({ length: n }, (_, i) => i * 60e6),
      open: close,
      high: close,
      low: close,
      close,
      volume: new Float32Array(n),
      priceOrigin: 0,
      tickSize: 0.5,
    });
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeWorker.created = [];
  setHostEnvFactory(() => fakeEnv());
});

afterEach(() => {
  setHostEnvFactory(null);
  vi.useRealTimers();
});

describe("AC5: crosshair events are edge-triggered (BQ-10, BQ-11)", () => {
  it("test_sweep_200PositionsInOneBar_oneCrosshairEvent_aReadoutEventPerFrame", () => {
    const c = container();
    const chart = createChart({ container: asHtml(c), theme, runMode: "inline" });
    bars(chart);
    // One bar of the (empty) 60 s map over the plot: spacing clamps to the 200 px maximum,
    // so bar 1 spans x in [100, 300).
    chart.timeScale.setVisibleRange({ from: 0, to: 60e6 });
    frames(3);
    const cross: ChartEvents["crosshair"][] = [];
    const readout: ReadoutEvent[] = [];
    chart.subscribe("crosshair", (e) => cross.push(e));
    chart.subscribe("readout", (e) => readout.push(e));
    for (let x = 100; x < 300; x += 1) {
      c.dispatch("pointermove", pointer(x, 20 + (x - 100), x));
      frames();
    }
    expect(cross).toEqual([{ time: 60e6, price: expect.any(Number), barIndex: 1 }]);
    expect(readout.length).toBeGreaterThan(150); // the y moved every frame
    expect(readout.every((r) => r.visible && r.bar === 1 && r.timeText !== "")).toBe(true);
    c.dispatch("pointerleave", pointer(-1, -1, 400));
    frames(3); // the host's flush, then the worker's frame
    expect(cross).toHaveLength(1); // leaving never fires (BQ-10)
    expect(readout.at(-1)).toMatchObject({ visible: false, fields: [] }); // m3: no values hidden
    c.dispatch("pointermove", pointer(150, 30, 401));
    frames(3);
    expect(cross).toHaveLength(1); // re-entering the same bar fires nothing either
    expect(readout.at(-1)?.visible).toBe(true);
    expect(chart.getFocusedUnit()).toBeNull(); // a pointer cursor is not a focused unit
    chart.dispose();
  });
});

describe("BQ-9: the magnet", () => {
  it("test_magnetMode_badOption_throwsRangeError", () => {
    const c = container();
    const bad = { container: asHtml(c), theme, magnetMode: "medium" } as never;
    expect(() => createChart(bad)).toThrow(RangeError);
  });

  it("test_setMagnetMode_sendsSetCrosshair_retained_andAnnouncesOnceUnderItsKey", () => {
    const doc = new FakeDocument();
    doc.offscreenAvailable = true;
    doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
    (doc.defaultView as { CustomEvent?: unknown }).CustomEvent = (
      container().ownerDocument.defaultView as { CustomEvent?: unknown }
    ).CustomEvent;
    const c = new FakeElement("div", doc);
    c.clientWidth = 200;
    c.clientHeight = 100;
    const said: unknown[] = [];
    c.addEventListener(ANNOUNCE_EVENT, (e) => said.push((e as { detail: unknown }).detail));
    const chart = createChart({ container: asHtml(c), theme, magnetMode: "strong" });
    frames(2);
    chart.setMagnetMode("strong"); // unchanged: nothing sent, nothing said
    chart.setMagnetMode("weak");
    frames(2);
    const w = FakeWorker.created.at(-1) as FakeWorker;
    const cmds = (w.inbox as ToWorker[]).flatMap((m) =>
      m.t === "command" && m.cmd.k === "setCrosshair" ? [m.cmd.magnetMode] : [],
    );
    expect(cmds).toEqual(["strong", "weak"]); // the option, then the setter
    expect(said).toEqual([
      { politeness: "polite", text: magnetText("weak"), key: MAGNET_ANNOUNCE_KEY },
    ]);
    expect(() => chart.setMagnetMode("x" as never)).toThrow(RangeError);
    chart.dispose();
    chart.setMagnetMode("off"); // disposed: a no-op
  });
});

describe("BQ-23: getFocusedUnit", () => {
  it("test_getFocusedUnit_keyCursor_returnsTheBar_otherwiseNull", () => {
    const doc = new FakeDocument();
    doc.offscreenAvailable = true;
    doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
    const c = new FakeElement("div", doc);
    c.clientWidth = 200;
    c.clientHeight = 100;
    const chart = createChart({ container: asHtml(c), theme });
    frames(2);
    const w = FakeWorker.created.at(-1) as FakeWorker;
    const say = (m: Partial<Extract<FromWorker, { t: "crosshair" }>>): void =>
      w.onmessage?.({
        data: {
          t: "crosshair",
          id: 1,
          bar: 7,
          time: 0,
          price: 42,
          priceText: "21",
          timeText: "",
          x: 1,
          y: 1,
          snap: null,
          driver: "key",
          visible: true,
          ...m,
        },
      });
    say({});
    expect(chart.getFocusedUnit()).toBeNull(); // no pane yet
    const pane = chart.addPane({});
    expect(chart.getFocusedUnit()).toEqual({
      kind: "bar",
      paneId: pane.id,
      barIndex: 7,
      priceLevel: 42,
    });
    say({ price: Number.NaN });
    expect(chart.getFocusedUnit()).toEqual({ kind: "bar", paneId: pane.id, barIndex: 7 });
    say({ visible: false });
    expect(chart.getFocusedUnit()).toBeNull();
    say({ driver: "pointer" });
    expect(chart.getFocusedUnit()).toBeNull();
    chart.dispose();
  });
});
