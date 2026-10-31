// A synthetic 1-minute map (E11-S04, BQ-111): the runtime holds no bars until E12, so the
// anchoring and gesture tests project through this instead.
import { INPUT_STRIDE } from "../../src/worker/protocol.js";
import type { IndexTimeMap } from "../../src/viewport/index.js";

export const MIN = 60e6; // µs
export const T0 = Date.UTC(2026, 9, 30) * 1000; // 2026-10-30T00:00Z, µs
export const AT_14 = T0 + 14 * 60 * MIN; // the 14:00 bar

export function minuteMap(n = 2000, t0 = T0): IndexTimeMap {
  return {
    length: n,
    barDurationUs: MIN,
    indexToTime: (i) => (i >= 0 && i < n ? t0 + i * MIN : Number.NaN),
    timeToIndex: (t) => (t < t0 ? -1 : Math.min(n - 1, Math.floor((t - t0) / MIN))),
  };
}

/** Packs `[type, x, y, buttons, modifiers, dt]` rows. */
export const rows = (...r: number[][]): Float32Array => {
  const out = new Float32Array(r.length * INPUT_STRIDE);
  r.forEach((row, i) => out.set(row, i * INPUT_STRIDE));
  return out;
};
