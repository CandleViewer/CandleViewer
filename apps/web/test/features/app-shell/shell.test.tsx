import { createRequire } from "node:module";
import { useEffect, type JSX, type ReactNode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../../../src/features/app-shell/AppShell";
import { buildRoutes } from "../../../src/routes/tree";
import { ROUTE_MANIFEST } from "../../../src/routes/manifest";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import type { Role } from "../../../src/routes/rbac";
import { PreferencesProvider } from "../../../src/features/a11y-preferences/PreferencesContext";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

function signIn(role: Role | null): void {
  setMeClaims({ authenticated: role !== null, role, permissions: [] });
}

function renderAt(path: string) {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

/** Elements reachable by Tab, in document order (jsdom has no real Tab traversal). */
function tabStops(): HTMLElement[] {
  const sel =
    "a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]";
  return [...document.querySelectorAll<HTMLElement>(sel)].filter((el) => el.tabIndex >= 0);
}

beforeEach(() => resetMeClaims());
afterEach(() => vi.unstubAllGlobals());

describe("E10-S01 S1: ShellLayout landmarks and one main per route", () => {
  it("renders the banner, Primary navigation, main, complementary and contentinfo landmarks", async () => {
    signIn("owner");
    renderAt("/risk");
    await screen.findByRole("heading", { name: /R-150/ });
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("complementary")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });

  it("every non-public manifest route an owner can open renders exactly one main, holding the screen", async () => {
    signIn("owner");
    for (const entry of ROUTE_MANIFEST) {
      if (entry.access.roles === "public" || !entry.access.roles.includes("owner")) continue;
      const router = createMemoryRouter(buildRoutes(), {
        initialEntries: [entry.path.replace(/:[a-zA-Z]+/g, "x")],
      });
      const { unmount } = render(
        <PreferencesProvider>
          <RouterProvider router={router} />
        </PreferencesProvider>,
      );
      const [heading] = await screen.findAllByRole("heading");
      // the screen itself, never the route error fallback
      expect(screen.queryByRole("heading", { name: /Something went wrong/ }), entry.id).toBeNull();
      const mains = screen.getAllByRole("main");
      expect(mains, entry.id).toHaveLength(1);
      expect(mains[0]?.contains(heading as HTMLElement), entry.id).toBe(true);
      expect(screen.getByRole("banner"), entry.id).toBeInTheDocument();
      unmount();
      router.dispose();
    }
  }, 30_000); // a serial sweep of every route: slow under the full parallel suite

  it("keeps one main for a role denial rendered inside the shell", async () => {
    signIn("viewer");
    renderAt("/risk");
    await screen.findByRole("heading", { name: "You don't have access to this", level: 1 });
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });

  it("leaves public routes outside the shell, each with its own single main", async () => {
    signIn(null);
    renderAt("/login/2fa/enroll");
    await screen.findByRole("heading", { name: /R-006/ });
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
  });

  it("a direct load of /login/2fa holds no challenge, so it lands on SCR-001 with no query (#2711 BQ-02)", async () => {
    signIn(null);
    const router = renderAt("/login/2fa?mfa_token=planted#planted");
    await screen.findByRole("heading", { name: "Sign in to CandleViewer", level: 1 });
    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.search).toBe("");
    expect(screen.queryByRole("heading", { name: "Two-factor code" })).toBeNull();
  });

  it("renders the catch-all 404 inside the shell, with one main, like a hidden admin route", async () => {
    signIn("owner");
    renderAt("/no/such/page");
    await screen.findByRole("heading", { name: "Page not found", level: 1 });
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
  });
});

describe("E10-S01 S1: skip link and route focus", () => {
  it("makes the skip link the first Tab stop, and activating it focuses main", async () => {
    signIn("owner");
    renderAt("/risk");
    await screen.findByRole("heading", { name: /R-150/ });
    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(tabStops()[0]).toBe(skip);
    act(() => skip.focus());
    fireEvent.click(skip);
    expect(document.activeElement).toBe(screen.getByRole("main"));
  });

  it("does not move focus on first load, then focuses the main heading after navigation", async () => {
    signIn("owner");
    const router = renderAt("/risk");
    await screen.findByRole("heading", { name: /R-150/ });
    expect(document.activeElement).toBe(document.body);
    await act(() => router.navigate("/journal"));
    const heading = await screen.findByRole("heading", { name: /R-180/ });
    expect(document.activeElement).toBe(heading);
    expect(within(screen.getByRole("main")).getByRole("heading", { name: /R-180/ })).toBe(heading);
    fireEvent.blur(heading);
    expect(heading).not.toHaveAttribute("tabindex");
  });

  it("has no serious or critical axe violations in the shell", async () => {
    signIn("owner");
    renderAt("/risk");
    await screen.findByRole("heading", { name: /R-150/ });
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } }); // jsdom has no layout
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});

describe("E10-S01 S1: shell slots", () => {
  it("render nothing by default, apart from S3's connection chip", async () => {
    signIn("owner");
    renderAt("/risk");
    await screen.findByRole("heading", { name: /R-150/ });
    const connection = document.querySelector<HTMLElement>('[data-shell-slot="connection"]');
    expect(connection).not.toBeNull();
    if (connection !== null) {
      expect(within(connection).getByRole("button", { name: /^Connection: / })).toBeInTheDocument();
    }
    for (const slot of ["canvas-overlay"]) {
      const el = document.querySelector(`[data-shell-slot="${slot}"]`);
      expect(el, slot).not.toBeNull();
      expect(el?.childNodes.length, slot).toBe(0);
    }
    // #306: the banner slot holds the CMP-077 region, which renders nothing until a socket was up,
    // then CMP-092's empty polite region (E17-D02 §8, §11; its assertive words: the announcer's).
    const banner = document.querySelector('[data-shell-slot="banner"]');
    expect(
      [...(banner?.children ?? [])].map((c) => [
        c.getAttribute("aria-live"),
        c.getAttribute("role"),
        c.textContent,
      ]),
    ).toEqual([["polite", null, ""]]);
  });

  it("place filled content in its region and never remount the outlet", () => {
    let mounts = 0;
    function Outlet(): JSX.Element {
      useEffect(() => {
        mounts += 1;
      }, []);
      return <h1>Screen</h1>;
    }
    const shell = (fill: string | null): ReactNode => (
      <AppShell
        mainId="m"
        banner={fill && <p>{`banner ${fill}`}</p>}
        connection={fill && <span>{`conn ${fill}`}</span>}
        canvasOverlay={fill && <div>{`overlay ${fill}`}</div>}
      >
        <Outlet />
      </AppShell>
    );
    const { rerender } = render(shell(null));
    rerender(shell("a"));
    rerender(shell("b"));
    expect(within(screen.getByRole("banner")).getByText("conn b")).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getByText("overlay b")).toBeInTheDocument();
    const banner = screen.getByText("banner b");
    expect(screen.getByRole("main").contains(banner)).toBe(false);
    expect(screen.getByRole("banner").contains(banner)).toBe(false);
    rerender(shell(null));
    expect(mounts).toBe(1);
  });
});
