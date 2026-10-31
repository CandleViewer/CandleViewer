import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createDispatcher } from "../src/keymap/dispatcher";
import { DANGEROUS_COMMANDS, KEYMAP, type KeyEventLike } from "../src/keymap/keymap";
import { commandMeta, createCommandRegistry, type ArmPort } from "../src/keymap/registry";

/**
 * #305 (E10-S02) PR C, BQ-5: `requiresArm` on the five order-entry commands `22`'s `ArmToken` forces the arm on (each
 * is a submit, `placeOrder`), never on a protective one (C-2.6); an injected `ArmPort` that reads unarmed by default
 * (fail closed); `confirm` on every dangerous command. The UI reads the arm and the server decides it (C-2.21, C-12.4):
 * these tests pin what the client runs and says, never an enforcement. AC2's scenario closes here too. A `pin:` test
 * passes before the change as well: it guards behaviour the arm must not alter.
 */
const FORCED = [
  "chart.limit_at_price",
  "chart.market_order",
  "dom.market_click",
  "dom.stop_click",
  "ticket.submit",
];
const ARMED: ArmPort = { isArmed: () => true };
const LOCKED = "Submit order is not available: one-click trading is locked.";
const ev = (key: string, init: Partial<Omit<KeyEventLike, "key">> = {}): KeyEventLike => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...init,
});
const ctx = (...names: string[]): ReadonlySet<string> => new Set(["Global", ...names]);
const SUBMIT = ev("Enter", { ctrlKey: true });

function dispatcher(arm?: ArmPort) {
  const execute = vi.fn();
  const notify = vi.fn();
  const clock = { t: 0 };
  const d = createDispatcher({
    isValid: () => true,
    execute,
    notify,
    now: () => clock.t,
    ...(arm === undefined ? {} : { arm }),
  });
  return { d, execute, notify, clock };
}

describe("BQ-5: the arm set and confirm, declared in keymap.json", () => {
  it("requiresArm is on exactly the five order-entry commands: never a protective one or an arm toggle", () => {
    const armed = KEYMAP.filter((c) => commandMeta(c.id)?.requiresArm).map((c) => c.id);
    expect(armed.sort()).toEqual(FORCED);
    for (const id of ["dom.cancel_all", "positions.close", "positions.close_all", "dom.arm"]) {
      expect(commandMeta(id)?.requiresArm, id).toBe(false);
    }
  });

  it("confirm is declared on every dangerous command, so on each destructive one, and on no other", () => {
    const confirm = KEYMAP.filter((c) => commandMeta(c.id)?.confirm).map((c) => c.id);
    expect(confirm.sort()).toEqual([...DANGEROUS_COMMANDS].sort());
    for (const c of KEYMAP.filter((k) => k.destructive)) {
      expect(commandMeta(c.id)?.confirm, c.id).toBe(true);
    }
  });
});

describe("the ArmPort at a key press: unarmed unless a port says armed (fail closed)", () => {
  it("default unarmed: Ctrl+Enter in a ticket never submits; it says why once, and a held key never again", () => {
    const { d, execute, notify, clock } = dispatcher();
    expect(d(SUBMIT, ctx("Ticket"))).toEqual({
      status: "unarmed",
      commandId: "ticket.submit",
      notified: true,
    });
    clock.t = 1000;
    expect(d(SUBMIT, ctx("Ticket"))).toMatchObject({ status: "unarmed", notified: false });
    clock.t = 9000;
    expect(d({ ...SUBMIT, repeat: true }, ctx("Ticket"))).toMatchObject({ notified: false });
    expect(execute).not.toHaveBeenCalled();
    expect(notify.mock.calls).toEqual([[LOCKED]]);
  });

  it("pin: an armed test port fires", () => {
    const { d, execute } = dispatcher(ARMED);
    expect(d(SUBMIT, ctx("Ticket"))).toEqual({ status: "executed", commandId: "ticket.submit" });
    expect(execute).toHaveBeenCalledTimes(1);
  });

  it("a port that throws, or answers anything but true, reads unarmed", () => {
    const broken: ArmPort[] = [
      {
        isArmed: () => {
          throw new Error("arm state unknown");
        },
      },
      { isArmed: () => "yes" as unknown as boolean },
    ];
    for (const arm of broken) {
      const { d, execute } = dispatcher(arm);
      expect(d(SUBMIT, ctx("Ticket")).status).toBe("unarmed");
      expect(execute).not.toHaveBeenCalled();
    }
  });

  it("pin: C-2.6: cancel, close, the arm toggle and a ticket key run, never consulting the port", () => {
    const isArmed = vi.fn(() => false);
    const { d, execute } = dispatcher({ isArmed });
    const runs: readonly (readonly [KeyEventLike, string, string])[] = [
      [ev("X", { ctrlKey: true, shiftKey: true }), "DOM", "dom.cancel_all"],
      [ev("W", { ctrlKey: true }), "Positions", "positions.close"],
      [ev("W", { ctrlKey: true, shiftKey: true }), "Positions", "positions.close_all"],
      [ev("T", { ctrlKey: true, shiftKey: true }), "Ticket", "ticket.arm"],
      [ev("b", { code: "KeyB" }), "Ticket", "ticket.side_buy"],
    ];
    for (const [press, view, id] of runs) {
      expect(d(press, ctx(view)), id).toEqual({ status: "executed", commandId: id });
    }
    expect([execute.mock.calls.length, isArmed.mock.calls.length]).toEqual([5, 0]);
  });

  it("pin: an order entry with no handler here explains that, not the arm, and asks no port", () => {
    const isArmed = vi.fn(() => false);
    const notify = vi.fn();
    const d = createDispatcher({
      isValid: () => false,
      execute: vi.fn(),
      notify,
      now: () => 0,
      arm: { isArmed },
    });
    expect(d(SUBMIT, ctx("Ticket"))).toMatchObject({ status: "inert", commandId: "ticket.submit" });
    expect(notify.mock.calls[0]?.[0]).toMatch(
      /^Submit order is not available here \(Ticket view\)/,
    );
    expect(isArmed).not.toHaveBeenCalled();
  });
});

describe("the registry honours it on every path that runs a command, a key press or not", () => {
  it("run refuses an order-entry command until the port reads armed; a protective one never asks", () => {
    let armed = false;
    const isArmed = vi.fn(() => armed);
    const registry = createCommandRegistry(KEYMAP, { isArmed });
    const [submit, limit, cancel] = [vi.fn(), vi.fn(), vi.fn()];
    registry.register("ticket.submit", submit);
    registry.register("chart.limit_at_price", limit);
    registry.register("dom.cancel_all", cancel);
    expect(registry.run("ticket.submit")).toBe(false);
    expect(registry.run("chart.limit_at_price")).toBe(false);
    expect(registry.run("dom.cancel_all")).toBe(true);
    expect(isArmed).toHaveBeenCalledTimes(2);
    armed = true;
    expect([registry.run("ticket.submit"), registry.run("chart.limit_at_price")]).toEqual([
      true,
      true,
    ]);
    expect([submit, limit, cancel].map((f) => f.mock.calls.length)).toEqual([1, 1, 1]);
  });

  it("a registry with no port reads unarmed: a registered order entry is valid here, yet inert", () => {
    const registry = createCommandRegistry();
    const submit = vi.fn();
    registry.register("ticket.submit", submit);
    expect([registry.isValid("ticket.submit"), registry.run("ticket.submit")]).toEqual([
      true,
      false,
    ]);
    expect(submit).not.toHaveBeenCalled();
  });
});

describe("the wired host: E30 injects the session's arm with setArmPort", () => {
  // The registry, the profile and the host keep their state at module level: each test loads its own copy.
  const load = async () => ({
    ...(await import("../src/keymap/KeymapHost")),
    ...(await import("../src/keymap/registry")),
    ...(await import("../src/keymap/profile")),
  });
  let m: Awaited<ReturnType<typeof load>>;
  beforeEach(async () => {
    window.localStorage.clear();
    vi.resetModules();
    m = await load();
  });
  const toast = (): HTMLElement => screen.getByRole("region", { name: "Notifications" });
  /** Ctrl+Enter from the focused ticket; false when the host took the key (`preventDefault`). */
  const submit = (): boolean => fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
  function mountTicket(run: () => void): void {
    const { KeymapHost, registerCommand } = m;
    registerCommand("ticket.submit", run);
    render(
      <div data-keymap-context="Ticket">
        <button type="button">ticket</button>
        <KeymapHost />
      </div>,
    );
    screen.getByRole("button", { name: "ticket" }).focus();
  }

  it("default unarmed: the key is taken, runs nothing and says why once", () => {
    const run = vi.fn();
    mountTicket(run);
    expect([submit(), submit()]).toEqual([false, false]);
    expect(run).not.toHaveBeenCalled();
    expect(toast().querySelectorAll("p")).toHaveLength(1);
    expect(toast()).toHaveTextContent(LOCKED);
  });

  it("an armed port lets it run, a change of the arm applies at the next press, and teardown restores unarmed", () => {
    let armed = true;
    const off = m.setArmPort({ isArmed: () => armed });
    const run = vi.fn();
    mountTicket(run);
    submit();
    armed = false;
    submit();
    armed = true;
    submit();
    expect(run).toHaveBeenCalledTimes(2);
    off();
    submit();
    expect(run).toHaveBeenCalledTimes(2);
    expect(toast()).toHaveTextContent(LOCKED);
  });

  it("AC2: flatten rebound to Ctrl+Shift+F runs where it is valid and is inert, saying why, elsewhere", () => {
    const { KeymapHost, registerCommand, getBindings, setArmPort, setBindings } = m;
    const isArmed = vi.fn(() => false);
    setArmPort({ isArmed });
    act(() => setBindings(new Map(getBindings()).set("positions.close_all", "Ctrl+Shift+F")));
    const run = vi.fn();
    registerCommand("positions.close_all", run);
    render(
      <>
        <div data-keymap-context="Positions">
          <button type="button">positions</button>
        </div>
        <div data-keymap-context="Chart">
          <button type="button">chart</button>
        </div>
        <KeymapHost />
      </>,
    );
    const flatten = () =>
      fireEvent.keyDown(window, { key: "F", code: "KeyF", ctrlKey: true, shiftKey: true });
    screen.getByRole("button", { name: "positions" }).focus();
    flatten();
    expect(run).toHaveBeenCalledTimes(1);
    screen.getByRole("button", { name: "chart" }).focus();
    flatten();
    expect(run).toHaveBeenCalledTimes(1);
    expect(toast()).toHaveTextContent(
      "Close all in view (confirm) is not available here (Positions view): it needs always.",
    );
    expect(isArmed).not.toHaveBeenCalled(); // flatten is protective (C-2.6): the arm is never asked
  });
});
