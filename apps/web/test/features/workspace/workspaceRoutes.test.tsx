// E15-S03 (#476) PR-1: the served `ui.workspace_dock`, read through #5669's `useFlag` (unread is
// off); off, R-101 and R-102 render what they rendered before; on, `/terminal/last` resolves to
// `/w/:workspaceId` and the workspace restores there.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { generated } from "@candleviewer/protocol";
import { act } from "react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const WS = "0190a000-0000-7000-8000-000000000001";
const listWorkspaces = vi.fn();
const getWorkspace = vi.fn();
vi.mock("../../../src/features/workspace/api/workspacesApi", () => ({
  listWorkspaces,
  getWorkspace,
}));

const { buildRoutes } = await import("../../../src/routes/tree");
const { resetMeClaims, setMeClaims } = await import("../../../src/lib/auth/meCache");
const { applySystemUpdate, resetShellState } = await import("../../../src/shell/bootstrap/store");
const { WORKSPACE_DOCK_FLAG } = await import("../../../src/features/workspace/routes/entry");

type System = generated.ws.System;
const flags = (kind: "health" | "feature_flags", values: Record<string, unknown>): void =>
  act(() => applySystemUpdate({ kind, feature_flags: values } as unknown as System));

const at = (path: string) => {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
};

const answer = (value: unknown) => ({ ok: true, etag: null, value });
beforeEach(() => {
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
  vi.stubGlobal("fetch", () => Promise.reject(new TypeError("no network in tests")));
  listWorkspaces.mockResolvedValue(answer([{ id: WS, is_default: true }]));
  getWorkspace.mockResolvedValue(answer({ id: WS, name: "Scalping", layouts: [] }));
});
afterEach(() => {
  cleanup();
  resetShellState();
  resetMeClaims();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("ui.workspace_dock", () => {
  it("test_a_rejected_resolve_is_the_network_failure_with_no_unhandled_rejection", async () => {
    flags("health", { [WORKSPACE_DOCK_FLAG]: true });
    const unhandled = vi.fn();
    process.on("unhandledRejection", unhandled);
    listWorkspaces.mockRejectedValueOnce(new Error("malformed"));
    at("/terminal/last");
    expect(await screen.findByText("Couldn't load workspaces.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
    expect(screen.queryByText("Opening your workspace…")).toBeNull();
    await new Promise((r) => setTimeout(r, 0));
    process.off("unhandledRejection", unhandled);
    expect(unhandled).not.toHaveBeenCalled();
  });

  it("test_flag_off_terminal_and_workspace_routes_keep_their_stubs", async () => {
    flags("health", { [WORKSPACE_DOCK_FLAG]: false }); // read off; unread (below) is off too
    at("/terminal/last");
    expect(await screen.findByRole("heading", { name: /R-101/ })).toBeVisible();
    cleanup();
    act(() => resetShellState());
    at("/terminal/last");
    expect(await screen.findByRole("heading", { name: /R-101/ })).toBeVisible();
    cleanup();
    at(`/w/${WS}`);
    expect(await screen.findByRole("heading", { name: /R-102/ })).toBeVisible();
    expect(listWorkspaces).not.toHaveBeenCalled();
    expect(getWorkspace).not.toHaveBeenCalled();
  });

  it("test_flag_on_terminal_last_resolves_to_the_workspace_route_and_restores_it", async () => {
    flags("health", { [WORKSPACE_DOCK_FLAG]: true });
    const router = at("/terminal/last?symbol=BTCUSDT");
    await waitFor(() => expect(router.state.location.pathname).toBe(`/w/${WS}`));
    expect(router.state.location.search).toBe(""); // §10.1 rule 5: identity only
    expect(await screen.findByText(/^No layout yet/)).toBeVisible();
    expect(getWorkspace).toHaveBeenCalledTimes(1);
    expect(listWorkspaces).toHaveBeenCalledWith(expect.any(AbortSignal)); // cancelled on leave
  });

  it("test_flag_on_with_no_workspace_says_so_and_a_failed_list_offers_try_again", async () => {
    flags("health", { [WORKSPACE_DOCK_FLAG]: true });
    listWorkspaces.mockResolvedValueOnce(answer([]));
    at("/terminal/last");
    expect(await screen.findByText("No workspaces yet — create one")).toBeVisible();
    cleanup();
    listWorkspaces.mockResolvedValueOnce({ ok: false, failure: { kind: "unavailable" } });
    at("/terminal/last");
    expect(await screen.findByText("Couldn't load workspaces.")).toBeVisible();
    act(() => screen.getByRole("button", { name: "Try again" }).click());
    await waitFor(() => expect(getWorkspace).toHaveBeenCalled());
  });

  it("test_flag_on_an_unknown_layout_id_is_the_404_not_the_default", async () => {
    flags("health", { [WORKSPACE_DOCK_FLAG]: true });
    const router = at("/terminal/0190a000-0000-7000-8000-0000000000ff");
    expect(await screen.findByRole("heading", { level: 1 })).toBeVisible(); // the uniform 404
    expect(router.state.location.pathname).toMatch(/^\/terminal\//);
    expect(getWorkspace).toHaveBeenCalledTimes(1);
  });
});
