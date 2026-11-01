/**
 * E42-S01 (#1022) BQ-7: the admin area's code loads only after the route guard let the session in
 * (E42-D03 §11: "the 404 with no call and no admin code loaded"). The admin area is one module behind
 * `React.lazy`, SCR-120's overview inside it; this file counts both modules' evaluations, which stand
 * for the chunk a browser would fetch. One test, so no other test can have loaded either module
 * first: the module registry is this file's.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as AdminAreaModule from "../../../../src/features/admin/shell/AdminArea";
import type * as OverviewModule from "../../../../src/features/admin/overview/OverviewPage";
import { resetMeClaims, setMeClaims } from "../../../../src/lib/auth/meCache";
import { ROUTE_MANIFEST } from "../../../../src/routes/manifest";
import type { Role } from "../../../../src/routes/rbac";
import { buildRoutes } from "../../../../src/routes/tree";
import { resetShellState, setShellState, type Me } from "../../../../src/shell/bootstrap/store";

const chunk = vi.hoisted(() => ({ loads: 0, overview: 0 }));
vi.mock("../../../../src/features/admin/shell/AdminArea", async (importOriginal) => {
  chunk.loads += 1;
  return importOriginal<typeof AdminAreaModule>();
});
vi.mock("../../../../src/features/admin/overview/OverviewPage", async (importOriginal) => {
  chunk.overview += 1;
  return importOriginal<typeof OverviewModule>();
});

const ADMIN_ROUTES = ROUTE_MANIFEST.filter(
  (e) => e.path === "/admin" || e.path.startsWith("/admin/"),
);
const concrete = (path: string): string => path.replace(/:[a-zA-Z]+/g, "x");

/** A session as the bootstrap leaves it: the guards' claims and the shell's `me`. */
function sessionFor(role: Role): void {
  setMeClaims({ authenticated: true, role, permissions: [] });
  const me = { role, permissions: [], accounts: [], user: { username: `${role}.one` } };
  setShellState({ me: me as unknown as Me, environment: "demo" });
}

/** What a denied session sees on an admin route: the hidden route's 404, or R-360's own page. */
function deniedHeading(role: Role, id: string): string {
  if (id !== "R-360") return "Page not found";
  return role === "manager" ? "R-360 — owned by E09" : "You don't have access to this";
}

/** A route's render with the admin area's lazy chunk: a busy host can take seconds over it. */
const ROUTE_WAIT = { timeout: 5_000 } as const;

const requested = (): string[] => vi.mocked(fetch).mock.calls.map(([input]) => String(input));

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

describe("E42-S01 BQ-7: the admin area's code sits behind the guard", () => {
  it(
    "loads no admin code and makes no admin request for a manager or a viewer; an owner's route loads it",
    { timeout: 120_000 },
    async () => {
      for (const role of ["manager", "viewer"] as const) {
        sessionFor(role);
        for (const entry of ADMIN_ROUTES) {
          const router = createMemoryRouter(buildRoutes(), {
            initialEntries: [concrete(entry.path)],
          });
          const view = render(<RouterProvider router={router} />);
          const name = deniedHeading(role, entry.id);
          await screen.findByRole("heading", { name, level: 1 }, ROUTE_WAIT);
          expect(screen.queryByRole("region", { name: "Admin area" }), entry.id).toBeNull();
          view.unmount();
          router.dispose();
        }
      }
      expect([chunk.loads, chunk.overview]).toEqual([0, 0]); // R-300's overview included
      // None of the area's reads either: no `/admin/*` call, and not the Users tile's
      // `/users/invites`, its one read outside that prefix (S-5330-04).
      const areaReads = (url: string): boolean =>
        url.includes("/api/v1/admin") || url.includes("/api/v1/users/invites");
      expect(requested().filter(areaReads)).toEqual([]);

      // The positive control, through the same watchers: an owner walks in from the journal.
      sessionFor("owner");
      const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/journal"] });
      render(<RouterProvider router={router} />);
      await screen.findByRole("heading", { name: /R-180/ }, ROUTE_WAIT);
      expect(chunk.loads).toBe(0);
      await act(() => router.navigate("/admin/users/new"));
      const band = await screen.findByRole("region", { name: "Admin area" }, ROUTE_WAIT);
      expect(band.textContent).toBe("◆ Admin area · Invite user");
      expect(chunk.loads).toBe(1);
      // The shell found no h1 while the code was on its way; focus still ends on the page's h1.
      const h1 = screen.getByRole("heading", { name: "Invite user", level: 1 });
      await waitFor(() => expect(document.activeElement).toBe(h1), ROUTE_WAIT);
      await waitFor(
        () => expect(requested().some((u) => u.endsWith("/users/invites"))).toBe(true),
        ROUTE_WAIT,
      );
      // Only now does the owner's area read: the strip's sources on every admin route.
      await waitFor(() => expect(requested()).toContain("/api/v1/admin/overview"), ROUTE_WAIT);
      // And R-300 mounts SCR-120 from the same chunk, which was evaluated once.
      await act(() => router.navigate("/admin"));
      await screen.findByRole("heading", { name: "Overview", level: 1 }, ROUTE_WAIT);
      expect([chunk.loads, chunk.overview]).toEqual([1, 1]);
      await waitFor(() => expect(requested()).toContain("/api/v1/admin/health"), ROUTE_WAIT);
    },
  );
});
