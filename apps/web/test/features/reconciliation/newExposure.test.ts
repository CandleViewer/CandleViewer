/**
 * E29-S07 (#1028) new exposure per account (BQ-7 of 6575172489; BQ-3 ruled (6610918411)): the
 * selector's legs in order, the guard's `order.blocked_offline`, the keymap's arm-gated entries,
 * and the ruling's binding line — no exit path ever consults the guard (C-2.6, `24` §8.10).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BLIND_REASONS,
  RECON_REASONS,
  guardNewExposure,
  installKeymapExposureGuard,
  newExposureGate,
  type ExposureInput,
} from "../../../src/features/reconciliation/newExposure";
import { createDispatcher } from "../../../src/keymap/dispatcher";
import { KEYMAP } from "../../../src/keymap/keymap";
import {
  EXPOSURE_UNINSTALLED,
  appExposure,
  appExposureRefusal,
  createCommandRegistry,
  exposureAllows,
  type ExposurePort,
} from "../../../src/keymap/registry";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { EngineEvent, WsState } from "../../../src/lib/ws/state/types";
import type { AccountSignal } from "../../../src/shell/accountState";
import { applySystemUpdate, resetShellState } from "../../../src/shell/bootstrap/store";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames";
import {
  OFF,
  ON,
  authOk,
  connecting,
  killSwitch,
  shutdown,
  stream,
} from "../../lib/ws/support/engineEvents";

const A = "a1000000-0000-4000-8000-00000000000a";
const run = (...events: EngineEvent[]): WsState => events.reduce(reduce, INITIAL_WS_STATE);
const UP = run(connecting, authOk(OFF), stream("live"));
const sig = (state: "reconciling" | "desync" | "stale", killLock = false): AccountSignal => ({
  oms: { state, sinceMs: 1, episode: 1, killLock },
  lockout: null,
});
const gate = (over: Partial<ExposureInput> = {}) =>
  newExposureGate({ ws: UP, privateFeedDown: false, account: undefined, ...over });
const reasonOf = (over: Partial<ExposureInput>) => {
  const v = gate(over);
  return v.open ? "open" : v.reason;
};
const client = (state: WsState): WsClientHandle =>
  ({ getState: () => state, subscribe: () => () => undefined }) as unknown as WsClientHandle;

afterEach(() => {
  setActiveClient(null);
  resetShellState();
});

describe("Trading is blocked while blind", () => {
  it("every leg of the transport refuses new exposure, with its reason in text", () => {
    expect(reasonOf({ ws: run(connecting) })).toBe("feed.disconnected");
    expect(reasonOf({ ws: reduce(UP, { type: "offline", cause: "tailnet_unreachable" }) })).toBe(
      "feed.unreachable",
    );
    expect(reasonOf({ ws: reduce(UP, killSwitch(ON)) })).toBe("risk.frozen.submit");
    expect(reasonOf({ ws: reduce(UP, shutdown) })).toBe("feed.shutdown");
    expect(reasonOf({ ws: run(connecting, authOk(), stream("stale")) })).toBe(
      "feed.system_unknown",
    );
    expect(reasonOf({ privateFeedDown: true })).toBe("feed.private_down");
    const v = gate({ privateFeedDown: true });
    expect(v.open ? "" : v.text).toBe("Private feed down — new orders off; cancel still works.");
  });

  it("an attempted submission is refused client-side and recorded as order.blocked_offline", () => {
    const seen: unknown[] = [];
    const on = (e: Event): void => void seen.push((e as CustomEvent).detail);
    window.addEventListener("cv:analytics", on);
    setActiveClient(client(run(connecting)));
    expect(guardNewExposure({ accountId: A }).open).toBe(false);
    window.removeEventListener("cv:analytics", on);
    expect(seen).toEqual([{ name: "order.blocked_offline", reason: "feed.disconnected" }]);
  });
});

describe("the selector's legs (E29-D03 §4.2 precedence)", () => {
  it("view-as first, then the transport, the lock and the pause", () => {
    expect(reasonOf({ viewingAs: "Dana", ws: run(connecting) })).toBe("rbac.view_as");
    expect(reasonOf({ ws: run(connecting), account: sig("stale") })).toBe("feed.disconnected");
    expect(reasonOf({ account: sig("stale") })).toBe("recon.stale");
    expect(reasonOf({ account: sig("stale", true) })).toBe("recon.killlock");
    expect(reasonOf({ account: sig("stale", true), reduceOnly: true })).toBe("recon.reduce");
    expect(reasonOf({ account: sig("desync") })).toBe("recon.desync");
    expect(reasonOf({ account: sig("reconciling") })).toBe("recon.reconciling");
    expect(reasonOf({ account: { oms: null, lockout: null } })).toBe("open");
    expect(reasonOf({})).toBe("open");
  });

  it("Repeated reconciliation failure: account A is locked while account B stays usable", () => {
    setActiveClient(client(UP));
    const notice = {
      kind: "account_notice",
      severity: "critical",
      reason: "oms.account_stale",
      message: "role-neutral",
      exchange_account_ids: [A],
      changed_at_ms: 1_000,
    } as SystemUpdate;
    applySystemUpdate(notice);
    expect(guardNewExposure({ accountId: A })).toMatchObject({
      open: false,
      reason: "recon.stale",
    });
    expect(guardNewExposure({ accountId: "a1000000-0000-4000-8000-00000000000b" }).open).toBe(true);
    expect(guardNewExposure({ accountId: null }).open).toBe(true);
  });

  it("a refusal other than the transport emits nothing (D03 C-18)", () => {
    const on = vi.fn();
    window.addEventListener("cv:analytics", on);
    setActiveClient(client(UP));
    applySystemUpdate({
      kind: "account_notice",
      severity: "warning",
      reason: "oms.account_desync",
      message: "m",
      exchange_account_ids: [A],
    } as SystemUpdate);
    expect(guardNewExposure({ accountId: A }).open).toBe(false);
    window.removeEventListener("cv:analytics", on);
    expect(on).not.toHaveBeenCalled();
  });

  it("every reason is one sentence of at most 60 characters with a full stop (G-T2.4)", () => {
    for (const text of [...Object.values(RECON_REASONS), ...Object.values(BLIND_REASONS)]) {
      expect(text.length).toBeLessThanOrEqual(60);
      expect(text).toMatch(/^[^.]+\.$/);
    }
  });
});

describe("the keymap's arm-gated entries consult the guard; no exit ever does", () => {
  const ARMED = { isArmed: () => true };
  const EXITS = KEYMAP.filter((c) => c.requiresArm !== true);

  it("an arm-gated entry runs only while the guard is open", () => {
    let open = false;
    const exposure: ExposurePort = { allows: vi.fn(() => open) };
    const registry = createCommandRegistry(KEYMAP, ARMED, exposure);
    const submit = vi.fn();
    registry.register("ticket.submit", submit);
    expect(registry.run("ticket.submit")).toBe(false);
    open = true;
    expect(registry.run("ticket.submit")).toBe(true);
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("a guard that throws reads closed", () => {
    const thrower: ExposurePort = {
      allows: () => {
        throw new Error("x");
      },
    };
    const submit = KEYMAP.find((c) => c.id === "ticket.submit");
    expect(submit === undefined ? true : exposureAllows(submit, thrower)).toBe(false);
  });

  it.each(EXITS.map((c) => [c.id]))("%s never consults the guard (C-2.6)", (id) => {
    const allows = vi.fn(() => false);
    const registry = createCommandRegistry(KEYMAP, ARMED, { allows });
    const handler = vi.fn();
    registry.register(id, handler);
    expect(registry.run(id, 1)).toBe(true);
    expect(handler).toHaveBeenCalled();
    expect(allows).not.toHaveBeenCalled();
  });

  it("the exits include every cancel, close, flatten and stop command", () => {
    const ids = EXITS.map((c) => c.id);
    expect(ids).toEqual(
      expect.arrayContaining([
        "positions.close",
        "positions.close_all",
        "dom.cancel_all",
        "positions.open_sltp",
      ]),
    );
  });
});

describe("the app's guard is injected, never imported by the registry", () => {
  it("until the shell installs it, an arm-gated entry is refused; exits never consult it", () => {
    expect(EXPOSURE_UNINSTALLED.allows()).toBe(false);
    expect(EXPOSURE_UNINSTALLED.refusal()).toBe("Trading controls are not ready.");
    const submit = KEYMAP.find((c) => c.id === "ticket.submit");
    expect(submit === undefined ? true : exposureAllows(submit, appExposure)).toBe(false);
    for (const c of KEYMAP.filter((k) => k.requiresArm !== true)) {
      expect(exposureAllows(c, appExposure), c.id).toBe(true);
    }
  });

  it("uninstalled, a refused arm-gated hotkey is reported blocked and told once (G-T2.3)", () => {
    const notify = vi.fn();
    const d = createDispatcher({
      isValid: () => true,
      execute: vi.fn(),
      notify,
      now: () => 0,
      arm: { isArmed: () => true },
      exposureRefusal: () => appExposureRefusal(),
    });
    const press = { key: "Enter", ctrlKey: true, metaKey: false, altKey: false, shiftKey: false };
    expect(d(press, new Set(["Global", "Ticket"]))).toEqual({
      status: "blocked",
      commandId: "ticket.submit",
      notified: true,
    });
    expect(notify).toHaveBeenCalledWith("Trading controls are not ready.");
  });

  it("installed, the app's guard and refusal read the live verdict; stopping restores fail closed", () => {
    const stop = installKeymapExposureGuard();
    setActiveClient(client(run(connecting)));
    expect(appExposure.allows()).toBe(false);
    expect(appExposureRefusal()).toBe(
      "Not connected — new orders off; cancel and close still work.",
    );
    setActiveClient(client(UP));
    expect(appExposure.allows()).toBe(true);
    expect(appExposureRefusal()).toBeNull();
    stop();
    expect(appExposure.allows()).toBe(false);
  });

  it("the registry module imports no guard (a light keymap import)", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const src = readFileSync(
      resolve(import.meta.dirname, "../../../src/keymap/registry.ts"),
      "utf8",
    );
    expect(src).not.toMatch(/from "\.\.\/features\/reconciliation/);
  });
});

describe("fail closed (review fold m3)", () => {
  it("connected but before the first system snapshot, a scoped account reads reconciling", () => {
    const pending: WsState = { ...UP, systemStream: "pending" }; // the replay is not heard yet
    const gate = (scoped: boolean) =>
      newExposureGate({ ws: pending, privateFeedDown: false, account: undefined, scoped });
    expect(gate(true)).toMatchObject({ open: false, reason: "recon.reconciling" });
    expect(gate(false).open).toBe(true); // a control with no account in scope
    const live = newExposureGate({
      ws: UP,
      privateFeedDown: false,
      account: undefined,
      scoped: true,
    });
    expect(live.open).toBe(true);
  });

  it("past the store's bound an unheld account reads reconciling, a held one its own state", () => {
    const gate = (account: AccountSignal | undefined) =>
      newExposureGate({ ws: UP, privateFeedDown: false, account, scoped: true, overflowed: true });
    expect(gate(undefined)).toMatchObject({ open: false, reason: "recon.reconciling" });
    expect(gate({ oms: null, lockout: null }).open).toBe(true);
  });
});

describe("a refused hotkey says why (review fold m1, G-T2.3)", () => {
  it("an armed order entry with new exposure closed is taken, not run, and its reason told once", () => {
    const execute = vi.fn();
    const notify = vi.fn();
    const exposureRefusal = vi.fn(() => "Stale — new orders locked until the owner resolves it.");
    const d = createDispatcher({
      isValid: () => true,
      execute,
      notify,
      now: () => 0,
      arm: { isArmed: () => true },
      exposureRefusal,
    });
    const press = { key: "Enter", ctrlKey: true, metaKey: false, altKey: false, shiftKey: false };
    const ctx = new Set(["Global", "Ticket"]);
    expect(d(press, ctx)).toEqual({
      status: "blocked",
      commandId: "ticket.submit",
      notified: true,
    });
    expect(d(press, ctx)).toEqual({
      status: "blocked",
      commandId: "ticket.submit",
      notified: false,
    });
    expect(execute).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith("Stale — new orders locked until the owner resolves it.");
  });
});
