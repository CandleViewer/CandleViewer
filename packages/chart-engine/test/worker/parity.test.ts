// Scenario: Inline fallback is behaviourally identical (E11-T02, 26 §2, C-Q02-1). One scripted
// interaction runs in both modes over the SAME runtime module; every observable the main thread
// gets (events, the LOD trace in bench mode, the a11y transport, pixels) must match, with the
// frame each one arrives in included. Only throughput may differ, and that is the bench's: on
// fake timers each hop of the async worker bus costs 1 ms, so arrival is compared per 16 ms frame.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, setHostEnvFactory } from "../../src/api/chart.js";
import { captureInput, createChartHost } from "../../src/worker/host.js";
import { INPUT, KEY, type FromWorker, type RunMode } from "../../src/worker/protocol.js";
import type { ThemeTokens } from "../../src/index.js";
import { asHtml, FakeDocument, FakeElement } from "../api/fake-dom.js";
import { fakeEnv, FakeWorker } from "./fake-worker.js";

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: { "color.chart.background": "#0b0e11" },
};

let resized: (entries: object[]) => void = () => undefined;

function realm(): FakeElement {
  const doc = new FakeDocument();
  doc.offscreenAvailable = true;
  const ResizeObserver = class {
    constructor(cb: (entries: object[]) => void) {
      resized = cb;
    }
    observe(): void {}
    disconnect(): void {}
  };
  doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {}, ResizeObserver };
  const el = new FakeElement("div", doc);
  el.clientWidth = 400;
  el.clientHeight = 200;
  return el;
}

const pointer = (x: number, buttons: number, t: number): object => ({
  offsetX: x,
  offsetY: 10,
  buttons,
  shiftKey: false,
  ctrlKey: false,
  altKey: false,
  metaKey: false,
  timeStamp: t,
  pointerType: "mouse",
});

/** Pan, zoom, crosshair and resize; returns everything observable, stamped with the fake clock. */
function scenario(runMode: RunMode): unknown[] {
  const container = realm();
  const chart = createChart({ container: asHtml(container), theme, runMode });
  const log: unknown[] = [];
  const t0 = Date.now();
  const at = (): number => Math.floor((Date.now() - t0) / 16);
  chart.subscribe("viewportChanged", (p) => log.push(["viewport", at(), p]));
  chart.subscribe("frameStats", (p) => log.push(["frame", at(), p]));
  chart.timeScale.setVisibleRange({ from: 0, to: 4e9 });
  vi.advanceTimersByTime(16);
  container.dispatch("pointerdown", pointer(100, 1, 1));
  container.dispatch("pointermove", pointer(200, 1, 2)); // pan
  container.dispatch("pointerup", pointer(200, 0, 3));
  vi.advanceTimersByTime(16);
  container.dispatch("wheel", { ...pointer(50, 0, 4), deltaY: -120 }); // zoom at the cursor
  vi.advanceTimersByTime(16);
  container.dispatch("pointermove", pointer(300, 0, 5)); // crosshair
  vi.advanceTimersByTime(16);
  container.clientWidth = 800; // resize: the crosshair math follows the new width
  resized([{}]);
  container.dispatch("pointermove", pointer(300, 1, 6));
  vi.advanceTimersByTime(1000);
  const canvas = container.children.find((c) => c.tagName === "CANVAS");
  // The backing store follows the resize in the runtime, the CSS box on the main thread.
  log.push([
    "pixels",
    canvas?.webgl2?.clears,
    canvas?.width,
    canvas?.height,
    canvas?.style["width"],
    canvas?.style["height"],
  ]);
  chart.dispose();
  return log;
}

/** The host-level transport (a11y, viewport, the bench-mode LOD trace), timestamped. */
function transport(runMode: RunMode): unknown[] {
  const container = realm();
  const doc = container.ownerDocument;
  const log: unknown[] = [];
  const t0 = Date.now();
  const host = createChartHost({
    realm: doc,
    runMode,
    env: fakeEnv(),
    canvas: () => asHtml(doc.createElement("canvas")) as HTMLCanvasElement,
    replaceCanvas: () => asHtml(doc.createElement("canvas")) as HTMLCanvasElement,
    dpr: 1,
    theme: {},
    syncGroup: "g",
    bench: true,
    listener: {
      deliver: (m: FromWorker) =>
        log.push([Math.floor((Date.now() - t0) / 16), { ...m, runMode: undefined }]),
      lost: () => undefined,
      restored: () => undefined,
      resync: () => undefined,
    },
  });
  const detach = captureInput(asHtml(container), host);
  host.command({ k: "setViewport", timeStart: 0, timeEnd: 1e10 });
  for (let i = 0; i < 4; i += 1) {
    container.dispatch("pointermove", pointer(50 * i, 0, i));
    host.command({ k: "setLod", candles: (i % 3) as 0 | 1 | 2, footprint: 0 });
    vi.advanceTimersByTime(16);
  }
  host.input("key", [INPUT.key, KEY.zoomOut, 0, 0, 0, 0]);
  host.sync("g", [5e9, 6e9], 5.5e9);
  host.command({ k: "pickAt", x: 1, y: 1 });
  vi.advanceTimersByTime(50);
  detach();
  host.dispose();
  return log;
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

describe("Scenario: Inline fallback is behaviourally identical", () => {
  it("pan, zoom, crosshair and resize give the same events, timing and pixels in both modes", () => {
    const worker = scenario("worker");
    expect(FakeWorker.created).toHaveLength(1);
    const inline = scenario("inline");
    expect(FakeWorker.created).toHaveLength(1); // inline never spawns a worker
    expect(worker.filter((e) => (e as unknown[])[0] === "viewport").length).toBeGreaterThan(2);
    expect((worker.at(-1) as unknown[]).slice(2)).toEqual([800, 200, "800px", "200px"]);
    expect(inline).toEqual(worker);
  });

  it("the a11y transport, the LOD trace and picks arrive on the same schedule", () => {
    const worker = transport("worker");
    const inline = transport("inline");
    const kinds = new Set(worker.map((e) => ((e as unknown[])[1] as FromWorker).t));
    // E12-S06 (BQ-9): `dataState` on the first frame (no series: empty).
    expect([...kinds].sort()).toEqual(["a11y", "dataState", "frame", "pick", "ready", "viewport"]);
    expect(inline).toEqual(worker);
  });
});
