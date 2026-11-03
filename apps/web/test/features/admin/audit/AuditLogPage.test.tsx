/**
 * E42-S04 (#1135): SCR-135 for the Owner at R-360 (E42-D04 §4, D4 to D11, AL-1 to AL-17). The page
 * renders the page store's and the integrity store's state and makes no request of its own: every
 * call here is the stubbed server's record (no network, C-13.5), and every line said is the shell's
 * announcer's (the page owns no live region; E42-S01's BQ-8). The worked example (§1): the Owner
 * `basiltt`, LIVE, 2026-10-22 "as of 14:02:11".
 */
import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as Announcer from "../../../../src/features/app-shell/announcer";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { auditIntegrity } from "../../../../src/features/admin/audit/integrity";
import { resetShellState } from "../../../../src/shell/bootstrap/store";
import {
  BROKEN,
  OWNER_ID,
  REF,
  T0,
  entries,
  entry,
  incident,
  json,
  pageBody,
  problem,
  verifyBody,
} from "./fixtures";
import { AUDIT, INCIDENTS, VERIFY, flush, mountAuditPage, pagesOf, sessionAs } from "./harness";

// The page renders CMP-049's grid, CMP-174 and the shell's announcer from the ui sources: a busy
// host can take seconds over a mount, as with SCR-120's page tests.
vi.setConfig({ testTimeout: 30_000 });

const said = vi.hoisted(() => [] as { politeness: string; text: string }[]);
vi.mock("../../../../src/features/app-shell/announcer", async (importOriginal) => {
  const real = await importOriginal<typeof Announcer>();
  return {
    ...real,
    announce: (politeness: Announcer.Politeness, text: string, key: string): boolean => {
      const written = real.announce(politeness, text, key);
      if (written) said.push({ politeness, text });
      return written;
    },
  };
});

/** What the page has said, politely, in order. */
const polite = (): string[] => said.filter((s) => s.politeness === "polite").map((s) => s.text);
/** The page itself, without the shell's announcer, whose regions repeat its lines. */
const inPage = (): ReturnType<typeof within> => within(screen.getByRole("main"));
const nav = (): HTMLElement => screen.getByRole("navigation", { name: "Pagination" });
const pagerButton = (name: string): HTMLElement =>
  within(nav()).getByRole("button", { name: new RegExp(`${name}$`) });
const describedText = (el: HTMLElement): string =>
  (el.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");
const rowIds = (): number[] =>
  [...document.querySelectorAll<HTMLElement>("tr[data-entry]")].map((row) =>
    Number(row.dataset["entry"]),
  );
const focusedRow = (): number | null => {
  const row = document.activeElement?.closest<HTMLElement>("tr[data-entry]");
  return row === null || row === undefined ? null : Number(row.dataset["entry"]);
};

const PAGE_1 = entries(3, 1_204_300);
const PAGE_2 = entries(3, 1_204_297);
const withNext = (items: readonly ReturnType<typeof entry>[], next: string): Response =>
  json(200, pageBody(items, { next }));

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  said.length = 0;
  clearAnnouncements();
  auditIntegrity.reset();
  sessionAs("owner");
});

afterEach(() => {
  auditIntegrity.reset();
  resetShellState();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("SCR-135 on entry (AL-1, AL-2)", () => {
  it("test_page_entry_reads_page_one_and_the_incidents_with_gets_only", async () => {
    const page = await mountAuditPage({ routes: { audit: pagesOf(PAGE_1) } });
    expect(page.sent.map((s) => `${s.method} ${s.url}`)).toEqual([
      `GET ${AUDIT}?limit=200`,
      `GET ${INCIDENTS}?limit=100`,
    ]);
    page.unmount();
  });

  it("test_page_loading_shows_skeleton_rows_the_bare_meta_and_no_pager_then_slow_at_400ms", async () => {
    const waiting = await mountAuditPage({
      routes: { audit: () => new Promise<Response>(() => undefined) },
    });
    expect(screen.getByRole("heading", { level: 1, name: "Audit log" })).toBeInTheDocument();
    expect(inPage().getByText("All times UTC")).toBeInTheDocument();
    expect(screen.getByRole("grid")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("navigation", { name: "Pagination" })).toBeNull();
    expect(inPage().queryByText("Taking longer than usual…")).toBeNull();
    await flush(400);
    expect(inPage().getByText("Taking longer than usual…")).toBeInTheDocument();
    waiting.unmount();
  });

  it("test_page_populated_states_the_log_append_only_with_its_marker_caption_and_checked_page", async () => {
    const page = await mountAuditPage({ routes: { audit: () => withNext(PAGE_1, "c1") } });
    expect(inPage().getByText("All times UTC · as of 14:02:11")).toBeInTheDocument();
    expect(
      inPage().getByText("Viewing this log is recorded — Audit log viewed (admin.audit_read)"),
    ).toBeInTheDocument();
    expect(
      inPage().getByText("Records can only be added, never edited or deleted. Kept indefinitely."),
    ).toBeInTheDocument();
    expect(screen.getByRole("grid")).toHaveAccessibleName(
      "Audit log, newest first. All times UTC. Role at the time is not recorded yet.",
    );
    expect(rowIds()).toEqual([1_204_300, 1_204_299, 1_204_298]);
    expect(inPage().getByText("Tamper check: this page checked — passed")).toBeInTheDocument();
    // page 1: Newest and Newer are T2 `admin.newest`; Older reads on
    for (const name of ["Newest", "Newer"]) {
      const button = pagerButton(name);
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(describedText(button)).toBe("Already at the start of the list.");
    }
    expect(pagerButton("Older")).not.toHaveAttribute("aria-disabled");
    page.unmount();
  });

  it("test_page_is_one_column_within_the_canvas_and_its_own_stacking_context", async () => {
    // A-1135P2-03: the column never grows past the canvas, so the page reflows at 200 % and 400 %;
    // A-1135P2-05: the grid's sticky header stays inside the page, under SCR-136 and the dialogs
    const page = await mountAuditPage({ routes: { audit: pagesOf(PAGE_1) } });
    const root = document.querySelector<HTMLElement>("[data-view='raw']");
    expect(root).toHaveStyle({ gridTemplateColumns: "minmax(0, 1fr)", isolation: "isolate" });
    page.unmount();
  });

  it("test_page_grid_says_no_line_of_its_own", async () => {
    // A-1135P2-06: CMP-049's own region said "3 rows" at load and "No rows" on a failed read
    const page = await mountAuditPage({ routes: { audit: pagesOf(PAGE_1) } });
    expect(document.querySelector(".cv-table__live")).toBeNull();
    expect(polite()).toEqual([]);
    page.unmount();
  });

  it("test_page_t2_press_says_its_reason_once_per_press_through_the_shell", async () => {
    // A-1135P2-02 (G-T2.3): the shell's gated announcement is a no-op; the page says the reason
    const page = await mountAuditPage({ routes: { audit: () => withNext(PAGE_1, "c1") } });
    fireEvent.click(pagerButton("Newest"));
    await flush();
    fireEvent.click(pagerButton("Newest"));
    await flush();
    expect(polite()).toEqual([
      "Already at the start of the list.",
      "Already at the start of the list.",
    ]);
    expect(page.reads()).toHaveLength(1);
    page.unmount();
  });
});

describe("cursor paging (D4, AL-9)", () => {
  it("test_page_older_reads_the_next_cursor_and_moves_focus_to_its_first_row", async () => {
    const page = await mountAuditPage({
      routes: { audit: pagesOf(withNext(PAGE_1, "c1"), PAGE_2) },
    });
    fireEvent.click(pagerButton("Older"));
    await flush();
    expect(page.reads().map((url) => url.searchParams.get("cursor"))).toEqual([null, "c1"]);
    expect(rowIds()).toEqual([1_204_297, 1_204_296, 1_204_295]);
    expect(focusedRow()).toBe(1_204_297);
    page.unmount();
  });

  it("test_page_last_page_says_audit_end_once_and_older_is_t2_on_that_line", async () => {
    const page = await mountAuditPage({
      routes: { audit: pagesOf(withNext(PAGE_1, "c1"), PAGE_2) },
    });
    fireEvent.click(pagerButton("Older"));
    await flush();
    const older = pagerButton("Older");
    expect(older).toHaveAttribute("aria-disabled", "true");
    expect(describedText(older)).toBe("No older entries.");
    expect(polite()).toEqual(["No older entries."]);
    fireEvent.click(older);
    await flush();
    expect(page.reads()).toHaveLength(2); // a T2 press reads nothing
    page.unmount();
  });

  it("test_page_newer_rereads_the_kept_cursor_before_this_page", async () => {
    const page = await mountAuditPage({
      routes: {
        audit: pagesOf(withNext(PAGE_1, "c1"), withNext(PAGE_2, "c2"), withNext(PAGE_1, "c1")),
      },
    });
    fireEvent.click(pagerButton("Older"));
    await flush();
    fireEvent.click(pagerButton("Newer"));
    await flush();
    expect(page.reads().map((url) => url.searchParams.get("cursor"))).toEqual([null, "c1", null]);
    expect(focusedRow()).toBe(1_204_300);
    page.unmount();
  });

  it("test_page_pager_press_overtaken_by_a_filter_change_moves_no_focus_later", async () => {
    // C-1135P2-14: Older's read never lands (a filter change aborts it); when the first set comes
    // back, its page lands without pulling focus to row 1 from where the user is
    const answers = [withNext(PAGE_1, "c1"), null, json(200, pageBody(PAGE_1.slice(0, 2)))];
    const page = await mountAuditPage({
      routes: {
        audit: (_url, n) =>
          n === 3
            ? json(200, pageBody(PAGE_1))
            : (answers[n] ?? new Promise<Response>(() => undefined)),
      },
    });
    fireEvent.click(pagerButton("Older"));
    await flush();
    await page.router.navigate("/admin/audit?severity=critical");
    await flush();
    expect(rowIds()).toEqual([1_204_300, 1_204_299]);
    const subject = screen.getByRole("textbox", { name: "Subject id" });
    subject.focus();
    await page.router.navigate("/admin/audit");
    await flush();
    expect(page.reads()).toHaveLength(4);
    expect(rowIds()).toEqual([1_204_300, 1_204_299, 1_204_298]);
    expect(document.activeElement).toBe(subject);
    page.unmount();
  });
});

describe("filters (D04 §4 Filters, D7, AL-6, AL-7)", () => {
  it("test_page_text_filter_applies_on_enter_pushes_the_url_and_says_the_count_once", async () => {
    const page = await mountAuditPage({ routes: { audit: pagesOf(PAGE_1, PAGE_1.slice(0, 2)) } });
    const subject = screen.getByRole("textbox", { name: "Subject id" });
    fireEvent.change(subject, { target: { value: "0a000000" } });
    await flush();
    expect(page.reads()).toHaveLength(1); // never per keystroke (BQ-3)
    fireEvent.keyDown(subject, { key: "Enter" });
    await flush();
    expect(page.router.state.location.search).toBe("?subject_id=0a000000");
    expect(page.reads().at(-1)?.searchParams.get("subject_id")).toBe("0a000000");
    expect(polite()).toEqual(["2 entries on this page"]);
    page.unmount();
  });

  it("test_page_environment_refilters_the_loaded_rows_and_sends_no_read", async () => {
    const rows = [entry({ id: 3 }), entry({ id: 2, environment: "demo" }), entry({ id: 1 })];
    const page = await mountAuditPage({ routes: { audit: pagesOf(rows) } });
    await page.router.navigate("/admin/audit?environment=demo");
    await flush();
    expect(page.reads()).toHaveLength(1);
    expect(rowIds()).toEqual([2]);
    expect(polite()).toEqual(["1 entry on this page"]);
    page.unmount();
  });

  it("test_page_filtered_to_nothing_offers_clear_filters_which_focuses_row_one", async () => {
    const events: unknown[] = [];
    const record = (event: Event): void => void events.push((event as CustomEvent).detail);
    window.addEventListener("cv:analytics", record);
    const page = await mountAuditPage({
      routes: { audit: pagesOf([], PAGE_1) },
      search: "?severity=critical",
    });
    // a heading level under the h1, never an h3 straight after it (A-1135P2-08)
    expect(
      screen.getByRole("heading", { level: 2, name: "No records match these filters." }),
    ).toBeVisible();
    expect(events).toEqual([{ name: "empty_state_shown", surface: "SCR-135", reason: "filtered" }]);
    expect(polite()).toEqual(["No records match these filters."]);
    fireEvent.click(
      within(screen.getByRole("grid")).getByRole("button", { name: "Clear filters" }),
    );
    await flush();
    expect(page.router.state.location.search).toBe("");
    expect(page.reads().at(-1)?.searchParams.get("severity")).toBeNull();
    expect(focusedRow()).toBe(1_204_300);
    window.removeEventListener("cv:analytics", record);
    page.unmount();
  });

  it("test_page_clear_filters_with_only_environment_set_focuses_row_one_at_once", async () => {
    // C-1135P2-10: Environment sends no read (D7), so nothing lands; the rows are there already
    const rows = [entry({ id: 3 }), entry({ id: 2, environment: "demo" }), entry({ id: 1 })];
    const page = await mountAuditPage({
      routes: { audit: pagesOf(rows) },
      search: "?environment=testnet",
    });
    const clear = within(screen.getByRole("grid")).getByRole("button", { name: "Clear filters" });
    clear.focus();
    fireEvent.click(clear);
    await flush();
    expect(page.router.state.location.search).toBe("");
    expect(page.reads()).toHaveLength(1);
    expect(focusedRow()).toBe(3);
    page.unmount();
  });

  it("test_page_own_view_says_a_dropped_filter_once", async () => {
    // A-1135P2-13 (AL-26): the own view, as R-360 frames it for a Manager; a crafted link's
    // filter is dropped, the line stays on the page and is said once, politely
    sessionAs("manager");
    const line = "That filter isn't available in your view.";
    const page = await mountAuditPage({
      view: "own",
      routes: { audit: pagesOf(PAGE_1) },
      search: "?q=withdrawal&ip=100.84.12.9",
    });
    expect(inPage().getByText(line)).toBeInTheDocument();
    await flush(10_000);
    expect(polite().filter((text) => text === line)).toEqual([line]);
    page.unmount();
  });
});

describe("refused and failed reads (AL-15, AL-16, AL-17)", () => {
  const ERROR =
    "Couldn't load the audit log — the query took too long or the store is unavailable. Try a shorter time range, or try again at 14:02:41 UTC.";

  it("test_page_503_says_audit_error_with_its_time_and_retry_never_an_empty_list", async () => {
    const page = await mountAuditPage({
      routes: {
        audit: pagesOf(problem(503, "store_unavailable", {}, { "Retry-After": "30" }), PAGE_1),
      },
    });
    expect(inPage().getByText(ERROR)).toBeInTheDocument();
    expect(rowIds()).toEqual([]);
    expect(inPage().queryByText("No records match these filters.")).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Pagination" })).toBeNull();
    expect(inPage().getByText("All times UTC")).toBeInTheDocument();
    expect(polite()).toEqual([ERROR]);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await flush();
    expect(rowIds()).toEqual([1_204_300, 1_204_299, 1_204_298]);
    expect(inPage().queryByText(ERROR)).toBeNull();
    page.unmount();
  });

  it("test_page_failed_paging_read_keeps_its_page_and_focus_on_the_button", async () => {
    const page = await mountAuditPage({
      routes: {
        audit: pagesOf(withNext(PAGE_1, "c1"), problem(503, "store_unavailable", {}, {})),
      },
    });
    const older = pagerButton("Older");
    older.focus();
    fireEvent.click(older);
    await flush();
    expect(rowIds()).toEqual([1_204_300, 1_204_299, 1_204_298]);
    expect(document.activeElement).toBe(older);
    expect(
      inPage().getByText(
        "Couldn't load the audit log — the query took too long or the store is unavailable. Try a shorter time range, or try again.",
      ),
    ).toBeInTheDocument();
    page.unmount();
  });

  it("test_page_429_pauses_every_list_control_behind_one_notice_until_retry_after", async () => {
    const limited = problem(429, "rate_limited", {}, { "Retry-After": "60" });
    const page = await mountAuditPage({
      routes: { audit: pagesOf(withNext(PAGE_1, "c1"), limited, PAGE_2) },
    });
    fireEvent.click(pagerButton("Older"));
    await flush();
    const line =
      "Too many requests — try again at 14:03:11 UTC (in 60 s). Run tamper check and opening records still work.";
    expect(inPage().getByText(line)).toBeInTheDocument();
    expect(inPage().getAllByText("Paused by a rate limit.")).toHaveLength(1);
    for (const name of ["Newest", "Newer", "Older"]) {
      expect(pagerButton(name)).toHaveAttribute("aria-disabled", "true");
      expect(describedText(pagerButton(name))).toBe("Paused by a rate limit.");
    }
    const search = screen.getByRole("search", { name: "Filter the audit log" });
    for (const control of within(search).getAllByRole("textbox")) {
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(describedText(control)).toBe("Paused by a rate limit.");
    }
    expect(polite()).toEqual([line]);
    fireEvent.click(pagerButton("Older"));
    await flush(30_000); // the re-read pauses too: nothing is sent or queued (AL-16)
    expect(page.reads()).toHaveLength(2);
    await flush(30_000);
    expect(pagerButton("Older")).not.toHaveAttribute("aria-disabled");
    expect(page.reads()).toHaveLength(2);
    page.unmount();
  });

  it("test_page_429_on_a_filter_change_shows_no_old_rows_and_retry_reads_the_new_set", async () => {
    // C-1135P2-04: the unfiltered page never stands under the new filter, and once the window
    // ends a line says nothing was loaded and [Retry] sends the set in the bar
    const ended = "The rate limit has passed — nothing was loaded. Retry to load these entries.";
    const limited = problem(429, "rate_limited", {}, { "Retry-After": "30" });
    const page = await mountAuditPage({ routes: { audit: pagesOf(PAGE_1, limited, PAGE_2) } });
    await page.router.navigate("/admin/audit?severity=critical");
    await flush();
    expect(rowIds()).toEqual([]);
    await flush(31_000);
    expect(inPage().getByText(ended)).toBeInTheDocument();
    expect(polite()).toContain(ended);
    await flush(60_000);
    expect(page.reads()).toHaveLength(2); // nothing re-read by itself (AL-16)
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await flush();
    expect(page.reads().at(-1)?.searchParams.get("severity")).toBe("critical");
    expect(rowIds()).toEqual([1_204_297, 1_204_296, 1_204_295]);
    page.unmount();
  });

  it("test_page_422_puts_its_error_under_to_and_reads_nothing_more", async () => {
    const invalid = problem(422, "validation_failed", {
      errors: [{ field: "to", rule: "after_from" }],
    });
    const page = await mountAuditPage({
      routes: { audit: pagesOf(invalid) },
      search: "?from=2026-10-22T14:00:00Z&to=2026-10-22T13:00:00Z",
    });
    expect(inPage().getByText("From must be earlier than To.")).toBeInTheDocument();
    expect(page.reads()).toHaveLength(1);
    page.unmount();
  });

  it("test_page_bad_cursor_says_cursor_lost_once_and_offers_newest", async () => {
    const page = await mountAuditPage({
      routes: {
        audit: pagesOf(withNext(PAGE_1, "c1"), problem(400, "invalid_cursor"), PAGE_1),
      },
    });
    fireEvent.click(pagerButton("Older"));
    await flush();
    const lost = "This page can't be continued. Start again from the newest entries.";
    expect(inPage().getByText(lost)).toBeInTheDocument();
    expect(polite()).toEqual([lost]);
    expect(pagerButton("Older")).not.toHaveAttribute("aria-disabled"); // never T2 (§4 Keys)
    const newest = screen
      .getAllByRole("button", { name: "Newest" })
      .find((button) => !nav().contains(button));
    fireEvent.click(newest as HTMLElement);
    await flush();
    expect(page.reads().at(-1)?.searchParams.get("cursor")).toBeNull();
    expect(inPage().queryByText(lost)).toBeNull();
    page.unmount();
  });
});

describe("new entries (D5, AL-8)", () => {
  it("test_page_pill_counts_newer_rows_but_the_viewers_own_area_entered_and_loads_the_newest", async () => {
    const newer = [
      entry({ id: 1_204_303 }),
      entry({ id: 1_204_302, action: "admin.area_entered", actor_user_id: OWNER_ID }),
      entry({ id: 1_204_301 }),
    ];
    const page = await mountAuditPage({
      routes: { audit: pagesOf(PAGE_1, [...newer, ...PAGE_1]) },
    });
    await flush(30_000);
    const pill = screen.getByRole("button", { name: "2 new entries — show newest" });
    expect(rowIds()).toEqual([1_204_300, 1_204_299, 1_204_298]); // nothing moves until pressed
    expect(polite()).toEqual(["2 new entries — show newest"]);
    fireEvent.click(pill);
    await flush();
    expect(rowIds().slice(0, 3)).toEqual([1_204_303, 1_204_302, 1_204_301]);
    expect(focusedRow()).toBe(1_204_303);
    await flush(5_000);
    expect(polite()).toEqual(["2 new entries — show newest", "2 new entries loaded"]);
    page.unmount();
  });

  it("test_page_failed_pill_read_leaves_no_count_for_a_later_newest_press", async () => {
    // C-1135P2-14: the pill's count is said for the read it pressed only; that read failed, so
    // Newest later loads the newest page without "2 new entries loaded"
    const newer = [entry({ id: 1_204_302 }), entry({ id: 1_204_301 })];
    const failed = problem(503, "store_unavailable", {}, {});
    const page = await mountAuditPage({
      routes: {
        audit: pagesOf(withNext(PAGE_1, "c1"), PAGE_2, [...newer, ...PAGE_1], failed, [
          ...newer,
          ...PAGE_1,
        ]),
      },
    });
    fireEvent.click(pagerButton("Older"));
    await flush(30_000);
    fireEvent.click(screen.getByRole("button", { name: "2 new entries — show newest" }));
    await flush();
    expect(rowIds()).toEqual([1_204_297, 1_204_296, 1_204_295]); // the failed read kept its page
    fireEvent.click(pagerButton("Newest"));
    await flush(20_000);
    expect(rowIds().slice(0, 2)).toEqual([1_204_302, 1_204_301]);
    expect(polite()).not.toContain("2 new entries loaded");
    page.unmount();
  });
});

describe("the withdrawn area (SCR-154 N-2)", () => {
  it("test_page_owner_403_shows_cmp089_withdrawn_calls_the_seam_once_and_reads_nothing_more", async () => {
    const onWithdrawn = vi.fn();
    const page = await mountAuditPage({
      routes: { audit: pagesOf(problem(403, "forbidden")) },
      onWithdrawn,
    });
    expect(screen.queryByRole("grid")).toBeNull();
    expect(inPage().getByText(/Ref/)).toBeInTheDocument();
    expect(onWithdrawn.mock.calls).toEqual([[REF]]);
    await flush(120_000);
    expect(page.reads()).toHaveLength(1);
    page.unmount();
  });
});

describe("Run tamper check and the incident (D10, D11, AL-11 to AL-13, §7)", () => {
  it("test_page_posts_the_check_only_on_press_and_says_its_result_once", async () => {
    const page = await mountAuditPage({
      routes: { audit: pagesOf(PAGE_1), verify: () => json(200, verifyBody()) },
    });
    expect(page.sent.filter((s) => s.method !== "GET")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Run tamper check" }));
    await flush();
    const posts = page.sent.filter((s) => s.method === "POST");
    expect(posts.map((s) => [s.url, s.body])).toEqual([[VERIFY, "{}"]]);
    const passed =
      "Tamper check: entries 204,119–1,204,118 checked at 14:05 UTC — passed. This covers that range only.";
    expect(inPage().getByText(passed)).toBeInTheDocument();
    expect(polite()).toEqual([passed]);
    expect(
      inPage().getByText("Recorded in the audit log · admin.audit_verify"),
    ).toBeInTheDocument();
    page.unmount();
  });

  it("test_page_failed_check_raises_the_banner_once_and_reads_the_incidents_at_once", async () => {
    const title = "Tamper check FAILED at entry 1,204,118 — treat this as a security incident";
    const page = await mountAuditPage({
      routes: { audit: pagesOf(PAGE_1), verify: () => json(200, BROKEN) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run tamper check" }));
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent(title);
    // the footer says it too, with the octagon, silently: the banner speaks
    expect(inPage().getAllByText(title)).toHaveLength(2);
    expect(polite()).toEqual([]);
    // the orchestrator's Q2 (a): the incidents are read again at once, not in 60 s
    expect(page.sent.filter((s) => s.url.startsWith(INCIDENTS))).toHaveLength(2);
    // no Retry, re-run, dismiss or acknowledge in the banner (§7)
    const banner = document.querySelector<HTMLElement>("[data-tamper-banner]");
    const names = within(banner as HTMLElement)
      .getAllByRole("button")
      .map((b) => b.getAttribute("aria-label") ?? b.textContent ?? "");
    expect(names).toEqual(["Copy details", "What to do now"]);
    page.unmount();
    // a later mount is static: one voice per episode (D11)
    const again = await mountAuditPage({ routes: { audit: pagesOf(PAGE_1) } });
    expect(inPage().getAllByText(title).length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).toBeNull();
    again.unmount();
  });

  it("test_page_open_incident_says_the_halt_and_acknowledged_the_standing_line", async () => {
    const page = await mountAuditPage({
      routes: {
        audit: pagesOf(PAGE_1),
        incidents: (n) =>
          json(200, {
            items: [incident(n === 0 ? {} : { status: "acknowledged" })],
            meta: { next_cursor: null, has_more: false, count: 1 },
          }),
      },
    });
    expect(
      inPage().getByText(/New orders that open or add to a position are halted/),
    ).toBeVisible();
    await flush(60_000);
    expect(inPage().queryByText(/are halted/)).toBeNull();
    expect(inPage().getByText(/A break does not stop order entry by itself/)).toBeVisible();
    page.unmount();
  });
});

describe("refusals at the point of action (E09-D09 T4)", () => {
  it("test_page_view_as_refusal_of_the_check_is_not_sent_at_the_button", async () => {
    // the session holds no view-as context the client can see: the server's refusal is T4
    const page = await mountAuditPage({
      routes: { audit: pagesOf(PAGE_1), verify: () => problem(403, "view_as_read_only") },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run tamper check" }));
    await flush();
    expect(inPage().getByText("Not sent — your access changed.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Audit log" })).toBeInTheDocument();
    page.unmount();
  });

  it("test_page_read_only_session_says_inflight_read_only_at_the_button", async () => {
    const page = await mountAuditPage({
      routes: { audit: pagesOf(PAGE_1), verify: () => problem(403, "session_read_only") },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run tamper check" }));
    await flush();
    expect(inPage().getByText("Not sent — read-only after three wrong codes.")).toBeInTheDocument();
    page.unmount();
  });
});
