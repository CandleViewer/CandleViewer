// E14-T02 (#400, BQ-04/05/06): the persistence layer. Local mutations coalesce per server id
// (last write wins; create+update folds into one create, create+delete into nothing, `22` duplicate_id)
// and flush on a 500 ms trailing debounce capped by a 2 s maxWait, or at once on `flush()`
// (pointer-up, tool change, pane close: PR-B). At most one request is in flight, because `if_match`
// chains on the previous response; tokens resolve at SEND time. A batch holds at most 200 operations.
// No answer / 408 / 5xx re-sends the SAME body under the SAME Idempotency-Key with full-jitter
// backoff (1 s base, x2, 30 s cap, DR33); 429 waits Retry-After. 403/413/422 are never re-sent: the
// symbol is re-read and server truth adopted (D02:500). A 409 rolled the whole batch back (`22`
// batchUpsertDrawings) and is reconciled per rule; see `reconcile` below.
import type { DrawingStore } from "./drawingStore";
import { serializeBatch, type BatchOutcome, type DrawingsApi } from "./drawingsApi";
import {
  inputOf,
  sameInput,
  type Drawing,
  type DrawingBatchOp,
  type Mutation,
  type SaveStatus,
} from "./types";
import { uuidv7 } from "./uuidv7";

export const DEBOUNCE_MS = 500;
export const MAX_WAIT_MS = 2_000;
export const CHUNK_SIZE = 200;
export const BACKOFF_BASE_MS = 1_000;
export const BACKOFF_CAP_MS = 30_000;
const BACKOFF_FLOOR_MS = 250;

export interface Scheduler {
  readonly now: () => number;
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (handle: unknown) => void;
}

const realScheduler: Scheduler = {
  now: () => Date.now(),
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export interface DrawingSyncDeps {
  readonly store: DrawingStore;
  readonly api: DrawingsApi;
  readonly scheduler?: Scheduler;
  /** [0, 1); the backoff jitter. */
  readonly random?: () => number;
  readonly newKey?: () => string;
  readonly mintId?: () => string;
}

export interface DrawingSync {
  /** Sends what is pending now (or right after the request in flight). */
  readonly flush: () => void;
  /** Reads a symbol from the server; concurrent calls share one request. */
  readonly load: (symbol: string) => Promise<boolean>;
  readonly pendingCount: () => number;
  readonly dispose: () => void;
}

interface Entry {
  readonly symbol: string;
  readonly m: Mutation;
}

interface Flight {
  readonly entries: readonly Entry[];
  readonly body: string;
  readonly key: string;
}

/** Folds a later mutation of the same id onto an earlier one; `null` cancels both. */
export function fold(older: Mutation, newer: Mutation): Mutation | null {
  if (older.op !== "create") return newer;
  return newer.op === "delete" ? null : { op: "create", id: older.id, input: newer.input };
}

export function backoffMs(attempt: number, random: () => number): number {
  const ceiling = Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2 ** Math.max(0, attempt - 1));
  return Math.max(BACKOFF_FLOOR_MS, Math.floor(random() * ceiling));
}

export function createDrawingSync(deps: DrawingSyncDeps): DrawingSync {
  const { store, api } = deps;
  const clock = deps.scheduler ?? realScheduler;
  const random = deps.random ?? Math.random;
  const newKey = deps.newKey ?? (() => crypto.randomUUID());
  const mintId = deps.mintId ?? (() => uuidv7());

  let pending = new Map<string, Entry>();
  let flight: Flight | null = null;
  // True while a settled batch is being reconciled (awaiting a re-read): no new batch may start,
  // because rolled-back entries are not requeued and tokens/ids are not adopted or re-minted yet.
  let settling = false;
  let failing = false;
  let attempt = 0;
  let firstAt: number | null = null;
  let timer: unknown = null;
  let retryTimer: unknown = null;
  let wantFlush = false;
  let disposed = false;
  const sticky = new Map<string, SaveStatus>();
  const loads = new Map<string, Promise<boolean>>();

  const inFlight = (id: string): boolean => flight?.entries.some((e) => e.m.id === id) ?? false;
  const busy = (id: string): boolean => pending.has(id) || inFlight(id);
  /** One request at a time: a batch in flight, its reconciliation, or a retry wait holds the queue. */
  const held = (): boolean => flight !== null || settling || retryTimer !== null;

  const statusOf = (symbol: string): SaveStatus => {
    const flying = flight?.entries.some((e) => e.symbol === symbol) ?? false;
    if (flying && failing) return { kind: "unsaved", retryable: true };
    if (flying || [...pending.values()].some((e) => e.symbol === symbol))
      return { kind: "pending" };
    return sticky.get(symbol) ?? { kind: "saved" };
  };
  const refresh = (symbols: Iterable<string>): void => {
    for (const symbol of new Set(symbols)) store.setStatus(symbol, statusOf(symbol));
  };
  const symbolsOf = (entries: readonly Entry[]): string[] => entries.map((e) => e.symbol);

  const put = (target: Map<string, Entry>, entry: Entry): void => {
    const prev = target.get(entry.m.id);
    const m = prev === undefined ? entry.m : fold(prev.m, entry.m);
    if (m === null) target.delete(entry.m.id);
    else target.set(entry.m.id, { symbol: entry.symbol, m });
  };
  /** Puts rolled-back entries back in front of anything enqueued since, folding per id. */
  const requeue = (entries: readonly Entry[]): void => {
    const next = new Map<string, Entry>();
    for (const e of entries) put(next, e);
    for (const e of pending.values()) put(next, e);
    pending = next;
  };

  const schedule = (): void => {
    if (pending.size === 0 || disposed) return;
    const now = clock.now();
    firstAt ??= now;
    const due = Math.min(now + DEBOUNCE_MS, firstAt + MAX_WAIT_MS);
    if (timer !== null) clock.clearTimeout(timer);
    timer = clock.setTimeout(fire, Math.max(0, due - now));
  };
  function fire(): void {
    timer = null;
    if (held()) wantFlush = true;
    else send();
  }

  const opOf = (e: Entry): DrawingBatchOp | null => {
    if (e.m.op === "create") return { op: "create", id: e.m.id, drawing: e.m.input };
    const token = store.tokenOf(e.m.id);
    if (token === null) return null;
    return e.m.op === "update"
      ? { op: "update", id: e.m.id, if_match: token, drawing: e.m.input }
      : { op: "delete", id: e.m.id, if_match: token };
  };

  function send(): void {
    if (disposed) return;
    if (timer !== null) clock.clearTimeout(timer);
    timer = null;
    const entries: Entry[] = [];
    const ops: DrawingBatchOp[] = [];
    for (const e of [...pending.values()]) {
      if (ops.length >= CHUNK_SIZE) break;
      const op = opOf(e);
      pending.delete(e.m.id);
      // Nothing is in flight here, so a missing token means a target never confirmed: unaddressable.
      if (op === null) continue;
      entries.push(e);
      ops.push(op);
    }
    firstAt = pending.size > 0 ? clock.now() : null;
    wantFlush = ops.length >= CHUNK_SIZE && pending.size > 0;
    if (entries.length === 0) {
      refresh(sticky.keys());
      return;
    }
    flight = { entries, body: serializeBatch(ops), key: newKey() };
    refresh(symbolsOf(entries));
    transmit();
  }

  function transmit(): void {
    const sent = flight;
    if (sent === null) return;
    void api
      .batch(sent.body, sent.key)
      // A transport that throws is treated as a 5xx: same body, same key, after backoff.
      .catch((): BatchOutcome => ({ kind: "retryable", status: 0 }))
      .then(async (outcome) => {
        if (disposed || flight !== sent) return;
        await settle(sent, outcome);
      })
      .catch(() => {
        // Reconciliation threw after the flight was cleared: never re-sent, the queue keeps going.
        if (disposed) return;
        const touched = symbolsOf(sent.entries);
        for (const symbol of touched) sticky.set(symbol, { kind: "unsaved", retryable: false });
        next(touched);
      });
  }

  const retryLater = (ms: number, then: () => void): void => {
    retryTimer = clock.setTimeout(() => {
      retryTimer = null;
      then();
    }, ms);
  };

  const next = (touched: Iterable<string>): void => {
    refresh(touched);
    if (disposed || held()) return;
    if (pending.size === 0) {
      firstAt = null;
      return;
    }
    if (wantFlush) send();
    else schedule();
  };

  async function settle(sent: Flight, outcome: BatchOutcome): Promise<void> {
    const touched = symbolsOf(sent.entries);
    if (outcome.kind === "rate_limited" || outcome.kind === "retryable") {
      if (outcome.kind === "retryable") {
        attempt += 1;
        failing = true;
      }
      const wait =
        outcome.kind === "rate_limited" && outcome.retryAfterS !== null
          ? outcome.retryAfterS * 1000
          : backoffMs(Math.max(attempt, 1), random);
      refresh(touched);
      retryLater(wait, transmit);
      return;
    }
    flight = null;
    failing = false;
    // A 409 whose re-read fails continues the escalation (reconcile), so the count is carried.
    const carried = attempt;
    attempt = 0;
    if (outcome.kind === "ok") {
      for (const d of [...outcome.result.created, ...outcome.result.updated]) {
        store.confirm(d, !pending.has(d.id));
      }
      for (const id of outcome.result.deleted) store.confirmDeleted(id);
    } else {
      settling = true;
      try {
        if (outcome.kind === "rejected") await abandon(sent.entries);
        else await reconcile(sent, outcome.rule, outcome.index, carried);
      } finally {
        settling = false;
      }
    }
    next(touched);
  }

  /** Never re-sent: unconfirmed creates go, and the symbols take server truth. */
  async function abandon(entries: readonly Entry[]): Promise<void> {
    for (const e of entries) if (e.m.op === "create") store.removeId(e.symbol, e.m.id);
    await resync(symbolsOf(entries), { kind: "unsaved", retryable: false });
  }

  async function resync(symbols: readonly string[], status: SaveStatus): Promise<void> {
    for (const symbol of new Set(symbols)) {
      sticky.set(symbol, status);
      const listed = await api.list(symbol);
      if (listed.ok && !disposed) store.hydrate(symbol, listed.items, busy);
    }
  }

  /** The atomic-batch 409 rules (BQ-04 plus the critic's self-conflict and send-time token cases). */
  async function reconcile(
    sent: Flight,
    rule: string,
    index: number | null,
    carried: number,
  ): Promise<void> {
    const failed = index === null ? undefined : sent.entries[index];
    const others = sent.entries.filter((e) => e !== failed);
    if (rule === "drawings_quota_exceeded") {
      // One notice per symbol for the episode, naming every reverted create (D02).
      const reverted = new Map<string, string[]>();
      for (const e of sent.entries.filter((x) => x.m.op === "create")) {
        store.removeId(e.symbol, e.m.id);
        sticky.set(e.symbol, { kind: "unsaved", retryable: false });
        const ids = reverted.get(e.symbol) ?? [];
        ids.push(e.m.id);
        reverted.set(e.symbol, ids);
      }
      for (const [symbol, ids] of reverted) store.notify({ kind: "quota_exceeded", symbol, ids });
      requeue(sent.entries.filter((x) => x.m.op !== "create"));
      return;
    }
    if (failed === undefined || !RULES.has(rule)) {
      await abandon(sent.entries);
      return;
    }
    const { symbol, m } = failed;
    if (rule === "target_unavailable") {
      store.removeId(symbol, m.id);
      if (m.op !== "delete") changed("removed_elsewhere", symbol, m.id);
      requeue(others);
      return;
    }
    const listed = await api.list(symbol);
    if (!listed.ok) {
      requeue(sent.entries);
      failing = true;
      attempt = carried + 1;
      retryLater(backoffMs(attempt, random), () => {
        wantFlush = true;
        next([symbol]);
      });
      return;
    }
    const server = new Map<string, Drawing>(listed.items.map((d) => [d.id, d]));
    if (rule === "id_unavailable") {
      const row = server.get(m.id);
      if (row !== undefined) {
        store.confirm(row, false);
        if (m.op !== "delete" && !sameInput(inputOf(row), m.input)) {
          requeue([{ symbol, m: { op: "update", id: m.id, input: m.input } }]);
        }
      } else if (m.op === "create") {
        const id = mintId();
        store.remint(symbol, m.id, id);
        const later = pending.get(m.id);
        pending.delete(m.id);
        const moved = later === undefined ? null : { ...later.m, id };
        const create: Mutation = { op: "create", id, input: m.input };
        const merged = moved === null ? create : fold(create, moved);
        if (merged !== null) requeue([{ symbol, m: merged }]);
      }
      requeue(others);
      return;
    }
    // version_conflict. Our own earlier write may have run (an evicted Idempotency-Key replay):
    // a row that already equals what we sent is confirmed silently, never "changed elsewhere".
    const unresolved: Entry[] = [];
    for (const e of sent.entries) {
      const row = e.symbol === symbol ? server.get(e.m.id) : undefined;
      if (e.symbol === symbol && e.m.op === "delete" && row === undefined) {
        store.confirmDeleted(e.m.id);
      } else if (row !== undefined && e.m.op !== "delete" && sameInput(inputOf(row), e.m.input)) {
        store.confirm(row, !pending.has(row.id));
      } else if (e === failed) {
        pending.delete(m.id);
        if (row === undefined) {
          store.removeId(symbol, m.id);
          changed("removed_elsewhere", symbol, m.id);
        } else {
          store.adopt(row);
          changed("changed_elsewhere", symbol, m.id);
        }
      } else unresolved.push(e);
    }
    requeue(unresolved);
  }

  const changed = (
    kind: "changed_elsewhere" | "removed_elsewhere",
    symbol: string,
    id: string,
  ): void => {
    sticky.set(symbol, { kind: "conflict" });
    store.notify({ kind, symbol, ids: [id] });
  };

  const unsubscribe = store.onMutations((symbol, mutations) => {
    sticky.delete(symbol);
    for (const m of mutations) put(pending, { symbol, m });
    refresh([symbol]);
    schedule();
  });

  return {
    flush: () => {
      if (held()) wantFlush = true;
      else send();
    },
    load: (symbol) => {
      const running = loads.get(symbol);
      if (running !== undefined) return running;
      const started = api.list(symbol).then((listed) => {
        loads.delete(symbol);
        if (!listed.ok || disposed) return false;
        store.hydrate(symbol, listed.items, busy);
        return true;
      });
      loads.set(symbol, started);
      return started;
    },
    pendingCount: () => pending.size,
    dispose: () => {
      disposed = true;
      unsubscribe();
      if (timer !== null) clock.clearTimeout(timer);
      if (retryTimer !== null) clock.clearTimeout(retryTimer);
      timer = null;
      retryTimer = null;
    },
  };
}

const RULES = new Set(["target_unavailable", "version_conflict", "id_unavailable"]);
