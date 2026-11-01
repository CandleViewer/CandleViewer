import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { buildRoutes } from "../../src/routes/tree";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { ROUTE_TITLES, pageTitle, syncDocumentTitle } from "../../src/routes/titles";
import { setMeClaims, resetMeClaims } from "../../src/lib/auth/meCache";
import { resetShellState, setShellState, type Me } from "../../src/shell/bootstrap/store";
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

/** A route's render with the admin area's lazy chunk: a busy host can take seconds over it. */
const ROUTE_WAIT = { timeout: 5_000 } as const;

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

  // The first admin render in this file loads the admin area's code, SCR-120 included: its own budget.
  it(
    "renders /admin for an owner with no step-up dialog and no step-up request (#2725)",
    { timeout: 30_000 },
    async () => {
      const f = vi.fn();
      vi.stubGlobal("fetch", f);
      claimsFor("owner");
      const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/admin?tab=x"] });
      render(<RouterProvider router={router} />);
      // the admin area's code arrives lazily, after the guard (E42-S01 BQ-7), with SCR-120 at R-300
      const first = { timeout: 20_000 }; // a busy host transforms the chunk's modules first
      expect(
        await screen.findByRole("heading", { name: "Overview", level: 1 }, first),
      ).toBeInTheDocument();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(router.state.location.search).toBe("?tab=x");
      expect(f.mock.calls.filter(([u]) => String(u).includes("/auth/step-up"))).toEqual([]);
    },
  );

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
        await waitFor(() => expect(screen.getByRole("main")).toBeInTheDocument());
        unmount();
      }
    },
  );
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

// ---- E42-S01 (#1022): every admin route inside CMP-087 AdminLayout, its code loaded behind the guard
// (BQ-7). That a non-owner loads no admin module at all is pinned in
// test/features/admin/shell/lazyBoundary.test.tsx, whose module registry is fresh; here an earlier
// test may already have loaded it.

const ADMIN_ROUTES = ROUTE_MANIFEST.filter(
  (e) => e.path === "/admin" || e.path.startsWith("/admin/"),
);
const concrete = (path: string): string => path.replace(/:[a-zA-Z]+/g, "x");
/** The band's route words: the page title (`titles.ts`, `12` §2); `/admin` is SCR-120's "Overview". */
const bandLabel = (id: string): string => (id === "R-300" ? "Overview" : (ROUTE_TITLES[id] ?? id));
/** The page each admin route shows today when it is not a stub. */
const PAGE_H1: Readonly<Record<string, string>> = {
  "R-300": "Overview", // SCR-120 (E42-S01)
  "R-303": "Invite user",
  "R-354": "Security centre",
  "R-360": "R-360 — owned by E09",
};

/** A session as the bootstrap leaves it: the guards' claims and the shell's `me` and environment. */
function sessionFor(role: Role): void {
  claimsFor(role);
  const me = { role, permissions: [], accounts: [], user: { username: `${role}.one` } };
  setShellState({ me: me as unknown as Me, environment: "demo" });
}

const requested = (): string[] => vi.mocked(fetch).mock.calls.map(([input]) => String(input));

describe("E42-S01: the admin routes inside CMP-087 AdminLayout", () => {
  beforeEach(() => {
    resetMeClaims();
    resetShellState();
    const body = JSON.stringify({ items: [] });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(body, { headers: { "Content-Type": "application/json" } })),
    );
  });
  afterEach(() => {
    resetShellState();
    vi.unstubAllGlobals();
  });

  it(
    "frames every admin route for an owner: the band first in main, then the page's one h1",
    { timeout: 60_000 },
    async () => {
      sessionFor("owner");
      expect(ADMIN_ROUTES).toHaveLength(21);
      for (const entry of ADMIN_ROUTES) {
        const router = createMemoryRouter(buildRoutes(), {
          initialEntries: [concrete(entry.path)],
        });
        const view = render(<RouterProvider router={router} />);
        const band = await screen.findByRole("region", { name: "Admin area" }, ROUTE_WAIT);
        expect(band.textContent, entry.id).toBe(`◆ Admin area · ${bandLabel(entry.id)}`);
        const main = screen.getByRole("main");
        // the outlet's first element is the area's D1 inset, the layout is its first element and
        // the band is the layout's first
        const area = main.querySelector("[data-shell-canvas]")?.firstElementChild;
        expect(area?.firstElementChild, entry.id).toHaveAttribute("data-cmp", "CMP-087");
        expect(area?.firstElementChild?.firstElementChild, entry.id).toBe(band);
        const [h1, ...more] = within(main).getAllByRole("heading", { level: 1 });
        expect(more, entry.id).toEqual([]);
        expect(h1, entry.id).toHaveAccessibleName(
          PAGE_H1[entry.id] ?? `${entry.id} — owned by E18`,
        );
        const after = band.compareDocumentPosition(h1 as HTMLElement);
        expect(after & Node.DOCUMENT_POSITION_FOLLOWING, entry.id).toBeTruthy();
        view.unmount();
        router.dispose();
      }
    },
  );

  it("frames R-360 /admin/audit for an owner only: a manager keeps the plain shell", async () => {
    sessionFor("manager");
    const plain = renderAt("/admin/audit");
    const stub = { name: "R-360 — owned by E09", level: 1 } as const;
    expect(await screen.findByRole("heading", stub, ROUTE_WAIT)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Admin area" })).toBeNull();
    plain.unmount();
    sessionFor("owner");
    renderAt("/admin/audit");
    const band = await screen.findByRole("region", { name: "Admin area" }, ROUTE_WAIT);
    expect(band.textContent).toBe("◆ Admin area · Audit log");
    expect(screen.getByRole("heading", stub)).toBeInTheDocument();
  });

  it(
    "gives a manager and a viewer the 404 on every hidden admin route: no band, no admin request",
    { timeout: 60_000 },
    async () => {
      for (const role of ["manager", "viewer"] as const) {
        sessionFor(role);
        for (const entry of ADMIN_ROUTES.filter((e) => e.access.denyAs === "404")) {
          const router = createMemoryRouter(buildRoutes(), {
            initialEntries: [concrete(entry.path)],
          });
          const view = render(<RouterProvider router={router} />);
          await screen.findByRole("heading", { name: "Page not found", level: 1 }, ROUTE_WAIT);
          expect(screen.queryByRole("region", { name: "Admin area" }), entry.id).toBeNull();
          view.unmount();
          router.dispose();
        }
      }
      expect(requested().filter((url) => url.includes("/api/v1/admin"))).toEqual([]);
      // the watcher sees an admin page's own reads: the owner's invite screen lists the invites
      sessionFor("owner");
      renderAt("/admin/users/new");
      await waitFor(
        () => expect(requested().some((u) => u.endsWith("/users/invites"))).toBe(true),
        ROUTE_WAIT,
      );
    },
  );

  it(
    "moves focus to the page h1 on the way in, with the one route announcement",
    { timeout: 30_000 },
    async () => {
      sessionFor("owner");
      const lands = async (path: string, h1: string): Promise<string[]> => {
        const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/journal"] });
        render(<RouterProvider router={router} />);
        await screen.findByRole("heading", { name: /R-180/ }, ROUTE_WAIT);
        const announced: string[] = [];
        const record = (records: MutationRecord[]): void => {
          for (const node of records.flatMap((r) => [...r.addedNodes])) {
            if (node instanceof HTMLElement && node.hasAttribute("data-seq")) {
              announced.push(node.textContent ?? "");
            }
          }
        };
        const regions = new MutationObserver(record);
        regions.observe(document.body, { childList: true, subtree: true });
        await act(() => router.navigate(path));
        const heading = await screen.findByRole("heading", { name: h1, level: 1 }, ROUTE_WAIT);
        await waitFor(() => expect(document.activeElement).toBe(heading), ROUTE_WAIT);
        record(regions.takeRecords());
        regions.disconnect();
        cleanup();
        router.dispose();
        return announced;
      };
      const plain = await lands("/risk", "R-150 — owned by E12");
      const admin = await lands("/admin/users", "R-301 — owned by E18");
      expect(plain).not.toEqual([]);
      expect(admin).toEqual(plain);
    },
  );
});
