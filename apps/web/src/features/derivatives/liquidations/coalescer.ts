// E24-S05 (#780) slice 1: the 250 ms coalescing buffer (`14` SCR-054; D02 §14). Prints wait here from the
// frame that read them until the animation frame after their 250 ms bucket closes, so render work follows
// the bucket clock, never the arrival rate. Buckets are monotonic-clock windows `[k·250, (k+1)·250)` of the
// arrival time.
// The burst rate is the live prints of the newest 500 ms push window (Bybit's batching, `23` §14.9 `note`)
// per second, windowed on the prints' own `ts_ms`: one 500 ms push of 620 prints reads 1,240 prints/s
// (D02 §6), and a backlog read at once (a hidden tab) is not counted as one burst. It holds for one push
// window plus a margin after the last live print arrived, so frame jitter never blinks it to 0.
import type { LiquidationPrint } from "./prints";

export const BUCKET_MS = 250;
/** One Bybit push window (`23` §14.9): the rate's span. */
export const RATE_WINDOW_MS = 500;
/** The rate's hold after the last live arrival: one push window plus a bucket. */
export const RATE_HOLD_MS = RATE_WINDOW_MS + BUCKET_MS;

export const bucketOf = (nowMs: number): number => Math.floor(nowMs / BUCKET_MS);

export class LiquidationCoalescer {
  private pending: LiquidationPrint[] = [];
  private pendingBucket: number | null = null;
  /** Live prints' `ts_ms` inside the newest push window. */
  private times: number[] = [];
  private newestLiveTs = -Infinity;
  private lastLiveArrival: number | null = null;
  /** Buckets flushed so far (a client metric, the ticket's Observability). */
  flushed = 0;

  /** Prints read at `nowMs`. `live` prints count toward the rate; a snapshot's replay does not. */
  add(prints: readonly LiquidationPrint[], nowMs: number, live: boolean): void {
    if (prints.length === 0) return;
    this.pendingBucket ??= bucketOf(nowMs);
    for (const print of prints) this.pending.push(print);
    if (!live) return;
    this.lastLiveArrival = nowMs;
    for (const print of prints) {
      if (print.tsMs > this.newestLiveTs) this.newestLiveTs = print.tsMs;
      this.times.push(print.tsMs);
    }
    const floor = this.newestLiveTs - RATE_WINDOW_MS;
    if ((this.times[0] ?? Infinity) <= floor) this.times = this.times.filter((t) => t > floor);
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
   * Prints per second over the newest push window. A lower bound by construction: Bybit batches at most one
   * push per symbol per 500 ms (`23` §14.9), so prints that venue merged are never counted. D02 DV-8 keeps
   * "lower bounds" off the screen (per ruling 19:33Z); the completeness sentence says it instead.
   */
  rateLowerBound(nowMs: number): number {
    if (this.lastLiveArrival === null || nowMs - this.lastLiveArrival > RATE_HOLD_MS) return 0;
    const floor = this.newestLiveTs - RATE_WINDOW_MS;
    let n = 0;
    for (const t of this.times) if (t > floor) n += 1;
    return Math.round((n * 1000) / RATE_WINDOW_MS);
  }

  clear(): void {
    this.pending = [];
    this.pendingBucket = null;
    this.times = [];
    this.newestLiveTs = -Infinity;
    this.lastLiveArrival = null;
  }
}
