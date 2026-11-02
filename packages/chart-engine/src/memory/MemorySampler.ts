// MemorySampler (26 §7 "When", E11-S15 BQ-S15-12): reads a chart's `MemoryAccount` every
// `memory.sampleIntervalMs` on the runtime's existing 1 s tick, and at once on a resize; never per
// frame and never on a timer of its own, so a parked chart is not woken. A sample reads
// `totalBytes` only (never `ids`) and allocates nothing. The governor (PR-2) consumes `usedMb`.
import type { MemoryAccount } from "./MemoryAccount.js";

/** `memory.sampleIntervalMs` default (ticket config key; 26 §7). */
export const MEMORY_SAMPLE_INTERVAL_MS = 5000;

const MIB = 2 ** 20;

export class MemorySampler {
  /** The bytes the last sample read (0 before the first). */
  usedBytes = 0;
  /** Samples taken (tests and diagnostics). */
  samples = 0;
  private last = Number.NEGATIVE_INFINITY;

  /** Throws `RangeError` unless `intervalMs` is a positive safe integer. */
  constructor(
    private readonly account: MemoryAccount,
    readonly intervalMs = MEMORY_SAMPLE_INTERVAL_MS,
  ) {
    if (!Number.isSafeInteger(intervalMs) || intervalMs < 1) {
      throw new RangeError("chart-engine: memory.sampleIntervalMs must be a positive integer");
    }
  }

  /** The 1 s tick: samples when `intervalMs` has passed since the last sample; true if it did. */
  tick(now: number): boolean {
    if (now - this.last < this.intervalMs) return false;
    this.sample(now);
    return true;
  }

  /** Samples now (a resize) and restarts the interval; returns the bytes read. */
  sample(now: number): number {
    this.last = now;
    this.usedBytes = this.account.totalBytes;
    this.samples += 1;
    return this.usedBytes;
  }

  /** The last sample in MiB, the unit of `memoryBudgetMb`. */
  get usedMb(): number {
    return this.usedBytes / MIB;
  }
}
