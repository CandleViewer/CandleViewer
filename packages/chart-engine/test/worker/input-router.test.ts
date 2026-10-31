// E11-S04 PR 1: the DOM half of the InputRouter (src/host/input-router.ts) on the fake DOM, over
// the real host and worker entry; frames are run by hand so each flush is one frame (BQ-99).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { routeInput } from "../../src/host/input-router.js";
import { MOD } from "../../src/interaction/wheel.js";
import { captureInput, createChartHost, type ChartHost } from "../../src/worker/host.js";
import { INPUT, type ToWorker } from "../../src/worker/protocol.js";
import { asHtml, FakeDocument, FakeElement } from "../api/fake-dom.js";
import { fakeEnv, FakeWorker } from "./fake-worker.js";

type Input = Extract<ToWorker, { t: "input" }>;

let frames: (() => void)[];
let container: FakeElement;
let host: ChartHost;

/** Runs the frame the host requested, then lets the fake bus deliver what it posted. */
const frame = (): void => {
  const due = frames.splice(0);
  for (const cb of due) cb();
  vi.advanceTimersByTime(1);
};
const inputs = (kind?: string): Input[] =>
  ((FakeWorker.created.at(-1)?.inbox ?? []) as ToWorker[]).filter(
    (m): m is Input => m.t === "input" && (kind === undefined || m.kind === kind),
  );
const rowsOf = (m: Input): number[][] => {
  const out: number[][] = [];
  for (let i = 0; i < m.events.length; i += 6) out.push([...m.events.slice(i, i + 6)]);
  return out;
};

const base = { offsetX: 500, offsetY: 300, shiftKey: false, ctrlKey: false, altKey: false };
const ptr = (id: number, x: number, t: number, type = "mouse"): object => ({
  ...base,
  metaKey: false,
  offsetX: x,
  buttons: 1,
  pointerId: id,
  pointerType: type,
  timeStamp: t,
});

beforeEach(() => {
  vi.useFakeTimers();
  FakeWorker.created = [];
  frames = [];
  const doc = new FakeDocument();
  doc.offscreenAvailable = true;
  doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
  container = new FakeElement("div", doc);
  container.clientWidth = 1064; // a 1000 × 600 plot
  container.clientHeight = 624;
  const canvas = doc.createElement("canvas");
  host = createChartHost({
    realm: doc,
    runMode: "worker",
    env: fakeEnv({ requestFrame: (cb) => void frames.push(cb) }),
    canvas: () => asHtml(canvas) as HTMLCanvasElement,
    replaceCanvas: () => asHtml(doc.createElement("canvas")) as HTMLCanvasElement,
    dpr: 1,
    theme: {},
    syncGroup: null,
    bench: false,
    listener: {
      deliver: () => undefined,
      lost: () => undefined,
      restored: () => undefined,
      resync: () => undefined,
    },
  });
  vi.advanceTimersByTime(1);
});

afterEach(() => {
  host.dispose();
  vi.useRealTimers();
});

describe("Scenario: A high-rate trackpad cannot flood the worker", () => {
  it("240 wheel events a second post at most one batch per frame, and Σ posted == Σ raw", () => {
    const detach = routeInput(asHtml(container), host);
    const raw: [number, number] = [0, 0]; // zoom class, pan class (px)
    let frameCount = 0;
    for (let i = 0; i < 240; i += 1) {
      const pan = i % 10 === 0; // Shift+wheel now and then: the second accumulator row
      const deltaY = ((i * 7) % 9) - 3;
      raw[pan ? 1 : 0] = (raw[pan ? 1 : 0] as number) + deltaY;
      const wheel = { ...base, metaKey: false, shiftKey: pan, deltaX: 0, deltaY, deltaMode: 0 };
      expect(container.dispatch("wheel", { ...wheel, timeStamp: i * (1000 / 240) })).toBe(true);
      if (i % 4 === 3) {
        const before = inputs("wheel").length;
        frame();
        frameCount += 1;
        expect(inputs("wheel").length - before).toBeLessThanOrEqual(1); // one batch per frame
      }
    }
    const sent = inputs("wheel");
    expect(frameCount).toBe(60);
    expect(sent.length).toBe(60);
    const posted: [number, number] = [0, 0];
    for (const m of sent) {
      const r = rowsOf(m);
      expect(r.length).toBeLessThanOrEqual(3); // zoom, pan, zoom: a class change opens a row
      for (const row of r) {
        const k = ((row[4] as number) & MOD.pan) !== 0 ? 1 : 0;
        posted[k] = (posted[k] as number) + (row[3] as number);
      }
    }
    expect(posted).toEqual(raw); // no zoom step lost
    detach();
  });

  it("normalises line and page deltas, and opens a new row when the class or region changes", () => {
    const detach = routeInput(asHtml(container), host);
    const wheel = { ...base, metaKey: false, deltaX: 0, timeStamp: 1 };
    container.dispatch("wheel", { ...wheel, deltaY: 3, deltaMode: 1 }); // 3 lines
    container.dispatch("wheel", { ...wheel, deltaY: 1, deltaMode: 2 }); // one plot height
    container.dispatch("wheel", { ...wheel, offsetY: 610, deltaY: 5, deltaMode: 0 }); // time axis
    container.dispatch("wheel", { ...wheel, deltaX: -30, deltaY: 2, deltaMode: 0, ctrlKey: true });
    container.dispatch("wheel", { ...wheel, deltaY: 7, deltaMode: 0 }); // never folded back: order
    frame();
    expect(rowsOf(inputs("wheel")[0] as Input)).toEqual([
      [INPUT.wheel, 500, 300, 48 + 600, 0, 0],
      [INPUT.wheel, 500, 610, 5, 0, 0],
      [INPUT.wheel, 500, 300, -30, MOD.ctrl | MOD.pan, 0], // a dominant deltaX pans
      [INPUT.wheel, 500, 300, 7, 0, 0],
    ]);
    detach();
  });
});

describe("pointer routing (BQ-102)", () => {
  it("captures the pointer, and a cancel or a capture lost mid-drag ends it with no coast", () => {
    const detach = routeInput(asHtml(container), host);
    container.dispatch("pointerdown", ptr(3, 100, 10));
    container.dispatch("pointercancel", ptr(3, 100, 12));
    container.dispatch("pointerdown", ptr(4, 100, 20));
    container.dispatch("lostpointercapture", ptr(4, 120, 22));
    container.dispatch("pointerdown", ptr(5, 100, 30));
    container.dispatch("pointerup", ptr(5, 140, 31));
    container.dispatch("lostpointercapture", ptr(5, 140, 31)); // after the up: not a cancel
    expect(container.dispatch("dblclick", { ...ptr(0, 140, 40) })).toBe(true); // no selection
    frame();
    expect(container.captured).toEqual([3, 4, 5]);
    expect(rowsOf(inputs("pointer")[0] as Input).map((r) => r[0])).toEqual([
      INPUT.down,
      INPUT.cancel,
      INPUT.down,
      INPUT.cancel,
      INPUT.down,
      INPUT.up,
      INPUT.dblclick,
    ]);
    detach();
    expect(container.listeners.get("pointercancel")?.size).toBe(0);
  });

  it("a touch row carries its pointer id, and touch-action is none on the container", () => {
    const detach = captureInput(asHtml(container), host); // the kept re-export
    container.dispatch("pointerdown", ptr(11, 100, 10, "touch"));
    container.dispatch("pointerdown", ptr(12, 300, 10, "touch"));
    container.dispatch("pointermove", {
      ...ptr(12, 350, 18, "touch"),
      getCoalescedEvents: () => [],
    });
    frame();
    expect(rowsOf(inputs("touch")[0] as Input).map((r) => [r[0], r[1], r[3]])).toEqual([
      [INPUT.down, 100, 11],
      [INPUT.down, 300, 12],
      [INPUT.move, 350, 12],
    ]);
    expect(container.style["touchAction"]).toBe("none");
    detach();
  });
});
