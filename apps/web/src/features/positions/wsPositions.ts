/**
 * The Positions tab's feed (E29-S01 #911): it fills `positionsStore` and `accountSignals`.
 *
 * - **WS** (`23` §6.2.3): `consume({ ch: "positions", opts: { exchange_account_ids }, priority:
 *   "private" })`, the same for `wallet` (`account_mm_rate` for the cross tiers, BQ-11), and one
 *   B20 `machines.risk_lockout:{id}.state` per account (BQ-14). The accounts are the caller's
 *   directory (`listExchangeAccounts`, scoped by the server), at most 25 (`23` §13.5).
 * - **The tick** (the ticket's 10 Hz, BQ-19): every 100 ms the feed asks `frameScheduler` for a
 *   frame; in it, every handle is drained (`read()`, never per arrival, C9), the store applies the
 *   frames and commits once. A frame read at the tick is on the screen by the next paint, so an
 *   arrival reaches the DOM within one tick and a frame (BQ-21's 200 ms, proven with fake timers).
 * - **Marks** (BQ-21): the scheduler's `state.apply` and `paint` marks, and between them a
 *   `performance.measure` named `ws_frame_apply_seconds` with `detail.topic` `"positions"` for every
 *   tick that applied a frame. Local only: its transport is G-W2's (E29-Q03, E29-T09).
 * - **REST** (BQ-18): one `listPositions` for first paint while the topic is pending, and one per
 *   link-down episode as the fallback. Never polled.
 * - **S-02:** no first `snap` within 5 s (BQ-18's budget), or a refused subscription, is "Could not
 *   load"; `retry()` re-subscribes.
 * - **A narrowing** (`23` §9.5) re-subscribes with the same accounts: its `sub_ok` names the ones
 *   kept, and the store drops the rest with their F-02 lines (SR-E29-11).
 */
import type { ConsumerSpec, TopicHandle, WsClient } from "../../lib/ws/api";
import { createFrameScheduler, type FrameMark } from "../../lib/ws/client/frameScheduler";
import type { WsState } from "../../lib/ws/state/types";
import type { AccountSignalsStore } from "./accountSignals";
import { MAX_ACCOUNT_IDS, positionsApi, type PositionsApi } from "./api";
import { accountInfo, type AccountInfo } from "./model/rowMapping";
import type { PositionsStore } from "./positionsStore";

/** The ticket's 10 Hz commit tick. */
export const COMMIT_INTERVAL_MS = 100;
/** S-02's "E29-S01 budget" (#911 BQ-18, `14`:2963). */
export const SNAPSHOT_BUDGET_MS = 5_000;
/** The pane the feed's subscriptions belong to (C8); the panel sets its visibility. */
export const POSITIONS_PANE_ID = "scr-063";
/** The client metric `ws_frame_apply_seconds{topic="positions"}` (the ticket's Observability). */
export const APPLY_MEASURE = "ws_frame_apply_seconds";
export const MARK_PREFIX = "cv.positions.";
/** The measures kept in the page's timeline at most (C-2.18): past it they are cleared and recounted. */
export const MAX_MEASURES = 1_000;

export interface FeedTimers {
  setInterval(callback: () => void, ms: number): unknown;
  clearInterval(handle: unknown): void;
  setTimeout(callback: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface PerformanceLike {
  mark(name: string, options?: { startTime?: number }): unknown;
  measure(name: string, options: { start: number; end: number; detail?: unknown }): unknown;
  clearMarks?(name?: string): void;
  clearMeasures?(name?: string): void;
}

export interface PositionsFeedOptions {
  readonly client: Pick<WsClient, "consume" | "getState" | "subscribe">;
  readonly store: PositionsStore;
  readonly signals?: AccountSignalsStore | undefined;
  readonly api?: PositionsApi | undefined;
  readonly timers?: FeedTimers | undefined;
  readonly raf?: ((callback: (frameTimeMs: number) => void) => number) | undefined;
  readonly caf?: ((handle: number) => void) | undefined;
  /** Monotonic ms for the marks; defaults to `performance.now`. */
  readonly now?: (() => number) | undefined;
  /** Epoch ms for a REST read's "as of"; defaults to `Date.now`. */
  readonly wall?: (() => number) | undefined;
  /** `null` turns the marks off; defaults to `globalThis.performance`. */
  readonly performance?: PerformanceLike | null | undefined;
  readonly paneId?: string | undefined;
  /** The measures kept at most; defaults to `MAX_MEASURES`. */
  readonly maxMeasures?: number | undefined;
}

export interface PositionsFeed {
  /** S-02's Retry: re-reads the directory if it failed, else re-subscribes. */
  retry(): void;
  stop(): void;
}

const platformTimers: FeedTimers = {
  setInterval: (callback, ms) => setInterval(callback, ms),
  clearInterval: (handle) => clearInterval(handle as ReturnType<typeof setInterval>),
  setTimeout: (callback, ms) => setTimeout(callback, ms),
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/**
 * The link is down from the loss of an `up` link (`WsState.outage`, set by the event that takes it
 * down, cleared by the next `auth_ok`) and while offline; a first connect is not a loss.
 */
const isDown = (state: Pick<WsState, "link" | "outage">): boolean =>
  state.outage !== null || state.link.kind === "offline";

export const lockoutChannel = (accountId: string): string =>
  `machines.risk_lockout:${accountId}.state`;

export function startPositionsFeed(options: PositionsFeedOptions): PositionsFeed {
  const { client, store, signals } = options;
  const api = options.api ?? positionsApi;
  const timers = options.timers ?? platformTimers;
  const wall = options.wall ?? ((): number => Date.now());
  const perf = options.performance === undefined ? globalThis.performance : options.performance;
  const paneId = options.paneId ?? POSITIONS_PANE_ID;
  const abort = new AbortController();
  let stopped = false;
  let accountIds: readonly string[] | null = null;
  let positions: TopicHandle | null = null;
  let wallet: TopicHandle | null = null;
  let lockouts = new Map<string, TopicHandle>();
  let budget: unknown;
  let fallbackAsked = false;
  let applied = 0;
  let applyStart = 0;
  let measures = 0;

  const spec = (ch: string, opts?: ConsumerSpec["opts"]): ConsumerSpec => ({
    ch,
    paneId,
    priority: "private",
    ...(opts !== undefined && { opts }),
  });

  function clearBudget(): void {
    if (budget !== undefined) timers.clearTimeout(budget);
    budget = undefined;
  }

  function release(): void {
    clearBudget();
    positions?.release();
    wallet?.release();
    for (const handle of lockouts.values()) handle.release();
    positions = null;
    wallet = null;
    lockouts = new Map();
  }

  function subscribe(ids: readonly string[]): void {
    release();
    if (stopped || ids.length === 0) return; // an empty list is `invalid_options` (23 §6.2)
    const named = ids.slice(0, MAX_ACCOUNT_IDS);
    store.setOverCap(ids.slice(MAX_ACCOUNT_IDS));
    const opts = { exchange_account_ids: [...named] };
    positions = client.consume(spec("positions", opts));
    wallet = client.consume(spec("wallet", opts));
    for (const id of named) lockouts.set(id, client.consume(spec(lockoutChannel(id))));
    budget = timers.setTimeout(() => {
      budget = undefined;
      store.markSnapshotFailed();
    }, SNAPSHOT_BUDGET_MS);
  }

  function readRest(): void {
    void api.listPositions({}, abort.signal).then((outcome) => {
      if (!stopped && outcome.kind === "ok") store.applyRest(outcome.items, wall());
    });
  }

  function loadAccounts(): void {
    void api.listExchangeAccounts(abort.signal).then((outcome) => {
      if (stopped) return;
      if (outcome.kind !== "ok") {
        store.setAccounts(null);
        return;
      }
      const directory = outcome.items.map(accountInfo).filter((a): a is AccountInfo => a !== null);
      store.setAccounts(directory);
      accountIds = directory.map((a) => a.id);
      subscribe(accountIds);
    });
  }

  function link(): void {
    const up = !isDown(client.getState());
    store.setLink(up);
    if (up) {
      fallbackAsked = false;
      return;
    }
    if (!fallbackAsked) {
      fallbackAsked = true; // one read per link-down episode, never a poll (BQ-18)
      readRest();
    }
  }

  function drain(): void {
    applied = 0;
    if (positions !== null) {
      const frames = positions.read();
      applied = frames.length;
      if (frames.some((f) => f.kind === "snap")) clearBudget();
      store.applyFrames(frames);
    }
    if (wallet !== null) store.applyWallet(wallet.read());
    for (const [id, handle] of lockouts) {
      const frames = handle.read();
      if (frames.length > 0) signals?.applyLockout(id, frames);
    }
    if (store.takeResubscribe() && accountIds !== null) subscribe(accountIds); // 23 §9.5
    if (positions !== null) store.setEffective(positions.effective);
    link();
    store.commit();
    // SR-E29-11: a withdrawn account's signals leave with its rows (`forget` is idempotent)
    signals?.forget(store.getSnapshot().withdrawn.map((w) => w.accountId));
  }

  /**
   * The scheduler's `state.apply` and `paint` marks, and the measure between them, for a tick that
   * applied frames (an idle tick writes nothing). The marks are cleared once measured and at most
   * `MAX_MEASURES` measures are kept, so the page's timeline stays bounded on a long session; a
   * `PerformanceObserver` sees every entry.
   */
  function mark(name: FrameMark, atMs: number): void {
    if (name === "state.apply") {
      applyStart = atMs;
      return;
    }
    if (applied === 0 || perf === null || perf === undefined) return;
    try {
      perf.mark(`${MARK_PREFIX}state.apply`, { startTime: applyStart });
      perf.mark(`${MARK_PREFIX}paint`, { startTime: atMs });
      perf.measure(APPLY_MEASURE, { start: applyStart, end: atMs, detail: { topic: "positions" } });
      perf.clearMarks?.(`${MARK_PREFIX}state.apply`);
      perf.clearMarks?.(`${MARK_PREFIX}paint`);
      measures += 1;
      if (measures >= (options.maxMeasures ?? MAX_MEASURES)) {
        perf.clearMeasures?.(APPLY_MEASURE);
        measures = 0;
      }
    } catch {
      // a measure must never harm the feed (`lib/telemetry`'s rule)
    }
  }

  const scheduler = createFrameScheduler<true>({
    render: drain,
    raf: options.raf,
    caf: options.caf,
    now: options.now,
    mark,
  });
  const tick = timers.setInterval(() => scheduler.post("tick", true), COMMIT_INTERVAL_MS);

  store.setStarted(true);
  store.commit();
  readRest();
  loadAccounts();

  return {
    retry() {
      if (stopped) return;
      store.markRetrying();
      if (accountIds === null) loadAccounts();
      else subscribe(accountIds);
    },
    stop() {
      if (stopped) return;
      stopped = true;
      abort.abort();
      timers.clearInterval(tick);
      scheduler.stop();
      release();
      signals?.forget(accountIds ?? []);
      store.setStarted(false);
      store.commit();
    },
  };
}
