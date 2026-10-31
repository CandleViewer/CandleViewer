/**
 * E08-S08 (#4702): SCR-100 is R-111's routed page in the shell's `main` (pre-ruling 1): through the real route tree,
 * `/watchlist/:groupId` renders the page's heading and the list's grid, an unknown list is the not-found state, a
 * list switched from its tab keeps keyboard focus on its tab (a navigation marked `ROUTE_FOCUS_KEEP`, #304 S10, so
 * the shell's route focus never visits the h1). PR (c): SCR-101 is the page's `?modal=watchlists`, which R-110
 * opens, and closing it follows what it changed, focus on the page when no opener is left. The session's
 * `workspaces:write` decides the writes; a signed-out visit goes to sign in. The REST calls are answered by a faked
 * `apiFetch` holding the lists (no network).
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
import { resetShellState, setShellState, type Me } from "../../../src/shell/bootstrap/store";

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

/** The lists the faked `/watchlists` holds; a DELETE takes one out. */
let held: (typeof MAJORS)[] = [];

beforeEach(() => {
  setMeClaims({ authenticated: true, role: "owner", permissions: ["workspaces:write"] });
  setShellState({
    me: {
      role: "owner",
      permissions: ["workspaces:write"],
      user: { username: "robin" },
    } as unknown as Me,
  });
  held = [MAJORS, ALTS];
  apiFetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      held = held.filter((l) => !url.endsWith(l.id));
      return new Response(null, { status: 204 });
    }
    if (url === "/api/v1/watchlists") return json({ items: held });
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
  resetShellState();
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
    // the lists are read first: a loaded runner takes more than waitFor's default second
    await waitFor(
      () => expect(screen.getByRole("heading", { level: 1 })).not.toHaveTextContent("Watchlist"),
      { timeout: 5_000 },
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

describe("SCR-101 at ?modal=watchlists (R-110 opens it)", () => {
  /**
   * A whole route (the shell, the panel and the dialog) renders slowly on a loaded runner, and the router commits a
   * navigation as a transition: the dialog leaves, and the page under it wakes, a render or two after the location.
   */
  const WAIT = { timeout: 15_000 };

  it(
    "R-110 /watchlist opens the manager on the first list; Close goes to that list's page",
    { timeout: 60_000 },
    async () => {
      const router = renderAt("/watchlist");
      const dialog = await screen.findByRole("dialog", { name: "Watchlists" }, WAIT);
      await within(dialog).findByRole("option", { name: "Majors, 2 symbols" }, WAIT);
      fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
      await waitFor(
        () => expect(router.state.location.pathname).toBe(`/watchlist/${MAJORS.id}`),
        WAIT,
      );
      expect(
        await screen.findByRole("grid", { name: /^Watchlist Majors/ }, WAIT),
      ).toBeInTheDocument();
      expect(screen.queryByRole("dialog", { name: "Watchlists" })).toBeNull();
    },
  );

  it(
    "'Manage watchlists…' opens it at ?modal=watchlists; Close goes back, and focus returns to the tab",
    { timeout: 60_000 },
    async () => {
      const router = renderAt(`/watchlist/${MAJORS.id}`);
      await screen.findByRole("grid", { name: /^Watchlist Majors/ }, WAIT);
      const tab = screen.getByRole("tab", { name: /^Majors/ });
      act(() => tab.focus());
      fireEvent.keyDown(tab, { key: "F10", shiftKey: true });
      fireEvent.click(await screen.findByRole("menuitem", { name: "Manage watchlists…" }, WAIT));
      await waitFor(() => expect(router.state.location.search).toBe("?modal=watchlists"), WAIT);
      const dialog = await screen.findByRole("dialog", { name: "Watchlists" }, WAIT);
      await within(dialog).findByRole("option", { name: "Majors, 2 symbols" }, WAIT);
      fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
      await waitFor(() => expect(router.state.location.search).toBe(""), WAIT);
      expect(router.state.location.pathname).toBe(`/watchlist/${MAJORS.id}`);
      await waitFor(
        () => expect(screen.queryByRole("dialog", { name: "Watchlists" })).toBeNull(),
        WAIT,
      );
      await waitFor(
        () => expect(document.activeElement).toBe(screen.getByRole("tab", { name: /^Majors/ })),
        WAIT,
      );
    },
  );

  it(
    "a deep link opens it on that list; the list deleted there, Close hands the page to the list it shows",
    { timeout: 60_000 },
    async () => {
      const router = renderAt(`/watchlist/${ALTS.id}?modal=watchlists`);
      const dialog = await screen.findByRole("dialog", { name: "Watchlists" }, WAIT);
      const alts = await within(dialog).findByRole("option", { name: "Alts, 1 symbol" }, WAIT);
      expect(alts).toHaveAttribute("aria-selected", "true");
      // CMP-044's guard (no press counts in its first 400 ms) reads `performance`: faked from before the confirm opens,
      // so the test moves it on with no real sleep (C-5335-09)
      vi.useFakeTimers({ toFake: ["performance"] });
      try {
        fireEvent.keyDown(alts, { key: "Delete" });
        const confirm = await screen.findByRole("alertdialog", { name: "Delete Alts?" }, WAIT);
        act(() => vi.advanceTimersByTime(450));
        fireEvent.click(within(confirm).getByRole("button", { name: "Delete Alts" }));
      } finally {
        vi.useRealTimers();
      }
      await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull(), WAIT);
      await waitFor(
        () => expect(within(dialog).queryByRole("option", { name: /^Alts/ })).toBeNull(),
        WAIT,
      );
      fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
      await waitFor(
        () => expect(router.state.location.pathname).toBe(`/watchlist/${MAJORS.id}`),
        WAIT,
      );
      expect(
        await screen.findByRole("grid", { name: /^Watchlist Majors/ }, WAIT),
      ).toBeInTheDocument();
      // the page read the lists again as the manager closed: the deleted list is no tab
      await waitFor(() => expect(screen.queryByRole("tab", { name: /^Alts/ })).toBeNull(), WAIT);
    },
  );
});

describe("#5335's lens round (the route)", () => {
  const WAIT = { timeout: 15_000 };

  it(
    "C-5335-06: R-110 with a typed ?modal=watchlists and no list closes: the param goes, the no-list state shows, focus on its button",
    { timeout: 60_000 },
    async () => {
      held = [];
      const router = renderAt("/watchlist?modal=watchlists");
      const dialog = await screen.findByRole("dialog", { name: "Watchlists" }, WAIT);
      fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
      await waitFor(
        () => expect(screen.queryByRole("dialog", { name: "Watchlists" })).toBeNull(),
        WAIT,
      );
      expect(router.state.location.search).toBe("");
      // A-5335-08: no opener to go back to: the page's first control takes focus, never the body
      const create = screen.getByRole("button", { name: "Create watchlist" });
      await waitFor(() => expect(document.activeElement).toBe(create), WAIT);
    },
  );

  it(
    "A-5335-08: a deep link has no opener: Close puts focus on the shown list's tab, never on the body",
    { timeout: 60_000 },
    async () => {
      renderAt(`/watchlist/${MAJORS.id}?modal=watchlists`);
      const dialog = await screen.findByRole("dialog", { name: "Watchlists" }, WAIT);
      await within(dialog).findByRole("option", { name: "Majors, 2 symbols" }, WAIT);
      fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
      await waitFor(
        () => expect(document.activeElement).toBe(screen.getByRole("tab", { name: /^Majors/ })),
        WAIT,
      );
    },
  );

  it(
    "S-5335-04: without workspaces:write the manager reads only: one notice, '+ New watchlist' and Import… T2, Export live",
    { timeout: 60_000 },
    async () => {
      setMeClaims({ authenticated: true, role: "viewer", permissions: [] });
      setShellState({
        me: { role: "viewer", permissions: [], user: { username: "robin" } } as unknown as Me,
      });
      renderAt(`/watchlist/${MAJORS.id}?modal=watchlists`);
      const dialog = await screen.findByRole("dialog", { name: "Watchlists" }, WAIT);
      await within(dialog).findByRole("option", { name: "Majors, 2 symbols" }, WAIT);
      const notice = within(dialog).getByText("Read-only — your role can't save workspaces.");
      for (const name of [/New watchlist/, /Import…/]) {
        const control = within(dialog).getByRole("button", { name });
        expect(control).toHaveAttribute("aria-disabled", "true");
        expect(control.getAttribute("aria-describedby")).toContain(notice.id);
      }
      expect(within(dialog).getByRole("button", { name: "Export Majors" })).not.toHaveAttribute(
        "aria-disabled",
      );
    },
  );

  it(
    "S-5335-04: a signed-out visit to /watchlist/x goes to sign in, coming back there after",
    { timeout: 60_000 },
    async () => {
      resetMeClaims();
      setMeClaims({ authenticated: false, role: null, permissions: [] });
      const router = renderAt("/watchlist/x");
      await waitFor(() => expect(router.state.location.pathname).toBe("/login"), WAIT);
      expect(router.state.location.search).toBe("?next=%2Fwatchlist%2Fx");
    },
  );
});
