import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
// RouterProvider comes from "react-router", not "react-router/dom" as in App.tsx: under
// Vitest 3 on Node >= 20.19 the dom entry loads a second router copy and error elements
// lose their context (#1819).
import { createMemoryRouter, RouterProvider } from "react-router";
import { buildRoutes } from "../../src/routes/tree";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { setMeClaims, resetMeClaims } from "../../src/lib/auth/meCache";
import type { Role } from "../../src/routes/rbac";

/**
 * Route matrix x role matrix: iterates a representative sample of route IDs
 * across owner/manager/viewer and asserts the rendered outcome, per the
 * ticket's Integration test-plan line. The exhaustive per-role x per-route
 * sweep for every one of the 65 routes lives in E10-Q02's E2E suite; this
 * unit-level test proves the guard composition and the admin-404 rule.
 */
function renderAt(path: string) {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

function claimsFor(role: Role | null, elevatedAt: string | null = null) {
  setMeClaims({
    authenticated: role !== null,
    role,
    permissions: [],
    elevatedAt,
  });
}

describe("route tree x RBAC matrix", () => {
  beforeEach(() => {
    resetMeClaims();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("redirects an unauthenticated user hitting a protected deep link to /login, not the terminal stub", async () => {
    claimsFor(null);
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/terminal/abc?tf=15"] });
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(router.state.location.search).toBe("?next=%2Fterminal%2Fabc%3Ftf%3D15");
  });

  it("renders the owner-owned stub for R-150 /risk when signed in as owner", async () => {
    claimsFor("owner");
    renderAt("/risk");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /R-150 — owned by E12/ })).toBeInTheDocument(),
    );
  });

  it("renders 403 for a viewer hitting an owner-only non-admin route", async () => {
    claimsFor("viewer");
    renderAt("/risk");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Forbidden" })).toBeInTheDocument(),
    );
  });

  it("renders 404, not 403, for a viewer hitting an admin route", async () => {
    claimsFor("viewer");
    renderAt("/admin/users");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Not found" })).toBeInTheDocument(),
    );
  });

  it("renders 404, not 403, for a manager hitting an admin route", async () => {
    claimsFor("manager");
    renderAt("/admin");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Not found" })).toBeInTheDocument(),
    );
  });

  it("shows the step-up modal for an owner whose step-up has expired", async () => {
    claimsFor("owner", null);
    renderAt("/admin");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Confirm it's you" })).toBeInTheDocument(),
    );
  });

  it("returns to /admin?tab=x, replacing the entry, when Continue is pressed after a step-up", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ elevated_until: new Date().toISOString() }),
      }),
    );
    claimsFor("owner", null);
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/admin?tab=x"] });
    render(<RouterProvider router={router} />);
    fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue" }));
    expect(
      await screen.findByRole("heading", { name: /R-300 — owned by E18/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(router.state.historyAction).toBe("REPLACE");
    expect(router.state.location.search).toBe("?tab=x");
  });

  it("renders the admin stub for an owner with fresh step-up", async () => {
    claimsFor("owner", new Date().toISOString());
    renderAt("/admin");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /R-300 — owned by E18/ })).toBeInTheDocument(),
    );
  });

  it("every manifest route is reachable by at least one role without crashing", async () => {
    claimsFor("owner", new Date().toISOString());
    for (const entry of ROUTE_MANIFEST) {
      if (entry.access.roles === "public") continue;
      if (!entry.access.roles.includes("owner")) continue;
      const concretePath = entry.path.replace(/:[a-zA-Z]+/g, "x");
      const router = createMemoryRouter(buildRoutes(), { initialEntries: [concretePath] });
      const { unmount } = render(<RouterProvider router={router} />);
      await waitFor(() => expect(screen.getByRole("main")).toBeInTheDocument());
      unmount();
    }
  });
});

describe("E49-S07 reachability through the real route tree", () => {
  beforeEach(() => resetMeClaims());
  it("mounts SCR-113 HotkeyEditor at /settings/hotkeys", async () => {
    claimsFor("owner");
    renderAt("/settings/hotkeys");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /hotkeys|keyboard/i })).toBeInTheDocument(),
    );
  });
});

describe("route ranking: a static path outranks its dynamic sibling", () => {
  beforeEach(() => claimsFor("owner", new Date().toISOString()));
  it.each([
    ["/trade-groups/new", "R-142"],
    ["/trade-groups/g1", "R-141"],
    ["/rules/new", "R-163"],
    ["/rules/r1", "R-161"],
    ["/journal/analytics", "R-182"],
    ["/journal/t1", "R-181"],
    ["/admin/users/new", "R-303"],
    ["/admin/users/u1", "R-302"],
    ["/admin/accounts/new", "R-312"],
    ["/admin/accounts/a1", "R-311"],
  ])("%s resolves to %s", (path, routeId) => {
    const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
    expect(router.state.matches.at(-1)?.route.id).toBe(routeId);
    router.dispose();
  });
});
