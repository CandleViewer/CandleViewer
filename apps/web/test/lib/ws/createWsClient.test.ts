// E17-T04 S5f (ADR-0005; 23 4.1; C8, C9, C11, C12): the tab's end of the port, against a fake worker. What the app sees follows
// the display, not the feed: frames wait in a bounded queue behind `read()`, what a handle reads changes on the animation frame,
// and only a change of the connection state (or a `system` update) is heard at once.
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TopicFrame } from "../../../src/lib/ws/api";
import {
  createWsClient,
  documentPage,
  HOST_WAIT_MS,
  type Page,
  type WsClientOptions,
} from "../../../src/lib/ws/client/createWsClient";
import type { PortLike } from "../../../src/lib/ws/port/endpoint";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** The worker, as the tab sees its port: what the tab posts is recorded, what the worker says is injected. */
class FakePort implements PortLike {
  readonly posted: { t: string; [key: string]: unknown }[] = [];
  readonly transfers: ArrayBuffer[][] = [];
  readonly order: string[] = [];
  private handler: ((data: unknown) => void) | undefined;
  postMessage(message: unknown, transfer: ArrayBuffer[]): void {
    this.order.push("post");
    this.posted.push(message as { t: string });
    this.transfers.push(transfer);
  }
  listen(handler: (data: unknown) => void): void {
    this.order.push("listen");
    this.handler = handler;
  }
  say(message: unknown): void {
    this.handler?.(message);
  }
  of(t: string) {
    return this.posted.filter((m) => m.t === t);
  }
}

function fakePage(hidden = false) {
  let isHidden = hidden;
  const watchers = new Set<() => void>();
  const exits = new Set<() => void>();
  const page: Page = {
    hidden: () => isHidden,
    watch: (listener) => {
      watchers.add(listener);
      return () => void watchers.delete(listener);
    },
    onExit: (listener) => {
      exits.add(listener);
      return () => void exits.delete(listener);
    },
  };
  return {
    page,
    watchers,
    exits,
    show: (value: boolean) => {
      isHidden = value;
      for (const listener of [...watchers]) listener();
    },
    leave: () => {
      for (const listener of [...exits]) listener();
    },
  };
}

/** A manual `requestAnimationFrame`: `frame()` runs what was asked for, as the display would. */
function fakeDisplay() {
  const requested = new Map<number, (frameTimeMs: number) => void>();
  let handle = 0;
  return {
    raf: (callback: (frameTimeMs: number) => void): number => {
      handle += 1;
      requested.set(handle, callback);
      return handle;
    },
    caf: (id: number): void => void requested.delete(id),
    pending: () => requested.size,
    frame: (): void => {
      const callbacks = [...requested.values()];
      requested.clear();
      for (const callback of callbacks) callback(16);
    },
  };
}

const base = { sp: undefined, decodeMs: 0.5, size: 20, meta: undefined };
const snap = (seq: number, ts = 1_000): TopicFrame => ({
  kind: "snap",
  seq,
  ts,
  ...base,
  bodies: [{ e: "j", p: {} }],
});
const delta = (seq: number, ts = 1_000): TopicFrame => ({
  kind: "d",
  seq,
  ts,
  ...base,
  body: { e: "j", p: {} },
});
const labels = (frames: readonly TopicFrame[]) =>
  frames.map((f) => (f.kind === "reset" ? `reset:${f.reason}` : `${f.kind}:${f.seq}`));
const data = (id: string, frames: TopicFrame[], over: object = {}) => ({
  t: "data",
  id,
  frames,
  status: "live",
  effective: {},
  source: "live",
  ...over,
});
const SPEC = { ch: "book.BTCUSDT.50", paneId: "p1", priority: "focused" } as const;

function rig(over: Partial<WsClientOptions> = {}) {
  vi.useFakeTimers();
  const port = new FakePort();
  const page = fakePage();
  const display = fakeDisplay();
  const systems: unknown[] = [];
  const raised: (() => void)[] = [];
  const client = createWsClient({
    wsUrl: "wss://cv.test/api/v1/ws",
    shell: "browser",
    locale: "en-GB",
    clientVersion: "1.0.0",
    port,
    page: page.page,
    raf: display.raf,
    caf: display.caf,
    onSystem: (update) => systems.push(update),
    timers: { queueMicrotask: (callback) => raised.push(callback) },
    ...over,
  });
  return { client, port, page, display, systems, raised };
}

describe("connecting", () => {
  it("listens first, then says connect and whether the page is seen", () => {
    const { port } = rig();
    expect(port.order.slice(0, 3)).toEqual(["listen", "post", "post"]);
    expect(port.posted.slice(0, 2)).toEqual([
      {
        t: "connect",
        v: 1,
        wsUrl: "wss://cv.test/api/v1/ws",
        shell: "browser",
        locale: "en-GB",
        clientVersion: "1.0.0",
      },
      { t: "visibility", hidden: false },
    ]);
    expect(port.transfers.every((transfer) => transfer.length === 0)).toBe(true);
    const hidden = rig({ page: fakePage(true).page }); // and says so when the page starts hidden
    expect(hidden.port.of("visibility")).toEqual([{ t: "visibility", hidden: true }]);
  });

  it("reads the initial state until the worker's arrives; a transition reaches each subscriber once, and is one object until the next", () => {
    const { client, port } = rig();
    expect(client.getState()).toBe(INITIAL_WS_STATE);
    const heard = vi.fn();
    const other = vi.fn();
    const stop = client.subscribe(heard);
    client.subscribe(other);
    const connected = reduce(INITIAL_WS_STATE, { type: "welcome", connectionId: "ws_1" });
    port.say({ t: "state", state: connected });
    expect([heard.mock.calls.length, other.mock.calls.length]).toEqual([1, 1]);
    expect(client.getState()).toBe(connected);
    expect(client.getState()).toBe(client.getState());
    stop();
    port.say({ t: "state", state: INITIAL_WS_STATE });
    expect([heard.mock.calls.length, other.mock.calls.length]).toEqual([1, 2]); // an unsubscribed listener hears no more
  });

  it("500 data messages notify nobody; one transition notifies once", () => {
    const { client, port, display } = rig();
    const handle = client.consume(SPEC);
    const heard = vi.fn();
    client.subscribe(heard);
    port.say(data("c1", [snap(1)]));
    for (let seq = 2; seq <= 501; seq += 1) port.say(data("c1", [delta(seq)]));
    display.frame();
    expect(heard).not.toHaveBeenCalled();
    expect(handle.read()).toHaveLength(501);
    port.say({ t: "state", state: reduce(INITIAL_WS_STATE, { type: "connecting" }) });
    expect(heard).toHaveBeenCalledTimes(1);
  });

  it("a subscriber that throws does not keep the others from hearing: its error is raised on its own", () => {
    const { client, port, raised } = rig();
    const heard = vi.fn();
    client.subscribe(() => {
      throw new Error("boom");
    });
    client.subscribe(heard);
    port.say({ t: "state", state: INITIAL_WS_STATE });
    expect(heard).toHaveBeenCalledTimes(1);
    expect(raised).toHaveLength(1);
    expect(() => raised[0]?.()).toThrow("boom");
  });

  it("a worker that does not answer in time is offline, once; an answer in time, or a late one, is the state", () => {
    const silent = rig();
    const heard = vi.fn();
    silent.client.subscribe(heard);
    vi.advanceTimersByTime(HOST_WAIT_MS - 1);
    expect(silent.client.getState().transport).toBe("connecting");
    vi.advanceTimersByTime(1);
    expect(silent.client.getState()).toMatchObject({
      transport: "offline",
      link: { cause: "fatal" },
    });
    expect(heard).toHaveBeenCalledTimes(1);
    const back = reduce(INITIAL_WS_STATE, { type: "welcome", connectionId: "ws_1" });
    silent.port.say({ t: "state", state: back });
    expect(silent.client.getState()).toBe(back);
    const prompt = rig();
    prompt.port.say({ t: "state", state: INITIAL_WS_STATE });
    vi.advanceTimersByTime(HOST_WAIT_MS * 2);
    expect(prompt.client.getState()).toBe(INITIAL_WS_STATE);
  });
});

describe("system updates", () => {
  it("reach the app the moment they arrive, in order, and one that throws is raised on its own", () => {
    const thrown = new Error("app bug");
    const systems: unknown[] = [];
    let first = true;
    const { port, raised } = rig({
      onSystem: (update) => {
        if (first) {
          first = false;
          throw thrown;
        }
        systems.push(update);
      },
    });
    port.say({ t: "system", update: { kind: "health", health: "healthy" } });
    port.say({ t: "system", update: { kind: "notice", message: "two" } });
    expect(systems).toEqual([{ kind: "notice", message: "two" }]);
    expect(() => raised[0]?.()).toThrow(thrown);
  });
});

describe("a consumer", () => {
  it("is posted with its pane, priority, options and replay session; a live one names none", () => {
    const { client, port } = rig();
    client.consume({ ...SPEC, opts: { depth: 50 } });
    client.consume(SPEC, "bb000000-0000-4000-8000-000000000001");
    expect(port.of("consume")).toEqual([
      { t: "consume", id: "c1", ch: SPEC.ch, pane: "p1", priority: "focused", opts: { depth: 50 } },
      {
        t: "consume",
        id: "c2",
        ch: SPEC.ch,
        pane: "p1",
        priority: "focused",
        rs: "bb000000-0000-4000-8000-000000000001",
      },
    ]);
  });

  it("reads pending, nothing and live until the worker says otherwise; a replay consumer reads replay", () => {
    const { client } = rig();
    const live = client.consume(SPEC);
    const replay = client.consume(SPEC, "bb000000-0000-4000-8000-000000000001");
    expect([live.ch, live.status, live.source, live.rs, live.effective, live.read()]).toEqual([
      SPEC.ch,
      "pending",
      "live",
      undefined,
      {},
      [],
    ]);
    expect([replay.source, replay.rs]).toEqual(["replay", "bb000000-0000-4000-8000-000000000001"]);
  });

  it("hands frames out of read() in order, once; what the handle reads changes on the animation frame, not on arrival", () => {
    const { client, port, display } = rig();
    const handle = client.consume(SPEC);
    port.say(data("c1", [snap(1), delta(2)], { effective: { throttle_ms: 50 } }));
    expect([handle.status, handle.effective]).toEqual(["pending", {}]); // nothing is applied from the arrival path
    expect(display.pending()).toBe(1);
    expect(labels(handle.read())).toEqual(["snap:1", "d:2"]);
    expect(handle.read()).toEqual([]); // drained
    display.frame();
    expect([handle.status, handle.effective]).toEqual(["live", { throttle_ms: 50 }]);
    port.say(data("c1", [], { status: "stale", source: "replay" }));
    display.frame();
    expect([handle.status, handle.source]).toEqual(["stale", "replay"]); // news without a frame
  });

  it("500 messages inside one animation frame are one render of the latest news", () => {
    const marks: string[] = [];
    const { client, port, display } = rig({ mark: (name) => marks.push(name) });
    const handle = client.consume(SPEC);
    port.say(data("c1", [snap(1)]));
    for (let seq = 2; seq <= 500; seq += 1) {
      port.say(data("c1", [delta(seq)], { status: seq === 500 ? "stale" : "live" }));
    }
    expect(display.pending()).toBe(1);
    display.frame();
    expect(marks).toEqual(["state.apply", "paint"]);
    expect(handle.status).toBe("stale");
  });

  it("is let go with release: posted once, nothing delivered after, its queue empty", () => {
    const { client, port, display } = rig();
    const handle = client.consume(SPEC);
    port.say(data("c1", [snap(1)]));
    handle.release();
    handle.release();
    expect(port.of("release")).toEqual([{ t: "release", id: "c1" }]);
    expect(handle.read()).toEqual([]);
    port.say(data("c1", [delta(2)]));
    display.frame();
    expect(handle.read()).toEqual([]);
    expect(handle.status).toBe("pending"); // the news of a consumer that is gone changes nothing
  });

  it("whose queue overflows is voided: a reset in order, no delta until a snapshot, one resync, and the snapshot restores it", () => {
    const { client, port, display } = rig({ queueLimits: { maxFrames: 3, maxBytes: 1e9 } });
    const handle = client.consume(SPEC);
    port.say(data("c1", [snap(1), delta(2), delta(3), delta(4)]));
    expect(port.of("resync")).toEqual([{ t: "resync", id: "c1" }]);
    port.say(data("c1", [delta(5), delta(6)])); // they extend a baseline that is gone
    display.frame();
    expect(handle.status).toBe("resyncing"); // whatever the worker had not heard yet
    expect(labels(handle.read())).toEqual(["reset:overflow"]);
    port.say(data("c1", [snap(9), delta(10)], { status: "live" }));
    display.frame();
    expect([handle.status, labels(handle.read())]).toEqual(["live", ["snap:9", "d:10"]]);
    expect(port.of("resync")).toHaveLength(1);
  });

  it("reads revoked, not resyncing, when the worker revoked a consumer the client voided: no snapshot will come for it", () => {
    const { client, port, display } = rig({ queueLimits: { maxFrames: 3, maxBytes: 1e9 } });
    const handle = client.consume(SPEC);
    port.say(data("c1", [snap(1), delta(2), delta(3), delta(4)])); // voided: it waits for a snapshot
    port.say(data("c1", [], { status: "revoked" })); // the worker's word wins (the host gives it precedence too)
    display.frame();
    expect(handle.status).toBe("revoked");
  });

  it("is revoked when the worker says nothing of it in time (it refused), and not when it does", () => {
    const { client, port } = rig();
    const refused = client.consume(SPEC);
    const served = client.consume({ ...SPEC, ch: "trades.BTCUSDT" });
    port.say(data("c2", [], { status: "pending" }));
    vi.advanceTimersByTime(HOST_WAIT_MS);
    expect([refused.status, served.status]).toEqual(["revoked", "pending"]);
  });
});

describe("panes, focus and the page", () => {
  it("posts a pane with its size only when it has one, and the focus", () => {
    const { client, port } = rig();
    client.setPane("p1", "offscreen");
    client.setPane("p2", "visible", { cssWidth: 1190, dpr: 1.5 });
    client.focusPane("p2");
    client.focusPane(null);
    expect(port.posted.slice(-4)).toEqual([
      { t: "pane", id: "p1", visibility: "offscreen" },
      { t: "pane", id: "p2", visibility: "visible", cssWidth: 1190, dpr: 1.5 },
      { t: "focus", id: "p2" },
      { t: "focus", id: null },
    ]);
  });

  it("says when the page is hidden or shown again, and stops listening with the client", () => {
    const { client, port, page } = rig();
    page.show(true);
    page.show(false);
    expect(port.of("visibility")).toEqual([
      { t: "visibility", hidden: false }, // at the start
      { t: "visibility", hidden: true },
      { t: "visibility", hidden: false },
    ]);
    client.stop();
    expect([page.watchers.size, page.exits.size]).toEqual([0, 0]);
  });

  it("stops when the page goes away: a closed tab cannot say stop afterwards, and a shared worker is not told", () => {
    const { port, page } = rig();
    page.leave();
    expect(port.of("stop")).toEqual([{ t: "stop" }]);
  });
});

describe("stopping", () => {
  it("posts stop once and hears nothing after: no state, no system update, no frame", async () => {
    const { client, port, systems, display } = rig();
    const handle = client.consume(SPEC);
    const heard = vi.fn();
    client.subscribe(heard);
    port.say(data("c1", [snap(1)])); // a frame is asked for, and is not wanted any more once the client has stopped
    client.stop();
    client.stop();
    expect(port.of("stop")).toEqual([{ t: "stop" }]);
    expect(display.pending()).toBe(0);
    port.say({ t: "state", state: INITIAL_WS_STATE });
    port.say({ t: "system", update: { kind: "health", health: "healthy" } });
    port.say(data("c1", [snap(1)]));
    await vi.advanceTimersByTimeAsync(0);
    display.frame();
    expect(heard).not.toHaveBeenCalled();
    expect(systems).toEqual([]);
    expect(handle.read()).toEqual([]);
  });

  it("posts nothing more: a pane, a focus, a release, and a consumer that starts afterwards reads revoked and is not posted", () => {
    const { client, port } = rig();
    const before = client.consume(SPEC);
    client.stop();
    const count = port.posted.length;
    client.setPane("p1", "visible");
    client.focusPane("p1");
    before.release();
    const after = client.consume(SPEC);
    expect(port.posted).toHaveLength(count);
    expect([after.status, after.read()]).toEqual(["revoked", []]);
    vi.advanceTimersByTime(HOST_WAIT_MS * 2); // no wait is left running
    expect(client.getState().transport).toBe("connecting");
  });
});

describe("what the worker posts is untrusted", () => {
  it("is ignored when it is not one of its messages: no state change, no throw", () => {
    const { client, port } = rig();
    const heard = vi.fn();
    client.subscribe(heard);
    for (const junk of [null, "state", { t: "state" }, { t: "data", id: 5 }, { t: "evil" }, [1]]) {
      expect(() => port.say(junk)).not.toThrow();
    }
    expect([heard.mock.calls.length, client.getState()]).toEqual([0, INITIAL_WS_STATE]);
  });
});

describe("the page it lives in", () => {
  /** What `document.visibilityState` says, as long as the test lasts. */
  const sees = (state: "visible" | "hidden") =>
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  afterEach(() => Reflect.deleteProperty(document, "visibilityState"));

  it("is the document: hidden follows its visibility, a change and the page going away are heard until stopped", () => {
    const page = documentPage();
    sees("visible");
    expect(page.hidden()).toBe(false);
    sees("hidden");
    expect(page.hidden()).toBe(true);
    const changed = vi.fn();
    const left = vi.fn();
    const stopWatching = page.watch(changed);
    const stopListening = page.onExit(left);
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("pagehide"));
    expect([changed.mock.calls.length, left.mock.calls.length]).toEqual([1, 1]);
    stopWatching();
    stopListening();
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("pagehide"));
    expect([changed.mock.calls.length, left.mock.calls.length]).toEqual([1, 1]);
  });

  it("is a page that is never hidden and never heard when there is no document", () => {
    vi.stubGlobal("document", undefined);
    const page = documentPage();
    expect(page.hidden()).toBe(false);
    expect(page.watch(() => undefined)()).toBeUndefined();
    expect(page.onExit(() => undefined)()).toBeUndefined();
    vi.unstubAllGlobals();
  });

  it("is the document unless the client is given another: a hidden page is told to the worker", () => {
    const { client, port } = rig({ page: undefined });
    sees("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    expect(port.of("visibility").at(-1)).toEqual({ t: "visibility", hidden: true });
    client.stop(); // it listened to the real document and window
  });
});
