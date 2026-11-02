// The mirror window's rows (E11-S13 PR-2; E06-D03 D9 `A11yRows`, 26 §12): the worker copies the
// cursor-centred window's bars into a struct-of-arrays, transferred with the `a11y` message, and
// the main thread validates it before the DOM mirror reads it. Pure: no DOM, no I/O (C-2.16).
import { A11Y_WINDOW_ROWS_MAX, type A11yRows, type A11yWindow } from "./window.js";

/** Pane 0's bars as columns (`BarView` fits structurally); the runtime's source until E12. */
export interface A11yBarSource {
  readonly length: number;
  readonly time: Float64Array;
  readonly open: Int32Array;
  readonly high: Int32Array;
  readonly low: Int32Array;
  readonly close: Int32Array;
  readonly volume: Float32Array;
  readonly delta?: Float32Array | undefined;
  readonly priceOrigin: number;
  readonly tickSize: number;
}

/** The decimals a tick size prints with (0.1 -> 1, 0.0005 -> 4), so labels equal the axis's. */
export function priceDecimalsOf(tickSize: number): number {
  if (!(tickSize > 0) || !Number.isFinite(tickSize)) return 0;
  for (let d = 0; d < 12; d += 1) {
    const scaled = tickSize * 10 ** d;
    if (scaled >= 0.5 && Math.abs(scaled - Math.round(scaled)) < 1e-9 * scaled) return d;
  }
  return 12;
}

/**
 * Copies `w`'s rows out of `bars` (fresh arrays: they are transferred, so never reused). Every row
 * is listed dirty in PR-2; the mirror diffs per cell, so an unchanged cell is never written.
 * `prevFirstBar` gives `shifted` (D2); null when the window is empty or the source too short.
 */
export function buildA11yRows(
  w: A11yWindow,
  bars: A11yBarSource,
  prevFirstBar: number,
): A11yRows | null {
  const count = Math.min(w.lastBar - w.firstBar + 1, A11Y_WINDOW_ROWS_MAX);
  if (count <= 0 || w.firstBar + count > bars.length) return null;
  const from = w.firstBar;
  const to = from + count;
  const dirty = new Uint16Array(count);
  for (let i = 0; i < count; i += 1) dirty[i] = i;
  return {
    firstBar: from,
    count,
    shifted: prevFirstBar < 0 ? count : from - prevFirstBar,
    dirty,
    time: bars.time.slice(from, to),
    open: bars.open.slice(from, to),
    high: bars.high.slice(from, to),
    low: bars.low.slice(from, to),
    close: bars.close.slice(from, to),
    volume: bars.volume.slice(from, to),
    delta: bars.delta?.slice(from, to) ?? new Float32Array(count),
    priceOrigin: bars.priceOrigin,
    tickSize: bars.tickSize,
    priceDecimals: priceDecimalsOf(bars.tickSize),
  };
}

/** The buffers to transfer with an `a11y` message that carries rows. */
export const rowsTransfer = (r: A11yRows): ArrayBuffer[] =>
  [r.dirty, r.time, r.open, r.high, r.low, r.close, r.volume, r.delta].map(
    (a) => a.buffer as ArrayBuffer,
  );

const COLUMNS = [
  ["time", Float64Array],
  ["open", Int32Array],
  ["high", Int32Array],
  ["low", Int32Array],
  ["close", Int32Array],
  ["volume", Float32Array],
  ["delta", Float32Array],
] as const;

/** Main-thread validation of `rows`; anything malformed is null (the mirror keeps its rows). */
export function readA11yRows(v: unknown): A11yRows | null {
  if (typeof v !== "object" || v === null) return null;
  const r = v as Record<string, unknown>;
  const count = r["count"];
  if (!Number.isSafeInteger(count) || (count as number) < 1) return null;
  if ((count as number) > A11Y_WINDOW_ROWS_MAX || !Number.isSafeInteger(r["firstBar"])) return null;
  if (!Number.isSafeInteger(r["shifted"]) || !(r["dirty"] instanceof Uint16Array)) return null;
  for (const [k, Ctor] of COLUMNS) {
    const col = r[k];
    if (!(col instanceof Ctor) || col.length < (count as number)) return null;
  }
  const ok = ["priceOrigin", "tickSize"].every((k) => Number.isFinite(r[k] as number));
  // `toFixed` throws outside 0..100; the decimals a tick prints with are 0..12 (priceDecimalsOf).
  const d = r["priceDecimals"];
  const decimalsOk = Number.isSafeInteger(d) && (d as number) >= 0 && (d as number) <= 20;
  return ok && decimalsOk ? (v as A11yRows) : null;
}
