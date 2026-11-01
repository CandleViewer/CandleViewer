// E12-S10 (additive; noted for the E11-T09 #1404 freeze): the facade turns the worker's
// `barStateChanged` into the typed `barStateChanged` event, field for field. Fake DOM, fake
// worker, fake clock.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, setHostEnvFactory } from "../../src/api/chart.js";
import type { ChartEvents } from "../../src/api/types.js";
import { fakeEnv, FakeWorker } from "../worker/fake-worker.js";
import { asHtml, FakeDocument, FakeElement } from "./fake-dom.js";

beforeEach(() => {
  vi.useFakeTimers();
  FakeWorker.created = [];
  setHostEnvFactory(() => fakeEnv());
});

afterEach(() => {
  setHostEnvFactory(null);
  vi.useRealTimers();
});

describe("barStateChanged (E12-S10)", () => {
  it("emits the bar's time and its forming / amended state", () => {
    const doc = new FakeDocument();
    doc.offscreenAvailable = true;
    doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
    const el = new FakeElement("div", doc);
    el.clientWidth = 200;
    el.clientHeight = 100;
    const theme = { palette: "default" as const, convention: "standard" as const, colors: {} };
    const chart = createChart({ container: asHtml(el), theme });
    vi.advanceTimersByTime(50);
    const worker = FakeWorker.created[0] as FakeWorker;
    const id = (worker.inbox[0] as { id: number }).id;
    const seen: ChartEvents["barStateChanged"][] = [];
    chart.subscribe("barStateChanged", (e) => seen.push(e));
    worker.onmessage?.({
      data: { t: "barStateChanged", id, time: 60e6, forming: false, amended: true },
    });
    expect(seen).toEqual([{ time: 60e6, forming: false, amended: true }]);
    chart.dispose();
  });
});
