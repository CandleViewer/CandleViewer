/**
 * E16-S01 2/9: the `recorder` topic reader (23 §6.2.2, §15.8; E16-D02 §3.1; BQ-6, BQ-7) against a fake
 * client, a hand-stepped animation frame and a fake clock: frames read on rAF only and checked against
 * the generated shape; stale after 2 s without one, at once while the socket is down, cleared by the
 * next; REST re-read after a reconnect, a change of rows or a write, through one 5 s gap with one in
 * flight; every subscription torn down.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConsumerSpec, TopicFrame, TopicHandle } from "../../../src/lib/ws/api";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { INITIAL_WS_STATE } from "../../../src/lib/ws/state/reducer";
import type { Link } from "../../../src/lib/ws/state/types";
import {
  isRecorderFrame,
  openRecorderTopic,
  type RecorderFrame,
  type RecorderTopicOptions,
  type RereadCause,
} from "../../../src/features/recorder/recorderTopic";
import { frameHealthy } from "./fixtures";

const STAMP = { seq: 1, ts: 0, sp: undefined, decodeMs: 0, size: 1, meta: undefined };
const snap = (p: unknown, ts = 0): TopicFrame => ({
  ...STAMP,
  ts,
  kind: "snap",
  bodies: [{ e: "j", p }],
});
const delta = (p: unknown): TopicFrame => ({ ...STAMP, kind: "d", body: { e: "j", p } });
const reset = (reason: "reconnect" | "gap"): TopicFrame => ({ kind: "reset", reason });
const frame = (...rows: [string, RecorderFrame["symbols"][number]["state"]][]): RecorderFrame => ({
  overall: "healthy",
  symbols: rows.map(([symbol, state]) => ({ symbol, state })),
});
const LINKS: Record<"up" | "reconnecting" | "offline", Link> = {
  up: { kind: "up" },
  reconnecting: { kind: "reconnecting", attempt: 1, nextAttemptAtMs: 0 },
  offline: { kind: "offline", cause: "offline" },
};

function harness(options: Partial<RecorderTopicOptions> = {}) {
  const queue: TopicFrame[] = [];
  let link: Link = LINKS.up;
  const handle: TopicHandle = {
    ch: "recorder",
    read: () => queue.splice(0),
    effective: {},
    status: "live",
    source: "live",
    rs: undefined,
    release: vi.fn(),
  };
  const client = {
    consume: vi.fn<(spec: ConsumerSpec) => TopicHandle>(() => handle),
    getState: () => ({ ...INITIAL_WS_STATE, link }),
  };
  let clock = 0;
  /** The wall clock, which may step on its own (an NTP correction); elapsed time is `clock`'s. */
  let wall: number | undefined;
  let pending: (() => void) | undefined;
  const caf = vi.fn();
  const onReread = vi.fn();
  const topic = openRecorderTopic({
    client,
    onReread,
    now: () => wall ?? clock,
    monotonic: () => clock,
    raf: (callback) => {
      pending = () => callback(clock);
      return clock + 1;
    },
    caf,
    ...options,
  });
  const listener = vi.fn();
  topic.subscribe(listener);
  /** Moves the clock to `at` ms, then runs one animation frame with `frames` waiting. */
  const step = (at: number, ...frames: TopicFrame[]): void => {
    clock = at;
    queue.push(...frames);
    const run = pending;
    pending = undefined;
    run?.();
  };
  const setLink = (kind: keyof typeof LINKS): void => void (link = LINKS[kind]);
  const setWall = (at: number | undefined): void => void (wall = at);
  return { topic, client, handle, caf, onReread, listener, step, setLink, setWall };
}

/** Lets settled re-reads leave flight (their `then` runs on a microtask). */
const quiesce = async (): Promise<void> => {
  for (let turn = 0; turn < 5; turn += 1) await Promise.resolve();
};

afterEach(() => setActiveClient(null));

describe("openRecorderTopic", () => {
  it("consumes `recorder` and holds each valid frame from the next animation frame on", () => {
    const { topic, client, listener, step } = harness();
    const spec = { ch: "recorder", paneId: "recorder", priority: "focused" };
    expect(client.consume).toHaveBeenCalledWith(spec);
    expect(topic.getView()).toEqual({ frame: null, frameAtMs: null, serverMs: null, stale: false });
    step(250, snap(frameHealthy));
    expect(topic.getView()).toEqual({
      frame: frameHealthy,
      frameAtMs: 250,
      serverMs: null,
      stale: false,
    });
    expect(listener).toHaveBeenCalledTimes(1);
    const view = topic.getView();
    step(300);
    expect(topic.getView()).toBe(view); // nothing changed: the same view, no notice
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("a delta is the whole frame; a frame that fails the shape check leaves the held one", () => {
    const { topic, step } = harness();
    step(0, snap(frameHealthy), delta(frame(["BTCUSDT", "stopping"])));
    expect(topic.getView().frame).toEqual(frame(["BTCUSDT", "stopping"]));
    const held = topic.getView().frame;
    const binary: TopicFrame = {
      ...STAMP,
      kind: "d",
      body: { e: "b64", bytes: new ArrayBuffer(4) },
    };
    const chunk = { e: "j", p: frameHealthy } as const;
    const chunked: TopicFrame = { ...STAMP, kind: "snap", bodies: [chunk, chunk] };
    step(100, delta({ symbols: [] }), binary, chunked, snap(null));
    expect(topic.getView().frame).toBe(held);
  });

  it("turns stale 2 s after the last frame, or after opening with none; the next frame clears it", () => {
    const { topic, listener, step } = harness();
    step(1_999);
    expect(topic.getView().stale).toBe(false);
    step(2_000);
    expect(topic.getView()).toEqual({ frame: null, frameAtMs: null, serverMs: null, stale: true });
    step(2_100, snap(frameHealthy));
    expect(topic.getView()).toMatchObject({ frame: frameHealthy, frameAtMs: 2_100, stale: false });
    step(4_099);
    expect(topic.getView().stale).toBe(false);
    step(4_100);
    expect(topic.getView()).toMatchObject({ frame: frameHealthy, frameAtMs: 2_100, stale: true });
    expect(listener).toHaveBeenCalledTimes(3);
  });

  it.each(["reconnecting", "offline"] as const)(
    "is stale at once while the socket is %s; the first frame after asks REST to re-read, once",
    (down) => {
      const { topic, onReread, step, setLink } = harness();
      step(0, snap(frameHealthy));
      setLink(down);
      step(16);
      expect(topic.getView().stale).toBe(true);
      setLink("up");
      step(500);
      expect(topic.getView().stale).toBe(true); // until the first frame after the reconnect
      expect(onReread).not.toHaveBeenCalled();
      step(900, snap(frameHealthy));
      expect(topic.getView().stale).toBe(false); // the first frame after it clears the view
      step(4_999, snap(frameHealthy));
      expect(onReread).not.toHaveBeenCalled(); // the mount's own reads were under 5 s ago (BQ-7)
      step(5_000, snap(frameHealthy));
      expect(onReread.mock.calls).toEqual([["reconnect"]]);
    },
  );

  it("a `reconnect` reset is stale until the frame after it, which asks for the re-read", () => {
    const { topic, onReread, step } = harness();
    step(0, snap(frameHealthy), reset("gap"), snap(frameHealthy));
    expect(onReread).not.toHaveBeenCalled(); // a gap is the topic's own resync
    step(5_100, reset("reconnect"));
    expect(topic.getView().stale).toBe(true);
    step(5_200, snap(frameHealthy));
    expect(topic.getView().stale).toBe(false);
    expect(onReread.mock.calls).toEqual([["reconnect"]]);
  });

  it("re-reads the list when a row joins, leaves or leaves `starting`: once per 5 s, one in flight", async () => {
    let settle = (): void => undefined;
    const onReread = vi.fn<(cause: RereadCause) => Promise<void>>(
      () => new Promise((resolve) => (settle = resolve)),
    );
    const { step } = harness({ onReread });
    step(0, snap(frame(["BTCUSDT", "recording"], ["SOLUSDT", "idle"])));
    step(1_000, snap(frame(["BTCUSDT", "recording"], ["SOLUSDT", "idle"], ["XRPUSDT", "idle"])));
    expect(onReread).not.toHaveBeenCalled(); // a refused start is no row
    step(2_000, snap(frame(["BTCUSDT", "recording"], ["ETHUSDT", "starting"])));
    step(4_999);
    expect(onReread).not.toHaveBeenCalled(); // the mount's own read was under 5 s ago
    step(5_000);
    expect(onReread.mock.calls).toEqual([["rows"]]);
    step(10_000, snap(frame(["BTCUSDT", "recording"], ["ETHUSDT", "recording"])));
    expect(onReread).toHaveBeenCalledTimes(1); // the first is still in flight
    settle();
    for (let turn = 0; turn < 5; turn += 1) await Promise.resolve(); // to quiescence
    step(10_016);
    expect(onReread.mock.calls).toEqual([["rows"], ["rows"]]);
    step(20_000, snap(frame(["BTCUSDT", "recording"], ["ETHUSDT", "degraded"])));
    expect(onReread).toHaveBeenCalledTimes(2); // a state change of a listed row is the frame's own
  });

  it("re-reads the list when a row leaves or reaches `stopped` (A-5309-01, A-5309-12)", async () => {
    const { onReread, step } = harness();
    step(0, snap(frame(["BTCUSDT", "recording"], ["ETHUSDT", "recording"])));
    step(6_000, snap(frame(["BTCUSDT", "recording"])));
    expect(onReread.mock.calls).toEqual([["rows"]]);
    await quiesce();
    step(12_000, snap(frame(["BTCUSDT", "stopping"])));
    expect(onReread).toHaveBeenCalledTimes(1); // stopping is the frame's own
    step(18_000, snap(frame(["BTCUSDT", "stopped"])));
    expect(onReread.mock.calls).toEqual([["rows"], ["rows"]]);
    await quiesce();
    step(24_000, snap(frame(["BTCUSDT", "stopped"])));
    expect(onReread).toHaveBeenCalledTimes(2);
  });

  it("reconnects re-read through the gap and the one in flight: six a second apart are two (A-5309-06)", async () => {
    let settle = (): void => undefined;
    const onReread = vi.fn<(cause: RereadCause) => Promise<void>>(
      () => new Promise((resolve) => (settle = resolve)),
    );
    const { step, setLink } = harness({ onReread });
    step(0, snap(frameHealthy));
    for (let n = 1; n <= 6; n += 1) {
      setLink("reconnecting");
      step(n * 1_000);
      setLink("up");
      step(n * 1_000 + 500, snap(frameHealthy));
    }
    expect(onReread.mock.calls).toEqual([["reconnect"]]); // at 5.5 s, the first past the gap
    step(12_000, snap(frameHealthy));
    expect(onReread).toHaveBeenCalledTimes(1); // the first is still in flight
    settle();
    await quiesce();
    step(12_016);
    expect(onReread.mock.calls).toEqual([["reconnect"], ["reconnect"]]); // the 6.5 s one, held
  });

  it("a reconnect while a rows re-read is in flight waits for it, then reads the three once", async () => {
    let settle = (): void => undefined;
    const onReread = vi.fn<(cause: RereadCause) => Promise<void>>(
      () => new Promise((resolve) => (settle = resolve)),
    );
    const { step, setLink } = harness({ onReread });
    step(0, snap(frame(["BTCUSDT", "recording"])));
    step(6_000, snap(frame(["BTCUSDT", "recording"], ["ETHUSDT", "starting"])));
    expect(onReread.mock.calls).toEqual([["rows"]]);
    setLink("offline");
    step(6_500);
    setLink("up");
    step(12_000, snap(frame(["BTCUSDT", "recording"], ["ETHUSDT", "recording"])));
    expect(onReread).toHaveBeenCalledTimes(1);
    settle();
    await quiesce();
    step(12_016);
    expect(onReread.mock.calls).toEqual([["rows"], ["reconnect"]]); // the reconnect's reads hold the list
    step(30_000);
    expect(onReread).toHaveBeenCalledTimes(2);
  });

  it("requestRows asks for the list through the same gap (a write landed, C-5309-10 (c))", () => {
    const { topic, onReread, step } = harness();
    step(0, snap(frameHealthy));
    topic.requestRows();
    step(1_000);
    expect(onReread).not.toHaveBeenCalled();
    topic.requestRows();
    step(5_000);
    expect(onReread.mock.calls).toEqual([["rows"]]);
    step(9_000);
    expect(onReread).toHaveBeenCalledTimes(1);
  });

  it("measures staleness on the monotonic clock: a wall-clock step back never hides it (A-5309-07)", () => {
    const { topic, step, setWall } = harness();
    step(0, snap(frameHealthy));
    setWall(-3_600_000); // the wall clock steps an hour back
    step(2_000);
    expect(topic.getView().stale).toBe(true);
    step(2_100, snap(frameHealthy));
    expect(topic.getView()).toMatchObject({ frameAtMs: -3_600_000, stale: false });
  });

  it("keeps reading after a listener throws (A-5309-07)", () => {
    const { topic, listener, step } = harness();
    const thrower = vi.fn(() => {
      throw new Error("a listener failed");
    });
    const off = topic.subscribe(thrower);
    expect(() => step(0, snap(frameHealthy))).toThrow("a listener failed");
    off();
    step(100, delta(frame(["BTCUSDT", "stopping"])));
    expect(topic.getView().frame).toEqual(frame(["BTCUSDT", "stopping"]));
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("holds the newest frame's envelope `ts` as the server's clock (23 §4.2; A-5309-08, C-5309-11)", () => {
    const { topic, step } = harness();
    step(100, snap(frameHealthy, 1_789_132_262_104));
    expect(topic.getView()).toMatchObject({ frameAtMs: 100, serverMs: 1_789_132_262_104 });
    step(200, snap(frameHealthy));
    expect(topic.getView().serverMs).toBeNull(); // a frame with no usable `ts`
  });

  it("close releases the subscription, cancels the frame and stops reading; it is idempotent", () => {
    const { topic, handle, caf, listener, step } = harness();
    const other = vi.fn();
    topic.subscribe(other)(); // unsubscribed at once
    step(0, snap(frameHealthy));
    expect(other).not.toHaveBeenCalled();
    topic.close();
    topic.close();
    expect(handle.release).toHaveBeenCalledTimes(1);
    expect(caf).toHaveBeenCalledTimes(1);
    step(5_000, delta(frame()));
    expect(listener).toHaveBeenCalledTimes(1); // the first frame's, before the close
    expect(topic.getView()).toEqual({
      frame: frameHealthy,
      frameAtMs: 0,
      serverMs: null,
      stale: false,
    });
  });

  it("reads the shell's client by default; with none it reads nothing and turns stale", () => {
    const shell = harness();
    setActiveClient(shell.client as unknown as WsClientHandle);
    const fallback = harness({ client: undefined });
    expect(shell.client.consume).toHaveBeenCalledTimes(2);
    fallback.topic.close();
    setActiveClient(null);
    const none = harness({ client: undefined });
    none.step(2_000);
    expect(none.topic.getView().stale).toBe(true);
    none.topic.close();
  });
});

// prettier-ignore
const ACCEPTED: [string, unknown][] = [
  ["the full frame", frameHealthy],
  ["the required fields alone", frame(["BTCUSDT", "recording"])],
  ["values of open-ended fields it does not know (C-6.3)", { ...frame(["A", "idle"]), symbols: [{ symbol: "A", state: "idle", refusal: "maintenance" }], storage: { write_gate_reason: "quota" } }],
  ["a field it does not know", { ...frameHealthy, added_later: 1 }],
];
const down = (extra: object): unknown => ({ overall: "down", symbols: [], ...extra });
// prettier-ignore
const REFUSED: [string, unknown][] = [
  ["null", null],
  ["a list", []],
  ["no overall", { symbols: [] }],
  ["an unknown overall", { overall: "fine", symbols: [] }],
  ["symbols not a list", down({ symbols: {} })],
  ["a row with no symbol", down({ symbols: [{ state: "idle" }] })],
  ["an unknown state", down({ symbols: [{ symbol: "A", state: "paused" }] })],
  ["a time as text", down({ symbols: [{ symbol: "A", state: "idle", linger_until_ms: "soon" }] })],
  ["a level as text", down({ storage: { level: "1" } })],
  ["a policy missing a field", down({ policy: { max_symbols: 20 } })],
  ["a connection not an object", down({ connections: ["up"] })],
];

describe("isRecorderFrame (the generated `Recorder` shape, 23 §15.8)", () => {
  it.each(ACCEPTED)("accepts %s", (_, value) => expect(isRecorderFrame(value)).toBe(true));
  it.each(REFUSED)("refuses %s", (_, value) => expect(isRecorderFrame(value)).toBe(false));
});
