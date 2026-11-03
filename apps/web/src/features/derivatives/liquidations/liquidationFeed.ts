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
import { LiquidationCoalescer } from "./coalescer";
import type { LiqCoverage, LiqHistoryRequest, LiqHistoryResult } from "./history";
import { CLUSTER_WINDOW_MS, parseLiquidationFrames, type LiquidationPrint } from "./prints";
import { LiquidationRing, type HeldPrint } from "./ring";

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
  | { readonly phase: "ready"; readonly coverage: LiqCoverage; readonly truncated: boolean }
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
  /** Newest first, at most `VIEW_ROWS`. */
  readonly rows: readonly HeldPrint[];
  /** The newest held `seq` (-1 when none): the paused view counts `N new` from it. */
  readonly newestSeq: number;
  /** Prints per second over the last push window; a lower bound (`23` §14.9). */
  readonly ratePerSec: number;
  /** The active server-side filter, as sent (`min_notional_usd`); `null` for none. */
  readonly minNotionalUsd: string | null;
  /** The requested backfill window; `null` before a feed runs. */
  readonly window: LiqWindow | null;
  readonly history: LiqHistoryPhase;
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
}

export interface LiqFeedHandle {
  readonly symbol: string;
  readonly minNotionalUsd: string | null;
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

export function startLiquidationFeed(
  client: Pick<WsClient, "consume">,
  options: LiqFeedOptions,
): LiqFeedHandle {
  const { symbol, paneId, window } = options;
  const minNotionalUsd = options.minNotionalUsd ?? null;
  if (!LIQ_SYMBOL.test(symbol)) throw new RangeError("liquidation symbol must be a USDT perpetual");
  if (minNotionalUsd !== null && !DECIMAL.test(minNotionalUsd)) {
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
  /** The newest print taken in, held or pending: a snapshot's replay at or before it is dropped. */
  let newestTsMs: number | null = null;
  /** The last backfilled print: a live print at or before it is the same print, dropped. */
  let restFloorMs: number | null = null;
  let history: LiqHistoryPhase = { phase: "loading" };
  let lastSuccessAtMs: number | null = null;
  let pendingStructural = false;
  let abort: AbortController | null = null;
  let malformed = 0;
  let frame: number | undefined;
  let stopped = false;

  const build = (feed: LiqSnapshot["feed"], ratePerSec: number): LiqSnapshot => ({
    feed,
    rows: ring.newest(VIEW_ROWS),
    newestSeq: ring.nextSeq - 1,
    ratePerSec,
    minNotionalUsd,
    window,
    history,
  });
  let snapshot = build("idle", 0);

  const take = (prints: readonly LiquidationPrint[], nowMs: number, live: boolean): void => {
    coalescer.add(prints, nowMs, live);
    for (const p of prints) if (newestTsMs === null || p.tsMs > newestTsMs) newestTsMs = p.tsMs;
  };

  const after = (floor: number | null) => (p: LiquidationPrint) => floor === null || p.tsMs > floor;

  /** The recorded prints first, then the live ones newer than the last of them. */
  const merge = (recorded: readonly LiquidationPrint[]): void => {
    const last = recorded.at(-1);
    if (last === undefined) return;
    const live = ring.all().filter(after(last.tsMs));
    ring.clear();
    for (const p of recorded.slice(-ring.capacity)) ring.push(p);
    for (const p of live) ring.push(p);
    restFloorMs = last.tsMs;
    if (newestTsMs === null || last.tsMs > newestTsMs) newestTsMs = last.tsMs;
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
    void options.loadHistory(req).then((result) => {
      if (stopped || call.signal.aborted) return;
      if (result.kind === "ok") {
        lastSuccessAtMs = wallNow();
        merge(result.prints);
        history = { phase: "ready", coverage: result.coverage, truncated: result.truncated };
      } else {
        // TODO(slice 3, #780): the ticket's backfill error event rides with the analytics.
        history = { phase: "failed", status: result.status, lastSuccessAtMs };
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
      if (batch.kind === "snap") take(batch.prints.filter(after(newestTsMs)), now, false);
      else take(batch.prints, now, true);
    }
    const due = coalescer.drain(now);
    if (due !== null) for (const p of due.filter(after(restFloorMs))) ring.push(p);
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
  minNotionalUsd: null,
  window: null,
  history: { phase: "loading" },
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
