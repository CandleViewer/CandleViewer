/**
 * The Positions tab's store (E29-S01 #911): a `useSyncExternalStore` store (BQ-19; the shell's
 * pattern, no Zustand, Jotai or RxJS) that holds one row per open position, keyed
 * `exchange_account_id|symbol|position_idx` (the ticket's normalised store).
 *
 * - **Sources (BQ-18).** The WS `positions` snapshot is authoritative. REST is first paint while the
 *   topic is `snapshot_pending`, and the fallback while the link is down; a `snap` replaces the REST
 *   view wholesale. The two clocks are never compared: `23` §15's rule applies within WS only.
 * - **`23` §15.** A delta item older than the held one (`updated_at_ms`) is dropped; an equal one
 *   replaces it. A frame's `removed` ids apply after its upserts (`23` §15.2).
 * - **Resets.** A `reset` voids the WS baseline (`lib/ws/api.ts`): the rows shown stay as the last
 *   good view until the next `snap` replaces them. `narrowed` and `revoked` drop the accounts' rows
 *   at once from every cache, rows, liquidation state and balances alike (OM-I04, SR-E29-11), and
 *   each withdrawn account gets E29-D05 F-02's "No longer shown" line.
 * - **A narrowing** (`23` §9.5) arrives as a bare `reset`: the consumer API carries no
 *   `removed_accounts`, and the handle's `effective` keeps the old list (E17's registry does not
 *   edit it). Its accounts wait as candidates: one the narrowed `snap` serves was kept; the feed
 *   re-reads the directory, and `setAccounts` names the ones it no longer lists (a narrowed
 *   `sub_ok` names them too, when one comes). A REST read never brings a candidate's rows back,
 *   nor a withdrawn or over-cap account's, nor any after a revocation (SR-E29-11).
 * - **A removed row stays removed** for the baseline's life: an item stamped at or before its
 *   removal is late (`23` §6.2.3, §15), whichever frame brings it.
 * - **Commits** are coalesced: inputs only mark the store dirty, and `commit()`, which the feed
 *   calls at most every 100 ms (`wsPositions.ts`), publishes one snapshot (the ticket's 10 Hz tick).
 */
import { useSyncExternalStore } from "react";
import type { TopicFrame } from "../../lib/ws/api";
import type { DataBody } from "../../lib/ws/protocol/codec";
import { parseDecimal } from "./model/decimal";
import { LiqTierTracker, type LiqCrossing, type LiqReading } from "./model/liqTier";
import {
  isUuid,
  keyOf,
  mapRow,
  type AccountInfo,
  type PositionRowModel,
  type RestPosition,
  type WsPosition,
} from "./model/rowMapping";
import { sortDefault } from "./model/sort";

export type FeedStatus =
  | "idle"
  | "loading"
  | "live"
  | "resyncing"
  | "offline"
  | "snapshot_failed"
  | "revoked"
  | "no_accounts";

export type ViewSource = "none" | "rest" | "ws" | "last_good";

/** E29-D05 F-02: an account whose rows were withdrawn, for its "No longer shown" line. */
export interface Withdrawn {
  readonly accountId: string;
  readonly label: string | null;
}

export interface Crossing {
  readonly seq: number;
  readonly key: string;
  readonly crossing: LiqCrossing;
}

export interface PositionsSnapshot {
  readonly status: FeedStatus;
  readonly source: ViewSource;
  /** When the rows shown were current: the newest frame's `ts`, or a REST read's receipt. */
  readonly asOfMs: number | null;
  /** The open positions, in D01 D13 (a)'s default order. */
  readonly rows: readonly PositionRowModel[];
  readonly liq: ReadonlyMap<string, LiqReading>;
  /** The crossings this commit found (an event each: RT-05, RT-12); `seq` never repeats. */
  readonly crossings: readonly Crossing[];
  readonly accounts: readonly AccountInfo[];
  readonly accountsLoaded: boolean;
  readonly withdrawn: readonly Withdrawn[];
  /** `wallet` `realised_pnl_today` per account, when served (D-15). */
  readonly realisedToday: ReadonlyMap<string, string>;
  /** Accounts past the 25 a `positions` subscription may name (`23` §13.5): not shown live. */
  readonly overCap: readonly string[];
  readonly version: number;
}

type Wire = WsPosition | RestPosition;
interface Held {
  readonly wire: Wire;
  readonly source: "ws" | "rest";
}
interface WalletEntry {
  readonly coin: string;
  readonly mmRate: string | null;
  readonly realisedToday: string | null;
  /** `23` §15.4: the balance is older than the producer's 10 s, since `staleSinceMs`. */
  readonly stale: boolean;
  readonly staleSinceMs: number | null;
  readonly updatedAtMs: number;
}
/** What a reading takes of the account's MM rate (BQ-11): the rate, and its balance's staleness. */
interface MmRate {
  readonly rate: string | null;
  /** The `wallet` balance's `stale`; `null` when the rate is not the wallet's. */
  readonly stale: boolean | null;
  readonly staleSinceMs: number | null;
}

/** Bounded, as every cache is (C-2.18): a crossings list per commit, the withdrawn lines. */
const MAX_CROSSINGS = 512;
const MAX_WITHDRAWN = 64;
/** The removed rows a baseline remembers (C-2.18): past it the oldest is forgotten first. */
export const MAX_TOMBSTONES = 1_024;

const EMPTY: PositionsSnapshot = Object.freeze({
  status: "idle",
  source: "none",
  asOfMs: null,
  rows: [],
  liq: new Map(),
  crossings: [],
  accounts: [],
  accountsLoaded: false,
  withdrawn: [],
  realisedToday: new Map(),
  overCap: [],
  version: 0,
});

const isRecord = (v: unknown): v is Readonly<Record<string, unknown>> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** The `positions` payload of a structured body, or `null` (a binary body carries no positions). */
function payloadOf(
  body: DataBody,
): { positions: readonly unknown[]; removed: readonly unknown[] } | null {
  if (body.e !== "j" || !isRecord(body.p) || !Array.isArray(body.p["positions"])) return null;
  const removed = body.p["removed"];
  return { positions: body.p["positions"], removed: Array.isArray(removed) ? removed : [] };
}

/** An item's store key, or `null` for one that names no position. */
function itemKey(item: unknown): string | null {
  if (!isRecord(item)) return null;
  const account = item["exchange_account_id"];
  const symbol = item["symbol"];
  const idx = item["position_idx"];
  if (!isUuid(account) || typeof symbol !== "string") return null;
  return keyOf(account.toLowerCase(), symbol, idx === 1 || idx === 2 ? idx : 0);
}

/** `23` §13 `epochMs`: a safe, non-negative integer, else `null`. */
const epochMs = (v: unknown): number | null =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : null;
const stampOf = (item: unknown): number | null =>
  epochMs(isRecord(item) ? item["updated_at_ms"] : undefined);

const isOpen = (item: unknown): boolean =>
  isRecord(item) && (item["side"] === "long" || item["side"] === "short");

export interface PositionsStore {
  getSnapshot(): PositionsSnapshot;
  subscribe(listener: () => void): () => void;
  /** The feed started (`loading`) or stopped (`idle`, every cache dropped). */
  setStarted(started: boolean): void;
  /** The account directory, `null` when its read failed. */
  setAccounts(accounts: readonly AccountInfo[] | null): void;
  /**
   * A REST read: first paint, or the link-down fallback. Ignored once a WS baseline is held and
   * while revoked; a narrowing's candidates, a withdrawn account while its line stands, and an
   * over-cap account bring no rows.
   */
  applyRest(items: readonly RestPosition[], atMs: number): void;
  /** What the `positions` handle's `read()` returned, in order. */
  applyFrames(frames: readonly TopicFrame[]): void;
  /** What the `wallet` handle's `read()` returned: the MM rate and today's realised PnL. */
  applyWallet(frames: readonly TopicFrame[]): void;
  /**
   * The current subscription's effective options (`TopicHandle.effective`, C4): an account it no
   * longer names leaves every cache with its F-02 line (a narrowed `sub_ok`, SR-E29-11). An
   * over-cap account is never named. A list that still names a narrowing's candidates settles
   * nothing: after a narrowing it is the old one (E17), so only the directory settles them.
   */
  setEffective(effective: Readonly<Record<string, unknown>>): void;
  setLink(up: boolean): void;
  /** S-02: no first `snap` within the budget, or the subscription refused before one. */
  markSnapshotFailed(): void;
  /** Retry re-subscribes (S-02): back to loading, the failure cleared. */
  markRetrying(): void;
  /** Accounts past the 25 a subscription names: never shown live, so their rows leave, unnamed. */
  setOverCap(accountIds: readonly string[]): void;
  /**
   * Whether a narrowing came since the last call (taken once): its reset names no account, so the
   * feed re-reads the directory, whose `setAccounts` names the ones that left (`23` §9.5).
   */
  takeNarrowed(): boolean;
  dismissWithdrawn(accountId: string): void;
  /** Publishes one snapshot when anything changed; `true` when it did. */
  commit(): boolean;
}

export function createPositionsStore(): PositionsStore {
  let snapshot = EMPTY;
  const listeners = new Set<() => void>();
  let dirty = false;
  let started = false;

  let directory: Map<string, AccountInfo> | null = null;
  let ws = new Map<string, WsPosition>();
  let wsIds = new Map<string, string>(); // position id -> key
  /** Removed rows' keys -> the stamp they were removed at, for the baseline's life (`23` §15). */
  let tombs = new Map<string, number>();
  let wsBaseline = false;
  let everSnapped = false;
  let wsAsOf: number | null = null;
  let rest: { rows: Map<string, RestPosition>; asOfMs: number } | null = null;
  let lastGood: { rows: Map<string, Held>; asOfMs: number | null } | null = null;
  let linkUp = true;
  let snapshotFailed = false;
  let revoked = false;
  /** A narrowing's candidates: the accounts whose rows it took, until the directory settles. */
  let pendingNarrowing: Set<string> | null = null;
  let narrowed = false;
  let withdrawn: Withdrawn[] = [];
  let overCap: readonly string[] = [];
  let wallet = new Map<string, Map<string, WalletEntry>>();
  let crossingSeq = 0;
  const tracker = new LiqTierTracker();
  const mapped = new Map<string, { wire: Wire; dir: unknown; row: PositionRowModel | null }>();

  const touch = (): void => {
    dirty = true;
  };

  /** The rows a view shows now, by key. */
  function shown(): { rows: Map<string, Held>; source: ViewSource; asOfMs: number | null } {
    if (wsBaseline) {
      const rows = new Map<string, Held>();
      for (const [key, wire] of ws) rows.set(key, { wire, source: "ws" });
      return { rows, source: "ws", asOfMs: wsAsOf };
    }
    if (lastGood !== null)
      return { rows: lastGood.rows, source: "last_good", asOfMs: lastGood.asOfMs };
    if (rest !== null) {
      const rows = new Map<string, Held>();
      for (const [key, wire] of rest.rows) rows.set(key, { wire, source: "rest" });
      return { rows, source: "rest", asOfMs: rest.asOfMs };
    }
    return { rows: new Map(), source: "none", asOfMs: null };
  }

  const accountOfKey = (key: string): string => key.slice(0, key.indexOf("|"));

  /** The keys the view shows now, read in place (no copy: it runs every tick). */
  function shownKeys(): Iterable<string> {
    if (wsBaseline) return ws.keys();
    if (lastGood !== null) return lastGood.rows.keys();
    return rest?.rows.keys() ?? [];
  }

  function heldAccounts(): Set<string> {
    const accounts = new Set<string>();
    for (const key of shownKeys()) accounts.add(accountOfKey(key));
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

  /** SR-E29-11: an account's rows, liquidation state and balances leave every cache now. */
  function dropAccounts(accountIds: ReadonlySet<string>): void {
    if (accountIds.size === 0) return;
    const gone = (key: string): boolean => accountIds.has(accountOfKey(key));
    for (const key of [...ws.keys()]) if (gone(key)) ws.delete(key);
    wsIds = new Map([...wsIds].filter(([, key]) => !gone(key)));
    if (rest !== null)
      rest = { ...rest, rows: new Map([...rest.rows].filter(([key]) => !gone(key))) };
    if (lastGood !== null) {
      lastGood = { ...lastGood, rows: new Map([...lastGood.rows].filter(([key]) => !gone(key))) };
    }
    for (const key of [...mapped.keys()]) if (gone(key)) mapped.delete(key);
    for (const key of [...tombs.keys()]) if (gone(key)) tombs.delete(key);
    for (const id of accountIds) wallet.delete(id);
    touch();
  }

  function clearWs(): void {
    ws = new Map();
    wsIds = new Map();
    tombs = new Map(); // a removal is the baseline's: the next one says what is open
    wsBaseline = false;
  }

  function upsert(item: unknown): void {
    const key = itemKey(item);
    const stamp = stampOf(item);
    if (key === null || stamp === null) return; // `23` §15.2 requires both: a malformed item is dropped
    const held = ws.get(key);
    if (held !== undefined && stamp < held.updated_at_ms) return; // older: discarded (23 §15)
    // a row removed since the baseline began: an item stamped no later than its removal is late
    const removedAt = tombs.get(key);
    if (held === undefined && removedAt !== undefined && stamp <= removedAt) return;
    if (!isOpen(item)) {
      remove(key, stamp); // a flat row leaves the view
      return;
    }
    const wire = item as WsPosition;
    ws.set(key, wire);
    wsIds.set(wire.id.toLowerCase(), key);
    tombs.delete(key);
  }

  /**
   * The row leaves, and its key remembers when: the flat item's stamp, else the removed row's own
   * (a `removed` id carries none), so an item stamped no later cannot bring it back.
   */
  function remove(key: string, stamp?: number): void {
    const wire = ws.get(key);
    if (wire !== undefined) wsIds.delete(wire.id.toLowerCase());
    ws.delete(key);
    const at = Math.max(stamp ?? -1, wire?.updated_at_ms ?? -1, tombs.get(key) ?? -1);
    if (at < 0) return;
    tombs.delete(key); // the newest removal goes last, so the oldest is forgotten first
    tombs.set(key, at);
    if (tombs.size > MAX_TOMBSTONES) {
      const oldest = tombs.keys().next();
      if (oldest.done !== true) tombs.delete(oldest.value);
    }
  }

  function applySnap(bodies: readonly DataBody[], ts: number): void {
    clearWs();
    for (const body of bodies) {
      const payload = payloadOf(body);
      if (payload === null) continue;
      for (const item of payload.positions) upsert(item);
    }
    if (pendingNarrowing !== null) {
      // a narrowing's `snap` is built under the new scope (`23` §9.5): an account it serves stayed
      for (const key of ws.keys()) pendingNarrowing.delete(accountOfKey(key));
      if (pendingNarrowing.size === 0) pendingNarrowing = null;
    }
    wsBaseline = true;
    everSnapped = true;
    snapshotFailed = false;
    revoked = false;
    rest = null; // a snap replaces the REST view wholesale (BQ-18)
    lastGood = null;
    wsAsOf = ts;
  }

  function applyDelta(body: DataBody, ts: number): void {
    if (!wsBaseline) return; // the client never extends a void baseline (23 §7.1)
    const payload = payloadOf(body);
    if (payload === null) return;
    for (const item of payload.positions) upsert(item);
    for (const id of payload.removed) {
      const key = typeof id === "string" ? wsIds.get(id.toLowerCase()) : undefined;
      if (key !== undefined) remove(key); // after the upserts (23 §15.2)
    }
    wsAsOf = Math.max(wsAsOf ?? ts, ts);
  }

  function applyReset(reason: string): void {
    if (reason === "narrowed" || reason === "revoked") {
      const held = heldAccounts();
      dropAccounts(held); // every row: which accounts left is not known yet (security first)
      clearWs();
      rest = null;
      lastGood = null;
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
    // gap, malformed, overflow, resnapshot, reconnect, unsubscribed: the baseline is void, the
    // view keeps the last good rows until the next `snap` (never extended by a delta)
    if (wsBaseline) {
      const rows = new Map<string, Held>();
      for (const [key, wire] of ws) rows.set(key, { wire, source: "ws" });
      lastGood = { rows, asOfMs: wsAsOf };
    }
    clearWs();
  }

  function walletPayload(body: DataBody): readonly unknown[] {
    if (body.e !== "j" || !isRecord(body.p) || !Array.isArray(body.p["balances"])) return [];
    return body.p["balances"];
  }

  function applyBalance(item: unknown): void {
    if (!isRecord(item) || !isUuid(item["exchange_account_id"])) return;
    const account = item["exchange_account_id"].toLowerCase();
    const coin = typeof item["coin"] === "string" ? item["coin"] : "";
    const stamp = stampOf(item);
    if (stamp === null) return;
    const coins = wallet.get(account) ?? new Map<string, WalletEntry>();
    const held = coins.get(coin);
    if (held !== undefined && stamp < held.updatedAtMs) return; // 23 §15, per (account, coin)
    const text = (v: unknown): string | null =>
      typeof v === "string" && parseDecimal(v) !== null ? v : null;
    const stale = item["stale"] === true;
    coins.set(coin, {
      coin,
      mmRate: text(item["account_mm_rate"]),
      realisedToday: text(item["realised_pnl_today"]),
      stale,
      staleSinceMs: stale ? epochMs(item["stale_since_ms"]) : null,
      updatedAtMs: stamp,
    });
    wallet.set(account, coins);
  }

  /**
   * The account's MM rate: `wallet`'s USDT row, else any, else the REST balance's (first paint),
   * with the wallet row's `stale` (`23` §15.4); the REST balance's is not read, so it is `null`.
   */
  function mmRateOf(accountId: string): MmRate {
    const coins = wallet.get(accountId);
    const entry = coins?.get("USDT") ?? [...(coins?.values() ?? [])][0];
    if (entry !== undefined && entry.mmRate !== null) {
      return { rate: entry.mmRate, stale: entry.stale, staleSinceMs: entry.staleSinceMs };
    }
    return { rate: directory?.get(accountId)?.mmRate ?? null, stale: null, staleSinceMs: null };
  }

  function statusOf(): FeedStatus {
    if (!started) return "idle";
    if (directory !== null && directory.size === 0) return "no_accounts";
    if (snapshotFailed) return "snapshot_failed";
    if (revoked) return "revoked";
    if (!linkUp) return "offline";
    if (wsBaseline) return "live";
    if (lastGood !== null) return "resyncing";
    return "loading";
  }

  function build(): PositionsSnapshot {
    const view = shown();
    const rows: PositionRowModel[] = [];
    const liq = new Map<string, LiqReading>();
    const crossings: Crossing[] = [];
    const dir = directory ?? new Map<string, AccountInfo>();
    for (const [key, held] of view.rows) {
      let entry = mapped.get(key);
      if (entry === undefined || entry.wire !== held.wire || entry.dir !== directory) {
        entry = { wire: held.wire, dir: directory, row: mapRow(held.wire, held.source, dir) };
        mapped.set(key, entry);
      }
      const row = entry.row;
      if (row === null) continue;
      rows.push(row);
      const mm = mmRateOf(row.accountId);
      const { reading, crossing } = tracker.update(row.key, {
        side: row.side,
        entry: row.entry,
        mark: row.mark,
        liqPrice: row.liqPrice,
        marginMode: row.marginMode.value,
        mmRate: mm.rate,
        mmRateStale: mm.stale,
        mmRateStaleSinceMs: mm.staleSinceMs,
      });
      liq.set(row.key, reading);
      if (crossing !== null && crossings.length < MAX_CROSSINGS) {
        crossingSeq += 1;
        crossings.push({ seq: crossingSeq, key: row.key, crossing });
      }
    }
    const keys = new Set(rows.map((r) => r.key));
    tracker.retain(keys); // a row that left re-arms
    for (const key of [...mapped.keys()]) if (!view.rows.has(key)) mapped.delete(key);
    const realisedToday = new Map<string, string>();
    for (const [account, coins] of wallet) {
      const value = (coins.get("USDT") ?? [...coins.values()][0])?.realisedToday;
      if (value !== null && value !== undefined) realisedToday.set(account, value);
    }
    return Object.freeze({
      status: statusOf(),
      source: view.source,
      asOfMs: view.asOfMs,
      rows: sortDefault(rows),
      liq,
      crossings,
      accounts: [...dir.values()],
      accountsLoaded: directory !== null,
      withdrawn,
      realisedToday,
      overCap,
      version: snapshot.version + 1,
    });
  }

  const store: PositionsStore = {
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
        clearWs();
        everSnapped = false;
        wsAsOf = null;
        rest = null;
        lastGood = null;
        linkUp = true;
        snapshotFailed = false;
        revoked = false;
        pendingNarrowing = null;
        narrowed = false;
        withdrawn = [];
        overCap = [];
        wallet = new Map();
        mapped.clear();
        tracker.clear();
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
      const gone = new Set<string>();
      for (const id of directory?.keys() ?? []) if (!next.has(id)) gone.add(id);
      // a shown account, or a narrowing's candidate, gets its line; labels from the old directory
      const named = new Set([...heldAccounts(), ...(pendingNarrowing ?? [])]);
      noteWithdrawn([...gone].filter((id) => named.has(id)));
      directory = next;
      dropAccounts(gone);
      pendingNarrowing = null; // the directory settles a narrowing: the candidates it lists stayed
      if (accounts.length > 0 && snapshotFailed && !everSnapped && rest === null)
        snapshotFailed = false;
      touch();
    },
    applyRest(items, atMs) {
      // the WS snapshot is authoritative (BQ-18); while revoked, no read applies until Retry
      if (wsBaseline || revoked) return;
      const barred = new Set([
        ...withdrawn.map((w) => w.accountId),
        ...(pendingNarrowing ?? []),
        ...overCap,
      ]);
      const rows = new Map<string, RestPosition>();
      for (const item of items) {
        const key = itemKey(item);
        // a read that set out before a withdrawal or a narrowing brings none of their rows back,
        // and an over-cap account's rows would never be live
        if (key !== null && isOpen(item) && !barred.has(accountOfKey(key))) rows.set(key, item);
      }
      rest = { rows, asOfMs: atMs };
      lastGood = null; // read after the loss, so newer than what the link left
      touch();
    },
    applyFrames(frames) {
      for (const frame of frames) {
        if (frame.kind === "reset") applyReset(frame.reason);
        else if (frame.kind === "snap") applySnap(frame.bodies, frame.ts);
        else applyDelta(frame.body, frame.ts);
      }
      if (frames.length > 0) touch();
    },
    applyWallet(frames) {
      for (const frame of frames) {
        if (frame.kind === "reset") {
          if (frame.reason === "narrowed" || frame.reason === "revoked") wallet = new Map();
          continue;
        }
        if (frame.kind === "snap") wallet = new Map();
        for (const body of frame.kind === "snap" ? frame.bodies : [frame.body]) {
          for (const item of walletPayload(body)) applyBalance(item);
        }
      }
      if (frames.length > 0) touch();
    },
    setEffective(effective) {
      const ids = effective["exchange_account_ids"];
      if (!Array.isArray(ids) || !ids.every(isUuid)) return; // no `sub_ok` yet: nothing narrowed
      const scope = new Set([...ids.map((id) => id.toLowerCase()), ...overCap]); // never withdrawn
      const out = new Set(
        [...heldAccounts(), ...(pendingNarrowing ?? [])].filter((id) => !scope.has(id)),
      );
      if (out.size === 0) return;
      noteWithdrawn(out); // a narrowed `sub_ok`, or the accounts a narrowing took (SR-E29-11)
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
      // a first-paint read set out before the cap was known: its rows of these accounts would never
      // be live, so they leave now, with no line (they were not withdrawn; `overCap` says why)
      dropAccounts(new Set(overCap));
      touch();
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
  return store;
}

/** One selected value of the store; re-renders when the selection changes (by `Object.is`). */
export function usePositions<T>(store: PositionsStore, select: (s: PositionsSnapshot) => T): T {
  const read = (): T => select(store.getSnapshot());
  return useSyncExternalStore(store.subscribe, read, read);
}
