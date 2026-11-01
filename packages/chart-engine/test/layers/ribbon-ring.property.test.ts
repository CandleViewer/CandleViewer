// E12-S07 PR B: the ribbon's +1 instance read over a wrapped CandleRing (plan §8's likely bug).
// Seeded mulberry32 loops (C-38 / README BQ-30; a failure prints its seed) over random append /
// merge / patch / prepend / replace sequences on small rings (growth, wrap, eviction):
// (1) for every slot the shader draws, the next-slot attribute (`a_next`, read one stride on in
// the guarded array) is the close of logical bar i + 1, where i = (slot - head) & mask: across
// the wrap the guard slot stands in for slot 0; (2) through a real BatchBuilder and GlBuffers
// on the fake GL, the GPU copy (the logged writes replayed) equals the ring for every live
// slot and the guard, so a changed-range upload never leaves the guard stale.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { GlBuffers } from "../../src/gl/buffers.js";
import { GlRegistry } from "../../src/gl/registry.js";
import { CANDLE_STRIDE, CandleRing, RibbonSource } from "../../src/layers/index.js";
import { BarStore, ModelRejection, type BarBatch } from "../../src/model/index.js";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { PooledBatchSink } from "../../src/scene/pool.js";
import { FakeGl } from "../gl/fake-gl.js";
import { bars } from "../model/fixtures.js";

const CASES = 1_000;

function randomBars(rng: () => number, first: number, count: number): BarBatch {
  const b = bars(first, count);
  for (let j = 0; j < count; j += 1) {
    const lo = Math.floor(rng() * 50) - 25;
    b.low[j] = lo;
    b.high[j] = lo + 3;
    b.open[j] = lo + 1;
    b.close[j] = lo + Math.floor(rng() * 4);
  }
  return { ...b, flags: Uint8Array.from({ length: count }, () => (rng() < 0.2 ? 1 : 0)) };
}

describe("property: the ribbon's next-slot read and its guard upload on a wrapped ring", () => {
  it(`holds for ${CASES} seeded cases`, { timeout: 60_000 }, () => {
    const failures: string[] = [];
    const seen = { wrapped: 0, guardUploads: 0 };
    for (let c = 0; c < CASES && failures.length === 0; c += 1) {
      const seed = 20261102 + c;
      const rng = mulberry32(seed);
      const int = (n: number): number => Math.floor(rng() * n);
      const fail = (s: number, what: string): number =>
        failures.push(`seed=${seed} step ${s}: ${what}`);
      const maxBars = 4 + int(20);
      const store = new BarStore({ maxBars, initialCapacity: 1 + int(8) });
      const graph = new SceneGraph();
      graph.addPane("p");
      const node = new NullSeries("ribbon");
      graph.addNode("p", "series", node);
      const gl = new FakeGl();
      const buffers = new GlBuffers(gl, new GlRegistry(gl));
      const builder = new BatchBuilder(graph, buffers);
      const ring = new CandleRing(builder);
      const source = new RibbonSource(ring);
      ring.nodes.push(node.id);
      const sink = new PooledBatchSink(4);
      let gpu = new Int32Array(0); // the GL buffer, replayed from the fake's write log
      const frame = (): void => {
        gl.writes.length = 0;
        node.count = Math.max(1, ring.length);
        node.collect(sink);
        builder.build(sink);
        sink.reset();
        const src = new Int32Array(source.data.buffer, 0, source.data.length);
        for (const w of gl.writes) {
          const [kind, a = 0, from = 0, n = 0] = w.split(" ");
          if (kind === "full") gpu = src.slice();
          else {
            gpu.set(src.subarray(Number(from), Number(from) + Number(n)), Number(a) / 4);
            if (Number(a) === ring.capacity * CANDLE_STRIDE * 4) seen.guardUploads += 1;
          }
        }
      };
      let [lo, hi] = [0, 0];
      ring.sync(store, store.replace(randomBars(rng, 0, 0)));
      buffers.attach(node.id, source);
      frame();
      for (let s = 0; s < 14; s += 1) {
        const op = int(5);
        const k = int(op === 4 ? maxBars + 1 : 6);
        let r;
        try {
          if (op <= 1) {
            const merge = op === 1 && store.length > 0;
            r = store.append(randomBars(rng, merge ? hi - 1 : hi, k), merge);
            if (merge && k > 0) hi -= 1;
          } else if (op === 2) {
            const n = store.length;
            const at = n === 0 ? 0 : int(n);
            r = store.patch(at, randomBars(rng, lo + at, Math.min(k, n - at)));
          } else if (op === 3) r = store.prepend(randomBars(rng, lo - k, k));
          else r = store.replace(randomBars(rng, (lo = int(100)), k));
        } catch (e) {
          if (!(e instanceof ModelRejection)) throw e;
          continue;
        }
        if (op <= 1) hi += k;
        if (op === 3) lo -= k;
        if (op === 4) hi = lo + k;
        lo = Math.max(lo, hi - store.length);
        ring.sync(store, r);
        frame();
        const cap = ring.capacity;
        const mask = cap - 1;
        const n = ring.length;
        const close = store.columns.close;
        const words = new Int32Array(source.data.buffer, 0, source.data.length);
        if (words.length !== (cap + 1) * CANDLE_STRIDE) fail(s, "no guard slot");
        // (1) the shader's mapping: slot → bar i, the next attribute → bar i + 1's close
        for (let slot = 0; slot < cap; slot += 1) {
          const i = (slot - ring.head) & mask;
          if (i + 1 >= n) continue;
          const next = words[(slot + 1) * CANDLE_STRIDE + 3];
          const want = close[(store.ringHead + i + 1) & mask];
          if (next !== want) fail(s, `slot ${slot}: next close ${next}, bar ${i + 1} is ${want}`);
          if (slot === cap - 1) seen.wrapped += 1;
        }
        // (2) the GPU copy: every live slot and, while slot 0 is live, the guard
        for (let i = 0; i < n; i += 1) {
          const at = ((ring.head + i) & mask) * CANDLE_STRIDE;
          for (let w = 0; w < CANDLE_STRIDE; w += 1) {
            if (gpu[at + w] !== words[at + w]) fail(s, `gpu bar ${i} word ${w} is stale`);
          }
        }
        if (((0 - ring.head) & mask) < n) {
          for (let w = 0; w < CANDLE_STRIDE; w += 1) {
            const g = cap * CANDLE_STRIDE + w;
            if (gpu[g] !== words[w]) fail(s, `the guard's word ${w} is stale on the GPU`);
          }
        }
      }
    }
    expect(failures).toEqual([]);
    expect(seen.wrapped).toBeGreaterThan(50); // the wrap is exercised, not assumed
    expect(seen.guardUploads).toBeGreaterThan(50);
  });
});
