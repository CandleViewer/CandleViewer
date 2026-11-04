// E24-S01 (#776) slice 1: one OI pane's feed, outside React. One `ticker.{symbol}` subscription through
// the existing `TopicHandle`, drained once per animation frame (never per message, rules/30), and one
// history read; both land in `OiSeries`. React reads a coarse snapshot through `useSyncExternalStore`.
// Deviation (as E22-S01's tape, C-69): `apps/web` carries no RxJS or Jotai, so the stream is the
// handle's rAF read and the atom an external store; the coalescing contract is the same.
import { useSyncExternalStore } from "react";
import type { WsClient } from "../../../lib/ws/api";
import type { TopicStatus } from "../../../lib/ws/state/types";
import type { OiAnalytics } from "./analytics";
import { ageSeconds, staleTier, type StaleTier } from "./freshness";
import type { HistoryRequest, HistoryResult } from "./history";
import { granularityNote, OI_INTERVAL_MS, requestInterval } from "./intervals";
import { OiSeries, type OiGap, type OiRow } from "./series";
import { parseTickerFrames } from "./ticker";

/** `23` §14.2 / common `symbol`: a USDT linear perpetual (C-1.3). */
export const OI_SYMBOL = /^[A-Z0-9]{2,20}USDT$/;
/** OI renders on change at ≤ 1 Hz (the ticket's Performance notes; D02 §14). */
export const PUBLISH_INTERVAL_MS = 1_000;

export interface OiClock {
  readonly raf: (callback: (frameTimeMs: number) => void) => number;
  readonly caf: (handle: number) => void;
  /** Monotonic ms: the age of the last update. */
  readonly now: () => number;
  /** Wall-clock epoch ms: `last_success_at`. */
  readonly wallNow: () => number;
}

export const browserOiClock = (): OiClock => ({
  raf: (callback) => requestAnimationFrame(callback),
  caf: (handle) => cancelAnimationFrame(handle),
  now: () => performance.now(),
  wallNow: () => Date.now(),
});

export type HistoryPhase =
  | { readonly phase: "loading" }
  | {
      readonly phase: "ready";
      readonly empty: boolean;
      readonly truncated: "older" | "newer" | null;
    }
  | {
      readonly phase: "failed";
      readonly status: number | null;
      /** `last_success_at` (client view model, D02 §4): the last load that succeeded, or `null`. */
      readonly lastSuccessAtMs: number | null;
    };

export interface OiSnapshot {
  readonly feed: "idle" | TopicStatus;
  readonly history: HistoryPhase;
  readonly latest: OiRow | null;
  readonly stale: {
    readonly tier: StaleTier;
    readonly ageMs: number;
    readonly lastTsMs: number | null;
  };
  readonly note: string | null;
  readonly coverageFromMs: number | null;
  readonly rows: readonly OiRow[];
  readonly gaps: readonly OiGap[];
}

export interface OiFeedOptions {
  readonly symbol: string;
  readonly paneId: string;
  readonly barMs: number;
  readonly window: { readonly fromMs: number; readonly toMs: number };
  readonly loadHistory: (req: HistoryRequest) => Promise<HistoryResult>;
  readonly clock?: OiClock | undefined;
  readonly analytics?: OiAnalytics | undefined;
}

export interface OiFeedHandle {
  readonly symbol: string;
  readonly barMs: number;
  getSnapshot(): OiSnapshot;
  subscribe(listener: () => void): () => void;
  /** The retry band's action: reads the history again; live keeps streaming meanwhile. */
  retry(): void;
  /** Releases the subscription, aborts the read and stops the loop. Idempotent. */
  stop(): void;
}

export function startOiFeed(
  client: Pick<WsClient, "consume">,
  options: OiFeedOptions,
): OiFeedHandle {
  const { symbol, paneId, barMs, window } = options;
  if (!OI_SYMBOL.test(symbol)) throw new RangeError("OI symbol must be a USDT perpetual");
  if (!(barMs > 0)) throw new RangeError("barMs must be positive");
  const clock = options.clock ?? browserOiClock();
  const series = new OiSeries(barMs, window);
  const listeners = new Set<() => void>();
  const handle = client.consume({ ch: `ticker.${symbol}`, paneId, priority: "other" });
  const interval = requestInterval(barMs);
  let history: HistoryPhase = { phase: "loading" };
  let lastSuccessAtMs: number | null = null;
  let lastArrival: number | null = null;
  // a stream that never delivers goes stale too: until the first tick, age counts from the start
  const startedAt = clock.now();
  let serverStale = false;
  let lastTsMs: number | null = null;
  let published = -Infinity;
  let shownVersion = -1;
  let shownAge = -1;
  let shownTier: StaleTier = "fresh";
  let shownFeed: OiSnapshot["feed"] = "idle";
  let pendingStructural = true;
  let abort: AbortController | null = null;
  let frame: number | undefined;
  let stopped = false;

  const build = (feed: OiSnapshot["feed"], tier: StaleTier, ageMs: number): OiSnapshot => ({
    feed,
    history,
    latest: series.latest(),
    stale: { tier, ageMs, lastTsMs },
    note: granularityNote(barMs, series.nativeInterval()),
    coverageFromMs: series.coverageFromMs(),
    rows: series.rows(),
    gaps: series.gaps(),
  });
  let snapshot = build("idle", "fresh", 0);

  const publish = (next: OiSnapshot): void => {
    snapshot = next;
    for (const listener of [...listeners]) listener();
  };

  const load = (): void => {
    abort?.abort();
    const call = new AbortController();
    abort = call;
    history = { phase: "loading" };
    pendingStructural = true;
    const req: HistoryRequest = {
      symbol,
      interval,
      fromMs: window.fromMs,
      toMs: window.toMs,
      signal: call.signal,
      onAnomaly: (anomaly) => {
        if (!stopped && !call.signal.aborted) options.analytics?.backfillAnomaly(symbol, anomaly);
      },
    };
    // a rejected or throwing read is a failed read, never a pane stuck in loading
    const threw: HistoryResult = { kind: "failed", status: null, code: "exception" };
    let pending: Promise<HistoryResult>;
    try {
      pending = options.loadHistory(req);
    } catch {
      pending = Promise.resolve(threw);
    }
    void pending
      .catch((): HistoryResult => threw)
      .then((result) => {
        if (stopped || call.signal.aborted) return;
        if (result.kind === "ok") {
          lastSuccessAtMs = clock.wallNow();
          series.setHistory(result.points, result.coverage, OI_INTERVAL_MS[interval]);
          history = {
            phase: "ready",
            empty: result.points.length === 0,
            truncated: result.truncated,
          };
        } else {
          series.setHistoryFailed();
          history = { phase: "failed", status: result.status, lastSuccessAtMs };
        }
        pendingStructural = true;
        if (result.kind !== "ok") {
          try {
            options.analytics?.backfillFailed(symbol, result.status, result.code);
          } catch {
            // analytics is best-effort: a throwing sink never rejects the read
          }
        }
      });
  };

  const onFrame = (): void => {
    frame = undefined;
    if (stopped) return;
    const now = clock.now();
    for (const tick of parseTickerFrames(handle.read(), symbol)) {
      if (tick === "reset") {
        series.seam();
        continue;
      }
      lastArrival = now;
      serverStale = tick.stale;
      lastTsMs = tick.tsMs;
      series.addLive(tick);
    }
    const ageMs = now - (lastArrival ?? startedAt);
    const tier = staleTier(ageMs, serverStale);
    const feed = handle.status;
    // a state change publishes at once; a value change at most once a second; the chip's age per second
    const structural = pendingStructural || tier !== shownTier || feed !== shownFeed;
    const valueDue = series.version !== shownVersion && now - published >= PUBLISH_INTERVAL_MS;
    const ageDue = tier !== "fresh" && ageSeconds(ageMs) !== shownAge;
    if (structural || valueDue || ageDue) {
      pendingStructural = false;
      published = now;
      shownVersion = series.version;
      shownAge = ageSeconds(ageMs);
      shownTier = tier;
      shownFeed = feed;
      publish(build(feed, tier, ageMs));
    }
    frame = clock.raf(onFrame);
  };

  load();
  frame = clock.raf(onFrame);

  return {
    symbol,
    barMs,
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    retry: () => {
      if (!stopped) load();
    },
    stop: () => {
      if (stopped) return;
      stopped = true;
      if (frame !== undefined) clock.caf(frame);
      frame = undefined;
      abort?.abort();
      listeners.clear();
      handle.release();
    },
  };
}

export const INITIAL_OI_SNAPSHOT: OiSnapshot = {
  feed: "idle",
  history: { phase: "loading" },
  latest: null,
  stale: { tier: "fresh", ageMs: 0, lastTsMs: null },
  note: null,
  coverageFromMs: null,
  rows: [],
  gaps: [],
};

const noopSubscribe = (): (() => void) => () => undefined;
const initial = (): OiSnapshot => INITIAL_OI_SNAPSHOT;

/** The coarse OI state; re-renders on a state change, at most once a second for values. */
export function useOiSnapshot(feed: OiFeedHandle | null): OiSnapshot {
  return useSyncExternalStore(
    feed?.subscribe ?? noopSubscribe,
    feed?.getSnapshot ?? initial,
    feed?.getSnapshot ?? initial,
  );
}
