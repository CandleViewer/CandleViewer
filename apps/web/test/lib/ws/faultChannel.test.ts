// E17-T04 S5e (23 4.4, 8.3, 9.4, 9.5; C7, C12; WS-E06): the dev-only fault-injection channel, through the host and the
// engine against the fake gateway. What it injects goes through the engine like anything from the socket, so each of
// the six transport states can be forced and reaches the state every tab sees once; what it must not do is make
// the engine see a gap it did not cause.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  FAULT_INJECTION_SENTINEL,
  installFaultChannel,
  parseFaultCommand,
  type FaultChannel,
} from "../../../src/lib/ws/worker/faultChannel";
import type { SocketEvents } from "../../../src/lib/ws/core/connection";
import { b64, bookSnapshot } from "./support/cvwb";
import { BOOK } from "./support/engineHarness";
import { hostHarness, type FakeTab } from "./support/hostHarness";

afterEach(() => vi.useRealTimers());

/** A host over the fake gateway with the channel between the engine and the socket, and a tab that is in. */
async function faulted(options: Parameters<typeof hostHarness>[0] = {}) {
  // the host calls these only once a tab has connected, which is after `channel` exists
  const t = hostHarness(options, {
    createSocket: (url, protocols, events) => channel.createSocket(url, protocols, events),
    fault: (command) => channel.handle(command),
  });
  const channel: FaultChannel = installFaultChannel(t.gateway.createSocket);
  const a = t.tab();
  t.consume(a, "k1", BOOK);
  await t.advance(400);
  const fault = (command: unknown) => a.say({ t: "fault", command });
  return { t, a, fault, conn: t.gateway.latest };
}
const stateOf = (tab: FakeTab) => tab.last("state").state;

describe("each transport state can be forced through the channel (E17-D02 state half)", () => {
  it("Connection chrome matches the design (state half): the six states each reach the state with transitionSeq +1, once", async () => {
    const { t, a, fault } = await faulted();
    expect(stateOf(a).transport).toBe("connected");
    /** `quiet`: how long after it nothing may announce it again (a reconnect is a transition of its own, 500 ms on). */
    const forced = async (command: object, transport: string, quiet = 1_000) => {
      const before = { seq: stateOf(a).transitionSeq, messages: a.of("state").length };
      fault(command);
      await t.advance(100);
      expect(stateOf(a).transport).toBe(transport);
      expect(stateOf(a).transitionSeq).toBe(before.seq + 1);
      expect(a.of("state")).toHaveLength(before.messages + 1); // told once
      await t.advance(quiet); // no heartbeat, ping or reply announces it again
      expect(stateOf(a).transitionSeq).toBe(before.seq + 1);
    };
    await forced({ kind: "quality", class: "lagging" }, "degraded:lagging");
    await forced({ kind: "quality", class: "saturated" }, "degraded:saturated");
    await forced({ kind: "shutdown", closingInMs: 5_000, downtimeMs: 20_000 }, "shutdown_pending");
    await forced({ kind: "close", code: 1011 }, "reconnecting", 300);
    await t.advance(3_000); // the next socket: connecting, then connected again
    expect(stateOf(a).transport).toBe("connected");
    await forced({ kind: "close", code: 4403 }, "offline"); // forbidden: no reconnect
    expect(stateOf(a).link).toMatchObject({ kind: "offline", cause: "fatal", closeCode: 4403 });
  });

  it("the kill switch it injects disables order entry in the task it is injected in", async () => {
    const { a, fault } = await faulted();
    expect(stateOf(a).orderEntry.enabled).toBe(true);
    fault({ kind: "killSwitch", engaged: true });
    expect(stateOf(a).orderEntry).toEqual({ enabled: false, reason: "kill_switch_engaged" });
    fault({ kind: "killSwitch", engaged: false });
    expect(stateOf(a).orderEntry.enabled).toBe(true);
  });

  it("marks what it injects with the sentinel, and closes with it as the reason", async () => {
    expect(FAULT_INJECTION_SENTINEL).toBe("cv-ws-fault-injection"); // the production bundle is searched for exactly this
    const { t, a, fault, conn } = await faulted();
    fault({ kind: "shutdown", closingInMs: 1_000, downtimeMs: 2_000 });
    expect(a.last("system").update).toMatchObject({
      kind: "shutdown_notice",
      reason: FAULT_INJECTION_SENTINEL,
    });
    fault({ kind: "close", code: 1011 });
    expect(conn.closedByClient).toEqual({ code: 1000, reason: FAULT_INJECTION_SENTINEL });
    await t.advance(100);
  });
});

describe("what it injects is the server's to the engine", () => {
  it("injected frames take numbers, and the real ones after them move up, so the engine sees no gap", async () => {
    const { t, a, fault, conn } = await faulted();
    fault({ kind: "quality", class: "lagging" });
    fault({ kind: "quality", class: "healthy" });
    conn.delta("system", { kind: "notice", message: "real" });
    conn.delta("system", { kind: "kill_switch", kill_switch: { engaged: true, scope: "global" } });
    await t.advance(200);
    expect(conn.of("resync")).toEqual([]); // not a gap
    expect(stateOf(a).orderEntry).toEqual({ enabled: false, reason: "kill_switch_engaged" }); // and applied
    expect(a.of("system").map((m) => m.update.kind)).toEqual([
      "health",
      "connection_quality",
      "connection_quality",
      "notice",
      "kill_switch",
    ]);
  });

  it("a stale snapshot makes the stream read stale, and the real frames after it continue it", async () => {
    const { t, a, fault, conn } = await faulted();
    fault({ kind: "staleSnap", ch: BOOK });
    await t.advance(20);
    expect(a.last("data").status).toBe("stale");
    conn.delta(BOOK);
    await t.advance(20);
    expect(a.frames("k1")).toEqual(["snap:1", "snap:2", "d:3"]);
    expect(conn.of("resync")).toEqual([]);
  });

  it("a stale snapshot of a stream with no baseline is nothing, and neither is one for a binary snapshot", async () => {
    const { t, a, fault, conn } = await faulted();
    fault({ kind: "staleSnap", ch: "trades.BTCUSDT" }); // not subscribed
    conn.snap(BOOK, "client_resync", undefined, { e: "b64", p: b64(bookSnapshot()) });
    fault({ kind: "staleSnap", ch: BOOK }); // its last body is bytes: there is nothing to make stale
    await t.advance(20);
    expect(a.frames("k1")).toEqual(["snap:1", "snap:2"]);
  });

  it("a revocation ends the stream it names", async () => {
    const { t, a, fault } = await faulted();
    fault({ kind: "revoke", ch: BOOK, reason: "permission_revoked" });
    await t.advance(20);
    expect(a.frames("k1")).toEqual(["snap:1", "reset:revoked"]);
    expect(a.last("data").status).toBe("revoked");
  });

  it("drops the next delta of a topic: the engine sees a gap and asks for a snapshot (C2)", async () => {
    const { t, a, fault, conn } = await faulted();
    fault({ kind: "drop", ch: BOOK });
    conn.delta(BOOK); // never seen
    conn.delta(BOOK); // 3 after 1: a gap
    await t.advance(200);
    expect(conn.of("resync")).toEqual([
      expect.objectContaining({ ch: BOOK, p: expect.objectContaining({ reason: "sequence_gap" }) }),
    ]);
    expect(a.frames("k1")).toEqual(["snap:1", "snap:4"]); // the reset and the snapshot came inside one window: the snapshot replaced it
    conn.delta(BOOK); // only the next one was dropped
    await t.advance(20);
    expect(a.frames("k1").at(-1)).toBe("d:5");
  });

  it("delays what the server says, in order, until it is told to stop", async () => {
    const { t, a, fault, conn } = await faulted();
    fault({ kind: "delay", ms: 500 });
    conn.delta(BOOK);
    conn.delta(BOOK);
    await t.advance(450);
    expect(a.frames("k1")).toEqual(["snap:1"]);
    await t.advance(100);
    expect(a.frames("k1")).toEqual(["snap:1", "d:2", "d:3"]);
    fault({ kind: "delay", ms: 0 });
    conn.delta(BOOK);
    await t.advance(8);
    expect(a.frames("k1")).toEqual(["snap:1", "d:2", "d:3", "d:4"]);
  });

  it.each([0, 100])(
    "keeps the order, and makes no gap, when the delay is lowered to %i ms while frames wait",
    async (ms) => {
      const { t, a, fault, conn } = await faulted();
      fault({ kind: "delay", ms: 500 });
      for (let i = 0; i < 3; i += 1) conn.delta(BOOK);
      fault({ kind: "delay", ms });
      conn.delta(BOOK); // not before the three that wait
      await t.advance(600);
      expect(a.frames("k1")).toEqual(["snap:1", "d:2", "d:3", "d:4", "d:5"]);
      expect(conn.of("resync")).toEqual([]); // the engine saw no gap
    },
  );

  it("a frame that is delayed past the close of its socket is never delivered", async () => {
    const { t, a, fault, conn } = await faulted();
    fault({ kind: "delay", ms: 500 });
    conn.delta(BOOK);
    fault({ kind: "close", code: 4403 });
    await t.advance(1_000);
    expect(a.frames("k1")).toEqual(["snap:1", "reset:reconnect"]);
  });

  it("a message that is not JSON, and a frame with no stream, pass through untouched for the engine to judge", async () => {
    const { t, a, conn } = await faulted();
    conn.raw("not json");
    conn.send({ t: "pong", id: "x", p: {} });
    await t.advance(1_100);
    expect(a.last("diag").diag.engine.malformedFrames).toBe(1); // the first, and only the first, is the engine's refusal
  });
});

describe("the channel against a socket it can see", () => {
  /** The channel over a fake socket: what the engine would hear (`events`), and what the real socket would say (`server`). */
  function rig() {
    const events = { open: vi.fn(), message: vi.fn(), close: vi.fn() };
    const socket = { send: vi.fn(), close: vi.fn() };
    let server: SocketEvents | undefined;
    const channel = installFaultChannel((_url, _protocols, handlers) => {
      server = handlers;
      return socket;
    });
    channel.createSocket("wss://cv.test/api/v1/ws", ["cv.v1.json"], events);
    if (server === undefined) throw new Error("no socket was made");
    return { channel, events, socket, server };
  }

  it("lets nothing more through once it ended the connection: not a late open or close of the real socket, not a message, not another command", () => {
    const { channel, events, socket, server } = rig();
    channel.handle({ kind: "close", code: 1011 });
    expect(socket.close).toHaveBeenCalledExactlyOnceWith(1000, FAULT_INJECTION_SENTINEL);
    server.open();
    server.message(JSON.stringify({ t: "d", ch: BOOK, s: 5, ts: 1, e: "j", p: {} }));
    server.close(1000); // the answer of the real socket to the close the channel asked for
    channel.handle({ kind: "close", code: 1012 });
    channel.handle({ kind: "quality", class: "lagging" });
    channel.handle({ kind: "revoke", ch: BOOK, reason: "permission_revoked" });
    expect(events.open).not.toHaveBeenCalled();
    expect(events.message).not.toHaveBeenCalled();
    expect(events.close).toHaveBeenCalledExactlyOnceWith(1011);
    expect(socket.close).toHaveBeenCalledTimes(1);
  });

  it("passes the real socket's open, messages and close on while it has not ended it", () => {
    const { events, server } = rig();
    server.open();
    server.message("text");
    server.close(1006);
    expect(events.open).toHaveBeenCalledTimes(1);
    expect(events.message).toHaveBeenCalledExactlyOnceWith("text");
    expect(events.close).toHaveBeenCalledExactlyOnceWith(1006);
  });

  it("marks a revocation with the sentinel, and names the stream and the reason it was given", () => {
    const { channel, events } = rig();
    channel.handle({ kind: "revoke", ch: BOOK, reason: "permission_revoked" });
    const [text] = events.message.mock.calls[0] as [string];
    expect(JSON.parse(text)).toEqual({
      t: "revoked",
      ch: BOOK,
      p: { reason: "permission_revoked", message: FAULT_INJECTION_SENTINEL },
    });
  });

  it("marks every frame it injects with the sentinel, in the field of the protocol that can carry it", () => {
    const { channel, events, server } = rig();
    server.message(JSON.stringify({ t: "snap", ch: BOOK, s: 1, ts: 1, e: "j", p: { levels: [] } }));
    const injected = (command: object): Record<string, unknown> => {
      events.message.mockClear();
      channel.handle(command);
      return JSON.parse((events.message.mock.calls[0] as [string])[0]) as Record<string, unknown>;
    };
    expect(injected({ kind: "quality", class: "lagging" })["p"]).toMatchObject({
      message: FAULT_INJECTION_SENTINEL,
    });
    expect(injected({ kind: "shutdown", closingInMs: 1, downtimeMs: 1 })["p"]).toMatchObject({
      reason: FAULT_INJECTION_SENTINEL,
      message: FAULT_INJECTION_SENTINEL,
    });
    expect(injected({ kind: "killSwitch", engaged: true })["p"]).toMatchObject({
      kill_switch: { reason: FAULT_INJECTION_SENTINEL },
    });
    expect(injected({ kind: "staleSnap", ch: BOOK })["meta"]).toMatchObject({
      reason: FAULT_INJECTION_SENTINEL,
    });
  });

  it("delivers what it delayed in the order the server said it, though the delay was lowered while it waited", () => {
    vi.useFakeTimers();
    const { channel, events, server } = rig();
    channel.handle({ kind: "delay", ms: 500 });
    server.message("first");
    channel.handle({ kind: "delay", ms: 100 });
    server.message("second");
    channel.handle({ kind: "delay", ms: 0 });
    server.message("third");
    vi.advanceTimersByTime(499);
    expect(events.message).not.toHaveBeenCalled(); // none overtakes the first, which is due at 500
    vi.advanceTimersByTime(1);
    expect(events.message.mock.calls.map(([data]) => data)).toEqual(["first", "second", "third"]);
  });

  it("keeps the order when a timer is late: a frame that finds the clock at the due time of one still waiting waits too", () => {
    vi.useFakeTimers();
    const { channel, events, server } = rig();
    channel.handle({ kind: "delay", ms: 100 });
    server.message("first");
    vi.setSystemTime(Date.now() + 100); // its time has come, its timer has not run
    channel.handle({ kind: "delay", ms: 0 });
    server.message("second");
    vi.runAllTimers();
    expect(events.message.mock.calls.map(([data]) => data)).toEqual(["first", "second"]);
  });

  it("never delivers a frame it delayed past the close it made: the engine's own guard is not what stops it", () => {
    vi.useFakeTimers();
    const { channel, events, server } = rig();
    channel.handle({ kind: "delay", ms: 500 });
    server.message("late");
    channel.handle({ kind: "close", code: 1011 });
    vi.advanceTimersByTime(1_000);
    expect(events.message).not.toHaveBeenCalled();
  });
});

describe("the channel takes only commands of its list", () => {
  const VALID: [string, unknown][] = [
    ["close", { kind: "close", code: 1011 }],
    ["drop", { kind: "drop", ch: BOOK }],
    ["delay", { kind: "delay", ms: 250 }],
    ["quality", { kind: "quality", class: "overflowing" }],
    ["shutdown", { kind: "shutdown", closingInMs: 0, downtimeMs: 60_000 }],
    [
      "shutdown of an hour and an hour",
      { kind: "shutdown", closingInMs: 3_600_000, downtimeMs: 3_600_000 },
    ],
    ["killSwitch", { kind: "killSwitch", engaged: true }],
    ["revoke", { kind: "revoke", ch: BOOK, reason: "permission_revoked" }],
    ["staleSnap", { kind: "staleSnap", ch: BOOK }],
  ];
  it.each(VALID)("%s is a command", (_name, command) => {
    expect(parseFaultCommand(command)).toEqual(command);
  });

  const REFUSED: [string, unknown][] = [
    ["null", null],
    ["a string", "close"],
    ["an unknown kind", { kind: "explode" }],
    ["a close code below 1000", { kind: "close", code: 999 }],
    ["a close code above 4999", { kind: "close", code: 5000 }],
    ["a fractional close code", { kind: "close", code: 1011.5 }],
    ["a drop of a topic that is not one", { kind: "drop", ch: "Not A Topic" }],
    ["a delay over a minute", { kind: "delay", ms: 60_001 }],
    ["a negative delay", { kind: "delay", ms: -1 }],
    ["a connection class that does not exist", { kind: "quality", class: "dead" }],
    ["a shutdown with no countdown", { kind: "shutdown", closingInMs: 1_000 }],
    ["a shutdown countdown of a day", { kind: "shutdown", closingInMs: 86_400_000, downtimeMs: 1 }],
    [
      "a shutdown that closes in over an hour",
      { kind: "shutdown", closingInMs: 3_600_001, downtimeMs: 1 },
    ],
    [
      "a shutdown that lasts over an hour",
      { kind: "shutdown", closingInMs: 1, downtimeMs: 3_600_001 },
    ],
    ["a kill switch that is not a boolean", { kind: "killSwitch", engaged: "yes" }],
    ["a revocation with no reason", { kind: "revoke", ch: BOOK, reason: "" }],
    [
      "a revocation reason over 64 characters",
      { kind: "revoke", ch: BOOK, reason: "r".repeat(65) },
    ],
    ["a stale snapshot of a topic that is not one", { kind: "staleSnap", ch: "" }],
  ];
  it.each(REFUSED)("refuses %s", (_name, command) => {
    expect(parseFaultCommand(command)).toBeUndefined();
  });

  it("does nothing with a command it refuses, with a command that needs a socket when there is none, or after the socket ended", async () => {
    const { t, a, fault, conn } = await faulted();
    const before = a.of("state").length;
    for (const command of [null, { kind: "close", code: 5 }, { kind: "quality", class: "dead" }]) {
      fault(command);
    }
    await t.advance(1_000);
    expect([a.of("state").length, t.gateway.conns.length]).toEqual([before, 1]);
    fault({ kind: "close", code: 4403 }); // ended
    fault({ kind: "close", code: 1011 }); // nothing left to close
    fault({ kind: "quality", class: "lagging" }); // nothing left to speak through
    await t.advance(100);
    expect(a.last("state").state.transport).toBe("offline");
    expect(conn.closedByClient).toBeDefined();
  });

  it("lets the real socket's close through, once: a close after the channel ended it is not the engine's to hear again", async () => {
    const { t, a, conn } = await faulted();
    conn.close(1011);
    expect(a.last("state").state.transport).toBe("reconnecting");
    const states = a.of("state").length;
    conn.lateClose(1011); // the same socket again
    await t.advance(10);
    expect(a.of("state")).toHaveLength(states);
  });

  it("a socket that cannot be closed (it is closing already) still ends the connection for the engine", () => {
    const events = { open: vi.fn(), message: vi.fn(), close: vi.fn() };
    const channel = installFaultChannel(() => ({
      send: vi.fn(),
      close: () => {
        throw new Error("already closing");
      },
    }));
    channel.createSocket("wss://cv.test/api/v1/ws", ["cv.v1.json"], events);
    channel.handle({ kind: "close", code: 1011 });
    expect(events.close).toHaveBeenCalledExactlyOnceWith(1011);
  });

  it("does nothing before a socket exists", () => {
    const channel = installFaultChannel(() => ({ send: vi.fn(), close: vi.fn() }));
    expect(() => channel.handle({ kind: "close", code: 1011 })).not.toThrow();
    expect(() => channel.handle({ kind: "quality", class: "lagging" })).not.toThrow();
  });
});
