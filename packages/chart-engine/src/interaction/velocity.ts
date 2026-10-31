// The release velocity (E11-S04 PR 1, README BQ-103): an exponentially weighted average over the
// last ~50 ms of coalesced samples, not a two-point difference, which is noisy at 240 Hz. Time
// comes from each row's `dt` column, so a sample train gives the same answer at any frame rate.
import { MOMENTUM } from "./momentum.js";

export class VelocityEstimator {
  /** px/ms, signed. */
  v = 0;
  /** ms since the pointer last moved. */
  still = 0;
  private carry = 0; // px of samples with no elapsed time yet (same timestamp)

  reset(): void {
    this.v = 0;
    this.still = 0;
    this.carry = 0;
  }

  /** One coalesced sample: `dx` px over `dtMs`. */
  sample(dx: number, dtMs: number): void {
    const d = dx + this.carry;
    if (!(dtMs > 0)) {
      this.carry = d;
      return;
    }
    this.carry = 0;
    const a = 1 - Math.exp(-dtMs / MOMENTUM.ewmaMs);
    this.v += a * (d / dtMs - this.v);
    this.still = d === 0 ? this.still + dtMs : 0;
  }

  /** The velocity at a release `dtMs` after the last sample: 0 once the pointer rested > 100 ms. */
  release(dtMs: number): number {
    const still = this.still + (dtMs > 0 ? dtMs : 0);
    return still > MOMENTUM.stillMs ? 0 : this.v;
  }
}
