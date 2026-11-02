import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PreferencesProvider } from "../../src/features/a11y-preferences/PreferencesContext";
import { KeymapHost } from "../../src/keymap/KeymapHost";
import {
  CLAIMS_MAX_AGE_MS,
  resetMeClaims,
  setMeClaims,
  setMeClaimsReader,
} from "../../src/lib/auth/meCache";
import type { MeClaims, Role } from "../../src/routes/rbac";
import { buildRoutes } from "../../src/routes/tree";

// #5405: the client-navigation variant of `@plan-AB-2` (e2e/shell/abuse.spec.ts reloads). The `/me`
// reader is a stub the test answers; no network. Only `Date` is faked, to step past the bound.
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
  await screen.findByRole("heading", { level: 1, name: heading });
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
  it("re-reads /me on the next rail click, drops Admin from the rail and denies Back to the admin route", async () => {
    const router = await renderAt("/admin/users", /^R-301/u);
    expect(read).not.toHaveBeenCalled(); // the bootstrap's claims are fresh: no second /me at boot
    expect(names()).toContain("Admin");

    role = "viewer"; // the server downgrades the user
    vi.setSystemTime(Date.now() + CLAIMS_MAX_AGE_MS);
    fireEvent.click(within(rail()).getByRole("link", { name: /Terminal/u }));
    await screen.findByRole("heading", { level: 1, name: /^R-101/u });
    expect(read).toHaveBeenCalledTimes(1);
    expect(names()).not.toContain("Admin");

    await act(async () => {
      await router.navigate(-1); // Back, client-side
    });
    expect(router.state.location.pathname).toBe("/admin/users");
    await screen.findByRole("heading", { level: 1, name: "Page not found" });
    expect(screen.queryByRole("heading", { name: /^R-301/u })).toBeNull();
    expect(read).toHaveBeenCalledTimes(1); // within the bound, the claims just read are used
  });

  it("an owner-only route the server withdrew answers 403 at the next client navigation", async () => {
    const router = await renderAt("/journal", /^R-180/u);
    role = "viewer";
    vi.setSystemTime(Date.now() + CLAIMS_MAX_AGE_MS);
    await act(async () => {
      await router.navigate("/risk");
    });
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { level: 1, name: "You don't have access to this" }),
      ).toBeInTheDocument(),
    );
    expect(names()).not.toContain("Rules");
  });
});
