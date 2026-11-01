/**
 * The Working-orders tab's feed (E29-S02 #912): it fills `ordersStore`.
 *
 * - **WS** (`23` §6.2.3): `consume({ ch: "orders", opts: { exchange_account_ids }, priority:
 *   "private" })` for the caller's directory (`listExchangeAccounts`, scoped by the server), at
 *   most 25 accounts (`23` §13.5). No `open_only` (BQ-14): an order's final frame must arrive, so
 *   the row can linger with its word.
 * - **Every animation frame** (BQ-14, ruled: no 10 Hz tick for `orders`, which is never throttled,
 *   `23` §6.2): the handle is drained (`read()`, never per arrival, C9), the store applies each
 *   frame O(1) per item into its keyed map, ends the lingers that are due and commits once. A
 *   frame-paced blotter is not a hot path (C-2.20).
 * - **Marks:** the scheduler's `state.apply` and `paint` marks, and between them a
 *   `performance.measure` named `ws_frame_apply_seconds` with `detail.topic` `"orders"` for every
 *   frame that applied a frame (in milliseconds, as every measure is; G-W2's transport makes it
 *   seconds, as the positions feed's).
 * - **REST** (BQ-6): one `listOrders?open_only=true` at first paint and one after each `snap`, a
 *   reconnect's included, never on a timer. Only the newest read applies; a complete one (not
 *   truncated) also settles the held and untracked rows the snapshot carried (`ordersStore.ts`).
 * - **S-02:** no first `snap` within 5 s, or a refused subscription, is "Could not load";
 *   `retry()` re-subscribes. A narrowing (`23` §9.5) re-reads the directory, as the positions feed
 *   does, and the subscription is made again only when the directory changed. Not covered, as in
 *   the positions feed: an account that leaves the subscription but stays listed
 *   (`account_disabled`, `key_revoked`) is not named, because the directory still lists it; its
 *   rows leave with the narrowing and no "No longer shown" line follows (fail-safe: none stays).
 */
import { useEffect } from "react";
import type { ConsumerSpec, TopicHandle, WsClient } from "../../../lib/ws/api";
import {
  createFrameScheduler,
  type FrameMark,
  type FrameScheduler,
} from "../../../lib/ws/client/frameScheduler";
import type { WsState } from "../../../lib/ws/state/types";
import { MAX_ACCOUNT_IDS } from "../api";
import { accountInfo, type AccountInfo } from "../model/rowMapping";
import {
  APPLY_MEASURE,
  POSITIONS_PANE_ID,
  type FeedTimers,
  type PerformanceLike,
} from "../wsPositions";
import { ordersApi, type OrdersApi } from "./api";
import type { OrdersStore } from "./ordersStore";

/** S-02's budget, the Positions tab's (#911 BQ-18): no first `snap` in it is "Could not load". */
export const SNAPSHOT_BUDGET_MS = 5_000;
/** The panel's pane (C8): the orders subscription belongs to SCR-063, as the positions one does. */
export const ORDERS_PANE_ID = POSITIONS_PANE_ID;
export { APPLY_MEASURE };
export const MARK_PREFIX = "cv.orders.";
/** At most this many measures stay in the page's timeline (C-2.18); past it they are cleared. */
export const MAX_MEASURES = 1_000;

export interface OrdersFeedOptions {
  readonly client: Pick<WsClient, "consume" | "getState" | "subscribe">;
  readonly store: OrdersStore;
  readonly api?: OrdersApi | undefined;
  readonly timers?: Pick<FeedTimers, "setTimeout" | "clearTimeout"> | undefined;
  readonly raf?: ((callback: (frameTimeMs: number) => void) => number) | undefined;
  readonly caf?: ((handle: number) => void) | undefined;
  /** Monotonic ms for the marks and the linger; defaults to `performance.now`. */
  readonly now?: (() => number) | undefined;
  /** Epoch ms for a REST read's "as of"; defaults to `Date.now`. */
  readonly wall?: (() => number) | undefined;
  /** `null` turns the marks off; defaults to `globalThis.performance`. */
  readonly performance?: PerformanceLike | null | undefined;
  readonly paneId?: string | undefined;
  /** The measures kept at most; defaults to `MAX_MEASURES`. */
  readonly maxMeasures?: number | undefined;
}

export interface OrdersFeed {
  /** S-02's Retry: re-reads the directory if it failed, else re-subscribes. */
  retry(): void;
  stop(): void;
}

const platformTimers: Pick<FeedTimers, "setTimeout" | "clearTimeout"> = {
  setTimeout: (callback, ms) => setTimeout(callback, ms),
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** The link is down from the loss of an `up` link until the next `auth_ok`, and while offline. */
const isDown = (state: Pick<WsState, "link" | "outage">): boolean =>
  state.outage !== null || state.link.kind === "offline";

export function startOrdersFeed(options: OrdersFeedOptions): OrdersFeed {
  const { client, store } = options;
  const api = options.api ?? ordersApi;
  const timers = options.timers ?? platformTimers;
  const now = options.now ?? ((): number => performance.now());
  const wall = options.wall ?? ((): number => Date.now());
  const perf = options.performance === undefined ? globalThis.performance : options.performance;
  const paneId = options.paneId ?? ORDERS_PANE_ID;
  const abort = new AbortController();
  let stopped = false;
  let accountIds: readonly string[] | null = null;
  let orders: TopicHandle | null = null;
  let budget: unknown;
  /** The newest REST read: an older one that lands later never applies over it. */
  let restSeq = 0;
  let applied = 0;
  let applyStart = 0;
  let measures = 0;
  let scheduler: FrameScheduler<true> | null = null;

  function clearBudget(): void {
    if (budget !== undefined) timers.clearTimeout(budget);
    budget = undefined;
  }

  function release(): void {
    clearBudget();
    orders?.release();
    orders = null;
  }

  function subscribe(ids: readonly string[]): void {
    release();
    if (stopped || ids.length === 0) return; // an empty list is `invalid_options` (23 §6.2)
    store.setOverCap(ids.slice(MAX_ACCOUNT_IDS));
    const spec: ConsumerSpec = {
      ch: "orders",
      paneId,
      priority: "private",
      opts: { exchange_account_ids: ids.slice(0, MAX_ACCOUNT_IDS) },
    };
    orders = client.consume(spec);
    budget = timers.setTimeout(() => {
      budget = undefined;
      store.markSnapshotFailed();
    }, SNAPSHOT_BUDGET_MS);
  }

  /** One `listOrders?open_only=true`; past the cap it names the 25 the subscription does. */
  function readRest(): void {
    restSeq += 1;
    const seq = restSeq;
    const named =
      accountIds !== null && accountIds.length > MAX_ACCOUNT_IDS
        ? { accountIds: accountIds.slice(0, MAX_ACCOUNT_IDS) }
        : {};
    void api.listOrders({ ...named, openOnly: true }, abort.signal).then((outcome) => {
      if (stopped || seq !== restSeq || outcome.kind !== "ok") return;
      // a truncated read cannot say an order closed: it settles nothing
      store.applyRest(outcome.items, wall(), outcome.truncated ? undefined : now());
    });
  }

  function loadAccounts(narrowed = false): void {
    void api.listExchangeAccounts(abort.signal).then((outcome) => {
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

  /**
   * One animation frame's work. The next frame is asked for in `finally`: a throw here (a store
   * listener's, say) is reported by the frame that raised it, and the feed keeps draining.
   */
  function drain(): void {
    try {
      applied = 0;
      if (orders !== null) {
        const frames = orders.read();
        applied = frames.length;
        store.applyFrames(frames, now());
        if (frames.some((f) => f.kind === "snap")) {
          clearBudget();
          readRest(); // BQ-6: after each snapshot, a reconnect's included
        }
        store.setEffective(orders.effective);
      }
      store.expire(now());
      if (store.takeNarrowed()) loadAccounts(true); // 23 §9.5: the directory says who left
      store.setLink(!isDown(client.getState()));
      store.commit();
    } finally {
      if (!stopped) scheduler?.post("frame", true); // the next animation frame drains again
    }
  }

  /** The marks and the measure for a frame that applied frames (an idle frame writes nothing). */
  function mark(name: FrameMark, atMs: number): void {
    if (name === "state.apply") {
      applyStart = atMs;
      return;
    }
    if (applied === 0 || perf === null || perf === undefined) return;
    try {
      perf.mark(`${MARK_PREFIX}state.apply`, { startTime: applyStart });
      perf.mark(`${MARK_PREFIX}paint`, { startTime: atMs });
      perf.measure(APPLY_MEASURE, { start: applyStart, end: atMs, detail: { topic: "orders" } });
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

  scheduler = createFrameScheduler<true>({
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
      scheduler?.stop();
      release();
      store.setStarted(false);
      store.commit();
    },
  };
}

/**
 * The feed for as long as the host is mounted: started on mount, stopped on unmount, which releases
 * the `orders` subscription (`30-frontend-react.md`: every subscription has a teardown).
 */
export function useOrdersFeed(
  client: OrdersFeedOptions["client"],
  store: OrdersStore,
  api?: OrdersApi,
): void {
  useEffect(() => {
    const feed = startOrdersFeed({ client, store, api });
    return () => feed.stop();
  }, [client, store, api]);
}
