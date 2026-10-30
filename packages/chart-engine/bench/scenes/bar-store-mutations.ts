// `bar-store` mutation microbench (E11-T03): a store of `size` bars (100k, 200k), each step one
// append, one patch of the last bar and, below maxBars, one prepend; zero allocation after setup.
// It reads no clock: bar-store-mutations.test.ts asserts the counts, the .perf.test.ts times it.
import { type BarBatch, BarStore } from "../../src/model/index.js";

const STEP_US = 60_000_000;

const batch = (count: number, firstUs: number): BarBatch => {
  const open = Int32Array.from({ length: count }, (_, i) => 1_000 + (i % 50));
  const time = Float64Array.from({ length: count }, (_, i) => firstUs + i * STEP_US);
  const volume = new Float32Array(count).fill(1);
  return { time, open, high: open, low: open, close: open, volume, priceOrigin: 0, tickSize: 1 };
};

export class BarStoreBench {
  readonly store = new BarStore();
  private readonly one = batch(1, 0);
  private next: number;
  private prev: number;
  private readonly warm: number;
  readonly columns: object;
  mutations = 0;

  constructor(size: number) {
    this.store.replace(batch(size, 0));
    [this.next, this.prev] = [size * STEP_US, -STEP_US];
    this.step(); // warm-up
    this.warm = this.store.counters.reallocations;
    this.columns = this.store.columns;
  }

  step(): void {
    const { store, one } = this;
    one.time[0] = this.next;
    this.next += STEP_US;
    store.append(one);
    store.patch(store.length - 1, one);
    this.mutations += 2;
    if (store.length >= store.maxBars) return;
    one.time[0] = this.prev;
    this.prev -= STEP_US;
    store.prepend(one);
    this.mutations += 1;
  }

  /** Reallocations since warm-up plus a swapped column set: must stay 0. */
  get allocationsInMutationPath(): number {
    const swapped = this.store.columns === this.columns ? 0 : 1;
    return this.store.counters.reallocations - this.warm + swapped;
  }
}
