import { createRequire } from "node:module";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, MemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createDispatcher } from "../../../src/keymap/dispatcher";
import { NavRail } from "../../../src/features/app-shell/NavRail";
import { KeymapHost } from "../../../src/keymap/KeymapHost";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import type { Role } from "../../../src/routes/rbac";
import { buildRoutes } from "../../../src/routes/tree";
import { PreferencesProvider } from "../../../src/features/a11y-preferences/PreferencesContext";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

function signIn(role: Role): void {
  setMeClaims({ authenticated: true, role, permissions: [] });
}

async function renderAt(path: string, heading: RegExp) {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  render(
    <PreferencesProvider>
      <KeymapHost />
      <RouterProvider router={router} />
    </PreferencesProvider>,
  );
  await screen.findByRole("heading", { name: heading });
  return router;
}

const rail = (): HTMLElement => screen.getByRole("navigation", { name: "Primary" });
const names = (): string[] =>
  within(rail())
    .getAllByRole("link")
    .map((a) => a.textContent ?? "");
const altKey = (key: string) =>
  act(async () => void fireEvent.keyDown(window, { key, altKey: true }));

const OWNER = ["Terminal", "Watchlist", "Positions/Orders", "Risk Dashboard", "Rules"];
const REST = ["Replay", "Journal", "Alerts", "Settings"];

beforeEach(() => resetMeClaims());

describe("E10-S01 S5: nav rail items per role", () => {
  it.each([
    ["owner", [...OWNER, ...REST, "Admin"], ""],
    ["manager", [...OWNER.slice(0, 3), "Rules", ...REST], 'a[href^="/admin"], a[href="/risk"]'],
    [
      "viewer",
      [...OWNER.slice(0, 3), ...REST],
      'a[href^="/admin"], a[href="/risk"], a[href="/rules"]',
    ],
  ] as const)(
    "renders a %s only the allowed items, with no axe violations",
    async (role, want, denied) => {
      signIn(role);
      await renderAt("/journal", /R-180/);
      // the a11y tree (by role), then the DOM: a denied item is absent, not hidden
      expect(names()).toEqual(want);
      if (denied) expect(rail().querySelector(denied)).toBeNull();
      const res = await axe.run(rail(), { rules: { "color-contrast": { enabled: false } } }); // jsdom has no layout
      expect(
        res.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
      ).toEqual([]);
    },
  );
});

describe("E10-S01 S5: current page", () => {
  it.each([
    ["/terminal/last", /R-101/, "Terminal"],
    ["/settings/appearance", /Appearance/, "Settings"],
    ["/admin/audit", /R-360/, "Admin"],
  ])(
    "marks only the item owning %s with aria-current=page and a non-colour cue",
    async (path, h, item) => {
      signIn("owner");
      await renderAt(path, h);
      const current = within(rail())
        .getAllByRole("link")
        .filter((a) => a.getAttribute("aria-current") === "page");
      expect(current.map((a) => a.textContent)).toEqual([item]);
      expect(current[0]?.style.boxShadow).toContain("inset 3px 0 0");
      expect(current[0]?.style.fontWeight).toBe("var(--font-weight-medium)");
    },
  );
});

describe("E10-S01 S5: keyboard", () => {
  it("Alt+N opens the Nth item, and Admin has no shortcut", async () => {
    signIn("owner");
    const router = await renderAt("/journal", /R-180/);
    expect(within(rail()).getByRole("link", { name: "Alerts" })).toHaveAttribute(
      "aria-keyshortcuts",
      "Alt+8",
    );
    expect(within(rail()).getByRole("link", { name: "Admin" })).not.toHaveAttribute(
      "aria-keyshortcuts",
    );
    await altKey("6");
    await waitFor(() => expect(router.state.location.pathname).toBe("/replay"));
  });

  it("Alt+N counts a viewer's visible items, and a digit past them does nothing", async () => {
    signIn("viewer");
    const router = await renderAt("/journal", /R-180/);
    await altKey("4");
    await waitFor(() => expect(router.state.location.pathname).toBe("/replay"));
    await altKey("9");
    expect(router.state.location.pathname).toBe("/replay");
  });

  it("moves focus with the arrows, Home and End, wrapping at the ends", async () => {
    signIn("viewer");
    await renderAt("/journal", /R-180/);
    const links = within(rail()).getAllByRole("link");
    act(() => links[0]?.focus());
    const last = links.length - 1;
    for (const [key, at] of [
      ["ArrowDown", 1],
      ["End", last],
      ["ArrowDown", 0],
      ["ArrowUp", last],
      ["Home", 0],
    ] as const) {
      fireEvent.keyDown(document.activeElement as Element, { key });
      expect(document.activeElement, key).toBe(links[at]);
    }
    expect(links.every((a) => a.tabIndex === 0)).toBe(true);
  });
});

describe("E10-S01 S5: badges", () => {
  it("puts the count words in the item's accessible name", () => {
    signIn("owner");
    render(
      <MemoryRouter initialEntries={["/journal"]}>
        <NavRail badges={{ alerts: "2 new", rules: "3 armed" }} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Alerts, 2 new" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Rules, 3 armed" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Journal" })).toBeInTheDocument();
  });
});

describe("E10-S01 S5: range bindings in the dispatcher", () => {
  const key = (k: string, alt = false) => ({
    ...{ ctrlKey: false, metaKey: false, shiftKey: false },
    key: k,
    altKey: alt,
  });

  it("passes the digit of a valid range command to execute", () => {
    const execute = vi.fn();
    const d = createDispatcher({ isValid: () => true, execute, notify: vi.fn(), now: () => 0 });
    expect(d(key("3", true), new Set(["Global"]))).toEqual({
      status: "executed",
      commandId: "global.nav_rail",
    });
    expect(execute.mock.calls[0]?.[1]).toBe(3);
  });

  it("leaves a range command with no valid handler unbound, so typed digits never toast", () => {
    const notify = vi.fn();
    const d = createDispatcher({ isValid: () => false, execute: vi.fn(), notify, now: () => 0 });
    expect(d(key("3"), new Set(["Global", "Chart"])).status).toBe("unbound");
    expect(d(key("3", true), new Set(["Global"])).status).toBe("unbound");
    expect(notify).not.toHaveBeenCalled();
  });
});
