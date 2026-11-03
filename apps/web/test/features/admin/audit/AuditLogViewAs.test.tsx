/**
 * E42-S04 (#1135), the orchestrator's BQ-9: while the session views as another user, reads answer
 * as the target, so a `403 forbidden` there is the target's refusal, never the area withdrawn. The
 * shell has no view-as source yet (#1134), so this file forces one through the page's seam.
 */
import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { resetShellState } from "../../../../src/shell/bootstrap/store";
import { T0, problem } from "./fixtures";
import { mountAuditPage, pagesOf, sessionAs } from "./harness";

// The page renders CMP-049's grid, CMP-174 and the shell's announcer from the ui sources: a busy
// host can take seconds over a mount, as with SCR-120's page tests.
vi.setConfig({ testTimeout: 30_000 });

const viewing = vi.hoisted(() => ({ as: null as { readonly user: string } | null }));
vi.mock("../../../../src/features/admin/audit/viewAs", () => ({
  useAuditViewAs: () => viewing.as,
}));

const VIEWING = { user: "alex" } as const;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  clearAnnouncements();
  sessionAs("owner");
  viewing.as = VIEWING;
});

afterEach(() => {
  viewing.as = null;
  resetShellState();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("view-as (BQ-9): the target's refusal", () => {
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
});
