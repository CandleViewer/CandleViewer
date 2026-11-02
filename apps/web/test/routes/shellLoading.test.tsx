/**
 * #5335 delta A-5335-d06: a first visit to a lazy screen (R-110 and R-111, `LAZY_SCREENS` in `routes/tree.tsx`)
 * draws one loading line while the screen's chunk loads, where it drew nothing and React Router logged "No
 * `HydrateFallback` element provided". The line is CMP-038 with SCR-150's words (E10-D03 §9.3), on the app surface
 * (the shell, which paints it, is not mounted yet). It is not the shell: the shell's chrome waits for the route guard,
 * which runs with the chunk's load, so a signed-out visit never sees it. This file renders no other first visit, so the
 * router's once-only warning is this test's to see.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { resetMeClaims, setMeClaims } from "../../src/lib/auth/meCache";
import { buildRoutes } from "../../src/routes/tree";

const json = (body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

afterEach(() => {
  resetMeClaims();
  apiFetch.mockReset();
  vi.restoreAllMocks();
});

describe("a first visit to a lazy screen", () => {
  it("A-5335-d06: draws one loading line on the app surface while the chunk loads, then the screen; React Router has nothing to warn of", async () => {
    apiFetch.mockImplementation(async () => json({ items: [] }));
    setMeClaims({ authenticated: true, role: "owner", permissions: ["workspaces:write"] });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/watchlist/x"] });
    render(<RouterProvider router={router} />);
    // The first paint, before any promise has settled: the screen is still on its way.
    const line = screen.getByRole("status");
    expect(line).toHaveTextContent("Loading");
    const page = screen.getByRole("main");
    expect(page).toContainElement(line);
    // Outside the shell, which paints `color.surface.app`: unpainted, its text sat on the browser's white (#4927).
    expect(page.style.background).toBe("var(--color-surface-app)");
    expect(page.style.color).toBe("var(--color-text-primary)");
    expect(screen.queryByRole("navigation")).toBeNull(); // no chrome yet
    await screen.findByRole("heading", { level: 1, name: "Watchlist" }, { timeout: 15_000 });
    expect(page.isConnected).toBe(false); // the line went with the fallback
    expect(warn).not.toHaveBeenCalledWith(expect.stringContaining("HydrateFallback"));
  }, 60_000);

  it("A-5335-d06: a signed-out visit sees the line and no shell, then goes to sign in (the guard is unchanged)", async () => {
    apiFetch.mockImplementation(async () => json({ items: [] }));
    setMeClaims({ authenticated: false, role: null, permissions: [] });
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/watchlist/x"] });
    render(<RouterProvider router={router} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("banner")).toBeNull();
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"), {
      timeout: 15_000,
    });
    expect(router.state.location.search).toBe("?next=%2Fwatchlist%2Fx");
  }, 60_000);
});
