// E24-S03 (#778) slice 1: one funding pane's history state, outside React, read through
// `useSyncExternalStore` (as E24-S01: `apps/web` carries no RxJS or Jotai). A failed read keeps the last good
// series and `last_success_at` (D02 §4), so the pane shows a retry band, never a blank chart.
import { useSyncExternalStore } from "react";
import type {
  FundingClock,
  FundingHistoryOk,
  FundingHistoryRequest,
  FundingHistoryResult,
} from "./history";
import { samePredicted } from "./predicted";
import { buildFundingSeries, EMPTY_SERIES, mergeSettled, type FundingSeriesModel } from "./series";

/** BQ 6: what an empty window means, from `meta.coverage`; `unknown` while it is not served. */
export type CoverageWord = "covered" | "not-recorded" | "unknown";

export type FundingHistoryPhase =
  | { readonly phase: "loading" }
  | {
      readonly phase: "ready";
      readonly empty: boolean;
      readonly coverage: CoverageWord;
      readonly truncated: boolean;
    }
  | { readonly phase: "unavailable" }
  | { readonly phase: "failed"; readonly status: number | null };

export interface FundingSnapshot {
  readonly history: FundingHistoryPhase;
  readonly series: FundingSeriesModel;
  readonly lastSuccessAtMs: number | null;
}

export interface FundingFeedOptions {
  readonly symbol: string;
  readonly window: { readonly fromMs: number; readonly toMs: number };
  readonly loadHistory: (req: FundingHistoryRequest) => Promise<FundingHistoryResult>;
  /** Wall-clock epoch ms for `last_success_at`. */
  readonly wallNow?: (() => number) | undefined;
  readonly onFailed?: ((status: number | null, code: string | null) => void) | undefined;
  /** Slice 2: the exchange-synced clock for the settlement poll's `to` (default `Date.now`). */
  readonly now?: (() => number) | undefined;
  readonly timers?: FundingClock | undefined;
}

/** BQ 5 ruling (6610230823): one poll at the settlement, then 1 / 2 / 4 / 8 s, at most five attempts. */
export const SETTLE_BACKOFF_MS: readonly number[] = [1_000, 2_000, 4_000, 8_000];

export interface FundingFeedHandle {
  readonly symbol: string;
  getSnapshot(): FundingSnapshot;
  subscribe(listener: () => void): () => void;
  /** The retry band's action. */
  retry(): void;
  /**
   * The countdown reached `deadlineMs` (BQ 5): read `to = now` until the settlement it names is stored, and
   * append it; a newer call replaces a running one.
   */
  settle(deadlineMs: number): void;
  /** Aborts the read and drops the listeners. Idempotent. */
  stop(): void;
}

/** `22` `Symbol`: a USDT linear perpetual (C-1.2 item 3). */
export const FUNDING_SYMBOL = /^[A-Z0-9]{2,20}USDT$/;

export const INITIAL_FUNDING_SNAPSHOT: FundingSnapshot = {
  history: { phase: "loading" },
  series: EMPTY_SERIES,
  lastSuccessAtMs: null,
};

const coverageWord = (r: Extract<FundingHistoryResult, { kind: "ok" }>): CoverageWord =>
  r.coverage === null ? "unknown" : r.coverage.noCoverage ? "not-recorded" : "covered";

export function startFundingFeed(options: FundingFeedOptions): FundingFeedHandle {
  const { symbol, window } = options;
  if (!FUNDING_SYMBOL.test(symbol)) throw new RangeError("funding symbol must be a USDT perpetual");
  const wallNow = options.wallNow ?? Date.now;
  const listeners = new Set<() => void>();
  let snapshot = INITIAL_FUNDING_SNAPSHOT;
  let abort: AbortController | null = null;
  let stopped = false;
  let cancelPoll = (): void => undefined;
  const now = options.now ?? Date.now;
  const timers: FundingClock = options.timers ?? {
    setTimeout: (run, ms) => setTimeout(run, ms),
    // `id` is what this clock's `setTimeout` returned; the cast only restores that type.
    clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
  };

  const publish = (next: FundingSnapshot): void => {
    snapshot = next;
    for (const listener of [...listeners]) listener();
  };

  const apply = (result: FundingHistoryResult): void => {
    if (result.kind === "ok") {
      const empty = result.settled.length === 0;
      const { truncated } = result;
      publish({
        history: { phase: "ready", empty, coverage: coverageWord(result), truncated },
        series: buildFundingSeries(result),
        lastSuccessAtMs: wallNow(),
      });
      return;
    }
    if (result.kind === "unavailable") {
      publish({ ...snapshot, history: { phase: "unavailable" }, series: EMPTY_SERIES });
      return;
    }
    options.onFailed?.(result.status, result.code);
    // the last good series and `last_success_at` stay (D02 §4)
    publish({ ...snapshot, history: { phase: "failed", status: result.status } });
  };

  const load = (): void => {
    abort?.abort();
    const call = new AbortController();
    abort = call;
    publish({ ...snapshot, history: { phase: "loading" } });
    const threw: FundingHistoryResult = { kind: "failed", status: null, code: "exception" };
    let pending: Promise<FundingHistoryResult>;
    try {
      pending = options.loadHistory({ symbol, ...window, signal: call.signal });
    } catch {
      pending = Promise.resolve(threw);
    }
    void pending
      .catch((): FundingHistoryResult => threw)
      .then((result) => {
        if (!stopped && !call.signal.aborted) apply(result);
      });
  };

  /** Appends a newer read's settlements; `true` once the one at `deadlineMs` is stored. */
  const append = (r: FundingHistoryOk, deadlineMs: number): boolean => {
    const { points, added } = mergeSettled(snapshot.series.settled, r.settled);
    // BQ-4: every ok read refreshes the accruing rate, even one that settles nothing new, so a rate that
    // is no longer published goes to n/a instead of being carried over
    if (added || !samePredicted(snapshot.series.predicted, r.predicted)) {
      const was = snapshot.history;
      const minutes =
        snapshot.series.intervalMs === null ? null : snapshot.series.intervalMs / 60_000;
      const series = buildFundingSeries({
        settled: points,
        intervalMinutes: r.intervalMinutes ?? minutes,
        coverage: null,
        predicted: r.predicted, // a fresh read's: the old accruing rate is never carried over (BQ-4)
      });
      publish({
        // a failed or unavailable window keeps its band: the poll is not the full read the retry makes
        history:
          was.phase === "ready" || was.phase === "loading"
            ? {
                phase: "ready",
                empty: false,
                coverage: was.phase === "ready" ? was.coverage : "unknown",
                truncated: was.phase === "ready" && was.truncated,
              }
            : was,
        // the gaps stay the full read's: a short `to = now` read reports none of the window's
        series: { ...series, gaps: snapshot.series.gaps },
        lastSuccessAtMs: wallNow(),
      });
    }
    return points.some((p) => p.tMs >= deadlineMs);
  };

  const settle = (deadlineMs: number): void => {
    cancelPoll();
    const call = new AbortController();
    const fromMs = snapshot.series.settled.at(-1)?.tMs ?? window.fromMs;
    let attempt = 0;
    let timer: unknown;
    const run = (): void => {
      attempt += 1;
      const req = { symbol, fromMs, toMs: now() + 1, signal: call.signal };
      void Promise.resolve()
        .then(() => options.loadHistory(req))
        .catch((): FundingHistoryResult => ({ kind: "failed", status: null, code: "exception" }))
        .then((r) => {
          if (stopped || call.signal.aborted) return;
          if (r.kind === "ok" && append(r, deadlineMs)) return;
          const wait = SETTLE_BACKOFF_MS[attempt - 1];
          if (wait !== undefined) timer = timers.setTimeout(run, wait);
        });
    };
    cancelPoll = () => {
      call.abort();
      if (timer !== undefined) timers.clearTimeout(timer);
    };
    run();
  };

  load();

  return {
    symbol,
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    retry: () => {
      if (!stopped) load();
    },
    settle: (deadlineMs) => {
      if (!stopped) settle(deadlineMs);
    },
    stop: () => {
      if (stopped) return;
      stopped = true;
      abort?.abort();
      cancelPoll();
      listeners.clear();
    },
  };
}

const noopSubscribe = (): (() => void) => () => undefined;
const initial = (): FundingSnapshot => INITIAL_FUNDING_SNAPSHOT;

export function useFundingSnapshot(feed: FundingFeedHandle | null): FundingSnapshot {
  return useSyncExternalStore(
    feed?.subscribe ?? noopSubscribe,
    feed?.getSnapshot ?? initial,
    feed?.getSnapshot ?? initial,
  );
}
