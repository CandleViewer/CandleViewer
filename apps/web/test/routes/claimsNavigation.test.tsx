import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PreferencesProvider } from "../../src/features/a11y-preferences/PreferencesContext";
import { KeymapHost } from "../../src/keymap/KeymapHost";
import {
  CLAIMS_MAX_AGE_MS,
  getMeClaims,
  resetMeClaims,
  setMeClaims,
  setMeClaimsReader,
} from "../../src/lib/auth/meCache";
import type { MeClaims, Role } from "../../src/routes/rbac";
import { buildRoutes } from "../../src/routes/tree";
import { REFRESH_PATH, REFRESH_SENT_KEY, accessToken } from "../../src/lib/auth/accessToken";
import { runBootstrap } from "../../src/shell/bootstrap/bootstrap";
import { VIEW_AS_PATH } from "../../src/lib/auth/viewAsContext";

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const ME_BODY = {
  user: { id: "u1", username: "owner", email: "o@example.com", roles: ["owner"], status: "active" },
  role: "owner",
  permissions: [],
  accounts: [],
  session: { session_id: "s1", environment: "demo", elevated_until: null },
};

// #5405: the client-navigation variant of `@plan-AB-2` (e2e/shell/abuse.spec.ts reloads). The `/me`
// reader is a stub the test answers; no network. Only `Date` is faked, to step past the bound.
const SLOW_MS = 10_000;
const claims = (role: Role): MeClaims => ({ authenticated: true, role, permissions: [] });
const rail = (): HTMLElement => screen.getByRole("navigation", { name: "Primary" });
const names = (): string[] =>
  within(rail())
    .getAllByRole("link")
    .map((a) => a.textContent ?? "");

async function renderAt(path: string, heading: RegExp) {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  render(
    <PreferencesProvider>
      <KeymapHost />
      <RouterProvider router={router} />
    </PreferencesProvider>,
  );
  // a route's first lazy import is slow on a loaded runner: bound it, as the suite's slow imports are
  await screen.findByRole("heading", { level: 1, name: heading }, { timeout: SLOW_MS });
  return router;
}

let role: Role = "owner";
const read = vi.fn(() => Promise.resolve(claims(role)));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-02T00:00:00Z"));
  resetMeClaims();
  read.mockClear();
  role = "owner";
  setMeClaims(claims(role)); // the bootstrap's answer, as main.tsx sets it before the router mounts
  setMeClaimsReader(read);
});

afterEach(() => {
  resetMeClaims();
  vi.useRealTimers();
});

describe("#5405 @plan-AB-2 client navigation: a server-side downgrade applies without a reload", () => {
  it(
    "re-reads /me on the next rail click, drops Admin from the rail and denies Back to the admin route",
    { timeout: 30_000 },
    async () => {
      const router = await renderAt("/admin/users", /^R-301/u);
      expect(read).not.toHaveBeenCalled(); // the bootstrap's claims are fresh: no second /me at boot
      expect(names()).toContain("Admin");

      role = "viewer"; // the server downgrades the user
      vi.setSystemTime(Date.now() + CLAIMS_MAX_AGE_MS);
      fireEvent.click(within(rail()).getByRole("link", { name: /Terminal/u }));
      await screen.findByRole("heading", { level: 1, name: /^R-101/u }, { timeout: SLOW_MS });
      expect(read).toHaveBeenCalledTimes(1);
      expect(names()).not.toContain("Admin");

      await act(async () => {
        await router.navigate(-1); // Back, client-side
      });
      expect(router.state.location.pathname).toBe("/admin/users");
      await screen.findByRole(
        "heading",
        { level: 1, name: "Page not found" },
        { timeout: SLOW_MS },
      );
      expect(screen.queryByRole("heading", { name: /^R-301/u })).toBeNull();
      expect(read).toHaveBeenCalledTimes(1); // within the bound, the claims just read are used
    },
  );

  it(
    "an owner-only route the server withdrew answers 403 at the next client navigation",
    { timeout: 30_000 },
    async () => {
      const router = await renderAt("/journal", /^R-180/u);
      role = "viewer";
      vi.setSystemTime(Date.now() + CLAIMS_MAX_AGE_MS);
      await act(async () => {
        await router.navigate("/risk");
      });
      await waitFor(
        () =>
          expect(
            screen.getByRole("heading", { level: 1, name: "You don't have access to this" }),
          ).toBeInTheDocument(),
        { timeout: SLOW_MS },
      );
      expect(names()).not.toContain("Rules");
    },
  );
});

// #5405 / E09-TC-D03: a stale bearer, then a rail click. The bootstrap's own reader goes through the
// real token holder, which refreshes. A refresh that finds the session lost signs it out: the loader
// runs before the navigation commits, so the holder's route would carry the page being left, and the
// guard routes instead. A refresh that fails or finds the session idle-locked is no sign-out: the
// claims stay and the navigation goes on (a locked one raises the SCR-005 overlay's cue).
describe("#5405 a stale bearer, then a rail click", () => {
  const assign = vi.fn();
  afterEach(() => {
    accessToken.clear();
    localStorage.removeItem(REFRESH_SENT_KEY); // the mark of a refresh no test answered
    assign.mockClear();
    vi.unstubAllGlobals();
  });

  async function clickSettings(refresh: () => Promise<Response>) {
    const { origin } = window.location;
    vi.stubGlobal("location", {
      origin,
      href: `${origin}/terminal/last`,
      pathname: "/terminal/last",
      search: "",
      assign,
    });
    // the refresh is the global `fetch`; the pages' own calls never answer, so the loader's re-read is
    // the only call that meets the stale bearer
    vi.stubGlobal("fetch", (url: unknown) =>
      String(url) === REFRESH_PATH ? refresh() : new Promise<Response>(() => undefined),
    );
    let stale = false;
    const fetchImpl = vi.fn(async (path: RequestInfo | URL) => {
      if (String(path) === VIEW_AS_PATH) return new Response(null, { status: 204 }); // E42-S03
      if (String(path) !== "/api/v1/me") return json({});
      return stale ? json({ code: "token_expired" }, 401) : json(ME_BODY);
    });
    resetMeClaims();
    await runBootstrap({ fetchImpl });
    accessToken.set({ access_token: "probe-held-x", token_type: "Bearer", expires_in: 600 });
    const router = await renderAt("/terminal/last", /^R-101/u);

    stale = true; // the token went stale (a slept laptop, a throttled background timer)
    vi.setSystemTime(Date.now() + CLAIMS_MAX_AGE_MS);
    fireEvent.click(within(rail()).getByRole("link", { name: /Settings/u }));
    return { router, fetchImpl };
  }

  it(
    "a refresh that finds the session lost lands on /login?next=%2Fsettings%2Fprofile, not the page left",
    { timeout: 30_000 },
    async () => {
      const { router } = await clickSettings(() =>
        Promise.resolve(json({ code: "refresh_token_invalid" }, 401)),
      );
      await waitFor(() => expect(router.state.location.pathname).toBe("/login"), {
        timeout: SLOW_MS,
      });
      expect(router.state.location.search).toBe("?next=%2Fsettings%2Fprofile");
      expect(getMeClaims().authenticated).toBe(false);
      expect(assign).not.toHaveBeenCalled();
    },
  );

  it.each<[string, () => Promise<Response>, boolean]>([
    ["fails on the network", () => Promise.reject(new TypeError("Failed to fetch")), false],
    ["answers a 5xx", () => Promise.resolve(json({ code: "unavailable" }, 503)), false],
    [
      "finds the session idle-locked",
      () => Promise.resolve(json({ code: "session_idle_locked" }, 401)),
      true,
    ],
  ])(
    "a refresh that %s keeps the claims and goes on to /settings/profile",
    { timeout: 30_000 },
    async (_name, refresh, locked) => {
      const onLocked = vi.fn();
      const unsubscribe = accessToken.onLocked(onLocked);
      try {
        const { router, fetchImpl } = await clickSettings(refresh);
        await waitFor(() => expect(router.state.location.pathname).toBe("/settings/profile"), {
          timeout: SLOW_MS,
        });
        expect(fetchImpl.mock.calls.filter(([p]) => String(p) === "/api/v1/me")).toHaveLength(2);
        expect(getMeClaims()).toMatchObject({ authenticated: true, role: "owner" });
        expect(assign).not.toHaveBeenCalled();
        expect(onLocked.mock.calls.length > 0).toBe(locked); // the SCR-005 overlay's cue
      } finally {
        unsubscribe();
      }
    },
  );
});
