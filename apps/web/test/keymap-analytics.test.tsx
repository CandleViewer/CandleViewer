import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDispatcher } from "../src/keymap/dispatcher";
import type { KeyEventLike } from "../src/keymap/keymap";

/**
 * #305 (E10-S02) PR C, BQ-10: the ticket's three analytics events (`hotkey.rebound {action, from, to}`,
 * `hotkey.conflict_blocked {action, collidesWith}`, `hotkey.inert_pressed {action, view}`) and `14` SCR-113's two
 * (`hotkey.reset`, `hotkey.profile_imported`), no other name, on the app's analytics seam (`cv:analytics` on
 * `window`). An event names commands, contexts and bindings only: never the user, and never a key typed in a field.
 */
const load = async () => ({
  ...(await import("../src/keymap/KeymapHost")),
  ...(await import("../src/keymap/HotkeyEditor")),
  ...(await import("../src/keymap/audit")),
  ...(await import("../src/lib/auth/meCache")),
  ...(await import("../src/shell/bootstrap/store")),
});
let m: Awaited<ReturnType<typeof load>>;
let events: unknown[];
const listen = (e: Event): void => {
  events.push((e as CustomEvent<unknown>).detail);
};

beforeEach(async () => {
  window.localStorage.clear();
  vi.resetModules();
  m = await load();
  m.setAuditSink(() => undefined);
  events = [];
  window.addEventListener("cv:analytics", listen);
  // An Owner is signed in, so a user id exists that an event could leak; none may carry it.
  const permissions = ["settings:read", "settings:write"];
  m.setMeClaims({ authenticated: true, role: "owner", permissions });
  m.setShellState({
    me: {
      accounts: [],
      permissions,
      role: "owner",
      user: {
        id: "u-1",
        email: "u@example.test",
        username: "u",
        roles: ["owner"],
        status: "active",
      },
    },
  });
});
afterEach(() => window.removeEventListener("cv:analytics", listen));

const NAMES = [
  "hotkey.rebound",
  "hotkey.conflict_blocked",
  "hotkey.inert_pressed",
  "hotkey.reset",
  "hotkey.profile_imported",
];
/** The hotkey events said so far, and a check that no other hotkey name was ever said. */
function said(): unknown[] {
  const ours = events.filter((e) => String((e as { name?: unknown }).name).startsWith("hotkey."));
  for (const e of ours) expect(NAMES).toContain((e as { name: string }).name);
  return ours;
}
const inRow = (label: string) =>
  within(screen.getByText(label, { selector: 'th[scope="row"]' }).closest("tr") as HTMLElement);
function bind(label: string, key: string, mods: readonly string[] = []): void {
  const row = inRow(label);
  for (const mod of mods)
    fireEvent.click(row.getByRole("checkbox", { name: `${mod} for ${label}` }));
  fireEvent.change(row.getByRole("textbox", { name: `Key for ${label}` }), {
    target: { value: key },
  });
  fireEvent.click(row.getByRole("button", { name: /^Save\b/ }));
}
const button = (name: string): HTMLElement => screen.getByText(name, { selector: "button" });

describe("SCR-113's changes: hotkey.rebound, hotkey.conflict_blocked, hotkey.reset, hotkey.profile_imported", () => {
  it("a rebind and an unbind each say hotkey.rebound {action, from, to}, and nothing more", () => {
    render(<m.HotkeyEditor />);
    bind("Toggle footprint", "Q", ["Alt"]);
    fireEvent.click(inRow("Toggle footprint").getByRole("button", { name: /^Unbind\b/ }));
    expect(said()).toEqual([
      { name: "hotkey.rebound", action: "chart.footprint_toggle", from: "F", to: "Alt+Q" },
      { name: "hotkey.rebound", action: "chart.footprint_toggle", from: "Alt+Q", to: "" },
    ]);
  });

  it("a blocked save says hotkey.conflict_blocked {action, collidesWith}; its swap says both moves", () => {
    render(<m.HotkeyEditor />);
    bind("Footprint mode profile/box", "Z", ["Ctrl"]);
    bind("Price zoom in", "-");
    fireEvent.click(inRow("Price zoom in").getByRole("button", { name: "Swap" }));
    expect(said()).toEqual([
      {
        name: "hotkey.conflict_blocked",
        action: "chart.footprint_mode",
        collidesWith: "chart.undo",
      },
      { name: "hotkey.conflict_blocked", action: "dom.zoom_in", collidesWith: "dom.zoom_out" },
      { name: "hotkey.rebound", action: "dom.zoom_in", from: "+", to: "-" },
      { name: "hotkey.rebound", action: "dom.zoom_out", from: "-", to: "+" },
    ]);
  });

  it("Reset all says hotkey.reset and an import hotkey.profile_imported, once each; a failed import nothing", () => {
    render(<m.HotkeyEditor />);
    fireEvent.click(button("Reset all"));
    const box = screen.getByLabelText("Import keymap (JSON)");
    fireEvent.change(box, { target: { value: "not json" } });
    fireEvent.click(button("Import"));
    fireEvent.change(box, { target: { value: '{"chart.footprint_toggle":"Alt+Q"}' } });
    fireEvent.click(button("Import"));
    expect(said()).toEqual([{ name: "hotkey.reset" }, { name: "hotkey.profile_imported" }]);
  });
});

describe("hotkey.inert_pressed {action, view}: where a key was pressed that does nothing there", () => {
  it("names the command and the view it was pressed in; a key typed in a field says nothing", () => {
    render(
      <div data-keymap-context="Chart">
        <button type="button">chart</button>
        <input aria-label="note" />
        <m.KeymapHost />
      </div>,
    );
    screen.getByRole("button", { name: "chart" }).focus();
    fireEvent.keyDown(window, { key: "X", code: "KeyX", ctrlKey: true, shiftKey: true });
    screen.getByRole("textbox", { name: "note" }).focus();
    fireEvent.keyDown(window, { key: "b", code: "KeyB" });
    expect(said()).toEqual([
      { name: "hotkey.inert_pressed", action: "dom.cancel_all", view: "Chart" },
    ]);
  });

  it("an order-entry key while the arm reads unarmed is an inert press too", () => {
    m.registerCommand("ticket.submit", vi.fn());
    render(
      <div data-keymap-context="Ticket">
        <button type="button">ticket</button>
        <m.KeymapHost />
      </div>,
    );
    screen.getByRole("button", { name: "ticket" }).focus();
    fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
    expect(said()).toEqual([
      { name: "hotkey.inert_pressed", action: "ticket.submit", view: "Ticket" },
    ]);
  });

  const held = (key: string, init: Partial<Omit<KeyEventLike, "key">>): KeyEventLike => ({
    key,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    ...init,
  });
  it.each([
    [
      "the unarmed default, Ctrl+Enter in a ticket",
      held("Enter", { ctrlKey: true }),
      "Ticket",
      "ticket.submit",
    ],
    [
      "an inert key, Ctrl+Shift+X outside the DOM view",
      held("X", { code: "KeyX", ctrlKey: true, shiftKey: true }),
      "Chart",
      "dom.cancel_all",
    ],
  ])(
    "CR-305C-03, pin: %s counts once, however long the key is held",
    (_what, press, view, action) => {
      const countInert = vi.fn();
      const d = createDispatcher({
        isValid: () => true,
        execute: vi.fn(),
        notify: vi.fn(),
        now: () => 0,
        countInert,
      });
      const active = new Set(["Global", view]);
      d(press, active);
      d({ ...press, repeat: true }, active);
      d({ ...press, repeat: true }, active);
      expect(countInert.mock.calls).toEqual([[action, view]]);
    },
  );
});
