// E24-S06 (#781) slice 1: the bars' read outside the pane. One read per key (symbol, interval, threshold), then one
// per bar close ("a static series per view; redraws only on new bars or a threshold change", the ticket): the raw
// served points are kept, and the zero / unknown mask is derived from #780's single coverage read (BQ-2), so a
// coverage that arrives after the bars, or changes, never costs a second metrics read. A refresh that fails keeps
// the bars it has and marks them stale; a first read that fails is `failed`.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LiqCoverage } from "../history";
import { fetchLiquidationBars, type BarsRead, type BarsRequest } from "./barsRead";
import { barWindow, buildBars, TIME_PARAMS, type BarWindow, type LiqBar } from "./model";

/** PROPOSED: a refresh lands this long after the bar closes, so the closed bar is final on the server. */
export const REFRESH_GRACE_MS = 2_000;
const MAX_TIMER_MS = 2 ** 31 - 1;

export interface LiqBarsFailure {
  readonly status: number | null;
  readonly code: string | null;
  readonly detail?: string | null;
}

export interface LiqBarsView {
  readonly phase: "loading" | "ready" | "failed";
  /** Masked by coverage; empty until coverage is known. */
  readonly bars: readonly LiqBar[];
  readonly window: BarWindow | null;
  readonly intervalMs: number | null;
  /** Served values that were not numbers (read as unknown). */
  readonly malformed: number;
  /** When the bars on screen landed, epoch ms (the read's end, not its start). */
  readonly loadedAtMs: number | null;
  /** A refresh failed: the bars are the last good read. */
  readonly stale: boolean;
  readonly error: LiqBarsFailure | null;
  readonly retry: () => void;
}

export interface LiqBarsOptions {
  readonly symbol: string;
  /** `22`'s `bar_type=time` `param`: the chart's interval. */
  readonly param: string;
  readonly coverage: LiqCoverage | null;
  readonly minNotionalUsd: string;
  readonly serverThreshold: boolean;
  /** Off while another mode is showing: nothing is read. */
  readonly enabled?: boolean;
  readonly read?: ((req: BarsRequest) => Promise<BarsRead>) | undefined;
  /** Wall-clock epoch ms. */
  readonly now?: (() => number) | undefined;
}

interface Raw {
  readonly key: string;
  readonly read: Extract<BarsRead, { kind: "ok" }>;
  readonly window: BarWindow;
  readonly loadedAtMs: number;
}

/** The delay to just after the next bar close. */
export function nextRefreshMs(nowMs: number, intervalMs: number): number {
  const close = (Math.floor(nowMs / intervalMs) + 1) * intervalMs;
  return Math.min(MAX_TIMER_MS, close - nowMs + REFRESH_GRACE_MS);
}

export function useLiquidationBars(o: LiqBarsOptions): LiqBarsView {
  const { symbol, param, coverage, minNotionalUsd, serverThreshold, enabled = true } = o;
  const readBars = o.read ?? fetchLiquidationBars;
  const now = o.now ?? Date.now;
  const intervalMs = TIME_PARAMS[param] ?? null;
  // the threshold is part of the read only when the server applies it (BQ-1): a commit never re-reads otherwise
  const threshold = serverThreshold ? minNotionalUsd : "";
  const key = `${symbol}|${param}|${threshold}`;
  const [raw, setRaw] = useState<Raw | null>(null);
  const [error, setError] = useState<{ key: string; failure: LiqBarsFailure } | null>(null);
  const [tick, setTick] = useState(0);
  const latest = useRef({ readBars, now });
  latest.current = { readBars, now };

  useEffect(() => {
    // a new run (another key, Retry, or back from another mode) starts clean: nothing of an earlier run shows as
    // fresh or as this key's error
    setError(null);
    if (!enabled || intervalMs === null) {
      setRaw(null);
      return undefined;
    }
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async (): Promise<void> => {
      const window = barWindow(latest.current.now(), intervalMs);
      let read: BarsRead;
      try {
        read = await latest.current.readBars({
          symbol,
          param,
          fromMs: window.fromMs,
          toMs: window.toMs,
          minNotionalUsd: threshold,
          serverThreshold,
          signal: ctl.signal,
        });
      } catch {
        // a read that throws is a failed read, and the next one is still scheduled
        read = { kind: "failed", status: null, code: null, detail: null };
      }
      if (ctl.signal.aborted) return;
      if (read.kind === "ok") {
        setRaw({ key, read, window, loadedAtMs: latest.current.now() });
        setError(null);
      } else {
        const { status, code, detail } = read;
        setError({ key, failure: { status, code, detail } });
      }
      timer = setTimeout(() => void run(), nextRefreshMs(latest.current.now(), intervalMs));
    };
    void run();
    return () => {
      ctl.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
    // `tick`: the Retry control re-runs the read
  }, [enabled, intervalMs, symbol, param, threshold, serverThreshold, key, tick]);

  const retry = useCallback(() => {
    setError(null);
    setTick((n) => n + 1);
  }, []);

  // a read of another key is never shown (a symbol or threshold change starts from loading)
  const mine = raw !== null && raw.key === key ? raw : null;
  const failure = error !== null && error.key === key ? error.failure : null;
  const bars = useMemo(
    () =>
      mine === null || coverage === null || intervalMs === null
        ? []
        : buildBars(mine.read.long, mine.read.short, coverage, intervalMs),
    [mine, coverage, intervalMs],
  );
  const unsupported: LiqBarsFailure | null =
    intervalMs === null ? { status: null, code: "unsupported_interval" } : null;
  const shownFailure = unsupported ?? failure;
  return {
    phase: shownFailure !== null && mine === null ? "failed" : mine === null ? "loading" : "ready",
    bars,
    window: mine?.window ?? null,
    intervalMs,
    malformed: mine?.read.malformed ?? 0,
    loadedAtMs: mine?.loadedAtMs ?? null,
    stale: shownFailure !== null && mine !== null,
    error: shownFailure,
    retry,
  };
}
