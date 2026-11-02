/**
 * E29-S01 (#911, BQ-16): the positions panel's code loads only once R-130's loader has let the
 * session in. The panel is one module behind `React.lazy` in the route's element (`tree.tsx`). This
 * file counts its evaluations, which stand for the chunk a browser would fetch, as in
 * `lazyBoundary.test.tsx` for the admin area (E42-S01 BQ-7): a visitor with no session is
 * redirected to `/login?next=…` by the loader, so the element never renders and the module is
 * never requested. One test, so no other test can have loaded the module first: the module registry
 * is this file's (the panel is imported up front in `positions-route.test.tsx`, so its count could
 * not start at zero).
 */
import { render, screen, waitFor, type RenderResult } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PreferencesProvider } from "../../src/features/a11y-preferences/PreferencesContext";
import type * as PositionsPanelModule from "../../src/features/positions/PositionsPanel";
import { resetMeClaims, setMeClaims } from "../../src/lib/auth/meCache";
import type { Role } from "../../src/routes/rbac";
import { buildRoutes } from "../../src/routes/tree";

const chunk = vi.hoisted(() => ({ loads: 0 }));
vi.mock("../../src/features/positions/PositionsPanel", async (importOriginal) => {
  chunk.loads += 1;
  return importOriginal<typeof PositionsPanelModule>();
});

/** The guards' claims: no session for `null`, else a signed-in one of that role. */
function claimsFor(role: Role | null): void {
  setMeClaims({ authenticated: role !== null, role, permissions: [] });
}

/**
 * The real route tree, its loaders and shell included, at `path`, inside the provider `App.tsx`
 * mounts it in.
 */
function mountAt(path: string): {
  readonly router: ReturnType<typeof createMemoryRouter>;
  readonly view: RenderResult;
} {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  const view = render(
    <PreferencesProvider>
      <RouterProvider router={router} />
    </PreferencesProvider>,
  );
  return { router, view };
}

beforeEach(() => {
  resetMeClaims();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 404 })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * A route's wait on a busy host: the sibling's 20 s for the lazy panel's first import and render
 * (`positions-route.test.tsx`). The redirect waits as long, so a regression that holds the redirect
 * behind the import still fails on the count below, not on a timeout.
 */
const ROUTE_WAIT = { timeout: 20_000 } as const;

describe("E29-S01 BQ-16: the positions panel's code sits behind the guard", () => {
  it(
    "loads no panel code for a visitor the guard sends to /login; a signed-in visit loads it",
    { timeout: 60_000 },
    async () => {
      claimsFor(null);
      const denied = mountAt("/positions?groupBy=symbol");
      await waitFor(() => expect(denied.router.state.location.pathname).toBe("/login"), ROUTE_WAIT);
      expect(denied.router.state.location.search).toBe("?next=%2Fpositions%3FgroupBy%3Dsymbol");
      // settle any import the denied route started before the count is read
      await vi.dynamicImportSettled();
      expect(chunk.loads).toBe(0);
      denied.view.unmount();
      denied.router.dispose();

      // The positive control, through the same watcher: a signed-in visit loads the panel.
      claimsFor("owner");
      const allowed = mountAt("/positions");
      // `hidden: true` skips RTL's accessibility walk on every poll; visibility is asserted once
      const heading = await screen.findByRole(
        "heading",
        { level: 1, name: "Positions and orders", hidden: true },
        ROUTE_WAIT,
      );
      expect(heading).toBeVisible();
      expect(allowed.router.state.location.pathname).toBe("/positions");
      expect(chunk.loads).toBe(1);
    },
  );
});
