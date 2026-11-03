// E24-S05 (#780) slice 1: the 250 ms coalescing buffer (`14` SCR-054; D02 §14). Prints wait here from the
// frame that read them until the animation frame after their 250 ms bucket closes, so render work follows
// the bucket clock, never the arrival rate. The burst rate is the prints of the last 500 ms push window
// (Bybit's batching, `23` §14.9 `note`) per second: one 500 ms push of 620 prints reads 1,240 prints/s
// (D02 §6). Buckets are monotonic-clock windows `[k·250, (k+1)·250)` of the arrival time.
import type { LiquidationPrint } from "./prints";

export const BUCKET_MS = 250;
/** One Bybit push window (`23` §14.9): the rate's span. */
export const RATE_WINDOW_MS = 500;
const RATE_BUCKETS = RATE_WINDOW_MS / BUCKET_MS;

export const bucketOf = (nowMs: number): number => Math.floor(nowMs / BUCKET_MS);

export class LiquidationCoalescer {
  private pending: LiquidationPrint[] = [];
  private pendingBucket: number | null = null;
  /** Arrived prints per bucket, the rate window's only. */
  private readonly counts = new Map<number, number>();
  /** Buckets flushed so far (a client metric, the ticket's Observability). */
  flushed = 0;

  /** Prints read at `nowMs`. `live` prints count toward the rate; a snapshot's replay does not. */
  add(prints: readonly LiquidationPrint[], nowMs: number, live: boolean): void {
    if (prints.length === 0) return;
    const bucket = bucketOf(nowMs);
    this.pendingBucket ??= bucket;
    for (const print of prints) this.pending.push(print);
    if (live) this.counts.set(bucket, (this.counts.get(bucket) ?? 0) + prints.length);
  }

  /** The prints whose bucket has closed by `nowMs`, oldest first, or `null` while it is open. */
  drain(nowMs: number): readonly LiquidationPrint[] | null {
    if (this.pendingBucket === null || bucketOf(nowMs) <= this.pendingBucket) return null;
    const out = this.pending;
    this.pending = [];
    this.pendingBucket = null;
    this.flushed += 1;
    return out;
  }

  /**
   * Prints per second over the last closed push window. A lower bound by construction: Bybit batches at most
   * one push per symbol per 500 ms (`23` §14.9), so prints that venue merged are never counted. D02 DV-8 keeps
   * "lower bounds" off the screen; the completeness sentence says it instead.
   */
  rateLowerBound(nowMs: number): number {
    const current = bucketOf(nowMs);
    let sum = 0;
    for (const [bucket, n] of this.counts) {
      if (bucket < current - RATE_BUCKETS) this.counts.delete(bucket);
      else if (bucket < current) sum += n;
    }
    return Math.round((sum * 1000) / RATE_WINDOW_MS);
  }

  clear(): void {
    this.pending = [];
    this.pendingBucket = null;
    this.counts.clear();
  }
}
