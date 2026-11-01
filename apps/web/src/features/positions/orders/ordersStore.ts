/**
 * The Working-orders tab's store (E29-S02 #912): a `useSyncExternalStore` store, the positions
 * store's pattern (#911 BQ-19), holding one row per order in a map keyed by order id, so a frame's
 * apply is O(1) per item (`23` §6.2: `orders` is never throttled, BQ-14).
 *
 * - **`23` §15.** An item older than the held one (`updated_at_ms`) is dropped; an equal one
 *   replaces it. A frame's `removed` ids apply after its upserts. A removed or ended order is
 *   remembered with its stamp (bounded), across snapshots, so a late item never brings it back.
 * - **The linger (D01 D13 d).** An order that ends, or whose id arrives in `removed`, stays in
 *   place with its word ("Filled", "Cancelled") for `LINGER_MS`, then leaves. The focused row
 *   never leaves while it has focus (`05` §3.4.3); it goes once focus moves off it.
 * - **Held and untracked (BQ-6).** The topic lists both as `removed` (neither is in the OMS's open
 *   set) and its snapshot never carries them, yet they are shown, not managed (S9): such a row
 *   stays when its id is removed, and REST supplies the ones WS has not sent.
 * - **REST, the side map (BQ-6).** `listOrders?open_only=true`, read at first paint and after each
 *   snapshot (`wsOrders.ts`), never on a timer. Before the first snapshot its rows are the view;
 *   after it, only its held and untracked rows are shown, while WS does not hold their id. Each
 *   read also gives the orders' creation constants (`created_at`, `provenance`,
 *   `trade_group_id`), kept per id; they never override WS state or terms.
 * - **Resets.** `revoked` and `narrowed` drop the accounts' rows at once from every cache, the
 *   linger and focus notwithstanding (SR-E29-11; E29-D05: the security rule wins), and a revoked
 *   account gets its "No longer shown" line. Any other reset voids the baseline: the rows shown
 *   stay as the last good view, no delta extends it, and the next `snap` replaces it.
 * - **Commits.** Inputs only mark the store dirty; `commit()`, which the feed calls once per
 *   animation frame, publishes one snapshot. The default order is kept between commits and sorted
 *   again only when the set of rows or a sort key changes, so a frame of updates is O(rows).
 */
import { useSyncExternalStore } from "react";
import type { TopicFrame } from "../../../lib/ws/api";
import type { DataBody } from "../../../lib/ws/protocol/codec";
import { isUuid, type AccountInfo } from "../model/rowMapping";
import type { Withdrawn } from "../positionsStore";
import {
  constantsOf,
  mapOrder,
  NO_CONSTANTS,
  orderIdOf,
  stateOfItem,
  UNOWNED,
  type OrderConstants,
  type OrderRowModel,
  type RestOrder,
  type WsOrder,
} from "./model/orderRow";
import { compareOrders } from "./model/sections";

export type OrdersFeedStatus =
  | "idle"
  | "loading"
  | "live"
  | "resyncing"
  | "offline"
  | "snapshot_failed"
  | "revoked"
  | "no_accounts";

export type OrdersViewSource = "none" | "rest" | "ws" | "last_good";

export interface OrdersSnapshot {
  readonly status: OrdersFeedStatus;
  readonly source: OrdersViewSource;
  /** When the rows shown were current: the newest frame's `ts`, or a REST read's receipt. */
  readonly asOfMs: number | null;
  /** Every shown order in D01 D13 (a)'s default order (`model/sections.ts` groups them). */
  readonly rows: readonly OrderRowModel[];
  /** Rows that ended and linger, with the time each leaves (D01 D13 d). */
  readonly lingering: ReadonlyMap<string, number>;
  readonly focusedId: string | null;
  readonly accounts: readonly AccountInfo[];
  readonly accountsLoaded: boolean;
  readonly withdrawn: readonly Withdrawn[];
  /** Accounts past the 25 an `orders` subscription may name (`23` §13.5): not shown live. */
  readonly overCap: readonly string[];
  readonly version: number;
}

/** D01 D13 (d): a terminal order stays in place about 5 s. */
export const LINGER_MS = 5_000;
/** The removed orders a store remembers (C-2.18): past it the oldest is forgotten first. */
export const MAX_TOMBSTONES = 1_024;
/** The orders whose creation constants are kept (C-2.18): past it the oldest is forgotten first. */
export const MAX_CONSTANTS = 4_096;
const MAX_WITHDRAWN = 64;

const EMPTY: OrdersSnapshot = Object.freeze({
  status: "idle",
  source: "none",
  asOfMs: null,
  rows: [],
  lingering: new Map(),
  focusedId: null,
  accounts: [],
  accountsLoaded: false,
  withdrawn: [],
  overCap: [],
  version: 0,
});

const isRecord = (v: unknown): v is Readonly<Record<string, unknown>> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** The `orders` payload of a structured body, or `null` (a binary body carries no orders). */
function payloadOf(
  body: DataBody,
): { orders: readonly unknown[]; removed: readonly unknown[] } | null {
  if (body.e !== "j" || !isRecord(body.p) || !Array.isArray(body.p["orders"])) return null;
  const removed = body.p["removed"];
  return { orders: body.p["orders"], removed: Array.isArray(removed) ? removed : [] };
}

/** `23` §13 `epochMs`: a safe, non-negative integer, else `null`. */
const epochMs = (v: unknown): number | null =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : null;
const stampOf = (item: unknown): number | null =>
  epochMs(isRecord(item) ? item["updated_at_ms"] : undefined);
const accountOf = (item: unknown): string | null => {
  const account = isRecord(item) ? item["exchange_account_id"] : undefined;
  return isUuid(account) ? account.toLowerCase() : null;
};
const unowned = (item: unknown): boolean => {
  const { lifecycle } = stateOfItem(item);
  return lifecycle !== null && UNOWNED.has(lifecycle);
};

export interface OrdersStore {
  getSnapshot(): OrdersSnapshot;
  subscribe(listener: () => void): () => void;
  /** The feed started (`loading`) or stopped (`idle`, every cache dropped). */
  setStarted(started: boolean): void;
  /** The account directory, `null` when its read failed. */
  setAccounts(accounts: readonly AccountInfo[] | null): void;
  /**
   * A `listOrders?open_only=true` read (BQ-6): it replaces the last read whole, and its constants
   * are kept. Ignored while revoked; a withdrawn, narrowed-away or over-cap account brings no row.
   */
  applyRest(items: readonly RestOrder[], atMs: number): void;
  /** What the `orders` handle's `read()` returned, in order; `nowMs` starts each linger. */
  applyFrames(frames: readonly TopicFrame[], nowMs: number): void;
  /** Ends each linger that is due, the focused row's excepted. */
  expire(nowMs: number): void;
  /** The row that has focus, which never leaves while it has it (`null`: none). */
  setFocused(orderId: string | null): void;
  /** The subscription's effective options (C4): an account it no longer names leaves at once. */
  setEffective(effective: Readonly<Record<string, unknown>>): void;
  setLink(up: boolean): void;
  /** S-02: no first `snap` within the budget, or the subscription refused before one. */
  markSnapshotFailed(): void;
  /** Retry re-subscribes (S-02): back to loading, the failure cleared. */
  markRetrying(): void;
  /** Accounts past the 25 a subscription names: never shown live, so their rows leave, unnamed. */
  setOverCap(accountIds: readonly string[]): void;
  /** Whether a narrowing came since the last call (taken once): the feed re-reads the directory. */
  takeNarrowed(): boolean;
  dismissWithdrawn(accountId: string): void;
  /** Publishes one snapshot when anything changed; `true` when it did. */
  commit(): boolean;
}

export function createOrdersStore(): OrdersStore {
  let snapshot = EMPTY;
  const listeners = new Set<() => void>();
  let dirty = false;
  /** The set of rows or a sort key changed: the default order is sorted again at the commit. */
  let resort = true;
  let started = false;

  let directory: Map<string, AccountInfo> | null = null;
  /** The WS view: every order the baseline and its deltas hold, ended ones while they linger. */
  let ws = new Map<string, WsOrder>();
  /** Removed and ended orders' ids, with the stamp they left at, across baselines (`23` §15). */
  let tombs = new Map<string, number>();
  /** id -> when it leaves: an ended order's linger, oldest first. */
  let lingers = new Map<string, number>();
  let wsBaseline = false;
  let everSnapped = false;
  let wsAsOf: number | null = null;
  let rest: { rows: Map<string, RestOrder>; asOfMs: number } | null = null;
  /** BQ-6's creation constants per id; the `created` frame's stamp in its own map. */
  let constants = new Map<string, OrderConstants>();
  let createdStamps = new Map<string, number>();
  /** The two merged per id, kept so a row's mapping is reused until one of them changes. */
  const merged = new Map<string, OrderConstants>();
  let focusedId: string | null = null;
  let linkUp = true;
  let snapshotFailed = false;
  let revoked = false;
  let pendingNarrowing: Set<string> | null = null;
  let narrowed = false;
  let withdrawn: Withdrawn[] = [];
  let overCap: readonly string[] = [];
  const mapped = new Map<
    string,
    { wire: WsOrder | RestOrder; kept: OrderConstants; dir: unknown; row: OrderRowModel | null }
  >();
  let order: readonly string[] = [];
  /** Bumped when the set of rows changes; `setEffective` re-checks only then or on a new list. */
  let membership = 0;
  let effectiveSeen: unknown = null;
  let membershipSeen = -1;

  const touch = (sorted = false): void => {
    dirty = true;
    if (sorted) {
      resort = true;
      membership += 1;
    }
  };

  const accountOfId = (id: string): string | null => {
    const held = ws.get(id) ?? rest?.rows.get(id);
    return held === undefined ? null : accountOf(held);
  };

  function tomb(id: string, stamp: number): void {
    tombs.delete(id); // the newest removal goes last, so the oldest is forgotten first
    tombs.set(id, Math.max(stamp, tombs.get(id) ?? -1));
    if (tombs.size > MAX_TOMBSTONES) {
      const oldest = tombs.keys().next();
      if (oldest.done !== true) tombs.delete(oldest.value);
    }
  }

  function keep(id: string, next: OrderConstants): void {
    constants.delete(id);
    constants.set(id, next);
    merged.delete(id);
    if (constants.size > MAX_CONSTANTS) {
      const oldest = constants.keys().next();
      if (oldest.done !== true) constants.delete(oldest.value);
    }
  }

  /** The constants a row maps with: REST's, its creation time else the `created` frame's stamp. */
  function constantsFor(id: string): OrderConstants {
    const cached = merged.get(id);
    if (cached !== undefined) return cached;
    const kept = constants.get(id) ?? NO_CONSTANTS;
    const stamp = createdStamps.get(id);
    const out =
      kept.createdAtMs !== null || stamp === undefined ? kept : { ...kept, createdAtMs: stamp };
    merged.set(id, out);
    return out;
  }

  /** An order's per-id state leaves with it: its linger, its creation stamp, its cached row. */
  function forget(id: string): void {
    lingers.delete(id);
    createdStamps.delete(id);
    merged.delete(id);
    mapped.delete(id);
  }

  function startLinger(id: string, nowMs: number): void {
    if (!lingers.has(id)) lingers.set(id, nowMs + LINGER_MS);
  }

  /** An order leaves the WS view now, remembered with its stamp so a late item stays out. */
  function leave(id: string): void {
    const wire = ws.get(id);
    ws.delete(id);
    forget(id);
    tomb(id, stampOf(wire) ?? 0); // a held item always has one (`upsert`)
    touch(true);
  }

  function upsert(item: unknown, nowMs: number): void {
    const id = orderIdOf(item);
    const stamp = stampOf(item);
    if (id === null || stamp === null) return; // `23` §15.1 requires both: a malformed item goes
    const held = ws.get(id);
    if (held !== undefined && stamp < held.updated_at_ms) return; // older: discarded (23 §15)
    const removedAt = tombs.get(id);
    if (held === undefined && removedAt !== undefined && stamp <= removedAt) return; // late
    if (accountOf(item) === null) return; // the server scopes the topic; an item names its account
    ws.set(id, item as WsOrder);
    tombs.delete(id);
    if (held === undefined) touch(true);
    if (isRecord(item) && item["change"] === "created" && !createdStamps.has(id)) {
      createdStamps.set(id, stamp);
      merged.delete(id);
      touch(true);
    }
    if (stateOfItem(item).terminal) startLinger(id, nowMs);
    else if (lingers.delete(id)) touch(true);
  }

  /**
   * A `removed` id: the row lingers, then leaves; a held or untracked row stays, shown and not
   * managed (BQ-6). An id WS never held still supersedes REST's row of it.
   */
  function removeId(id: string, nowMs: number, ts: number): void {
    const wire = ws.get(id);
    if (wire === undefined) {
      if (rest?.rows.has(id) === true) {
        tomb(id, ts);
        touch(true);
      }
      return;
    }
    if (!unowned(wire)) startLinger(id, nowMs);
  }

  /** The accounts no read may bring rows back for. */
  function barred(): Set<string> {
    return new Set([...withdrawn.map((w) => w.accountId), ...(pendingNarrowing ?? []), ...overCap]);
  }

  function heldAccounts(): Set<string> {
    const accounts = new Set<string>();
    for (const wire of ws.values()) {
      const account = accountOf(wire);
      if (account !== null) accounts.add(account);
    }
    for (const wire of rest?.rows.values() ?? []) {
      const account = accountOf(wire);
      if (account !== null) accounts.add(account);
    }
    return accounts;
  }

  function labelOf(accountId: string): string | null {
    return directory?.get(accountId)?.label ?? null;
  }

  function noteWithdrawn(accountIds: Iterable<string>): void {
    for (const accountId of accountIds) {
      if (withdrawn.some((w) => w.accountId === accountId)) continue;
      withdrawn = [...withdrawn, { accountId, label: labelOf(accountId) }].slice(-MAX_WITHDRAWN);
    }
  }

  /** SR-E29-11: an account's rows leave every cache now, the linger and focus notwithstanding. */
  function dropAccounts(accountIds: ReadonlySet<string>): void {
    if (accountIds.size === 0) return;
    const gone = (wire: unknown): boolean => {
      const account = accountOf(wire);
      return account !== null && accountIds.has(account);
    };
    for (const [id, wire] of [...ws]) {
      if (!gone(wire)) continue;
      ws.delete(id);
      constants.delete(id);
      forget(id);
    }
    if (rest !== null) {
      for (const [id, wire] of [...rest.rows]) {
        if (!gone(wire)) continue;
        rest.rows.delete(id);
        constants.delete(id);
        forget(id);
      }
    }
    if (focusedId !== null && accountOfId(focusedId) === null) focusedId = null;
    touch(true);
  }

  function applySnap(bodies: readonly DataBody[], ts: number, nowMs: number): void {
    const before = ws;
    ws = new Map();
    for (const body of bodies) {
      const payload = payloadOf(body);
      if (payload === null) continue;
      for (const item of payload.orders) upsert(item, nowMs);
    }
    // The snapshot holds open orders only: a held or untracked row, a lingering one and the
    // focused one stay; any other order it does not list is gone (`23` §6.2.3).
    for (const [id, wire] of before) {
      if (ws.has(id)) continue;
      if (unowned(wire) || lingers.has(id)) ws.set(id, wire);
      else if (id === focusedId) {
        ws.set(id, wire);
        startLinger(id, nowMs);
      } else {
        forget(id);
      }
    }
    if (pendingNarrowing !== null) {
      // a narrowing's `snap` is built under the new scope (`23` §9.5): an account it serves stayed
      for (const wire of ws.values()) {
        const account = accountOf(wire);
        if (account !== null) pendingNarrowing.delete(account);
      }
      if (pendingNarrowing.size === 0) pendingNarrowing = null;
    }
    wsBaseline = true;
    everSnapped = true;
    snapshotFailed = false;
    revoked = false;
    wsAsOf = ts;
    touch(true);
  }

  function applyDelta(body: DataBody, ts: number, nowMs: number): void {
    if (!wsBaseline) return; // the client never extends a void baseline (23 §7.1)
    const payload = payloadOf(body);
    if (payload === null) return;
    for (const item of payload.orders) upsert(item, nowMs);
    for (const id of payload.removed) {
      if (typeof id === "string") removeId(id.toLowerCase(), nowMs, ts); // after the upserts
    }
    wsAsOf = Math.max(wsAsOf ?? ts, ts);
    touch();
  }

  function applyReset(reason: string): void {
    if (reason === "narrowed" || reason === "revoked") {
      const held = heldAccounts();
      dropAccounts(held); // every row: which accounts left is not known yet (security first)
      ws = new Map();
      tombs = new Map(); // ids of accounts that may have left: the next `snap` says what is open
      lingers = new Map();
      createdStamps = new Map();
      merged.clear();
      rest = null;
      wsBaseline = false;
      focusedId = null;
      if (reason === "revoked") {
        if (everSnapped) {
          revoked = true;
          noteWithdrawn([...held, ...(pendingNarrowing ?? [])]);
          pendingNarrowing = null;
          narrowed = false; // ended: nothing is re-read or re-made until Retry
        } else {
          snapshotFailed = true; // refused before any snapshot (S-02)
        }
      } else {
        pendingNarrowing = new Set([...(pendingNarrowing ?? []), ...held]);
        narrowed = true;
      }
      return;
    }
    // gap, malformed, overflow, resnapshot, reconnect, unsubscribed: the baseline is void and the
    // rows shown stay as the last good view until the next `snap` (never extended by a delta)
    wsBaseline = false;
    touch();
  }

  /** The order ids the view shows now: WS's, and REST's that WS does not hold (BQ-6). */
  function shownIds(): string[] {
    const ids: string[] = [];
    if (everSnapped || wsBaseline) {
      for (const id of ws.keys()) ids.push(id);
      for (const [id, wire] of rest?.rows ?? []) {
        if (!ws.has(id) && !tombs.has(id) && unowned(wire)) ids.push(id);
      }
      return ids;
    }
    for (const id of rest?.rows.keys() ?? []) if (!tombs.has(id)) ids.push(id);
    return ids;
  }

  function rowOf(id: string, dir: ReadonlyMap<string, AccountInfo>): OrderRowModel | null {
    const fromWs = ws.get(id);
    const wire = fromWs ?? rest?.rows.get(id);
    if (wire === undefined) return null;
    const kept = constantsFor(id);
    let entry = mapped.get(id);
    if (
      entry === undefined ||
      entry.wire !== wire ||
      entry.kept !== kept ||
      entry.dir !== directory
    ) {
      const row = mapOrder(wire, fromWs !== undefined ? "ws" : "rest", dir, kept);
      entry = { wire, kept, dir: directory, row };
      mapped.set(id, entry);
    }
    return entry.row;
  }

  function statusOf(): OrdersFeedStatus {
    if (!started) return "idle";
    if (directory !== null && directory.size === 0) return "no_accounts";
    if (snapshotFailed) return "snapshot_failed";
    if (revoked) return "revoked";
    if (!linkUp) return "offline";
    if (wsBaseline) return "live";
    if (everSnapped) return "resyncing";
    return "loading";
  }

  function sourceOf(): OrdersViewSource {
    if (wsBaseline) return "ws";
    if (everSnapped) return "last_good";
    return rest === null ? "none" : "rest";
  }

  function build(): OrdersSnapshot {
    const dir = directory ?? new Map<string, AccountInfo>();
    if (resort) {
      // hidden rows (`draft`, `validated`) keep their place too, so one that starts sending shows
      // in place without a sort
      const all: OrderRowModel[] = [];
      for (const id of shownIds()) {
        const row = rowOf(id, dir);
        if (row !== null) all.push(row);
      }
      all.sort(compareOrders);
      order = all.map((r) => r.id);
      const live = new Set(order);
      for (const id of [...mapped.keys()]) if (!live.has(id)) mapped.delete(id);
      for (const id of [...merged.keys()]) if (!live.has(id)) merged.delete(id);
      resort = false;
    }
    const rows: OrderRowModel[] = [];
    for (const id of order) {
      const row = rowOf(id, dir);
      if (row !== null && !row.state.hidden) rows.push(row);
    }
    const asOfMs = wsBaseline || everSnapped ? wsAsOf : (rest?.asOfMs ?? null);
    return Object.freeze({
      status: statusOf(),
      source: sourceOf(),
      asOfMs,
      rows,
      lingering: new Map(lingers),
      focusedId,
      accounts: [...dir.values()],
      accountsLoaded: directory !== null,
      withdrawn,
      overCap,
      version: snapshot.version + 1,
    });
  }

  return {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    setStarted(next) {
      if (next === started) return;
      started = next;
      if (!next) {
        directory = null;
        ws = new Map();
        tombs = new Map();
        lingers = new Map();
        wsBaseline = false;
        everSnapped = false;
        wsAsOf = null;
        rest = null;
        constants = new Map();
        createdStamps = new Map();
        merged.clear();
        focusedId = null;
        linkUp = true;
        snapshotFailed = false;
        revoked = false;
        pendingNarrowing = null;
        narrowed = false;
        withdrawn = [];
        overCap = [];
        mapped.clear();
      }
      touch(true);
    },
    setAccounts(accounts) {
      if (accounts === null) {
        if (directory === null) snapshotFailed = true; // no directory, nothing to subscribe to
        touch();
        return;
      }
      const next = new Map(accounts.map((a) => [a.id, a]));
      const gone = new Set<string>();
      for (const id of directory?.keys() ?? []) if (!next.has(id)) gone.add(id);
      const named = new Set([...heldAccounts(), ...(pendingNarrowing ?? [])]);
      noteWithdrawn([...gone].filter((id) => named.has(id)));
      directory = next;
      dropAccounts(gone);
      pendingNarrowing = null; // the directory settles a narrowing: the candidates it lists stayed
      if (accounts.length > 0 && snapshotFailed && !everSnapped && rest === null)
        snapshotFailed = false;
      touch(true);
    },
    applyRest(items, atMs) {
      if (revoked) return; // nothing is read back until Retry (SR-E29-11)
      const out = barred();
      const rows = new Map<string, RestOrder>();
      for (const item of items) {
        const id = orderIdOf(item);
        const account = accountOf(item);
        // a read that set out before a withdrawal or a narrowing brings none of their rows back
        if (id === null || account === null || out.has(account)) continue;
        rows.set(id, item);
        keep(id, constantsOf(item));
      }
      rest = { rows, asOfMs: atMs };
      touch(true);
    },
    applyFrames(frames, nowMs) {
      for (const frame of frames) {
        if (frame.kind === "reset") applyReset(frame.reason);
        else if (frame.kind === "snap") applySnap(frame.bodies, frame.ts, nowMs);
        else applyDelta(frame.body, frame.ts, nowMs);
      }
      if (frames.length > 0) touch();
    },
    expire(nowMs) {
      for (const [id, leaveAt] of [...lingers]) {
        if (leaveAt > nowMs || id === focusedId) continue;
        leave(id);
      }
    },
    setFocused(orderId) {
      const next = orderId === null ? null : orderId.toLowerCase();
      if (next === focusedId) return;
      focusedId = next;
      touch();
    },
    setEffective(effective) {
      // the feed asks every frame: the scan below runs on a new list or a changed set of rows only
      if (effective === effectiveSeen && membership === membershipSeen) return;
      effectiveSeen = effective;
      membershipSeen = membership;
      const ids = effective["exchange_account_ids"];
      if (!Array.isArray(ids) || !ids.every(isUuid)) return; // no `sub_ok` yet: nothing narrowed
      const scope = new Set([...ids.map((id) => id.toLowerCase()), ...overCap]); // never withdrawn
      const out = new Set(
        [...heldAccounts(), ...(pendingNarrowing ?? [])].filter((id) => !scope.has(id)),
      );
      if (out.size === 0) return;
      noteWithdrawn(out);
      dropAccounts(out);
      if (pendingNarrowing === null) return;
      for (const id of out) pendingNarrowing.delete(id);
      if (pendingNarrowing.size === 0) pendingNarrowing = null;
    },
    setLink(up) {
      if (up === linkUp) return;
      linkUp = up;
      touch();
    },
    markSnapshotFailed() {
      if (wsBaseline || snapshotFailed) return;
      snapshotFailed = true;
      touch();
    },
    markRetrying() {
      snapshotFailed = false;
      revoked = false;
      touch();
    },
    setOverCap(accountIds) {
      if (accountIds.length === overCap.length && accountIds.every((id, i) => overCap[i] === id))
        return;
      overCap = [...accountIds];
      dropAccounts(new Set(overCap)); // a first-paint read set out before the cap was known
      touch(true);
    },
    takeNarrowed() {
      const owed = narrowed;
      narrowed = false;
      return owed;
    },
    dismissWithdrawn(accountId) {
      const next = withdrawn.filter((w) => w.accountId !== accountId);
      if (next.length === withdrawn.length) return;
      withdrawn = next;
      touch();
    },
    commit() {
      if (!dirty) return false;
      dirty = false;
      snapshot = build();
      for (const listener of [...listeners]) listener();
      return true;
    },
  };
}

/** One selected value of the store; re-renders when the selection changes (by `Object.is`). */
export function useOrders<T>(store: OrdersStore, select: (s: OrdersSnapshot) => T): T {
  const read = (): T => select(store.getSnapshot());
  return useSyncExternalStore(store.subscribe, read, read);
}
