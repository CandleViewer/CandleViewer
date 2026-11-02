/**
 * The Fills tab's feed (E29-S04 #979): it fills `fillsStore`.
 *
 * - **WS** (`23` §6.2.3): `consume({ ch: "executions", opts: { exchange_account_ids }, priority:
 *   "private" })` for the caller's directory (`listExchangeAccounts`, scoped by the server), at
 *   most 25 accounts (`23` §13.5), with no `throttle_ms`: `executions` is never throttled or
 *   coalesced (S4), and a client that cannot keep up is closed `4429`.
 * - **Every animation frame** the handle is drained (`read()`, never per arrival, C9) and the store
 *   applies each item in O(1); **every 200 ms** at most it commits, so the list paints at 5 Hz
 *   (D03 §3.9, `14`:1734) while the topic itself stays unthrottled. A frame-paced blotter is not a
 *   hot path (C-2.20).
 * - **Marks:** for a frame that committed, the scheduler's `state.apply` and `paint` marks and a
 *   `performance.measure` named `ws_frame_apply_seconds` with `detail.topic` `"executions"` between
 *   them (milliseconds, as every measure is; G-W2's transport makes it seconds, as the positions
 *   feed's): the apply-to-paint measure BQ-17's 4 ms budget reads.
 * - **REST** (BQ-9): `listExecutions`, newest first, at most two pages of 500, once at first paint
 *   and once after each `snap` (a reconnect's included): the backfill beyond the snapshot's 100
 *   fills of orders, and the fills of no order, which only REST serves (D03 G20). Never polled.
 *   Past 25 accounts a read names the 25 the subscription does. Only the newest read applies.
 * - **S-02:** no first `snap` within 5 s, or a refused subscription, is "Could not load"; `retry()`
 *   re-subscribes. A narrowing re-reads the directory, as the positions feed does, and the
 *   subscription is made again only when the directory changed.
 */
import type { ConsumerSpec, TopicHandle, WsClient } from "../../../lib/ws/api";
import { createFrameScheduler, type FrameMark } from "../../../lib/ws/client/frameScheduler";
import type { WsState } from "../../../lib/ws/state/types";
import { MAX_ACCOUNT_IDS, positionsApi, type PositionsApi } from "../api";
import { accountInfo, type AccountInfo } from "../model/rowMapping";
import type { FeedTimers, PerformanceLike } from "../wsPositions";
import { fillsApi, readExecutions, type FillsApi } from "./api";
import type { FillsStore } from "./fillsStore";

/** D03 §3.9: painted at most every 200 ms (5 Hz). */
export const COMMIT_INTERVAL_MS = 200;
/** S-02's budget (#911 BQ-18). */
export const SNAPSHOT_BUDGET_MS = 5_000;
/** BQ-9: a backfill reads at most this many pages of `PAGE_LIMIT` (2 × 500). */
export const BACKFILL_PAGES = 2;
export const FILLS_PANE_ID = "scr-063";
export const APPLY_MEASURE = "ws_frame_apply_seconds";
export const MARK_PREFIX = "cv.fills.";
/** The measures kept in the page's timeline at most (C-2.18). */
export const MAX_MEASURES = 1_000;

export interface FillsFeedOptions {
  readonly client: Pick<WsClient, "consume" | "getState" | "subscribe">;
  readonly store: FillsStore;
  readonly api?: FillsApi | undefined;
  /** The account directory's read; defaults to the positions feed's. */
  readonly accounts?: Pick<PositionsApi, "listExchangeAccounts"> | undefined;
  readonly timers?: Pick<FeedTimers, "setTimeout" | "clearTimeout"> | undefined;
  readonly raf?: ((callback: (frameTimeMs: number) => void) => number) | undefined;
  readonly caf?: ((handle: number) => void) | undefined;
  /** Monotonic ms for the commit cadence and the marks; defaults to `performance.now`. */
  readonly now?: (() => number) | undefined;
  /** `null` turns the marks off; defaults to `globalThis.performance`. */
  readonly performance?: PerformanceLike | null | undefined;
  readonly paneId?: string | undefined;
  readonly maxMeasures?: number | undefined;
}

export interface FillsFeed {
  /** S-02's Retry: re-reads the directory if it failed, else re-subscribes. */
  retry(): void;
  stop(): void;
}

const platformTimers = {
  setTimeout: (callback: () => void, ms: number): unknown => setTimeout(callback, ms),
  clearTimeout: (handle: unknown): void => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** Down from the loss of an `up` link until the next `auth_ok`, and while offline. */
const isDown = (state: Pick<WsState, "link" | "outage">): boolean =>
  state.outage !== null || state.link.kind === "offline";

export function startFillsFeed(options: FillsFeedOptions): FillsFeed {
  const { client, store } = options;
  const api = options.api ?? fillsApi;
  const directoryApi = options.accounts ?? positionsApi;
  const timers = options.timers ?? platformTimers;
  const now = options.now ?? ((): number => performance.now());
  const perf = options.performance === undefined ? globalThis.performance : options.performance;
  const abort = new AbortController();
  let stopped = false;
  let accountIds: readonly string[] | null = null;
  let handle: TopicHandle | null = null;
  let budget: unknown;
  let restSeq = 0;
  let lastCommit = Number.NEGATIVE_INFINITY;
  let committed = false;
  let applyStart = 0;
  let measures = 0;

  function clearBudget(): void {
    if (budget !== undefined) timers.clearTimeout(budget);
    budget = undefined;
  }

  function release(): void {
    clearBudget();
    handle?.release();
    handle = null;
  }

  function subscribe(ids: readonly string[]): void {
    release();
    if (stopped || ids.length === 0) return; // an empty list is `invalid_options` (23 §6.2)
    store.setOverCap(ids.slice(MAX_ACCOUNT_IDS));
    const spec: ConsumerSpec = {
      ch: "executions",
      paneId: options.paneId ?? FILLS_PANE_ID,
      priority: "private",
      opts: { exchange_account_ids: ids.slice(0, MAX_ACCOUNT_IDS) },
    };
    handle = client.consume(spec);
    budget = timers.setTimeout(() => {
      budget = undefined;
      store.markSnapshotFailed();
    }, SNAPSHOT_BUDGET_MS);
  }

  /** One backfill: newest first, at most two pages; past the cap it names the subscription's 25. */
  function readRest(): void {
    restSeq += 1;
    const seq = restSeq;
    const named =
      accountIds !== null && accountIds.length > MAX_ACCOUNT_IDS
        ? { accountIds: accountIds.slice(0, MAX_ACCOUNT_IDS) }
        : {};
    void readExecutions(api, named, BACKFILL_PAGES, abort.signal).then((out) => {
      if (!stopped && seq === restSeq && out.kind === "ok") store.applyRest(out.value.items);
    });
  }

  function loadAccounts(narrowed = false): void {
    void directoryApi.listExchangeAccounts(abort.signal).then((outcome) => {
      if (stopped) return;
      if (outcome.kind !== "ok") {
        if (!narrowed) store.setAccounts(null);
        return;
      }
      const directory = outcome.items.map(accountInfo).filter((a): a is AccountInfo => a !== null);
      store.setAccounts(directory);
      const ids = directory.map((a) => a.id);
      const before = accountIds;
      const same =
        before !== null && ids.length === before.length && ids.every((id, i) => before[i] === id);
      accountIds = ids;
      if (!narrowed || (!same && store.getSnapshot().status !== "revoked")) subscribe(ids);
    });
  }

  /** One animation frame: drain and apply; commit when 200 ms have passed since the last. */
  function drain(): void {
    committed = false;
    try {
      if (handle !== null) {
        const frames = handle.read();
        store.applyFrames(frames);
        if (frames.some((f) => f.kind === "snap")) {
          clearBudget();
          readRest(); // BQ-9: after each snapshot, a reconnect's included
        }
        store.setEffective(handle.effective);
      }
      if (store.takeNarrowed()) loadAccounts(true); // 23 §9.5: the directory says who left
      store.setLink(!isDown(client.getState()));
      const at = now();
      if (at - lastCommit >= COMMIT_INTERVAL_MS && store.commit()) {
        lastCommit = at;
        committed = true;
      }
    } finally {
      if (!stopped) scheduler.post("frame", true); // the next animation frame drains again
    }
  }

  function mark(name: FrameMark, atMs: number): void {
    if (name === "state.apply") {
      applyStart = atMs;
      return;
    }
    if (!committed || perf === null || perf === undefined) return;
    try {
      perf.mark(`${MARK_PREFIX}state.apply`, { startTime: applyStart });
      perf.mark(`${MARK_PREFIX}paint`, { startTime: atMs });
      perf.measure(APPLY_MEASURE, {
        start: applyStart,
        end: atMs,
        detail: { topic: "executions" },
      });
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

  store.setStarted(true);
  store.commit();
  readRest(); // first paint, before the directory and the snapshot
  loadAccounts();
  scheduler.post("frame", true);

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
      scheduler.stop();
      release();
      store.setStarted(false);
      store.commit();
    },
  };
}
