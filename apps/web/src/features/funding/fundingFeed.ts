// E24-S03 (#778) slice 1: one funding pane's history state, outside React, read through
// `useSyncExternalStore` (as E24-S01: `apps/web` carries no RxJS or Jotai). A failed read keeps the last good
// series and `last_success_at` (D02 §4), so the pane shows a retry band, never a blank chart.
import { useSyncExternalStore } from "react";
import type { FundingHistoryRequest, FundingHistoryResult } from "./history";
import { buildFundingSeries, EMPTY_SERIES, type FundingSeriesModel } from "./series";

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
}

export interface FundingFeedHandle {
  readonly symbol: string;
  getSnapshot(): FundingSnapshot;
  subscribe(listener: () => void): () => void;
  /** The retry band's action. */
  retry(): void;
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
    stop: () => {
      if (stopped) return;
      stopped = true;
      abort?.abort();
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
