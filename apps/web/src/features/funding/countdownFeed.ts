// E24-S03 (#778) slice 2: the countdown's one store entry per symbol, shared by the header and the sub-pane: the
// ticker's rate and `next_funding_time_ms` (BQ 1) drained per animation frame, the server's charge lines at the
// 5 and 1 min marks (BQ 4) and the settlement signal (BQ 5). An external store, as E24-S01 (no RxJS / Jotai).
import { useEffect, useState, useSyncExternalStore } from "react";
import type { FundingCharge, SecondTick } from "@candleviewer/ui";
import type { WsClient } from "../../lib/ws/api";
import { getActiveClient, subscribeActiveClient } from "../../lib/ws/client/activeClient";
import type { TopicStatus } from "../../lib/ws/state/types";
import { FUNDING_SYMBOL } from "./fundingFeed";
import { parseFundingFrames } from "./ticker";

/** D02 DV-1 / D03 §10.2 (as E24-S01's OI readout): stale from 5 s without an update, escalated from 15 s. */
export const STALE_T1_MS = 5_000;
export const STALE_T2_MS = 15_000;
/** D02 §13 / D04 LR-1, LR-2: the marks; the charge lines are re-read at each (§19.110 Q3). */
export const CHARGE_MARKS_MS: readonly number[] = [300_000, 60_000];

export type StaleTier = "fresh" | "t1" | "t2";

export interface CountdownSnapshot {
  readonly feed: "idle" | TopicStatus;
  readonly rate: string | null;
  readonly nextFundingTimeMs: number | null;
  readonly stale: {
    readonly tier: StaleTier;
    readonly ageS: number;
    readonly lastTsMs: number | null;
  };
  /** Server-computed; empty with no position, outside the 5 min window, or after the settlement. */
  readonly charges: readonly FundingCharge[];
}

export interface CountdownClock {
  readonly raf: (callback: (frameTimeMs: number) => void) => number;
  readonly caf: (handle: number) => void;
  /** Monotonic ms: the age of the last ticker update. */
  readonly now: () => number;
}

export const browserCountdownClock = (): CountdownClock => ({
  raf: (callback) => requestAnimationFrame(callback),
  caf: (handle) => cancelAnimationFrame(handle),
  now: () => performance.now(),
});

export interface CountdownFeedOptions {
  readonly symbol: string;
  readonly tick: SecondTick;
  readonly loadCharges: (
    symbol: string,
    signal: AbortSignal,
  ) => Promise<readonly FundingCharge[] | null>;
  readonly clock?: CountdownClock | undefined;
}

export interface CountdownFeedHandle {
  readonly symbol: string;
  getSnapshot(): CountdownSnapshot;
  subscribe(listener: () => void): () => void;
  /** Called once per deadline when the synced clock passes it (BQ 5). */
  onSettlement(listener: (deadlineMs: number) => void): () => void;
  stop(): void;
}

export const INITIAL_COUNTDOWN: CountdownSnapshot = {
  feed: "idle",
  rate: null,
  nextFundingTimeMs: null,
  stale: { tier: "fresh", ageS: 0, lastTsMs: null },
  charges: [],
};

const tierOf = (ageMs: number, serverStale: boolean): StaleTier =>
  serverStale || ageMs >= STALE_T2_MS ? "t2" : ageMs >= STALE_T1_MS ? "t1" : "fresh";

export function startCountdownFeed(
  client: Pick<WsClient, "consume">,
  options: CountdownFeedOptions,
): CountdownFeedHandle {
  const { symbol, tick } = options;
  if (!FUNDING_SYMBOL.test(symbol)) throw new RangeError("funding symbol must be a USDT perpetual");
  const clock = options.clock ?? browserCountdownClock();
  const handle = client.consume({
    ch: `ticker.${symbol}`,
    paneId: `funding:${symbol}`,
    priority: "other",
  });
  const listeners = new Set<() => void>();
  const settledListeners = new Set<(deadlineMs: number) => void>();
  const startedAt = clock.now();
  let snapshot = INITIAL_COUNTDOWN;
  let lastArrival: number | null = null;
  let serverStale = false;
  let marked = new Set<number>();
  let settledFor: number | null = null;
  let chargesCall: AbortController | null = null;
  let frame: number | undefined;
  let stopped = false;

  const publish = (patch: Partial<CountdownSnapshot>): void => {
    snapshot = { ...snapshot, ...patch };
    for (const listener of [...listeners]) listener();
  };

  const readCharges = (): void => {
    chargesCall?.abort();
    const call = new AbortController();
    chargesCall = call;
    void options
      .loadCharges(symbol, call.signal)
      .catch(() => null)
      .then((lines) => {
        // a failed read keeps no line: the charge is never guessed (BQ 4)
        if (!stopped && !call.signal.aborted) publish({ charges: lines ?? [] });
      });
  };

  /** Signals one deadline's settlement, once (BQ 5). */
  const notifySettled = (deadlineMs: number): void => {
    if (settledFor === deadlineMs) return;
    settledFor = deadlineMs;
    for (const listener of [...settledListeners]) listener(deadlineMs);
  };

  const onTick = (): void => {
    const next = snapshot.nextFundingTimeMs;
    if (next === null || stopped) return;
    const left = next - tick.now();
    if (left <= 0) {
      if (settledFor === next) return;
      chargesCall?.abort();
      if (snapshot.charges.length > 0) publish({ charges: [] });
      notifySettled(next);
      return;
    }
    const crossed = CHARGE_MARKS_MS.filter((m) => left <= m && !marked.has(m));
    if (crossed.length === 0) return;
    crossed.forEach((m) => marked.add(m));
    readCharges();
  };
  const offTick = tick.subscribe(onTick);

  const onFrame = (): void => {
    frame = undefined;
    if (stopped) return;
    const now = clock.now();
    let { rate, nextFundingTimeMs } = snapshot;
    let { lastTsMs } = snapshot.stale;
    for (const t of parseFundingFrames(handle.read(), symbol)) {
      if (t === "reset") continue; // the next snapshot restates the item whole
      lastArrival = now;
      serverStale = t.stale;
      lastTsMs = t.tsMs;
      rate = t.rate;
      nextFundingTimeMs = t.nextFundingTimeMs;
    }
    const ageMs = now - (lastArrival ?? startedAt);
    const tier = tierOf(ageMs, serverStale);
    const ageS = tier === "fresh" ? 0 : Math.floor(ageMs / 1000);
    const previous = snapshot.nextFundingTimeMs;
    const nextChanged = nextFundingTimeMs !== previous;
    if (nextChanged) {
      // a new deadline: its own marks, and the old one's lines go
      marked = new Set();
      chargesCall?.abort();
    }
    const s = snapshot.stale;
    if (
      nextChanged ||
      rate !== snapshot.rate ||
      handle.status !== snapshot.feed ||
      tier !== s.tier ||
      ageS !== s.ageS ||
      lastTsMs !== s.lastTsMs
    ) {
      publish({
        feed: handle.status,
        rate,
        nextFundingTimeMs,
        stale: { tier, ageS, lastTsMs },
        ...(nextChanged ? { charges: [] } : {}),
      });
      // the ticker advanced past a deadline the tick never reached (a frame late, a background tab): that
      // settlement is still signalled, once, so its rate is polled for and appended
      if (
        nextChanged &&
        previous !== null &&
        nextFundingTimeMs !== null &&
        previous < nextFundingTimeMs
      ) {
        notifySettled(previous);
      }
      if (nextChanged) onTick();
    }
    frame = clock.raf(onFrame);
  };
  frame = clock.raf(onFrame);

  return {
    symbol,
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    onSettlement: (listener) => {
      settledListeners.add(listener);
      return () => void settledListeners.delete(listener);
    },
    stop: () => {
      if (stopped) return;
      stopped = true;
      offTick();
      if (frame !== undefined) clock.caf(frame);
      frame = undefined;
      chargesCall?.abort();
      listeners.clear();
      settledListeners.clear();
      handle.release();
    },
  };
}

interface Entry {
  readonly feed: CountdownFeedHandle;
  refs: number;
}
const registry = new WeakMap<object, Map<string, Entry>>();

/** The symbol's one entry on this client, shared by every holder; the last release stops it. */
export function acquireCountdownFeed(
  client: Pick<WsClient, "consume">,
  options: CountdownFeedOptions,
): { readonly feed: CountdownFeedHandle; readonly release: () => void } {
  let bySymbol = registry.get(client);
  if (bySymbol === undefined) {
    bySymbol = new Map();
    registry.set(client, bySymbol);
  }
  const map = bySymbol;
  const found = map.get(options.symbol);
  const entry = found ?? { feed: startCountdownFeed(client, options), refs: 0 };
  if (found === undefined) map.set(options.symbol, entry);
  entry.refs += 1;
  let released = false;
  return {
    feed: entry.feed,
    release: () => {
      if (released) return;
      released = true;
      entry.refs -= 1;
      if (entry.refs > 0) return;
      map.delete(options.symbol);
      entry.feed.stop();
    },
  };
}

/** The shared countdown entry for the symbol on the app's client; `null` without one. */
export function useCountdownFeed(
  symbol: string,
  options: Omit<CountdownFeedOptions, "symbol">,
): CountdownFeedHandle | null {
  const { tick, loadCharges, clock } = options;
  const client = useSyncExternalStore(subscribeActiveClient, getActiveClient, getActiveClient);
  const [feed, setFeed] = useState<CountdownFeedHandle | null>(null);
  useEffect(() => {
    if (client === null || !FUNDING_SYMBOL.test(symbol)) return undefined;
    const held = acquireCountdownFeed(client, { symbol, tick, loadCharges, clock });
    setFeed(held.feed);
    return () => {
      held.release();
      setFeed((current) => (current === held.feed ? null : current));
    };
  }, [client, symbol, tick, loadCharges, clock]);
  return feed?.symbol === symbol ? feed : null;
}

const noopSubscribe = (): (() => void) => () => undefined;
const initial = (): CountdownSnapshot => INITIAL_COUNTDOWN;

export function useCountdownSnapshot(feed: CountdownFeedHandle | null): CountdownSnapshot {
  return useSyncExternalStore(
    feed?.subscribe ?? noopSubscribe,
    feed?.getSnapshot ?? initial,
    feed?.getSnapshot ?? initial,
  );
}
