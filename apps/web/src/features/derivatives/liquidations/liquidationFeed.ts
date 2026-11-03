// E24-S05 (#780): one liquidation feed, outside React. One `liquidations.{symbol}` subscription through the
// existing `TopicHandle`, drained once per animation frame (never per message, rules/30), into the 250 ms
// coalescer and from it into the bounded ring; one backfill read of the window (slice 2) gives the recorded
// prints and the coverage. React reads a coarse snapshot through `useSyncExternalStore`, at most once per
// closed bucket or on a state change.
// Deviation (as E22-S01's tape and E24-S01's OI feed, C-69): `apps/web` carries no RxJS or Jotai, so the
// stream is the handle's rAF read and the atom an external store; the coalescing contract is the same.
import { useSyncExternalStore } from "react";
import type { WsClient } from "../../../lib/ws/api";
import type { TopicStatus } from "../../../lib/ws/state/types";
import { feedRows, type FeedRow } from "./buckets";
import { LiquidationCoalescer } from "./coalescer";
import type { LiqCoverage, LiqHistoryRequest, LiqHistoryResult, LiqTruncation } from "./history";
import { CLUSTER_WINDOW_MS, parseLiquidationFrames, type LiquidationPrint } from "./prints";
import { LiquidationRing } from "./ring";

/** `23` common `symbol`: a USDT linear perpetual (C-1.3). */
export const LIQ_SYMBOL = /^[A-Z0-9]{2,20}USDT$/;
/** D02 §6 / D03 S54-43: at most 40 rows in view. */
export const VIEW_ROWS = 40;

export interface LiqClock {
  readonly raf: (callback: (frameTimeMs: number) => void) => number;
  readonly caf: (handle: number) => void;
  /** Monotonic ms: the bucket clock. */
  readonly now: () => number;
  /** Wall-clock epoch ms: `last_success_at`. `Date.now` when absent. */
  readonly wallNow?: (() => number) | undefined;
}

export const browserLiqClock = (): LiqClock => ({
  raf: (callback) => requestAnimationFrame(callback),
  caf: (handle) => cancelAnimationFrame(handle),
  now: () => performance.now(),
  wallNow: () => Date.now(),
});

export type LiqHistoryPhase =
  | { readonly phase: "loading" }
  | {
      readonly phase: "ready";
      readonly coverage: LiqCoverage;
      readonly truncated: LiqTruncation | null;
    }
  | {
      readonly phase: "failed";
      readonly status: number | null;
      /** `last_success_at` (client view model, D02 §6): the last read that succeeded, or `null`. */
      readonly lastSuccessAtMs: number | null;
    };

export interface LiqWindow {
  readonly fromMs: number;
  readonly toMs: number;
}

export interface LiqSnapshot {
  readonly feed: "idle" | TopicStatus;
  /** Newest first, at most `VIEW_ROWS`: one per 250 ms bucket and side (D02 §6, BQ 5). */
  readonly rows: readonly FeedRow[];
  /** The newest held `seq` (-1 when none): the paused view counts `N new` from it. */
  readonly newestSeq: number;
  /** Prints per second over the last push window; a lower bound (`23` §14.9). */
  readonly ratePerSec: number;
  /** The long side's share of that window's served notional (AN-4), or `null`. */
  readonly longShare: number | null;
  /** The active server-side filter, as sent (`min_notional_usd`); `null` for none. */
  readonly minNotionalUsd: string | null;
  /** The requested backfill window; `null` before a feed runs. */
  readonly window: LiqWindow | null;
  readonly history: LiqHistoryPhase;
  /** The last read's coverage, kept while a retry runs or fails, so the chip never goes away; `null` before one. */
  readonly coverage: LiqCoverage | null;
  /** Prints held in the ring (the "newest 40 of N" disclosure). */
  readonly held: number;
  /** The newest `seq` right after the last backfill merge (-1 before one): a paused view counts from here. */
  readonly mergedSeq: number;
  /** Wall-clock epoch ms of the last data frame the topic delivered (the stale chip's "last"), or `null`. */
  readonly lastFrameAtMs: number | null;
}

export interface LiqFeedOptions {
  readonly symbol: string;
  readonly paneId: string;
  /** A decimal USD floor sent as the subscription option; filtering is the server's. */
  readonly minNotionalUsd?: string | null | undefined;
  readonly window: LiqWindow;
  readonly loadHistory: (req: LiqHistoryRequest) => Promise<LiqHistoryResult>;
  readonly clock?: LiqClock | undefined;
  readonly capacity?: number | undefined;
  /** The ticket's error event when the read fails. */
  readonly onBackfillFailed?: ((status: number | null, code: string | null) => void) | undefined;
}

export interface LiqFeedHandle {
  readonly symbol: string;
  /** The filter as sent (`feedFilter`): a hook compares it to never show another filter's feed. */
  readonly minNotionalUsd: string | null;
  /** The read's window: a hook compares it to never show another window's feed. */
  readonly window: LiqWindow;
  getSnapshot(): LiqSnapshot;
  subscribe(listener: () => void): () => void;
  /** The retry band's action: reads the window again; live keeps streaming meanwhile. */
  retry(): void;
  /** Buckets flushed and prints held: the ticket's client metrics, in memory only. */
  metrics(): { readonly buckets: number; readonly held: number; readonly malformed: number };
  /** Releases the subscription, aborts the read and stops the loop. Idempotent. */
  stop(): void;
}

const DECIMAL = /^\d{1,30}(\.\d{1,18})?$/;
/** The server's bound on `min_notional_usd` (`23` registry): longer values are `invalid_options`. */
export const MIN_NOTIONAL_MAX_CHARS = 32;

/**
 * `min_notional_usd` as the feed sends it: a zero floor (the ruled `deriv.liq.min_notional_usd` default "0") is no
 * filter, so it is neither sent nor stated as "at least 0 USDT" (#5763 (a); as #5767's `feedMinNotional`).
 */
export const feedFilter = (value: string | null | undefined): string | null =>
  value === null || value === undefined || /^0+(?:\.0+)?$/.test(value) ? null : value;

const keyOf = (p: LiquidationPrint): string =>
  `${String(p.tsMs)}|${p.side}|${p.price}|${p.size}|${String(p.clusterSize)}`;

/**
 * The prints at one boundary millisecond, as a multiset. A print before the boundary is old; one at it is old
 * only while it matches a held print (side, price, size and cluster too), each held print matching at most
 * one print of a batch; one after it is new. Two distinct prints in one millisecond both survive.
 */
class Boundary {
  ms: number | null = null;
  private readonly keys = new Map<string, number>();

  note(prints: readonly LiquidationPrint[]): void {
    for (const p of prints) {
      if (this.ms === null || p.tsMs > this.ms) {
        this.ms = p.tsMs;
        this.keys.clear();
      }
      if (p.tsMs === this.ms) this.keys.set(keyOf(p), (this.keys.get(keyOf(p)) ?? 0) + 1);
    }
  }

  newOnly(prints: readonly LiquidationPrint[]): LiquidationPrint[] {
    const ms = this.ms;
    if (ms === null) return [...prints];
    const left = new Map(this.keys);
    return prints.filter((p) => {
      if (p.tsMs !== ms) return p.tsMs > ms;
      const n = left.get(keyOf(p)) ?? 0;
      if (n > 0) left.set(keyOf(p), n - 1);
      return n === 0;
    });
  }
}

export function startLiquidationFeed(
  client: Pick<WsClient, "consume">,
  options: LiqFeedOptions,
): LiqFeedHandle {
  const { symbol, paneId, window } = options;
  const minNotionalUsd = feedFilter(options.minNotionalUsd);
  if (!LIQ_SYMBOL.test(symbol)) throw new RangeError("liquidation symbol must be a USDT perpetual");
  const tooLong = minNotionalUsd !== null && minNotionalUsd.length > MIN_NOTIONAL_MAX_CHARS;
  if (minNotionalUsd !== null && (tooLong || !DECIMAL.test(minNotionalUsd))) {
    throw new RangeError("min_notional_usd must be a non-negative decimal");
  }
  if (!(window.fromMs < window.toMs)) throw new RangeError("the window must start before it ends");
  const clock = options.clock ?? browserLiqClock();
  const wallNow = clock.wallNow ?? Date.now;
  const ring = new LiquidationRing(options.capacity);
  const coalescer = new LiquidationCoalescer();
  const listeners = new Set<() => void>();
  const handle = client.consume({
    ch: `liquidations.${symbol}`,
    opts: {
      cluster_window_ms: CLUSTER_WINDOW_MS,
      ...(minNotionalUsd === null ? {} : { min_notional_usd: minNotionalUsd }),
    },
    paneId,
    priority: "other",
  });
  /** The newest prints taken in, held or pending: a snapshot's replay of them is dropped. */
  const taken = new Boundary();
  /** The last backfilled prints: a live print that is one of them is dropped. */
  let recordedEnd = new Boundary();
  let history: LiqHistoryPhase = { phase: "loading" };
  let coverage: LiqCoverage | null = null;
  let mergedSeq = -1;
  let lastFrameAtMs: number | null = null;
  let lastSuccessAtMs: number | null = null;
  let pendingStructural = false;
  let abort: AbortController | null = null;
  let malformed = 0;
  let frame: number | undefined;
  let stopped = false;

  const build = (feed: LiqSnapshot["feed"], ratePerSec: number): LiqSnapshot => ({
    feed,
    rows: feedRows(ring.newest(ring.capacity), VIEW_ROWS),
    newestSeq: ring.nextSeq - 1,
    ratePerSec,
    longShare: ratePerSec > 0 ? coalescer.longShare() : null,
    minNotionalUsd,
    window,
    history,
    coverage,
    held: ring.length,
    mergedSeq,
    lastFrameAtMs,
  });
  let snapshot = build("idle", 0);

  const take = (prints: readonly LiquidationPrint[], nowMs: number, live: boolean): void => {
    coalescer.add(prints, nowMs, live);
    taken.note(prints);
  };

  /** The recorded prints first, then the live ones newer than the last of them. */
  const merge = (recorded: readonly LiquidationPrint[]): void => {
    if (recorded.length === 0) return;
    recordedEnd = new Boundary();
    recordedEnd.note(recorded);
    const live = recordedEnd.newOnly(ring.all());
    ring.clear();
    for (const p of recorded.slice(-ring.capacity)) ring.push(p);
    for (const p of live) ring.push(p);
    taken.note(recorded);
    mergedSeq = ring.nextSeq - 1;
  };

  const load = (): void => {
    abort?.abort();
    const call = new AbortController();
    abort = call;
    history = { phase: "loading" };
    pendingStructural = true;
    const req: LiqHistoryRequest = {
      symbol,
      fromMs: window.fromMs,
      toMs: window.toMs,
      minNotionalUsd,
      signal: call.signal,
      keep: ring.capacity,
    };
    // a rejected read is a failed one (#5763 (e)): never an unhandled rejection, never a stuck "loading"
    const read = options
      .loadHistory(req)
      .catch((): LiqHistoryResult => ({ kind: "failed", status: null, code: null }));
    void read.then((result) => {
      if (stopped || call.signal.aborted) return;
      if (result.kind === "ok") {
        lastSuccessAtMs = wallNow();
        merge(result.prints);
        coverage = result.coverage;
        history = { phase: "ready", coverage: result.coverage, truncated: result.truncated };
      } else {
        history = { phase: "failed", status: result.status, lastSuccessAtMs };
        options.onBackfillFailed?.(result.status, result.code);
      }
      pendingStructural = true;
    });
  };

  const onFrame = (): void => {
    frame = undefined;
    if (stopped) return;
    const now = clock.now();
    for (const batch of parseLiquidationFrames(handle.read(), symbol)) {
      if (batch === "reset") continue; // last-good rows stay; the snapshot after it is deduplicated
      malformed += batch.malformed;
      lastFrameAtMs = wallNow();
      if (batch.kind === "snap") take(taken.newOnly(batch.prints), now, false);
      else take(batch.prints, now, true);
    }
    const due = coalescer.drain(now);
    if (due !== null) for (const p of recordedEnd.newOnly(due)) ring.push(p);
    const rate = coalescer.rateLowerBound(now);
    const feed = handle.status;
    const changed = due !== null || rate !== snapshot.ratePerSec || feed !== snapshot.feed;
    if (changed || pendingStructural) {
      pendingStructural = false;
      snapshot = build(feed, rate);
      for (const listener of [...listeners]) listener();
    }
    frame = clock.raf(onFrame);
  };

  load();
  frame = clock.raf(onFrame);

  return {
    symbol,
    minNotionalUsd,
    window,
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    retry: () => {
      if (!stopped) load();
    },
    metrics: () => ({ buckets: coalescer.flushed, held: ring.length, malformed }),
    stop: () => {
      if (stopped) return;
      stopped = true;
      if (frame !== undefined) clock.caf(frame);
      frame = undefined;
      abort?.abort();
      listeners.clear();
      coalescer.clear();
      handle.release();
    },
  };
}

export const INITIAL_LIQ_SNAPSHOT: LiqSnapshot = {
  feed: "idle",
  rows: [],
  newestSeq: -1,
  ratePerSec: 0,
  longShare: null,
  minNotionalUsd: null,
  window: null,
  history: { phase: "loading" },
  coverage: null,
  held: 0,
  mergedSeq: -1,
  lastFrameAtMs: null,
};

const noopSubscribe = (): (() => void) => () => undefined;
const initial = (): LiqSnapshot => INITIAL_LIQ_SNAPSHOT;

/** The coarse feed state; re-renders at most once per closed 250 ms bucket or on a state change. */
export function useLiqSnapshot(feed: LiqFeedHandle | null): LiqSnapshot {
  return useSyncExternalStore(
    feed?.subscribe ?? noopSubscribe,
    feed?.getSnapshot ?? initial,
    feed?.getSnapshot ?? initial,
  );
}
