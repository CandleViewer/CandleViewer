// E14-T03 slice 1 through the runtime and the host: `setDrawings` (replace and patch), the
// `drawingBounds` post (≤ 1 a frame, `ids` only on a set change), refusals that change nothing,
// and the set kept across the degraded-2d re-init and a worker restart. Scenario 1's isolation
// (a drag touches the drawings node alone) is the `drawings-drag` scene's counted test.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { copyInput, type DrawingInput } from "../../src/layers/drawings/model.js";
import { createChartHost } from "../../src/worker/host.js";
import type { Command, FromWorker, ToWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { asHtml, FakeDocument } from "../api/fake-dom.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap } from "../interaction/fixtures.js";
import { fakeEnv, FakeWorker } from "./fake-worker.js";

type Bounds = Extract<FromWorker, { t: "drawingBounds" }>;
const T = (i: number): number => minuteMap().indexToTime(i);
const seg = (id: string, i = 10): DrawingInput => ({
  id,
  kind: "segment",
  points: [T(i), 100, T(i + 5), 150],
  style: { colour: 0x2962ffff, width: 2, dash: 1 },
});
const many = (n: number, p = "d"): DrawingInput[] =>
  Array.from({ length: n }, (_, i) => seg(`${p}${i}`, i));

let out: FromWorker[];
let rt: RenderRuntime;
const frame = (): void => void vi.advanceTimersByTime(16);
const cmd = (c: object): void => rt.handle({ t: "command", id: 1, cmd: c as Command });
const bounds = (): Bounds[] => out.filter((m): m is Bounds => m.t === "drawingBounds");
/** The last GL fake a canvas handed out (the runtime asks once, on the first frame). */
let gl: FakeGl;
const init = (extra: object = {}): void => {
  const getContext = (): FakeGl => (gl = new FakeGl({ params: ROOMY }));
  const canvas = { width: 800, height: 600, getContext };
  const config = { bench: true, syncGroup: null };
  rt.handle({ t: "init", id: 1, canvas, dpr: 1, theme: {}, config, ...extra });
};

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap: minuteMap(),
  });
  init();
  frame();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("setDrawings through the runtime", () => {
  it("posts each drawing's bounds once a frame, with ids only when the set changed", () => {
    expect(bounds()).toEqual([]); // no drawings: no node, no post
    cmd({ k: "setDrawings", op: "replace", drawings: many(3) });
    frame();
    const b = bounds()[0]?.bounds as Float32Array;
    expect([bounds()[0]?.ids, b.length]).toEqual([["d0", "d1", "d2"], 12]);
    expect(b[2] as number).toBeGreaterThan(b[0] as number); // a 5-bar segment has width
    cmd({ k: "setViewport", timeStart: T(0), timeEnd: T(100) }); // TRANSFORM only
    frame();
    frame(); // nothing changed: nothing posted
    expect(bounds()).toHaveLength(2);
    expect([bounds()[1]?.ids, bounds()[1]?.bounds[0] === b[0]]).toEqual([undefined, false]);
  });

  it("refuses a malformed or over-cap command and leaves the set as it was", () => {
    cmd({ k: "setDrawings", op: "replace", drawings: many(2) });
    frame();
    out.length = 0;
    cmd({ k: "setDrawings", op: "patch", drawings: [{ ...seg("x"), kind: "iframe" }] });
    cmd({ k: "setDrawings", op: "patch", drawings: [{ ...seg("x"), points: [0, Infinity] }] });
    cmd({ k: "setDrawings", op: "patch", drawings: many(999, "n") }); // + 2 held > 1 000
    expect(out.map((m) => (m.t === "error" ? `${m.code}: ${m.message}` : m.t))).toEqual([
      "ENGINE_DECODE_ERROR: setDrawings: unknown drawing kind iframe",
      "ENGINE_DECODE_ERROR: setDrawings: segment takes 2,2",
      "ENGINE_DECODE_ERROR: setDrawings: more than 1000 drawings",
    ]);
    frame();
    expect(bounds()).toEqual([]); // refused: not even DATA
    cmd({ k: "setDrawings", op: "patch", drawings: [], remove: ["d0"] });
    frame();
    expect(bounds()[0]?.ids).toEqual(["d1"]);
  });

  it("keeps the drawings across the degraded-2d re-init", () => {
    cmd({ k: "setDrawings", op: "replace", drawings: many(4) });
    frame();
    init({ profile: "degraded-2d" });
    frame();
    expect(bounds().at(-1)?.ids).toEqual(["d0", "d1", "d2", "d3"]);
  });
});

describe("drawing-line through the runtime (slice 2)", () => {
  type Frame = Extract<FromWorker, { t: "frame" }>;
  const last = (): Frame => out.filter((m): m is Frame => m.t === "frame").at(-1) as Frame;

  it("draws the lines in one call; a pan uploads 0 bytes; a drag uploads one instance", () => {
    cmd({ k: "setDrawings", op: "replace", drawings: many(5) });
    frame();
    // The first upload is the whole 64-slot ring.
    expect([last().drawCalls, last().triangles, last().uploadedBytes]).toEqual([1, 10, 64 * 64]);
    cmd({ k: "setViewport", timeStart: T(3), timeEnd: T(90) });
    frame();
    expect([last().drawCalls, last().uploadedBytes]).toEqual([1, 0]);
    cmd({ k: "setDrawings", op: "patch", drawings: [seg("d2", 40)] });
    frame();
    expect(last().uploadedBytes).toBe(64);
  });

  it("binds the four ivec4 inputs on the runtime's backend (attach with LINE_ATTRIBUTES)", () => {
    cmd({ k: "setDrawings", op: "replace", drawings: many(2) });
    frame();
    expect(gl.attribs.filter((a) => a.startsWith("attrib"))).toEqual(
      [0, 1, 2, 3].map((at) => `attrib ${at} 4 64 ${at * 16}`),
    );
  });

  it("re-wires the ring to the degraded-2d re-init's backend and builder", () => {
    cmd({ k: "setDrawings", op: "replace", drawings: many(3) });
    frame();
    init({ profile: "degraded-2d" });
    frame();
    expect([last().renderProfile, last().drawCalls]).toEqual(["degraded-2d", 0]); // FakeGl: no 2D
    cmd({ k: "setDrawings", op: "patch", drawings: [seg("d9", 9)] });
    frame();
    expect(bounds().at(-1)?.ids).toEqual(["d0", "d1", "d2", "d9"]);
  });
});

describe("the host after a worker restart", () => {
  it("replays the folded set as one replace, never holding a refused change", () => {
    FakeWorker.created = [];
    const doc = new FakeDocument();
    doc.offscreenAvailable = true;
    doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
    const canvas = (): HTMLCanvasElement =>
      asHtml(doc.createElement("canvas")) as HTMLCanvasElement;
    const nop = (): undefined => undefined;
    const host = createChartHost({
      ...{ realm: doc, runMode: "worker", env: fakeEnv(), canvas, replaceCanvas: canvas },
      ...{ dpr: 1, theme: {}, syncGroup: null, bench: false },
      listener: { deliver: nop, lost: nop, restored: nop, resync: nop },
    });
    vi.advanceTimersByTime(20);
    host.command({ k: "setDrawings", op: "replace", drawings: many(3) });
    const moved = seg("d1", 50);
    host.command({ k: "setDrawings", op: "patch", drawings: [moved], remove: ["d0"] });
    (moved.points as number[])[1] = 7; // mutated after command(): the replay keeps what was sent
    host.command({
      k: "setDrawings",
      op: "patch",
      drawings: [{ ...seg("z"), kind: "x" as "ray" }],
    });
    (FakeWorker.created.at(-1) as FakeWorker).kill();
    vi.advanceTimersByTime(1020);
    const inbox = (FakeWorker.created.at(-1) as FakeWorker).inbox as ToWorker[];
    expect(inbox.flatMap((m) => (m.t === "command" ? [m.cmd] : []))).toEqual([
      { k: "setDrawings", op: "replace", drawings: [seg("d1", 50), seg("d2", 2)].map(copyInput) },
    ]);
    host.dispose();
  });
});
