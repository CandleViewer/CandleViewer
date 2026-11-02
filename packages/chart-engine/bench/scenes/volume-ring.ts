// `volume-ring` scene (E12-S08 pre-stage, rule 31: a new layer adds a scene): the live-feed data
// plane of one volume series borrowing the price store. A store of `size` bars and a VolumeSeries
// whose ring is patched for one node (`series.volume.body`); each step is a forming-bar update
// (append-merge: a patch) then a new bar (append). It reads no clock: volume-ring.test.ts asserts
// the counts and zero allocation after warm-up, volume-ring.perf.test.ts times it.
import { VolumeSeries } from "../../src/layers/volume/series.js";
import { type BarBatch, BarStore } from "../../src/model/index.js";
import type { MutationRange } from "../../src/model/counters.js";

const STEP_US = 60_000_000;

export class VolumeRingBench {
  readonly store: BarStore;
  readonly series: VolumeSeries;
  /** Batch patches recorded: one node per mutation. */
  patches = 0;
  private readonly one: BarBatch;
  private next: number;
  private readonly warm: { rewrites: number; data: Float32Array; reallocations: number };

  constructor(size: number) {
    this.store = new BarStore({ maxBars: size });
    this.series = new VolumeSeries({
      patch: (_: string, r: MutationRange) => void (this.patches += r.to - r.from > 0 ? 1 : 0),
    });
    this.series.ring.nodes.push("series.volume.body");
    const open = Int32Array.from({ length: size }, (_, i) => 1_000 + (i % 50));
    this.series.sync(
      this.store,
      this.store.replace({
        time: Float64Array.from({ length: size }, (_, i) => i * STEP_US),
        open,
        high: open.map((o) => o + 4),
        low: open.map((o) => o - 3),
        close: open.map((o, i) => o + ((i % 5) - 2)),
        volume: Float32Array.from({ length: size }, (_, i) => 1 + (i % 97) * 0.25),
        flags: new Uint8Array(size),
        priceOrigin: 0,
        tickSize: 1,
      }),
    );
    const t = (size - 1) * STEP_US;
    this.one = {
      time: Float64Array.of(t),
      open: Int32Array.of(1_000),
      high: Int32Array.of(1_004),
      low: Int32Array.of(997),
      close: Int32Array.of(1_001),
      volume: Float32Array.of(2.5),
      flags: Uint8Array.of(2),
      priceOrigin: 0,
      tickSize: 1,
    };
    this.next = t;
    this.step(); // warm-up: the first eviction's growth to the ceiling capacity
    this.warm = {
      rewrites: this.series.ring.rewrites,
      data: this.series.ring.data,
      reallocations: this.store.counters.reallocations,
    };
  }

  /** One forming-bar update (merged patch) and one new bar. */
  step(): void {
    const { store, series, one } = this;
    one.time[0] = this.next;
    one.close[0] = 1_000 + (this.patches & 3);
    series.sync(store, store.append(one, true));
    this.next += STEP_US;
    one.time[0] = this.next;
    series.sync(store, store.append(one, true));
  }

  /** One frame's per-frame work (geometry + block words): must allocate nothing. */
  frame(): void {
    this.series.frame(8, 2);
  }

  /** Ring rewrites, store reallocations and a swapped ring array since warm-up: must stay 0. */
  get allocationsInMutationPath(): number {
    const w = this.warm;
    const ring = this.series.ring;
    const swapped = ring.data === w.data ? 0 : 1;
    return (
      ring.rewrites - w.rewrites + this.store.counters.reallocations - w.reallocations + swapped
    );
  }
}
