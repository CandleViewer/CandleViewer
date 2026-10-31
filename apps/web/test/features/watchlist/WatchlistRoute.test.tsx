/**
 * E08-S08 (#4702): SCR-100 is R-111's routed page in the shell's `main` (pre-ruling 1): through the real route tree,
 * `/watchlist/:groupId` renders the page's heading and the list's grid, an unknown list is the not-found state, a
 * list switched from its tab keeps keyboard focus on the tabs past the shell's route focus, and R-110 is left to
 * SCR-101 (#4702 PR c). The REST calls are answered by a faked `apiFetch` (no network).
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { ROUTE_FOCUS_KEEP } from "../../../src/features/app-shell/useRouteFocus";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import { buildRoutes } from "../../../src/routes/tree";

const MAJORS = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Majors",
  symbols: ["BTCUSDT", "ETHUSDT"],
  columns: [],
  version: 1,
  created_at: "2026-10-30T10:00:00Z",
  updated_at: "2026-10-30T10:00:00Z",
};
const ALTS = {
  ...MAJORS,
  id: "22222222-2222-4222-8222-222222222222",
  name: "Alts",
  symbols: ["SOLUSDT"],
};
const instrument = (symbol: string) => ({
  symbol,
  category: "linear",
  status: "Trading",
  price_scale: 2,
  tick_size: "0.1",
  qty_step: "0.001",
});
const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  setMeClaims({ authenticated: true, role: "owner", permissions: ["workspaces:write"] });
  apiFetch.mockImplementation(async (url: string) => {
    if (url === "/api/v1/watchlists") return json({ items: [MAJORS, ALTS] });
    if (url.startsWith("/api/v1/instruments?"))
      return json({
        items: [instrument("BTCUSDT"), instrument("ETHUSDT"), instrument("SOLUSDT")],
        meta: { next_cursor: null, has_more: false, count: 3, cache_age_s: 1, stale_since: null },
      });
    return json({ status: 404 }, 404);
  });
});
afterEach(() => {
  resetMeClaims();
  apiFetch.mockReset();
});

const renderAt = (path: string) => {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
};

describe("R-111 /watchlist/:groupId", () => {
  /**
   * The route's modules load on its first render and its page reads the lists: on a loaded runner the page comes well
   * past findBy's default second (React Router draws nothing meanwhile).
   */
  const WAIT = { timeout: 15_000 };

  it(
    "renders SCR-100 for the list: the page heading and the list's grid",
    { timeout: 60_000 },
    async () => {
      renderAt(`/watchlist/${MAJORS.id}`);
      expect(
        await screen.findByRole("heading", { level: 1, name: "Watchlist" }, WAIT),
      ).toBeInTheDocument();
      expect(
        await screen.findByRole(
          "grid",
          { name: "Watchlist Majors, 2 symbols, manual order" },
          WAIT,
        ),
      ).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Watchlist Majors" })).toBeInTheDocument();
    },
  );

  it("an id that is none of the user's lists is the not-found state", async () => {
    renderAt("/watchlist/99999999-9999-4999-8999-999999999999");
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 })).not.toHaveTextContent("Watchlist"),
    );
    expect(screen.queryByRole("grid")).toBeNull();
  });

  it(
    "Enter on a list's tab switches the page by a marked navigation: focus stays on that tab and never visits the h1 (WCAG 2.4.3)",
    { timeout: 60_000 },
    async () => {
      const router = renderAt(`/watchlist/${MAJORS.id}`);
      await screen.findByRole("grid", { name: /^Watchlist Majors/ }, WAIT);
      const alts = screen.getByRole("tab", { name: /^Alts/ });
      act(() => alts.focus());
      // Every element focus enters from the press on: the shell's route focus would move it to the h1 first.
      const entered: string[] = [];
      const record = (event: FocusEvent): void => {
        if (event.target instanceof Element) entered.push(event.target.tagName.toLowerCase());
      };
      document.addEventListener("focusin", record);
      try {
        await act(async () => {
          fireEvent.keyDown(alts, { key: "Enter" });
        });
        await screen.findByRole("grid", { name: /^Watchlist Alts/ }, WAIT);
        // every effect of the route change has run, the shell's route focus among them
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 0));
        });
      } finally {
        document.removeEventListener("focusin", record);
      }
      expect(router.state.location.pathname).toBe(`/watchlist/${ALTS.id}`);
      expect(router.state.location.state).toEqual({ [ROUTE_FOCUS_KEEP]: true });
      const tab = screen.getByRole("tab", { name: /^Alts/ });
      expect(tab).toHaveAttribute("aria-selected", "true");
      expect(document.activeElement).toBe(tab);
      expect(entered).not.toContain("h1");
    },
  );
});
