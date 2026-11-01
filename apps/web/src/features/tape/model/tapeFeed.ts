// E22-S01 (#714) PR-A: one tape's feed loop, outside React. It consumes `trades.{symbol}` through
// the existing `TopicHandle` (BQ-208: no `lib/ws` change), drains it once per animation frame,
// ingests the frames into the ring and tells the store and the frame listeners (the writer of
// PR-B). Nothing is applied on arrival and nothing per message reaches React (C-2.20, rules/30).
import type { PaneVisibility, WsClient } from "../../../lib/ws/api";
import { TapeIngest, type IngestCounters } from "./ingest";
import { TapeRing } from "./ring";
import { createTapeStore, type TapeStore } from "./tapeStore";

/** `23` §14.2 / common `symbol`: a USDT linear perpetual (C-1.3). */
export const TAPE_SYMBOL = /^[A-Z0-9]{2,20}USDT$/;

export interface TapeClock {
  readonly raf: (callback: (frameTimeMs: number) => void) => number;
  readonly caf: (handle: number) => void;
  /** Monotonic milliseconds. */
  readonly now: () => number;
}

export const browserClock = (): TapeClock => ({
  raf: (callback) => requestAnimationFrame(callback),
  caf: (handle) => cancelAnimationFrame(handle),
  now: () => performance.now(),
});

/** In memory only, never exported off the client (BQ-209, Observability). */
export interface TapeMetrics extends IngestCounters {
  /** Animation frames that read the handle. */
  readonly ticks: number;
  /** Time spent ingesting, last frame and worst frame, in ms. */
  readonly lastIngestMs: number;
  readonly maxIngestMs: number;
}

export type FrameListener = (appended: number) => void;

export interface TapeFeedHandle {
  readonly symbol: string;
  readonly ring: TapeRing;
  readonly store: TapeStore;
  /** Called once per animation frame, after the ingest: the writer's hook (PR-B). */
  onFrame(listener: FrameListener): () => void;
  setVisibility(visibility: PaneVisibility): void;
  metrics(): TapeMetrics;
  /** Releases the subscription and stops the loop. Idempotent. */
  stop(): void;
}

export interface TapeFeedOptions {
  readonly symbol: string;
  readonly paneId: string;
  readonly capacity?: number | undefined;
  readonly clock?: TapeClock | undefined;
}

export function startTapeFeed(
  client: Pick<WsClient, "consume" | "setPane">,
  options: TapeFeedOptions,
): TapeFeedHandle {
  const { symbol, paneId } = options;
  if (!TAPE_SYMBOL.test(symbol)) throw new RangeError("tape symbol must be a USDT perpetual");
  const clock = options.clock ?? browserClock();
  const ring = new TapeRing(options.capacity);
  const ingest = new TapeIngest(ring, symbol);
  const store = createTapeStore();
  const listeners = new Set<FrameListener>();
  // BQ-207: structured, which carries `id`, `dropped` and `coalesced_count`; no other option is
  // sent (`min_size` and clustering belong to E22-S02/S04/S05).
  const handle = client.consume({
    ch: `trades.${symbol}`,
    opts: { encoding: "structured" },
    paneId,
    priority: "other",
  });
  let ticks = 0;
  let lastIngestMs = 0;
  let maxIngestMs = 0;
  let frame: number | undefined;
  let stopped = false;

  const onFrame = (): void => {
    frame = undefined;
    if (stopped) return;
    const start = clock.now();
    const appended = ingest.apply(handle.read());
    const end = clock.now();
    ticks += 1;
    lastIngestMs = end - start;
    if (lastIngestMs > maxIngestMs) maxIngestMs = lastIngestMs;
    store.setFeed(handle.status);
    store.frame(end, {
      appended,
      rows: ring.length,
      seams: ingest.seams,
      notKept: ring.notKept,
      lastPrintTsMs: ingest.lastPrintTsMs,
      threshold: ingest.threshold,
    });
    // iterate the Set directly: no per-frame copy (a listener that adds itself mid-frame is called)
    for (const listener of listeners) listener(appended);
    frame = clock.raf(onFrame);
  };

  store.setFeed(handle.status);
  frame = clock.raf(onFrame);

  return {
    symbol,
    ring,
    store,
    onFrame: (listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    // PR-B (the panel) is the only caller besides the hook: it owns visibility from here on.
    setVisibility: (visibility) => {
      if (!stopped) client.setPane(paneId, visibility);
    },
    metrics: () => ({ ...ingest.counters, ticks, lastIngestMs, maxIngestMs }),
    stop: () => {
      if (stopped) return;
      stopped = true;
      if (frame !== undefined) clock.caf(frame);
      frame = undefined;
      listeners.clear();
      handle.release();
      store.setFeed("idle");
    },
  };
}
