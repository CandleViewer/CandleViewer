import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  INTERVAL_PATTERN,
  SyncBusAssertionError,
  createSyncBus,
  isSyncPayload,
} from "../../../../src/features/workspace/sync/syncBus";
import type { SyncPayload } from "../../../../src/features/workspace/sync/types";
import { ALL_ON, busWithFrames, fakeMember, joinAll, manualFrames } from "./fakes";

const PAYLOADS: SyncPayload[] = [
  { axis: "symbol", symbol: "ETHUSDT" },
  { axis: "interval", interval: "time:60" },
  { axis: "crosshair", crosshair: 1_700_000_000_000_000 },
  { axis: "timeRange", timeRange: { from: 1, to: 2 } },
  { axis: "drawings", priceLevel: 64_000 },
];

describe("SyncBus fan-out", () => {
  it.each(PAYLOADS)("fans $axis out to every other member on the next frame", (payload) => {
    const { bus, frames } = busWithFrames();
    const [p1, p2, p3] = joinAll(bus, 3);
    expect(bus.publish("p1", payload)).toBe(true);
    expect(p2?.received).toEqual([]);
    frames.run();
    expect(p2?.received).toEqual([payload]);
    expect(p3?.received).toEqual([payload]);
    expect(p1?.received).toEqual([]);
  });

  it("isolates groups: pane 3 in group B is untouched on every axis", () => {
    const { bus, frames } = busWithFrames();
    const [p1, p2] = joinAll(bus, 2, "A");
    if (p1 !== undefined) p1.symbol = "ETHUSDT"; // the origin changed first, then published
    const p3 = fakeMember("p3");
    bus.join(p3, "B");
    for (const payload of PAYLOADS) bus.publish("p1", payload);
    frames.run();
    expect(p2?.received).toHaveLength(PAYLOADS.length);
    expect(p3.received).toEqual([]);
    expect(p3.current()).toEqual({ symbol: "BTCUSDT", interval: "time:1" });
  });

  it("keeps axes independent: symbol follows, each member keeps its interval", () => {
    const { bus, frames } = busWithFrames();
    bus.setAxes("A", { ...ALL_ON, interval: false });
    const [p1, p2] = joinAll(bus, 2);
    if (p2 !== undefined) p2.interval = "time:60";
    bus.publish("p1", { axis: "symbol", symbol: "SOLUSDT" });
    bus.publish("p1", { axis: "interval", interval: "time:5" });
    frames.run();
    expect([p1?.symbol, p2?.symbol]).toEqual(["BTCUSDT", "SOLUSDT"]);
    expect(p2?.interval).toBe("time:60");
  });

  it("propagates nothing for a group with no stored flags (BQ-04: no defaults)", () => {
    const frames = manualFrames();
    const bus = createSyncBus({ dev: true, requestFrame: frames.requestFrame });
    const [, p2] = joinAll(bus, 2);
    bus.publish("p1", { axis: "crosshair", crosshair: 5 });
    frames.run();
    expect(p2?.received).toEqual([]);
    expect(bus.snapshot("A").axes.crosshair).toBe(false);
  });

  it("reaches charts only (BQ-05), and levels same-symbol charts only (D-8)", () => {
    const { bus, frames } = busWithFrames();
    const [, p2, p3] = joinAll(bus, 3);
    if (p3 !== undefined) p3.symbol = "ETHUSDT";
    const dom = fakeMember("dom1", { kind: "dom" });
    bus.join(dom, "A");
    bus.publish("p1", { axis: "drawings", priceLevel: 1 });
    bus.publish("p1", { axis: "crosshair", crosshair: 1 });
    frames.run();
    expect(p2?.received).toHaveLength(2);
    expect(p3?.received.map((p) => p.axis)).toEqual(["crosshair"]);
    expect(dom.received).toEqual([]);
  });
});

describe("SyncBus loop suppression", () => {
  it.each([
    [2, "sync"],
    [3, "sync"],
    [6, "sync"],
    [2, "late"],
    [3, "late"],
    [6, "late"],
  ] as const)("applies once, never echoes, never asserts: %i members, %s echo", (n, when) => {
    const { bus, frames } = busWithFrames();
    const members = joinAll(bus, n);
    // Every member re-emits what it was given: inside `apply`, or on a later frame.
    if (when === "sync") for (const m of members) m.onApply = (p) => void bus.publish(m.paneId, p);
    bus.publish("p1", { axis: "symbol", symbol: "ETHUSDT" });
    expect(() => frames.run()).not.toThrow();
    for (const m of members.slice(1)) {
      expect(m.received).toEqual([{ axis: "symbol", symbol: "ETHUSDT" }]);
      if (when === "late") bus.publish(m.paneId, { axis: "symbol", symbol: "ETHUSDT" });
    }
    frames.run();
    expect(members[0]?.received).toEqual([]);
    const c = bus.devCounters();
    expect(c.suppressedEchoes).toBe(n - 1);
    expect(c.reentrancyHits).toBe(0);
  });

  it.each(PAYLOADS)(
    "forgets a $axis echo after one frame: the receiver's own later publish goes",
    (p) => {
      const { bus, frames } = busWithFrames();
      const [p1] = joinAll(bus, 2);
      bus.publish("p1", p);
      frames.run(); // p2 receives the value and never echoes it
      expect(frames.run()).toBe(1); // the frame after: the echo memory expires
      expect(bus.publish("p2", p)).toBe(true);
      frames.run();
      expect(p1?.received).toEqual([p]);
      expect(frames.run()).toBe(1); // ...and stops scheduling once it is empty
      expect(frames.run()).toBe(0);
    },
  );

  it("suppresses only the echo: a third member's own update still propagates", () => {
    const { bus, frames } = busWithFrames();
    const [p1, p2, p3] = joinAll(bus, 3);
    bus.publish("p1", { axis: "crosshair", crosshair: 10 });
    frames.run();
    bus.publish("p3", { axis: "crosshair", crosshair: 20 });
    frames.run();
    expect(p1?.received).toEqual([{ axis: "crosshair", crosshair: 20 }]);
    expect(p2?.received.map((p) => p.axis)).toEqual(["crosshair", "crosshair"]);
    expect(p3?.received).toHaveLength(1);
  });

  it("fires the dev re-entrancy assertion after the frame, and every member still gets it", () => {
    const { bus, frames } = busWithFrames();
    const [, p2, p3] = joinAll(bus, 3);
    if (p2 !== undefined)
      p2.onApply = () => void bus.publish("p2", { axis: "interval", interval: "time:5" });
    bus.publish("p1", { axis: "symbol", symbol: "ETHUSDT" });
    expect(() => frames.run()).toThrow(SyncBusAssertionError);
    expect(p3?.received).toHaveLength(1);
    expect(bus.devCounters().reentrancyHits).toBe(1);
  });

  it("isolates a throwing apply: the frame finishes, counts it, then rethrows", () => {
    const said: string[] = [];
    const { bus, frames } = busWithFrames({ announce: (t) => void said.push(t) });
    const [, p2, p3] = joinAll(bus, 3);
    const q2 = fakeMember("q2");
    bus.join(fakeMember("q1"), "B");
    bus.join(q2, "B");
    if (p2 !== undefined)
      p2.apply = () => {
        throw new Error("boom");
      };
    bus.publish("p1", { axis: "symbol", symbol: "ETHUSDT" });
    bus.publish("q1", { axis: "crosshair", crosshair: 1 });
    let versions = 0;
    bus.subscribe(() => void (versions += 1));
    expect(() => frames.run()).toThrow("boom");
    expect([p3?.received.length, q2.received.length]).toEqual([1, 1]);
    expect([versions, said.length, bus.devCounters().applyErrors]).toEqual([1, 1, 1]);
  });

  it("counts re-entrancy without throwing in production", () => {
    const frames = manualFrames();
    const bus = createSyncBus({ dev: false, requestFrame: frames.requestFrame });
    bus.setAxes("A", ALL_ON);
    const [, p2] = joinAll(bus, 2);
    if (p2 !== undefined)
      p2.onApply = () => void bus.publish("p2", { axis: "crosshair", crosshair: 1 });
    bus.publish("p1", { axis: "symbol", symbol: "X" });
    expect(() => frames.run()).not.toThrow();
    expect(bus.devCounters().reentrancyHits).toBe(1);
  });
});

describe("SyncBus coalescing", () => {
  it("turns 10 updates in one frame into 1 dispatch per member, the last value", () => {
    const { bus, frames } = busWithFrames();
    const [, p2, p3] = joinAll(bus, 3);
    for (let i = 0; i < 10; i += 1) bus.publish("p1", { axis: "crosshair", crosshair: i });
    expect(frames.pending).toBe(1);
    frames.run();
    expect(p2?.received).toEqual([{ axis: "crosshair", crosshair: 9 }]);
    expect(p3?.received).toHaveLength(1);
    const c = bus.devCounters();
    expect(c.lastFrameDispatches).toBe(2);
    expect(c.coalesced).toBe(9);
  });
});

describe("SyncBus membership", () => {
  it("stops a member mid-sweep at once; the rest continue", () => {
    const { bus, frames } = busWithFrames();
    const [, p2, p3] = joinAll(bus, 3);
    if (p2 !== undefined) p2.onApply = () => bus.leave("p3");
    bus.publish("p1", { axis: "crosshair", crosshair: 1 });
    frames.run();
    expect(p3?.received).toEqual([]);
    bus.publish("p1", { axis: "crosshair", crosshair: 2 });
    frames.run();
    expect(p2?.received).toHaveLength(2);
    expect(bus.groupOf("p3")).toBeNull();
  });

  it("drops a leaving origin's queued write and moves a member between groups", () => {
    const { bus, frames } = busWithFrames();
    const [p1, p2] = joinAll(bus, 2);
    bus.publish("p1", { axis: "crosshair", crosshair: 1 });
    bus.leave("p1");
    frames.run();
    expect(p2?.received).toEqual([]);
    if (p1 !== undefined) bus.join(p1, "B");
    expect(bus.groupOf("p1")).toBe("B");
    expect(bus.publish("ghost", { axis: "crosshair", crosshair: 1 })).toBe(false);
  });

  it("leaves nothing behind after 1,000 join/leave cycles", () => {
    const { bus, frames } = busWithFrames();
    joinAll(bus, 2);
    for (let i = 0; i < 1_000; i += 1) {
      const leave = bus.join(fakeMember(`m${i}`), i % 2 === 0 ? "A" : "B");
      bus.publish(`m${i}`, { axis: "crosshair", crosshair: i });
      leave();
      leave(); // idempotent
    }
    frames.run();
    expect(bus.snapshot("A").members.map((m) => m.paneId)).toEqual(["p1", "p2"]);
    expect(bus.snapshot("B").members).toEqual([]);
  });

  it("an old leave does not remove the member's re-join", () => {
    const { bus } = busWithFrames();
    const m = fakeMember("p1");
    const leaveA = bus.join(m, "A");
    bus.join(m, "B");
    leaveA();
    expect(bus.groupOf("p1")).toBe("B");
  });
});

describe("SyncBus armed members (BQ-05)", () => {
  it("an armed chart holds a synced symbol, stays armed, and is never re-armed or replayed", () => {
    const { bus, frames } = busWithFrames();
    const armed = fakeMember("p2", { armed: true });
    bus.join(fakeMember("p1"), "A");
    bus.join(armed, "A");
    bus.publish("p1", { axis: "symbol", symbol: "ETHUSDT" });
    frames.run();
    expect(armed.symbol).toBe("BTCUSDT");
    expect(armed.armed).toBe(true);
    expect(bus.devCounters().held).toBe(1);
    armed.armed = false; // the user disarms
    frames.run();
    expect(armed.received).toEqual([]);
    bus.publish("p1", { axis: "symbol", symbol: "SOLUSDT" });
    frames.run();
    expect([armed.symbol, armed.armed]).toEqual(["SOLUSDT", false]);
  });
});

describe("SyncBus payload allow-list", () => {
  const bad: unknown[] = [
    null,
    "symbol",
    [],
    { axis: "account", account: "x" },
    { axis: "symbol", symbol: "BTC", account: "acc-1" },
    { axis: "symbol", symbol: "" },
    { axis: "symbol", symbol: "x".repeat(65) },
    { axis: "interval", interval: 1 },
    { axis: "interval", interval: "time:7" },
    { axis: "interval", interval: "tick:0500" },
    { axis: "interval", interval: "volume:0.50" },
    { axis: "crosshair", crosshair: Number.NaN },
    { axis: "crosshair", price: 1 },
    { axis: "drawings", priceLevel: "1" },
    { axis: "timeRange", timeRange: { from: 2, to: 1 } },
    { axis: "timeRange", timeRange: { from: 1, to: 2, env: "live" } },
    { axis: "timeRange", timeRange: null },
    { axis: "timeRange", timeRange: [1, 2] },
    Object.assign(Object.create({ axis: "crosshair" }) as object, { crosshair: 1, t: 5 }),
    JSON.parse('{"axis":"crosshair","t":5,"__proto__":{"x":1}}'),
    { axis: "crosshair", constructor: 1 },
  ];

  it.each(bad)("rejects %j", (payload) => {
    expect(isSyncPayload(payload)).toBe(false);
  });

  it("refuses, counts and (in dev) asserts on a payload outside the list", () => {
    const { bus, frames } = busWithFrames();
    const [, p2] = joinAll(bus, 2);
    expect(() => bus.publish("p1", { axis: "symbol", symbol: "X", env: "live" })).toThrow(
      SyncBusAssertionError,
    );
    const quiet = createSyncBus({ dev: false, requestFrame: frames.requestFrame });
    expect(quiet.publish("p1", { axis: "account" })).toBe(false);
    frames.run();
    expect(p2?.received).toEqual([]);
    expect(bus.devCounters().rejectedPayloads).toBe(1);
    expect(quiet.devCounters().rejectedPayloads).toBe(1);
  });

  it("delivers the published value, not a later mutation of the caller's object", () => {
    const { bus, frames } = busWithFrames();
    const [, p2] = joinAll(bus, 2);
    const payload = { axis: "timeRange" as const, timeRange: { from: 1, to: 2 } };
    expect(bus.publish("p1", payload)).toBe(true);
    payload.timeRange.to = 99;
    (payload as { axis: string }).axis = "symbol";
    frames.run();
    expect(p2?.received).toEqual([{ axis: "timeRange", timeRange: { from: 1, to: 2 } }]);
    expect(Object.isFrozen(p2?.received[0])).toBe(true);
    expect(Object.isFrozen((p2?.received[0] as { timeRange: object }).timeRange)).toBe(true);
  });

  it("delivers what it checked: a getter is read once, a window's symbol key is refused", () => {
    const { bus, frames } = busWithFrames();
    const [, p2] = joinAll(bus, 2);
    let reads = 0;
    const shifty = {
      axis: "crosshair",
      get crosshair(): unknown {
        reads += 1;
        return reads === 1 ? 5 : { other: 1 };
      },
    };
    expect(bus.publish("p1", shifty)).toBe(true);
    frames.run();
    expect(p2?.received).toEqual([{ axis: "crosshair", crosshair: 5 }]);
    expect(reads).toBe(1);
    const tagged = { axis: "timeRange", timeRange: { from: 1, to: 2, [Symbol("x")]: 3 } };
    expect(isSyncPayload(tagged)).toBe(false);
  });

  it("keeps the interval pattern equal to `22` PaneIntervalCode's", () => {
    const api = resolve(import.meta.dirname, "../../../../../../docs/plan/22-api-openapi.yaml");
    const yaml = readFileSync(api, "utf8");
    const quoted = /PaneIntervalCode:\n(?: {6}.*\n)*? {6}pattern: "(.*)"/.exec(yaml)?.[1];
    expect(quoted?.replaceAll("\\\\", "\\")).toBe(INTERVAL_PATTERN.source);
  });

  it.each([
    { axis: "crosshair", crosshair: null },
    ...["time:D", "heikin_ashi:240", "range:9", "delta:0.5", "renko:atr:14", "pnf:10:3"].map(
      (interval) => ({ axis: "interval", interval }),
    ),
  ])("accepts %j", (payload) => {
    expect(isSyncPayload(payload)).toBe(true);
  });
});

describe("SyncBus notifications", () => {
  it("notifies on membership, axes and symbol changes but never on the crosshair", () => {
    const { bus, frames } = busWithFrames();
    joinAll(bus, 2);
    let calls = 0;
    const off = bus.subscribe(() => void (calls += 1));
    for (let i = 0; i < 50; i += 1) {
      bus.publish("p1", { axis: "crosshair", crosshair: i });
      frames.run();
    }
    expect(calls).toBe(0);
    bus.publish("p1", { axis: "symbol", symbol: "ETHUSDT" });
    frames.run();
    bus.setAxes("A", { ...ALL_ON, drawings: false });
    bus.setAxes("A", { ...ALL_ON, drawings: false }); // unchanged: no notification
    expect(calls).toBe(2);
    const v = bus.getVersion();
    off();
    bus.leave("p2");
    expect(calls).toBe(2);
    expect(bus.getVersion()).toBe(v + 1);
  });

  it("announces once per sync-state change, every changed group in one message", () => {
    const said: string[] = [];
    const { bus, frames } = busWithFrames({ announce: (t) => void said.push(t) });
    joinAll(bus, 3);
    frames.run();
    bus.setAxes("A", { ...ALL_ON, symbol: false, interval: false, timeRange: false });
    for (const id of ["c1", "c2"]) bus.join(fakeMember(id), "C");
    frames.run();
    bus.leave("p3"); // still linked, same axes: nothing new
    frames.run();
    bus.leave("p2");
    bus.leave("p2"); // twice: one change
    frames.run();
    expect(said).toEqual([
      "Panes linked in sync group A: symbol, interval, crosshair, time range, levels.",
      "Panes linked in sync group A: crosshair, levels. " +
        "Panes linked in sync group C: symbol, interval, crosshair, time range, levels.",
      "Panes in sync group A are no longer linked.",
    ]);
  });

  it("prunes a member collected without leaving: its group no longer reads as linked", () => {
    const collected = new Set<object>();
    vi.stubGlobal(
      "WeakRef",
      class<T extends object> {
        constructor(private readonly target: T) {}
        deref = (): T | undefined => (collected.has(this.target) ? undefined : this.target);
      },
    );
    const said: string[] = [];
    const { bus, frames } = busWithFrames({ announce: (t) => void said.push(t) });
    const [, p2] = joinAll(bus, 2);
    frames.run();
    if (p2 !== undefined) collected.add(p2);
    expect(bus.snapshot("A").members.map((m) => m.paneId)).toEqual(["p1"]);
    frames.run();
    expect(said.at(-1)).toBe("Panes in sync group A are no longer linked.");
    expect(bus.groupOf("p2")).toBeNull();
  });
});

afterEach(() => void vi.unstubAllGlobals());

describe("SyncBus default frame", () => {
  it("flushes through requestAnimationFrame when present", () => {
    const queued: FrameRequestCallback[] = [];
    const raf = globalThis.requestAnimationFrame;
    globalThis.requestAnimationFrame = (cb) => queued.push(cb);
    try {
      const bus = createSyncBus({ dev: true });
      bus.setAxes("A", ALL_ON);
      const [, p2] = joinAll(bus, 2);
      bus.publish("p1", { axis: "crosshair", crosshair: 3 });
      for (const cb of queued.splice(0)) cb(0);
      expect(p2?.received).toHaveLength(1);
    } finally {
      globalThis.requestAnimationFrame = raf;
    }
  });
});
