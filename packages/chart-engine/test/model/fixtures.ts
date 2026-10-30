// Shared fixtures for the model tests (E11-T03): bars one minute apart, ticks derived from the index.
import type { BarBatch } from "../../src/model/index.js";

export const T0 = 1_700_000_000_000_000; // µs
export const STEP = 60_000_000;

/** `count` bars from logical minute `first` (negative = older history). */
export function bars(first: number, count: number, origin = 50_000, tickSize = 0.1): BarBatch {
  const time = Float64Array.from({ length: count }, (_, i) => T0 + (first + i) * STEP);
  const open = Int32Array.from({ length: count }, (_, i) => first + i);
  return {
    time,
    open,
    high: open.map((p) => p + 3),
    low: open.map((p) => p - 2),
    close: open.map((p) => p + 1),
    volume: Float32Array.from(open, (p) => Math.abs(p % 97) + 1),
    delta: Float32Array.from(open, (p) => (p % 7) - 3),
    priceOrigin: origin,
    tickSize,
  };
}

/** Every byte the store owns, plus its ring state: a rejected mutation must not change any. */
export function snapshot(store: {
  readonly columns: Readonly<Record<string, ArrayBufferView>>;
  readonly length: number;
  readonly ringHead: number;
  readonly priceOrigin: number;
  readonly tickSize: number;
}): string {
  const parts = Object.values(store.columns).map((c) =>
    Buffer.from(c.buffer, c.byteOffset, c.byteLength).toString("base64"),
  );
  const { length, ringHead, priceOrigin, tickSize } = store;
  return `${length}/${ringHead}/${priceOrigin}/${tickSize}/${parts.join("|")}`;
}
