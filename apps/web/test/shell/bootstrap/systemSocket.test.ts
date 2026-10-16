import { describe, expect, it, vi } from "vitest";
import { SystemSocket, isSystemUpdate } from "../../../src/shell/bootstrap/systemSocket.js";

class FakeWebSocket extends EventTarget {
  static instances: FakeWebSocket[] = [];
  sent: string[] = [];
  closed = false;

  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {
    super();
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
    this.dispatchEvent(new Event("close"));
  }

  emitOpen(): void {
    this.dispatchEvent(new Event("open"));
  }

  emitMessage(data: string): void {
    this.dispatchEvent(new MessageEvent("message", { data }));
  }

  emitClose(): void {
    this.dispatchEvent(new Event("close"));
  }
}

describe("isSystemUpdate", () => {
  it("accepts a payload with a recognised kind", () => {
    expect(isSystemUpdate({ kind: "health", health: "healthy" })).toBe(true);
  });

  it("rejects a payload with an unrecognised kind", () => {
    expect(isSystemUpdate({ kind: "bogus" })).toBe(false);
  });

  it("rejects non-object payloads", () => {
    expect(isSystemUpdate(null)).toBe(false);
    expect(isSystemUpdate("health")).toBe(false);
  });
});

describe("SystemSocket", () => {
  it("reports connecting then live, and delivers a system update frame", () => {
    FakeWebSocket.instances = [];
    const events: unknown[] = [];
    const updates: unknown[] = [];
    const socket = new SystemSocket({
      url: "wss://localhost/api/v1/ws",
      createSocket: (url, protocols) => new FakeWebSocket(url, protocols) as unknown as WebSocket,
      callbacks: {
        onConnectionChange: (state) => events.push(state),
        onSystemUpdate: (update) => updates.push(update),
      },
    });
    socket.connect();
    expect(events).toEqual([{ kind: "connecting" }]);

    const fake = FakeWebSocket.instances[0]!;
    fake.emitOpen();
    expect(events).toEqual([{ kind: "connecting" }, { kind: "live" }]);

    fake.emitMessage(
      JSON.stringify({
        t: "d",
        ch: "system",
        s: 1,
        ts: 1,
        e: "j",
        p: { kind: "health", health: "degraded" },
      }),
    );
    expect(updates).toEqual([{ kind: "health", health: "degraded" }]);
    socket.stop();
  });

  // #2483: the server picks `cv.v1.msgpack` whenever it is offered, and this client decodes only
  // JSON text frames, so every connection it opens must offer `cv.v1.json` alone.
  it("offers only cv.v1.json, on the first connect and on a reconnect", () => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    const socket = new SystemSocket({
      url: "wss://localhost/api/v1/ws",
      createSocket: (url, protocols) => new FakeWebSocket(url, protocols) as unknown as WebSocket,
      random: () => 0.5,
      callbacks: { onConnectionChange: () => {}, onSystemUpdate: () => {} },
    });
    socket.connect();
    FakeWebSocket.instances[0]!.emitClose();
    vi.runOnlyPendingTimers();
    expect(FakeWebSocket.instances.map((ws) => ws.protocols)).toEqual([
      ["cv.v1.json"],
      ["cv.v1.json"],
    ]);
    socket.stop();
    vi.useRealTimers();
  });

  it("ignores frames on a channel other than system", () => {
    FakeWebSocket.instances = [];
    const updates: unknown[] = [];
    const socket = new SystemSocket({
      url: "wss://localhost/api/v1/ws",
      createSocket: (url, protocols) => new FakeWebSocket(url, protocols) as unknown as WebSocket,
      callbacks: { onConnectionChange: () => {}, onSystemUpdate: (u) => updates.push(u) },
    });
    socket.connect();
    const fake = FakeWebSocket.instances[0]!;
    fake.emitOpen();
    fake.emitMessage(
      JSON.stringify({ t: "d", ch: "orders", s: 1, ts: 1, e: "j", p: { kind: "health" } }),
    );
    expect(updates).toEqual([]);
    socket.stop();
  });

  it("ignores malformed JSON without throwing", () => {
    FakeWebSocket.instances = [];
    const socket = new SystemSocket({
      url: "wss://localhost/api/v1/ws",
      createSocket: (url, protocols) => new FakeWebSocket(url, protocols) as unknown as WebSocket,
      callbacks: { onConnectionChange: () => {}, onSystemUpdate: () => {} },
    });
    socket.connect();
    const fake = FakeWebSocket.instances[0]!;
    fake.emitOpen();
    expect(() => fake.emitMessage("not json")).not.toThrow();
    socket.stop();
  });

  it("schedules a reconnect with an increasing attempt number on close", () => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    const events: { kind: string; attempt?: number }[] = [];
    const socket = new SystemSocket({
      url: "wss://localhost/api/v1/ws",
      createSocket: (url, protocols) => new FakeWebSocket(url, protocols) as unknown as WebSocket,
      random: () => 0.5,
      callbacks: {
        onConnectionChange: (state) => events.push(state as { kind: string; attempt?: number }),
        onSystemUpdate: () => {},
      },
    });
    socket.connect();
    const first = FakeWebSocket.instances[0]!;
    first.emitClose();
    const reconnecting = events.find((e) => e.kind === "reconnecting");
    expect(reconnecting?.attempt).toBe(1);

    vi.runOnlyPendingTimers();
    expect(FakeWebSocket.instances.length).toBe(2);
    socket.stop();
    vi.useRealTimers();
  });

  it("stop() prevents further reconnects", () => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    const socket = new SystemSocket({
      url: "wss://localhost/api/v1/ws",
      createSocket: (url, protocols) => new FakeWebSocket(url, protocols) as unknown as WebSocket,
      callbacks: { onConnectionChange: () => {}, onSystemUpdate: () => {} },
    });
    socket.connect();
    socket.stop();
    const first = FakeWebSocket.instances[0]!;
    first.emitClose();
    vi.runOnlyPendingTimers();
    expect(FakeWebSocket.instances.length).toBe(1);
    vi.useRealTimers();
  });
});
