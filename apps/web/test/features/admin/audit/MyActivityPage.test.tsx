/**
 * E42-S04 (#1135): "My activity", R-360 for a Manager (the orchestrator's BQ-8 (a); E42-D04 AL-25,
 * AL-26, AD-7). The server scopes and projects every entry (`22` queryAuditLog, Access): the page
 * states the scope from the session's role, never from the rows, drops no row, sends no Actor, `q`
 * or `ip` (BQ-3), reads no incidents (BQ-4), and keeps the Owner-only controls as T2
 * `rbac.owner_only`. The worked example's manager `alex`.
 */
import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { auditExport } from "../../../../src/features/admin/audit/exportJob";
import { auditIntegrity } from "../../../../src/features/admin/audit/integrity";
import { MyActivityPage } from "../../../../src/features/admin/audit/MyActivityPage";
import { resetShellState } from "../../../../src/shell/bootstrap/store";
import { ALEX_ID, BROKEN, OWNER_ID, T0, entry, json } from "./fixtures";
import { INCIDENTS, flush, mountAuditPage, pagesOf, sessionAs } from "./harness";

// The page renders CMP-049's grid, CMP-174 and the shell's announcer from the ui sources: a busy
// host can take seconds over a mount, as with SCR-120's page tests.
vi.setConfig({ testTimeout: 30_000 });

const BEA_ID = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0003";
/** Alex's own entries as the projection serves them (`22` AuditEntry): the hidden fields null. */
const projected = (over: Parameters<typeof entry>[0] = {}) =>
  entry({
    actor_user_id: ALEX_ID,
    actor_username: "alex",
    environment: null,
    ip: null,
    session_id: null,
    user_agent: null,
    reason: null,
    subject_label: null,
    entry_hash: null,
    prev_hash: null,
    detail: {},
    ...over,
  });
const OWN = [
  projected({ id: 21 }),
  projected({ id: 20, subject_type: "user", subject_id: BEA_ID }),
];

const main = (): ReturnType<typeof within> => within(screen.getByRole("main"));
const ownerOnly = (verb: string): string => `Only the owner can ${verb}.`;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  clearAnnouncements();
  auditIntegrity.reset();
  auditExport.reset();
  sessionAs("manager", ALEX_ID, "alex");
});

afterEach(() => {
  auditExport.reset();
  auditIntegrity.reset();
  resetShellState();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("My activity: the scope stated, never enforced here (AL-25)", () => {
  it("test_my_activity_says_its_scope_from_the_session_and_drops_no_row", async () => {
    // a row of another actor's, as a broken server might serve it: shown, never filtered here
    const rows = [...OWN, projected({ id: 19, actor_user_id: BEA_ID, actor_username: "bea" })];
    const page = await mountAuditPage({
      element: <MyActivityPage />,
      routes: { audit: pagesOf(rows) },
    });
    expect(screen.getByRole("heading", { level: 1, name: "My activity" })).toBeInTheDocument();
    expect(main().getByText("Showing your actions only")).toBeInTheDocument();
    expect(document.querySelectorAll("tr[data-entry]")).toHaveLength(3);
    page.unmount();
  });

  it("test_my_activity_sends_no_actor_q_or_ip_and_says_a_crafted_filter_was_dropped", async () => {
    // the binding tests: a Manager's other-user `actor_user_id`, `q` and `ip` are never sent (the
    // server would narrow the first with one `admin.audit_denied` and refuse the others, `22`)
    const page = await mountAuditPage({
      element: <MyActivityPage />,
      routes: { audit: pagesOf(OWN) },
      search: `?actor_user_id=${BEA_ID}&q=withdrawal&ip=100.84.12.9&environment=live&severity=error`,
    });
    const sent = page.reads().map((url) => [...url.searchParams.keys()].sort());
    expect(sent).toEqual([["limit", "severity"]]);
    expect(main().getByText("That filter isn't available in your view.")).toBeInTheDocument();
    page.unmount();
  });

  it("test_my_activity_reads_no_incidents_and_its_owner_only_controls_are_t2", async () => {
    const page = await mountAuditPage({
      element: <MyActivityPage />,
      routes: { audit: pagesOf(OWN) },
    });
    await flush(120_000);
    expect(page.sent.filter((s) => s.url.startsWith(INCIDENTS))).toEqual([]);
    const run = screen.getByRole("button", { name: /Run tamper check$/ });
    expect(run).toHaveAttribute("aria-disabled", "true");
    expect(main().getByText(ownerOnly("run a tamper check"))).toBeInTheDocument();
    const search = screen.getByRole("search", { name: "Filter the audit log" });
    for (const name of [/IP$/, /Search$/]) {
      expect(within(search).getByRole("textbox", { name })).toHaveAttribute(
        "aria-disabled",
        "true",
      );
    }
    fireEvent.click(run);
    await flush();
    expect(page.sent.filter((s) => s.method !== "GET")).toEqual([]);
    page.unmount();
  });

  it("test_my_activity_signed_export_is_t2_owner_only_and_opens_nothing", async () => {
    // C-1135P2-17: the export's gate on My activity (AL-25)
    const page = await mountAuditPage({
      element: <MyActivityPage />,
      routes: { audit: pagesOf(OWN) },
    });
    const signed = screen.getByRole("button", { name: /Signed export…$/ });
    expect(signed).toHaveAttribute("aria-disabled", "true");
    expect(signed).toHaveAccessibleDescription(ownerOnly("export the audit log"));
    fireEvent.click(signed);
    await flush(1_000);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(page.sent.filter((s) => s.method !== "GET")).toEqual([]);
    page.unmount();
  });

  it("test_my_activity_never_shows_an_owners_break_from_this_document", async () => {
    // S-1135P2-02: the session's integrity is the Owner's (BQ-4, AD-7: `rec.not_checked`)
    sessionAs("owner", OWNER_ID);
    const owner = await mountAuditPage({
      routes: { audit: pagesOf(OWN), verify: () => json(200, BROKEN) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run tamper check" }));
    await flush();
    owner.unmount();
    sessionAs("manager", ALEX_ID, "alex");
    const page = await mountAuditPage({
      element: <MyActivityPage />,
      routes: { audit: pagesOf([projected({ id: 1_204_120 })]) },
    });
    const row = document.querySelector<HTMLElement>('tr[data-entry="1204120"]') as HTMLElement;
    fireEvent.keyDown(row, { key: " " }); // the diff row: no AD-5 line after the break
    await flush();
    expect(main().queryByText(/at or after the break/)).toBeNull();
    fireEvent.keyDown(row, { key: "Enter" });
    await flush();
    const d = within(screen.getByRole("dialog"));
    expect(d.getByText("No tamper check this session covers this record.")).toBeInTheDocument();
    expect(d.queryByText(/at or after the break/)).toBeNull();
    page.unmount();
  });

  it("test_my_activity_projected_cells_and_its_page_line_stay_neutral", async () => {
    const page = await mountAuditPage({
      element: <MyActivityPage />,
      routes: { audit: pagesOf(OWN) },
    });
    expect(main().getAllByText("not shown in your view").length).toBeGreaterThanOrEqual(4);
    expect(main().getByText("Tamper check: this page checked — passed")).toBeInTheDocument();
    page.unmount();
  });

  it("test_my_activity_empty_says_no_actions_by_you", async () => {
    const page = await mountAuditPage({
      element: <MyActivityPage />,
      routes: { audit: pagesOf([]) },
      search: "?severity=critical",
    });
    expect(
      main().getByRole("heading", { name: "No actions by you match these filters." }),
    ).toBeInTheDocument();
    page.unmount();
  });

  it("test_the_owners_page_never_says_it_is_scoped", async () => {
    sessionAs("owner", OWNER_ID);
    const page = await mountAuditPage({ routes: { audit: pagesOf(OWN) } });
    expect(main().queryByText("Showing your actions only")).toBeNull();
    page.unmount();
  });
});

describe("My activity's record drawer (AD-7)", () => {
  it("test_my_activity_drawer_hides_the_projection_behind_one_notice", async () => {
    const page = await mountAuditPage({
      element: <MyActivityPage />,
      routes: { audit: pagesOf(OWN) },
    });
    const row = document.querySelector<HTMLElement>('tr[data-entry="20"]') as HTMLElement;
    fireEvent.keyDown(row, { key: "Enter" });
    await flush();
    const d = within(screen.getByRole("dialog"));
    const notice = d.getByText(ownerOnly("see raw records"));
    const show = d.getByRole("button", { name: /Show raw record$/ });
    expect(show).toHaveAttribute("aria-disabled", "true");
    expect(show.getAttribute("aria-describedby")).toBe(notice.id);
    for (const name of [/Copy session$/, /Copy IP$/, /Copy entry hash$/, /Copy previous hash$/]) {
      expect(d.getByRole("button", { name }).getAttribute("aria-describedby")).toBe(notice.id);
    }
    expect(d.getByText("Not shown in your view")).toBeInTheDocument(); // the diff's projection
    // an /admin subject and the actor are text for a Manager; only subject and time pivots
    expect(d.queryByRole("link", { name: /alex/ })).toBeNull();
    expect(d.getByText(`user · ${BEA_ID}`)).toBeInTheDocument();
    const pivots = d.getAllByRole("link").map((a) => a.textContent);
    expect(pivots).toEqual(["This subject's entries", "Entries around this time"]);
    fireEvent.click(show);
    await flush();
    expect(d.queryByRole("region", { name: "Raw record" })).toBeNull();
    page.unmount();
  });
});
