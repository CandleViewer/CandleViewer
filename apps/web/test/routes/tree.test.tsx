import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, type RouteObject } from "react-router";
import { RouterProvider } from "react-router/dom";
import { buildRoutes } from "../../src/routes/tree";
import { WatchlistRoute } from "../../src/features/watchlist/WatchlistRoute";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { pageTitle, syncDocumentTitle } from "../../src/routes/titles";
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

function claimsFor(role: Role | null) {
  setMeClaims({
    authenticated: role !== null,
    role,
    permissions: [],
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

  it("R-005 /locked is an alias: it lands on the default route, where the overlay host opens the lock (#1640)", async () => {
    claimsFor("viewer");
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/locked"] });
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(router.state.location.pathname).toBe("/terminal/last"));
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
      expect(
        screen.getByRole("heading", { name: "You don't have access to this", level: 1 }),
      ).toBeInTheDocument(),
    );
  });

  it("renders 404, not 403, for a viewer hitting an admin route", async () => {
    claimsFor("viewer");
    renderAt("/admin/users");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Page not found", level: 1 })).toBeInTheDocument(),
    );
  });

  it("renders 404, not 403, for a manager hitting an admin route", async () => {
    claimsFor("manager");
    renderAt("/admin");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Page not found", level: 1 })).toBeInTheDocument(),
    );
  });

  it("renders /admin for an owner with no step-up dialog and no step-up request (#2725)", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    claimsFor("owner");
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/admin?tab=x"] });
    render(<RouterProvider router={router} />);
    expect(
      await screen.findByRole("heading", { name: /R-300 — owned by E18/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(router.state.location.search).toBe("?tab=x");
    expect(f.mock.calls.filter(([u]) => String(u).includes("/auth/step-up"))).toEqual([]);
  });

  // The walk mounts every manifest route in turn, so its time grows with the manifest: its own budget.
  it(
    "every manifest route is reachable by at least one role without crashing",
    { timeout: 15_000 },
    async () => {
      claimsFor("owner");
      for (const entry of ROUTE_MANIFEST) {
        if (entry.access.roles === "public") continue;
        if (!entry.access.roles.includes("owner")) continue;
        const concretePath = entry.path.replace(/:[a-zA-Z]+/g, "x");
        const router = createMemoryRouter(buildRoutes(), { initialEntries: [concretePath] });
        const { unmount } = render(<RouterProvider router={router} />);
        // R-110 opens SCR-101 (#4702), a modal: the page under it is inert, `aria-hidden` where jsdom has no `inert`.
        const hidden = entry.id === "R-110";
        await waitFor(() => expect(screen.getByRole("main", { hidden })).toBeInTheDocument());
        if (hidden) expect(screen.getByRole("dialog", { name: "Watchlists" })).toBeInTheDocument();
        unmount();
      }
    },
  );
});

describe("feature routes load on first visit (C-14.3; #5335's read)", () => {
  /** A route of the shell's children, as `buildRoutes` declares it. */
  const shellRoute = (id: string): RouteObject | undefined =>
    buildRoutes()
      .find((route) => route.id === "shell")
      ?.children?.find((route) => route.id === id);

  it.each(["R-110", "R-111"])(
    "%s: its screen is a route `lazy` (no static element); the guard and the access are unchanged",
    async (id) => {
      const route = shellRoute(id);
      expect(route?.element).toBeUndefined();
      expect(route?.loader).toBeTypeOf("function");
      expect(ROUTE_MANIFEST.find((entry) => entry.id === id)?.access).toEqual({
        roles: ["owner", "manager", "viewer"],
      });
      const lazy = route?.lazy;
      expect(lazy).toBeTypeOf("function");
      const loaded = typeof lazy === "function" ? await lazy() : undefined;
      expect(loaded).toEqual({ Component: WatchlistRoute });
    },
  );

  it("a signed-out visit is still guarded: /watchlist/x goes to sign in, coming back there after", async () => {
    claimsFor(null);
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/watchlist/x"] });
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(router.state.location.search).toBe("?next=%2Fwatchlist%2Fx");
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
  beforeEach(() => claimsFor("owner"));
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

describe("page titles (D-01, WCAG 2.4.2)", () => {
  beforeEach(() => {
    resetMeClaims();
    document.title = "CandleViewer";
  });

  it("sets the title on load and on every navigation, guard errors included", async () => {
    claimsFor("viewer");
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/login"] });
    const stop = syncDocumentTitle(router);
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(document.title).toBe("Login - CandleViewer"));
    await act(() => router.navigate("/login/change-password"));
    expect(document.title).toBe("Forced password change - CandleViewer");
    await act(() => router.navigate("/admin/users/new")); // a viewer: hidden as 404
    expect(document.title).toBe("Not found - CandleViewer");
    await act(() => router.navigate("/no-such-page"));
    expect(document.title).toBe("Not found - CandleViewer");
    await act(() => router.navigate("/watchlist"));
    expect(document.title).toBe("Watchlists - CandleViewer");
    stop();
    await act(() => router.navigate("/login"));
    expect(document.title).toBe("Watchlists - CandleViewer"); // unsubscribed
  });

  it("names a role-denied route Forbidden", async () => {
    claimsFor("viewer");
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/risk"] });
    const stop = syncDocumentTitle(router);
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(document.title).toBe("Forbidden - CandleViewer"));
    stop();
  });

  it.each([
    [404, "Not found"],
    [403, "Forbidden"],
    [500, "Something went wrong"],
    [503, "Something went wrong"],
  ])("names a %i route error response %s, never Forbidden for a server error", (status, title) => {
    const error = { status, statusText: "", internal: false, data: null };
    type State = Parameters<typeof pageTitle>[0];
    const state = { errors: { root: error }, matches: [] } as unknown as State;
    expect(pageTitle(state)).toBe(title);
  });
});
