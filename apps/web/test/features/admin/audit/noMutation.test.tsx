/**
 * E42-S04 (#1135), "No mutation affordance exists": every control SCR-135 and SCR-136 draw, with a
 * row expanded and the drawer open, is a filter, a pager, an expander, an opener, a copy, a link,
 * Run tamper check or a disclosure (E42-D04 D9). None edits, deletes, corrects, archives, repairs or
 * re-hashes a record: the log is append-only, and the page and the drawer say so (C-2.9).
 * CMP-174's chips' "Remove {action}" removes a filter, not a record, and is allowed by name.
 */
import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { auditIntegrity } from "../../../../src/features/admin/audit/integrity";
import { resetShellState } from "../../../../src/shell/bootstrap/store";
import { BROKEN, T0, entries, json } from "./fixtures";
import { flush, mountAuditPage, pagesOf, sessionAs } from "./harness";

// The page renders CMP-049's grid, CMP-174 and the shell's announcer from the ui sources: a busy
// host can take seconds over a mount, as with SCR-120's page tests.
vi.setConfig({ testTimeout: 30_000 });

const MUTATION = /\b(edit|delete|correct|archive|repair|re-?hash|purge|modify|update)\b/i;
const FILTER_CHIP = /^Remove [a-z0-9_]+([.][a-z0-9_]+){1,3}$/;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
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

describe("no mutation affordance (D9)", () => {
  it("test_no_control_on_the_page_a_row_or_the_drawer_changes_a_record", async () => {
    const page = await mountAuditPage({
      routes: { audit: pagesOf(entries(3)), verify: () => json(200, BROKEN) },
      search: "?action=orders.submit",
    });
    fireEvent.click(screen.getByRole("button", { name: "Run tamper check" })); // the banner too
    await flush();
    const first = document.querySelector<HTMLElement>("tr[data-entry]") as HTMLElement;
    fireEvent.keyDown(first, { key: " " }); // the expanded diff row
    fireEvent.keyDown(first, { key: "Enter" }); // and SCR-136
    await flush();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    const names = [
      ...screen.getAllByRole("button"),
      ...screen.getAllByRole("link"),
      ...screen.queryAllByRole("menuitem"),
    ].map((el) => (el.getAttribute("aria-label") ?? el.textContent ?? "").trim());
    expect(names.length).toBeGreaterThan(10);
    const offending = names.filter((name) => MUTATION.test(name) && !FILTER_CHIP.test(name));
    expect(offending).toEqual([]);
    expect(
      screen.getByText("Records can only be added, never edited or deleted. Kept indefinitely."),
    ).toBeInTheDocument();
    expect(screen.getByText("This record cannot be edited or deleted.")).toBeInTheDocument();
    page.unmount();
  });
});
