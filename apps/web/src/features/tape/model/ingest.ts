// E22-S01 (#714) PR-A: applies the `trades.{symbol}` frames a `TopicHandle.read()` hands over, in
// the panel's rAF read, straight into the ring (BQ-208: `lib/ws` stays untouched; C-66). The
// subscription is structured (`e: "j"`, BQ-207): kind 3 has no `id` to dedupe by and no count.
//
// C-78, a departure from the `ResetFrame` note in `lib/ws/api.ts` ("the consumer clears its
// state"): the tape keeps its last-good rows as display-only history and puts a seam above the
// first print that follows the reset; the `snap` that reseeds it is deduped by `id` against them
// (C-68, AC4), so a reconnect never duplicates a row. Only the ingest cursor is reset.
import type { generated } from "@candleviewer/protocol";
import type { ResetReason, TopicFrame } from "../../../lib/ws/api";
import type { DataBody } from "../../../lib/ws/protocol/codec";
import { FLAG_BIG, FLAG_BLOCK, FLAG_LIQUIDATION, SIDE_BUY, SIDE_SELL, type TapeRing } from "./ring";

/** Every print the feed sent is accounted for, never silently lost (BQ-209, `23` §6.1). */
export interface IngestCounters {
  /** Frames applied (`snap` and `d`). */
  frames: number;
  /** Items received in those frames. */
  received: number;
  appended: number;
  /** Items whose `id` the ring already held (a reseeding `snap`, C-68). */
  duplicates: number;
  /** Items the full ring refused because its oldest row was pinned (S22). */
  notKept: number;
  /** Items that failed the §14.2 shape check. */
  malformed: number;
  /** Bodies that were not a `trades` batch for this symbol, or arrived binary (BQ-207). */
  rejectedBodies: number;
  /** The server's `dropped`: prints `min_size` filtered or overflow shed (`23` §6.1). */
  serverDropped: number;
  /** Frames the server marked `coalesced`, and the sum of their `coalesced_count` (`23` §8.6). */
  coalescedFrames: number;
  coalescedCount: number;
  resets: number;
}

const emptyCounters = (): IngestCounters => ({
  frames: 0,
  received: 0,
  appended: 0,
  duplicates: 0,
  notKept: 0,
  malformed: 0,
  rejectedBodies: 0,
  serverDropped: 0,
  coalescedFrames: 0,
  coalescedCount: 0,
  resets: 0,
});

type TradesBatch = generated.ws.TradesSymbol;
/** A payload before its check: every `23` §14.2 field is present or not, of no known type. */
type Unchecked<T> = { readonly [K in keyof T]?: unknown };

const isObject = <T>(v: unknown): v is Unchecked<T> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const isCount = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0;

const isDecimal = (v: unknown): v is string =>
  typeof v === "string" && v.length > 0 && v.length <= 40 && Number.isFinite(Number(v));

export class TapeIngest {
  readonly counters: IngestCounters = emptyCounters();
  /** The engine's current threshold, from the latest batch (`23` §14.2); never compared here. */
  threshold: string | undefined;
  lastReset: ResetReason | undefined;
  /** Seams placed (C-78). */
  seams = 0;
  /** `ts_ms` of the newest print appended. */
  lastPrintTsMs: number | undefined;
  private seamPending = false;

  constructor(
    private readonly ring: TapeRing,
    private readonly symbol: string,
  ) {}

  /** Applies the frames in order and returns how many prints were appended. */
  apply(frames: readonly TopicFrame[]): number {
    let appended = 0;
    for (const frame of frames) {
      if (frame.kind === "reset") {
        this.counters.resets += 1;
        this.lastReset = frame.reason;
        if (this.ring.length > 0) this.seamPending = true;
        continue;
      }
      this.counters.frames += 1;
      if (frame.kind === "snap") {
        for (const body of frame.bodies) appended += this.applyBody(body);
      } else {
        appended += this.applyBody(frame.body);
      }
    }
    return appended;
  }

  private applyBody(body: DataBody): number {
    const p = body.e === "j" ? body.p : undefined;
    if (!isObject<TradesBatch>(p) || p.symbol !== this.symbol || !Array.isArray(p.trades)) {
      this.counters.rejectedBodies += 1;
      return 0;
    }
    if (isDecimal(p.big_trade_threshold)) this.threshold = p.big_trade_threshold;
    if (isCount(p.dropped)) this.counters.serverDropped += p.dropped;
    if (p.coalesced === true) {
      this.counters.coalescedFrames += 1;
      this.counters.coalescedCount += isCount(p.coalesced_count) ? p.coalesced_count : 0;
    }
    let appended = 0;
    // Items arrive oldest first (`23` §6.1: a merged window appends, never merges).
    for (const item of p.trades as readonly unknown[]) {
      this.counters.received += 1;
      if (this.applyItem(item)) appended += 1;
    }
    return appended;
  }

  private applyItem(item: unknown): boolean {
    if (
      !isObject<TradesBatch["trades"][number]>(item) ||
      typeof item.ts_ms !== "number" ||
      !Number.isFinite(item.ts_ms) ||
      !isDecimal(item.price) ||
      !isDecimal(item.size) ||
      (item.side !== "buy" && item.side !== "sell") ||
      (item.id !== undefined && (typeof item.id !== "string" || item.id.length === 0))
    ) {
      this.counters.malformed += 1;
      return false;
    }
    // `id` is optional in `23` §14.2 `TradesBatch`: a print without one cannot be deduped, so a
    // reseeding `snap` that repeats id-less prints would duplicate them. Known limit; the server
    // sends an `id` on every structured print (BQ-207), so it is documented, not rejected.
    const id = item.id as string | undefined;
    if (id !== undefined && this.ring.hasId(id)) {
      this.counters.duplicates += 1;
      return false;
    }
    const flags =
      (item.is_block_trade === true ? FLAG_BLOCK : 0) |
      (item.is_liquidation === true ? FLAG_LIQUIDATION : 0) |
      (item.is_big_trade === true ? FLAG_BIG : 0);
    const seq = this.ring.push({
      id,
      tsMs: item.ts_ms,
      price: item.price,
      size: item.size,
      // the aggressor side straight from the feed, never inferred (AC1)
      side: item.side === "buy" ? SIDE_BUY : SIDE_SELL,
      flags,
      clusterSize: isCount(item.cluster_size) ? item.cluster_size : 1,
    });
    if (seq === null) {
      this.counters.notKept += 1;
      return false;
    }
    if (this.seamPending) {
      this.ring.markSeam(seq);
      this.seams += 1;
      this.seamPending = false;
    }
    this.counters.appended += 1;
    this.lastPrintTsMs = item.ts_ms;
    return true;
  }
}
