// VolumeExtentSource (E12-S08, E12-D06 §12; BQ-6): the autoscale source of a volume pane, in the
// `PriceExtentSource` shape the `AutoScaler` reads per pane. Linear only: the range is exactly
// [0, the visible maximum] in ticks (the minimum is forced to 0, so the columns stand on the pane
// bottom). NO top margin: the pane's `marginTop` / `marginBottom` are 0 (`VOLUME_PANE_MARGINS`,
// PR 2 sets them); lock / unlock are the scaler's. Unavailable bars do not count. It reads the volume ring's int words, so what it
// fits is what is drawn. `version` is bumped by `bump()` (the series calls it on every sync),
// the key the scaler refits on. No allocation per call.
import type { PriceExtentSource } from "../../viewport/autoscale.js";
import { CANDLE_STRIDE, type CandleRing } from "../candle/ring.js";
import { VOLUME_UNAVAILABLE } from "./volume-ring.js";

export class VolumeExtentSource implements PriceExtentSource {
  readonly kind = "series" as const;
  version = 0;

  constructor(private readonly ring: CandleRing) {}

  bump(): void {
    this.version += 1;
  }

  /** [0, max volume in ticks] over bars [i0, i1) clipped to the ring; false when none count. */
  extent(i0: number, i1: number, out: Float64Array): boolean {
    const r = this.ring;
    const a = Math.max(0, i0);
    const b = Math.min(r.length, i1);
    const mask = r.capacity - 1;
    const ints = r.ints;
    let max = -1;
    for (let i = a; i < b; i += 1) {
      const w = ((r.head + i) & mask) * CANDLE_STRIDE;
      if (((ints[w + 4] as number) & VOLUME_UNAVAILABLE) !== 0) continue;
      const v = ints[w] as number;
      if (v > max) max = v;
    }
    if (max < 0) return false;
    out[0] = 0;
    out[1] = max;
    return true;
  }

  /** The log guard's lowest low: volume is never log-scaled, its floor is 0. */
  minLow(): number {
    return this.ring.length === 0 ? Number.NaN : 0;
  }
}
