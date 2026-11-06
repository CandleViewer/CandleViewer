/**
 * SCR-121's page store (E42-S02; BQ-1, BQ-7), in the admin read store's idiom (`overview/readStore.ts`): injected
 * reads and clock, one store per page mount (nothing kept after it goes). The list reads 50 users a page by cursor
 * (Load more); a new filter drops the pages; an expired cursor (`400`) reads again from page one, once per walk. A
 * sort orders every user (`listUsers` has no sort, CG-29): it reads the remaining pages first, the header busy
 * (`sortPending`); a failed page keeps the rows read in the server's order until a Retry. A walk stops at a cursor
 * already followed or at `MAX_PAGES`, as a failed page. After a write the list is read again as deep as shown, its
 * rows kept until the last page answers; an unbuilt list reads the invites alone. Invites are read once per entry;
 * grants only for active and locked non-owner rows, four at once, again once a row's status changes. A `403` on
 * any read withdraws the area (`adminReads.deny`, BQ-8). Nothing polls.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { FailReason, ReadOutcome, ReadTimers } from "../overview/adminReads";
import { adminReads, sameJson } from "../overview/readStore";
import type { UsersQuery } from "./query";
import { readGrants, readPendingInvites, readUserPage } from "./usersApi";
import type { Grant, PendingInvite, RoleName, UserId, UserPage, VettedUser } from "./vet";

/** The grid's sortable columns (E42-D03 §7): User, Role, Last sign-in and Status. */
export type UsersSortColumn = "user" | "role" | "lastSignIn" | "status";

/** A sort as CMP-049 asks for it (`TableSort`). */
export interface UsersSort {
  readonly columnId: UsersSortColumn;
  readonly direction: "ascending" | "descending";
}

export interface UsersFailure {
  readonly reason: FailReason;
  readonly status: number | undefined;
}

export interface UsersListState {
  /** `loading` while the first page (or, under a sort, every page) of a new query is read. */
  readonly phase: "idle" | "loading" | "ok" | "failed" | "not_built" | "denied";
  /** Every row read so far, in the server's order. */
  readonly rows: readonly VettedUser[];
  readonly hasMore: boolean;
  readonly nextCursor: string | null;
  /** Load more's read in flight. */
  readonly loadingMore: boolean;
  /** The last read's failure: the first page's (`failed`), or a later one's under the rows kept. */
  readonly failure: UsersFailure | null;
  /** The sort shown (`aria-sort`); null is the server's order. */
  readonly sort: UsersSort | null;
  /** The column whose sort waits on pages still being read: its header is busy. */
  readonly sortPending: UsersSortColumn | null;
  /** When the first page answered (the page header's "as of"). */
  readonly okAt: number | null;
}

export interface UsersInvitesState {
  readonly phase: "idle" | "ok" | "failed" | "not_built";
  /** The last list read, kept through a failed re-read (never "none" for a value not received). */
  readonly items: readonly PendingInvite[];
  /** The pending invites by their user: the list's chips read their expiry. */
  readonly byUser: Readonly<Record<string, PendingInvite>>;
  /** The last read's failure, for its line's words. */
  readonly failure: UsersFailure | null;
}

export interface GrantsEntry {
  readonly phase: "loading" | "ok" | "failed" | "not_built";
  readonly items: readonly Grant[];
}

export interface UsersState {
  readonly query: UsersQuery;
  readonly list: UsersListState;
  readonly invites: UsersInvitesState;
  /** Each eligible row's grants, by user id. */
  readonly grants: Readonly<Record<string, GrantsEntry>>;
}

export interface UsersStoreDeps {
  readonly now: () => number;
  readonly readPage: (
    query: UsersQuery,
    cursor: string | undefined,
    signal: AbortSignal,
  ) => Promise<ReadOutcome<UserPage>>;
  readonly readInvites: (signal: AbortSignal) => Promise<ReadOutcome<readonly PendingInvite[]>>;
  readonly readGrants: (id: UserId, signal: AbortSignal) => Promise<ReadOutcome<readonly Grant[]>>;
  /** The area's refusal: a page read answered `403` withdraws it (SCR-154 N-2). */
  readonly deny: (refId: string | undefined) => void;
}

export interface UsersStore {
  readonly getState: () => UsersState;
  readonly subscribe: (listener: () => void) => () => void;
  /** Reads `query` from its first page, every page while a sort is set; the old pages go. The same query is a no-op. */
  readonly setQuery: (query: UsersQuery) => void;
  /** Reads the next page. */
  readonly loadMore: () => void;
  /** Sorts every user: reads the remaining pages first (the header busy), then sorts. Null is the server's order. */
  readonly sortBy: (sort: UsersSort | null) => void;
  /** Repeats what failed: the first page, the next page or the sort's remaining pages, and the invites. */
  readonly retry: () => void;
  /** A write answered with its user (`PATCH`): the row changes in place; a changed status reads its grants again. */
  readonly upsert: (user: VettedUser) => void;
  /** After a write with no user in its answer: reads the invites and every page shown again, rows kept. */
  readonly invalidate: () => void;
  /** Stops every read and keeps nothing; a later query starts cold. */
  readonly release: () => void;
}

/** At most this many grants reads in flight (CG-11: one call per row). */
export const MAX_GRANT_READS = 4;

/** A walk of pages stops here (5,000 users, far past this screen's scale), as at a cursor already followed. */
export const MAX_PAGES = 100;
/** Restarts from page one after an expired cursor, at most, in one walk (a cursor refused again fails it). */
export const MAX_RESTARTS = 1;

const LIST0: UsersListState = Object.freeze({
  phase: "idle",
  rows: [],
  hasMore: false,
  nextCursor: null,
  loadingMore: false,
  failure: null,
  sort: null,
  sortPending: null,
  okAt: null,
});
const INVITES0: UsersInvitesState = Object.freeze({
  phase: "idle",
  items: [],
  byUser: {},
  failure: null,
});
const INITIAL: UsersState = Object.freeze({
  query: {},
  list: LIST0,
  invites: INVITES0,
  grants: {},
});

/** Rows whose Accounts cell reads grants: an owner reads "all", an invited or disabled user "—" (D13). */
const readsGrants = (user: VettedUser): boolean =>
  (user.status === "active" || user.status === "locked") && !user.roles.includes("owner");
/** What a row's grants were read for: a change of either means they are read again (C-1023-01). */
const grantsKey = (user: VettedUser): string =>
  `${user.status}|${readsGrants(user) ? "eligible" : "none"}`;

/** A later page's rows after the ones read: a row read again takes its place, never a second one. */
function merged(rows: readonly VettedUser[], items: readonly VettedUser[]): VettedUser[] {
  const out = rows.slice();
  const at = new Map(out.map((row, i) => [row.id, i] as const));
  for (const item of items) {
    const i = at.get(item.id);
    if (i === undefined) {
      at.set(item.id, out.length);
      out.push(item);
    } else {
      out[i] = item;
    }
  }
  return out;
}

const RANK: Readonly<Record<RoleName, number>> = { owner: 0, manager: 1, viewer: 2 };
const collator = new Intl.Collator("en", { sensitivity: "base", numeric: true });
const rankOf = (user: VettedUser): number => Math.min(3, ...user.roles.map((role) => RANK[role]));
const byName = (a: VettedUser, b: VettedUser): number =>
  collator.compare(a.username, b.username) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
const signedIn = (user: VettedUser): number | null =>
  user.last_login_at === null ? null : Date.parse(user.last_login_at);

/**
 * Every row sorted on the client (D03 §7): User by name, Role by rank (owner, manager, viewer), Last sign-in by
 * time with "never" last either way, Status by its word; ties by name, so the order is stable.
 */
export function sortUsers(rows: readonly VettedUser[], sort: UsersSort): VettedUser[] {
  const dir = sort.direction === "ascending" ? 1 : -1;
  return rows.slice().sort((a, b) => {
    switch (sort.columnId) {
      case "user":
        return dir * byName(a, b);
      case "role":
        return dir * (rankOf(a) - rankOf(b)) || byName(a, b);
      case "status":
        return dir * collator.compare(a.status, b.status) || byName(a, b);
      case "lastSignIn": {
        const ta = signedIn(a);
        const tb = signedIn(b);
        if (ta === null || tb === null) return ta === tb ? byName(a, b) : ta === null ? 1 : -1;
        return dir * (ta - tb) || byName(a, b);
      }
    }
  });
}

/** The rows as the grid shows them: sorted while a sort is set, else in the server's order. */
export function visibleRows(state: UsersState): readonly VettedUser[] {
  return state.list.sort === null ? state.list.rows : sortUsers(state.list.rows, state.list.sort);
}

export function createUsersStore(deps: UsersStoreDeps): UsersStore {
  let state: UsersState = INITIAL;
  const listeners = new Set<() => void>();
  let listRead: AbortController | null = null;
  /** Whether the list read in flight (or the last one) is a first page. */
  let firstRead = true;
  let invitesRead: AbortController | null = null;
  const grantReads = new Map<string, AbortController>();
  /** Each row's `grantsKey` when its grants were asked for. */
  const grantsFor = new Map<string, string>();
  let queue: UserId[] = [];
  /** How many pages make up the rows shown: what a re-read after a write reads again. */
  let pagesShown = 0;
  /** The cursors this walk of pages has followed (a first page starts a walk): one seen again ends it. */
  let walked = new Set<string>();
  /** A quiet re-read of every page shown, after a write: its rows replace the list's once the last answers. */
  let refresh: {
    readonly pages: number;
    rows: VettedUser[];
    read: number;
    next: string | null;
  } | null = null;
  /** A re-read after a write that failed: its Retry reads every page again. */
  let refreshFailed: number | null = null;
  /** The sort asked for: applied once every page is read; a Retry completes a read that failed. */
  let wanted: UsersSort | null = null;
  /** Restarts from page one after an expired cursor, in this walk; a user action starts a new walk. */
  let restarts = 0;
  /** The invites are read once per entry: the first query of a mount (or after a release). */
  let entered = false;
  /** A `403` withdrew the area: nothing more is asked. */
  let withdrawn = false;

  const notify = (): void => {
    for (const listener of [...listeners]) listener();
  };
  const commit = (next: UsersState): void => {
    state = next;
    notify();
  };
  const setList = (patch: Partial<UsersListState>): void =>
    commit({ ...state, list: { ...state.list, ...patch } });

  function stopReads(): void {
    listRead?.abort();
    listRead = null;
    invitesRead?.abort();
    invitesRead = null;
    for (const controller of grantReads.values()) controller.abort();
    grantReads.clear();
    grantsFor.clear();
    queue = [];
    refresh = null;
    refreshFailed = null;
  }

  /** A `403`: every read stops, every answer goes, and the area is withdrawn (BQ-8). */
  function withdraw(refId: string | undefined): void {
    if (withdrawn) return;
    withdrawn = true;
    stopReads();
    commit({ ...INITIAL, query: state.query, list: { ...LIST0, phase: "denied" } });
    deps.deny(refId);
  }

  // ---- grants: one read per eligible row, at most MAX_GRANT_READS at once ----

  function pumpGrants(): void {
    while (!withdrawn && grantReads.size < MAX_GRANT_READS && queue.length > 0) {
      const id = queue.shift() as UserId;
      const controller = new AbortController();
      grantReads.set(id, controller);
      commit({ ...state, grants: { ...state.grants, [id]: { phase: "loading", items: [] } } });
      void deps.readGrants(id, controller.signal).then((outcome) => {
        if (grantReads.get(id) !== controller) return; // stopped meanwhile: its answer is dropped
        grantReads.delete(id);
        if (outcome.kind === "denied") return withdraw(outcome.refId);
        const entry: GrantsEntry =
          outcome.kind === "ok"
            ? { phase: "ok", items: outcome.body }
            : { phase: outcome.kind, items: [] };
        commit({ ...state, grants: { ...state.grants, [id]: entry } });
        pumpGrants();
      });
    }
  }

  /** A row's grants as read are no longer its own (its status or eligibility changed): they go, unread. */
  function forgetGrants(id: string): void {
    grantReads.get(id)?.abort();
    grantReads.delete(id);
    grantsFor.delete(id);
    queue = queue.filter((queued) => queued !== id);
    if (state.grants[id] === undefined) return;
    const grants = Object.fromEntries(Object.entries(state.grants).filter(([key]) => key !== id));
    commit({ ...state, grants });
  }

  function queueGrants(users: readonly VettedUser[]): void {
    for (const user of users) {
      const key = grantsKey(user);
      const asked = grantsFor.get(user.id);
      if (asked !== undefined && asked !== key) forgetGrants(user.id);
      if (readsGrants(user) && state.grants[user.id] === undefined && !queue.includes(user.id)) {
        grantsFor.set(user.id, key);
        queue.push(user.id);
      }
    }
    pumpGrants();
  }

  // ---- the pending invites ----

  function readInvites(): void {
    if (withdrawn) return;
    invitesRead?.abort();
    const controller = new AbortController();
    invitesRead = controller;
    void deps.readInvites(controller.signal).then((outcome) => {
      if (invitesRead !== controller) return;
      invitesRead = null;
      if (outcome.kind === "denied") return withdraw(outcome.refId);
      const invites: UsersInvitesState =
        outcome.kind === "ok"
          ? {
              phase: "ok",
              items: outcome.body,
              byUser: Object.fromEntries(outcome.body.map((invite) => [invite.user_id, invite])),
              failure: null,
            }
          : outcome.kind === "failed"
            ? {
                ...state.invites,
                phase: "failed",
                failure: { reason: outcome.reason, status: outcome.status },
              }
            : { phase: "not_built", items: [], byUser: {}, failure: null };
      commit({ ...state, invites });
    });
  }

  // ---- the list ----

  /** A walk may follow `next` if not followed yet, within `MAX_PAGES` (C-1023-04). */
  const canFollow = (next: string | null): boolean =>
    next !== null && !walked.has(next) && walked.size < MAX_PAGES - 1;
  /** A walk that cannot go on (a cursor repeated, or `MAX_PAGES` read) ends as a failed page does. */
  const STUCK: UsersFailure = Object.freeze({ reason: "unreadable", status: undefined });

  /** Reads the first page (loading, unless `quiet` keeps the rows) or the next by cursor; a wanted sort reads on. */
  function readList(first: boolean, quiet: boolean): void {
    if (withdrawn) return;
    listRead?.abort();
    const controller = new AbortController();
    listRead = controller;
    firstRead = first;
    if (first) walked = new Set();
    const cursor = first
      ? undefined
      : ((refresh === null ? state.list.nextCursor : refresh.next) ?? undefined);
    if (cursor !== undefined) walked.add(cursor);
    const busy = wanted === null ? null : wanted.columnId;
    if (first && !quiet) {
      setList({ ...LIST0, phase: "loading", sort: state.list.sort, sortPending: busy });
    } else {
      setList({
        loadingMore: !first && wanted === null && refresh === null,
        failure: null,
        sortPending: busy,
      });
    }
    void deps.readPage(state.query, cursor, controller.signal).then((outcome) => {
      if (listRead !== controller) return; // superseded or stopped: its answer is dropped
      listRead = null;
      settlePage(outcome, first);
    });
  }

  /** Reads every page shown again, quietly (after a write, or its Retry). */
  function rereadShown(pages: number): void {
    refresh = { pages: Math.max(1, pages), rows: [], read: 0, next: null };
    refreshFailed = null;
    readList(true, true);
  }

  /** A re-read's page: on until as many as were shown (every one under a sort), then the swap. */
  function settleRefresh(page: UserPage, first: boolean): void {
    const run = refresh;
    if (run === null) return;
    run.rows = first ? page.items.slice() : merged(run.rows, page.items);
    run.read = first ? 1 : run.read + 1;
    run.next = page.nextCursor;
    const wantsMore = page.hasMore && (wanted !== null || run.read < run.pages);
    const more = wantsMore && canFollow(page.nextCursor);
    // A sort needs every page: a walk that cannot go on fails as a page would; without one, what was read shows.
    const stuck = wantsMore && !more && wanted !== null;
    if (more) {
      readList(false, true);
      return;
    }
    refresh = null;
    pagesShown = run.read;
    setList({
      phase: "ok",
      rows: run.rows,
      hasMore: page.hasMore,
      nextCursor: page.nextCursor,
      loadingMore: false,
      failure: stuck ? STUCK : null,
      okAt: deps.now(),
      ...(wanted === null
        ? {}
        : stuck
          ? { sort: null, sortPending: null }
          : { sort: wanted, sortPending: null }),
    });
    queueGrants(run.rows);
  }

  function settlePage(outcome: ReadOutcome<UserPage>, first: boolean): void {
    if (outcome.kind === "denied") return withdraw(outcome.refId);
    if (outcome.kind === "ok") {
      const page = outcome.body;
      if (refresh !== null) return settleRefresh(page, first);
      const follow = wanted !== null && page.hasMore;
      const stuck = follow && !canFollow(page.nextCursor);
      const more = follow && !stuck;
      pagesShown = first ? 1 : pagesShown + 1;
      setList({
        // A new query under a sort shows its rows once every page is read.
        phase: state.list.phase === "loading" && more ? "loading" : "ok",
        rows: first ? page.items.slice() : merged(state.list.rows, page.items),
        hasMore: page.hasMore,
        nextCursor: page.nextCursor,
        loadingMore: false,
        failure: stuck ? STUCK : null,
        okAt: first ? deps.now() : state.list.okAt,
        ...(wanted === null || more
          ? {}
          : stuck
            ? { sort: null, sortPending: null }
            : { sort: wanted, sortPending: null }),
      });
      queueGrants(page.items);
      if (more) readList(false, true);
      return;
    }
    if (outcome.kind === "not_built" && first && refresh === null) {
      setList({ ...LIST0, phase: "not_built" });
      return;
    }
    // An expired cursor: read again from the first page, rows kept; refused again, the walk fails (no loop).
    if (!first && outcome.kind === "failed" && outcome.status === 400 && restarts < MAX_RESTARTS) {
      restarts += 1;
      readList(true, true);
      return;
    }
    const failure: UsersFailure =
      outcome.kind === "failed"
        ? { reason: outcome.reason, status: outcome.status }
        : { reason: "status", status: undefined };
    if (refresh !== null) {
      // A re-read after a write: the rows shown stay; its Retry reads every page again.
      refreshFailed = refresh.pages;
      refresh = null;
    }
    setList({
      phase: first && state.list.phase === "loading" ? "failed" : "ok",
      loadingMore: false,
      failure,
      // The rows read so far stay, in the server's order; the sort waits for a Retry (D03 §7).
      ...(wanted === null ? {} : { sort: null, sortPending: null }),
    });
  }

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setQuery: (query) => {
      if (withdrawn) return;
      if (state.list.phase !== "idle" && sameJson(query, state.query)) return;
      commit({ ...state, query });
      restarts = 0;
      refresh = null;
      refreshFailed = null;
      readList(true, false);
      if (!entered) {
        entered = true;
        readInvites();
      }
    },
    loadMore: () => {
      if (withdrawn || listRead !== null || state.list.phase !== "ok" || !state.list.hasMore)
        return;
      restarts = 0;
      readList(false, false);
    },
    sortBy: (sort) => {
      if (withdrawn) return;
      wanted = sort;
      if (sort === null) {
        setList({ sort: null, sortPending: null });
        return;
      }
      if (state.list.phase !== "ok" && state.list.phase !== "loading") return; // applied once rows exist
      if (listRead !== null) {
        setList({ sortPending: sort.columnId }); // the read in flight reads on and applies it
        return;
      }
      if (!state.list.hasMore) {
        setList({ sort, sortPending: null });
        return;
      }
      restarts = 0;
      readList(false, false);
    },
    retry: () => {
      if (withdrawn) return;
      if (state.invites.phase === "failed") readInvites();
      if (listRead !== null) return;
      restarts = 0;
      if (state.list.phase === "failed") readList(true, false);
      else if (refreshFailed !== null) rereadShown(refreshFailed);
      else if (state.list.failure !== null) readList(firstRead, true);
    },
    upsert: (user) => {
      const at = state.list.rows.findIndex((row) => row.id === user.id);
      if (at < 0) return;
      const rows = state.list.rows.slice();
      rows[at] = user;
      setList({ rows });
      queueGrants([user]);
    },
    invalidate: () => {
      if (withdrawn || state.list.phase === "idle") return;
      readInvites();
      restarts = 0;
      if (state.list.phase === "not_built") return; // nothing to read again: no reload, no second report
      if (state.list.phase === "ok") rereadShown(pagesShown);
      else readList(true, false);
    },
    release: () => {
      stopReads();
      wanted = null;
      restarts = 0;
      entered = false;
      pagesShown = 0;
      walked = new Set();
      if (!withdrawn) state = INITIAL;
      notify();
    },
  };
}

const TIMERS: ReadTimers = {
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** The page's reads in the browser: the users client, and the area's one read store for a refusal. */
export function browserUsersDeps(): UsersStoreDeps {
  return {
    now: () => Date.now(),
    readPage: (query, cursor, signal) => readUserPage(query, cursor, signal, TIMERS),
    readInvites: (signal) => readPendingInvites(signal, TIMERS),
    readGrants: (id, signal) => readGrants(id, signal, TIMERS),
    deny: (refId) => adminReads.deny(refId),
  };
}

/** The page's own store: created with the page, released (every read stopped, nothing kept) when it goes. */
export function useUsersStore(deps?: UsersStoreDeps): UsersStore {
  const [store] = useState(() => createUsersStore(deps ?? browserUsersDeps()));
  useEffect(() => () => store.release(), [store]);
  return store;
}

/** A selection from the page store, kept while its JSON is unchanged (as `useAdminSelector`). */
export function useUsersSelector<T>(store: UsersStore, selector: (state: UsersState) => T): T {
  const memo = useRef<{ state: UsersState; selector: typeof selector; value: T } | null>(null);
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
