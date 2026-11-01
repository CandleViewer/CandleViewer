// E12-S06 CandleRing properties (C-38 / README BQ-30: seeded mulberry32 loops, no fast-check; a
// failure prints its seed). Over random append / merge / patch / prepend / replace sequences on
// a small ring (growth, wrap, eviction): (1) the ring equals the store bar for bar; (2) a sync
// writes only the mutated range, or rewrites the whole ring exactly when the store reallocated;
// (3) through a real BatchBuilder and GlBuffers on the fake GL, every `bufferSubData` lands
// inside the mutated range, and a full upload happens only after a reallocation.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { GlBuffers } from "../../src/gl/buffers.js";
import { GlRegistry } from "../../src/gl/registry.js";
import { CANDLE_STRIDE, CandleRing } from "../../src/layers/index.js";
import { BarStore, ModelRejection, type BarBatch } from "../../src/model/index.js";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { PooledBatchSink } from "../../src/scene/pool.js";
import { FakeGl } from "../gl/fake-gl.js";
import { bars } from "../model/fixtures.js";
import { ringBar, storeBar } from "./fixtures.js";

const CASES = 2_000;

/** `bars(first, count)` with random OHLC inside a random range: the F-02 relations hold. */
function randomBars(rng: () => number, first: number, count: number): BarBatch {
  const b = bars(first, count);
  for (let j = 0; j < count; j += 1) {
    const lo = Math.floor(rng() * 50) - 25;
    const hi = lo + Math.floor(rng() * 4); // zero-range and doji bars happen often
    b.low[j] = lo;
    b.high[j] = hi;
    b.open[j] = lo + Math.floor(rng() * (hi - lo + 1));
    b.close[j] = lo + Math.floor(rng() * (hi - lo + 1));
  }
  return { ...b, flags: Uint8Array.from({ length: count }, () => Math.floor(rng() * 16)) };
}

describe("property: CandleRing mirrors its BarStore, writing and uploading only mutated ranges", () => {
  it(`holds for ${CASES} seeded cases`, { timeout: 60_000 }, () => {
    const failures: string[] = [];
    const seen = { rewrites: 0, subUploads: 0, evictions: 0, merges: 0, rejected: 0 };
    for (let c = 0; c < CASES && failures.length === 0; c += 1) {
      const seed = 20261101 + c;
      const rng = mulberry32(seed);
      const int = (n: number): number => Math.floor(rng() * n);
      const fail = (s: number, what: string): number =>
        failures.push(`seed=${seed} step ${s}: ${what}`);
      const maxBars = 4 + int(28);
      const store = new BarStore({ maxBars, initialCapacity: 1 + int(8) });
      const graph = new SceneGraph();
      graph.addPane("p");
      const node = new NullSeries("candle");
      graph.addNode("p", "series", node);
      const gl = new FakeGl();
      const buffers = new GlBuffers(gl, new GlRegistry(gl));
      const builder = new BatchBuilder(graph, buffers);
      const ring = new CandleRing(builder);
      ring.nodes.push(node.id);
      const sink = new PooledBatchSink(4);
      const frame = (): void => {
        node.count = Math.max(1, ring.length);
        node.collect(sink);
        builder.build(sink);
        sink.reset();
      };
      let [lo, hi] = [0, 0]; // minutes held: [lo, hi)
      ring.sync(store, store.replace(randomBars(rng, 0, 0)));
      buffers.attach(node.id, ring);
      frame();
      let gpu = ring.data; // the array the GPU holds
      for (let s = 0; s < 12; s += 1) {
        const op = int(5);
        const k = int(op === 4 ? maxBars + 1 : 6);
        const cols = store.columns;
        const realloc = store.counters.reallocations;
        gl.writes.length = 0;
        let r;
        try {
          if (op === 0) r = store.append(randomBars(rng, hi, k));
          else if (op === 1) {
            const merge = store.length > 0;
            r = store.append(randomBars(rng, merge ? hi - 1 : hi, k), true);
            if (merge && k > 0) [seen.merges, hi] = [seen.merges + 1, hi - 1];
          } else if (op === 2) {
            const n = store.length;
            const at = n === 0 ? 0 : int(n);
            const kk = Math.min(k, n - at);
            r = store.patch(at, randomBars(rng, lo + at, kk));
          } else if (op === 3) r = store.prepend(randomBars(rng, lo - k, k));
          else r = store.replace(randomBars(rng, (lo = int(100)), k));
        } catch (e) {
          if (!(e instanceof ModelRejection)) throw e;
          seen.rejected += 1; // e.g. a prepend past maxBars: nothing written, nothing synced
          continue;
        }
        if (op === 0 || op === 1) hi += k;
        if (op === 3) lo -= k;
        if (op === 4) hi = lo + k;
        lo = Math.max(lo, hi - store.length); // evictions drop the oldest
        seen.evictions += r.op === "append" ? r.indexShift : 0;
        const reallocated = store.columns !== cols || store.counters.reallocations !== realloc;
        const data = ring.data;
        ring.sync(store, r);
        // (1) bar for bar
        if (ring.length !== store.length) fail(s, `length ${ring.length} vs ${store.length}`);
        for (let i = 0; i < store.length; i += 1) {
          if (ringBar(ring, i).join() !== storeBar(store, i).join()) fail(s, `bar ${i} differs`);
        }
        // (2) writes ⊆ mutated range, or a whole rewrite iff the store reallocated
        if (reallocated !== (ring.data !== data)) fail(s, "rewrite without a reallocation");
        const whole = ring.lastFrom === 0 && ring.lastTo === store.length;
        if (!reallocated && (ring.lastFrom < r.from || ring.lastTo > r.to)) {
          fail(s, `wrote [${ring.lastFrom}, ${ring.lastTo}) outside [${r.from}, ${r.to})`);
        }
        if (reallocated && !whole) fail(s, "a reallocation rewrote only part of the ring");
        seen.rewrites += reallocated ? 1 : 0;
        // (3) uploads ⊆ mutated range; full only after a reallocation
        frame();
        const mask = ring.capacity - 1;
        for (const w of gl.writes) {
          const [kind, a, , len] = w.split(" ").map((x, i) => (i === 0 ? x : Number(x))) as [
            string,
            number,
            number,
            number,
          ];
          if (kind === "full") {
            // Only a new ring array (a store reallocation, maybe an earlier, empty one) uploads in full.
            if (ring.data === gpu) fail(s, "a full upload of an array already uploaded");
            gpu = ring.data;
            continue;
          }
          seen.subUploads += 1;
          const first = a / (CANDLE_STRIDE * 4);
          for (let p = first; p < first + len / CANDLE_STRIDE; p += 1) {
            const i = (p - ring.head) & mask;
            if (i < r.from || i >= r.to) fail(s, `uploaded bar ${i} outside [${r.from}, ${r.to})`);
          }
        }
      }
    }
    expect(failures).toEqual([]);
    // Every path was exercised.
    for (const [k, v] of Object.entries(seen)) expect(v, k).toBeGreaterThan(0);
  });
});
