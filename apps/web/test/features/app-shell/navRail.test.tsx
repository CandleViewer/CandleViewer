import { createRequire } from "node:module";
import type { ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, MemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createDispatcher } from "../../../src/keymap/dispatcher";
import { validateBinding } from "../../../src/keymap/validate";
import { KEYMAP } from "../../../src/keymap/keymap";
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

async function renderAt(path: string, heading: RegExp, extra?: ReactNode) {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  render(
    <PreferencesProvider>
      {extra}
      <KeymapHost />
      <RouterProvider router={router} />
    </PreferencesProvider>,
  );
  await screen.findByRole("heading", { name: heading });
  await act(async () => {}); // flush the effects that register the rail's command
  return router;
}

const rail = (): HTMLElement => screen.getByRole("navigation", { name: "Primary" });
const names = (): string[] =>
  within(rail())
    .getAllByRole("link")
    .map((a) => a.textContent ?? "");
const altKey = (key: string) =>
  act(async () => void fireEvent.keyDown(window, { key, altKey: true }));

// Claims are set before render, as main.tsx runs the bootstrap before the router mounts.
beforeEach(() => resetMeClaims());

describe("E10-S01 S5: nav rail items per role", () => {
  it.each([
    ["owner", ["Terminal", "Rules", "Journal", "Replay", "Alerts", "Settings", "Admin"], ""],
    [
      "manager",
      ["Terminal", "Rules", "Journal", "Replay", "Alerts", "Settings"],
      'a[href^="/admin"]',
    ],
    [
      "viewer",
      ["Terminal", "Journal", "Replay", "Alerts", "Settings"],
      'a[href^="/admin"], a[href="/rules"]',
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
      const links = within(rail()).getAllByRole("link");
      const current = links.filter((a) => a.getAttribute("aria-current") === "page");
      expect(current.map((a) => a.textContent)).toEqual([item]);
      // a border, which forced colours keep; the others have none (a transparent one would show)
      expect(current[0]?.style.borderLeft).toBe("3px solid var(--color-border-selected)");
      expect(current[0]?.style.fontWeight).toBe("var(--font-weight-medium)");
      expect(links.filter((a) => a.style.borderLeft.includes("solid"))).toEqual(current);
    },
  );
});

describe("E10-S01 S5: keyboard", () => {
  it.each([
    ["owner", ["1", "2", "3", "4", "5", "6", "7"]],
    ["viewer", ["1", "3", "4", "5", "6"]],
  ] as const)("gives a %s's items their fixed Alt digit, leaving gaps", async (role, digits) => {
    signIn(role);
    await renderAt("/journal", /R-180/);
    const keys = within(rail())
      .getAllByRole("link")
      .map((a) => a.getAttribute("aria-keyshortcuts"));
    expect(keys).toEqual(digits.map((d) => `Alt+${d}`));
  });

  it("Alt+N opens item N, and a viewer's Alt+2 (Rules) and Alt+7 (Admin) do nothing", async () => {
    signIn("viewer");
    const router = await renderAt("/journal", /R-180/);
    await altKey("5");
    await waitFor(() => expect(router.state.location.pathname).toBe("/alerts"));
    await altKey("2");
    await altKey("7");
    expect(router.state.location.pathname).toBe("/alerts");
  });

  it("does nothing behind the idle lock", async () => {
    signIn("owner");
    const router = await renderAt("/journal", /R-180/, <div data-keymap-context="Locked" />);
    await altKey("4");
    expect(router.state.location.pathname).toBe("/journal");
  });

  it("never toasts a bare digit typed in a Chart context: no Chart range handler is registered", async () => {
    signIn("owner");
    await renderAt("/journal", /R-180/, <input aria-label="probe" data-keymap-context="Chart" />);
    const probe = screen.getByRole("textbox", { name: "probe" });
    act(() => probe.focus());
    await act(async () => void fireEvent.keyDown(probe, { key: "3" }));
    expect(screen.queryByRole("region", { name: "Notifications" })).toBeNull();
  });

  it("moves focus with the arrows, Home and End, wrapping, but not with a modifier", async () => {
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
    for (const mod of ["altKey", "ctrlKey", "metaKey", "shiftKey"]) {
      fireEvent.keyDown(links[0] as Element, { key: "ArrowDown", [mod]: true });
      expect(document.activeElement, mod).toBe(links[0]);
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

describe("E10-S01 S5: range bindings in the dispatcher and the validator", () => {
  const key = (k: string, alt = false) => ({
    ...{ ctrlKey: false, metaKey: false, shiftKey: false },
    key: k,
    altKey: alt,
  });
  const cur = () => new Map(KEYMAP.map((c) => [c.id, c.defaultBinding]));

  it("passes the digit of a valid range command to execute", () => {
    const execute = vi.fn();
    const d = createDispatcher({ isValid: () => true, execute, notify: vi.fn(), now: () => 0 });
    expect(d(key("3", true), new Set(["Global"]))).toEqual({
      status: "executed",
      commandId: "global.nav_rail",
    });
    expect(execute.mock.calls[0]?.[1]).toBe(3);
  });

  it("lets an exact binding beat a range binding", () => {
    const execute = vi.fn();
    const bindings = new Map([["global.cheatsheet", "Alt+3"]]);
    const d = createDispatcher({
      isValid: () => true,
      execute,
      notify: vi.fn(),
      now: () => 0,
      bindings,
    });
    expect(d(key("3", true), new Set(["Global"]))).toMatchObject({
      commandId: "global.cheatsheet",
    });
  });

  it("leaves a range command with no valid handler unbound, so typed digits never toast", () => {
    const notify = vi.fn();
    const d = createDispatcher({ isValid: () => false, execute: vi.fn(), notify, now: () => 0 });
    expect(d(key("3"), new Set(["Global", "Chart"])).status).toBe("unbound");
    expect(d(key("3", true), new Set(["Global"])).status).toBe("unbound");
    expect(notify).not.toHaveBeenCalled();
  });

  it("checks each atom of a range against reserved keys and same-context bindings, both ways", () => {
    expect(validateBinding("global.nav_rail", "Ctrl+1..9", cur())).toMatchObject({
      kind: "reserved",
      reason: expect.stringMatching(/^Ctrl\+1 /),
    });
    expect(validateBinding("global.cheatsheet", "Alt+4", cur())).toMatchObject({
      kind: "conflict",
      with: "global.nav_rail",
    });
    const exact = new Map([...cur(), ["global.cheatsheet", "Alt+4"]]);
    expect(validateBinding("global.nav_rail", "Alt+1..9", exact)).toMatchObject({
      kind: "conflict",
      with: "global.cheatsheet",
    });
    expect(validateBinding("global.nav_rail", "Alt+1..9", cur())).toBeNull();
  });
});

describe("E10-Q03 fix 1: the collapsed rail's CMP-016 echo tooltip (SC 1.4.13)", () => {
  const renderRail = (collapsed: boolean) => {
    signIn("owner");
    return render(
      <MemoryRouter initialEntries={["/journal"]}>
        <NavRail collapsed={collapsed} badges={{ alerts: "2 new" }} />
      </MemoryRouter>,
    );
  };
  const tip = (): HTMLElement | null => document.querySelector<HTMLElement>('[role="tooltip"]');

  it("shows on keyboard focus with the name, badge and key, aria-hidden so nothing reads twice", () => {
    renderRail(true);
    const link = screen.getByRole("link", { name: "Alerts, 2 new" });
    expect(link).not.toHaveAttribute("title");
    expect(link).not.toHaveAttribute("aria-describedby");
    expect(document.querySelector('[role="tooltip"]:not([hidden])')).toBeNull(); // hidden until focus
    act(() => link.focus());
    fireEvent.focus(link); // jsdom: a script focus is not focus-visible, so no echo without this
    const shown = document.querySelector<HTMLElement>('[role="tooltip"]:not([hidden])');
    expect(shown).not.toBeNull();
    expect(shown).toHaveAttribute("aria-hidden", "true");
    expect(shown).toHaveTextContent("Alerts · 2 new · Alt+5");
    expect(screen.queryByRole("tooltip")).toBeNull(); // aria-hidden: absent from the a11y tree
  });

  it("Esc hides it and keeps focus on the link", () => {
    renderRail(true);
    const link = screen.getByRole("link", { name: "Journal" });
    act(() => link.focus());
    fireEvent.focus(link);
    expect(document.querySelector('[role="tooltip"]:not([hidden])')).not.toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.querySelector('[role="tooltip"]:not([hidden])')).toBeNull();
    expect(link).toHaveFocus();
  });

  it("renders no tooltip node when expanded, and the link keeps its identity across the toggle", () => {
    const { rerender } = renderRail(false);
    const link = screen.getByRole("link", { name: "Journal" });
    act(() => link.focus());
    fireEvent.focus(link);
    expect(tip()).toBeNull(); // expanded: empty content renders no node at all
    rerender(
      <MemoryRouter initialEntries={["/journal"]}>
        <NavRail collapsed badges={{ alerts: "2 new" }} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Journal" })).toBe(link);
    expect(link).toHaveFocus();
  });
});
