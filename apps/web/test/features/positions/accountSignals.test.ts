/**
 * E29-S01 (#911, BQ-14) the account-level signals: `account_notice` reasons (`23` §15.9) mapped
 * to E29-D03 §4.1's line, marker and announcement per role, once per episode; the kill-switch lock;
 * the B20 risk lockout (a refused subscription reads unknown, never clear); the kill switch from
 * `WsState`. The resyncing frame is the shipped producer's golden; E29-T06's rows follow `23`'s table.
 */
import { describe, expect, it, vi } from "vitest";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames";
import type { KillSwitchView } from "../../../src/lib/ws/state/types";
import {
  accountLine,
  createAccountSignals,
  engagedAtOf,
  killSwitchBanner,
  killSwitchCovers,
  startAccountSignals,
} from "../../../src/features/positions/accountSignals";
import { bindDeck } from "../../../src/features/positions/copy";
import { delta, golden, MAIN, reset, snap, SUB1, SUB2 } from "./support/fakes";

const resyncing = golden<SystemUpdate>("ws_system_account_notice.json");
/** `23` §15.9's table rows for E29-T06's reasons (its producer is not wired yet, #914). */
const notice = (
  reason: string,
  ids: [string, ...string[]],
  severity: SystemUpdate["severity"] = "warning",
): SystemUpdate => ({
  kind: "account_notice",
  severity,
  reason,
  message: "role-neutral",
  exchange_account_ids: ids,
});
const engaged = (scope: "global" | "accounts", ids: string[] = []): KillSwitchView => ({
  state: "engaged",
  scope,
  exchangeAccountIds: ids,
});
const machine = (state: string) => ({
  machine_kind: "risk_lockout",
  state,
  tags: state === "locked" ? ["trading_blocked"] : ["trading_allowed"],
  degraded: false,
  machine_hash: "0".repeat(64),
  environment: "live",
  updated_at_ms: 1_793_455_331_000,
});

describe("account_notice → the account's state (D03 §4.1)", () => {
  it("Reconciling: the resyncing notice (the shipped producer's frame)", () => {
    const signals = createAccountSignals();
    signals.applyNotice(resyncing, 100);
    const sub1 = signals.getSnapshot().accounts.get(SUB1);
    expect(sub1?.oms).toEqual({ state: "reconciling", sinceMs: 100, episode: 1, killLock: false });
    expect(accountLine(sub1 ?? { oms: null, lockout: null }, "owner")).toEqual({
      line: "acct.reconciling.line",
      marker: "acct.marker.checking",
      announce: "acct.announce.reconciling",
    });
    expect(bindDeck("acct.reconciling.line", { "Sub-1": "Sub-1", LIVE: "LIVE" })).toBe(
      "Sub-1 · LIVE — Reconciling with the exchange… Values shown are the last Bybit confirmed. Closing, cancelling and tightening stops still work.",
    );
  });

  it("Verifying, then synced clears; a repeat is the same episode", () => {
    const signals = createAccountSignals();
    signals.applyNotice(notice("oms.account_desync", [SUB1]), 1);
    signals.applyNotice(notice("oms.account_desync", [SUB1]), 2);
    expect(signals.getSnapshot().accounts.get(SUB1)?.oms).toMatchObject({
      state: "desync",
      episode: 1,
      sinceMs: 1,
    });
    expect(
      accountLine(
        signals.getSnapshot().accounts.get(SUB1) ?? { oms: null, lockout: null },
        "viewer",
      )?.line,
    ).toBe("acct.desync.line");
    signals.applyNotice(notice("oms.account_synced", [SUB1], "info"), 3);
    expect(signals.getSnapshot().accounts.has(SUB1)).toBe(false);
    signals.applyNotice(notice("oms.account_desync", [SUB1.toUpperCase()]), 4);
    expect(signals.getSnapshot().accounts.get(SUB1)?.oms).toMatchObject({ episode: 2 }); // a new episode
  });

  it("Stale — locked: the cause is the Owner's; a Manager or Viewer reads the no-cause line", () => {
    const signals = createAccountSignals();
    signals.applyNotice(notice("oms.account_stale", [SUB2], "critical"), 7);
    const signal = signals.getSnapshot().accounts.get(SUB2) ?? { oms: null, lockout: null };
    expect(accountLine(signal, "owner")).toEqual({
      line: "acct.stale.line",
      marker: "acct.marker.stale",
      announce: "acct.announce.stale",
    });
    expect(accountLine(signal, "manager")?.line).toBe("acct.stale.line.nocause");
    expect(accountLine(signal, "viewer")?.line).toBe("acct.stale.line.nocause");
  });

  it("a stale notice under a covering kill switch is the kill-switch lock, for every role", () => {
    const signals = createAccountSignals();
    signals.setKillSwitch(engaged("accounts", [SUB2]), 5);
    signals.applyNotice(notice("oms.account_stale", [SUB1, SUB2]), 9);
    const sub2 = signals.getSnapshot().accounts.get(SUB2) ?? { oms: null, lockout: null };
    expect(accountLine(sub2, "manager")).toEqual({
      line: "acct.killlock.line",
      marker: "kill_lock",
      announce: null,
    });
    expect(signals.getSnapshot().accounts.get(SUB1)?.oms?.killLock).toBe(false);
  });

  it("events and unknown reasons are kept for nothing; bad ids are skipped", () => {
    const signals = createAccountSignals();
    const listener = vi.fn();
    signals.subscribe(listener);
    signals.applyNotice(notice("profiles.changed", [MAIN], "info"), 1);
    signals.applyNotice(notice("oms.account_unheard_of", [MAIN]), 1);
    signals.applyNotice(notice("oms.account_desync", ["not-an-id"]), 1);
    signals.applyNotice({ kind: "health" } as SystemUpdate, 1);
    expect(listener).not.toHaveBeenCalled();
    expect(accountLine({ oms: null, lockout: null }, "owner")).toBeNull();
  });
});

describe("the kill switch (WsState; 23 §15.9)", () => {
  it("covers every account when global, the listed ones when scoped, none when unknown", () => {
    expect(killSwitchCovers(engaged("global"), MAIN)).toBe(true);
    expect(killSwitchCovers(engaged("accounts", [SUB1.toUpperCase()]), SUB1)).toBe(true);
    expect(killSwitchCovers(engaged("accounts", [SUB1]), MAIN)).toBe(false);
    expect(killSwitchCovers({ state: "unknown" }, MAIN)).toBe(false);
  });

  it("S-19 and S-20: the Owner's banner, and every other role's", () => {
    expect(killSwitchBanner("owner")).toEqual(["blotter.ui.ks_owner"]);
    expect(killSwitchBanner("manager")).toEqual(["blotter.ui.ks_manager", "blotter.ui.ks_ask"]);
  });

  it("the engage time comes from the shell's last system frame that carries one", () => {
    expect(
      engagedAtOf({
        kill_switch: {
          kind: "kill_switch",
          kill_switch: { engaged: true, scope: "global", engaged_at_ms: 42 },
        },
      }),
    ).toBe(42);
    expect(
      engagedAtOf({
        health: {
          kind: "health",
          kill_switch: { engaged: true, scope: "global", engaged_at_ms: 7 },
        },
      }),
    ).toBe(7);
    expect(engagedAtOf({})).toBeNull();
  });

  it("publishes a change only", () => {
    const signals = createAccountSignals();
    const listener = vi.fn();
    signals.subscribe(listener);
    signals.setKillSwitch({ state: "unknown" }, null);
    signals.setKillSwitch(engaged("global"), 1);
    signals.setKillSwitch(engaged("global"), 1);
    signals.setKillSwitch(engaged("accounts", [MAIN]), 1);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

describe("the risk lockout (B20, 23 §6.4): the locked chip's state", () => {
  it("reads clear, warning and locked from the machine's payload", () => {
    const signals = createAccountSignals();
    signals.applyLockout(SUB2, [snap(machine("locked"))]);
    expect(signals.getSnapshot().accounts.get(SUB2)?.lockout).toBe("locked");
    expect(() => bindDeck("blotter.ui.lockout_chip", {})).toThrow(/unbound 00:00/); // its time must be bound
    expect(bindDeck("blotter.ui.lockout_chip", { "00:00": "00:00" })).toBe(
      "Locked · daily loss limit · until 00:00 UTC · closing and reducing still work",
    );
    signals.applyLockout(SUB2, [delta(machine("warning"))]);
    expect(signals.getSnapshot().accounts.get(SUB2)?.lockout).toBe("warning");
  });

  it("a refused or ended subscription reads unknown, never clear", () => {
    const signals = createAccountSignals();
    signals.applyLockout(SUB2, [snap(machine("clear"))]);
    signals.applyLockout(SUB2, [reset("revoked")]);
    expect(signals.getSnapshot().accounts.has(SUB2)).toBe(false);
  });

  it("ignores another machine's payload and an unknown state", () => {
    const signals = createAccountSignals();
    signals.applyLockout(SUB2, [
      snap({ ...machine("locked"), machine_kind: "kill_switch" }),
      delta(machine("frozen")),
    ]);
    expect(signals.getSnapshot().accounts.has(SUB2)).toBe(false);
  });

  it("forget and clear drop an account's signals (SR-E29-11)", () => {
    const signals = createAccountSignals();
    signals.applyNotice(resyncing, 1);
    signals.applyLockout(SUB2, [snap(machine("locked"))]);
    signals.forget([SUB1]);
    expect([...signals.getSnapshot().accounts.keys()]).toEqual([SUB2]);
    signals.clear();
    expect(signals.getSnapshot().accounts.size).toBe(0);
    signals.clear();
  });
});

describe("startAccountSignals", () => {
  it("seeds from the shell's last notice, follows new ones and the client's kill switch", () => {
    let systemByKind: Partial<Record<SystemUpdate["kind"], SystemUpdate>> = {
      account_notice: resyncing,
    };
    let killSwitch: KillSwitchView = { state: "unknown" };
    const shellListeners = new Set<() => void>();
    const wsListeners = new Set<() => void>();
    const signals = createAccountSignals();
    const stop = startAccountSignals(signals, {
      shell: {
        getState: () => ({ systemByKind }),
        subscribe: (l) => (shellListeners.add(l), () => shellListeners.delete(l)),
      },
      ws: {
        getState: () => ({ killSwitch }),
        subscribe: (l) => (wsListeners.add(l), () => wsListeners.delete(l)),
      },
      wall: () => 500,
    });
    expect(signals.getSnapshot().accounts.get(SUB1)?.oms).toMatchObject({
      state: "reconciling",
      sinceMs: 500,
    });
    killSwitch = engaged("global");
    wsListeners.forEach((l) => l());
    expect(signals.getSnapshot().killSwitch.view.state).toBe("engaged");
    systemByKind = { ...systemByKind, account_notice: notice("oms.account_stale", [SUB1]) };
    shellListeners.forEach((l) => l());
    expect(signals.getSnapshot().accounts.get(SUB1)?.oms).toMatchObject({
      state: "stale",
      killLock: true,
    });
    stop();
    expect(shellListeners.size + wsListeners.size).toBe(0);
  });
});
