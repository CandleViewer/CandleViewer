// E17-T04 S2 (C2, C3, C10, C11): what the registry delivers and asks for, driven by real decoded frames.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decodeBars } from "@candleviewer/protocol";
import type { ConsumerSpec, TopicFrame } from "../../../src/lib/ws/api";
import { FRAME_OVERHEAD_BYTES, JSON_HEAP_FACTOR } from "../../../src/lib/ws/core/snapshotAssembler";
import {
  createSubscriptionRegistry,
  type RegistryOptions,
} from "../../../src/lib/ws/core/subscriptions";
import { decodeFrame, type DataFrame } from "../../../src/lib/ws/protocol/codec";
import { b64, bars, bookDelta, bookSnapshot, FLAG_PARTIAL, FLAG_REPLAY } from "./support/cvwb";

const BOOK = "book.BTCUSDT.50";
const BARS = "bars.BTCUSDT.time.1";
const RS = "bb000000-0000-4000-8000-000000000001";
const SP = "0123456789abcdef";
const wire = (frame: object): string => JSON.stringify(frame);

function data(frame: object): DataFrame {
  const decoded = decodeFrame(wire({ ts: 1_789_132_262_000, e: "j", p: {}, ...frame }));
  if (decoded.t !== "snap" && decoded.t !== "d") throw new Error(`not data: ${wire(decoded)}`);
  return decoded;
}
const snap = (s: number | null, over: object = {}) => data({ t: "snap", ch: BOOK, s, ...over });
const delta = (s: number, over: object = {}) => data({ t: "d", ch: BOOK, s, ...over });
const binary = (bytes: Uint8Array) => ({ e: "b64", p: b64(bytes) });

const spec = (over: Partial<ConsumerSpec> = {}): ConsumerSpec => ({
  ch: BOOK,
  paneId: "p1",
  priority: "focused",
  ...over,
});
const kinds = (frames: readonly TopicFrame[]) =>
  frames.map((f) => (f.kind === "reset" ? `reset:${f.reason}` : `${f.kind}:${f.seq}`));

function setup(over: Partial<RegistryOptions> = {}) {
  const delivered = new Map<string, TopicFrame[]>();
  const stream = (ch: string, rs?: string) => `${ch}#${rs ?? "live"}`;
  const host = {
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
    resync: vi.fn(),
    deliver: vi.fn((ch: string, rs: string | undefined, frame: TopicFrame) => {
      delivered.set(stream(ch, rs), [...(delivered.get(stream(ch, rs)) ?? []), frame]);
    }),
  };
  /** What a stream delivered since the last call. */
  const take = (ch = BOOK, rs?: string) => delivered.get(stream(ch, rs))?.splice(0) ?? [];
  const got = (ch = BOOK, rs?: string) => kinds(take(ch, rs));
  return { host, take, got, registry: createSubscriptionRegistry({ host, ...over }) };
}
/** A live stream with one consumer whose baseline (snap 100) was delivered and read. */
function live(over: Partial<RegistryOptions> = {}) {
  const t = setup(over);
  const handle = t.registry.consume(spec());
  t.registry.onData(snap(100), 1);
  t.take();
  return { ...t, handle };
}
const resynced = (host: { resync: unknown }, last_seq: number | null, reason: string) =>
  expect(host.resync).toHaveBeenCalledWith(BOOK, { last_seq, reason });

describe("streams", () => {
  it("takes server-chosen topic names as plain stream keys", () => {
    const { registry, got } = setup();
    for (const ch of ["constructor", "__proto__", "valueof"]) {
      registry.consume(spec({ ch }));
      registry.onData(snap(1, { ch }), 0);
      expect(got(ch)).toEqual(["snap:1"]);
    }
  });

  it("shows a structured snapshot's stale flag as the stale status until the next snap clears it", () => {
    const { registry } = setup();
    const handle = registry.consume(spec());
    registry.onData(snap(100, { p: { stale: true } }), 1);
    registry.onData(delta(101), 1);
    expect(handle.status).toBe("stale");
    registry.onData(snap(102, { p: { stale: false } }), 1);
    expect(handle.status).toBe("live");
  });
});

describe("a gap is never patched (C2)", () => {
  it("A gap is never patched: nothing is delivered after the hole until the fresh snap", () => {
    const { registry, host, handle, got } = live();
    for (const s of [101, 102, 104]) registry.onData(delta(s), 1); // 103 was lost
    resynced(host, 102, "sequence_gap");
    expect(handle.status).toBe("resyncing");
    for (const s of [103, 104, 105]) registry.onData(delta(s), 1); // the late 103 patches nothing
    expect(got()).toEqual(["d:101", "d:102", "reset:gap"]);
    registry.onData(snap(110), 1);
    registry.onData(delta(111), 1);
    expect(got()).toEqual(["snap:110", "d:111"]);
    expect(handle.status).toBe("live");
    expect(registry.counters.gaps).toBe(1);
  });

  it("drops a delta that has no baseline unread, and a live delta without a number is malformed", () => {
    const { registry, host, got } = setup();
    registry.consume(spec());
    registry.onData(delta(1), 1);
    registry.onData({ ...delta(2), s: null }, 1); // no baseline: dropped before anything looks at it
    expect([got(), host.resync.mock.calls.length]).toEqual([[], 0]);
    registry.onData(snap(1), 1);
    registry.onData({ ...delta(2), s: null }, 1); // the codec refuses it; a caller may not have
    resynced(host, 1, "decode_error");
  });
});

describe("live and replay data (C11)", () => {
  it("keeps the streams of one ch apart, each with its own sequence", () => {
    const { registry, got } = setup();
    const liveHandle = registry.consume(spec());
    const replayHandle = registry.consume(spec(), RS);
    registry.onData(snap(100), 1);
    registry.onData(snap(5, { rs: RS, meta: { source: "replay" } }), 1);
    registry.onData(delta(7, { rs: RS }), 1); // a gap in the replay stream...
    expect([replayHandle.status, liveHandle.status]).toEqual(["resyncing", "live"]); // ...not in live
    registry.onData(delta(101), 1);
    expect(got()).toEqual(["snap:100", "d:101"]);
    expect(got(BOOK, RS)).toEqual(["snap:5", "reset:gap"]);
  });

  it("takes source and rs from meta, the binary header flag and the envelope, and is replay once any frame says so", () => {
    const { registry } = setup();
    const byMeta = registry.consume(spec({ ch: "trades.BTCUSDT" }));
    registry.onData(snap(1, { ch: "trades.BTCUSDT", meta: { source: "replay" } }), 1);
    expect([byMeta.source, byMeta.rs]).toEqual(["replay", undefined]);
    const byFlag = registry.consume(spec({ ch: "ticker.BTCUSDT" }));
    expect(byFlag.source).toBe("live");
    registry.onData(snap(1, { ch: "ticker.BTCUSDT", ...binary(bookSnapshot(FLAG_REPLAY)) }), 1);
    expect(byFlag.source).toBe("replay");
    const byEnvelope = registry.consume(spec({ ch: "liquidations.BTCUSDT" }), RS);
    registry.onData(snap(1, { ch: "liquidations.BTCUSDT", rs: RS }), 1);
    expect([byEnvelope.source, byEnvelope.rs]).toEqual(["replay", RS]);
    const sticky = registry.consume(spec({ ch: "metrics.BTCUSDT" }));
    registry.onData(snap(1, { ch: "metrics.BTCUSDT" }), 1);
    registry.onData(delta(2, { ch: "metrics.BTCUSDT", ...binary(bookDelta(FLAG_REPLAY)) }), 1);
    expect(sticky.source).toBe("replay"); // a replay frame makes it replay...
    registry.onData(snap(9, { ch: "metrics.BTCUSDT" }), 1);
    expect(sticky.source).toBe("live"); // ...until a live baseline
  });
});

describe("chunked snapshots (3.6, 7.2)", () => {
  const part = (s: number | null, p: object, id = "set-1") => snap(s, { id, p });
  const bodies = (frames: readonly TopicFrame[]) =>
    frames.flatMap((f) =>
      f.kind === "snap" ? f.bodies.map((b) => (b.e === "j" ? b.p : null)) : [],
    );

  it("delivers a chunked set whole under the last chunk's number; D17: a new id replaces the old set", () => {
    const { registry, handle, take } = live();
    registry.onData(part(null, { tag: "A1" }, "a"), 2);
    registry.onData(part(null, { tag: "A2" }, "a"), 2);
    registry.onData(part(null, { tag: "B1" }, "b"), 2);
    expect([take(), handle.status]).toEqual([[], "resyncing"]); // an incomplete set applies nothing
    registry.onData(part(null, { tag: "B2" }, "b"), 2);
    const last = snap(500, { id: "b", p: { tag: "B3" }, sp: SP, meta: { reason: "initial" } });
    registry.onData(last, 2);
    const frames = take();
    expect(kinds(frames)).toEqual(["snap:500"]);
    expect(bodies(frames)).toEqual([{ tag: "B1" }, { tag: "B2" }, { tag: "B3" }]);
    expect(frames[0]).toMatchObject({ decodeMs: 6, sp: SP, meta: { reason: "initial" } });
    expect(handle.status).toBe("live");
  });

  it("assembles a binary set by the partial bit; a chunk whose markers disagree is malformed (C10)", () => {
    let tick = 0; // each validation reads the clock twice, 3 ms apart
    const { registry, host, take, got } = live({ now: () => (tick += 3) });
    registry.onData(snap(null, { id: "bin", ...binary(bookSnapshot(FLAG_PARTIAL)) }), 1);
    registry.onData(snap(40, { id: "bin", ...binary(bookSnapshot()) }), 1);
    const frames = take();
    expect(kinds(frames)).toEqual(["snap:40"]);
    expect(frames[0]).toMatchObject({ decodeMs: 8 }); // two chunks of 1 ms decode and 3 ms validation
    registry.onData(snap(null, { id: "bad", ...binary(bookSnapshot()) }), 1); // "more to come", but last
    resynced(host, 40, "decode_error");
    expect(got()).toEqual(["reset:malformed"]);
  });

  it("drops a set that passes the held-bytes cap, resyncs, and ignores the rest of it", () => {
    const cost = part(null, { n: 1 }).size * JSON_HEAP_FACTOR + FRAME_OVERHEAD_BYTES;
    const { registry, host, handle, got } = live({ maxHeldBytes: 2 * cost });
    for (const n of [1, 2, 3]) registry.onData(part(null, { n }), 1); // the third is over the cap
    resynced(host, 100, "state_corrupt");
    expect([registry.heldBytes, registry.counters.overflows]).toEqual([0, 1]);
    expect(got()).toEqual(["reset:overflow"]);
    registry.onData(part(700, { n: 4 }), 1); // the set's last chunk alone is not a snapshot
    expect([got(), handle.status]).toEqual([[], "resyncing"]);
    registry.onData(snap(800), 1);
    expect(got()).toEqual(["snap:800"]);
  });

  it("a stream that has no baseline yet stays pending while its first snapshot is assembled", () => {
    const { registry, host, take } = setup();
    const handle = registry.consume(spec());
    registry.onData(part(null, { tag: "A1" }), 1);
    expect([handle.status, take()]).toEqual(["pending", []]);
    registry.onData(part(7, { tag: "A2" }), 1);
    expect([handle.status, host.resync.mock.calls.length]).toEqual(["live", 0]);
  });

  it("a delta while a set is incomplete says the server dropped the set: the stream is voided and a snap asked for", () => {
    const { registry, host, handle, got } = live();
    registry.onData(part(null, { n: 1 }), 1);
    registry.onData(delta(101), 1); // nothing will complete the set now
    expect([got(), handle.status, registry.heldBytes]).toEqual([["reset:gap"], "resyncing", 0]);
    resynced(host, 100, "state_corrupt");
    registry.onData(part(null, { n: 2 }), 1); // the rest of the dropped set is refused
    registry.onData(part(300, { n: 3 }), 1);
    expect(got()).toEqual([]);
    registry.onData(snap(400), 1);
    expect([got(), handle.status]).toEqual([["snap:400"], "live"]);
    registry.onData(delta(401), 1); // with no set held, a delta is only applied or dropped
    expect([got(), host.resync.mock.calls.length]).toEqual([["d:401"], 1]);
  });
});

describe("malformed data (C10)", () => {
  const badDelta = () => {
    const bad = bookDelta();
    bad[0] = 0; // not "CVWB"
    return binary(bad);
  };

  it("a malformed binary body voids the stream and asks for a resync", () => {
    const { registry, host, handle, got } = live();
    registry.onData(delta(101, badDelta()), 1);
    resynced(host, 100, "decode_error");
    expect([handle.status, registry.counters.malformed]).toEqual(["resyncing", 1]);
    expect(got()).toEqual(["reset:malformed"]);
    registry.onData(delta(102, binary(bookDelta())), 1); // valid, but there is no baseline now
    registry.onData(snap(110), 1);
    expect([got(), handle.status]).toEqual([["snap:110"], "live"]);
  });

  it("a stream that is already void is not voided again: its bad deltas are dropped unread", () => {
    const { registry, host, got } = live();
    for (let s = 101; s <= 120; s += 1) registry.onData(delta(s, badDelta()), 1);
    expect([got(), host.resync.mock.calls.length]).toEqual([["reset:malformed"], 1]);
    expect(registry.counters.malformed).toBe(1);
  });

  it("a second bad snapshot asks again, as the first may have been the answer, but resets once", () => {
    const { registry, host, got } = live();
    const bad = bookSnapshot();
    bad[0] = 0;
    registry.onData(snap(200, binary(bad)), 1);
    registry.onData(snap(201, binary(bad)), 1);
    expect([got(), host.resync.mock.calls.length]).toEqual([["reset:malformed"], 2]);
    registry.onData(snap(300), 1);
    registry.onData(delta(302), 1); // the next loss is a new one: it resets again
    expect(got()).toEqual(["snap:300", "reset:gap"]);
  });

  it("a malformed first chunk of a new set drops the held set and refuses the rest of the new one", () => {
    const { registry, host, got } = live();
    registry.onData(snap(null, { id: "a", ...binary(bookSnapshot(FLAG_PARTIAL)) }), 1);
    const bad = bookSnapshot(FLAG_PARTIAL);
    bad[4] = 9; // an unknown format version
    registry.onData(snap(null, { id: "b", ...binary(bad) }), 1);
    registry.onData(snap(60, { id: "b", ...binary(bookSnapshot()) }), 1); // b's last chunk alone
    expect(registry.heldBytes).toBe(0);
    expect([got(), host.resync.mock.calls.length]).toEqual([["reset:malformed"], 1]); // refused, not a second loss
  });
});

describe("bars (C3)", () => {
  it("delivers an unconfirmed bar untouched, never as closed, with the delta's meta", () => {
    const { registry, take } = setup();
    registry.consume(spec({ ch: BARS }));
    const forming = { bars: [{ index: 1, confirm: false }] };
    registry.onData(snap(1, { ch: BARS, p: forming }), 1);
    const meta = { include_delta: true };
    const update = data({ t: "d", ch: BARS, s: 2, sp: SP, meta, ...binary(bars(false)) });
    registry.onData(update, 1);
    const [first, second] = take(BARS);
    expect(first).toMatchObject({ kind: "snap", bodies: [{ e: "j", p: forming }] });
    if (second?.kind !== "d" || second.body.e !== "b64") throw new Error("expected a b64 delta");
    expect(second).toMatchObject({ sp: SP, ts: update.ts, meta }); // `include_delta` is how a 0 delta reads (6.1)
    expect(second.body).toBe(update.body); // the very body that arrived: nothing read or rewritten
    expect(decodeBars(new Uint8Array(second.body.bytes)).bars[0]?.confirmed).toBe(false);
    expect(decodeBars(bars(true)).bars[0]?.confirmed).toBe(true); // the builder sets the bit it claims
  });
});

describe("consumers", () => {
  it("counts consumers per stream; a newcomer to a baselined stream asks for a baseline of its own", () => {
    const { registry, host, handle, got } = live();
    const late = registry.consume(spec({ paneId: "p2" }));
    expect(host.subscribe).toHaveBeenCalledTimes(1);
    resynced(host, 100, "client_restart");
    registry.onData(snap(150), 1); // delivered like any snap: the engine gives it to the newcomer
    expect(got()).toEqual(["snap:150"]);
    late.release();
    late.release(); // idempotent
    expect(host.unsubscribe).not.toHaveBeenCalled();
    handle.release(); // the last consumer: the stream and its baseline are forgotten
    expect(host.unsubscribe).toHaveBeenCalledTimes(1);
    const again = registry.consume(spec());
    expect([again.status, host.resync.mock.calls.length]).toEqual(["pending", 1]);
  });

  it("joins a stream that has no baseline yet without asking for one, and unsubscribes when the last leaves", () => {
    const { registry, host, got } = setup();
    const a = registry.consume(spec());
    const b = registry.consume(spec({ paneId: "p2" }));
    expect(host.resync).not.toHaveBeenCalled(); // the first snap serves both
    expect([Object.isFrozen(a.effective), a.effective]).toEqual([true, {}]); // no options until S2d
    a.release();
    expect(host.unsubscribe).not.toHaveBeenCalled();
    b.release();
    expect(host.unsubscribe).toHaveBeenCalledWith(BOOK, undefined);
    registry.onData(snap(2), 1); // nobody consumes it any more: dropped, not thrown
    expect(got()).toEqual([]);
  });

  it("a released stream gives up the chunks it held", () => {
    const { registry, handle } = live();
    registry.onData(snap(null, { id: "a", p: { n: 1 } }), 1);
    expect(registry.heldBytes).toBeGreaterThan(0);
    handle.release();
    expect(registry.heldBytes).toBe(0);
  });

  it("dispose forgets every stream: the chunks held, the baselines and what waits", () => {
    const { registry, host, handle } = live();
    registry.onData(snap(null, { id: "a", p: { n: 1 } }), 1); // a chunk is held
    registry.dispose();
    handle.release(); // the registry holds nothing of it any more: no `unsub` either
    expect([registry.heldBytes, host.unsubscribe.mock.calls.length]).toEqual([0, 0]);
    registry.onData(delta(101), 1); // the stream is gone
    expect(host.resync).not.toHaveBeenCalled();
    expect(registry.consume(spec()).status).toBe("pending"); // and a new one starts from nothing
  });
});

describe("resync budget (7.5)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  /** `n` gaps, each repaired by a snap: the last baseline is 100 + 10 n. */
  function gaps(registry: ReturnType<typeof setup>["registry"], n: number): number {
    for (let i = 0; i < n; i += 1) {
      registry.onData(delta(100 + 10 * i + 2), 1);
      registry.onData(snap(100 + 10 * (i + 1)), 1);
    }
    return 100 + 10 * n;
  }

  it("defers the sixth resync inside a minute, and never sends it early", () => {
    const { registry, host, handle } = live();
    const base = gaps(registry, 5);
    registry.onData(delta(base + 2), 1);
    expect(host.resync).toHaveBeenCalledTimes(5);
    expect([handle.status, registry.counters.resyncsDeferred]).toEqual(["resyncing", 1]);
    vi.advanceTimersByTime(60_999);
    expect(host.resync).toHaveBeenCalledTimes(5);
    vi.advanceTimersByTime(1);
    expect(host.resync).toHaveBeenCalledTimes(6);
    resynced(host, base, "sequence_gap");
    expect(registry.counters.resyncsSent).toBe(6);
  });

  it("drops the deferred resync when a snap repairs the stream first", () => {
    const { registry, host, handle } = live();
    const base = gaps(registry, 5);
    registry.onData(delta(base + 2), 1);
    registry.onData(snap(base + 50), 1); // the gateway sent one anyway (7.4)
    vi.advanceTimersByTime(120_000);
    expect(host.resync).toHaveBeenCalledTimes(5);
    expect(handle.status).toBe("live");
  });

  it("a snap of one stream does not cancel a resync that another stream of the ch waits for", () => {
    const { registry, host } = live();
    registry.consume(spec(), RS);
    const base = gaps(registry, 5);
    registry.onData(delta(base + 2), 1); // the sixth: it waits
    registry.onData(snap(1, { rs: RS }), 1); // the replay stream's first baseline: nothing was repaired
    vi.advanceTimersByTime(61_000);
    expect(host.resync).toHaveBeenCalledTimes(6);
  });

  it("dispose drops a resync that waits", () => {
    const { registry, host } = live();
    const base = gaps(registry, 5);
    registry.onData(delta(base + 2), 1);
    registry.dispose();
    vi.advanceTimersByTime(120_000);
    expect(host.resync).toHaveBeenCalledTimes(5);
  });

  it("a released stream takes the resync it waits for with it, and keeps the window while a twin is left", () => {
    const { registry, host, handle } = live();
    const twin = registry.consume(spec(), RS);
    const base = gaps(registry, 5);
    registry.onData(delta(base + 2), 1); // the sixth waits
    handle.release(); // the window stays with the twin, but the resync goes with its stream
    vi.advanceTimersByTime(120_000);
    expect([host.resync.mock.calls.length, twin.status]).toEqual([5, "pending"]);
  });

  it("a released stream leaves a resync that its twin still waits for", () => {
    const { registry, host, handle } = live();
    registry.consume(spec(), RS);
    registry.onData(snap(1, { rs: RS }), 1);
    gaps(registry, 5);
    registry.onData(delta(3, { rs: RS }), 1); // the twin loses its baseline: the sixth resync waits
    handle.release();
    vi.advanceTimersByTime(61_000);
    expect(host.resync).toHaveBeenCalledTimes(6);
  });

  it("a released stream takes the gateway's resync window with it, unless a twin of the ch is left", () => {
    const { registry, host, handle } = live();
    const twin = registry.consume(spec(), RS);
    const base = gaps(registry, 5);
    handle.release(); // the replay stream of the ch remains, and the window with it
    const again = registry.consume(spec());
    registry.onData(snap(base), 1);
    registry.onData(delta(base + 2), 1); // a sixth resync of the ch inside the minute: it waits
    expect(host.resync).toHaveBeenCalledTimes(5);
    again.release(); // and a waiting resync does not outlive its stream
    twin.release(); // now no stream of the ch is left: the next subscription has a new window
    registry.consume(spec());
    registry.onData(snap(1), 1);
    registry.onData(delta(3), 1);
    expect(host.resync).toHaveBeenCalledTimes(6);
    vi.advanceTimersByTime(120_000);
    expect(host.resync).toHaveBeenCalledTimes(6);
  });
});
