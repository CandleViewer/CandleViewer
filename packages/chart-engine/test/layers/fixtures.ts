// Shared CandleRing test helpers (E12-S06): read the ring and the store slot by slot, through
// their own heads, without `store.view()` (which re-linearises a wrapped ring: a reallocation).
import { CANDLE_STRIDE, type CandleRing, candleDir } from "../../src/layers/index.js";
import type { BarStore } from "../../src/model/index.js";

/** Instance i of the ring as [o, h, l, c, meta]. */
export function ringBar(ring: CandleRing, i: number): number[] {
  const p = ((ring.head + i) & (ring.capacity - 1)) * CANDLE_STRIDE;
  return Array.from(ring.ints.subarray(p, p + CANDLE_STRIDE));
}

/** Bar i of the store as the ring must hold it. */
export function storeBar(store: BarStore, i: number): number[] {
  const { open, high, low, close, flags } = store.columns;
  const p = (store.ringHead + i) & (store.capacity - 1);
  const [o, h, l, c] = [open[p] ?? 0, high[p] ?? 0, low[p] ?? 0, close[p] ?? 0];
  return [o, h, l, c, ((flags[p] ?? 0) & 0x0f) | (candleDir(o, h, l, c) << 4)];
}
