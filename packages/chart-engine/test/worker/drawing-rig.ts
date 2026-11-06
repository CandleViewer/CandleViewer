// E14-T04 runtime fixture: one inline chart over the synthetic minute map (the runtime-pick
// pattern), frames by hand, and helpers that place drawings by view fraction and read the
// worker's messages by type.
import { vi } from "vitest";
import type { ObjectIndex } from "../../src/hit/index.js";
import { columnSource, priceToScreen, timeToScreen } from "../../src/viewport/index.js";
import { createRenderRuntime } from "../../src/worker/runtime.js";
import type { Command, FromWorker, ToWorker } from "../../src/worker/protocol.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap, rows } from "../interaction/fixtures.js";

export type Msg<T extends FromWorker["t"]> = Extract<FromWorker, { t: T }>;

export function drawingRig() {
  vi.useFakeTimers();
  const out: FromWorker[] = [];
  const cols = {
    low: new Int32Array(2000).fill(1_000),
    high: new Int32Array(2000).fill(3_000),
    close: new Int32Array(2000).fill(2_000),
    length: 2000,
  };
  const rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap: minuteMap(),
    priceSources: [columnSource(() => cols)],
  });
  const send = (msg: ToWorker): void => rt.handle(msg);
  const frame = (): void => void vi.advanceTimersByTime(16);
  const canvas = { width: 1064, height: 624, getContext: () => new FakeGl({ params: ROOMY }) };
  send({ t: "init", id: 1, canvas, dpr: 1, theme: {}, config: { bench: true, syncGroup: null } });
  frame();
  const objects = rt.pickIndex(1)?.objects as ObjectIndex;
  const of = <T extends FromWorker["t"]>(t: T): Msg<T>[] =>
    out.filter((m): m is Msg<T> => m.t === t);
  const view = (): Msg<"viewport"> => of("viewport").at(-1) as Msg<"viewport">;
  const rig = {
    rt,
    out,
    objects,
    frame,
    send,
    cmd: (c: Command) => send({ t: "command", id: 1, cmd: c }),
    of,
    /** The anchor `u` of the way across the view in time, `v` up its price window. */
    at(u: number, v: number): [number, number] {
      const { timeStart, timeEnd, priceLow, priceHigh } = view();
      const bar = Math.round((timeStart + (timeEnd - timeStart) * u) / 60e6) * 60e6;
      return [bar, Math.round(priceLow + (priceHigh - priceLow) * v)];
    },
    xy: ([t, p]: readonly [number, number]): [number, number] => [
      timeToScreen(objects.viewport, t),
      priceToScreen(objects.viewport, 0, p),
    ],
    draw(id: string, kind: string, anchors: [number, number][], more = {}) {
      rig.cmd({ k: "addDrawing", drawingId: id, kind, anchors: anchors.flat(), ...more });
    },
    input: (...r: number[][]) => send({ t: "input", id: 1, kind: "pointer", events: rows(...r) }),
  };
  return rig;
}

export type DrawingRig = ReturnType<typeof drawingRig>;
