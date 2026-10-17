// E17-T04 S1b (C12, WS-E06): the transport/kill-switch/order-entry state, driven only by `reduce`.
// `reducer.sweep.test.ts` checks the rules over every reachable state and event.
import { describe, expect, it } from "vitest";
import type { KillSwitchPayload } from "../../../src/lib/ws/protocol/frames";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { EngineEvent, WsState } from "../../../src/lib/ws/state/types";
import {
  OFF,
  ON,
  assertEngineOrder,
  authOk,
  connecting,
  killSwitch,
  notice,
  offline,
  quality,
  retry,
  shutdown,
  stream,
  wire,
} from "./support/engineEvents";

/** Runs events an engine could emit: a scenario cannot lean on an order S4 promises never to produce. */
const run = (...events: EngineEvent[]): WsState => {
  assertEngineOrder(events);
  return events.reduce(reduce, INITIAL_WS_STATE);
};

describe("transport states", () => {
  it("moves transitionSeq once per change of transport, never per event", () => {
    const steps: [EngineEvent, number][] = [
      [authOk(OFF), 1],
      [quality("lagging"), 2],
      [quality("lagging"), 2],
      [quality("saturated"), 3], // degraded:lagging -> degraded:saturated is a change of row
      [retry(1), 4],
      [retry(2), 4],
      [offline, 5],
      [{ type: "offline", cause: "fatal", closeCode: 4403 }, 5], // the cause is not a new row
      [connecting, 6],
      [authOk(OFF), 7],
      [shutdown, 8],
      [authOk(OFF), 8], // an in-place re-auth is not a transition
    ];
    let state = INITIAL_WS_STATE;
    for (const [event, seq] of steps) {
      state = reduce(state, event);
      expect(state.transitionSeq).toBe(seq);
    }
  });

  it("reads overflowing as saturated and ignores an unknown class, a prototype key included", () => {
    expect(run(authOk(OFF), quality("overflowing")).transport).toBe("degraded:saturated");
    const lagging = run(authOk(OFF), quality("lagging"));
    const odd = ["odd", "__proto__", "constructor", "toString", "hasOwnProperty", 3, null, {}];
    for (const wireClass of [...odd, undefined]) {
      expect(reduce(lagging, quality(wireClass))).toBe(lagging);
      expect(run(authOk(OFF), quality(wireClass)).transport).toBe("connected");
    }
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

  it("WS-E06 (Q6): unknown, never not-killed, while the transport is down or the system stream resyncs", () => {
    const live = run(authOk(ON));
    expect(live.killSwitch.state).toBe("engaged");
    for (const down of [reduce(live, retry(1)), reduce(live, offline)]) {
      expect(down.killSwitch).toEqual({ state: "unknown" });
      expect(down.orderEntry).toEqual({ enabled: false, reason: "kill_switch_unknown" });
    }
    const resyncing = reduce(run(authOk(OFF)), stream("resyncing"));
    expect(resyncing.killSwitch).toEqual({ state: "unknown" });
    // The value the gap may have invalidated is not resurrected when the stream comes back.
    const live2 = reduce(resyncing, stream("live"));
    expect(live2.killSwitch.state).toBe("unknown");
    expect(reduce(live2, killSwitch(OFF)).orderEntry.enabled).toBe(true);
  });

  it("takes a kill-switch fact only while the system stream is pending or live", () => {
    for (const status of ["resyncing", "stale", "revoked"] as const) {
      const gap = reduce(run(authOk(OFF)), stream(status));
      // Out of order on purpose: the fact arrives before `live` and is dropped, not queued.
      expect(reduce(gap, killSwitch(OFF)).killSwitch.state).toBe("unknown");
    }
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
    ["a non-array account list", { engaged: false, scope: "accounts", exchange_account_ids: "a" }],
    ["a non-string account id", { engaged: false, scope: "accounts", exchange_account_ids: [1] }],
    ["a mixed account list", { engaged: false, scope: "accounts", exchange_account_ids: ["a", 1] }],
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
    expect(pending.shutdown).toEqual({ closingInMs: 5000, expectedDowntimeMs: 2e4 });
    expect(pending.transport).toBe("shutdown_pending");
    expect(pending.orderEntry).toEqual({ enabled: false, reason: "shutdown_pending" });
    const back = run(authOk(OFF), shutdown, retry(1), connecting, authOk(OFF));
    expect(back.orderEntry).toEqual({ enabled: true, reason: null });
    expect(back.shutdown).toBeNull();
  });
});

describe("in-place re-auth (23 4.1) and a new socket's auth_ok", () => {
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

  it("keeps the last kill switch when a re-auth carries none, and drops it when it is malformed", () => {
    const engaged = run(authOk(ON));
    expect(reduce(engaged, authOk())).toBe(engaged);
    const bad = reduce(engaged, authOk(wire({ engaged: "yes", scope: "global" })));
    expect(bad.killSwitch).toEqual({ state: "unknown" });
    expect(bad.orderEntry).toEqual({ enabled: false, reason: "kill_switch_unknown" });
    expect(run(authOk()).killSwitch).toEqual({ state: "unknown" }); // a new socket has no last fact
  });

  it("ignores an auth_ok after reconnecting or offline: only connecting announces a new socket", () => {
    const lost = run(authOk(OFF), shutdown, retry(1));
    // Out of order on purpose: no `connecting` came before the `auth_ok`.
    expect(reduce(lost, authOk(OFF))).toBe(lost);
    expect(lost.orderEntry).toEqual({ enabled: false, reason: "shutdown_pending" });
    const fatal = reduce(lost, { type: "offline", cause: "fatal", closeCode: 4403 });
    expect(reduce(fatal, authOk(OFF))).toBe(fatal);
    expect(fatal.transport).toBe("offline");
  });
});

describe("total over the wire, and frozen", () => {
  it("ignores a system update that is not an object", () => {
    const live = run(authOk(OFF));
    for (const update of [null, undefined, [], 7, "x"]) {
      expect(reduce(live, { type: "system", update: wire(update) })).toBe(live);
    }
  });

  it("keeps only finite numbers of a shutdown countdown, and never recurses into the payload", () => {
    let deep: unknown = 1;
    for (let i = 0; i < 10_000; i += 1) deep = { deep };
    const countdown = (v: unknown) => notice({ closing_in_ms: v, expected_downtime_ms: v });
    const vetted = { closingInMs: undefined, expectedDowntimeMs: undefined };
    for (const junk of [deep, Number.NaN, Infinity, -Infinity, "5", null, [5]]) {
      const pending = run(authOk(OFF), countdown(junk));
      expect(pending.shutdown).toStrictEqual(vetted);
      expect(reduce(pending, countdown(junk))).toBe(pending); // a copied payload would overflow isSame
    }
    const real = run(authOk(OFF), countdown(30)).shutdown;
    expect(real).toEqual({ closingInMs: 30, expectedDowntimeMs: 30 });
  });

  it("freezes the initial state, the unknown kill switch and every state it returns", () => {
    const lost = run(authOk(ON), retry(1)); // its kill switch is the shared unknown view
    for (const state of [INITIAL_WS_STATE, lost, run(authOk(OFF))]) {
      expect(() => Object.assign(state.orderEntry, { enabled: true })).toThrow(TypeError);
      expect(() => Object.assign(state.killSwitch, { state: "disengaged" })).toThrow(TypeError);
    }
    expect(lost.killSwitch).toEqual({ state: "unknown" }); // the write attempts left no mark
    expect(run(offline).orderEntry.enabled).toBe(false);
  });
});

describe("assertEngineOrder (the two promises S4 keeps)", () => {
  it("accepts what an engine emits; rejects a new socket without connecting and a fact before live", () => {
    const legal = [
      [authOk(OFF), shutdown, retry(1), connecting, authOk(OFF)],
      [authOk(OFF), authOk(ON)], // an in-place re-auth
      [authOk(OFF), stream("resyncing"), retry(1), connecting, authOk(OFF), killSwitch(ON)],
      [authOk(OFF), stream("resyncing"), stream("live"), killSwitch(ON)],
    ];
    for (const events of legal) expect(() => assertEngineOrder(events)).not.toThrow();
    const broken: [EngineEvent[], RegExp][] = [
      [[authOk(OFF), retry(1), authOk(OFF)], /auth_ok after reconnecting/],
      [[offline, authOk(OFF)], /auth_ok after offline/],
      [[authOk(OFF), stream("resyncing"), killSwitch(OFF)], /report live first/],
      [[authOk(OFF), stream("stale"), shutdown], /report live first/],
    ];
    for (const [events, message] of broken) {
      expect(() => assertEngineOrder(events)).toThrow(message);
    }
  });
});
