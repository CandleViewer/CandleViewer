// `candle-ring` scene (E12-S06 PR A): the live-feed data plane for one candle series. A store of
// `size` bars and its CandleRing patched into a BatchBuilder; each step is a forming-bar update
// (append-merge: equal time, a patch) then a new bar (append), each mirrored into the ring and
// patched for two nodes (wick, body). It reads no clock: candle-ring.test.ts asserts the counts
// and zero allocation after warm-up, candle-ring.perf.test.ts times it.
import { CandleRing } from "../../src/layers/candle/ring.js";
import { type BarBatch, BarStore } from "../../src/model/index.js";
import type { MutationRange } from "../../src/model/counters.js";

const STEP_US = 60_000_000;

export class CandleRingBench {
  readonly store: BarStore;
  readonly ring: CandleRing;
  /** Batch patches recorded: two nodes per mutation. */
  patches = 0;
  private readonly one: BarBatch;
  private next: number;
  private readonly warm: { rewrites: number; data: Float32Array; reallocations: number };

  constructor(size: number) {
    this.store = new BarStore({ maxBars: size });
    this.ring = new CandleRing({
      patch: (_: string, r: MutationRange) => void (this.patches += r.to - r.from > 0 ? 1 : 0),
    });
    this.ring.nodes.push("series.candle.wick", "series.candle.body");
    const n = size;
    const open = Int32Array.from({ length: n }, (_, i) => 1_000 + (i % 50));
    const high = open.map((o) => o + 4);
    const low = open.map((o) => o - 3);
    const close = open.map((o, i) => o + ((i % 5) - 2));
    const time = Float64Array.from({ length: n }, (_, i) => i * STEP_US);
    const volume = new Float32Array(n).fill(1);
    const flags = new Uint8Array(n); // one batch shape throughout, as `decodeBars` produces
    this.ring.sync(
      this.store,
      this.store.replace({
        time,
        open,
        high,
        low,
        close,
        volume,
        flags,
        priceOrigin: 0,
        tickSize: 1,
      }),
    );
    const t = (n - 1) * STEP_US;
    this.one = {
      time: Float64Array.of(t),
      open: Int32Array.of(1_000),
      high: Int32Array.of(1_004),
      low: Int32Array.of(997),
      close: Int32Array.of(1_001),
      volume: Float32Array.of(1),
      flags: Uint8Array.of(2),
      priceOrigin: 0,
      tickSize: 1,
    };
    this.next = t;
    this.step(); // warm-up: the first eviction's growth to the ceiling capacity
    this.warm = {
      rewrites: this.ring.rewrites,
      data: this.ring.data,
      reallocations: this.store.counters.reallocations,
    };
  }

  /** One forming-bar update (merged patch) and one new bar. */
  step(): void {
    const { store, ring, one } = this;
    one.time[0] = this.next;
    one.close[0] = 1_000 + (this.patches & 3);
    ring.sync(store, store.append(one, true)); // equal time: patches the live bar
    this.next += STEP_US;
    one.time[0] = this.next;
    ring.sync(store, store.append(one, true)); // a new bar: evicts at maxBars
  }

  /** Ring rewrites, store reallocations and a swapped ring array since warm-up: must stay 0. */
  get allocationsInMutationPath(): number {
    const w = this.warm;
    const swapped = this.ring.data === w.data ? 0 : 1;
    return (
      this.ring.rewrites -
      w.rewrites +
      this.store.counters.reallocations -
      w.reallocations +
      swapped
    );
  }
}
