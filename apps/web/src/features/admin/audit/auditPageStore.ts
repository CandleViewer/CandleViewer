/**
 * SCR-135's page store (E42-S04; E42-D04 D4, D5, D7, AL-1, AL-8 to AL-10, AL-15 to AL-17; the build
 * plan's §3), one per mounted page, read through `useSyncExternalStore` as #5330's read store is.
 * - Keyset paging (D4): a stack of the cursors read so far; Older reads the page's `next_cursor`,
 *   Newer re-reads the kept cursor before it, Newest starts over. A cursor is never URL state.
 * - One list read in flight: a new filter set aborts the read in flight; a pager press while one
 *   is in flight does nothing. A user read raises `slow` at 400 ms (AL-1, M12, M17); only the
 *   first read shows no rows while it waits.
 * - Page 1 of the shown filter set is re-read every 30 s (`AUDIT_CADENCE`, D5, PROPOSED) while
 *   the page is visible and no list read is in flight, to count the rows above the head row, the
 *   viewer's own reading rows left out (`admin.area_entered` and `admin.audit_read`, which the
 *   page's own reads write; "200+" at the cap); nothing moves until the pill is pressed. A
 *   re-read whose `chain_verified` is false raises `newestPartial` (AL-10).
 * - After a `429` no list read is sent until `Retry-After`; the re-read pauses and nothing is
 *   queued (AL-16). A failed paging read keeps its page and cursors (AL-15, AL-17); a failed first
 *   or filter read shows no rows, a refused one included, so the rows shown are always the set's
 *   in the bar; once the window ends [Retry] sends it. A `422` keeps the page with its field
 *   errors, a `400 invalid_cursor` keeps it with `cursorLost`.
 * - Environment re-filters the loaded rows and sends no read (D7). A Manager's Actor, `q` and `ip`
 *   are never sent (BQ-3).
 * - An Owner's `403 forbidden` withdraws the area: every read stops and nothing more is asked (the
 *   page shows CMP-089 withdrawn); under view-as it is the target's refusal instead (BQ-9).
 * - The last release aborts the read in flight and stops every timer and listener.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  AUDIT_CADENCE,
  forbiddenMeaning,
  queryAuditLog,
  type AuditAnswer,
  type AuditEntry,
  type AuditFailReason,
  type AuditPageBody,
  type AuditQuery,
  type AuditRefusal,
  type AuditTimers,
  type AuditView,
  type FieldError,
} from "./auditReads";
import {
  PAGE_LIMIT,
  filtersKey,
  parseFilters,
  queryOf,
  rowsFor,
  searchOf,
  type AuditFilters,
} from "./auditFilters";

/** D5 (PROPOSED): page 1's re-read; set with the other cadences in `AUDIT_CADENCE`. */
export const REREAD_MS = AUDIT_CADENCE.headRereadMs;
/** AL-1, M12, M17: `audit.slow` from 400 ms. */
export const SLOW_MS = 400;
/** D5: the pill's cap, a page's 200 rows: "200+". */
export const NEW_CAP = PAGE_LIMIT;
/** PROPOSED: a `429` that names no `Retry-After` waits out the per-minute window. */
export const LIMIT_FALLBACK_S = 60;

export type AuditPhase = "idle" | "loading" | "ok" | "failed" | "limited" | "invalid";
/** Why a user read was sent: focus moves to row 1 when a pager press or the pill lands (§5). */
export type ReadMove = "first" | "filter" | "newest" | "newer" | "older";
export type ReadProblem =
  AuditRefusal | { readonly kind: "failed"; readonly reason: AuditFailReason };

/** A page as shown: the set it was read with, the served body and the cursors that reached it. */
export interface ShownPage {
  readonly key: string;
  readonly filters: AuditFilters;
  readonly body: AuditPageBody;
  /** `[null]` on page 1, read without a cursor; the last is this page's own. */
  readonly stack: readonly (string | null)[];
  /** The client's clock when it answered: the header's "as of". */
  readonly at: number;
}

export interface AuditPageState {
  /** The set the bar shows, Environment included. */
  readonly filters: AuditFilters;
  /** Its read key: Environment never changes it (D7). */
  readonly key: string;
  readonly phase: AuditPhase;
  readonly page: ShownPage | null;
  /** The page's rows after Environment's facet: what the grid draws and `audit.count` counts. */
  readonly rows: readonly AuditEntry[];
  /** The user read in flight; a re-read is not one. */
  readonly reading: ReadMove | null;
  readonly slow: boolean;
  /** The last user read's refusal or failure while `phase` is failed, limited or invalid. */
  readonly error: ReadProblem | null;
  /** A `422`'s field errors (AL-17). */
  readonly fieldErrors: readonly FieldError[];
  /** A `400 invalid_cursor` (AL-17): `audit.cursor_lost` under the last row. */
  readonly cursorLost: boolean;
  /** On the client's clock: no list read is sent before it (AL-16). */
  readonly limitedUntil: number | null;
  /** Rows above page 1's head, the viewer's own reading rows left out; `NEW_CAP` is "200+". */
  readonly newCount: number;
  /** The latest re-read of page 1 was not fully checked: `tamper.newest_partial` (AL-10). */
  readonly newestPartial: boolean;
  /** The area is withdrawn: nothing more is read (SCR-154 N-2). */
  readonly denied: { readonly refId: string | undefined } | null;
  /** Bumped each time a user read lands a page. */
  readonly landed: number;
  readonly landedBy: ReadMove | null;
}

export interface AuditPageDeps extends AuditTimers {
  readonly now: () => number;
  /** The document whose visibility pauses the re-read; `null` reads it as always visible. */
  readonly document: Document | null;
  readonly read: (query: AuditQuery, signal: AbortSignal) => Promise<AuditAnswer<AuditPageBody>>;
  /** The Owner's raw log, or a Manager's "My activity". Fixed for the store's life. */
  readonly view: AuditView;
  /** `me.user.id`: whose own reading rows the new-entries count leaves out (D5). */
  readonly ownUserId: () => string | null;
  /** The session views as another user (#1134); false until the shell has a source. */
  readonly viewAs?: (() => boolean) | undefined;
}

export interface AuditPageStore {
  readonly getState: () => AuditPageState;
  readonly subscribe: (listener: () => void) => () => void;
  /** Keeps the page read while held: the first read once visible, then the 30 s re-read. */
  readonly hold: () => () => void;
  /** A new set reads its page 1; Environment alone re-filters the loaded rows (D7). */
  readonly setFilters: (filters: AuditFilters) => void;
  /** Each pager press, the pill and [Retry]: false when nothing was sent. */
  readonly newest: () => boolean;
  readonly newer: () => boolean;
  readonly older: () => boolean;
  readonly retry: () => boolean;
}

/** The pager's ends (D4): page 1 has nothing newer, `has_more: false` nothing older. */
export function pagerOf(state: AuditPageState): {
  readonly atNewest: boolean;
  readonly atOldest: boolean;
  readonly page: number;
} {
  const { page } = state;
  if (page === null) return { atNewest: true, atOldest: true, page: 0 };
  return {
    atNewest: page.stack.length <= 1,
    atOldest: !page.body.meta.has_more,
    page: page.stack.length,
  };
}

interface Request {
  readonly move: ReadMove;
  readonly key: string;
  readonly filters: AuditFilters;
  readonly stack: readonly (string | null)[];
}

const NETWORK: ReadProblem = { kind: "failed", reason: "network" };

/**
 * The rows the viewer's own reading writes, left out of the new-entries count (D5): entering the
 * area, and `admin.audit_read` for each new filter set and each flush of a known one (`22`
 * queryAuditLog, "Audit budget"), so an idle page never counts its own re-reads (C-1135P2-05).
 */
const OWN_READS: ReadonlySet<string> = new Set(["admin.area_entered", "admin.audit_read"]);

export function createAuditPageStore(
  deps: AuditPageDeps,
  filters: AuditFilters = {},
): AuditPageStore {
  const viewAs = deps.viewAs ?? ((): boolean => false);
  let state: AuditPageState = {
    filters,
    key: filtersKey(filters, deps.view),
    phase: "idle",
    page: null,
    rows: [],
    reading: null,
    slow: false,
    error: null,
    fieldErrors: [],
    cursorLost: false,
    limitedUntil: null,
    newCount: 0,
    newestPartial: false,
    denied: null,
    landed: 0,
    landedBy: null,
  };
  const listeners = new Set<() => void>();
  let holds = 0;
  let watching = false;
  let controller: AbortController | null = null;
  let flight: "user" | "reread" | null = null;
  let inFlight: Request | null = null;
  /** The last user read that failed or was refused: [Retry] sends it again. */
  let pending: Request | null = null;
  let slowTimer: unknown = null;
  let rereadTimer: unknown = null;
  let limitTimer: unknown = null;
  /** Page 1's first entry at its last landing; null when page 1 was empty. */
  let head: number | null = null;
  /** When page 1 was last read, by a user read or a re-read. */
  let rereadAt: number | null = null;

  const visible = (): boolean => deps.document?.visibilityState !== "hidden";
  const limited = (): boolean => state.limitedUntil !== null && deps.now() < state.limitedUntil;
  const envOf = (f: AuditFilters): AuditFilters["environment"] =>
    deps.view === "own" ? undefined : f.environment;

  function notify(): void {
    for (const listener of [...listeners]) listener();
  }
  function patch(next: Partial<AuditPageState>): void {
    state = { ...state, ...next };
    notify();
  }
  function clear(handle: unknown): null {
    if (handle !== null) deps.clearTimeout(handle);
    return null;
  }
  function abortFlight(): void {
    controller?.abort();
    controller = null;
    flight = null;
    inFlight = null;
    slowTimer = clear(slowTimer);
  }

  function schedule(): void {
    rereadTimer = clear(rereadTimer);
    if (holds === 0 || state.denied !== null || state.page === null) return;
    if (!visible() || limited()) return;
    rereadTimer = deps.setTimeout(() => {
      rereadTimer = null;
      if (flight === null && !limited()) startReread();
      else schedule(); // a list read in flight: this tick yields to it (BQ-11 as ruled)
    }, REREAD_MS);
  }

  function armLimit(): void {
    limitTimer = clear(limitTimer);
    if (state.limitedUntil === null) return;
    limitTimer = deps.setTimeout(
      () => {
        limitTimer = null;
        const shown = state.page !== null;
        patch({
          limitedUntil: null,
          phase: shown ? "ok" : "failed",
          error: shown ? null : state.error,
        });
        schedule();
      },
      Math.max(0, state.limitedUntil - deps.now()),
    );
  }

  /** A set the shown page was not read with shows no rows: never another set's (C-1135P2-04). */
  function unread(): Partial<AuditPageState> {
    return state.page !== null && state.page.key !== state.key ? { page: null, rows: [] } : {};
  }

  function limit(answer: AuditRefusal): void {
    const until = deps.now() + (answer.retryAfterS ?? LIMIT_FALLBACK_S) * 1_000;
    rereadTimer = clear(rereadTimer);
    patch({
      phase: "limited",
      error: answer,
      limitedUntil: until,
      reading: null,
      slow: false,
      ...unread(),
    });
    armLimit();
  }

  function stopAll(): void {
    rereadTimer = clear(rereadTimer);
    limitTimer = clear(limitTimer);
    if (watching) deps.document?.removeEventListener("visibilitychange", onVisibility);
    watching = false;
    abortFlight();
    const unread = state.page === null && state.phase === "loading";
    patch({ reading: null, slow: false, ...(unread ? { phase: "idle" as const } : {}) });
  }

  function withdraw(answer: AuditRefusal): void {
    stopAll();
    patch({
      denied: { refId: answer.refId },
      phase: "failed",
      error: answer,
      page: null,
      rows: [],
    });
  }

  /** The rows above the head in page 1's re-read, the viewer's own reading rows left out. */
  function countNew(body: AuditPageBody): number {
    const own = deps.ownUserId();
    const mine = (e: AuditEntry): boolean =>
      own !== null && e.actor_user_id === own && OWN_READS.has(e.action);
    const newer = (rows: readonly AuditEntry[]): number => rows.filter((e) => !mine(e)).length;
    if (head === null) return body.meta.has_more ? NEW_CAP : Math.min(NEW_CAP, newer(body.items));
    const at = body.items.findIndex((e) => e.id === head);
    return at < 0 ? NEW_CAP : newer(body.items.slice(0, at));
  }

  function settleUser(request: Request, answer: AuditAnswer<AuditPageBody>): void {
    const now = deps.now();
    if (answer.kind === "ok") {
      const first = request.stack.length === 1;
      if (first) {
        head = answer.body.items[0]?.id ?? null;
        rereadAt = now;
      }
      pending = null;
      patch({
        phase: "ok",
        page: {
          key: request.key,
          filters: request.filters,
          body: answer.body,
          stack: request.stack,
          at: now,
        },
        rows: rowsFor(answer.body.items, envOf(state.filters)),
        reading: null,
        slow: false,
        error: null,
        fieldErrors: [],
        cursorLost: false,
        landed: state.landed + 1,
        landedBy: request.move,
        ...(first ? { newCount: 0, newestPartial: false } : {}),
      });
      schedule();
      return;
    }
    pending = request;
    const settled = { reading: null, slow: false } as const;
    if (answer.kind === "refused") {
      if (answer.status === 429) return limit(answer);
      if (answer.status === 422) {
        return patch({
          ...settled,
          phase: "invalid",
          error: answer,
          fieldErrors: answer.errors ?? [],
        });
      }
      if (answer.status === 400 && answer.code === "invalid_cursor") {
        return patch({ ...settled, phase: "invalid", error: answer, cursorLost: true });
      }
      if (forbiddenMeaning(answer, { viewAs: viewAs() }) === "withdrawn") return withdraw(answer);
    }
    const paging = request.move !== "first" && request.move !== "filter";
    patch({
      ...settled,
      phase: "failed",
      error: answer.kind === "unknown" ? NETWORK : answer,
      ...(paging ? {} : { page: null, rows: [] }),
    });
  }

  function settleReread(answer: AuditAnswer<AuditPageBody>): void {
    if (answer.kind === "ok") {
      rereadAt = deps.now();
      patch({ newCount: countNew(answer.body), newestPartial: !answer.body.chain_verified });
    } else if (answer.kind === "refused") {
      if (answer.status === 429) return limit(answer);
      if (forbiddenMeaning(answer, { viewAs: viewAs() }) === "withdrawn") return withdraw(answer);
    }
    schedule(); // any other failure is silent: the next tick tries again
  }

  function startUser(request: Request): boolean {
    if (holds === 0 || state.denied !== null || limited()) return false;
    if (flight === "user" && request.move !== "filter") return false; // one list read in flight
    abortFlight(); // a new filter set aborts the older read; a re-read always yields
    const c = new AbortController();
    controller = c;
    flight = "user";
    inFlight = request;
    const query = queryOf(
      request.filters,
      request.stack[request.stack.length - 1] ?? null,
      deps.view,
    );
    slowTimer = deps.setTimeout(() => {
      slowTimer = null;
      if (controller === c) patch({ slow: true });
    }, SLOW_MS);
    patch({
      reading: request.move,
      slow: false,
      phase: state.page === null ? "loading" : "ok",
      error: null,
      fieldErrors: [],
      cursorLost: false,
    });
    const land = (answer: AuditAnswer<AuditPageBody>): void => {
      if (controller !== c) return; // aborted or replaced: its answer is dropped
      controller = null;
      flight = null;
      inFlight = null;
      slowTimer = clear(slowTimer);
      settleUser(request, answer);
    };
    void deps.read(query, c.signal).then(land, () => land(NETWORK));
    return true;
  }

  function startReread(): void {
    const page = state.page;
    if (page === null || state.denied !== null) return;
    const c = new AbortController();
    controller = c;
    flight = "reread";
    const query = queryOf(page.filters, null, deps.view);
    const land = (answer: AuditAnswer<AuditPageBody>): void => {
      if (controller !== c) return;
      controller = null;
      flight = null;
      settleReread(answer);
    };
    void deps.read(query, c.signal).then(land, () => land(NETWORK));
  }

  const firstRead = (): Request => ({
    move: "first",
    key: state.key,
    filters: state.filters,
    stack: [null],
  });

  function onVisibility(): void {
    if (!visible()) {
      rereadTimer = clear(rereadTimer);
      return;
    }
    if (state.phase === "idle" && flight === null) {
      startUser(firstRead());
      return;
    }
    const due = rereadAt === null || deps.now() - rereadAt >= REREAD_MS;
    if (due && flight === null && state.page !== null && !limited() && state.denied === null) {
      startReread();
    } else {
      schedule();
    }
  }

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    hold: () => {
      holds += 1;
      if (!watching && deps.document !== null) {
        deps.document.addEventListener("visibilitychange", onVisibility);
        watching = true;
      }
      if (state.phase === "idle" && flight === null && visible()) startUser(firstRead());
      if (limitTimer === null) armLimit();
      schedule();
      let released = false;
      return () => {
        if (released) return;
        released = true;
        holds -= 1;
        // StrictMode releases and holds again in one commit: stop only if nothing came back
        queueMicrotask(() => {
          if (holds === 0) stopAll();
        });
      };
    },
    setFilters: (next) => {
      const key = filtersKey(next, deps.view);
      patch({
        filters: next,
        key,
        rows: state.page === null ? [] : rowsFor(state.page.body.items, envOf(next)),
      });
      if (inFlight?.key === key) return; // already reading this set
      if (state.page?.key === key) {
        if (flight === "user") abortFlight(); // back to the shown set: the other read is dropped
        if (state.reading !== null) patch({ reading: null, slow: false });
        return; // Environment alone, or the shown set again (D7)
      }
      const sent = startUser({ move: "filter", key, filters: next, stack: [null] });
      if (!sent && limited()) patch(unread()); // read once the window ends, by [Retry] (AL-16)
    },
    newest: () => {
      const page = state.page;
      if (page === null) return false;
      return startUser({ move: "newest", key: page.key, filters: page.filters, stack: [null] });
    },
    newer: () => {
      const page = state.page;
      if (page === null || page.stack.length <= 1) return false;
      const stack = page.stack.slice(0, -1);
      return startUser({ move: "newer", key: page.key, filters: page.filters, stack });
    },
    older: () => {
      const page = state.page;
      const next = page?.body.meta.next_cursor;
      if (page === null || !page.body.meta.has_more || typeof next !== "string") return false;
      const stack = [...page.stack, next];
      return startUser({ move: "older", key: page.key, filters: page.filters, stack });
    },
    retry: () => {
      if (state.denied !== null || limited()) return false;
      if (pending !== null && pending.key === state.key) return startUser(pending);
      if (state.page !== null && state.page.key === state.key) return false;
      // the set in the bar, never read or refused: its page 1 (a 429 on a filter change included)
      const move = state.landed === 0 ? "first" : "filter";
      return startUser({ move, key: state.key, filters: state.filters, stack: [null] });
    },
  };
}

const BROWSER: Omit<AuditPageDeps, "view" | "ownUserId" | "viewAs"> = {
  now: () => Date.now(),
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
  document: typeof document === "undefined" ? null : document,
  read: (query, signal) => queryAuditLog(query, { signal }),
};

export interface AuditPageOptions {
  /** Fixed for the page's life: the Owner's log, or a Manager's "My activity". */
  readonly view: AuditView;
  readonly ownUserId: string | null;
  readonly viewAs?: boolean | undefined;
}

/**
 * One page's store, held while the calling view is mounted and fed its filter set (the URL's,
 * through `parseFilters`); the state re-renders the view on every change of the store.
 */
export function useAuditPage(
  filters: AuditFilters,
  options: AuditPageOptions,
): { readonly state: AuditPageState; readonly store: AuditPageStore } {
  const { view } = options;
  const own = useRef(options.ownUserId);
  const viewing = useRef(options.viewAs === true);
  useEffect(() => {
    own.current = options.ownUserId;
    viewing.current = options.viewAs === true;
  }, [options.ownUserId, options.viewAs]);
  const [store] = useState(() =>
    createAuditPageStore(
      { ...BROWSER, view, ownUserId: () => own.current, viewAs: () => viewing.current },
      parseFilters(searchOf(filters), view).filters,
    ),
  );
  useEffect(() => store.hold(), [store]);
  const search = searchOf(filters);
  useEffect(() => {
    store.setFilters(parseFilters(search, view).filters);
  }, [store, search, view]);
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);
  return { state, store };
}
