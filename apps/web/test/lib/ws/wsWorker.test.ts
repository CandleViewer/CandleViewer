// E17-T04 S5e (ADR-0005; 23 4.1, 9.1): the shared worker's entry, run as a browser would run it: `onconnect` hands the
// port of each tab to the host, a dedicated worker serves its one port, the socket is the platform's `WebSocket`,
// and the fault channel is in the worker in development and not in production.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MAX_EARLY_MESSAGES,
  portOf,
  type MessageEndpoint,
} from "../../../src/lib/ws/port/endpoint";
import { tokenOf, URL } from "./support/connectionHarness";
import { createFakeGateway } from "./support/fakeGateway";
import { CONNECT } from "./support/hostHarness";

/** A `WebSocket` the test drives: it records what the worker does to it, and fires the events a server would. */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readonly sent: string[] = [];
  closed: { code: number; reason: string } | undefined;
  private readonly listeners = new Map<string, ((event: unknown) => void)[]>();
  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {
    FakeWebSocket.instances.push(this);
  }
  addEventListener(type: string, listener: (event: unknown) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  send(data: string): void {
    this.sent.push(data);
  }
  close(code: number, reason: string): void {
    this.closed = { code, reason };
  }
  fire(type: string, event: unknown = {}): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

/** A tab's end of a port, or a dedicated worker's scope: what `MessageEndpoint` is. */
class FakeEndpoint implements MessageEndpoint {
  readonly posted: { t: string; [key: string]: unknown }[] = [];
  transfers: Transferable[][] = [];
  onmessage: ((event: MessageEvent) => unknown) | null = null;
  postMessage(message: unknown, transfer: Transferable[]): void {
    this.posted.push(message as { t: string });
    this.transfers.push(transfer);
  }
  /** One message from the tab. */
  say(data: unknown): void {
    this.onmessage?.({ data } as MessageEvent);
  }
  of(t: string) {
    return this.posted.filter((m) => m.t === t);
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.resetModules();
  vi.stubGlobal("WebSocket", FakeWebSocket);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.doUnmock("../../../src/lib/ws/worker/faultChannel");
});

/** What a worker's global scope is an instance of: the scopes the tests enter are, a page is not. */
const workerScopes = new WeakSet<object>();
class FakeWorkerGlobalScope {
  static [Symbol.hasInstance](value: unknown): boolean {
    return typeof value === "object" && value !== null && workerScopes.has(value);
  }
}

/** Loads the entry with `scope` as the worker's global scope. */
const enter = async (scope: object): Promise<void> => {
  workerScopes.add(scope);
  vi.stubGlobal("WorkerGlobalScope", FakeWorkerGlobalScope);
  vi.stubGlobal("self", scope);
  await import("../../../src/lib/ws/worker/wsWorker");
};
const answer = (port: FakeEndpoint, req = 1) =>
  port.say({
    t: "token",
    req,
    result: { kind: "ok", accessToken: tokenOf(1), expiresAtMs: Date.now() + 600_000 },
  });

describe("a shared worker", () => {
  type Shared = { onconnect: ((event: { ports: FakeEndpoint[] }) => void) | null };
  it("registers onconnect at once, serves the port of each tab that connects, and drives the platform's socket", async () => {
    const scope: Shared & MessageEndpoint = {
      onconnect: null,
      postMessage: vi.fn(),
      onmessage: null,
    };
    await enter(scope);
    expect(scope.onconnect).toBeTypeOf("function");
    const first = new FakeEndpoint();
    const second = new FakeEndpoint();
    scope.onconnect?.({ ports: [first] });
    scope.onconnect?.({ ports: [second] });
    await vi.waitFor(() => expect([first.onmessage, second.onmessage]).not.toContain(null));
    first.say(CONNECT);
    expect(first.of("tokenRequest")).toHaveLength(1);
    second.say(CONNECT); // the same worker: one engine, one socket
    answer(first);
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    expect([socket?.url, socket?.protocols]).toEqual([URL, ["cv.v1.json"]]);
    socket?.fire("open");
    await vi.waitFor(() => expect(socket?.sent).toHaveLength(1));
    expect(JSON.parse(socket?.sent[0] ?? "{}")).toMatchObject({ t: "hello" });
    socket?.fire("message", { data: "not a frame" }); // a text message that is not one is the codec's to refuse
    socket?.fire("close", { code: 1011 });
    expect(first.of("state").at(-1)).toMatchObject({ state: { transport: "reconnecting" } });
    expect(second.of("state").at(-1)).toMatchObject({ state: { transport: "reconnecting" } });
    first.say({ t: "stop" });
    second.say({ t: "stop" });
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("closes the platform's socket when the last tab leaves, with the code and the reason the engine gives", async () => {
    const scope: Shared & MessageEndpoint = {
      onconnect: null,
      postMessage: vi.fn(),
      onmessage: null,
    };
    await enter(scope);
    const port = new FakeEndpoint();
    scope.onconnect?.({ ports: [port] });
    await vi.waitFor(() => expect(port.onmessage).not.toBeNull());
    port.say(CONNECT);
    answer(port);
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    FakeWebSocket.instances[0]?.fire("open");
    port.say({ t: "stop" });
    expect(FakeWebSocket.instances[0]?.closed).toEqual({ code: 1000, reason: "client_stop" });
  });
});

describe("a shared worker, ports", () => {
  it("serves every port a connect event carries", async () => {
    const scope = { onconnect: null, postMessage: vi.fn(), onmessage: null };
    await enter(scope);
    const ports = [new FakeEndpoint(), new FakeEndpoint(), new FakeEndpoint()];
    (scope as unknown as { onconnect: (e: { ports: FakeEndpoint[] }) => void }).onconnect({
      ports,
    });
    await vi.waitFor(() => expect(ports.map((port) => port.onmessage)).not.toContain(null));
  });
});

describe("the platform's socket", () => {
  /** What the worker sees as a `WebSocket`, with the fake gateway at the other end of it. */
  function overGateway() {
    const gateway = createFakeGateway();
    class GatewaySocket {
      private readonly listeners = new Map<string, ((event: unknown) => void)[]>();
      private readonly inner: {
        send(data: string): void;
        close(code: number, reason: string): void;
      };
      constructor(url: string, protocols: string[]) {
        const fire = (type: string, event: unknown) =>
          this.listeners.get(type)?.forEach((listener) => listener(event));
        this.inner = gateway.createSocket(url, protocols, {
          open: () => fire("open", {}),
          message: (data) => fire("message", { data }),
          close: (code) => fire("close", { code }),
        });
      }
      addEventListener(type: string, listener: (event: unknown) => void): void {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }
      send(data: string): void {
        this.inner.send(data);
      }
      close(code: number, reason: string): void {
        this.inner.close(code, reason);
      }
    }
    vi.stubGlobal("WebSocket", GatewaySocket);
    return gateway;
  }

  it("carries the protocol both ways, and the close code the engine is to judge by: connected, then a fatal close is offline", async () => {
    vi.useFakeTimers();
    const gateway = overGateway();
    const scope = Object.assign(new FakeEndpoint(), { onconnect: null as unknown });
    await enter(scope);
    const port = new FakeEndpoint();
    (scope as unknown as { onconnect: (e: { ports: FakeEndpoint[] }) => void }).onconnect({
      ports: [port],
    });
    await vi.waitFor(() => expect(port.onmessage).not.toBeNull());
    port.say(CONNECT);
    answer(port);
    await vi.advanceTimersByTimeAsync(400);
    expect(port.of("state").at(-1)).toMatchObject({ state: { transport: "connected" } }); // hello, welcome, auth and auth_ok went through it
    expect(gateway.latest.protocols).toEqual(["cv.v1.json"]);
    gateway.latest.close(4403); // forbidden: the engine does not reconnect
    expect(port.of("state").at(-1)).toMatchObject({
      state: { transport: "offline", link: { closeCode: 4403 } },
    });
    port.say({ t: "stop" });
  });

  it("hands the engine a message that is not text as it is: the codec refuses it, it is not made into text", async () => {
    vi.useFakeTimers();
    const scope = Object.assign(new FakeEndpoint(), { onconnect: null as unknown });
    await enter(scope);
    const port = new FakeEndpoint();
    (scope as unknown as { onconnect: (e: { ports: FakeEndpoint[] }) => void }).onconnect({
      ports: [port],
    });
    await vi.waitFor(() => expect(port.onmessage).not.toBeNull());
    port.say(CONNECT);
    answer(port);
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    socket?.fire("open");
    await vi.waitFor(() => expect(socket?.sent).toHaveLength(1)); // hello
    const ping = JSON.stringify({ t: "ping", id: "srv1", p: { server_ms: 1 } });
    socket?.fire("message", { data: ping });
    await vi.waitFor(() => expect(socket?.sent).toHaveLength(2)); // a text ping is answered
    socket?.fire("message", { data: { toString: () => ping } }); // an object that would read as that ping if it were made into text
    await vi.advanceTimersByTimeAsync(200);
    expect(socket?.sent).toHaveLength(2);
    port.say({ t: "stop" });
  });
});

describe("a dedicated worker", () => {
  it("serves the one port it has: its own scope", async () => {
    const scope = new FakeEndpoint();
    await enter(scope);
    scope.say(CONNECT); // heard once the host is there, whenever that is
    await vi.waitFor(() => expect(scope.of("tokenRequest")).toHaveLength(1));
    answer(scope);
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    scope.say({ t: "stop" });
  });
});

describe("a dedicated worker, before its host is ready", () => {
  /** The fault channel's module is one that is not loaded until `open()` is called: the host does not exist until then. */
  function gated(): () => void {
    let open = (): void => undefined;
    const gate = new Promise<void>((resolve) => {
      open = resolve;
    });
    vi.doMock("../../../src/lib/ws/worker/faultChannel", async () => {
      await gate;
      return {
        installFaultChannel: (createSocket: unknown) => ({ createSocket, handle: vi.fn() }),
      };
    });
    return () => open();
  }

  it("takes what its tab says at once, and serves it in order once the host is there", async () => {
    const open = gated();
    const scope = new FakeEndpoint();
    await enter(scope);
    expect(scope.onmessage).not.toBeNull(); // not once the host exists
    scope.say(CONNECT);
    scope.say({ t: "consume", id: "k1", ch: "trades.BTCUSDT", pane: "p1", priority: "focused" });
    open();
    await vi.waitFor(() => expect(scope.of("tokenRequest")).toHaveLength(1)); // the connect was heard
    await vi.waitFor(() => expect(scope.of("data")).toHaveLength(1)); // and the consume after it, which needs the connect
    scope.say({ t: "stop" });
  });

  it("keeps the first 128 messages and counts the rest: a count in the log, and not what they said", async () => {
    const open = gated();
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const scope = new FakeEndpoint();
    await enter(scope);
    scope.say(CONNECT);
    for (let i = 0; i < MAX_EARLY_MESSAGES + 2; i += 1)
      scope.say({ t: "visibility", hidden: false });
    open();
    await vi.waitFor(() =>
      expect(log).toHaveBeenCalledExactlyOnceWith(
        "wsWorker: 3 message(s) refused before the host was ready",
      ),
    );
    expect(scope.of("tokenRequest")).toHaveLength(1);
    scope.say({ t: "stop" });
    log.mockRestore();
  });
});

describe("a page", () => {
  it("is refused: the entry throws and takes no port, so what is posted to a page is not a tab's message", async () => {
    const page = new FakeEndpoint(); // a window has an `onmessage` and no `onconnect`
    vi.stubGlobal("self", page);
    await expect(import("../../../src/lib/ws/worker/wsWorker")).rejects.toThrow("on a page"); // it has no WorkerGlobalScope
    vi.resetModules();
    vi.stubGlobal("WorkerGlobalScope", FakeWorkerGlobalScope); // and where there is one, a page is not an instance of it
    await expect(import("../../../src/lib/ws/worker/wsWorker")).rejects.toThrow("on a page");
    expect(page.onmessage).toBeNull();
  });
});

describe("the fault channel", () => {
  const scope = (): FakeEndpoint & { onconnect: null } =>
    Object.assign(new FakeEndpoint(), { onconnect: null });

  it("is in the worker in development: a fault message reaches it", async () => {
    const handle = vi.fn();
    vi.doMock("../../../src/lib/ws/worker/faultChannel", () => ({
      installFaultChannel: (createSocket: unknown) => ({ createSocket, handle }),
    }));
    const shared = scope();
    await enter(shared);
    const port = new FakeEndpoint();
    (shared as unknown as { onconnect: (e: { ports: FakeEndpoint[] }) => void }).onconnect({
      ports: [port],
    });
    await vi.waitFor(() => expect(port.onmessage).not.toBeNull());
    port.say(CONNECT);
    port.say({ t: "fault", command: { kind: "close", code: 1011 } });
    expect(handle).toHaveBeenCalledExactlyOnceWith({ kind: "close", code: 1011 });
    port.say({ t: "stop" });
  });

  it("is in the worker of a build made with the flag, though it is not development", async () => {
    const handle = vi.fn();
    vi.doMock("../../../src/lib/ws/worker/faultChannel", () => ({
      installFaultChannel: (createSocket: unknown) => ({ createSocket, handle }),
    }));
    vi.stubEnv("DEV", false);
    vi.stubGlobal("__CV_ALLOW_FAULT_INJECTION__", true);
    const shared = scope();
    await enter(shared);
    const port = new FakeEndpoint();
    (shared as unknown as { onconnect: (e: { ports: FakeEndpoint[] }) => void }).onconnect({
      ports: [port],
    });
    await vi.waitFor(() => expect(port.onmessage).not.toBeNull());
    port.say(CONNECT);
    port.say({ t: "fault", command: { kind: "close", code: 1011 } });
    expect(handle).toHaveBeenCalledExactlyOnceWith({ kind: "close", code: 1011 });
    port.say({ t: "stop" });
  });

  it("is not in the worker in production: its module is never loaded, and a fault message is dropped", async () => {
    let loaded = false;
    vi.doMock("../../../src/lib/ws/worker/faultChannel", () => {
      loaded = true;
      return { installFaultChannel: vi.fn() };
    });
    vi.stubEnv("DEV", false);
    vi.stubGlobal("__CV_ALLOW_FAULT_INJECTION__", false); // whatever the shell exports
    const shared = scope();
    await enter(shared);
    const port = new FakeEndpoint();
    (shared as unknown as { onconnect: (e: { ports: FakeEndpoint[] }) => void }).onconnect({
      ports: [port],
    });
    await vi.waitFor(() => expect(port.onmessage).not.toBeNull());
    port.say(CONNECT);
    port.say({ t: "fault", command: { kind: "close", code: 1011 } });
    port.say({ t: "stop" });
    expect(loaded).toBe(false);
  });

  it("a channel that cannot be loaded leaves each tab unserved, with a count in the log and not the error", async () => {
    vi.doMock("../../../src/lib/ws/worker/faultChannel", () => {
      throw new Error("no channel for wss://secret.test");
    });
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const shared = scope();
    await enter(shared);
    (shared as unknown as { onconnect: (e: { ports: FakeEndpoint[] }) => void }).onconnect({
      ports: [new FakeEndpoint(), new FakeEndpoint()],
    });
    await vi.waitFor(() => expect(log).toHaveBeenCalledTimes(2));
    expect(log.mock.calls.map(([line]) => line)).toEqual([
      "wsWorker: 1 tab(s) not served",
      "wsWorker: 2 tab(s) not served",
    ]);
    log.mockRestore();
  });

  it("the same for a dedicated worker: its one port is left unserved, with a count", async () => {
    vi.doMock("../../../src/lib/ws/worker/faultChannel", () => {
      throw new Error("no channel for wss://secret.test");
    });
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await enter(new FakeEndpoint());
    await vi.waitFor(() =>
      expect(log).toHaveBeenCalledExactlyOnceWith("wsWorker: 1 tab(s) not served"),
    );
    log.mockRestore();
  });
});

describe("a port", () => {
  it("posts with the buffers to transfer, and listens by taking the data of each message", () => {
    const endpoint = new FakeEndpoint();
    const port = portOf(endpoint);
    const buffer = new ArrayBuffer(8);
    port.postMessage({ t: "x" }, [buffer]);
    expect(endpoint.posted).toEqual([{ t: "x" }]);
    expect(endpoint.transfers).toEqual([[buffer]]);
    const heard: unknown[] = [];
    port.listen((data) => heard.push(data));
    endpoint.say({ t: "hello" });
    expect(heard).toEqual([{ t: "hello" }]);
  });
});
