/**
 * The reassurance gate (E29-S07 #1028; BQ-11 of the ruling of record 6575172489, BQ-6 and BQ-7
 * ruled (6610918411)): "Your exchange-side stop-losses are unaffected." shows only when it is true.
 *
 * - **The read.** The REST `listPositions` read at each connect and reconnect, and again when an
 *   account's lock begins (`RecoveredRegionSlot`). An account passes when every open position
 *   reads `native_stop_present: true` and none is in Partial mode (`24` §8.12: the REST derivation
 *   misses a Partial-mode stop, so a Partial position never counts as confirmed).
 * - **Dropped** at the account's next `positions` delta (or a reset) until the next read: the slot
 *   watches the `positions` topic with a consumer of its own (`positionsWatch.ts`) and calls
 *   `dropReassurance`. Each drop bumps the account's generation, and a read publishes a verdict
 *   only when the account's generation has not moved since the read began, so a delta that lands
 *   between the request and its answer never leaves a stale `true` (OM-T08, C-2.6).
 * - **No time clause** (BQ-6 ruled): the deck keeps the first sentence only; `{time}` would be the
 *   server's last exchange confirmation, which no feed carries yet (BQ-11's rider: never the
 *   client's read time).
 * - **E17's stops clause** (BQ-7 ruled; `stopsConfirmed.ts`): kept only while every account in
 *   scope is synced (no `oms.` state) and its last read passed. An unknown or empty account list
 *   reads as unread, so the clause is dropped (fail closed).
 * - A stopped shell clears the store (`clearReassurance`, from `shell/bootstrap/store.ts`).
 */
import { useSyncExternalStore } from "react";
import type { Position, PositionsApi } from "../positions/api";
import type { SignalsSnapshot } from "../../shell/accountState/accountSignals";
import type { WsState } from "../../lib/ws/state/types";

export type Reassurance =
  | { readonly kind: "unread" }
  | { readonly kind: "true" }
  | { readonly kind: "false"; readonly symbols: readonly string[] };

const UNREAD: Reassurance = Object.freeze({ kind: "unread" });
const TRUE: Reassurance = Object.freeze({ kind: "true" });
/** Bounded (C-2.18), as the account states are. */
const MAX_ACCOUNTS = 256;
/** A read whose account moved under it is retried once, then left unread (fail closed). */
export const READ_ATTEMPTS = 2;

let byAccount: ReadonlyMap<string, Reassurance> = new Map();
/** Per account, bumped by every drop; a whole clear bumps `epoch`. A read publishes only if neither moved. */
let generations = new Map<string, number>();
let epoch = 0;
const generationOf = (id: string): number => generations.get(id) ?? 0;
const listeners = new Set<() => void>();

function publish(next: Map<string, Reassurance>): void {
  byAccount = next;
  for (const listener of [...listeners]) listener();
}

export const getReassurance = (): ReadonlyMap<string, Reassurance> => byAccount;
export function subscribeReassurance(listener: () => void): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}

const isOpen = (p: Position): boolean => {
  const size = Number(p.size);
  return Number.isFinite(size) && size !== 0;
};

/** One account's verdict from its positions (any order, any account mixed in). */
export function judge(accountId: string, positions: readonly Position[]): Reassurance {
  const id = accountId.toLowerCase();
  const naked = positions
    .filter((p) => p.exchange_account_id.toLowerCase() === id && isOpen(p))
    .filter((p) => p.native_stop_present !== true || p.tpsl_mode === "Partial")
    .map((p) => p.symbol);
  return naked.length === 0 ? TRUE : { kind: "false", symbols: [...new Set(naked)].sort() };
}

/**
 * Reads `accountIds` (at most 25 a request) and stores each verdict; a failed read leaves them
 * unread. A verdict is not stored when the account's generation moved during the read: that
 * account is read again, at most `READ_ATTEMPTS` reads in all, so a read that crosses the
 * subscription's first snap is judged by its retry, and one that crosses a drop stays unread
 * unless its retry is answered before any further move.
 */
export async function readReassurance(
  accountIds: readonly string[],
  api: Pick<PositionsApi, "listPositions">,
  signal?: AbortSignal,
): Promise<void> {
  const ids = [...new Set(accountIds.map((a) => a.toLowerCase()))];
  for (let i = 0; i < ids.length; i += 25) {
    let pending = ids.slice(i, i + 25);
    // An account whose stream moved during a read is read once more (the server's `positions`
    // snap on subscribe usually beats the connect read's answer); never more (C-2.18).
    for (let attempt = 0; attempt < READ_ATTEMPTS && pending.length > 0; attempt += 1) {
      const startEpoch = epoch;
      const started = new Map(pending.map((id) => [id, generationOf(id)]));
      const got = await api.listPositions({ accountIds: pending }, signal);
      if (signal?.aborted === true || epoch !== startEpoch) return;
      const next = new Map(byAccount);
      const moved: string[] = [];
      for (const id of pending) {
        // a move after this request: its answer may predate the move, so it is never published
        if (generationOf(id) !== started.get(id)) {
          moved.push(id);
          continue;
        }
        const verdict = got.kind === "ok" ? judge(id, got.items) : UNREAD;
        if (next.has(id) || next.size < MAX_ACCOUNTS) next.set(id, verdict);
      }
      publish(next);
      pending = moved;
    }
  }
}

/**
 * The account's `positions` stream moved under a read in flight: the read's verdict is not
 * published (its generation moved), and a verdict already held stands. The handle's first `snap`.
 */
export function touchReassurance(accountId: string): void {
  const id = accountId.toLowerCase();
  if (generations.has(id) || generations.size < MAX_ACCOUNTS) {
    generations.set(id, generationOf(id) + 1);
  } else {
    epoch += 1; // past the bound a touch voids every read in flight (fail closed, C-2.18)
  }
}

/** The account's next `positions` delta: the verdict no longer holds until the next read. */
export function dropReassurance(accountId: string): void {
  const id = accountId.toLowerCase();
  touchReassurance(id);
  if ((byAccount.get(id) ?? UNREAD).kind === "unread") return;
  const next = new Map(byAccount);
  next.delete(id);
  publish(next);
}

/** Test and logout reset. */
export function clearReassurance(): void {
  epoch += 1;
  generations = new Map();
  if (byAccount.size > 0) publish(new Map());
}

/** The deck's line for the verdict (D03:322–323), or `null` while unread (nothing is claimed). */
export function reassuranceLine(
  r: Reassurance,
): { readonly key: "acct.reassure.true" | "acct.reassure.false"; readonly text: string } | null {
  if (r.kind === "unread") return null;
  if (r.kind === "true") {
    return { key: "acct.reassure.true", text: "Your exchange-side stop-losses are unaffected." };
  }
  const n = r.symbols.length;
  const what = n === 1 ? "1 open position has" : `${n} open positions have`;
  return {
    key: "acct.reassure.false",
    text: `${what} no confirmed exchange-side stop: ${r.symbols.join(", ")}.`,
  };
}

/**
 * Whether the link is up and the `system` stream and the private snapshots are in: the state in which
 * the `positions` watch is running and the verdicts are kept current (`RecoveredRegionSlot`).
 */
export function streamReady(
  ws: Pick<WsState, "link" | "outage" | "systemStream">,
  privateFeedDown: boolean,
): boolean {
  return (
    ws.link.kind === "up" && ws.outage === null && ws.systemStream === "live" && !privateFeedDown
  );
}

/** BQ-7 ruled: whether E17's stops clause may stand for `scope`. */
export function stopsClauseHolds(
  scope: readonly string[] | undefined,
  signals: SignalsSnapshot,
  reassurance: ReadonlyMap<string, Reassurance>,
): boolean {
  if (scope === undefined || scope.length === 0) return false; // unknown or empty: unread (L3)
  if (signals.overflowed) return false; // a state refused past the bound: fail closed, as new exposure does
  return scope.every((raw) => {
    const id = raw.toLowerCase();
    const synced = (signals.accounts.get(id)?.oms ?? null) === null;
    return synced && reassurance.get(id)?.kind === "true";
  });
}

/** The account's line, re-rendered on a read, a drop or a new verdict. */
export function useReassuranceLine(accountId: string): ReturnType<typeof reassuranceLine> {
  const r = useSyncExternalStore(
    subscribeReassurance,
    () => byAccount.get(accountId.toLowerCase()) ?? UNREAD,
    () => UNREAD,
  );
  return reassuranceLine(r);
}
