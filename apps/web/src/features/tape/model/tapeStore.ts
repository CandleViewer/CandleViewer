// E22-S01 (#714) PR-A: the tape's coarse state for React. A plain external store read through
// `useSyncExternalStore` (C-69: no Jotai, RxJS or Zustand in `apps/web`; a recorded deviation from
// `rules/30`). Rows never pass through it: they go ring -> writer (PR-B). The counters it carries
// (the CP3 readout "2 010 /s (1 s) · 33 /frame", BQ-209) publish at most twice a second (D4-07);
// only a feed transition publishes at once, and never once per message.
import { useSyncExternalStore } from "react";
import type { TopicStatus } from "../../../lib/ws/state/types";

/** ≤ 2 Hz (C-69, D4-07). */
export const PUBLISH_INTERVAL_MS = 500;
/** The readout's window: "(1 s)". */
export const RATE_WINDOW_MS = 1_000;
/** Frame samples kept for the window: far more than 1 s of 240 Hz frames. */
const SAMPLE_SLOTS = 512;

/** `idle`: no subscription yet (no client, or the flag is off). */
export type TapeFeed = "idle" | TopicStatus;

export interface TapeSnapshot {
  readonly feed: TapeFeed;
  /** Prints appended in the last second. */
  readonly ratePerSec: number;
  /** Prints per animation frame over that second, rounded. */
  readonly perFrame: number;
  readonly rows: number;
  readonly seams: number;
  readonly notKept: number;
  readonly lastPrintTsMs: number | null;
  readonly threshold: string | null;
}

/** What the feed loop reports on each animation frame. */
export interface FrameReport {
  readonly appended: number;
  readonly rows: number;
  readonly seams: number;
  readonly notKept: number;
  readonly lastPrintTsMs: number | undefined;
  readonly threshold: string | undefined;
}

export interface TapeStore {
  getSnapshot(): TapeSnapshot;
  subscribe(listener: () => void): () => void;
  /** Once per animation frame; publishes when the interval has passed and something changed. */
  frame(nowMs: number, report: FrameReport): void;
  /** A transition publishes at once. */
  setFeed(feed: TapeFeed): void;
}

export const INITIAL_TAPE_SNAPSHOT: TapeSnapshot = {
  feed: "idle",
  ratePerSec: 0,
  perFrame: 0,
  rows: 0,
  seams: 0,
  notKept: 0,
  lastPrintTsMs: null,
  threshold: null,
};

const sameCounters = (a: TapeSnapshot, b: TapeSnapshot): boolean =>
  a.ratePerSec === b.ratePerSec &&
  a.perFrame === b.perFrame &&
  a.rows === b.rows &&
  a.seams === b.seams &&
  a.notKept === b.notKept &&
  a.lastPrintTsMs === b.lastPrintTsMs &&
  a.threshold === b.threshold;

export function createTapeStore(): TapeStore {
  let snapshot = INITIAL_TAPE_SNAPSHOT;
  let lastPublish = -Infinity;
  const listeners = new Set<() => void>();
  // a fixed ring of (time, appended) frame samples: no allocation per frame
  const times = new Float64Array(SAMPLE_SLOTS);
  const counts = new Float64Array(SAMPLE_SLOTS);
  let head = 0;
  let held = 0;
  let sum = 0;

  const publish = (next: TapeSnapshot): void => {
    snapshot = next;
    for (const listener of [...listeners]) listener();
  };

  const prune = (nowMs: number): void => {
    while (held > 0) {
      const tail = (head - held + SAMPLE_SLOTS) % SAMPLE_SLOTS;
      if (held < SAMPLE_SLOTS && nowMs - (times[tail] ?? 0) < RATE_WINDOW_MS) break;
      sum -= counts[tail] ?? 0;
      held -= 1;
    }
  };

  return {
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    frame: (nowMs, report) => {
      prune(nowMs);
      times[head] = nowMs;
      counts[head] = report.appended;
      head = (head + 1) % SAMPLE_SLOTS;
      held += 1;
      sum += report.appended;
      if (nowMs - lastPublish < PUBLISH_INTERVAL_MS) return;
      lastPublish = nowMs;
      const next: TapeSnapshot = {
        feed: snapshot.feed,
        ratePerSec: sum,
        perFrame: Math.round(sum / held),
        rows: report.rows,
        seams: report.seams,
        notKept: report.notKept,
        lastPrintTsMs: report.lastPrintTsMs ?? null,
        threshold: report.threshold ?? null,
      };
      if (!sameCounters(next, snapshot)) publish(next);
    },
    setFeed: (feed) => {
      if (feed !== snapshot.feed) publish({ ...snapshot, feed });
    },
  };
}

/** The coarse tape state; re-renders at most at the publish rate, or on a feed transition. */
export function useTapeSnapshot(store: TapeStore | null): TapeSnapshot {
  return useSyncExternalStore(
    store?.subscribe ?? noopSubscribe,
    store?.getSnapshot ?? initial,
    store?.getSnapshot ?? initial,
  );
}

const noopSubscribe = (): (() => void) => () => undefined;
const initial = (): TapeSnapshot => INITIAL_TAPE_SNAPSHOT;
