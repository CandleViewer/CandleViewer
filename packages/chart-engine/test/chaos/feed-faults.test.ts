// E11-Q04 chaos charter, group 2: feed faults (Gherkin G4, the engine-layer half of G5, the
// 60 s stall). The engine's input is a typed-array batch per store, not a socket frame (BQ-04):
// malformed batches are rejected at the worker boundary and hostile values at the store boundary,
// both before any write. Fault classes are described by class only (public repo, BQ-14).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BarStore, ModelRejection, type RejectReason } from "../../src/model/index.js";
import { createChartHost, MAX_QUEUED, MAX_UNACKED, type ChartHost } from "../../src/worker/host.js";
import {
  ENGINE_DECODE_ERROR,
  type DataOp,
  type StoreId,
  type ToWorker,
} from "../../src/worker/protocol.js";
import { asHtml, FakeDocument } from "../api/fake-dom.js";
import { bars, snapshot } from "../model/fixtures.js";
import { fakeEnv, FakeWorker } from "../worker/fake-worker.js";
import {
  candleBatch,
  codes,
  dataMsg,
  frames,
  last,
  lossCanvas,
  rng,
  roomyGl,
  runtimeOnFakeClock,
  SEEDS,
  type Rng,
} from "./harness.js";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  FakeWorker.created = [];
});

afterEach(() => {
  vi.useRealTimers();
});

/** Malformed-batch classes at the worker boundary; each turns a valid batch into a bad message. */
const MALFORMED: Record<string, (b: ReturnType<typeof candleBatch>, r: Rng) => object> = {
  truncated: (b, r) =>
    dataMsg({ ...b, buffer: b.buffer.slice(0, b.buffer.byteLength - r.int(1, 8)) }),
  overlong: (b, r) => dataMsg({ ...b, buffer: grow(b.buffer, r.int(1, 64)) }),
  "count above the ceiling": (b) => dataMsg({ ...b, layout: { ...b.layout, count: 2 ** 26 + 1 } }),
  "fractional count": (b) =>
    dataMsg({ ...b, layout: { ...b.layout, count: b.layout.count + 0.5 } }),
  "non-finite parameter": (b, r) =>
    dataMsg({ ...b, layout: { ...b.layout, params: [r.pick([NaN, Infinity, -Infinity]), 0.1] } }),
  "overlapping columns": (b) =>
    dataMsg({
      ...b,
      layout: { ...b.layout, columns: b.layout.columns.map((c) => ({ ...c, offset: 0 })) },
    }),
  "misaligned column": (b) =>
    dataMsg({
      ...b,
      layout: { ...b.layout, columns: [{ offset: 4, bytes: 8 }, ...b.layout.columns.slice(1)] },
    }),
  "not an ArrayBuffer": (b) => dataMsg({ ...b, buffer: new Uint8Array(b.buffer) }),
  "unknown store": (b) => dataMsg(b, "append", "orders"),
  "unknown op": (b) => dataMsg(b, "upsert"),
};

function grow(buffer: ArrayBuffer, extra: number): ArrayBuffer {
  const out = new Uint8Array(buffer.byteLength + extra);
  out.set(new Uint8Array(buffer));
  return out.buffer;
}

/** A seeded batch session; `bad` interleaves a malformed batch after some valid ones. */
function feed(seed: number, bad: boolean) {
  vi.clearAllTimers();
  vi.setSystemTime(0);
  const r = rng(seed);
  const { rt, out, init } = runtimeOnFakeClock();
  const gl = roomyGl();
  init(lossCanvas(gl));
  frames(32);
  const classes = Object.keys(MALFORMED);
  const injected: string[] = [];
  for (let i = 0; i < 30; i += 1) {
    const valid = candleBatch(r, i * 40, r.int(1, 40));
    const k = r.int(0, 2); // decided in both runs, so the valid stream is identical
    const cls = classes[r.int(0, classes.length - 1)] as string;
    const badBatch = MALFORMED[cls]?.(candleBatch(r, 0, r.int(1, 40)), r);
    if (bad && k === 0 && badBatch !== undefined) {
      rt.handle(badBatch);
      injected.push(cls);
    }
    rt.handle(dataMsg(valid));
    frames(16);
  }
  frames(64);
  return {
    out,
    injected,
    gl: { live: gl.alive.size, clear: gl.clears.at(-1), writes: gl.writes.length },
  };
}

describe("Scenario: Malformed frames are rejected without collateral damage (G4, worker boundary)", () => {
  it("10 malformed classes over 25 seeds: one recoverable DECODE_ERROR each, slot released, scene unchanged", () => {
    const seen = new Set<string>();
    for (const seed of SEEDS) {
      const ref = feed(seed, false);
      const hit = feed(seed, true);
      hit.injected.forEach((c) => seen.add(c));
      const decode = codes(hit.out).filter(([c]) => c === ENGINE_DECODE_ERROR);
      expect(decode, `seed ${seed}`).toEqual(hit.injected.map(() => [ENGINE_DECODE_ERROR, true]));
      expect(codes(ref.out), `seed ${seed}`).toEqual([]);
      // A rejected batch still acks (its backpressure slot is released), so nothing stalls.
      const acks = (o: typeof ref.out): number => o.filter((m) => m.t === "ack").length;
      expect(
        acks(hit.out) - hit.injected.filter((c) => !c.startsWith("unknown store")).length,
        `seed ${seed}`,
      ).toEqual(acks(ref.out));
      expect([last(hit.out, "viewport"), last(hit.out, "frame"), hit.gl], `seed ${seed}`).toEqual([
        last(ref.out, "viewport"),
        last(ref.out, "frame"),
        ref.gl,
      ]);
    }
    expect([...seen].sort()).toEqual(Object.keys(MALFORMED).sort()); // every class was exercised
  });
});

/** Hostile-value classes at the store boundary: [name, the reason expected, the mutation]. */
type Hostile = [string, RejectReason, (s: BarStore, r: Rng) => unknown];
const B = (n = 4, origin?: number) => bars(5000, n, origin);
const HOSTILE: Hostile[] = [
  ["NaN time", "non_finite", (s, r) => s.append(poke(B(), "time", r, NaN))],
  ["+Infinity volume", "non_finite", (s, r) => s.append(poke(B(), "volume", r, Infinity))],
  ["-Infinity delta", "non_finite", (s, r) => s.append(poke(B(), "delta", r, -Infinity))],
  ["non-finite tick size", "non_finite", (s) => s.append({ ...B(), tickSize: Infinity })],
  ["duplicate time in a batch", "order", (s) => s.append(dup(B()))],
  ["out-of-order append", "order", (s, r) => s.append(bars(r.int(0, 999), 2))],
  ["prepend newer than held", "order", (s) => s.prepend(bars(1500, 2))],
  ["patch breaking order", "order", (s) => s.patch(10, bars(500, 2))],
  ["count above maxBars", "ceiling", (s) => s.append(B(2049))],
  ["unequal column lengths", "length", (s) => s.append({ ...B(), close: new Int32Array(3) })],
  ["patch outside the held range", "range", (s, r) => s.patch(r.int(1000, 5000), B(2))],
  ["another series' origin", "origin", (s) => s.append(B(2, 1))],
  ["untyped column", "type", (s) => s.append({ ...B(2), open: [1, 2] as unknown as Int32Array })],
];

type Bars = ReturnType<typeof bars>;
function poke(b: Bars, col: "time" | "volume" | "delta", r: Rng, v: number): Bars {
  const arr = b[col] as Float64Array | Float32Array;
  arr[r.int(0, arr.length - 1)] = v;
  return b;
}

function dup(b: Bars): Bars {
  b.time[2] = b.time[1] as number;
  return b;
}

describe("Scenario: Malformed frames are rejected without collateral damage (G4, store boundary)", () => {
  it("13 hostile classes over 25 seeds: ENGINE_DECODE_ERROR with its reason, store byte-identical", () => {
    for (const seed of SEEDS) {
      const r = rng(seed);
      const store = new BarStore({ maxBars: 2048, initialCapacity: 16 });
      store.append(bars(0, 1000));
      const counts: Partial<Record<RejectReason, number>> = {};
      for (let i = 0; i < 40; i += 1) {
        const [name, reason, apply] = r.pick(HOSTILE);
        const at = `seed ${seed}: ${name}`;
        const before = snapshot(store);
        let err: unknown = null;
        try {
          apply(store, r);
        } catch (e) {
          err = e;
        }
        expect(err, at).toBeInstanceOf(ModelRejection);
        expect([(err as ModelRejection).code, (err as ModelRejection).reason], at).toEqual([
          ENGINE_DECODE_ERROR,
          reason,
        ]);
        expect(snapshot(store) === before, at).toBe(true);
        counts[reason] = (counts[reason] ?? 0) + 1;
      }
      expect(store.counters.rejectedMutations).toMatchObject(counts);
      // The scene's data carries on: the next valid batch lands where it should.
      store.append(bars(1000, 5));
      expect(
        [store.length, store.indexToTime(1004) - store.indexToTime(1003)],
        `seed ${seed}`,
      ).toEqual([1005, 60_000_000]);
    }
  });

  it.todo(
    "G4 hostile values reach the store through the runtime's data path (pending: E12-T06 #399, bars seam wiring)",
  );
  it.todo("G4 the memoryBudgetMb ceiling holds under adversarial input (pending: E11-S15 #448)");
  it.todo(
    "G4 pixels, not a fake-GL digest, unchanged after a rejected batch (pending: E11-T08 #391)",
  );
});

/** A worker-mode host on the fake DOM, recording resync requests. */
function workerHost(resyncs: StoreId[]): ChartHost {
  const doc = new FakeDocument();
  doc.offscreenAvailable = true;
  doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
  let canvas = doc.createElement("canvas");
  return createChartHost({
    realm: doc,
    runMode: "worker",
    env: fakeEnv(),
    canvas: () => asHtml(canvas) as HTMLCanvasElement,
    replaceCanvas: () => {
      canvas = doc.createElement("canvas");
      return asHtml(canvas) as HTMLCanvasElement;
    },
    dpr: 1,
    theme: {},
    syncGroup: null,
    bench: false,
    listener: {
      deliver: () => undefined,
      lost: () => undefined,
      restored: () => undefined,
      resync: (store) => resyncs.push(store),
    },
  });
}

const delivered = (): Extract<ToWorker, { t: "data" }>[] =>
  (FakeWorker.created.at(-1)?.inbox ?? []).filter(
    (m): m is Extract<ToWorker, { t: "data" }> => (m as ToWorker).t === "data",
  );

describe("Scenario: A sequence gap resyncs rather than drawing wrong data (G5, engine layer only)", () => {
  // Engine-layer evidence for H-05 / CE-D05 (BQ-04), not a pass for G5: the socket-sequence half
  // and the stale indicator (F-05) are pending rows.
  it("a seeded mixed-op storm: any dropped batch asks for exactly one resync per episode", () => {
    const ops: DataOp[] = ["append", "append", "patch", "prepend", "replace"];
    let overloaded = 0;
    for (const seed of SEEDS) {
      vi.clearAllTimers();
      const r = rng(seed);
      const resyncs: StoreId[] = [];
      const host = workerHost(resyncs);
      vi.advanceTimersByTime(20);
      let episodes = 0;
      for (let burst = 0; burst < 4; burst += 1) {
        const dropped = host.counters.messagesDropped;
        for (let i = 0; i < r.int(1, 30); i += 1) {
          const n = r.int(1, 3);
          host.data(
            "bars",
            r.pick(ops),
            { count: n, columns: [{ offset: 0, bytes: 8 }], params: [] },
            new ArrayBuffer(8 * n),
          );
        }
        if (host.counters.messagesDropped > dropped) episodes += 1;
        expect([burst, resyncs.length], `seed ${seed}`).toEqual([burst, episodes]);
        overloaded += host.counters.messagesDropped > dropped ? 1 : 0;
        vi.advanceTimersByTime(20); // the acks drain the queue: the episode ends
      }
      expect(delivered().every((m) => m.layout.count > 0)).toBe(true);
      host.dispose();
    }
    expect(overloaded).toBeGreaterThan(0); // 9 of the 100 bursts overload the queue at these seeds
  });

  it.todo(
    "G5 a socket sequence gap requests a snapshot before later frames apply (pending: E12-T06 #399, socket-gap wiring)",
  );
  it.todo(
    "G5 the per-pane stale indicator shows until the resync completes (pending: F-05, E12-S10 #396)",
  );
});

describe("Scope: a 60 s feed stall followed by a burst", () => {
  it("after the stall, a seeded append burst arrives whole, in order, with at most two batches in flight", () => {
    for (const seed of SEEDS) {
      vi.clearAllTimers();
      FakeWorker.created = [];
      const r = rng(seed);
      const host = workerHost([]);
      vi.advanceTimersByTime(60_000); // the stall: no data for a minute of fake time
      const T0 = 1_700_000_000_000_000;
      let next = 0;
      for (let i = 0; i < 200; i += 1) {
        const n = r.int(1, 20);
        const time = Float64Array.from({ length: n }, (_, j) => T0 + (next + j) * 1_000_000);
        next += n;
        host.data(
          "bars",
          "append",
          { count: n, columns: [{ offset: 0, bytes: 8 }], params: [] },
          time.buffer,
        );
      }
      vi.advanceTimersByTime(0);
      expect(delivered().length, `seed ${seed}`).toEqual(MAX_UNACKED); // the rest is held back
      vi.advanceTimersByTime(200);
      const times = delivered().flatMap((m) => [
        ...new Float64Array(m.buffer, m.layout.columns[0]?.offset, m.layout.count),
      ]);
      expect([times.length, host.counters.messagesDropped], `seed ${seed}`).toEqual([next, 0]);
      expect(times.every((t, i) => t === T0 + i * 1_000_000)).toBe(true); // no gap, no duplicate
      expect(delivered().length).toBeLessThanOrEqual(MAX_UNACKED + MAX_QUEUED);
      host.dispose();
    }
  });

  it.todo(
    "the post-burst catch-up does not stall the UI thread (pending: measured by E11-Q03 #445)",
  );
});
