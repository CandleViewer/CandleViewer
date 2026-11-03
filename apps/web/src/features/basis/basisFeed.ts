// E24-S08 (#783) slice 1: the basis readout's feed, outside React. One `ticker.{symbol}` subscription
// through the existing `TopicHandle`, drained once per animation frame (never per message, rules/30);
// React reads a coarse snapshot through `useSyncExternalStore`. Deviation (as E22-S01's tape and E24-S01's
// OI feed, C-69): `apps/web` carries no RxJS or Jotai, so the stream is the handle's rAF read and the atom
// an external store; the coalescing contract is the same. A live readout only (BQ 1, ruled (6612480577)): ticker
// snapshots are not stored, so there is no history to draw a series from.
import { useSyncExternalStore } from "react";
import type { WsClient } from "../../lib/ws/api";
import type { TopicStatus } from "../../lib/ws/state/types";
import { parseBasisFrames, type BasisTick } from "./ticker";

/** `23` §14.2 / common `symbol`: a USDT linear perpetual (C-1.3). */
export const BASIS_SYMBOL = /^[A-Z0-9]{2,20}USDT$/;
/** The readout renders on change at <= 1 Hz (the ticket's Performance notes). */
export const PUBLISH_INTERVAL_MS = 1_000;
/** D02 DV-1 / D03 §10.2 (as the OI readout, BQ 3): a stale chip from 5 s, escalated from 15 s. */
export const STALE_T1_MS = 5_000;
export const STALE_T2_MS = 15_000;

export type StaleTier = "fresh" | "t1" | "t2";

export function staleTier(ageMs: number, serverStale: boolean): StaleTier {
  if (serverStale || ageMs >= STALE_T2_MS) return "t2";
  return ageMs >= STALE_T1_MS ? "t1" : "fresh";
}

const ageSeconds = (ageMs: number): number => Math.floor(Math.max(0, ageMs) / 1000);

export interface BasisClock {
  readonly raf: (callback: (frameTimeMs: number) => void) => number;
  readonly caf: (handle: number) => void;
  /** Monotonic ms: the age of the last update. */
  readonly now: () => number;
  /** Wall-clock epoch ms. */
  readonly wallNow: () => number;
}

export const browserBasisClock = (): BasisClock => ({
  raf: (callback) => requestAnimationFrame(callback),
  caf: (handle) => cancelAnimationFrame(handle),
  now: () => performance.now(),
  wallNow: () => Date.now(),
});

export interface BasisSnapshot {
  readonly feed: "idle" | TopicStatus;
  readonly latest: BasisTick | null;
  readonly stale: {
    readonly tier: StaleTier;
    readonly ageMs: number;
    readonly lastTsMs: number | null;
  };
}

export interface BasisFeedOptions {
  readonly symbol: string;
  readonly paneId: string;
  readonly clock?: BasisClock | undefined;
}

export interface BasisFeedHandle {
  readonly symbol: string;
  getSnapshot(): BasisSnapshot;
  subscribe(listener: () => void): () => void;
  /** Releases the subscription and stops the loop. Idempotent. */
  stop(): void;
}

export const INITIAL_BASIS_SNAPSHOT: BasisSnapshot = {
  feed: "idle",
  latest: null,
  stale: { tier: "fresh", ageMs: 0, lastTsMs: null },
};

export function startBasisFeed(
  client: Pick<WsClient, "consume">,
  options: BasisFeedOptions,
): BasisFeedHandle {
  const { symbol, paneId } = options;
  if (!BASIS_SYMBOL.test(symbol)) throw new RangeError("basis symbol must be a USDT perpetual");
  const clock = options.clock ?? browserBasisClock();
  const listeners = new Set<() => void>();
  const handle = client.consume({ ch: `ticker.${symbol}`, paneId, priority: "other" });
  let snapshot: BasisSnapshot = INITIAL_BASIS_SNAPSHOT;
  let latest: BasisTick | null = null;
  // the timestamp-ordering baseline: cleared on a reset (a restarted stream may carry older timestamps),
  // while `latest` stays shown
  let baselineTs: number | null = null;
  let version = 0;
  let lastArrival: number | null = null;
  let published = -Infinity;
  let shownVersion = -1;
  let shownAge = -1;
  let shownTier: StaleTier = "fresh";
  let shownFeed: BasisSnapshot["feed"] = "idle";
  let frame: number | undefined;
  let stopped = false;

  const publish = (next: BasisSnapshot): void => {
    snapshot = next;
    for (const listener of [...listeners]) listener();
  };

  const onFrame = (): void => {
    frame = undefined;
    if (stopped) return;
    const now = clock.now();
    for (const tick of parseBasisFrames(handle.read(), symbol)) {
      if (tick === "reset") {
        baselineTs = null; // whole items: the next one replaces the state (`23` §8.2)
        continue;
      }
      if (baselineTs !== null && tick.tsMs < baselineTs) continue; // an older item never replaces a newer
      latest = tick;
      baselineTs = tick.tsMs;
      lastArrival = now;
      version += 1;
    }
    const ageMs = lastArrival === null ? 0 : now - lastArrival;
    const feed = handle.status;
    // a `stale` topic is the stale chip at t2, the same as a served `stale: true`
    const tier =
      latest === null || lastArrival === null
        ? "fresh"
        : staleTier(ageMs, latest.stale || feed === "stale");
    // a state change publishes at once; a value change at most once a second; the chip's age per second
    const structural = tier !== shownTier || feed !== shownFeed;
    const valueDue = version !== shownVersion && now - published >= PUBLISH_INTERVAL_MS;
    const ageDue = tier !== "fresh" && ageSeconds(ageMs) !== shownAge;
    if (structural || valueDue || ageDue) {
      published = now;
      shownVersion = version;
      shownAge = ageSeconds(ageMs);
      shownTier = tier;
      shownFeed = feed;
      publish({ feed, latest, stale: { tier, ageMs, lastTsMs: latest?.tsMs ?? null } });
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
    stop: () => {
      if (stopped) return;
      stopped = true;
      if (frame !== undefined) clock.caf(frame);
      frame = undefined;
      listeners.clear();
      handle.release();
    },
  };
}

const noopSubscribe = (): (() => void) => () => undefined;
const initial = (): BasisSnapshot => INITIAL_BASIS_SNAPSHOT;

/** The coarse basis state; re-renders on a state change, at most once a second for values. */
export function useBasisSnapshot(feed: BasisFeedHandle | null): BasisSnapshot {
  return useSyncExternalStore(
    feed?.subscribe ?? noopSubscribe,
    feed?.getSnapshot ?? initial,
    feed?.getSnapshot ?? initial,
  );
}
