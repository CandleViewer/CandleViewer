/**
 * E42-S04 (#1135), the orchestrator's BQ-9: while the session views as another user, Run tamper
 * check is T2 `rbac.view_as`, described by the page's ONE notice (`32` G-T2.5, G-T2.6), and a press
 * sends nothing; reads answer as the target, so a `403 forbidden` there is the target's refusal,
 * never the area withdrawn. The shell has no view-as source yet (#1134), so this file forces one
 * through the page's seam.
 */
import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { auditIntegrity } from "../../../../src/features/admin/audit/integrity";
import { resetShellState } from "../../../../src/shell/bootstrap/store";
import { T0, entries, json, problem, verifyBody } from "./fixtures";
import { flush, mountAuditPage, pagesOf, sessionAs } from "./harness";

// The page renders CMP-049's grid, CMP-174 and the shell's announcer from the ui sources: a busy
// host can take seconds over a mount, as with SCR-120's page tests.
vi.setConfig({ testTimeout: 30_000 });

const viewing = vi.hoisted(() => ({ as: null as { readonly user: string } | null }));
vi.mock("../../../../src/features/admin/audit/viewAs", () => ({
  useAuditViewAs: () => viewing.as,
}));

const NOTICE = "Read-only while viewing as alex.";
const VIEWING = { user: "alex" } as const;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  clearAnnouncements();
  auditIntegrity.reset();
  sessionAs("owner");
  viewing.as = VIEWING;
});

afterEach(() => {
  viewing.as = null;
  auditIntegrity.reset();
  resetShellState();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("view-as (BQ-9): T2 rbac.view_as behind one notice", () => {
  it("test_view_as_run_tamper_check_is_t2_on_the_one_notice_and_sends_nothing", async () => {
    const page = await mountAuditPage({
      routes: { audit: pagesOf(entries(2)), verify: () => json(200, verifyBody()) },
    });
    const notices = within(screen.getByRole("main")).getAllByText(NOTICE);
    expect(notices).toHaveLength(1);
    const run = screen.getByRole("button", { name: /Run tamper check$/ });
    expect(run).toHaveAttribute("aria-disabled", "true");
    expect(run).toHaveAccessibleName("Not available Run tamper check");
    expect(run.getAttribute("aria-describedby")).toBe(notices[0]?.id);
    fireEvent.click(run);
    await flush();
    expect(page.sent.filter((s) => s.method !== "GET")).toEqual([]);
    // the marker stays visible while the control is T2 (D09:236)
    expect(
      within(screen.getByRole("main")).getByText("Recorded in the audit log · admin.audit_verify"),
    ).toBeVisible();
    page.unmount();
  });

  it("test_view_as_403_forbidden_is_the_targets_refusal_never_the_area_withdrawn", async () => {
    const onWithdrawn = vi.fn();
    const page = await mountAuditPage({
      routes: { audit: pagesOf(problem(403, "forbidden")) },
      onWithdrawn,
    });
    expect(onWithdrawn).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1, name: "Audit log" })).toBeInTheDocument();
    page.unmount();
  });

  it("test_view_as_incident_read_403_forbidden_is_the_targets_never_the_area_withdrawn", async () => {
    // C-1135P2-07 / S-1135P2-01: the session's integrity store learns the page's view-as state
    const onWithdrawn = vi.fn();
    const page = await mountAuditPage({
      routes: { audit: pagesOf(entries(2)), incidents: () => problem(403, "forbidden") },
      onWithdrawn,
    });
    await flush();
    expect(onWithdrawn).not.toHaveBeenCalled();
    expect(screen.getByRole("grid")).toBeInTheDocument();
    page.unmount();
  });

  it("test_view_as_gone_lifts_the_notice", async () => {
    viewing.as = null;
    const page = await mountAuditPage({ routes: { audit: pagesOf(entries(2)) } });
    expect(within(screen.getByRole("main")).queryByText(NOTICE)).toBeNull();
    expect(screen.getByRole("button", { name: "Run tamper check" })).not.toHaveAttribute(
      "aria-disabled",
    );
    page.unmount();
  });
});
