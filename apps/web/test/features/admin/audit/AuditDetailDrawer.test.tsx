/**
 * E42-S04 (#1135): SCR-136, the record drawer (E42-D04 §5, D14, AD-1 to AD-6). It renders the
 * page's own entry: opening it fetches and records nothing (CG-5; QA AD-S04-N06). Its raw record is
 * built only when shown, and withheld when the diff model finds a value under a secret name (AD-3);
 * no redaction marker's value ever reaches the DOM. The Manager's projection (AD-7) is My
 * activity's, pinned with that page.
 */
import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as Announcer from "../../../../src/features/app-shell/announcer";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { auditIntegrity } from "../../../../src/features/admin/audit/integrity";
import { resetShellState } from "../../../../src/shell/bootstrap/store";
import { ALEX_ID, T0, entry } from "./fixtures";
import { flush, mountAuditPage, pagesOf, sessionAs } from "./harness";

// The page renders CMP-049's grid, CMP-174 and the shell's announcer from the ui sources: a busy
// host can take seconds over a mount, as with SCR-120's page tests.
vi.setConfig({ testTimeout: 30_000 });

const said = vi.hoisted(() => [] as string[]);
vi.mock("../../../../src/features/app-shell/announcer", async (importOriginal) => {
  const real = await importOriginal<typeof Announcer>();
  return {
    ...real,
    announce: (politeness: Announcer.Politeness, text: string, key: string): boolean => {
      const written = real.announce(politeness, text, key);
      if (written && politeness === "polite") said.push(text);
      return written;
    },
  };
});

const ORDER = entry({ id: 1_204_120, subject_label: "BTCUSDT" });
const FLAG = entry({
  id: 1_204_119,
  ts: "2026-10-22T14:01:40.551203Z",
  actor_user_id: ALEX_ID,
  actor_username: "alex",
  action: "flags.change",
  subject_type: "feature_flag",
  subject_id: "trading.one_click",
  severity: "warning",
  reason: "rollout to alex",
  detail: {
    before: { value: false },
    after: { value: true, phase: "intent" },
  },
});
const REDACTED = entry({
  id: 1_204_118,
  actor_user_id: null,
  actor_username: "deleted-user-3f9a12bc4d5e",
  action: "account.updated",
  subject_type: "widget",
  subject_id: "w-1",
  detail: {
    before: { note: "plain" },
    after: {
      note: "changed",
      password: "<redacted:secret>",
      client_secret: "unredacted-plain-text",
    },
  },
});
const ROWS = [ORDER, FLAG, REDACTED];

const row = (id: number): HTMLElement => {
  const found = document.querySelector<HTMLElement>(`tr[data-entry="${id}"]`);
  if (found === null) throw new Error(`no row ${id}`);
  return found;
};
const drawer = (): HTMLElement => screen.getByRole("dialog");
const open = async (id: number): Promise<void> => {
  fireEvent.keyDown(row(id), { key: "Enter" });
  await flush();
};
/** A row's expander: the grid's one control in its first cell, focused in the cell's place. */
const toggle = (id: number): HTMLElement => row(id).querySelector("button") as HTMLElement;
/** Opens the drawer as a keyboard user does: focus on the row's expander, then Enter. */
const openFrom = async (id: number): Promise<void> => {
  await act(async () => toggle(id).focus());
  fireEvent.keyDown(toggle(id), { key: "Enter" });
  await flush();
};
const press = async (key: string, ctrlKey = false): Promise<void> => {
  fireEvent.keyDown(document.activeElement as HTMLElement, { key, ctrlKey });
  await flush();
};

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

describe("SCR-136 opens from the row it shows (D14, CG-5)", () => {
  it("test_drawer_opens_on_enter_with_its_heading_focused_and_fetches_nothing", async () => {
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    const before = page.sent.length;
    await open(1_204_120);
    const heading = within(drawer()).getByRole("heading", { level: 2, name: "Record 1,204,120" });
    expect(document.activeElement).toBe(heading);
    expect(drawer()).not.toHaveAttribute("aria-modal");
    expect(row(1_204_120)).toHaveAttribute("aria-selected", "true");
    await flush(10_000);
    expect(page.sent.slice(before).filter((s) => !s.url.includes("/incidents"))).toEqual([]);
    page.unmount();
  });

  it("test_drawer_states_the_record_in_its_sections_and_that_it_cannot_change", async () => {
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    await open(1_204_120);
    const d = within(drawer());
    expect(
      d.getByText(
        "Order submitted (orders.submit) · Success · Info · 2026-10-22 14:01:50.212 UTC · LIVE",
      ),
    ).toBeInTheDocument();
    for (const name of ["Who", "What", "Before / after", "Request", "Related", "Integrity"]) {
      expect(d.getByRole("heading", { level: 3, name })).toBeInTheDocument();
    }
    expect(d.getByText("Role at the time: not recorded")).toBeInTheDocument();
    expect(d.getByText("User agent: not recorded")).toBeInTheDocument();
    expect(d.getByText("Linked records can't be listed yet.")).toBeInTheDocument();
    expect(d.getByText("No tamper check this session covers this record.")).toBeInTheDocument();
    expect(d.getByText("Each record is linked to the one before it.")).toBeInTheDocument();
    expect(d.getByText("This record cannot be edited or deleted.")).toBeInTheDocument();
    expect(d.getByRole("link", { name: "order · BTCUSDT" })).toHaveAttribute(
      "href",
      "/positions/order/0a000000-0000-4000-8000-000000000001",
    );
    expect(d.getByRole("link", { name: "basiltt" })).toHaveAttribute(
      "href",
      "/admin/users/9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001",
    );
    expect(d.getByRole("button", { name: "Copy session" })).toBeInTheDocument();
    expect(d.getByRole("button", { name: "Copy request id" })).toBeInTheDocument();
    const pivots = d
      .getAllByRole("link")
      .filter((a) => a.getAttribute("href")?.startsWith("/admin/audit"));
    expect(pivots.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["This actor's entries", "/admin/audit?actor_user_id=9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001"],
      [
        "This subject's entries",
        "/admin/audit?subject_type=order&subject_id=0a000000-0000-4000-8000-000000000001",
      ],
      [
        "Entries around this time",
        "/admin/audit?from=2026-10-22T13%3A56%3A50.212Z&to=2026-10-22T14%3A06%3A50.212Z",
      ],
    ]);
    page.unmount();
  });

  it("test_drawer_builds_the_raw_record_only_when_shown", async () => {
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    await open(1_204_120);
    const d = within(drawer());
    expect(d.queryByRole("region", { name: "Raw record" })).toBeNull();
    const show = d.getByRole("button", { name: "Show raw record" });
    expect(show).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(show);
    await flush();
    const raw = d.getByRole("region", { name: "Raw record" });
    expect(show).toHaveAttribute("aria-controls", raw.id);
    expect(JSON.parse(raw.textContent ?? "")).toMatchObject({ id: 1_204_120 });
    expect(d.getByRole("button", { name: "Copy Raw record" })).toBeInTheDocument();
    page.unmount();
  });

  it("test_drawer_redacted_values_show_their_words_never_a_marker_and_the_raw_record_is_withheld", async () => {
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    await open(1_204_118);
    const d = within(drawer());
    expect(d.getAllByText("Secret — never recorded").length).toBeGreaterThan(0);
    expect(d.getByText("Hidden — secret-named field")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("<redacted:");
    expect(document.body.textContent).not.toContain("unredacted-plain-text");
    expect(
      d.getByText(
        "This record holds a value under a secret-named field — report it to security (SR-069).",
      ),
    ).toBeInTheDocument();
    expect(d.queryByRole("button", { name: "Show raw record" })).toBeNull();
    // a pseudonym is text, never a link (CG-33), and an unmapped kind is text too
    expect(d.queryByRole("link", { name: /deleted-user/ })).toBeNull();
    expect(d.getByText("widget · w-1")).toBeInTheDocument();
    page.unmount();
  });

  it("test_drawer_raw_record_is_withheld_for_a_secret_named_value_outside_before_and_after", async () => {
    // the raw block shows the whole record, so the mirror reads all of `detail` (S-1135P2-d01)
    const extra = entry({
      id: 1_204_117,
      detail: {
        before: null,
        after: { note: "plain" },
        extra: { client_secret: "extra-plain-secret" },
      },
    });
    const page = await mountAuditPage({ routes: { audit: pagesOf([ORDER, extra]) } });
    await open(1_204_117);
    const d = within(drawer());
    expect(d.queryByRole("button", { name: "Show raw record" })).toBeNull();
    expect(d.getByText(/report it to security/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("extra-plain-secret");
    page.unmount();
  });

  it("test_drawer_raw_record_is_withheld_for_a_secret_named_value_in_a_served_text", async () => {
    // a top-level text the raw block shows is read as the server reads embedded JSON
    const text = entry({ id: 1_204_116, user_agent: '{"api_key":"agent-plain-key"}' });
    const page = await mountAuditPage({ routes: { audit: pagesOf([ORDER, text]) } });
    await open(1_204_116);
    const d = within(drawer());
    expect(d.queryByRole("button", { name: "Show raw record" })).toBeNull();
    expect(d.getByText(/report it to security/)).toBeInTheDocument();
    page.unmount();
  });

  it("test_drawer_reason_is_given_on_an_intent_and_a_code_elsewhere", async () => {
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    await open(1_204_119);
    expect(within(drawer()).getByText("Reason given")).toBeInTheDocument();
    expect(within(drawer()).getByText("rollout to alex")).toBeInTheDocument();
    await open(1_204_120);
    expect(within(drawer()).getByText("Reason code")).toBeInTheDocument();
    page.unmount();
  });
});

describe("stepping and closing (D14, §5)", () => {
  it("test_drawer_previous_and_next_step_through_the_loaded_page_and_are_t2_at_its_ends", async () => {
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    await open(1_204_120);
    const d = (): ReturnType<typeof within> => within(drawer());
    const previous = (): HTMLElement => d().getByRole("button", { name: /Previous$/ });
    const next = (): HTMLElement => d().getByRole("button", { name: /Next$/ });
    expect(previous()).toHaveAttribute("aria-disabled", "true");
    expect(
      document.getElementById(previous().getAttribute("aria-describedby") ?? ""),
    ).toHaveTextContent("No more records in the loaded page.");
    fireEvent.click(next());
    await flush();
    expect(d().getByRole("heading", { level: 2 })).toHaveTextContent("Record 1,204,119");
    expect(row(1_204_119)).toHaveAttribute("aria-selected", "true");
    fireEvent.click(next());
    await flush();
    expect(next()).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(previous());
    await flush();
    expect(d().getByRole("heading", { level: 2 })).toHaveTextContent("Record 1,204,119");
    page.unmount();
  });

  it("test_drawer_steps_say_the_record_they_show_and_a_t2_step_its_reason", async () => {
    // A-1135P2-11: focus stays on Next while the record changes, so the record is said;
    // A-1135P2-02: a T2 step says its reason through the shell, once per press
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    await open(1_204_120);
    fireEvent.click(within(drawer()).getByRole("button", { name: /Next$/ }));
    await flush();
    fireEvent.click(within(drawer()).getByRole("button", { name: /Next$/ }));
    await flush();
    fireEvent.click(within(drawer()).getByRole("button", { name: /Next$/ }));
    await flush();
    expect(said).toEqual([
      "Record 1,204,119",
      "Record 1,204,118",
      "No more records in the loaded page.",
    ]);
    page.unmount();
  });

  it("test_drawer_esc_and_close_after_a_step_close_it_and_return_focus_to_that_row", async () => {
    // A-1135P2-01: CMP-046 hands focus back to the opener first; that row never re-opens it
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    await openFrom(1_204_120);
    fireEvent.click(within(drawer()).getByRole("button", { name: /Next$/ }));
    await flush();
    await press("Escape");
    await flush(1_000);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(toggle(1_204_119));
    await openFrom(1_204_119);
    fireEvent.click(within(drawer()).getByRole("button", { name: /Next$/ }));
    await flush();
    fireEvent.click(within(drawer()).getByRole("button", { name: "Close Record 1,204,118" }));
    await flush(1_000);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(toggle(1_204_118));
    page.unmount();
  });

  it("test_drawer_follows_focus_moved_in_the_grid_never_focus_arriving_from_outside", async () => {
    // D14 (C-1135P2-11): ↓ in the grid keeps the drawer on the focused row; focus arriving from
    // the drawer or the filters picks no record (A-1135P2-01)
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    await openFrom(1_204_120);
    fireEvent.click(within(drawer()).getByRole("button", { name: /Next$/ }));
    await flush();
    const heading = (): HTMLElement => within(drawer()).getByRole("heading", { level: 2 });
    expect(heading()).toHaveTextContent("Record 1,204,119");
    await act(async () => toggle(1_204_120).focus()); // from the drawer: no record picked
    await flush();
    expect(heading()).toHaveTextContent("Record 1,204,119");
    await press("ArrowDown");
    await press("ArrowDown");
    expect(document.activeElement).toBe(toggle(1_204_118));
    expect(heading()).toHaveTextContent("Record 1,204,118");
    expect(row(1_204_118)).toHaveAttribute("aria-selected", "true");
    expect(row(1_204_119)).not.toHaveAttribute("aria-selected");
    page.unmount();
  });

  it("test_drawer_open_stops_the_arrows_at_action_so_no_cell_under_it_takes_focus", async () => {
    // A-1135P2-04 (D04 D1): Target onward is the drawer's to read while it is open
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    await openFrom(1_204_120);
    await act(async () => toggle(1_204_120).focus());
    const column = (): number =>
      Number(
        (document.activeElement as HTMLElement).closest<HTMLElement>("[data-cv-c]")?.dataset["cvC"],
      );
    for (let n = 0; n < 9; n += 1) await press("ArrowRight");
    expect(column()).toBe(4); // Action
    await press("Home");
    await press("End");
    expect(column()).toBe(4);
    await press("End", true);
    expect(column()).toBe(4);
    expect(document.activeElement?.closest("tr")).toBe(row(1_204_118));
    page.unmount();
  });

  it("test_drawer_pivot_closes_it_and_row_one_takes_focus_once_its_set_lands", async () => {
    // C-1135P2-13: the record is not in the new set
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS, [FLAG]) } });
    await open(1_204_120);
    fireEvent.click(within(drawer()).getByRole("link", { name: "This subject's entries" }));
    await flush(1_000);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(page.router.state.location.search).toContain("subject_type=order");
    expect(document.activeElement).toBe(toggle(1_204_119));
    page.unmount();
  });

  it("test_drawer_close_returns_focus_to_the_record_it_showed", async () => {
    const page = await mountAuditPage({ routes: { audit: pagesOf(ROWS) } });
    await open(1_204_120);
    fireEvent.click(within(drawer()).getByRole("button", { name: /Next$/ }));
    await flush();
    fireEvent.click(within(drawer()).getByRole("button", { name: "Close Record 1,204,119" }));
    await flush(1_000);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement?.closest("tr")).toBe(row(1_204_119));
    page.unmount();
  });
});
