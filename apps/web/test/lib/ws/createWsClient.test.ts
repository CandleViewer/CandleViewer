// E17-T04 S5f (ADR-0005; 23 4.1; C8, C9, C11, C12): the tab's end of the port, against a fake worker. What the app sees follows
// the display, not the feed: frames wait in a bounded queue behind `read()`, what a handle reads changes on the animation frame,
// and only a change of the connection state (or a `system` update) is heard at once.
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TokenResult, TokenSource, TopicFrame } from "../../../src/lib/ws/api";
import {
  createWsClient,
  documentPage,
  HOST_WAIT_MS,
  type WsClientOptions,
} from "../../../src/lib/ws/client/createWsClient";
import { RESYNC_WINDOW_MS } from "../../../src/lib/ws/core/resyncGuard";
import type { PortLike } from "../../../src/lib/ws/port/endpoint";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import { fakePage } from "./support/fakePage";

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

const TOKEN = "t".repeat(48);
const RS = "bb000000-0000-4000-8000-000000000001";
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
const reset = (reason: "gap" | "overflow" = "gap"): TopicFrame => ({ kind: "reset", reason });
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
const KILL = { engaged: false, scope: "global" } as const;
const UP = reduce(INITIAL_WS_STATE, { type: "auth_ok", killSwitch: KILL }); // connected: order entry is on

function rig(over: Partial<WsClientOptions> = {}, tokens?: Partial<TokenSource>) {
  vi.useFakeTimers();
  const port = new FakePort();
  const page = fakePage();
  const display = fakeDisplay();
  const source: TokenSource = {
    getToken: vi.fn(async (): Promise<TokenResult> => ({
      kind: "ok",
      accessToken: TOKEN,
      expiresAtMs: 9e12,
    })),
    invalidate: vi.fn(),
    ...tokens,
  };
  const systems: unknown[] = [];
  const raised: (() => void)[] = [];
  const client = createWsClient({
    wsUrl: "wss://cv.test/api/v1/ws",
    tokens: source,
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
  return { client, port, page, display, source, systems, raised };
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

  it("hears a port that answers inside postMessage: the waits are armed before the posts, so none is left to refuse what was served", () => {
    let say: (message: unknown) => void = () => undefined;
    const port: PortLike = {
      listen: (handler) => void (say = handler),
      postMessage: (message) => {
        const { t, id } = message as { t: string; id?: string };
        if (t === "connect") say({ t: "state", state: UP });
        if (t === "consume") say(data(id ?? "", [snap(1)]));
      },
    };
    const { client } = rig({ port });
    const handle = client.consume(SPEC);
    vi.advanceTimersByTime(HOST_WAIT_MS * 2);
    expect(client.getState()).toBe(UP); // not offline at 5 s
    expect(handle.status).not.toBe("revoked"); // and not refused
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

  it("asks again each resync window while no snapshot has come (the host refuses a vote in silence), and not after one comes", () => {
    const { client, port } = rig({ queueLimits: { maxFrames: 3, maxBytes: 1e9 } });
    client.consume(SPEC);
    port.say(data("c1", [snap(1), delta(2), delta(3), delta(4)])); // voided: the first resync, and the host says nothing
    vi.advanceTimersByTime(RESYNC_WINDOW_MS - 1);
    expect(port.of("resync")).toHaveLength(1); // the window cannot have reopened yet
    vi.advanceTimersByTime(1);
    expect(port.of("resync")).toHaveLength(2);
    vi.advanceTimersByTime(RESYNC_WINDOW_MS);
    expect(port.of("resync")).toHaveLength(3); // and again, while none has come
    port.say(data("c1", [snap(9)]));
    vi.advanceTimersByTime(RESYNC_WINDOW_MS * 2);
    expect(port.of("resync")).toHaveLength(3);
  });

  it("asks no more of a consumer that is let go, or that the worker revoked: no snapshot is wanted, or none will come", () => {
    const { client, port } = rig({ queueLimits: { maxFrames: 3, maxBytes: 1e9 } });
    const gone = client.consume(SPEC);
    client.consume({ ...SPEC, ch: "trades.BTCUSDT" });
    for (const id of ["c1", "c2"]) port.say(data(id, [snap(1), delta(2), delta(3), delta(4)])); // each is voided
    gone.release();
    port.say(data("c2", [], { status: "revoked" }));
    vi.advanceTimersByTime(RESYNC_WINDOW_MS * 2);
    expect(port.of("resync")).toHaveLength(2); // the two first ones, and no more
  });

  it("is revoked when the worker says nothing of it in time (it refused), and not when it does", () => {
    const { client, port } = rig();
    const refused = client.consume(SPEC);
    const served = client.consume({ ...SPEC, ch: "trades.BTCUSDT" });
    port.say(data("c2", [], { status: "pending" }));
    vi.advanceTimersByTime(HOST_WAIT_MS);
    expect([refused.status, served.status]).toEqual(["revoked", "pending"]);
  });

  it("is not revoked when it was let go before the worker's first word: its wait ended with it", () => {
    const { client } = rig();
    const handle = client.consume(SPEC);
    handle.release();
    vi.advanceTimersByTime(HOST_WAIT_MS);
    expect(handle.status).toBe("pending");
  });

  it("feeds the decode time of every frame to telemetry, and none for a reset", () => {
    const recordDecode = vi.fn();
    const { client, port } = rig({ telemetry: { recordDecode } });
    client.consume(SPEC);
    port.say(data("c1", [snap(1), reset(), delta(2)]));
    expect(recordDecode.mock.calls).toEqual([[0.5], [0.5]]);
  });

  it("feeds the age of the newest frame of a rendered batch to the latency indicator, by the worker's clock, once a second", () => {
    const indicators: { valueMs: number | null; state: string }[] = [];
    let now = 10_000;
    const { client, port, display } = rig({
      wallClock: () => now,
      onLatency: (indicator) => indicators.push(indicator),
    });
    client.consume(SPEC);
    client.consume({ ...SPEC, ch: "trades.BTCUSDT" });
    port.say({
      t: "diag",
      diag: { engine: {}, host: {}, slowConsumerHint: [], clockSkewMs: 500 },
    });
    port.say(data("c1", [snap(1, 10_300), delta(2, 10_340)])); // the worker's clock is 500 ms ahead
    port.say(data("c2", [snap(1, 10_460)])); // the newest of the two consumers of the batch is the one measured
    display.frame();
    expect(indicators).toEqual([expect.objectContaining({ valueMs: 40, state: "ok" })]);
    now += 500;
    port.say(data("c1", [delta(3, 10_900)]));
    display.frame();
    expect(indicators).toHaveLength(1); // not again inside the second
    now += 600;
    port.say(data("c1", [delta(4, 11_300)]));
    display.frame();
    expect(indicators.at(-1)).toMatchObject({ valueMs: 300, state: "breach" });
  });

  it("measures the newest frame of a message for the latency indicator, not its first", () => {
    const indicators: { valueMs: number | null }[] = [];
    const { client, port, display } = rig({
      wallClock: () => 10_000,
      onLatency: (i) => indicators.push(i),
    });
    client.consume(SPEC);
    port.say(data("c1", [snap(1, 9_600), delta(2, 9_900)])); // no skew: 100 ms old, not 400
    display.frame();
    expect(indicators).toEqual([expect.objectContaining({ valueMs: 100 })]);
  });

  it("measures the newest frame of a batch wherever it is, and no replay frame: its ts is the time it was recorded (23 11)", () => {
    const indicators: { valueMs: number | null }[] = [];
    const { client, port, display } = rig({
      wallClock: () => 10_000,
      onLatency: (i) => indicators.push(i),
    });
    client.consume(SPEC, RS);
    port.say(data("c1", [snap(1, 1_000)], { source: "replay" }));
    display.frame();
    expect(indicators).toEqual([]); // a batch of replay frames says nothing of the feed
    client.consume({ ...SPEC, ch: "trades.BTCUSDT" });
    client.consume({ ...SPEC, ch: "bars.BTCUSDT.time.1" });
    port.say(data("c2", [snap(1, 9_900)])); // the newest, and not the last
    port.say(data("c3", [snap(1, 9_100)]));
    port.say(data("c1", [delta(2, 9_999)], { source: "replay" }));
    display.frame();
    expect(indicators).toEqual([expect.objectContaining({ valueMs: 100 })]);
  });

  it("keeps the frames of a message whose telemetry throws: the error is raised on its own", () => {
    const recordDecode = vi.fn(() => {
      throw new Error("aggregator");
    });
    const { client, port, raised } = rig({ telemetry: { recordDecode } });
    const handle = client.consume(SPEC);
    port.say(data("c1", [snap(1), delta(2)]));
    expect(labels(handle.read())).toEqual(["snap:1", "d:2"]);
    expect(raised).toHaveLength(2);
    expect(() => raised[0]?.()).toThrow("aggregator");
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

describe("the access token (4.3)", () => {
  it("is asked of the source when the worker asks, and goes back in one `token` message and nowhere else", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    const store = vi.spyOn(Storage.prototype, "setItem");
    const { client, port, source } = rig();
    client.consume(SPEC);
    port.say({ t: "tokenRequest", req: 7, invalidate: false });
    await vi.advanceTimersByTimeAsync(0);
    expect(source.invalidate).not.toHaveBeenCalled();
    expect(port.of("token")).toEqual([
      { t: "token", req: 7, result: { kind: "ok", accessToken: TOKEN, expiresAtMs: 9e12 } },
    ]);
    const elsewhere = JSON.stringify(port.posted.filter((m) => m.t !== "token"));
    expect(elsewhere).not.toContain(TOKEN);
    expect(JSON.stringify(spies.flatMap((spy) => spy.mock.calls))).not.toContain(TOKEN);
    expect(JSON.stringify(client.getState())).not.toContain(TOKEN);
    expect(JSON.stringify(client.diagnostics() ?? null)).not.toContain(TOKEN);
    expect(store).not.toHaveBeenCalled();
  });

  it("posts the three fields of a token and no more: what the source adds stays in the tab", async () => {
    const getToken = async (): Promise<TokenResult> =>
      ({
        kind: "ok",
        accessToken: TOKEN,
        expiresAtMs: 9e12,
        refreshToken: "r-secret",
      }) as TokenResult;
    const { port } = rig({}, { getToken });
    port.say({ t: "tokenRequest", req: 5, invalidate: false });
    await vi.advanceTimersByTimeAsync(0);
    expect(port.of("token")).toStrictEqual([
      { t: "token", req: 5, result: { kind: "ok", accessToken: TOKEN, expiresAtMs: 9e12 } },
    ]);
  });

  it("answers unavailable when the source throws from invalidate: the throw does not leave the port's handler", async () => {
    const invalidate = (): void => {
      throw new Error("down");
    };
    const { port } = rig({}, { invalidate });
    expect(() => port.say({ t: "tokenRequest", req: 6, invalidate: true })).not.toThrow();
    await vi.advanceTimersByTimeAsync(0);
    expect(port.of("token")).toEqual([{ t: "token", req: 6, result: { kind: "unavailable" } }]);
  });

  it("is refused by the server (invalidate): the source is told first, once, and the next token is asked for", async () => {
    const { port, source } = rig();
    port.say({ t: "tokenRequest", req: 1, invalidate: true });
    await vi.advanceTimersByTimeAsync(0);
    expect(source.invalidate).toHaveBeenCalledTimes(1);
    expect(source.getToken).toHaveBeenCalledTimes(1);
    expect(vi.mocked(source.invalidate).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(source.getToken).mock.invocationCallOrder[0] ?? 0,
    );
  });

  it.each([
    [
      "locked",
      { getToken: async (): Promise<TokenResult> => ({ kind: "locked" }) },
      { kind: "locked" },
    ],
    [
      "unavailable",
      { getToken: async (): Promise<TokenResult> => ({ kind: "unavailable" }) },
      { kind: "unavailable" },
    ],
    [
      "a source that rejects",
      {
        getToken: (): Promise<TokenResult> => Promise.reject(new Error(`no ${TOKEN}`)),
      },
      { kind: "unavailable" },
    ],
    [
      "a source that throws",
      {
        getToken: (): Promise<TokenResult> => {
          throw new Error("down");
        },
      },
      { kind: "unavailable" },
    ],
  ])(
    "says %s as it is, and a source that fails says unavailable",
    async (_name, tokens, expected) => {
      const { port } = rig({}, tokens);
      port.say({ t: "tokenRequest", req: 4, invalidate: false });
      await vi.advanceTimersByTimeAsync(0);
      expect(port.of("token")).toEqual([{ t: "token", req: 4, result: expected }]);
    },
  );

  it("is not posted once the client has stopped: a late answer is dropped", async () => {
    let answer: (result: TokenResult) => void = () => undefined;
    const { client, port } = rig(
      {},
      { getToken: () => new Promise<TokenResult>((resolve) => (answer = resolve)) },
    );
    port.say({ t: "tokenRequest", req: 2, invalidate: false });
    await vi.advanceTimersByTimeAsync(0);
    client.stop();
    answer({ kind: "ok", accessToken: TOKEN, expiresAtMs: 9e12 });
    await vi.advanceTimersByTimeAsync(0);
    expect(port.of("token")).toEqual([]);
  });
});

describe("stopping", () => {
  it("posts stop once and hears nothing after: no state, no system update, no frame, no token request", async () => {
    const { client, port, source, systems, display } = rig();
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
    port.say({ t: "tokenRequest", req: 1, invalidate: false });
    await vi.advanceTimersByTimeAsync(0);
    display.frame();
    expect(heard).toHaveBeenCalledTimes(1); // the offline of the stop itself, and nothing after it
    expect(systems).toEqual([]);
    expect(handle.read()).toEqual([]);
    expect(source.getToken).not.toHaveBeenCalled();
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
    expect(vi.getTimerCount()).toBe(0); // no wait is left running
    vi.advanceTimersByTime(HOST_WAIT_MS * 2);
    expect(client.getState().transport).toBe("offline"); // the stop's own: nothing changed it since
  });

  it("reads offline once stopped, and the subscribers hear it: a mounted UI never keeps order entry on", () => {
    const { client, port } = rig();
    const heard = vi.fn();
    client.subscribe(heard);
    port.say({ t: "state", state: UP });
    expect(client.getState().orderEntry.enabled).toBe(true);
    client.stop();
    expect(client.getState().transport).toBe("offline");
    expect(client.getState().orderEntry.enabled).toBe(false);
    expect(heard).toHaveBeenCalledTimes(2); // the state, and the stop
  });

  it("leaves no timer running: the waits for the state, for a consumer's first word and for a snapshot are all ended", () => {
    const { client, port } = rig({ queueLimits: { maxFrames: 3, maxBytes: 1e9 } });
    client.consume(SPEC);
    client.consume({ ...SPEC, ch: "trades.BTCUSDT" });
    port.say(data("c1", [snap(1), delta(2), delta(3), delta(4)])); // c1 is voided: it asks again if no snapshot comes
    port.say(data("c1", [snap(9), delta(10), delta(11), delta(12)])); // a snapshot, and voided again by the burst behind it
    expect(vi.getTimerCount()).toBe(3); // one each: the state's, c2's first word, c1's snapshot
    client.stop();
    expect(vi.getTimerCount()).toBe(0);
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

  it("is kept as the worker's counters, and says nothing to the subscribers", () => {
    const { client, port } = rig();
    const heard = vi.fn();
    client.subscribe(heard);
    expect(client.diagnostics()).toBeUndefined();
    const diag = { engine: {}, host: {}, slowConsumerHint: ["c1"], clockSkewMs: 12 };
    port.say({ t: "diag", diag });
    expect(client.diagnostics()).toEqual(diag);
    expect(heard).not.toHaveBeenCalled();
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
