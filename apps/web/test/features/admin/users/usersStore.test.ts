/**
 * E42-S02 (#1023) BQ-1, BQ-7: SCR-121's page store, in the admin read store's idiom. The list reads 50 users a
 * page by cursor; Load more reads the next; a new filter or search drops the pages and the cursor; an expired
 * cursor (`400`) reads again from the first page. A sort orders every user: while more pages remain it reads them
 * first (the header busy), then sorts; a page that fails keeps the rows read so far in the server's order and the
 * sort waits for a Retry. `404`, `405` and `501` are not built; a `403` on any read withdraws the area (BQ-8). The
 * pending invites are read once per entry and after a write. Grants are read only for active and locked non-owner
 * rows, at most four at once, and read again once a row's status changes. After a write the list is read again as
 * deep as it was shown, its rows kept until the last page answers; a walk of pages stops at a repeated cursor or at
 * `MAX_PAGES`. Nothing polls, and a release aborts every read and keeps nothing.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReadOutcome } from "../../../../src/features/admin/overview/adminReads";
import {
  createUsersStore,
  MAX_GRANT_READS,
  MAX_PAGES,
  sortUsers,
  visibleRows,
  type UsersStoreDeps,
} from "../../../../src/features/admin/users/usersStore";
import type { UsersQuery } from "../../../../src/features/admin/users/query";
import {
  userIdOf,
  type Grant,
  type PendingInvite,
  type UserId,
  type UserPage,
  type VettedUser,
} from "../../../../src/features/admin/users/vet";

const hex = (n: number): string => n.toString(16).padStart(12, "0");
const idOf = (n: number): UserId => userIdOf(`0c9b8a7d-6e5f-4a3b-9c2d-${hex(n)}`) as UserId;
const user = (n: number, patch: Partial<VettedUser> = {}): VettedUser => ({
  id: idOf(n),
  username: `user${String(n).padStart(3, "0")}`,
  email: `u${n}@example.com`,
  display_name: null,
  roles: ["viewer"],
  status: "active",
  mfa_enabled: true,
  last_login_at: null,
  ...patch,
});
const page = (users: readonly VettedUser[], nextCursor: string | null = null): UserPage => ({
  items: users,
  hasMore: nextCursor !== null,
  nextCursor,
});
const ok = <T>(body: T): ReadOutcome<T> => ({ kind: "ok", body });
const GRANT: Grant = {
  exchange_account_id: "1c9b8a7d-6e5f-4a3b-9c2d-000000000001",
  level: "trade",
  account_label: "sub_001",
  environment: "live",
};
const CAROL_INVITE: PendingInvite = {
  user_id: idOf(7),
  username: "carol",
  email: "carol@example.com",
  display_name: null,
  role: "viewer",
  expires_at: "2026-11-04T10:00:00+00:00",
  expired: false,
};

interface Pending<T> {
  readonly args: readonly unknown[];
  readonly signal: AbortSignal;
  readonly answer: (outcome: ReadOutcome<T>) => Promise<void>;
}

/** A store whose reads the test answers one by one. */
function setup() {
  const pages: Pending<UserPage>[] = [];
  const invites: Pending<readonly PendingInvite[]>[] = [];
  const grants: Pending<readonly Grant[]>[] = [];
  const deny = vi.fn();
  const settle = async (): Promise<void> => {
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  };
  const pend =
    <T>(list: Pending<T>[]) =>
    (...args: unknown[]): Promise<ReadOutcome<T>> =>
      new Promise((resolve) => {
        const signal = args.at(-1) as AbortSignal;
        list.push({
          args: args.slice(0, -1),
          signal,
          answer: async (outcome) => {
            resolve(outcome);
            await settle();
          },
        });
      });
  const deps: UsersStoreDeps = {
    now: () => Date.UTC(2026, 10, 2, 10, 0, 0),
    readPage: pend(pages) as UsersStoreDeps["readPage"],
    readInvites: pend(invites) as UsersStoreDeps["readInvites"],
    readGrants: pend(grants) as UsersStoreDeps["readGrants"],
    deny,
  };
  const store = createUsersStore(deps);
  const last = <T>(list: Pending<T>[]): Pending<T> => {
    const found = list.at(-1);
    if (found === undefined) throw new Error("no read");
    return found;
  };
  return { store, pages, invites, grants, deny, last, settle };
}

const usernames = (rows: readonly VettedUser[]): string[] => rows.map((u) => u.username);

afterEach(() => vi.restoreAllMocks());

describe("the users page store: pages", () => {
  it("reads the first page for the query, then the invites, once", async () => {
    const { store, pages, invites, last } = setup();
    const query: UsersQuery = { role: "manager" };
    store.setQuery(query);
    expect(store.getState().list.phase).toBe("loading");
    expect(pages).toHaveLength(1);
    expect(last(pages).args).toEqual([query, undefined]);
    expect(invites).toHaveLength(1);
    await last(pages).answer(ok(page([user(1), user(2)], "c1")));
    expect(store.getState().list).toMatchObject({ phase: "ok", hasMore: true, failure: null });
    expect(usernames(store.getState().list.rows)).toEqual(["user001", "user002"]);
    expect(store.getState().list.okAt).toBe(Date.UTC(2026, 10, 2, 10, 0, 0));
    // The same query again (a re-render, StrictMode) reads nothing more.
    store.setQuery({ role: "manager" });
    expect(pages).toHaveLength(1);
    expect(invites).toHaveLength(1);
  });

  it("Load more reads the next page by its cursor and appends it", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1)], "c1")));
    store.loadMore();
    expect(store.getState().list.loadingMore).toBe(true);
    expect(last(pages).args).toEqual([{}, "c1"]);
    store.loadMore(); // in flight: no second request
    expect(pages).toHaveLength(2);
    await last(pages).answer(ok(page([user(2)])));
    expect(usernames(store.getState().list.rows)).toEqual(["user001", "user002"]);
    expect(store.getState().list).toMatchObject({ hasMore: false, loadingMore: false });
    store.loadMore(); // nothing more to read
    expect(pages).toHaveLength(2);
  });

  it("a new filter drops the pages and the cursor and aborts the read in flight", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1)], "c1")));
    store.loadMore();
    const stale = last(pages);
    store.setQuery({ status: "disabled" });
    expect(stale.signal.aborted).toBe(true);
    expect(last(pages).args).toEqual([{ status: "disabled" }, undefined]);
    expect(store.getState().list).toMatchObject({ phase: "loading", rows: [], hasMore: false });
    await stale.answer(ok(page([user(9)])));
    expect(store.getState().list.rows).toEqual([]);
    await last(pages).answer(ok(page([user(3, { status: "disabled" })])));
    expect(usernames(store.getState().list.rows)).toEqual(["user003"]);
  });

  it("an expired cursor (400) reads again from the first page", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1)], "c1")));
    store.loadMore();
    await last(pages).answer({ kind: "failed", reason: "status", status: 400 });
    expect(last(pages).args).toEqual([{}, undefined]);
    expect(store.getState().list).toMatchObject({ phase: "ok", failure: null }); // rows kept meanwhile
    expect(usernames(store.getState().list.rows)).toEqual(["user001"]);
    await last(pages).answer(ok(page([user(1), user(2)])));
    expect(usernames(store.getState().list.rows)).toEqual(["user001", "user002"]);
    expect(store.getState().list.failure).toBeNull();
  });

  it("a cursor the server keeps refusing restarts the walk once, then fails it (no loop)", async () => {
    const { store, pages, last } = setup();
    const refused = { kind: "failed", reason: "status", status: 400 } as const;
    store.setQuery({});
    await last(pages).answer(ok(page([user(2)], "c1")));
    store.sortBy({ columnId: "user", direction: "ascending" });
    await last(pages).answer(refused); // the cursor expired: from the first page, once
    expect(last(pages).args).toEqual([{}, undefined]);
    await last(pages).answer(ok(page([user(2)], "c1")));
    await last(pages).answer(refused); // refused again: the walk fails as a page does
    expect(pages).toHaveLength(4);
    expect(store.getState().list).toMatchObject({
      phase: "ok",
      sort: null,
      sortPending: null,
      failure: { reason: "status", status: 400 },
    });
    store.retry(); // a user action starts a new walk, with its own restart
    expect(last(pages).args).toEqual([{}, "c1"]);
    await last(pages).answer(refused);
    expect(pages).toHaveLength(6);
  });

  it("a failed first page fails the list; Retry reads it again", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer({ kind: "failed", reason: "status", status: 503 });
    expect(store.getState().list).toMatchObject({
      phase: "failed",
      failure: { reason: "status", status: 503 },
    });
    store.retry();
    expect(pages).toHaveLength(2);
    await last(pages).answer(ok(page([user(1)])));
    expect(store.getState().list).toMatchObject({ phase: "ok", failure: null });
  });

  it("a failed later page keeps the rows; Retry reads it again", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1)], "c1")));
    store.loadMore();
    await last(pages).answer({ kind: "failed", reason: "timeout" });
    expect(store.getState().list).toMatchObject({ phase: "ok", failure: { reason: "timeout" } });
    expect(usernames(store.getState().list.rows)).toEqual(["user001"]);
    store.retry();
    expect(last(pages).args).toEqual([{}, "c1"]);
  });

  it.each(["not_built"] as const)(
    "a list answered %s is not built; the invites still read",
    async (kind) => {
      const { store, pages, invites, last } = setup();
      store.setQuery({});
      await last(pages).answer({ kind });
      expect(store.getState().list.phase).toBe("not_built");
      await last(invites).answer(ok([]));
      expect(store.getState().invites.phase).toBe("ok");
    },
  );

  it("a 403 on any read withdraws the area: deny with its Ref, everything stopped and dropped", async () => {
    const { store, pages, invites, deny, last } = setup();
    store.setQuery({});
    await last(pages).answer({ kind: "denied", refId: "urn:cv:req:9" });
    expect(deny).toHaveBeenCalledWith("urn:cv:req:9");
    expect(last(invites).signal.aborted).toBe(true);
    expect(store.getState().list).toMatchObject({ phase: "denied", rows: [] });
    store.setQuery({ role: "owner" });
    store.retry();
    expect(pages).toHaveLength(1);
  });

  it("upserts a write's answer in place: the row never moves", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1), user(2), user(3)])));
    store.upsert(user(2, { status: "disabled" }));
    expect(usernames(store.getState().list.rows)).toEqual(["user001", "user002", "user003"]);
    expect(store.getState().list.rows[1]?.status).toBe("disabled");
  });

  it("invalidate re-reads the list (keeping its rows meanwhile) and the invites", async () => {
    const { store, pages, invites, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1)])));
    await last(invites).answer(ok([]));
    store.invalidate();
    expect(pages).toHaveLength(2);
    expect(invites).toHaveLength(2);
    expect(store.getState().list.phase).toBe("ok");
    expect(usernames(store.getState().list.rows)).toEqual(["user001"]);
    await last(pages).answer(ok(page([user(1), user(4)])));
    expect(usernames(store.getState().list.rows)).toEqual(["user001", "user004"]);
  });

  it("invalidate re-reads every page shown, the rows kept until the last answers (A-1023-07)", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1)], "c1")));
    store.loadMore();
    await last(pages).answer(ok(page([user(2)], "c2"))); // two pages shown, more on the server
    store.invalidate();
    expect(last(pages).args).toEqual([{}, undefined]);
    expect(store.getState().list.loadingMore).toBe(false);
    await last(pages).answer(ok(page([user(1)], "d1")));
    // the second page's row is still shown while its page is read again
    expect(usernames(store.getState().list.rows)).toEqual(["user001", "user002"]);
    expect(last(pages).args).toEqual([{}, "d1"]);
    await last(pages).answer(ok(page([user(2, { status: "disabled" })], "d2")));
    expect(usernames(store.getState().list.rows)).toEqual(["user001", "user002"]);
    expect(store.getState().list.rows[1]?.status).toBe("disabled");
    expect(store.getState().list).toMatchObject({ phase: "ok", hasMore: true, nextCursor: "d2" });
    expect(pages).toHaveLength(4); // as deep as it was shown, no deeper
  });

  it("a re-read after a write that fails keeps the rows; its Retry reads every page again", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1)], "c1")));
    store.loadMore();
    await last(pages).answer(ok(page([user(2)])));
    store.invalidate();
    await last(pages).answer(ok(page([user(1)], "d1")));
    await last(pages).answer({ kind: "failed", reason: "timeout" });
    expect(usernames(store.getState().list.rows)).toEqual(["user001", "user002"]);
    expect(store.getState().list).toMatchObject({ phase: "ok", failure: { reason: "timeout" } });
    store.retry();
    expect(last(pages).args).toEqual([{}, undefined]);
    await last(pages).answer(ok(page([user(1)], "e1")));
    expect(last(pages).args).toEqual([{}, "e1"]);
    await last(pages).answer(ok(page([user(2)])));
    expect(store.getState().list.failure).toBeNull();
  });

  it("invalidate on a list that is not built reads the invites alone (C-1023-09)", async () => {
    const { store, pages, invites, last } = setup();
    store.setQuery({});
    await last(pages).answer({ kind: "not_built" });
    await last(invites).answer(ok([]));
    store.invalidate();
    expect(pages).toHaveLength(1);
    expect(invites).toHaveLength(2);
    expect(store.getState().list.phase).toBe("not_built");
  });

  it("a walk that meets a cursor it followed stops, as a failed page: the sort waits (C-1023-04)", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(2)], "c1")));
    store.sortBy({ columnId: "user", direction: "ascending" });
    await last(pages).answer(ok(page([user(1)], "c1"))); // the same cursor again
    expect(pages).toHaveLength(2);
    expect(store.getState().list).toMatchObject({
      sort: null,
      sortPending: null,
      failure: { reason: "unreadable" },
    });
    expect(usernames(visibleRows(store.getState()))).toEqual(["user002", "user001"]);
  });

  it("a walk stops at MAX_PAGES pages, as a failed page", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(0)], "c1")));
    store.sortBy({ columnId: "user", direction: "ascending" });
    for (let n = 1; pages.length > n; n += 1) {
      await last(pages).answer(ok(page([user(n)], `c${n + 1}`)));
    }
    expect(MAX_PAGES).toBe(100);
    expect(pages).toHaveLength(MAX_PAGES);
    expect(store.getState().list).toMatchObject({ sort: null, failure: { reason: "unreadable" } });
  });

  it("release aborts every read, keeps nothing, and a new query starts cold", async () => {
    const { store, pages, invites, last } = setup();
    store.setQuery({});
    const first = last(pages);
    store.release();
    expect(first.signal.aborted).toBe(true);
    expect(last(invites).signal.aborted).toBe(true);
    await first.answer(ok(page([user(1)])));
    expect(store.getState().list.rows).toEqual([]);
    expect(store.getState().list.phase).toBe("idle");
    store.setQuery({});
    expect(pages).toHaveLength(2);
    expect(invites).toHaveLength(2);
  });

  it("keeps no timer: nothing polls", async () => {
    vi.useFakeTimers();
    try {
      const { store, pages, last } = setup();
      store.setQuery({});
      await last(pages).answer(ok(page([user(1)])));
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("the users page store: a sort orders every user", () => {
  it("reads the remaining pages first (the header busy), then sorts", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(3), user(1)], "c1")));
    store.sortBy({ columnId: "user", direction: "ascending" });
    expect(store.getState().list).toMatchObject({ sortPending: "user", sort: null });
    expect(last(pages).args).toEqual([{}, "c1"]);
    await last(pages).answer(ok(page([user(2)], "c2")));
    expect(last(pages).args).toEqual([{}, "c2"]);
    await last(pages).answer(ok(page([user(0)])));
    const list = store.getState().list;
    expect(list).toMatchObject({
      sortPending: null,
      sort: { columnId: "user", direction: "ascending" },
      hasMore: false,
    });
    expect(usernames(visibleRows(store.getState()))).toEqual([
      "user000",
      "user001",
      "user002",
      "user003",
    ]);
    // The rows themselves stay in the server's order.
    expect(usernames(list.rows)).toEqual(["user003", "user001", "user002", "user000"]);
  });

  it("sorts at once when every page is read", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(2), user(1)])));
    store.sortBy({ columnId: "user", direction: "descending" });
    expect(pages).toHaveLength(1);
    expect(usernames(visibleRows(store.getState()))).toEqual(["user002", "user001"]);
  });

  it("a failed page keeps the rows in the server's order with no sort, until a Retry completes it", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(3), user(1)], "c1")));
    store.sortBy({ columnId: "user", direction: "ascending" });
    await last(pages).answer({ kind: "failed", reason: "network" });
    expect(store.getState().list).toMatchObject({
      sort: null,
      sortPending: null,
      failure: { reason: "network" },
    });
    expect(usernames(visibleRows(store.getState()))).toEqual(["user003", "user001"]);
    store.retry();
    expect(store.getState().list.sortPending).toBe("user");
    await last(pages).answer(ok(page([user(2)])));
    expect(store.getState().list.sort).toEqual({ columnId: "user", direction: "ascending" });
    expect(usernames(visibleRows(store.getState()))).toEqual(["user001", "user002", "user003"]);
  });

  it("while a sort is set a new filter reads every page before the rows show", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(2), user(1)])));
    store.sortBy({ columnId: "user", direction: "ascending" });
    store.setQuery({ role: "viewer" });
    expect(store.getState().list).toMatchObject({ phase: "loading", sortPending: "user" });
    await last(pages).answer(ok(page([user(5)], "c1")));
    expect(store.getState().list.phase).toBe("loading");
    await last(pages).answer(ok(page([user(4)])));
    expect(store.getState().list).toMatchObject({ phase: "ok", sortPending: null });
    expect(usernames(visibleRows(store.getState()))).toEqual(["user004", "user005"]);
  });

  it("sortBy(null) returns to the server's order", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(2), user(1)])));
    store.sortBy({ columnId: "user", direction: "ascending" });
    expect(usernames(visibleRows(store.getState()))).toEqual(["user001", "user002"]);
    store.sortBy(null);
    expect(store.getState().list).toMatchObject({ sort: null, sortPending: null });
    expect(usernames(visibleRows(store.getState()))).toEqual(["user002", "user001"]);
  });

  it("sortBy(null) in the middle of a walk clears the busy header", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(2)], "c1")));
    store.sortBy({ columnId: "user", direction: "ascending" });
    expect(store.getState().list.sortPending).toBe("user");
    store.sortBy(null);
    expect(store.getState().list).toMatchObject({ sort: null, sortPending: null });
    await last(pages).answer(ok(page([user(1)])));
    expect(store.getState().list).toMatchObject({ sort: null, sortPending: null });
  });

  it("a re-read under a sort that meets a repeated cursor drops the sort, as a failed page", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(2)], "c1")));
    store.sortBy({ columnId: "user", direction: "ascending" });
    await last(pages).answer(ok(page([user(1)])));
    expect(store.getState().list.sort).not.toBeNull();
    store.invalidate();
    await last(pages).answer(ok(page([user(2)], "c1")));
    await last(pages).answer(ok(page([user(1)], "c1"))); // the same cursor again
    expect(store.getState().list).toMatchObject({
      sort: null,
      sortPending: null,
      failure: { reason: "unreadable" },
    });
  });

  it("a sort asked while a page is on the wire is applied by that read, which reads on", async () => {
    const { store, pages, last } = setup();
    store.setQuery({});
    store.sortBy({ columnId: "user", direction: "descending" }); // the first page is still on the wire
    expect(pages).toHaveLength(1);
    expect(store.getState().list.sortPending).toBe("user");
    await last(pages).answer(ok(page([user(1)], "c1")));
    expect(last(pages).args).toEqual([{}, "c1"]);
    await last(pages).answer(ok(page([user(2)])));
    expect(store.getState().list.sort).toEqual({ columnId: "user", direction: "descending" });
    expect(usernames(visibleRows(store.getState()))).toEqual(["user002", "user001"]);
  });

  it("orders each column: role by rank, sign-in by time with never last, status by its word", () => {
    const rows = [
      user(1, { roles: ["viewer"], last_login_at: null, status: "locked" }),
      user(2, { roles: ["owner"], last_login_at: "2026-11-01T09:00:00Z", status: "active" }),
      user(3, { roles: ["manager"], last_login_at: "2026-10-01T09:00:00Z", status: "disabled" }),
    ];
    const order = (
      columnId: "role" | "lastSignIn" | "status",
      direction: "ascending" | "descending",
    ) => usernames(sortUsers(rows, { columnId, direction }));
    expect(order("role", "ascending")).toEqual(["user002", "user003", "user001"]);
    expect(order("lastSignIn", "ascending")).toEqual(["user003", "user002", "user001"]);
    expect(order("lastSignIn", "descending")).toEqual(["user002", "user003", "user001"]);
    expect(order("status", "ascending")).toEqual(["user002", "user003", "user001"]);
  });

  it("ranks a user by the highest of several roles, and one with none last", () => {
    const rows = [
      user(1, { roles: ["viewer", "owner"] }),
      user(2, { roles: [] }),
      user(3, { roles: ["manager"] }),
      user(4, { roles: ["viewer"] }),
    ];
    expect(usernames(sortUsers(rows, { columnId: "role", direction: "ascending" }))).toEqual([
      "user001",
      "user003",
      "user004",
      "user002",
    ]);
  });
});

describe("the users page store: invites and grants", () => {
  it("keys the pending invites by their user", async () => {
    const { store, invites, last } = setup();
    store.setQuery({});
    await last(invites).answer(
      ok([
        {
          user_id: idOf(7),
          username: "carol",
          email: "carol@example.com",
          display_name: null,
          role: "viewer",
          expires_at: "2026-11-04T10:00:00+00:00",
          expired: false,
        },
      ]),
    );
    expect(store.getState().invites.byUser[idOf(7)]).toMatchObject({ username: "carol" });
  });

  it("reads grants for active and locked non-owner rows only, at most four at once", async () => {
    const { store, pages, grants, last } = setup();
    store.setQuery({});
    const rows = [
      user(1, { roles: ["owner"] }),
      user(2, { status: "invited" }),
      user(3, { status: "disabled" }),
      user(4, { status: "unknown" }),
      ...[5, 6, 7, 8, 9, 10].map((n) =>
        user(n, { roles: ["manager"], status: n === 6 ? "locked" : "active" }),
      ),
    ];
    await last(pages).answer(ok(page(rows)));
    expect(MAX_GRANT_READS).toBe(4);
    expect(grants.map((g) => g.args[0])).toEqual([idOf(5), idOf(6), idOf(7), idOf(8)]);
    await grants[0]?.answer(ok([]));
    expect(grants.map((g) => g.args[0])).toEqual([idOf(5), idOf(6), idOf(7), idOf(8), idOf(9)]);
    expect(store.getState().grants[idOf(5)]).toEqual({ phase: "ok", items: [] });
    expect(store.getState().grants[idOf(9)]).toEqual({ phase: "loading", items: [] });
    for (const g of grants.slice(1)) await g.answer(ok([]));
    await last(grants).answer(ok([]));
    expect(grants).toHaveLength(6);
    expect(Object.keys(store.getState().grants)).toHaveLength(6);
  });

  it("a changed status reads a row's grants again: Disable drops them, Enable reads them anew (C-1023-01)", async () => {
    const { store, pages, grants, last } = setup();
    store.setQuery({});
    const alex = user(1, { roles: ["manager"] });
    await last(pages).answer(ok(page([alex])));
    await last(grants).answer(ok([GRANT]));
    expect(store.getState().grants[idOf(1)]).toEqual({ phase: "ok", items: [GRANT] });
    store.upsert({ ...alex, status: "disabled" }); // a disable revokes every grant (`22` updateUser)
    expect(store.getState().grants[idOf(1)]).toBeUndefined();
    expect(grants).toHaveLength(1); // a disabled row reads none
    store.upsert({ ...alex, status: "active" }); // an enable never restores them: read anew
    expect(grants).toHaveLength(2);
    expect(store.getState().grants[idOf(1)]).toEqual({ phase: "loading", items: [] });
    await last(grants).answer(ok([]));
    expect(store.getState().grants[idOf(1)]).toEqual({ phase: "ok", items: [] });
  });

  it("a grants answer for a row whose status changed meanwhile is dropped; the new read stands", async () => {
    const { store, pages, grants, last } = setup();
    store.setQuery({});
    const alex = user(1, { roles: ["manager"] });
    await last(pages).answer(ok(page([alex])));
    const first = last(grants);
    store.upsert({ ...alex, status: "locked" });
    expect(first.signal.aborted).toBe(true);
    expect(grants).toHaveLength(2);
    await first.answer(ok([GRANT]));
    expect(store.getState().grants[idOf(1)]).toEqual({ phase: "loading", items: [] });
    await last(grants).answer(ok([]));
    expect(store.getState().grants[idOf(1)]).toEqual({ phase: "ok", items: [] });
  });

  it("a pending-invites read refused 403 withdraws the area", async () => {
    const { store, invites, deny, last } = setup();
    store.setQuery({});
    await last(invites).answer({ kind: "denied", refId: "urn:cv:req:11" });
    expect(deny).toHaveBeenCalledWith("urn:cv:req:11");
    expect(store.getState().list.phase).toBe("denied");
  });

  it("a failed invites read keeps its last items and says why; Retry reads them again", async () => {
    const { store, pages, invites, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1)])));
    await last(invites).answer(ok([CAROL_INVITE]));
    store.invalidate();
    await last(invites).answer({ kind: "failed", reason: "status", status: 503 });
    expect(store.getState().invites).toMatchObject({
      phase: "failed",
      items: [{ username: "carol" }],
      failure: { reason: "status", status: 503 },
    });
    store.retry();
    expect(invites).toHaveLength(3);
    await last(invites).answer(ok([]));
    expect(store.getState().invites).toMatchObject({ phase: "ok", items: [], failure: null });
  });

  it("a grants read refused 403 withdraws the area", async () => {
    const { store, pages, grants, deny, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1, { roles: ["manager"] })])));
    await last(grants).answer({ kind: "denied", refId: undefined });
    expect(deny).toHaveBeenCalledWith(undefined);
    expect(store.getState().list.phase).toBe("denied");
  });

  it("release aborts the grants in flight", async () => {
    const { store, pages, grants, last } = setup();
    store.setQuery({});
    await last(pages).answer(ok(page([user(1, { roles: ["manager"] })])));
    store.release();
    expect(last(grants).signal.aborted).toBe(true);
    expect(store.getState().grants).toEqual({});
  });
});
