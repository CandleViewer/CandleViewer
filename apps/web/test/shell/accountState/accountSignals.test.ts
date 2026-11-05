/**
 * E29-S07 (#1028) the shell lift (BQ-5 of 6575172489; BQ-1 and BQ-2 ruled (6610918411)): the shell
 * store hears every `account_notice` as it arrives, keys an `oms.` state on (account, reason,
 * `changed_at_ms` or its absence) so a replay at reconnect is one state (`23` §15.9), and a stopped
 * shell leaves no state behind. The Positions tab's tests run unchanged through the re-export.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { delta } from "../../features/positions/support/fakes";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames";
import * as shim from "../../../src/features/positions/accountSignals";
import { createAccountSignals, shellAccountSignals } from "../../../src/shell/accountState";
import {
  applySystemUpdate,
  clearDegraded,
  resetShellState,
} from "../../../src/shell/bootstrap/store";

const A = "a1000000-0000-4000-8000-00000000000a";
const B = "a1000000-0000-4000-8000-00000000000b";

const notice = (reason: string, ids: string[], changedAtMs?: number): SystemUpdate =>
  ({
    kind: "account_notice",
    severity: "warning",
    reason,
    message: "role-neutral",
    exchange_account_ids: ids,
    ...(changedAtMs === undefined ? {} : { changed_at_ms: changedAtMs }),
  }) as SystemUpdate;

afterEach(() => resetShellState());

describe("the shell store hears every account_notice", () => {
  it("two notices in a row both land, though the shell keeps only the last of a kind", () => {
    applySystemUpdate(notice("oms.account_desync", [A], 1_000));
    applySystemUpdate(notice("oms.account_stale", [B], 2_000));
    const accounts = shellAccountSignals.getSnapshot().accounts;
    expect(accounts.get(A)?.oms).toMatchObject({ state: "desync", sinceMs: 1_000 });
    expect(accounts.get(B)?.oms).toMatchObject({ state: "stale", sinceMs: 2_000 });
  });

  it("another system kind changes no account", () => {
    const before = shellAccountSignals.getSnapshot();
    applySystemUpdate({ kind: "notice", severity: "info", message: "hi" } as SystemUpdate);
    expect(shellAccountSignals.getSnapshot()).toBe(before);
  });

  it("a stopped shell (clearDegraded) and the test reset drop every account state", () => {
    applySystemUpdate(notice("oms.account_stale", [A], 1_000));
    clearDegraded();
    expect(shellAccountSignals.getSnapshot().accounts.size).toBe(0);
    applySystemUpdate(notice("oms.account_stale", [A], 1_000));
    resetShellState();
    expect(shellAccountSignals.getSnapshot().accounts.size).toBe(0);
  });

  it("the Positions tab's module is the shell's (a re-export, one mapping)", () => {
    expect(shim.createAccountSignals).toBe(createAccountSignals);
  });
});

describe("the key: account, reason and changed_at_ms (23 §15.9; BQ-1 ruled)", () => {
  it("a replay equal in all three is that state again: no new episode, the server's time kept", () => {
    const s = createAccountSignals();
    s.applyNotice(notice("oms.account_stale", [A], 5_000), 9_000);
    const first = s.getSnapshot().accounts.get(A)?.oms;
    expect(first).toEqual({
      state: "stale",
      sinceMs: 5_000,
      changedAtMs: 5_000,
      episode: 1,
      killLock: false,
    });
    const version = s.getSnapshot().version;
    s.applyNotice(notice("oms.account_stale", [A], 5_000), 20_000);
    expect(s.getSnapshot().version).toBe(version);
    expect(s.getSnapshot().accounts.get(A)?.oms).toBe(first);
  });

  it("an untimed lock then B19's timed one is one lock with its time (no new episode)", () => {
    const s = createAccountSignals();
    s.applyNotice(notice("oms.account_stale", [A]), 9_000);
    expect(s.getSnapshot().accounts.get(A)?.oms).not.toHaveProperty("changedAtMs");
    s.applyNotice(notice("oms.account_stale", [A], 8_500), 9_100);
    expect(s.getSnapshot().accounts.get(A)?.oms).toEqual({
      state: "stale",
      sinceMs: 8_500,
      changedAtMs: 8_500,
      episode: 1,
      killLock: false,
    });
  });

  it("an untimed replay of a timed state keeps the time and the episode", () => {
    const s = createAccountSignals();
    s.applyNotice(notice("oms.account_desync", [A], 3_000), 4_000);
    s.applyNotice(notice("oms.account_desync", [A]), 7_000);
    expect(s.getSnapshot().accounts.get(A)?.oms).toMatchObject({ sinceMs: 3_000, episode: 1 });
  });

  it("the same reason at another server time is a new episode (a later pass's desync)", () => {
    const s = createAccountSignals();
    s.applyNotice(notice("oms.account_desync", [A], 3_000), 4_000);
    s.applyNotice(notice("oms.account_desync", [A], 6_000), 7_000);
    expect(s.getSnapshot().accounts.get(A)?.oms).toMatchObject({ sinceMs: 6_000, episode: 2 });
  });

  it("a time that is not a safe integer is no time: the client's first-heard time stands", () => {
    const s = createAccountSignals();
    s.applyNotice(notice("oms.account_resyncing", [A], 1.5), 4_000);
    expect(s.getSnapshot().accounts.get(A)?.oms).toEqual({
      state: "reconciling",
      sinceMs: 4_000,
      episode: 1,
      killLock: false,
    });
  });

  it("synced for an account with no state starts and ends nothing", () => {
    const s = createAccountSignals();
    s.applyNotice(notice("oms.account_synced", [A], 1_000), 2_000);
    expect(s.getSnapshot().accounts.size).toBe(0);
  });
});

describe("the bound (review fold m3)", () => {
  it("a state refused past 256 accounts marks the store overflowed, logs once, and a clear resets it", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const s = createAccountSignals();
    const id = (i: number) => `a1000000-0000-4000-8000-${String(i).padStart(12, "0")}`;
    for (let i = 0; i < 258; i += 1) s.applyNotice(notice("oms.account_desync", [id(i)], 1), 1);
    expect(s.getSnapshot().accounts.size).toBe(256);
    expect(s.getSnapshot().overflowed).toBe(true);
    expect(warn).toHaveBeenCalledTimes(1);
    s.clear();
    expect(s.getSnapshot().overflowed).toBe(false);
    warn.mockRestore();
  });

  it("a lockout refused past 256 accounts also marks the store overflowed (it is dropped, never silent)", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const s = createAccountSignals();
    const id = (i: number) => `a1000000-0000-4000-8000-${String(i).padStart(12, "0")}`;
    const locked = delta({
      machine_kind: "risk_lockout",
      state: "locked",
      tags: ["trading_blocked"],
      degraded: false,
      machine_hash: "0".repeat(64),
      environment: "live",
      updated_at_ms: 1,
    });
    for (let i = 0; i < 257; i += 1) s.applyLockout(id(i), [locked]);
    expect(s.getSnapshot().accounts.size).toBe(256);
    expect(s.getSnapshot().accounts.has(id(256))).toBe(false);
    expect(s.getSnapshot().overflowed).toBe(true);
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });
});
