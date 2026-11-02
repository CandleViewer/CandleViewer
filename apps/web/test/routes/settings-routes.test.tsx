import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PreferencesProvider } from "../../src/features/a11y-preferences/PreferencesContext";
import { KeymapHost } from "../../src/keymap/KeymapHost";
import { resetMeClaims, setMeClaims } from "../../src/lib/auth/meCache";
import { buildRoutes } from "../../src/routes/tree";

/** E47-S08: the SCR-110 layout through the real route tree, as the shell mounts it. */
beforeEach(() => {
  resetMeClaims();
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
});
afterEach(cleanup);

async function open(entry: string) {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [entry] });
  render(
    <PreferencesProvider>
      <KeymapHost />
      <RouterProvider router={router} />
    </PreferencesProvider>,
  );
  await screen.findByRole("navigation", { name: "Settings" }, { timeout: 4000 });
  return router;
}

describe("settings routes", () => {
  it.each(["/settings/profile", "/settings/hotkeys", "/settings/appearance"])(
    "%s sits in the layout: one main, one Settings nav, the section's own page",
    async (path) => {
      await open(path);
      expect(screen.getAllByRole("main")).toHaveLength(1);
      expect(screen.getAllByRole("navigation", { name: "Settings" })).toHaveLength(1);
      expect(screen.getByRole("searchbox", { name: "Search settings" })).toBeVisible();
      expect(screen.getAllByRole("heading", { level: 1 }).length).toBeGreaterThan(0);
    },
  );

  it.each(["/settings/notifications", "/settings/windows"])(
    "%s (a routed stub) is inside the layout too",
    async (path) => {
      await open(path);
      expect(screen.getAllByRole("navigation", { name: "Settings" })).toHaveLength(1);
    },
  );

  it("R-200 /settings redirects to the profile section", async () => {
    const router = await open("/settings");
    await waitFor(() => expect(router.state.location.pathname).toBe("/settings/profile"));
    const nav = screen.getByRole("navigation", { name: "Settings" });
    expect(within(nav).getByRole("link", { name: "Profile" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("aria-current follows the #security hash on the profile route", async () => {
    await open("/settings/profile#security");
    const nav = screen.getByRole("navigation", { name: "Settings" });
    expect(within(nav).getByRole("link", { name: "Security" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Profile" })).not.toHaveAttribute("aria-current");
    // The anchor the hash names exists on the page.
    expect(document.getElementById("security")).not.toBeNull();
  });

  it("Notifications is a link (routed), Trading defaults is disabled with a reason", async () => {
    await open("/settings/appearance");
    const nav = screen.getByRole("navigation", { name: "Settings" });
    expect(within(nav).getByRole("link", { name: "Notifications" })).toHaveAttribute(
      "href",
      "/settings/notifications",
    );
    expect(within(nav).getByRole("button", { name: "Trading defaults" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("Tab order: search, then the nav's single stop, then the page; the Appearance rows state scope", async () => {
    await open("/settings/appearance");
    const search = screen.getByRole("searchbox", { name: "Search settings" });
    const nav = screen.getByRole("navigation", { name: "Settings" });
    const stop = within(nav)
      .getAllByRole("link")
      .filter((l) => l.tabIndex === 0);
    expect(stop).toHaveLength(1);
    expect(stop[0]).toHaveTextContent("Appearance");
    const radio = screen.getByRole("radio", { name: /colour-blind safe/i });
    const order = [search, stop[0]!, radio];
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1]!.compareDocumentPosition(order[i]!)).toBe(
        Node.DOCUMENT_POSITION_FOLLOWING,
      );
    }
    // SettingRow on a real screen: the palette group's description carries the scope.
    const palette = screen.getByRole("group", { name: "Chart palette" });
    expect(palette).toHaveAccessibleDescription(/Scope: Per device/);
  });
});
