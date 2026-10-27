import { beforeEach, describe, expect, it, vi } from "vitest";
import { PRIVATE_HANDOVER_MS } from "../../../src/features/system-states/degradedIssues.js";
import {
  INITIAL_SHELL_STATE,
  applySystemUpdate,
  getShellState,
  resetShellState,
  setShellState,
  subscribeShellState,
} from "../../../src/shell/bootstrap/store.js";

describe("shell store", () => {
  beforeEach(() => {
    resetShellState();
  });

  it("defaults to the unknown environment and loading bootstrap phase", () => {
    expect(getShellState()).toEqual(INITIAL_SHELL_STATE);
    expect(getShellState().environment).toBe("unknown");
  });

  it("setShellState merges a partial patch and notifies subscribers", () => {
    const seen: string[] = [];
    subscribeShellState(() => seen.push(getShellState().environment));
    setShellState({ environment: "demo" });
    expect(getShellState().environment).toBe("demo");
    expect(seen).toEqual(["demo"]);
  });

  it("unsubscribe stops notification", () => {
    let calls = 0;
    const unsubscribe = subscribeShellState(() => {
      calls += 1;
    });
    unsubscribe();
    setShellState({ environment: "live" });
    expect(calls).toBe(0);
  });

  it("applySystemUpdate keys the latest frame by kind", () => {
    applySystemUpdate({ kind: "health", health: "degraded" });
    applySystemUpdate({ kind: "kill_switch", kill_switch: { engaged: true, scope: "global" } });
    const state = getShellState();
    expect(state.systemByKind.health).toEqual({ kind: "health", health: "degraded" });
    expect(state.systemByKind.kill_switch?.kill_switch?.engaged).toBe(true);
  });

  it("applySystemUpdate replaces the prior frame of the same kind", () => {
    applySystemUpdate({ kind: "health", health: "healthy" });
    applySystemUpdate({ kind: "health", health: "down" });
    expect(getShellState().systemByKind.health).toEqual({ kind: "health", health: "down" });
  });

  it("resetShellState drops a pending private-reconnect hand-over (E10-S04)", () => {
    vi.useFakeTimers();
    try {
      applySystemUpdate({ kind: "exchange_state", private_ws: "connecting" });
      expect(getShellState().degraded.asserted.privateReconnect).toBe(1);
      resetShellState();
      const notified = vi.fn();
      subscribeShellState(notified);
      vi.advanceTimersByTime(PRIVATE_HANDOVER_MS);
      expect(notified).not.toHaveBeenCalled();
      expect(getShellState()).toBe(INITIAL_SHELL_STATE);
    } finally {
      vi.useRealTimers();
    }
  });

  it("resetShellState restores the frozen initial state and notifies", () => {
    setShellState({ environment: "live" });
    let notified = false;
    subscribeShellState(() => {
      notified = true;
    });
    resetShellState();
    expect(getShellState()).toEqual(INITIAL_SHELL_STATE);
    expect(notified).toBe(true);
  });
});
