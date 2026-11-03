/**
 * The admin reads' shared store (E42-S01, BQ-5 and BQ-6): one module-level entry per read, read by
 * the strip on every admin route and by SCR-120's tiles, so the strip never adds a request while
 * the overview is open. Each entry keeps its last good body through a failed re-read (E42-D02 D4's
 * "old": the value stays). Reads run while some view holds them: at most one in flight per read, a
 * hold repeats no read answered under 30 s ago, and one chained 30 s timer re-reads the overview
 * (`CYCLE_READS`); every other read is asked once per entry and on its tile's Retry. The timer
 * stops while the document is hidden and when nothing holds a read; the last release also aborts
 * the reads in flight and drops every answer, and a `403` drops them at once and asks nothing
 * more. The store holds no React state: views select from it.
 */
import { useEffect, useRef, useSyncExternalStore } from "react";
import {
  readAdmin,
  vetAudit,
  vetBackups,
  vetCapacity,
  vetFlags,
  vetHealth,
  vetInvites,
  vetOverview,
  type AdminOverview,
  type AuditPage,
  type BackupPage,
  type CapacityReport,
  type FailReason,
  type FlagList,
  type HealthReport,
  type InviteCount,
  type ReadOutcome,
  type ReadTimers,
} from "./adminReads";

/** What each read returns, by id. */
export interface ReadBodies {
  readonly overview: AdminOverview;
  readonly capacity: CapacityReport;
  readonly health: HealthReport;
  readonly flags: FlagList;
  readonly audit: AuditPage;
  readonly backups: BackupPage;
  readonly invites: InviteCount;
}
export type ReadId = keyof ReadBodies;

/** The path each read asks for: the contract's operations (`22`), nothing composed from data. */
export const READ_PATHS: Readonly<Record<ReadId, string>> = {
  overview: "/api/v1/admin/overview", // getAdminOverview
  capacity: "/api/v1/admin/capacity", // getCapacity
  health: "/api/v1/admin/health", // getHealth
  flags: "/api/v1/admin/feature-flags", // listFeatureFlags
  audit: "/api/v1/admin/audit?limit=3", // queryAuditLog, the three latest entries (D9)
  backups: "/api/v1/admin/backups?limit=1", // listBackups: 501 until catalogued (CG-10)
  invites: "/api/v1/users/invites", // listPendingInvites
};

const VET: { readonly [K in ReadId]: (raw: unknown) => ReadBodies[K] | null } = {
  overview: vetOverview,
  capacity: vetCapacity,
  health: vetHealth,
  flags: vetFlags,
  audit: vetAudit,
  backups: vetBackups,
  invites: vetInvites,
};

/** The re-read period (E42-D03 §6, D02 §6.2) and the age under which a held read is not repeated. */
export const REREAD_MS = 30_000;

/**
 * What the 30 s cycle repeats: the overview's slices, as the orchestrator ruled BQ-5 for #5330.
 * Capacity, health, flags, audit, backups and invites are asked once per entry (a view's hold)
 * and on their tile's Retry, so a visit writes one `admin.area_entered` row per 30 s and the page
 * stops adding its own reads to the Audit tile's newest rows on every tick. The entry's own reads
 * still land in one instant beside the single audit read (S-5330-02, C-5330-03, C-5330-12; the
 * server's write policy is #5331). The lines the once-read reads feed print their own read time
 * (C-5330-11): none of them joins the cycle, or each `/admin/*` one adds a row per tick again.
 */
export const CYCLE_READS: readonly ReadId[] = ["overview"];

export interface ReadEntry<T> {
  /** The last answer's kind; `idle` until the first answer. */
  readonly phase: "idle" | "ok" | "failed" | "not_built" | "denied";
  /** The last good body, kept through a failure: the tile shows it as old, never as fresh. */
  readonly data?: T | undefined;
  /** The client's clock at the last good answer. */
  readonly okAt?: number | undefined;
  /**
   * Per slice of the body (`AdminSliceStatus`), when it last read `ok`: its `generated_at`, else
   * the answer's time. A slice that answers `error` reads "last good {time}" from here.
   */
  readonly sliceGoodAt?: Readonly<Record<string, number>> | undefined;
  /** The client's clock at the first failure since the last good answer ("stale since"). */
  readonly failedAt?: number | undefined;
  readonly reason?: FailReason | undefined;
  readonly status?: number | undefined;
  /** A `403`'s problem `instance`. */
  readonly refId?: string | undefined;
  /** When the last answer came: a held read answered under `REREAD_MS` ago is not repeated. */
  readonly answeredAt?: number | undefined;
  readonly inFlight: boolean;
  /** The tile whose Retry started the read in flight: only that tile shows it loading. */
  readonly retriedBy?: string | undefined;
}

export type AdminReadState = { readonly [K in ReadId]: ReadEntry<ReadBodies[K]> };

const IDLE: ReadEntry<never> = Object.freeze({ phase: "idle", inFlight: false });
const READ_IDS = Object.keys(READ_PATHS) as ReadId[];
const INITIAL = Object.freeze(
  Object.fromEntries(READ_IDS.map((id) => [id, IDLE])),
) as unknown as AdminReadState;

/**
 * Every entry back to idle but a refusal, which keeps the area withdrawn until the page reloads
 * (BQ-8): nothing an admin read answered stays in memory (C-5330-02, S-5330-03).
 */
const cleared = (s: AdminReadState): AdminReadState =>
  Object.fromEntries(
    READ_IDS.map((id) => [id, s[id].phase === "denied" ? s[id] : IDLE]),
  ) as unknown as AdminReadState;

export interface AdminReadDeps extends ReadTimers {
  readonly now: () => number;
  /** The document whose visibility pauses the re-read; `null` reads it as always visible. */
  readonly document: Document | null;
  readonly read: <K extends ReadId>(
    id: K,
    signal: AbortSignal,
  ) => Promise<ReadOutcome<ReadBodies[K]>>;
}

export interface AdminReadStore {
  readonly getState: () => AdminReadState;
  readonly subscribe: (listener: () => void) => () => void;
  /** Keeps `ids` read while held; returns the release. */
  readonly hold: (ids: readonly ReadId[]) => () => void;
  /** A tile's Retry: reads `ids` now, whatever their age; `origin` names the tile shown loading. */
  readonly retry: (ids: readonly ReadId[], origin: string) => void;
  /** Tests only: back to the first state, with every read and timer stopped. */
  readonly reset: () => void;
}

/** Each `ok` slice's time in `body`, over the times kept for the slices that are not `ok` now. */
function goodSlices(
  body: unknown,
  kept: Readonly<Record<string, number>> | undefined,
  at: number,
): Readonly<Record<string, number>> | undefined {
  if (typeof body !== "object" || body === null) return kept;
  const out: Record<string, number> = { ...kept };
  for (const [name, slice] of Object.entries(body)) {
    if (typeof slice !== "object" || slice === null || !("status" in slice)) continue;
    if (slice.status !== "ok") continue;
    const generated = "generated_at" in slice ? Date.parse(String(slice.generated_at)) : NaN;
    out[name] = Number.isFinite(generated) ? generated : at;
  }
  return Object.keys(out).length === 0 ? undefined : out;
}

/** Same JSON, so a re-read that changed nothing keeps the old body and its readers stay still. */
export const sameJson = (a: unknown, b: unknown): boolean =>
  a === b || JSON.stringify(a) === JSON.stringify(b);

export function createAdminReadStore(deps: AdminReadDeps): AdminReadStore {
  let state: AdminReadState = INITIAL;
  const listeners = new Set<() => void>();
  const holds = new Map<ReadId, number>();
  const controllers = new Map<ReadId, AbortController>();
  let timer: unknown = null;
  let watching = false;

  const visible = (): boolean => deps.document?.visibilityState !== "hidden";
  const held = (): ReadId[] => READ_IDS.filter((id) => (holds.get(id) ?? 0) > 0);
  const cycled = (id: ReadId): boolean => CYCLE_READS.includes(id);
  /** A `403` withdrew the area: nothing more is asked for any read (BQ-8). */
  const withdrawn = (): boolean => READ_IDS.some((id) => state[id].phase === "denied");

  function notify(): void {
    for (const listener of [...listeners]) listener();
  }

  function commit<K extends ReadId>(id: K, entry: ReadEntry<ReadBodies[K]>): void {
    state = { ...state, [id]: entry };
    notify();
  }

  /** Aborts every read in flight: an answer that comes later is dropped. */
  function abortAll(): void {
    for (const controller of controllers.values()) controller.abort();
    controllers.clear();
  }

  function settle<K extends ReadId>(id: K, outcome: ReadOutcome<ReadBodies[K]>): void {
    const prev = state[id];
    const at = deps.now();
    const base = { answeredAt: at, inFlight: false } as const;
    switch (outcome.kind) {
      case "ok":
        commit(id, {
          ...base,
          phase: "ok",
          data: sameJson(prev.data, outcome.body) ? prev.data : outcome.body,
          okAt: at,
          sliceGoodAt: goodSlices(outcome.body, prev.sliceGoodAt, at),
        });
        return;
      case "failed":
        commit(id, {
          ...base,
          phase: "failed",
          data: prev.data,
          okAt: prev.okAt,
          sliceGoodAt: prev.sliceGoodAt,
          failedAt: prev.phase === "failed" && prev.failedAt !== undefined ? prev.failedAt : at,
          reason: outcome.reason,
          status: outcome.status,
        });
        return;
      case "not_built":
        commit(id, { ...base, phase: "not_built" });
        return;
      case "denied":
        // The area is withdrawn: every other read stops and no answer stays (S-5330-03).
        abortAll();
        state = { ...cleared(state), [id]: { ...base, phase: "denied", refId: outcome.refId } };
        notify();
    }
  }

  function start(id: ReadId, retriedBy?: string): void {
    if (withdrawn()) return; // the area is gone: nothing more is asked for it
    if (controllers.has(id)) {
      if (retriedBy !== undefined) commit(id, { ...state[id], retriedBy });
      return;
    }
    const controller = new AbortController();
    controllers.set(id, controller);
    commit(id, { ...state[id], inFlight: true, retriedBy });
    void deps.read(id, controller.signal).then((outcome) => {
      if (controllers.get(id) !== controller) return; // stopped meanwhile: its answer is dropped
      controllers.delete(id);
      settle(id, outcome);
    });
  }

  /** How long ago `id` answered; an aborted read never answered, so it is due again at once. */
  const age = (id: ReadId): number => {
    const answeredAt = state[id].answeredAt;
    return answeredAt === undefined ? Infinity : deps.now() - answeredAt;
  };
  const due = (id: ReadId): boolean => age(id) >= REREAD_MS;

  function schedule(): void {
    if (timer !== null) deps.clearTimeout(timer);
    timer = null;
    if (!held().some(cycled) || !visible()) return;
    timer = deps.setTimeout(() => {
      timer = null;
      // A read a Retry answered under half a period ago waits for the next tick (C-5330-08).
      for (const id of held()) if (cycled(id) && age(id) >= REREAD_MS / 2) start(id);
      schedule();
    }, REREAD_MS);
  }

  // Shown again: the cycle reads what is due, and a read first held while hidden is asked now.
  const onVisibility = (): void => {
    if (visible()) {
      for (const id of held()) if (cycled(id) ? due(id) : age(id) === Infinity) start(id);
    }
    schedule();
  };

  function stopAll(): void {
    if (timer !== null) deps.clearTimeout(timer);
    timer = null;
    if (watching) deps.document?.removeEventListener("visibilitychange", onVisibility);
    watching = false;
    abortAll();
    // Leaving the area keeps nothing it read: the next visit starts cold, so no tile shows an old
    // visit's answers as fresh and the render measure is real (C-5330-02).
    state = cleared(state);
    notify();
  }

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    hold: (ids) => {
      for (const id of ids) holds.set(id, (holds.get(id) ?? 0) + 1);
      if (!watching && deps.document !== null) {
        deps.document.addEventListener("visibilitychange", onVisibility);
        watching = true;
      }
      if (visible()) for (const id of ids) if (due(id)) start(id);
      schedule();
      let released = false;
      return () => {
        if (released) return;
        released = true;
        for (const id of ids) holds.set(id, Math.max(0, (holds.get(id) ?? 0) - 1));
        // A route change releases and holds again in one commit: stop only if nothing came back.
        queueMicrotask(() => {
          if (held().length === 0) stopAll();
        });
      };
    },
    retry: (ids, origin) => {
      for (const id of ids) start(id, origin);
    },
    reset: () => {
      stopAll();
      holds.clear();
      state = INITIAL;
      for (const listener of [...listeners]) listener();
    },
  };
}

const browserDeps: AdminReadDeps = {
  now: () => Date.now(),
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
  document: typeof document === "undefined" ? null : document,
  read: (id, signal) => readAdmin(READ_PATHS[id], VET[id], signal, browserDeps),
};

/** The admin area's one store. */
export const adminReads: AdminReadStore = createAdminReadStore(browserDeps);

/** Holds `ids` while the calling view is mounted (and `active`). */
export function useAdminHold(
  ids: readonly ReadId[],
  active = true,
  store: AdminReadStore = adminReads,
): void {
  const key = ids.join(",");
  useEffect(() => {
    if (!active) return undefined;
    return store.hold(key.split(",") as ReadId[]);
  }, [key, active, store]);
}

/**
 * A selection from the store, kept while its JSON is unchanged: a view re-renders only when what it
 * shows changed, not on every answer (a re-read that changed nothing renders nothing).
 */
export function useAdminSelector<T>(
  selector: (state: AdminReadState) => T,
  store: AdminReadStore = adminReads,
): T {
  const memo = useRef<{ state: AdminReadState; selector: typeof selector; value: T } | null>(null);
  const getSnapshot = (): T => {
    const current = store.getState();
    const last = memo.current;
    if (last !== null && last.state === current && last.selector === selector) return last.value;
    const next = selector(current);
    const value = last !== null && sameJson(last.value, next) ? last.value : next;
    memo.current = { state: current, selector, value };
    return value;
  };
  return useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot);
}
