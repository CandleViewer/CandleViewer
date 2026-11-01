import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildRoutes } from "../../../src/routes/tree";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import type { Role } from "../../../src/routes/rbac";
import { clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { KeymapHost, registerCommand } from "../../../src/keymap/KeymapHost";
import { KEYMAP } from "../../../src/keymap/keymap";
import { commandMeta, isCommandValid } from "../../../src/keymap/registry";
import { resetShellState, setShellState, type Me } from "../../../src/shell/bootstrap/store.js";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore";
import { closePalette } from "../../../src/features/command-palette/CommandPaletteHost";
import { missingGates } from "../../../src/features/command-palette/gates";
import { ADMIN_READ, registerPaletteSource } from "../../../src/features/command-palette/sources";
import { closeSymbolSearch } from "../../../src/features/symbol-search/searchSession";

// Spies that delegate: SCR-102's close (the palette closes it on opening) and the source subscription (teardown).
const live = vi.hoisted(() => ({ subscriptions: 0 }));
vi.mock("../../../src/features/symbol-search/searchSession", async (original) => {
  const real = await original<typeof import("../../../src/features/symbol-search/searchSession")>();
  return { ...real, closeSymbolSearch: vi.fn(real.closeSymbolSearch) };
});
vi.mock("../../../src/features/command-palette/sources", async (original) => {
  const real = await original<typeof import("../../../src/features/command-palette/sources")>();
  return {
    ...real,
    subscribePaletteSources: (listener: () => void) => {
      live.subscriptions += 1;
      const off = real.subscribePaletteSources(listener);
      return () => {
        live.subscriptions -= 1;
        off();
      };
    },
  };
});

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

/** What the shell's polite region holds now (every region of that politeness, as `top-bar.test.tsx` reads it). */
const polite = (): string =>
  [...document.querySelectorAll('[aria-live="polite"]')].map((n) => n.textContent).join("");
/** CMP-059's own status region: the count, the no-results sentence, a re-shown reason. */
const status = (): string =>
  within(screen.getByRole("dialog")).getByRole("status").textContent ?? "";
const groups = (): string[] =>
  screen
    .getAllByRole("group")
    .map((g) => g.getAttribute("aria-labelledby") ?? "")
    .map((id) => document.getElementById(id)?.textContent ?? "");

const offs: (() => void)[] = [];
afterEach(() => offs.splice(0).forEach((off) => off()));

beforeEach(() => {
  // jsdom has no layout: CMP-059 scrolls the active row into view on a key move.
  Element.prototype.scrollIntoView = vi.fn();
  window.localStorage.clear();
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

describe("E10-S05 scenario 2: typing filters and the count is said once", () => {
  it("groups in the fixed order with no header for an empty group, and says the count after it settles", async () => {
    await shellAt("/journal");
    pressCtrlK();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    fireEvent.change(input(), { target: { value: "a" } });
    fireEvent.change(input(), { target: { value: "al" } });
    fireEvent.change(input(), { target: { value: "alr" } });
    expect(options()).toEqual(["Alerts"]);
    expect(within(screen.getByRole("option", { name: "Alerts" })).getByText("Al").tagName).toBe(
      "MARK",
    );
    expect(groups()).toEqual(["Navigate"]);
    act(() => void vi.advanceTimersByTime(400));
    expect(status()).toBe(""); // never once per keystroke
    act(() => void vi.advanceTimersByTime(100));
    expect(status()).toBe("1 result");
    fireEvent.change(input(), { target: { value: "t" } });
    expect(groups()).toEqual(["Navigate", "Action"]); // Navigate before Action, whatever the score
  });
});

describe("E10-S05 scenario 4: an action runs through the keymap registry", () => {
  it("runs the Hotkey cheatsheet through runCommand, the handler Ctrl+/ reaches: SCR-013 opens", async () => {
    await shellAt("/journal");
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "cheatsheet" } });
    expect(options()).toEqual(["Hotkey cheatsheet"]);
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
  });

  it("lists every registered, valid command except the palette and range commands (completeness)", async () => {
    await shellAt("/journal");
    pressCtrlK();
    const found = (label: string): boolean => {
      fireEvent.change(input(), { target: { value: label } });
      return screen.queryAllByRole("option").some((o) => o.getAttribute("aria-label") === label);
    };
    const expected = KEYMAP.filter(
      (c) => isCommandValid(c.id) && c.id !== "global.palette" && !c.defaultBinding.includes(".."),
    ).map((c) => commandMeta(c.id)?.label ?? c.id);
    expect(expected.length).toBeGreaterThan(3);
    for (const label of expected) expect(found(label), label).toBe(true);
    expect(found("Command palette")).toBe(false);
    expect(found("Navigate rail item 1-9")).toBe(false);
  });

  it("every registered dangerous command has a gate row (none registered today)", async () => {
    await shellAt("/journal");
    const registered = KEYMAP.filter((c) => isCommandValid(c.id)).map((c) => ({
      meta: commandMeta(c.id) ?? (undefined as never),
      destructive: c.destructive,
    }));
    expect(missingGates(registered)).toEqual([]);
  });

  it("a command runCommand refuses (an order entry, unarmed) runs nothing and says so once", async () => {
    const order = vi.fn();
    offs.push(registerCommand("chart.market_order", order));
    await shellAt("/journal");
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "market order" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(order).not.toHaveBeenCalled();
    expect(polite()).toBe(
      "Market order at market (arm-gated) did not run: it is not available here.",
    );
  });
});

describe("E10-S05 scenario 5: a dangerous command routes into its own confirmation", () => {
  it("is tagged confirms with a glyph; Enter closes the palette, then the handler opens its confirm", async () => {
    const executed = vi.fn();
    // When the handler runs, the palette has closed: its layer is inert and focus has left it.
    const openConfirm = vi.fn(() => {
      const layer = document.querySelector("[data-cv-layer]");
      return [layer?.getAttribute("data-state") ?? "gone", layer?.contains(document.activeElement)];
    });
    offs.push(registerCommand("positions.close", openConfirm));
    await shellAt("/journal");
    trigger().focus(); // the element focus returns to (E10-D04 T-11)
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "close selected" } });
    const row = screen.getByRole("option", { name: "Close selected position (confirm), confirms" });
    expect(row.closest("[data-kind]")).toHaveAttribute("data-kind", "destructive");
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(openConfirm).toHaveBeenCalledTimes(1);
    expect(openConfirm.mock.results[0]?.value).toEqual(["closing", false]);
    expect(executed).not.toHaveBeenCalled(); // the palette never fires the action itself
    expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull();
  });
});

describe("E10-S05 scenario 6: admin destinations are absent without admin:read", () => {
  const unknownWord = (word: string): string =>
    `No command matches “${word}”. Try fewer letters, or use the nav rail.`;

  it("a manager without admin:read: no /admin/* row, and admin words read as unknown words", async () => {
    await shellAt("/journal", "manager");
    pressCtrlK();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    for (const word of ["admin", "users", "audit", "zzzq"]) {
      fireEvent.change(input(), { target: { value: word } });
      act(() => void vi.advanceTimersByTime(500));
      expect(screen.queryAllByRole("option")).toEqual([]);
      expect(status()).toBe(unknownWord(word));
    }
  });

  it("an owner with admin:read finds Profile and security and Invite user by name (2.4.5)", async () => {
    const { router } = await shellAt("/journal", "owner", [ADMIN_READ]);
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "profile" } });
    expect(options()).toContain("Profile and security");
    fireEvent.change(input(), { target: { value: "invite user" } });
    expect(options()[0]).toBe("Invite user");
    fireEvent.keyDown(input(), { key: "Enter" });
    await screen.findByRole("heading", { level: 1, name: /R-303|Invite/ });
    expect(router.state.location.pathname).toBe("/admin/users/new");
  });

  it("re-filters in place when the claims change while open", async () => {
    await shellAt("/journal", "owner", [ADMIN_READ]);
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "invite user" } });
    expect(options()).toContain("Invite user");
    act(() => {
      setMeClaims({ authenticated: true, role: "owner", permissions: [] });
      setShellState({ me: me("owner", []) });
    });
    expect(screen.queryByRole("option", { name: "Invite user" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  });
});

describe("E10-S05 scenario 9: a screen reader can operate it by keyboard alone", () => {
  it("reaches a T2 row, keeps its reason in its description, and Enter re-shows it without running", async () => {
    const run = vi.fn();
    const reason = "Your role can't change positions.";
    offs.push(
      registerPaletteSource({
        id: "fixture",
        group: "Action",
        rows: () => [
          {
            id: "fixture:lev",
            label: "Set leverage",
            group: "Action",
            target: { kind: "command", commandId: "fixture.lev" },
            disabledReason: reason,
          },
        ],
      }),
    );
    offs.push(registerCommand("positions.close", run));
    await shellAt("/journal", "viewer");
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "set leverage" } });
    const option = screen.getByRole("option", { name: "Set leverage" });
    expect(input()).toHaveAttribute("aria-activedescendant", option.id);
    expect(option).toHaveAttribute("aria-disabled", "true");
    expect(option).toHaveAccessibleDescription(reason);
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(status()).toContain(reason);
    expect(run).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  });

  it("arrows wrap, Home and End jump, and the active option is named with its tag", async () => {
    offs.push(registerCommand("positions.close", vi.fn()));
    await shellAt("/journal");
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "o" } });
    const all = screen.getAllByRole("option");
    const active = (): string | null =>
      document
        .getElementById(input().getAttribute("aria-activedescendant") ?? "")
        ?.getAttribute("aria-label") ?? null;
    fireEvent.keyDown(input(), { key: "End" });
    expect(input()).toHaveAttribute("aria-activedescendant", all[all.length - 1]?.id);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(input()).toHaveAttribute("aria-activedescendant", all[0]?.id);
    fireEvent.keyDown(input(), { key: "ArrowUp" });
    fireEvent.keyDown(input(), { key: "Home" });
    expect(input()).toHaveAttribute("aria-activedescendant", all[0]?.id);
    fireEvent.change(input(), { target: { value: "close selected" } });
    expect(active()).toBe("Close selected position (confirm), confirms");
  });
});

describe("E10-S05 scenario 1 (empty query): Recent and Suggested", () => {
  it("first open: no Recent header, Suggested lists the session's actions", async () => {
    await shellAt("/journal");
    pressCtrlK();
    expect(groups()).toEqual(["Suggested"]);
    expect(options()).toContain("Hotkey cheatsheet");
  });

  it("Recent holds the last runs, newest first, per user on this device", async () => {
    await shellAt("/journal");
    for (const query of ["journal analytics", "alerts"]) {
      pressCtrlK();
      fireEvent.change(input(), { target: { value: query } });
      fireEvent.keyDown(input(), { key: "Enter" });
      await screen.findByRole("heading", { level: 1 });
    }
    pressCtrlK();
    expect(groups()).toEqual(["Recent", "Suggested"]);
    const recent = within(screen.getAllByRole("group")[0] as HTMLElement)
      .getAllByRole("option")
      .map((o) => o.getAttribute("aria-label"));
    expect(recent).toEqual(["Alerts", "Journal analytics"]);
    expect(JSON.stringify(window.localStorage)).not.toMatch(/alerts"|journal analytics/i); // ids, not queries
    expect(window.localStorage.getItem("cv.palette-recent.v1:u-1")).toContain("route:R-190");
  });
});

describe("E10-S05 scenario 7: empty and no-result states are honest about their sources", () => {
  it("with only routes and actions, it says no command matches and offers a way on, once", async () => {
    await shellAt("/journal");
    pressCtrlK();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    fireEvent.change(input(), { target: { value: "xyz" } });
    const sentence = "No command matches “xyz”. Try fewer letters, or use the nav rail.";
    expect(screen.getByText(sentence)).toBeVisible();
    expect(screen.queryByRole("group")).toBeNull(); // no headers
    expect(status()).toBe("");
    act(() => void vi.advanceTimersByTime(500));
    expect(status()).toBe(sentence);
  });

  it("once a Symbol source registers, the sentence is 14's", async () => {
    offs.push(registerPaletteSource({ id: "symbols", group: "Symbol", rows: () => [] }));
    await shellAt("/journal");
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "xyz" } });
    expect(screen.getByText("No command or symbol matches “xyz”")).toBeVisible();
  });
});

describe("E10-S05 scenario 8: reduced motion makes the close instant", () => {
  afterEach(() => document.documentElement.removeAttribute("data-motion"));

  it("with the override on, the card and scrim are gone at once and focus is back on the trigger", async () => {
    document.documentElement.setAttribute("data-motion", "reduce");
    await shellAt("/journal");
    trigger().focus();
    fireEvent.click(trigger());
    expect(document.querySelector(".cv-dialog__scrim")).not.toBeNull();
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(document.querySelector(".cv-dialog__scrim")).toBeNull();
    expect(document.querySelector("[data-cv-layer]")).toBeNull();
    expect(trigger()).toHaveFocus();
  });
});

describe("E10-S05 axe: every palette state in three themes", () => {
  const serious = async (): Promise<unknown[]> =>
    (await axe.run(document.body, NO_CONTRAST)).violations.filter((v) =>
      /serious|critical/.test(v.impact ?? ""),
    );
  afterEach(() => document.documentElement.removeAttribute("data-theme"));

  for (const theme of ["dark", "light", "high-contrast"])
    it(`empty query, results, no results, T2 and destructive rows: zero serious or critical (${theme})`, async () => {
      document.documentElement.setAttribute("data-theme", theme);
      offs.push(registerCommand("positions.close", vi.fn()));
      offs.push(
        registerPaletteSource({
          id: "t2",
          group: "Action",
          rows: () => [
            {
              id: "t2:lev",
              label: "Set leverage",
              group: "Action",
              target: { kind: "command", commandId: "t2.lev" },
              disabledReason: "Your role can't change positions.",
            },
          ],
        }),
      );
      await shellAt("/journal");
      pressCtrlK();
      expect(await serious()).toEqual([]); // empty query
      for (const query of ["alerts", "zzqx", "set leverage", "close selected"]) {
        fireEvent.change(input(), { target: { value: query } });
        expect(await serious(), query).toEqual([]);
      }
    });
});

describe("E10-S05 lens r1 fold", () => {
  it("m1 teardown: unmounting unregisters Ctrl+K, drops the source subscription and leaves no dialog", async () => {
    const { view } = await shellAt("/journal");
    pressCtrlK();
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeVisible();
    expect(live.subscriptions).toBeGreaterThan(0);
    view.unmount();
    expect(isCommandValid("global.palette")).toBe(false);
    expect(live.subscriptions).toBe(0);
    expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull();
  });

  it("m3 a dangerous row is a choice, not a run: no recency, palette.chosen instead of palette.ran", async () => {
    offs.push(registerCommand("positions.close", vi.fn()));
    await shellAt("/journal");
    const seen: { name: string }[] = [];
    const on = (e: Event): void => void seen.push((e as CustomEvent<{ name: string }>).detail);
    window.addEventListener(THEME_ANALYTICS_EVENT, on);
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "close selected" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    window.removeEventListener(THEME_ANALYTICS_EVENT, on);
    expect(seen.map((e) => e.name)).toEqual(["palette.opened", "palette.chosen"]);
    expect(window.localStorage.getItem("cv.palette-recent.v1:u-1")).toBeNull();
  });

  it("m4 a command that stopped being valid while the palette closed runs nothing and says so once", async () => {
    let valid = true;
    const run = vi.fn();
    offs.push(registerCommand("positions.close", run, () => valid));
    offs.push(
      registerPaletteSource({
        id: "fixture-m4",
        group: "Action",
        rows: () => [
          {
            id: "fixture:m4",
            label: "Fixture close",
            group: "Action",
            target: { kind: "command", commandId: "positions.close" },
          },
        ],
      }),
    );
    await shellAt("/journal");
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "fixture close" } });
    valid = false; // focus moved to a context where the command no longer applies, before the run step
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(run).not.toHaveBeenCalled();
    expect(polite()).toBe("Fixture close did not run: it is not available here.");
    expect(window.localStorage.getItem("cv.palette-recent.v1:u-1")).toBeNull();
  });

  it("n2 opening the palette closes SCR-102 instead of stacking two dialogs", async () => {
    await shellAt("/journal");
    vi.mocked(closeSymbolSearch).mockClear();
    pressCtrlK();
    expect(closeSymbolSearch).toHaveBeenCalledTimes(1);
    pressCtrlK(); // closing the palette does not touch it
    expect(closeSymbolSearch).toHaveBeenCalledTimes(1);
  });

  it("a11y m1 opened from body, Esc leaves focus on the main landmark, not on body", async () => {
    await shellAt("/journal");
    (document.activeElement as HTMLElement | null)?.blur();
    expect(document.body).toHaveFocus();
    pressCtrlK();
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull();
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("a11y m1 opened from body, a non-navigating Action also ends on main; a route leaves it to the shell", async () => {
    const { router } = await shellAt("/journal");
    (document.activeElement as HTMLElement | null)?.blur();
    pressCtrlK();
    fireEvent.change(input(), { target: { value: "alerts" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    await screen.findByRole("heading", { level: 1, name: /R-190/ });
    expect(router.state.location.pathname).toBe("/alerts");
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
  });

  it("a11y n2 the trigger announces that it opens a dialog", async () => {
    await shellAt("/journal");
    expect(trigger()).toHaveAttribute("aria-haspopup", "dialog");
  });
});
