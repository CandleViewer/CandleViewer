/**
 * E42-S04 (#1135): SCR-135's page store (E42-D04 D4, D5, D7, AL-1, AL-8 to AL-10, AL-15 to AL-17;
 * the plan's §3). Keyset paging from a stack of kept cursors, one list read in flight, the 6 s
 * bound left to the read, page 1 re-read every 30 s while visible and idle to count newer rows
 * (the viewer's own reading rows left out, "200+" at the cap), no list read until a `429`'s
 * `Retry-After` and nothing queued, a failed paging read keeping its page, a refused filter read
 * showing no rows of another set, Environment filtering the loaded rows with no read, and every
 * read and timer stopped on the last release.
 */
import { act, renderHook } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  AuditAnswer,
  AuditPageBody,
  AuditQuery,
} from "../../../../src/features/admin/audit/auditReads";
import type { AuditFilters } from "../../../../src/features/admin/audit/auditFilters";
import {
  NEW_CAP,
  REREAD_MS,
  SLOW_MS,
  createAuditPageStore,
  pagerOf,
  useAuditPage,
  type AuditPageDeps,
} from "../../../../src/features/admin/audit/auditPageStore";
import {
  FakeDocument,
  OWNER_ID,
  REF,
  T0,
  entries,
  entry,
  hangingFetch,
  pageBody,
} from "./fixtures";

interface Call {
  readonly query: AuditQuery;
  readonly signal: AbortSignal;
  readonly answer: (outcome: AuditAnswer<AuditPageBody>) => Promise<void>;
}

/** A store on fake timers whose reads the test answers one by one. */
function setup(over: Partial<AuditPageDeps> = {}, filters = {}) {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  const doc = new FakeDocument();
  const calls: Call[] = [];
  const deps: AuditPageDeps = {
    now: () => Date.now(),
    setTimeout: (run, ms) => setTimeout(run, ms),
    clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    document: doc as unknown as Document,
    view: "raw",
    ownUserId: () => OWNER_ID,
    read: (query, signal) =>
      new Promise((resolve) => {
        calls.push({
          query,
          signal,
          answer: async (outcome) => {
            resolve(outcome);
            await vi.advanceTimersByTimeAsync(0);
          },
        });
      }),
    ...over,
  };
  const store = createAuditPageStore(deps, filters);
  const last = (): Call => {
    const call = calls.at(-1);
    if (call === undefined) throw new Error("no read was asked");
    return call;
  };
  return { store, doc, calls, last };
}

const ok = (body: AuditPageBody): AuditAnswer<AuditPageBody> => ({ kind: "ok", body });
const refused = (status: number, code: string, more: object = {}): AuditAnswer<AuditPageBody> => ({
  kind: "refused",
  status,
  code,
  refId: REF,
  ...more,
});
/** Page 1: 200 rows from id 1,204,300 down, more after it. */
const PAGE_1 = pageBody(entries(200), { next: "c1" });
const PAGE_2 = pageBody(entries(200, 1_204_100), { next: "c2" });
const PAGE_3 = pageBody(entries(10, 1_203_900));

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the first read and the slow line", () => {
  it("test_store_hold_reads_page_1_of_the_filter_set_once", async () => {
    const { store, calls, last } = setup({}, { severity: "error", environment: "live" });
    const release = store.hold();
    const again = store.hold(); // StrictMode's second mount: still one read
    expect(calls).toHaveLength(1);
    expect(last().query).toEqual({ severity: "error", limit: 200 });
    expect(store.getState()).toMatchObject({ phase: "loading", reading: "first", slow: false });
    await last().answer(ok(PAGE_1));
    expect(store.getState()).toMatchObject({ phase: "ok", reading: null, landed: 1 });
    expect(store.getState().page?.stack).toEqual([null]);
    [release, again].forEach((r) => r());
  });

  it("test_store_slow_flag_rises_at_400ms_for_a_user_read", async () => {
    expect(SLOW_MS).toBe(400); // AL-1, M12: `audit.slow` from 400 ms
    const { store, last } = setup();
    const release = store.hold();
    await vi.advanceTimersByTimeAsync(SLOW_MS - 1);
    expect(store.getState().slow).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(store.getState().slow).toBe(true);
    await last().answer(ok(PAGE_1));
    expect(store.getState().slow).toBe(false);
    release();
  });

  it("test_store_hold_while_hidden_asks_nothing_until_the_document_shows", () => {
    const { store, doc, calls } = setup();
    doc.visibilityState = "hidden";
    const release = store.hold();
    expect(calls).toHaveLength(0);
    doc.show("visible");
    expect(calls).toHaveLength(1);
    release();
  });
});

describe("cursor paging (D4)", () => {
  it("test_store_older_and_newer_read_kept_cursors_and_newest_starts_over", async () => {
    const { store, calls, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    expect(pagerOf(store.getState())).toEqual({ atNewest: true, atOldest: false, page: 1 });
    expect(store.older()).toBe(true);
    expect(last().query).toEqual({ limit: 200, cursor: "c1" });
    await last().answer(ok(PAGE_2));
    expect(store.older()).toBe(true);
    expect(last().query.cursor).toBe("c2");
    await last().answer(ok(PAGE_3));
    expect(pagerOf(store.getState())).toEqual({ atNewest: false, atOldest: true, page: 3 });
    expect(store.older()).toBe(false); // has_more: false ends the list
    expect(store.newer()).toBe(true);
    expect(last().query.cursor).toBe("c1"); // the kept cursor, not a new one
    await last().answer(ok(PAGE_2));
    expect(store.getState().page?.stack).toEqual([null, "c1"]);
    expect(store.newest()).toBe(true);
    expect(last().query).toEqual({ limit: 200 });
    await last().answer(ok(PAGE_1));
    expect(store.getState().page?.stack).toEqual([null]);
    expect(store.newer()).toBe(false); // page 1 has nothing newer to read
    expect(calls).toHaveLength(5);
    expect(store.getState()).toMatchObject({ landed: 5, landedBy: "newest" });
    release();
  });

  it("test_store_one_list_read_in_flight_a_new_filter_set_aborts_the_older", async () => {
    const { store, calls, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    expect(store.older()).toBe(true);
    const paging = last();
    expect(store.older()).toBe(false);
    expect(store.newest()).toBe(false);
    expect(calls).toHaveLength(2);
    store.setFilters({ q: "BTC" });
    expect(paging.signal.aborted).toBe(true);
    expect(last().query).toEqual({ q: "BTC", limit: 200 });
    await paging.answer(ok(PAGE_2)); // its late answer is dropped
    expect(store.getState().page?.body).toBe(PAGE_1);
    await last().answer(ok(PAGE_3));
    expect(store.getState().page?.body).toBe(PAGE_3);
    release();
  });

  it("test_store_environment_refilters_the_loaded_rows_and_sends_no_read", async () => {
    const { store, calls, last } = setup();
    const release = store.hold();
    const mixed = pageBody(
      [entry({ id: 3, environment: "live" }), entry({ id: 2, environment: "demo" })],
      { next: "c1" },
    );
    await last().answer(ok(mixed));
    store.setFilters({ environment: "demo" });
    expect(calls).toHaveLength(1);
    expect(store.getState().rows.map((e) => e.id)).toEqual([2]);
    expect(store.getState().page?.body).toBe(mixed);
    expect(store.older()).toBe(true); // the cursor is kept
    expect(last().query).toEqual({ limit: 200, cursor: "c1" });
    release();
  });
});

describe("failures keep what they should (AL-15, AL-17)", () => {
  it("test_store_failed_paging_read_keeps_the_page_and_its_cursors_and_retry_resends", async () => {
    const { store, calls, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    store.older();
    await last().answer(ok(PAGE_2));
    store.older();
    await last().answer(refused(503, "store_unavailable", { retryAfterS: 5 }));
    expect(store.getState()).toMatchObject({ phase: "failed", error: { status: 503 } });
    expect(store.getState().page?.body).toBe(PAGE_2);
    expect(store.getState().page?.stack).toEqual([null, "c1"]);
    expect(store.retry()).toBe(true);
    expect(last().query.cursor).toBe("c2");
    await last().answer(ok(PAGE_3));
    expect(store.getState()).toMatchObject({ phase: "ok", error: null });
    expect(calls).toHaveLength(4);
    release();
  });

  it("test_store_failed_first_or_filter_read_shows_no_rows", async () => {
    const { store, last } = setup();
    const release = store.hold();
    await last().answer({ kind: "failed", reason: "timeout" });
    expect(store.getState()).toMatchObject({ phase: "failed", page: null, rows: [] });
    store.retry();
    await last().answer(ok(PAGE_1));
    store.setFilters({ q: "BTC" });
    await last().answer(refused(503, "store_unavailable"));
    expect(store.getState()).toMatchObject({ phase: "failed", page: null });
    release();
  });

  it("test_store_422_keeps_the_last_page_with_its_field_errors", async () => {
    const { store, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    store.setFilters({ from: "2026-10-22T14:00:00Z", to: "2026-10-22T13:00:00Z" });
    await last().answer(
      refused(422, "validation_failed", { errors: [{ field: "to", rule: "value_error" }] }),
    );
    expect(store.getState()).toMatchObject({
      phase: "invalid",
      fieldErrors: [{ field: "to", rule: "value_error" }],
    });
    expect(store.getState().page?.body).toBe(PAGE_1);
    release();
  });

  it("test_store_400_invalid_cursor_is_cursor_lost_with_paging_still_open", async () => {
    const { store, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    store.older();
    await last().answer(refused(400, "invalid_cursor"));
    expect(store.getState()).toMatchObject({ phase: "invalid", cursorLost: true });
    expect(store.getState().page?.body).toBe(PAGE_1);
    expect(store.older()).toBe(true); // Newer and Older stay enabled (AL-17)
    release();
  });
});

describe("the rate limit (AL-16)", () => {
  it("test_store_429_sends_no_list_read_until_retry_after_and_queues_nothing", async () => {
    const { store, calls, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    store.older();
    await last().answer(refused(429, "rate_limited", { retryAfterS: 12 }));
    expect(store.getState()).toMatchObject({ phase: "limited", limitedUntil: T0 + 12_000 });
    expect(store.getState().page?.body).toBe(PAGE_1);
    expect(store.older()).toBe(false);
    expect(store.newest()).toBe(false);
    expect(store.retry()).toBe(false);
    store.setFilters({ q: "BTC" }); // a URL change meanwhile: recorded, not read
    expect(calls).toHaveLength(2);
    // never the other set's rows under this one (C-1135P2-04)
    expect(store.getState()).toMatchObject({ page: null, rows: [], phase: "limited" });
    await vi.advanceTimersByTimeAsync(12_000);
    expect(store.getState()).toMatchObject({ phase: "failed", limitedUntil: null, page: null });
    expect(calls).toHaveLength(2); // nothing was queued
    expect(store.retry()).toBe(true); // [Retry] sends the set in the bar
    expect(last().query).toEqual({ q: "BTC", limit: 200 });
    release();
  });

  it("test_store_429_on_a_filter_change_shows_no_rows_and_retry_reads_that_set", async () => {
    // C-1135P2-04: the refused read was the filter set's own; the old page never stands under it
    const { store, calls, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    store.setFilters({ severity: "critical" });
    await last().answer(refused(429, "rate_limited", { retryAfterS: 30 }));
    expect(store.getState()).toMatchObject({ phase: "limited", page: null, rows: [] });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(store.getState()).toMatchObject({ phase: "failed", error: { status: 429 } });
    await vi.advanceTimersByTimeAsync(REREAD_MS * 2);
    expect(calls).toHaveLength(2); // no re-read of the old set, nothing queued
    expect(store.retry()).toBe(true);
    expect(last().query).toEqual({ severity: "critical", limit: 200 });
    await last().answer(ok(PAGE_3));
    expect(store.getState()).toMatchObject({ phase: "ok", landedBy: "filter" });
    expect(store.getState().page?.key).toBe(store.getState().key);
    release();
  });

  it("test_store_retry_after_the_limit_resends_the_refused_read", async () => {
    const { store, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    store.older();
    await last().answer(refused(429, "rate_limited", { retryAfterS: 2 }));
    await vi.advanceTimersByTimeAsync(2_000);
    expect(store.retry()).toBe(true);
    expect(last().query).toEqual({ limit: 200, cursor: "c1" });
    release();
  });

  it("test_store_429_pauses_the_30s_reread", async () => {
    const { store, calls, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    expect(calls).toHaveLength(2);
    await last().answer(refused(429, "rate_limited", { retryAfterS: 90 }));
    expect(store.getState().phase).toBe("limited");
    await vi.advanceTimersByTimeAsync(89_000);
    expect(calls).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1_000 + REREAD_MS);
    expect(calls).toHaveLength(3);
    release();
  });
});

describe("the 30 s re-read and the new-entries pill (D5, AL-8, AL-10)", () => {
  it("test_store_rereads_page_1_every_30s_while_visible_and_pauses_while_hidden", async () => {
    const { store, doc, calls, last } = setup({}, { severity: "error" });
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    store.older();
    await last().answer(ok(PAGE_2));
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    expect(calls).toHaveLength(3);
    expect(last().query).toEqual({ severity: "error", limit: 200 }); // page 1, not page 2
    expect(store.getState().reading).toBeNull(); // a re-read is not a user read
    await last().answer(ok(PAGE_1));
    expect(store.getState().page?.body).toBe(PAGE_2); // nothing moves (D5)
    doc.show("hidden");
    await vi.advanceTimersByTimeAsync(REREAD_MS * 3);
    expect(calls).toHaveLength(3);
    doc.show("visible");
    expect(calls).toHaveLength(4); // due: read at once
    release();
  });

  it("test_store_reread_that_lands_while_hidden_arms_nothing_until_visible", async () => {
    // C-1135P2-09: an answer landing on a hidden tab never re-arms the 30 s re-read
    const { store, doc, calls, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    expect(calls).toHaveLength(2);
    doc.show("hidden");
    await last().answer(ok(PAGE_1));
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(REREAD_MS * 3);
    expect(calls).toHaveLength(2);
    doc.show("visible");
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    expect(calls).toHaveLength(3);
    release();
  });

  it("test_store_reread_waits_for_a_user_read_in_flight", async () => {
    const { store, calls, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    await vi.advanceTimersByTimeAsync(REREAD_MS - 100);
    store.older();
    await vi.advanceTimersByTimeAsync(200);
    expect(calls).toHaveLength(2);
    expect(store.getState().slow).toBe(false); // slow is the user read's own; 400 ms not yet
    release();
  });

  it("test_store_counts_rows_above_the_head_without_the_viewers_own_reads", async () => {
    const { store, last } = setup();
    const release = store.hold();
    const head = entries(5, 100);
    await last().answer(ok(pageBody(head)));
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    const mine = entry({ id: 104, action: "admin.area_entered", actor_user_id: OWNER_ID });
    // the page's own re-reads write this one (C-1135P2-05): an idle page never counts itself
    const read = entry({ id: 103, action: "admin.audit_read", actor_user_id: OWNER_ID });
    const theirs = entry({ id: 102, action: "admin.area_entered", actor_user_id: "other" });
    const order = entry({ id: 101, action: "orders.submit", actor_user_id: OWNER_ID });
    await last().answer(ok(pageBody([mine, read, theirs, order, ...head])));
    expect(store.getState().newCount).toBe(2);
    expect(store.getState().newestPartial).toBe(false);
    release();
  });

  it("test_store_reread_past_the_head_is_the_200_plus_cap_and_marks_newest_partial", async () => {
    const { store, last } = setup();
    const release = store.hold();
    await last().answer(ok(pageBody(entries(3, 10))));
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    await last().answer(ok(pageBody(entries(200, 900), { next: "x", chain: false })));
    expect(store.getState().newCount).toBe(NEW_CAP);
    expect(store.getState().newestPartial).toBe(true);
    release();
  });

  it("test_store_empty_page_1_counts_every_new_row", async () => {
    const { store, last } = setup();
    const release = store.hold();
    await last().answer(ok(pageBody([])));
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    await last().answer(ok(pageBody(entries(4, 50, { actor_user_id: "other" }))));
    expect(store.getState().newCount).toBe(4);
    release();
  });

  it("test_store_newest_loads_page_1_and_clears_the_count", async () => {
    const { store, last } = setup();
    const release = store.hold();
    await last().answer(ok(pageBody(entries(5, 100))));
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    await last().answer(ok(pageBody(entries(8, 103, { actor_user_id: "other" }))));
    expect(store.getState().newCount).toBe(3);
    expect(store.newest()).toBe(true);
    await last().answer(ok(pageBody(entries(8, 103))));
    expect(store.getState()).toMatchObject({ newCount: 0, landedBy: "newest" });
    release();
  });
});

describe("refusals that end the page, and the release", () => {
  it("test_store_owner_403_forbidden_withdraws_and_reads_nothing_more", async () => {
    const { store, calls, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    await last().answer(refused(403, "forbidden"));
    expect(store.getState().denied).toEqual({ refId: REF });
    expect(vi.getTimerCount()).toBe(0);
    expect(store.older()).toBe(false);
    store.setFilters({ q: "x" });
    await vi.advanceTimersByTimeAsync(REREAD_MS * 3);
    expect(calls).toHaveLength(2);
    release();
  });

  it("test_store_viewer_or_manager_403_forbidden_withdraws_the_page", async () => {
    // a Viewer holds no `audit:read` (#2083); a Manager who lost it is refused the same way
    const { store, last } = setup({ view: "own" }, { severity: "error" });
    const release = store.hold();
    await last().answer(refused(403, "forbidden"));
    expect(store.getState()).toMatchObject({ phase: "failed", page: null });
    expect(store.getState().denied).toEqual({ refId: REF });
    release();
  });

  it("test_store_403_forbidden_while_viewing_as_is_the_targets_refusal_not_a_withdrawal", async () => {
    const { store, last } = setup({ viewAs: () => true });
    const release = store.hold();
    await last().answer(refused(403, "forbidden"));
    expect(store.getState()).toMatchObject({ phase: "failed", denied: null });
    expect(store.getState().error).toMatchObject({ status: 403, code: "forbidden" });
    release();
  });

  it("test_store_last_release_aborts_the_read_and_stops_every_timer", async () => {
    const { store, doc, last } = setup();
    const release = store.hold();
    await last().answer(ok(PAGE_1));
    store.older();
    const paging = last();
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(paging.signal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(doc.listeners).toBe(0);
    expect(store.getState().reading).toBeNull();
  });
});

describe("My activity: a Manager's projection (AL-25, AL-26; the orchestrator's BQ-3)", () => {
  const ALEX = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002";

  it("test_store_managers_actor_q_and_ip_never_leave_the_client", async () => {
    const crafted: AuditFilters = {
      actor_user_id: OWNER_ID,
      q: "BTC",
      ip: "100.84.12.9",
      severity: "error",
    };
    const { store, calls, last } = setup({ view: "own", ownUserId: () => ALEX }, crafted);
    const release = store.hold();
    expect(last().query).toEqual({ severity: "error", limit: 200 });
    await last().answer(ok(PAGE_1));
    store.setFilters({ ...crafted, q: "ETH", ip: "100.84.12.10" });
    expect(calls).toHaveLength(1); // a Manager's q and ip change nothing that is sent
    store.older();
    expect(Object.keys(last().query).sort()).toEqual(["cursor", "limit", "severity"]);
    release();
  });

  it("test_store_manager_idor_answer_is_shown_as_served_its_denial_row_included", async () => {
    // `22` queryAuditLog Access: another user's `actor_user_id` is replaced by the caller's own
    // and the attempt is recorded once as `admin.audit_denied`, which the Manager reads as their
    // own entry. The client drops nothing: the scope is the server's.
    const { store, last } = setup({ view: "own", ownUserId: () => ALEX });
    const release = store.hold();
    const own = entries(3, 500, { actor_user_id: ALEX, actor_username: "alex" });
    await last().answer(ok(pageBody(own)));
    expect(store.getState().rows).toEqual(own);
    await vi.advanceTimersByTimeAsync(REREAD_MS);
    const denial = entry({
      id: 501,
      action: "admin.audit_denied",
      outcome: "denied",
      actor_user_id: ALEX,
      actor_username: "alex",
      subject_type: null,
      subject_id: null,
      environment: null,
      ip: null,
      session_id: null,
      request_id: "0193f2bb-0000-7000-8000-000000000501",
      entry_hash: null,
      prev_hash: null,
      detail: {},
    });
    await last().answer(ok(pageBody([denial, ...own])));
    expect(store.getState().newCount).toBe(1);
    release();
  });
});

describe("useAuditPage", () => {
  it("test_useAuditPage_reads_on_mount_through_apiFetch_and_aborts_on_unmount", async () => {
    const signals = hangingFetch();
    const { result, unmount } = renderHook(() =>
      useAuditPage({ severity: "critical" }, { view: "raw", ownUserId: OWNER_ID }),
    );
    expect(signals).toHaveLength(1);
    expect(result.current.state).toMatchObject({ phase: "loading", reading: "first" });
    unmount();
    await act(async () => {
      await Promise.resolve();
    });
    expect(signals[0]?.aborted).toBe(true);
  });

  it("test_useAuditPage_under_strict_mode_reads_once_and_a_filter_change_reads_again", async () => {
    const signals = hangingFetch();
    const { rerender, unmount } = renderHook(
      ({ filters }) => useAuditPage(filters, { view: "raw", ownUserId: OWNER_ID }),
      { initialProps: { filters: { severity: "critical" } as AuditFilters }, wrapper: StrictMode },
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(signals).toHaveLength(1);
    expect(signals[0]?.aborted).toBe(false);
    rerender({ filters: { severity: "error" } });
    expect(signals).toHaveLength(2);
    expect(signals[0]?.aborted).toBe(true); // a new filter set aborts the older read
    unmount();
    await act(async () => {
      await Promise.resolve();
    });
    expect(signals[1]?.aborted).toBe(true);
  });
});
