import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildRoutes } from "../../../src/routes/tree";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import type { Role } from "../../../src/routes/rbac";
import { clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { KeymapHost } from "../../../src/keymap/KeymapHost";
import { resetShellState, setShellState, type Me } from "../../../src/shell/bootstrap/store.js";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore";
import { closePalette } from "../../../src/features/command-palette/CommandPaletteHost";

// E10-S05 (#5236): SCR-012 mounted in the real shell route tree beside the real keymap host, by role and label.

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };
const NO_CONTRAST = { rules: { "color-contrast": { enabled: false } } }; // jsdom has no layout

const me = (role: Role, permissions: readonly string[]): Me => ({
  accounts: [],
  permissions: [...permissions],
  role,
  user: { id: "u-1", email: "r@example.test", username: "robin", roles: [role], status: "active" },
});

async function shellAt(path: string, role: Role = "owner", permissions: string[] = []) {
  setMeClaims({ authenticated: true, role, permissions });
  setShellState({ environment: "demo", me: me(role, permissions) });
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  const view = render(
    <>
      <KeymapHost />
      <RouterProvider router={router} />
    </>,
  );
  await screen.findByRole("heading", { level: 1 });
  return { router, view };
}

const pressCtrlK = (): void => {
  fireEvent.keyDown(document.activeElement ?? document.body, {
    key: "k",
    code: "KeyK",
    ctrlKey: true,
  });
};
const input = (): HTMLElement => screen.getByRole("combobox", { name: "Search commands" });
const options = (): string[] =>
  screen.getAllByRole("option").map((o) => o.getAttribute("aria-label") ?? "");
const trigger = (): HTMLElement => screen.getByRole("button", { name: "Search commands Ctrl+K" });

beforeEach(() => {
  resetMeClaims();
  resetShellState();
  clearAnnouncements();
});
afterEach(() => {
  act(() => closePalette());
  vi.useRealTimers();
});

describe("E10-S05 scenario 1: Ctrl+K and the top-bar trigger open the palette", () => {
  it("Ctrl+K opens SCR-012 as a modal dialog with focus in the input, and Ctrl+K closes it", async () => {
    await shellAt("/journal");
    pressCtrlK();
    const dialog = screen.getByRole("dialog", { name: "Command palette" });
    expect(dialog).toBeVisible();
    expect(input()).toHaveFocus();
    expect(within(dialog).getByRole("listbox", { name: "Commands" })).toBeInTheDocument();
    pressCtrlK(); // from inside the input too (`dispatcher.ts`: a chord still runs in a text field)
    expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull();
  });

  it("the trigger is enabled, names Control+K, opens the palette and reports how", async () => {
    await shellAt("/journal");
    const seen: unknown[] = [];
    const on = (e: Event): void => void seen.push((e as CustomEvent).detail);
    window.addEventListener(THEME_ANALYTICS_EVENT, on);
    expect(trigger()).toHaveAttribute("aria-keyshortcuts", "Control+K");
    expect(trigger()).not.toHaveAttribute("aria-disabled");
    trigger().focus();
    fireEvent.click(trigger());
    expect(input()).toHaveFocus();
    pressCtrlK(); // closes: one toggle for the key and the button
    expect(trigger()).toHaveFocus();
    pressCtrlK();
    window.removeEventListener(THEME_ANALYTICS_EVENT, on);
    expect(seen).toEqual([
      { name: "palette.opened", via: "trigger" },
      { name: "palette.opened", via: "hotkey" },
    ]);
  });

  it("is axe-clean open, with zero serious or critical", async () => {
    await shellAt("/journal");
    pressCtrlK();
    const res = await axe.run(document.body, NO_CONTRAST);
    expect(res.violations.filter((v) => /serious|critical/.test(v.impact ?? ""))).toEqual([]);
  });
});

describe("E10-S05 scenario 3: running a Navigate row navigates", () => {
  it("arrow to Alerts, Enter: the palette closes first, then the router lands on /alerts", async () => {
    const { router } = await shellAt("/journal");
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "alerts" } });
    expect(options()[0]).toBe("Alerts");
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull();
    await screen.findByRole("heading", { level: 1, name: /R-190/ });
    expect(router.state.location.pathname).toBe("/alerts");
  });
});

describe("E10-S05 scenario 8: Esc closes and focus returns", () => {
  it("returns focus to the trigger it opened from", async () => {
    await shellAt("/journal");
    trigger().focus();
    fireEvent.click(trigger());
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull();
    expect(trigger()).toHaveFocus();
  });
});
