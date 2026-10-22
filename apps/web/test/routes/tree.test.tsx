import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { buildRoutes, V7_RENDER_FLAGS, V7_ROUTER_FLAGS } from "../../src/routes/tree";
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
  const router = createMemoryRouter(buildRoutes(), {
    initialEntries: [path],
    future: V7_ROUTER_FLAGS,
  });
  return render(<RouterProvider router={router} future={V7_RENDER_FLAGS} />);
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

  it("redirects an unauthenticated user hitting a protected deep link to /login, not the terminal stub", async () => {
    claimsFor(null);
    const router = createMemoryRouter(buildRoutes(), {
      initialEntries: ["/terminal/abc?tf=15"],
      future: V7_ROUTER_FLAGS,
    });
    render(<RouterProvider router={router} future={V7_RENDER_FLAGS} />);
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
      const router = createMemoryRouter(buildRoutes(), {
        initialEntries: [concretePath],
        future: V7_ROUTER_FLAGS,
      });
      const { unmount } = render(<RouterProvider router={router} future={V7_RENDER_FLAGS} />);
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
