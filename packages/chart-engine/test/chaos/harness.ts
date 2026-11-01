// E11-Q04 chaos harness: a seeded generator, a canvas that fires the two context events, a
// render runtime on vitest's fake clock and the readers every chaos file shares. No real time,
// no network, no Math.random: every generator takes a seed and every failure names it.
import { vi } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import {
  encodeCandles,
  type BufferLayout,
  type FromWorker,
  type RunMode,
} from "../../src/worker/protocol.js";
import type { TextPlatform } from "../../src/text/platform.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";

/** The seeds every seeded chaos case walks; a failure message carries the seed. */
export const SEEDS = Array.from({ length: 25 }, (_, i) => 20261031 + i);

export interface Rng {
  /** A float in [0, 1). */
  next(): number;
  /** An integer in [lo, hi]. */
  int(lo: number, hi: number): number;
  pick<T>(items: readonly T[]): T;
}

export function rng(seed: number): Rng {
  const next = mulberry32(seed);
  const int = (lo: number, hi: number): number => lo + Math.floor(next() * (hi - lo + 1));
  return { next, int, pick: (items) => items[int(0, items.length - 1)] as never };
}

type Listener = (ev: { preventDefault(): void }) => void;

/** A canvas holding `gl` (null: no WebGL2) that fires `webglcontextlost` / `restored` on demand. */
export function lossCanvas(gl: FakeGl | null) {
  const on = new Map<string, Listener>();
  const ctx2d = { fillStyle: "", clearRect: () => undefined, fillRect: () => undefined };
  return {
    width: 200,
    height: 100,
    getContext: (id: string): unknown => (id === "webgl2" ? gl : ctx2d),
    addEventListener: (type: string, cb: Listener) => void on.set(type, cb),
    removeEventListener: (type: string) => void on.delete(type),
    /** The driver drops the context, then the browser dispatches the event. */
    lose(): void {
      gl?.loseContext();
      on.get("webglcontextlost")?.({ preventDefault: () => undefined });
    },
    restore(): void {
      gl?.restoreContext();
      on.get("webglcontextrestored")?.({ preventDefault: () => undefined });
    },
  };
}

/** A runtime on the fake clock (call `vi.useFakeTimers()` first) and everything it posted. */
export function runtimeOnFakeClock(runMode: RunMode = "inline", text?: TextPlatform) {
  const out: FromWorker[] = [];
  const rt: RenderRuntime = createRenderRuntime({
    runMode,
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: fakeNow,
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    ...(text && { text }),
  });
  const init = (canvas: object, id = 1, extra: object = {}): void =>
    rt.handle({
      ...extra,
      t: "init",
      id,
      canvas,
      dpr: 1,
      theme: { "color.chart.background": "#0b0e11" },
      config: { bench: true, syncGroup: "g" },
    });
  return { rt, out, init };
}

/** The fake clock's time (never the wall clock: see test/guards/no-wall-clock-in-unit.test.ts). */
export const fakeNow = (): number => Number(vi.getMockedSystemTime());

/** Moves the fake clock by `ms` in 16 ms frames, so every frame callback in between runs. */
export function frames(ms: number): void {
  for (let left = ms; left > 0; left -= 16) vi.advanceTimersByTime(Math.min(16, left));
}

/** Every `error` the runtime posted, as [code, recoverable]. */
export const codes = (out: readonly FromWorker[]): [string, boolean][] =>
  out.flatMap((m) => (m.t === "error" ? [[m.code, m.recoverable] as [string, boolean]] : []));

/** The last message of kind `t`; a `frame` without its volatile timing fields. */
export function last(out: readonly FromWorker[], t: FromWorker["t"]): unknown {
  const m = out.filter((x) => x.t === t).at(-1);
  if (m?.t !== "frame") return m;
  const stable: Record<string, unknown> = { ...m };
  delete stable["frameTimeMs"];
  delete stable["uploadedBytes"];
  return stable;
}

/** A valid bars batch of `n` one-minute candles from minute `first` (seeded prices). */
export function candleBatch(
  r: Rng,
  first: number,
  n: number,
): { layout: BufferLayout; buffer: ArrayBuffer } {
  const T0 = 1_700_000_000_000_000;
  const time = Float64Array.from({ length: n }, (_, i) => T0 + (first + i) * 60_000_000);
  const open = Int32Array.from({ length: n }, () => r.int(0, 1000));
  return encodeCandles({
    time,
    open,
    high: open.map((p) => p + 3),
    low: open.map((p) => p - 2),
    close: open.map((p) => p + 1),
    volume: Float32Array.from(open, (p) => (p % 97) + 1),
    priceOrigin: 50_000,
    tickSize: 0.1,
  });
}

/** A data message for chart `id` (the runtime takes untyped input: it validates it). */
export const dataMsg = (
  batch: { layout: unknown; buffer: unknown },
  op = "append",
  store = "bars",
  id = 1,
) => ({ t: "data", id, store, op, layout: batch.layout, buffer: batch.buffer });

/** A fresh roomy fake GL (the `full` profile). */
export const roomyGl = (): FakeGl => new FakeGl({ params: ROOMY });
