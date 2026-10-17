// E17-T04 S1b (C12, WS-E06): the transport/kill-switch/order-entry state, driven only by `reduce`.
// `reducer.sweep.test.ts` checks the same invariants over every reachable state and event.
import { describe, expect, it } from "vitest";
import type { KillSwitchPayload } from "../../../src/lib/ws/protocol/frames";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { EngineEvent, TransportState, WsState } from "../../../src/lib/ws/state/types";
import {
  OFF,
  ON,
  authOk,
  connecting,
  killSwitch,
  offline,
  quality,
  retry,
  shutdown,
  stream,
  system,
  wire,
} from "./support/engineEvents";

const run = (...events: EngineEvent[]): WsState => events.reduce(reduce, INITIAL_WS_STATE);

describe("transport states", () => {
  it("starts connecting, with the kill switch unknown and order entry off", () => {
    expect(INITIAL_WS_STATE).toMatchObject({
      transport: "connecting",
      transitionSeq: 0,
      killSwitch: { state: "unknown" },
      orderEntry: { enabled: false, reason: "kill_switch_unknown" },
    });
  });

  it.each<[TransportState, EngineEvent[]]>([
    ["connecting", []],
    ["connected", [authOk(OFF)]],
    ["degraded:lagging", [authOk(OFF), quality("lagging")]],
    ["degraded:saturated", [authOk(OFF), quality("saturated")]],
    ["reconnecting", [authOk(OFF), retry(1)]],
    ["offline", [offline]],
    ["shutdown_pending", [authOk(OFF), shutdown]],
  ])("%s is reachable", (transport, events) => {
    expect(run(...events).transport).toBe(transport);
  });

  it("reads an overflowing connection as saturated", () => {
    expect(run(authOk(OFF), quality("overflowing")).transport).toBe("degraded:saturated");
  });

  it("ignores a connection class it does not know, a prototype key included (untrusted wire)", () => {
    const lagging = run(authOk(OFF), quality("lagging"));
    const odd = ["odd", "__proto__", "constructor", "toString", "hasOwnProperty", 3, null, {}];
    for (const wireClass of [...odd, undefined]) {
      expect(reduce(lagging, quality(wireClass))).toBe(lagging);
      expect(run(authOk(OFF), quality(wireClass)).transport).toBe("connected");
    }
  });

  it("moves transitionSeq once per change of transport, never per event", () => {
    const steps: [EngineEvent, number][] = [
      [connecting, 0],
      [authOk(OFF), 1],
      [quality("lagging"), 2],
      [quality("lagging"), 2],
      [system({ kind: "health", health: "healthy" }), 2],
      [quality("saturated"), 3], // degraded:lagging -> degraded:saturated is a change of row
      [quality("healthy"), 4],
      [retry(1), 5],
      [retry(2), 5],
      [offline, 6],
      [{ type: "offline", cause: "fatal", closeCode: 4403 }, 6], // the cause is not a new row
      [connecting, 7],
      [authOk(OFF), 8],
      [shutdown, 9],
      [authOk(OFF), 9], // an in-place re-auth is not a transition
    ];
    let state = INITIAL_WS_STATE;
    for (const [event, seq] of steps) {
      state = reduce(state, event);
      expect(state.transitionSeq).toBe(seq);
    }
  });

  it("returns the same state object for an event that changes nothing", () => {
    const welcome: EngineEvent = { type: "welcome", connectionId: "ws_1" };
    const requestId: EngineEvent = { type: "request_id", requestId: "r-1" };
    const live = run(connecting, welcome, requestId, authOk(OFF));
    const repeats = [authOk(OFF), killSwitch(OFF), quality("healthy"), stream("pending")];
    const quiet = [system({ kind: "notice" }), system({ kind: "health" }), welcome, requestId];
    for (const event of [...repeats, ...quiet]) expect(reduce(live, event)).toBe(live);
    const down = run(offline);
    expect(reduce(down, offline)).toBe(down);
    expect(reduce(live, killSwitch(ON))).not.toBe(live); // a real change is a new object
  });

  it("keeps the connection and request ids, in either order, until a later one replaces them", () => {
    const welcome: EngineEvent = { type: "welcome", connectionId: "ws_1" };
    const requestId: EngineEvent = { type: "request_id", requestId: "r-1" };
    const ids = { connectionId: "ws_1", requestId: "r-1" };
    expect(run(welcome, requestId).diagnostics).toEqual(ids);
    expect(run(requestId, welcome, offline, connecting).diagnostics).toEqual(ids);
    const later: EngineEvent = { type: "welcome", connectionId: "ws_2" };
    expect(run(welcome, requestId, later).diagnostics).toEqual({ ...ids, connectionId: "ws_2" });
  });

  it("never puts a connection id, a request id or server prose in a user-facing field", () => {
    const prose = { ...ON, engaged_by: "PROSE_USER", reason: "PROSE_REASON" };
    const state = run(
      { type: "welcome", connectionId: "ID_CONNECTION" },
      { type: "request_id", requestId: "ID_REQUEST" },
      authOk(prose),
      system({ kind: "notice", message: "PROSE_NOTICE" }),
    );
    expect(state.killSwitch).toEqual({ state: "engaged", scope: "global", exchangeAccountIds: [] });
    expect(JSON.stringify({ ...state, diagnostics: null })).not.toMatch(/PROSE|ID_/);
    expect(state.diagnostics).toEqual({ connectionId: "ID_CONNECTION", requestId: "ID_REQUEST" });
  });
});

describe("kill switch and order entry (C12, WS-E06)", () => {
  it("kill switch engaged disables order entry synchronously", () => {
    const live = run(authOk(OFF));
    expect(live.orderEntry).toEqual({ enabled: true, reason: null });
    const next = reduce(live, killSwitch(ON)); // one call: no await, no REST
    expect(next.orderEntry).toEqual({ enabled: false, reason: "kill_switch_engaged" });
    expect(reduce(next, killSwitch(OFF)).orderEntry.enabled).toBe(true);
  });

  it("counts a kill switch carried by any system kind, with its scope and accounts", () => {
    const scoped: KillSwitchPayload = {
      engaged: true,
      scope: "accounts",
      exchange_account_ids: ["a-1"],
    };
    const state = reduce(run(authOk(OFF)), system({ kind: "health", kill_switch: scoped }));
    expect(state.killSwitch).toEqual({
      state: "engaged",
      scope: "accounts",
      exchangeAccountIds: ["a-1"],
    });
    expect(state.orderEntry.enabled).toBe(false);
  });

  it("WS-E06 (Q6): unknown, never not-killed, while the transport is down or the system stream resyncs", () => {
    const live = run(authOk(ON));
    expect(live.killSwitch.state).toBe("engaged");
    for (const down of [reduce(live, retry(1)), reduce(live, offline)]) {
      expect(down.killSwitch).toEqual({ state: "unknown" });
      expect(down.orderEntry).toEqual({ enabled: false, reason: "kill_switch_unknown" });
    }
    const resyncing = reduce(run(authOk(OFF)), stream("resyncing"));
    expect(resyncing.killSwitch.state).toBe("unknown");
    expect(resyncing.orderEntry.enabled).toBe(false);
    // The value the gap may have invalidated is not resurrected when the stream comes back.
    const live2 = reduce(resyncing, stream("live"));
    expect(live2.killSwitch.state).toBe("unknown");
    expect(reduce(live2, killSwitch(OFF)).orderEntry.enabled).toBe(true);
  });

  it("takes a kill-switch fact only while the system stream is pending or live", () => {
    for (const status of ["resyncing", "stale", "revoked"] as const) {
      const gap = reduce(run(authOk(OFF)), stream(status));
      expect(reduce(gap, killSwitch(OFF)).killSwitch.state).toBe("unknown"); // dropped, not queued
    }
    // The order the engine promises: `live` first, then the update of the snapshot that ended it.
    const healed = run(authOk(OFF), stream("resyncing"), stream("live"), killSwitch(ON));
    expect(healed.orderEntry).toEqual({ enabled: false, reason: "kill_switch_engaged" });
    // The first `system` snapshot flips the stream to live and must not wipe the `auth_ok` fact.
    expect(run(authOk(ON), stream("live")).killSwitch.state).toBe("engaged");
    expect(run(authOk(OFF), stream("live")).orderEntry.enabled).toBe(true);
  });

  it.each([
    ["missing", undefined],
    ["null", null],
    ["a string engaged flag", { engaged: "no", scope: "global" }],
    ["no engaged flag", { scope: "global" }],
    ["an unknown scope", { engaged: false, scope: "nowhere" }],
    [
      "a non-array account list",
      { engaged: false, scope: "accounts", exchange_account_ids: "a-1" },
    ],
    ["a non-string account id", { engaged: false, scope: "accounts", exchange_account_ids: [1] }],
    ["a null account list", { engaged: true, scope: "accounts", exchange_account_ids: null }],
  ])("a %s kill switch is unknown, from auth_ok and from a system frame", (_name, payload) => {
    const viaAuth = run(authOk(wire<KillSwitchPayload | undefined>(payload)));
    const viaSystem = reduce(run(authOk(OFF)), killSwitch(payload));
    for (const state of [viaAuth, viaSystem]) {
      expect(state.killSwitch).toEqual({ state: "unknown" });
      expect(state.orderEntry).toEqual({ enabled: false, reason: "kill_switch_unknown" });
    }
  });

  it("copies the account ids: the state never aliases the event", () => {
    const ids = ["a-1"];
    const state = run(authOk({ engaged: true, scope: "accounts", exchange_account_ids: ids }));
    ids.push("a-2");
    expect(state.killSwitch).toMatchObject({ exchangeAccountIds: ["a-1"] });
  });

  it("shutdown_notice disables order entry until the next connection's auth_ok", () => {
    const pending = run(authOk(OFF), shutdown);
    expect(pending.transport).toBe("shutdown_pending");
    expect(pending.shutdown).toEqual({ closingInMs: 5000, expectedDowntimeMs: 2e4 });
    expect(pending.orderEntry).toEqual({ enabled: false, reason: "shutdown_pending" });
    const closed = reduce(pending, retry(1));
    expect(closed.transport).toBe("reconnecting");
    expect(closed.orderEntry.reason).toBe("shutdown_pending");
    const back = reduce(reduce(closed, connecting), authOk(OFF));
    expect(back.orderEntry).toEqual({ enabled: true, reason: null });
    expect(back.shutdown).toBeNull();
  });
});

describe("in-place re-auth (23 4.1)", () => {
  it("refreshes the kill switch and keeps the connection quality and the system stream", () => {
    const degraded = run(authOk(OFF), stream("live"), quality("saturated"));
    const again = reduce(degraded, authOk(ON));
    expect(again).toMatchObject({ transport: "degraded:saturated", systemStream: "live" });
    expect(again.killSwitch.state).toBe("engaged");
    expect(again.transitionSeq).toBe(degraded.transitionSeq);
  });

  it("does not end a pending shutdown: order entry stays off until the next connection", () => {
    const again = reduce(run(authOk(OFF), shutdown), authOk(OFF));
    expect(again.transport).toBe("shutdown_pending");
    expect(again.orderEntry).toEqual({ enabled: false, reason: "shutdown_pending" });
  });

  it("starts afresh when the link was not up: quality, shutdown and stream are reset", () => {
    const worn = run(authOk(OFF), quality("saturated"), shutdown, stream("stale"), retry(1));
    expect(reduce(worn, authOk(OFF))).toMatchObject({
      transport: "connected",
      quality: "healthy",
      shutdown: null,
      systemStream: "pending",
    });
  });
});
