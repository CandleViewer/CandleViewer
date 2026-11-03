/**
 * The Fills tab's store (E29-S04 #979): a `useSyncExternalStore` store, the positions store's
 * pattern (#911 BQ-19), holding one row per fill keyed (`exchange_account_id`, `exec_id`), the
 * database's own key (`21` `ux_exec_id`; D03:204).
 *
 * - **Sources (BQ-9).** A fill is one immutable stored row, so every source adds to one set: the
 *   WS snapshot and deltas and the REST backfill alike. A fill seen again (the normal WS/REST
 *   overlap, a re-snapshot) is not added: the first copy wins, and a member only the second
 *   carries is taken from it (REST's trade group, WS's environment; `mergeFill`). A fill is counted
 *   once, when the other source first brings it (`dedupeHits`: `exec_dedupe_hits_total`, in-page,
 *   G-W2), so a repeated backfill adds nothing. Applying an item is O(1): `executions` is never
 *   throttled (`23` §6.2.3, S4), so a frame's work never grows with the rows held.
 * - **Scope.** Once the directory is known, a fill of an account it does not list is refused, and
 *   the first one drops a first-paint read's fills of the others (SR-E29-11, in depth).
 * - **Order.** Newest first by fill time, then id: the server's keyset, so REST (newest first) and
 *   the WS snapshot (oldest first) merge into one order whatever their arrival.
 * - **Commits** are coalesced: inputs only mark the store dirty, and `commit()`, which the feed
 *   calls at most every 200 ms (5 Hz, D03 §3.9, `14`:1734), sorts the fills added since the last
 *   one and merges them in, O(rows), re-reading the committed rows through `held` only when a fill
 *   left or a copy merged since. A security reset is published at once (`commit(true)`).
 * - **Bounded** at `MAX_FILLS` (C-2.18): past it the oldest fills leave at the commit.
 * - **New fills (D01 D13 g).** While the list is scrolled away from its top (`setAtTop(false)`),
 *   fills newer than its top row are held back from `rows` and counted (`newCount`, the "3 new
 *   fills" pill): nothing moves. Back at the top they join; `all` holds them meanwhile (D-21).
 * - **Resets.** `revoked` and `narrowed` drop every fill at once (which accounts left is not known
 *   yet: security first, SR-E29-11), and a withdrawn account gets E29-D05 F-02's line; the
 *   directory, a narrowed `sub_ok` or the next snapshot settles who stayed (`takeSettled`), and
 *   REST brings their fills back. No read brings back a withdrawn, narrowed-away or over-cap
 *   account's fills. Any other reset voids the WS baseline and keeps the fills: they are records,
 *   and the next `snap` follows.
 */
import { useSyncExternalStore } from "react";
import type { TopicFrame } from "../../../lib/ws/api";
import type { DataBody } from "../../../lib/ws/protocol/codec";
import { isUuid, type AccountInfo } from "../model/rowMapping";
import type { FeedStatus, Withdrawn } from "../positionsStore";
import { mapFill, mergeFill, newestFirst, type FillRowModel } from "./model/fillRow";

/** The fills held at most (C-2.18): BQ-9's bound, five times the 1,000 a session tests. */
export const MAX_FILLS = 5_000;
const MAX_WITHDRAWN = 64;

export interface FillsSnapshot {
  readonly status: FeedStatus;
  /** The fills shown, newest first; the held-back new ones excluded. */
  readonly rows: readonly FillRowModel[];
  /** Every fill held, newest first, the held-back new ones included: the export's (D02 D-21). */
  readonly all: readonly FillRowModel[];
  /** Fills newer than the top row that arrived while the list was scrolled away. */
  readonly newCount: number;
  /** The fills both sources brought, each counted once. */
  readonly dedupeHits: number;
  readonly accounts: readonly AccountInfo[];
  readonly accountsLoaded: boolean;
  readonly withdrawn: readonly Withdrawn[];
  /** The newest WS frame's `ts`: `fills.offline`'s "As of" (D03 §3.7). */
  readonly asOfMs: number | null;
  /** The last REST read failed: D03:191's "Could not load" and Retry; the rows shown stay. */
  readonly readFailed: boolean;
  readonly version: number;
}

const EMPTY: FillsSnapshot = Object.freeze({
  status: "idle",
  rows: [],
  all: [],
  newCount: 0,
  dedupeHits: 0,
  accounts: [],
  accountsLoaded: false,
  withdrawn: [],
  asOfMs: null,
  readFailed: false,
  version: 0,
});

export interface FillsStore {
  getSnapshot(): FillsSnapshot;
  subscribe(listener: () => void): () => void;
  setStarted(started: boolean): void;
  /** The account directory, `null` when its read failed. */
  setAccounts(accounts: readonly AccountInfo[] | null): void;
  /** REST items, in any order (`listExecutions` pages). Ignored while revoked. */
  applyRest(items: readonly unknown[]): void;
  /** What the `executions` handle's `read()` returned, in order; returns the items they held. */
  applyFrames(frames: readonly TopicFrame[]): number;
  /** The subscription's effective options: an account it no longer names leaves (SR-E29-11). */
  setEffective(effective: Readonly<Record<string, unknown>>): void;
  setLink(up: boolean): void;
  markSnapshotFailed(): void;
  /** Whether the last REST read failed, or a page of it. */
  setReadFailed(failed: boolean): void;
  markRetrying(): void;
  /** Accounts past the 25 a subscription names (`23` §13.5): never live, so never shown. */
  setOverCap(accountIds: readonly string[]): void;
  /** Whether a narrowing came since the last call (taken once): the feed re-reads the directory. */
  takeNarrowed(): boolean;
  /** Whether a narrowing settled since the last call (taken once): REST brings back who stayed. */
  takeSettled(): boolean;
  /** The list is at its top (new fills join it) or scrolled away (they wait, counted). */
  setAtTop(atTop: boolean): void;
  dismissWithdrawn(accountId: string): void;
  /**
   * Publishes one snapshot when anything changed; `true` when it did. `onlyUrgent` (inside the
   * 200 ms window) publishes only a security reset, which SR-E29-11 clears at once.
   */
  commit(onlyUrgent?: boolean): boolean;
}

const isRecord = (v: unknown): v is Readonly<Record<string, unknown>> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

function itemsOf(body: DataBody): readonly unknown[] {
  if (body.e !== "j" || !isRecord(body.p)) return [];
  const items = body.p["executions"];
  return Array.isArray(items) ? items : [];
}

/** Two sorted (newest-first) lists as one, O(a + b). */
function merge(a: readonly FillRowModel[], b: readonly FillRowModel[]): FillRowModel[] {
  const out: FillRowModel[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    const x = a[i];
    const y = b[j];
    if (y === undefined || (x !== undefined && newestFirst(x, y) <= 0)) {
      if (x !== undefined) out.push(x);
      i += 1;
    } else {
      out.push(y);
      j += 1;
    }
  }
  return out;
}

export function createFillsStore(): FillsStore {
  let snapshot = EMPTY;
  const listeners = new Set<() => void>();
  let dirty = false;
  let started = false;
  const held = new Map<string, FillRowModel>();
  const perAccount = new Map<string, number>();
  let added: string[] = []; // the keys of the fills new since the last commit
  let sorted: FillRowModel[] = [];
  let stale = false; // a committed fill left `held`, or a copy merged: `sorted` is re-read
  let urgent = false; // a security reset waits to be published
  const crossed = new Set<string>(); // the fills both sources brought, each counted once (G-W2)
  let dedupeHits = 0;
  let directory: Map<string, AccountInfo> | null = null;
  let withdrawn: Withdrawn[] = [];
  let pending: Set<string> | null = null; // a narrowing's candidates, until the directory says
  let narrowed = false;
  let settled = false;
  let readFailed = false;
  let overCap: readonly string[] = [];
  let baseline = false;
  let everSnapped = false;
  let snapshotFailed = false;
  let revoked = false;
  let linkUp = true;
  let asOfMs: number | null = null;
  let atTop = true;
  let anchor: FillRowModel | null = null;

  const touch = (): void => {
    dirty = true;
  };

  function barred(accountId: string): boolean {
    return (
      directory?.has(accountId) === false ||
      pending?.has(accountId) === true ||
      overCap.includes(accountId) ||
      withdrawn.some((w) => w.accountId === accountId)
    );
  }

  /** One wire item: O(1). */
  function apply(item: unknown, source: "ws" | "rest"): void {
    if (!isRecord(item)) return;
    const row = mapFill(item as Parameters<typeof mapFill>[0], source);
    if (row === null || barred(row.accountId)) return;
    const first = held.get(row.key);
    if (first === undefined) {
      held.set(row.key, row);
      perAccount.set(row.accountId, (perAccount.get(row.accountId) ?? 0) + 1);
      added.push(row.key);
      touch();
      return;
    }
    if (first.source !== source && !crossed.has(row.key)) {
      crossed.add(row.key);
      dedupeHits += 1;
      touch();
    }
    const merged = mergeFill(first, row);
    if (merged === first) return;
    held.set(row.key, merged);
    stale = true;
    touch();
  }

  function noteWithdrawn(accountIds: Iterable<string>): void {
    for (const accountId of accountIds) {
      if (withdrawn.some((w) => w.accountId === accountId)) continue;
      const label = directory?.get(accountId)?.label ?? null;
      withdrawn = [...withdrawn, { accountId, label }].slice(-MAX_WITHDRAWN);
    }
  }

  /** SR-E29-11: the accounts' fills leave every cache now, and the next frame publishes it. */
  function dropAccounts(accountIds: ReadonlySet<string>): void {
    if (accountIds.size === 0) return;
    for (const [key, row] of held)
      if (accountIds.has(row.accountId)) {
        held.delete(key);
        crossed.delete(key);
      }
    for (const id of accountIds) perAccount.delete(id);
    added = added.filter((key) => held.has(key)); // a dropped key leaves: brought again, it is one
    stale = true;
    urgent = true;
    touch();
  }

  /** A narrowing settles once no candidate is left: REST then brings back who stayed. */
  function settle(done: boolean): void {
    if (pending === null || !done) return;
    pending = null;
    settled = true;
  }

  const heldAccounts = (): Set<string> => new Set(perAccount.keys());

  function applyReset(reason: string): void {
    baseline = false;
    if (reason !== "narrowed" && reason !== "revoked") return; // the fills stay: they are records
    urgent = true;
    const accounts = heldAccounts();
    dropAccounts(accounts);
    if (reason === "narrowed") {
      // every account the directory lists is a candidate, held fills or not: a read still in
      // flight must not bring one back before the directory or a snapshot says who stayed
      pending = new Set([...(pending ?? []), ...accounts, ...(directory?.keys() ?? [])]);
      narrowed = true;
    } else if (everSnapped) {
      revoked = true;
      noteWithdrawn([...accounts, ...(pending ?? [])]);
      pending = null;
      narrowed = false; // ended: nothing is re-read or re-made until Retry
    } else {
      snapshotFailed = true; // refused before any snapshot (S-02)
    }
  }

  function applyItems(items: readonly unknown[]): number {
    for (const item of items) apply(item, "ws");
    return items.length;
  }

  function status(): FeedStatus {
    if (!started) return "idle";
    if (directory !== null && directory.size === 0) return "no_accounts";
    if (snapshotFailed) return "snapshot_failed";
    if (revoked) return "revoked";
    if (!linkUp) return "offline";
    if (baseline) return "live";
    return everSnapped ? "resyncing" : "loading";
  }

  function build(): FillsSnapshot {
    // each new fill as held now, a merged copy's members in: `held` is the only source
    const fresh = added.flatMap((key) => held.get(key) ?? []).sort(newestFirst);
    let base = sorted;
    if (stale) {
      // the committed fills as held now: a dropped one gone, a merged one current, one dropped
      // and brought again in this window only in `fresh`, so each key is published once
      const keys = new Set(fresh.map((r) => r.key));
      base = sorted.flatMap((r) => (keys.has(r.key) ? [] : (held.get(r.key) ?? [])));
    }
    sorted = merge(fresh, base);
    added = [];
    stale = false;
    for (const row of sorted.splice(MAX_FILLS)) {
      held.delete(row.key);
      crossed.delete(row.key);
      const left = (perAccount.get(row.accountId) ?? 1) - 1;
      if (left > 0) perAccount.set(row.accountId, left);
      else perAccount.delete(row.accountId);
    }
    let newCount = 0;
    if (!atTop && anchor !== null) {
      const top = anchor;
      while (newCount < sorted.length && newestFirst(sorted[newCount] ?? top, top) < 0)
        newCount += 1;
    }
    return Object.freeze({
      status: status(),
      rows: newCount === 0 ? sorted : sorted.slice(newCount),
      all: sorted,
      newCount,
      dedupeHits,
      accounts: [...(directory ?? new Map<string, AccountInfo>()).values()],
      accountsLoaded: directory !== null,
      withdrawn,
      asOfMs,
      readFailed,
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
        held.clear();
        perAccount.clear();
        crossed.clear();
        added = [];
        sorted = [];
        directory = null;
        withdrawn = [];
        pending = null;
        narrowed = false;
        settled = false;
        readFailed = false;
        overCap = [];
        baseline = false;
        everSnapped = false;
        snapshotFailed = false;
        revoked = false;
        linkUp = true;
        asOfMs = null;
        anchor = null;
        atTop = true;
      }
      touch();
    },
    setAccounts(accounts) {
      if (accounts === null) {
        if (directory === null) snapshotFailed = true; // no directory, nothing to subscribe to
        touch();
        return;
      }
      const next = new Map(accounts.map((a) => [a.id, a]));
      // the first directory also drops a first-paint read's fills of an account it does not list
      const known = directory?.keys() ?? heldAccounts();
      const gone = new Set([...known].filter((id) => !next.has(id)));
      const named = new Set([...heldAccounts(), ...(pending ?? [])]);
      noteWithdrawn([...gone].filter((id) => named.has(id)));
      directory = next;
      dropAccounts(gone);
      settle(true); // the directory settles a narrowing: the candidates it lists stayed
      touch();
    },
    applyRest(items) {
      if (revoked) return; // no read applies until Retry (SR-E29-11)
      for (const item of items) apply(item, "rest");
    },
    applyFrames(frames) {
      let seen = 0;
      for (const frame of frames) {
        if (frame.kind === "reset") {
          applyReset(frame.reason);
          continue;
        }
        if (frame.kind === "snap") {
          baseline = true;
          everSnapped = true;
          snapshotFailed = false;
          revoked = false;
          const items = frame.bodies.flatMap(itemsOf);
          // a narrowing's snapshot is built under the new scope: an account it serves stayed, so
          // it leaves `pending` before the fills apply
          for (const item of items) {
            const account = isRecord(item) ? item["exchange_account_id"] : null;
            if (isUuid(account)) pending?.delete(account.toLowerCase());
          }
          seen += applyItems(items);
          settle(pending?.size === 0);
          asOfMs = frame.ts;
        } else if (baseline) {
          seen += applyItems(itemsOf(frame.body)); // a delta never extends a void baseline (23 §7.1)
          asOfMs = Math.max(asOfMs ?? frame.ts, frame.ts);
        }
      }
      if (frames.length > 0) touch();
      return seen;
    },
    setEffective(effective) {
      const ids = effective["exchange_account_ids"];
      if (!Array.isArray(ids) || !ids.every(isUuid)) return; // no `sub_ok` yet: nothing narrowed
      const scope = new Set([...ids.map((id) => id.toLowerCase()), ...overCap]);
      const out = new Set([...heldAccounts(), ...(pending ?? [])].filter((id) => !scope.has(id)));
      if (out.size === 0) return;
      noteWithdrawn(out);
      dropAccounts(out);
      if (pending === null) return;
      for (const id of out) pending.delete(id);
      settle(pending.size === 0);
    },
    setLink(up) {
      if (up === linkUp) return;
      linkUp = up;
      touch();
    },
    markSnapshotFailed() {
      if (baseline || snapshotFailed) return;
      snapshotFailed = true;
      touch();
    },
    setReadFailed(failed) {
      if (failed === readFailed) return;
      readFailed = failed;
      touch();
    },
    markRetrying() {
      snapshotFailed = false;
      revoked = false;
      readFailed = false;
      touch();
    },
    setOverCap(accountIds) {
      if (accountIds.length === overCap.length && accountIds.every((id, i) => overCap[i] === id))
        return;
      overCap = [...accountIds];
      dropAccounts(new Set(overCap)); // a first-paint read's rows of them would never be live
    },
    takeNarrowed() {
      const owed = narrowed;
      narrowed = false;
      return owed;
    },
    takeSettled() {
      const owed = settled;
      settled = false;
      return owed;
    },
    setAtTop(next) {
      if (next === atTop) return;
      atTop = next;
      // away: the newest row shown now is the line new fills wait above
      anchor = next ? null : (snapshot.rows[0] ?? null);
      touch();
    },
    dismissWithdrawn(accountId) {
      const next = withdrawn.filter((w) => w.accountId !== accountId);
      if (next.length === withdrawn.length) return;
      withdrawn = next;
      touch();
    },
    commit(onlyUrgent = false) {
      if (!dirty || (onlyUrgent && !urgent)) return false;
      dirty = false;
      urgent = false;
      snapshot = build();
      for (const listener of [...listeners]) listener();
      return true;
    },
  };
}

/** One selected value of the store; re-renders when the selection changes (by `Object.is`). */
export function useFills<T>(store: FillsStore, select: (s: FillsSnapshot) => T): T {
  const read = (): T => select(store.getSnapshot());
  return useSyncExternalStore(store.subscribe, read, read);
}
