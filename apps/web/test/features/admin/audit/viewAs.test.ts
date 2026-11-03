/**
 * E42-S04, the orchestrator's BQ-9: the audit pages' view-as seam reports view-as whenever the
 * shell's read-only overlay says so, with or without a name to show (S-1135P2-d02).
 */
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAuditViewAs } from "../../../../src/features/admin/audit/viewAs";

const shell = vi.hoisted(() => ({
  readOnly: null as string | null,
  me: null as { readonly user?: { readonly username?: string } } | null,
}));
vi.mock("../../../../src/features/app-shell/useShellMode", () => ({
  useShellMode: () => ({ readOnly: shell.readOnly }),
}));
vi.mock("../../../../src/shell/useShellSelector", () => ({
  useShellSelector: <T>(select: (state: unknown) => T): T => select({ me: shell.me }),
}));

afterEach(() => {
  shell.readOnly = null;
  shell.me = null;
});

describe("useAuditViewAs (BQ-9)", () => {
  it("test_view_as_names_the_target_when_the_session_has_a_username", () => {
    shell.readOnly = "view-as";
    shell.me = { user: { username: "alex" } };
    expect(renderHook(() => useAuditViewAs()).result.current).toEqual({ user: "alex" });
  });

  it("test_view_as_without_a_username_is_still_view_as_with_a_generic_name", () => {
    shell.readOnly = "view-as";
    for (const me of [null, {}, { user: {} }, { user: { username: "" } }]) {
      shell.me = me;
      expect(renderHook(() => useAuditViewAs()).result.current).toEqual({ user: "another user" });
    }
  });

  it("test_view_as_is_null_outside_view_as", () => {
    shell.me = { user: { username: "alex" } };
    for (const mode of [null, "lockout"]) {
      shell.readOnly = mode;
      expect(renderHook(() => useAuditViewAs()).result.current).toBeNull();
    }
  });
});
