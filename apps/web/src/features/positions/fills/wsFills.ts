/**
 * The Fills tab's feed (E29-S04 #979): it fills `fillsStore`.
 *
 * - **WS** (`23` §6.2.3): `consume({ ch: "executions", opts: { exchange_account_ids }, priority:
 *   "private" })` for the caller's directory (`listExchangeAccounts`, scoped by the server), at
 *   most 25 accounts (`23` §13.5), with no `throttle_ms`: `executions` is never throttled or
 *   coalesced (S4), and a client that cannot keep up is closed `4429`.
 * - **Every animation frame** the handle is drained (`read()`, never per arrival, C9) and the store
 *   applies each item in O(1), then REST's waiting items up to `APPLY_SLICE` in all; **every
 *   200 ms** at most it commits, so the list paints at 5 Hz (D03 §3.9, `14`:1734) while the topic
 *   itself stays unthrottled, and a security reset is published in its own frame (SR-E29-11). A
 *   frame-paced blotter is not a hot path (C-2.20).
 * - **Marks:** for a frame that applied fills or committed, the scheduler's `state.apply` and
 *   `paint` marks and a `performance.measure` named `ws_frame_apply_seconds` with `detail.topic`
 *   `"executions"` between them (milliseconds, as every measure is; G-W2's transport makes it
 *   seconds, as the positions feed's): the apply-to-paint measure BQ-17's 4 ms budget reads.
 * - **REST** (BQ-9): `listExecutions`, newest first, at most two pages of 500, once at first paint
 *   and after each `snap` (a reconnect's included) or settled narrowing, those at most once per
 *   `BACKFILL_INTERVAL_MS`: the backfill beyond the snapshot's 100 fills of orders, and the fills
 *   of no order, which only REST serves (D03 G20). Never polled. Past 25 accounts a read names the
 *   25 the subscription does. Every read that answers applies, a superseded one too (the store is
 *   a set); a failed one, or a failed page, is the store's `readFailed` if it was asked last.
 *   A Retry after a revoke drops the answers of the reads asked before it, waiting ones too.
 * - **S-02:** no first `snap` within 5 s, or a refused subscription, is "Could not load"; `retry()`
 *   re-subscribes, and reads REST again after a failed read. A narrowing re-reads the directory,
 *   as the positions feed does, and the subscription is made again only when the directory changed;
 *   while it waits, a failed re-read is D03:191's "Could not load", and `retry()` reads it again.
 */
import type { ConsumerSpec, TopicHandle, WsClient } from "../../../lib/ws/api";
import { createFrameScheduler, type FrameMark } from "../../../lib/ws/client/frameScheduler";
import type { WsState } from "../../../lib/ws/state/types";
import { MAX_ACCOUNT_IDS, positionsApi, type PositionsApi } from "../api";
import { accountInfo, type AccountInfo } from "../model/rowMapping";
import type { FeedTimers, PerformanceLike } from "../wsPositions";
import { fillsApi, readExecutions, type FillsApi } from "./api";
import { MAX_FILLS, type FillsStore } from "./fillsStore";

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
/** The fills one animation frame applies at most: WS items first, then REST's, which wait. */
export const APPLY_SLICE = 200;
/** The REST items that wait for a frame, at most (C-2.18): the store holds `MAX_FILLS` anyway. */
export const MAX_QUEUED = MAX_FILLS;
/**
 * One backfill after first paint per 10 s at most; one asked inside it reads at its end. A link
 * that flaps, or a topic re-snapshotted after each missed publish (`23` §6.2.3), would otherwise
 * read 2 × 500 rows, mostly held, per snapshot; and the snapshot brings the newest 100 at once.
 */
export const BACKFILL_INTERVAL_MS = 10_000;

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
  /** S-02's Retry: re-reads a failed directory (a narrowing's too) and re-makes a failed feed. */
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
  const queue: unknown[] = []; // REST items to apply: 1,000 a read, `MAX_QUEUED` at most (C-2.18)
  let readSeq = 0; // the reads asked so far: the last one decides `readFailed`
  let readLost = false; // that last read failed, or a page of it
  let narrowing = false; // a narrowing waits for a read to say who stayed
  let directoryLost = false; // and its directory re-read failed: the candidates stay barred
  let lastBackfill = Number.NEGATIVE_INFINITY;
  let owed: unknown; // the timer of a backfill asked inside the interval
  let effective: Readonly<Record<string, unknown>> | null = null;
  let lastCommit = Number.NEGATIVE_INFINITY;
  let committed = false;
  let applied = 0;
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

  /** D03:191's "Could not load" and Retry: the last read failed, or a narrowing's directory. */
  const showLost = (): void => store.setReadFailed(readLost || directoryLost);

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

  /** One read: newest first, at most two pages; past the cap it names the subscription's 25. */
  function readRest(signal = store.readSignal()): void {
    const named =
      accountIds !== null && accountIds.length > MAX_ACCOUNT_IDS
        ? { accountIds: accountIds.slice(0, MAX_ACCOUNT_IDS) }
        : {};
    const seq = (readSeq += 1);
    void readExecutions(api, named, BACKFILL_PAGES, signal).then((out) => {
      if (stopped || signal.aborted) return; // a Retry after a revoke starts the reads afresh
      if (seq === readSeq) {
        readLost = out.kind !== "ok" || out.value.failure !== null;
        showLost();
      }
      if (out.kind === "ok") queue.push(...out.value.items.slice(0, MAX_QUEUED - queue.length));
    });
  }

  /** A backfill after first paint, at most one per interval. */
  function backfill(): void {
    if (owed !== undefined) return;
    const wait = lastBackfill + BACKFILL_INTERVAL_MS - now();
    if (wait > 0) {
      owed = timers.setTimeout(() => {
        owed = undefined;
        backfill();
      }, wait);
      return;
    }
    lastBackfill = now();
    readRest();
  }

  function loadAccounts(narrowed = false): void {
    void directoryApi.listExchangeAccounts(abort.signal).then((outcome) => {
      if (stopped) return;
      if (outcome.kind !== "ok") {
        if (!narrowed) store.setAccounts(null);
        else if (narrowing) {
          directoryLost = true; // its candidates' fills are refused until a read settles it
          showLost();
        }
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

  /** One animation frame: drain and apply; commit 200 ms after the last, a security reset now. */
  function drain(): void {
    committed = false;
    applied = 0;
    try {
      if (handle !== null) {
        const frames = handle.read();
        applied = store.applyFrames(frames);
        if (frames.some((f) => f.kind === "snap")) {
          clearBudget();
          backfill(); // BQ-9: after each snapshot, a reconnect's included
        }
        if (handle.effective !== effective) {
          effective = handle.effective; // only a `sub_ok` or a `ctl_ok` makes a new one
          store.setEffective(effective);
        }
      }
      if (queue.length > 0) {
        const slice = queue.splice(0, Math.max(0, APPLY_SLICE - applied));
        store.applyRest(slice);
        applied += slice.length;
      }
      if (store.takeNarrowed()) {
        narrowing = true;
        loadAccounts(true); // 23 §9.5: the directory says who left
      }
      if (store.takeSettled()) {
        narrowing = false;
        directoryLost = false;
        showLost();
        backfill(); // and REST brings back who stayed
      }
      store.setLink(!isDown(client.getState()));
      const at = now();
      if (store.commit(at - lastCommit < COMMIT_INTERVAL_MS)) {
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
    if ((!committed && applied === 0) || perf === null || perf === undefined) return;
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
      // Retry reads again what failed (a read, the directory) and makes a failed feed again; a live
      // feed never is made again, as the frames it has not read yet would be lost
      const { status } = store.getSnapshot();
      const lost = { read: readLost, directory: directoryLost };
      const asked = store.readSignal(); // aborted below when this Retry starts the reads afresh
      readLost = false; // as `markRetrying` clears the line: a read that fails again sets it
      directoryLost = false;
      store.markRetrying();
      if (asked.aborted) queue.length = 0; // the answers still waiting were read before it
      if (lost.read) readRest();
      if (accountIds === null) loadAccounts();
      else {
        if (lost.directory) loadAccounts(true);
        if (status === "snapshot_failed" || status === "revoked") subscribe(accountIds);
      }
    },
    stop() {
      if (stopped) return;
      stopped = true;
      abort.abort();
      if (owed !== undefined) timers.clearTimeout(owed);
      scheduler.stop();
      release();
      store.setStarted(false);
      store.commit();
    },
  };
}
