// E11-S08 PR 2 through the runtime: hover picks are edge-triggered per `input` message (S4,
// BQ-134), the tolerance follows the input's pointer type (S3), `pickAt` always replies with its
// `reqId` (BQ-135, BQ-136), and a log scale bends a segment's cells (G-27). Frames by hand.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ObjectIndex, Pickable } from "../../src/hit/index.js";
import { columnSource } from "../../src/viewport/index.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { INPUT, type FromWorker, type ToWorker } from "../../src/worker/protocol.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { MOD } from "../../src/interaction/wheel.js";
import { minuteMap, rows } from "../interaction/fixtures.js";

type PickMsg = Extract<FromWorker, { t: "pick" }>;
type View = Extract<FromWorker, { t: "viewport" }>;

let out: FromWorker[];
let rt: RenderRuntime;
let objects: ObjectIndex;
/** Bars from 10 to 100 000 ticks: a wide window, so a log y bends a segment hard. */
const cols = {
  low: new Int32Array(2000).fill(10),
  high: new Int32Array(2000).fill(100_000),
  close: new Int32Array(2000).fill(50_000),
  length: 2000,
};
const frame = (): void => void vi.advanceTimersByTime(16);
const picks = (): PickMsg[] => out.filter((m): m is PickMsg => m.t === "pick");
const view = (): View => out.filter((m): m is View => m.t === "viewport").at(-1) as View;
/** A time `u` of the way across the view, and the tick `v` of the way up its window. */
const at = (u: number, v = 0.5): [number, number] => {
  const { timeStart, timeEnd, priceLow, priceHigh } = view();
  return [timeStart + (timeEnd - timeStart) * u, Math.round(priceLow + (priceHigh - priceLow) * v)];
};
const mid = (): number => at(0)[1];
const send = (msg: ToWorker): void => rt.handle(msg);
const move = (x: number, y: number, kind: "pointer" | "touch" = "pointer", b = 0): void =>
  send({ t: "input", id: 1, kind, events: rows([INPUT.move, x, y, b, 0, 16]) });
const pickAt = (cmd: object): void =>
  send({ t: "command", id: 1, cmd: { k: "pickAt", ...cmd } as never });
const add = (p: Partial<Pickable> & { id: string; geometry: Pickable["geometry"] }): void =>
  objects.registerPickable({ kind: "drawing", paneId: "main", zIndex: 0, widthPx: 0, ...p });
/** A registered object's projected box [x0, y0, x1, y1] in CSS px. */
const box = (id: string): number[] => {
  const b: number[] = [];
  objects.boundsOf(id, b);
  return b;
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
    priceSources: [columnSource(() => cols)],
  });
  const canvas = { width: 1064, height: 624, getContext: () => new FakeGl({ params: ROOMY }) };
  send({ t: "init", id: 1, canvas, dpr: 1, theme: {}, config: { bench: true, syncGroup: null } });
  frame(); // lays out the plot and fits the price window
  objects = rt.pickIndex(1)?.objects as ObjectIndex;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("hover picking", () => {
  it("Scenario: Pick messages are edge-triggered", () => {
    add({ id: "d", geometry: { type: "hline", p: mid() }, widthPx: 2 });
    const y = box("d")[1] as number;
    for (let x = 100; x <= 400; x += 10) move(x, y + 1); // 300 px over the same drawing
    expect(picks()).toHaveLength(1);
    expect(picks()[0]).toMatchObject({ objectId: "d", kind: "drawing", part: "body" });
    move(400, y + 200); // leaves it
    move(420, y + 220);
    expect(picks()).toHaveLength(2);
    expect(picks()[1]).toMatchObject({ objectId: null, kind: "none" });
    expect(picks()[1]).not.toHaveProperty("part");
  });

  it("a pointer leaving the canvas off a hovered object posts one null; none else (G-29)", () => {
    add({ id: "d", geometry: { type: "hline", p: mid() } });
    const y = box("d")[1] as number;
    const leave = (): void =>
      send({ t: "input", id: 1, kind: "pointer", events: rows([INPUT.leave, 1064, y, 0, 0, 4]) });
    move(300, y);
    leave();
    leave();
    expect(picks().map((p) => [p.objectId, p.kind])).toEqual([
      ["d", "drawing"],
      [null, "none"],
    ]);
    move(300, y + 200); // back in, over nothing
    leave();
    expect(picks()).toHaveLength(2);
  });

  it("posts no pick during a drag, and picks again after it", () => {
    add({ id: "d", geometry: { type: "hline", p: mid() } });
    const y = box("d")[1] as number;
    send({ t: "input", id: 1, kind: "pointer", events: rows([INPUT.down, 200, y + 100, 1, 0, 0]) });
    move(200, y, "pointer", 1); // dragged across the line
    move(210, y + 50, "pointer", 1);
    expect(picks()).toEqual([]);
    send({ t: "input", id: 1, kind: "pointer", events: rows([INPUT.cancel, 210, y, 1, 0, 0]) });
    move(210, box("d")[1] as number);
    expect(picks().map((p) => p.objectId)).toEqual(["d"]);
  });

  it("picks once per message, at its last move", () => {
    add({ id: "d", geometry: { type: "hline", p: mid() } });
    const y = box("d")[1] as number;
    const events = rows([INPUT.move, 100, y, 0, 0, 8], [INPUT.move, 100, y + 300, 0, 0, 8]);
    send({ t: "input", id: 1, kind: "pointer", events });
    expect(picks()).toEqual([]); // the last move is off the line: no change from none
  });

  it("Scenario: Touch gets a larger tolerance than mouse (a touch move with no finger down)", () => {
    add({ id: "o", kind: "order-line", geometry: { type: "hline", p: mid() } });
    const y = (box("o")[1] as number) + 13;
    move(300, y, "touch");
    expect(picks().at(-1)).toMatchObject({ objectId: "o", kind: "order-line" });
    move(300, y, "pointer");
    expect(picks().at(-1)).toMatchObject({ objectId: null, kind: "none" });
  });

  it("a finger down posts no hover pick: a real tap selects through the host's pickAt", () => {
    add({ id: "o", geometry: { type: "hline", p: mid() } });
    const y = box("o")[1] as number;
    send({ t: "input", id: 1, kind: "touch", events: rows([INPUT.down, 300, y, 5, 0, 0]) });
    move(300, y, "touch", 5);
    expect(picks()).toEqual([]);
  });

  it("a key that only changes the handle posts again", () => {
    const [[t0, p], [t1]] = [at(0.3), at(0.6)];
    const geometry = { type: "segment", t0, p0: p, t1, p1: p } as const;
    add({ id: "s", geometry, handles: [{ t: t1, p }] });
    const [x0, y, x1] = box("s") as [number, number, number];
    move((x0 + x1) / 2, y);
    move(x1, y);
    expect(picks().map((p) => [p.part, p.handle])).toEqual([
      ["body", undefined],
      ["handle", 0],
    ]);
  });
});

describe("pickAt", () => {
  it("always replies, echoing reqId, and leaves the hover edge alone (BQ-135)", () => {
    add({ id: "d", geometry: { type: "hline", p: mid() } });
    const y = box("d")[1] as number;
    pickAt({ x: 300, y, reqId: 7 });
    pickAt({ x: 300, y, reqId: 8 });
    expect(picks().map((p) => [p.reqId, p.objectId])).toEqual([
      [7, "d"],
      [8, "d"],
    ]);
    move(300, y); // the hover state still says none: this is an edge
    expect(picks().at(-1)).toMatchObject({ objectId: "d" });
    expect(picks().at(-1)).not.toHaveProperty("reqId");
  });

  it("a miss carries the bar and the tick level; a gutter is `axis` (BQ-136)", () => {
    pickAt({ x: 300, y: 200 });
    const [miss] = picks();
    expect(miss).toMatchObject({ objectId: null, kind: "none" });
    expect(Number.isInteger(miss?.bar) && Number.isInteger(miss?.price)).toBe(true);
    pickAt({ x: 1_050, y: 200, reqId: 2 }); // the price gutter
    pickAt({ x: 300, y: 620, reqId: 3 }); // the time gutter
    expect(picks().map((p) => [p.kind, p.reqId])).toEqual([
      ["none", undefined],
      ["axis", 2],
      ["axis", 3],
    ]);
    expect(picks()[1]?.price).toBe(miss?.price);
    expect(picks()[2]?.bar).toBe(miss?.bar);
  });

  it("resolves the pointer's tolerance: touch 16, mouse and pen 10", () => {
    add({ id: "o", kind: "order-line", geometry: { type: "hline", p: mid() } });
    const y = (box("o")[1] as number) + 13;
    for (const pointer of ["touch", "mouse", "pen", undefined]) pickAt({ x: 300, y, pointer });
    expect(picks().map((p) => p.objectId)).toEqual(["o", null, null, null]);
  });
});

describe("the degraded-2d re-init (G-28)", () => {
  it("keeps the registrations: the same object picks at the same point", () => {
    add({ id: "d", geometry: { type: "hline", p: mid() } });
    const y = box("d")[1] as number;
    const canvas = { width: 1064, height: 624, getContext: () => null };
    const config = { bench: true, syncGroup: null };
    send({ t: "init", id: 1, canvas, dpr: 1, theme: {}, config, profile: "degraded-2d" });
    frame();
    expect(rt.pickIndex(1)?.objects).toBe(objects); // registrants keep their handle
    pickAt({ x: 300, y, reqId: 1 });
    expect(picks().at(-1)).toMatchObject({ objectId: "d", reqId: 1 });
  });
});

describe("under a log scale (G-27)", () => {
  it("picks a segment along its drawn line, after one rebuild for the mode switch", () => {
    const bars = (params: number[]): void =>
      send({
        t: "data",
        id: 1,
        store: "bars",
        op: "replace",
        layout: { count: 0, columns: [], params },
        buffer: new ArrayBuffer(0),
      });
    bars([0, 1]);
    frame();
    const geometry = {
      type: "segment",
      t0: at(0.2)[0],
      p0: 100,
      t1: at(0.8)[0],
      p1: 90_000,
    } as const;
    add({ id: "s", geometry });
    pickAt({ x: 0, y: 0 });
    const before = objects.counters.indexRebuilds;
    send({ t: "command", id: 1, cmd: { k: "setPriceScale", pane: 0, mode: "log" } });
    frame();
    const [x0, y0, x1, y1] = box("s") as [number, number, number, number];
    for (let u = 0.05; u < 1; u += 0.05) {
      // The drawn line is straight on screen: rising, so from (x0, y1) to (x1, y0).
      pickAt({ x: x0 + (x1 - x0) * u, y: y1 + (y0 - y1) * u, reqId: Math.round(u * 100) });
      expect(picks().at(-1)?.objectId).toBe("s");
    }
    expect(objects.counters.indexRebuilds).toBe(before + 1);
    send({
      t: "input",
      id: 1,
      kind: "wheel",
      events: rows([INPUT.wheel, 500, 300, 40, MOD.pan, 0]),
    });
    pickAt({ x: 10, y: 10 });
    expect(objects.counters.indexRebuilds).toBe(before + 1); // a pan never rebuilds
  });
});
