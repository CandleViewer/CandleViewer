// A drawing as the layer keeps it (E14-T03): `copyInput`'s whitelisted copy plus its anchors in
// chart space and the per-map caches the projection fills. Its own module so `project.ts` (the
// node) and `lines.ts` (the instance ring) both read it with no cycle. DOM- and GL-free.
import { copyInput, type DrawingInput } from "./model.js";

export interface DrawingRecord {
  /** `copyInput`'s whitelisted copy: kind, style, z, visibility and the clamped label. */
  readonly input: DrawingInput;
  readonly t: Float64Array;
  readonly tick: Float64Array;
  /** Each anchor's fractional bar index under the map stamped in `stamp`. */
  readonly idx: Float64Array;
  /** [idxMin, tickMin, idxMax, tickMax], a band's implied fourth corner included. */
  readonly box: Float64Array;
  stamp: number;
}

export function toRecord(d: DrawingInput): DrawingRecord {
  const input = copyInput(d);
  const n = input.points.length / 2;
  const r = {
    input,
    t: new Float64Array(n),
    tick: new Float64Array(n),
    idx: new Float64Array(n),
    box: new Float64Array(4),
    stamp: -1,
  };
  for (let i = 0; i < n; i += 1) {
    r.t[i] = input.points[2 * i] as number;
    r.tick[i] = input.points[2 * i + 1] as number;
  }
  return r;
}
