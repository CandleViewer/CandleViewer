// E17-T04 S2 (C2-C5, C10, C11): what the registry delivers and asks for, driven by real decoded frames.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decodeBars } from "@candleviewer/protocol";
import type { ConsumerSpec, TopicFrame } from "../../../src/lib/ws/api";
import { FRAME_OVERHEAD_BYTES, JSON_HEAP_FACTOR } from "../../../src/lib/ws/core/snapshotAssembler";
import {
  createSubscriptionRegistry,
  type RegistryOptions,
} from "../../../src/lib/ws/core/subscriptions";
import {
  decodeFrame,
  type ControlOf,
  type ControlType,
  type DataFrame,
} from "../../../src/lib/ws/protocol/codec";
import { b64, bars, bookDelta, bookSnapshot, FLAG_PARTIAL, FLAG_REPLAY } from "./support/cvwb";

const BOOK = "book.BTCUSDT.50";
const BARS = "bars.BTCUSDT.time.1";
const RS = "bb000000-0000-4000-8000-000000000001";
const SP = "0123456789abcdef";
const LIVE = { rs: undefined }; // the scope of a request for the live stream
const wire = (frame: object): string => JSON.stringify(frame);

function data(frame: object): DataFrame {
  const decoded = decodeFrame(wire({ ts: 1_789_132_262_000, e: "j", p: {}, ...frame }));
  if (decoded.t !== "snap" && decoded.t !== "d") throw new Error(`not data: ${wire(decoded)}`);
  return decoded;
}
const snap = (s: number | null, over: object = {}) => data({ t: "snap", ch: BOOK, s, ...over });
const delta = (s: number, over: object = {}) => data({ t: "d", ch: BOOK, s, ...over });
const binary = (bytes: Uint8Array) => ({ e: "b64", p: b64(bytes) });

function control<T extends ControlType>(t: T, p: object, over: object = {}): ControlOf<T> {
  const decoded = decodeFrame(wire({ t, ...over, p }));
  if (decoded.t !== t) throw new Error(`${t} did not decode: ${wire(decoded)}`);
  return decoded as ControlOf<T>;
}
const subOk = (effective: unknown = {}, ch = BOOK, extra: object = {}) =>
  control("sub_ok", { results: [{ ch, ok: true, sub_id: "s_01", effective, ...extra }] });
const refused = (code = "replay_session_not_found") =>
  control("sub_ok", { results: [{ ch: BOOK, ok: false, error: { code, message: "m" } }] });
const ctlOk = (effective: object, resnapshot = false) =>
  control("ctl_ok", { effective, ...(resnapshot && { resnapshot }) }, { ch: BOOK });
const unsubOk = (ok = true) => control("unsub_ok", { results: [{ ch: BOOK, ok }] });
const revoked = (reason: string, extra: object = {}, ch = BOOK) =>
  control("revoked", { reason, message: "m", ...extra }, { ch });

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
const resynced = (
  host: { resync: unknown },
  last_seq: number | null,
  reason: string,
  rs?: string,
  subId?: string,
) => expect(host.resync).toHaveBeenCalledWith(BOOK, rs, { last_seq, reason }, subId);

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
  it("a resync names the replay stream it is for: a bare ch would get the live stream's snapshot", () => {
    const { registry, host } = setup();
    registry.consume(spec());
    registry.consume(spec(), RS);
    registry.onData(snap(100), 1);
    registry.onData(snap(5, { rs: RS, meta: { source: "replay" } }), 1);
    registry.onData(delta(7, { rs: RS }), 1); // a gap in the replay stream
    registry.onData(snap(8, { rs: RS }), 1);
    registry.consume(spec({ paneId: "p2" }), RS); // another replay consumer needs a baseline of its own
    registry.onData(delta(102), 1); // a gap in the live stream
    const asked = host.resync.mock.calls.map(([, rs, payload]) => [rs, payload.reason]);
    expect(asked).toEqual([
      [RS, "sequence_gap"],
      [RS, "client_restart"],
      [undefined, "sequence_gap"],
    ]);
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

  it("stops asking when a snapshot passes the cap twice in a row: the server sends the same one again", () => {
    const cost = part(null, { n: 1 }).size * JSON_HEAP_FACTOR + FRAME_OVERHEAD_BYTES;
    const { registry, host, got } = live({ maxHeldBytes: 2 * cost });
    const tooBig = (id: string) => {
      for (const n of [1, 2, 3]) registry.onData(part(null, { n }, id), 1); // the third is over the cap
    };
    tooBig("a");
    tooBig("b"); // the answer to the resync
    expect([host.resync.mock.calls.length, registry.counters.overflows]).toEqual([1, 2]);
    expect(got()).toEqual(["reset:overflow"]); // once: consumers hold nothing to clear
    registry.onData(part(null, { n: 1 }, "c"), 1);
    registry.onData(delta(101), 1); // a delta amid chunks would ask, but this stream is out of asks
    expect(host.resync).toHaveBeenCalledTimes(1);
    registry.onData(snap(300), 1); // one that fits: live again, and it asks if it loses its baseline
    registry.onData(delta(305), 1);
    expect(host.resync).toHaveBeenCalledTimes(2);
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

  it("a first chunk whose markers disagree refuses the rest of its set: [b2, b3] is never a snapshot", () => {
    const { registry, got } = live();
    registry.onData(snap(null, { id: "a", ...binary(bookSnapshot(FLAG_PARTIAL)) }), 1);
    registry.onData(snap(null, { id: "b", ...binary(bookSnapshot()) }), 1); // "more to come", no partial bit
    registry.onData(snap(null, { id: "b", ...binary(bookSnapshot(FLAG_PARTIAL)) }), 1); // b2
    registry.onData(snap(60, { id: "b", ...binary(bookSnapshot()) }), 1); // b3, the last
    expect([registry.heldBytes, got()]).toEqual([0, ["reset:malformed"]]);
  });
});

describe("options (C4) and server strings", () => {
  it("requested 5 reads back as effective 50; ctl_ok retunes without losing the rest", () => {
    const { registry, host, got } = setup();
    const handle = registry.consume(spec({ opts: { throttle_ms: 5 } }));
    expect(host.subscribe).toHaveBeenCalledWith(spec({ opts: { throttle_ms: 5 } }), undefined);
    registry.onSubOk(subOk("not an object", BOOK, { sub_id: "s".repeat(65) }), LIVE); // neither is used
    expect([handle.effective, handle.subId]).toEqual([{}, undefined]);
    registry.onSubOk(subOk("not an object", BOOK, { sub_id: "" }), LIVE); // 1 to 64 characters: no id either
    expect(handle.subId).toBeUndefined();
    registry.onSubOk(subOk({}, BOOK, { sub_id: "s".repeat(64) }), LIVE); // the longest one kept
    expect(handle.subId).toBe("s".repeat(64));
    registry.onSubOk(subOk({ throttle_ms: 50, encoding: "binary" }), LIVE);
    expect(handle.effective).toEqual({ throttle_ms: 50, encoding: "binary" });
    expect(handle.subId).toBe("s_01");
    registry.onSubOk(subOk("not an object", BOOK, { sub_id: "" }), LIVE); // nor does it replace the one kept
    expect(handle.subId).toBe("s_01");
    registry.onCtlOk(control("ctl_ok", { effective: { throttle_ms: 1 } }), LIVE); // names no topic: ignored
    registry.onCtlOk(ctlOk({ throttle_ms: 200 }), LIVE);
    registry.onCtlOk(control("ctl_ok", { effective: {}, resnapshot: false }, { ch: BOOK }), LIVE);
    expect(handle.effective).toEqual({ throttle_ms: 200, encoding: "binary" });
    expect(got()).toEqual([]); // no `resnapshot`: the stream's state is left alone
  });

  it("keeps __proto__ and constructor keys of the options as plain data", () => {
    const { registry } = setup();
    const handle = registry.consume(spec());
    const hostile = '{"__proto__":{"polluted":true},"constructor":{"x":1},"throttle_ms":50}';
    const one = `{"ch":"${BOOK}","ok":true,"effective":${hostile}}`;
    const sub = decodeFrame(`{"t":"sub_ok","p":{"results":[${one}]}}`);
    const ctl = decodeFrame(`{"t":"ctl_ok","ch":"${BOOK}","p":{"effective":${hostile}}}`);
    registry.onSubOk(sub as ControlOf<"sub_ok">, LIVE);
    registry.onCtlOk(ctl as ControlOf<"ctl_ok">, LIVE);
    expect(Object.getPrototypeOf(handle.effective)).toBe(Object.prototype);
    expect(({} as Record<string, unknown>)["polluted"]).toBeUndefined();
    expect(Object.hasOwn(handle.effective, "constructor")).toBe(true);
  });

  it("ends a stream the server refused, and counts a forced snapshot", () => {
    const { registry, got } = setup();
    const ended = registry.consume(spec());
    registry.onSubOk(refused("forbidden"), LIVE);
    expect([ended.status, got()]).toEqual(["revoked", ["reset:revoked"]]);
    registry.consume(spec({ ch: BARS }));
    registry.onSubOk(subOk({}, BARS, { snapshot_forced: false }), LIVE);
    expect(registry.counters.forcedSnapshots).toBe(0);
    registry.onSubOk(subOk({}, BARS, { snapshot_forced: true }), LIVE);
    expect(registry.counters.forcedSnapshots).toBe(1);
  });

  it("shares an effective that is a read-only copy all the way down", () => {
    const { registry } = setup();
    const handle = registry.consume(spec());
    expect(Object.isFrozen(handle.effective)).toBe(true);
    const frame = subOk({ throttle_ms: 50, metrics: ["cvd"] });
    registry.onSubOk(frame, LIVE);
    expect([handle.effective, handle.effective["metrics"]].map((v) => Object.isFrozen(v))).toEqual([
      true,
      true,
    ]);
    registry.onCtlOk(ctlOk({ depth: { max: 200 } }), LIVE);
    const shared = [handle.effective, handle.effective["metrics"], handle.effective["depth"]];
    expect(shared.map((v) => Object.isFrozen(v))).toEqual([true, true, true]);
    expect(handle.effective["metrics"]).toEqual(["cvd"]); // an array stays an array
    expect(Object.isFrozen(frame.p.results[0]?.effective)).toBe(false); // the frame is left as it came
  });
});

describe("options too deep or too big", () => {
  // JSON.parse accepts a million levels and a 4 MiB frame holds a million elements: `effective` can arrive so.
  const deep = (n: number) => '{"a":'.repeat(n) + "1" + "}".repeat(n);
  const subWith = (options: string) =>
    decodeFrame(
      `{"t":"sub_ok","p":{"results":[{"ch":"${BOOK}","ok":true,"effective":${options}}]}}`,
    ) as ControlOf<"sub_ok">;
  const ctlWith = (options: string, extra = "") =>
    decodeFrame(
      `{"t":"ctl_ok","ch":"${BOOK}","p":{"effective":${options}${extra}}}`,
    ) as ControlOf<"ctl_ok">;

  it("keeps eight levels and ignores nine, and a hundred thousand throw nothing", () => {
    const { registry } = setup();
    const handle = registry.consume(spec());
    registry.onSubOk(subOk({ throttle_ms: 50 }), LIVE);
    registry.onSubOk(subWith(deep(100_000)), LIVE);
    registry.onCtlOk(ctlWith(deep(100_000)), LIVE);
    expect(handle.effective).toEqual({ throttle_ms: 50 }); // what it had stays
    registry.onSubOk(subWith(deep(9)), LIVE);
    expect(handle.effective).toEqual({ throttle_ms: 50 });
    registry.onSubOk(subWith(deep(8)), LIVE);
    expect(Object.keys(handle.effective)).toEqual(["a"]);
    registry.onCtlOk(ctlWith(deep(9)), LIVE);
    expect(Object.keys(handle.effective)).toEqual(["a"]); // a retune too deep changed nothing
    registry.onCtlOk(ctlWith('{"b":1}'), LIVE);
    expect(Object.keys(handle.effective)).toEqual(["a", "b"]);
  });

  it("an effective of 100 000 keys or a 1 M-element list is ignored like one too deep", () => {
    const { registry } = setup();
    const handle = registry.consume(spec());
    registry.onSubOk(subOk({ throttle_ms: 50 }), LIVE);
    const keys = `{${Array.from({ length: 100_000 }, (_, i) => `"k${i}":1`).join(",")}}`;
    const empties = `{"v":[${new Array<string>(1_000_000).fill("[]").join(",")}]}`;
    for (const options of [keys, empties]) {
      registry.onSubOk(subWith(options), LIVE);
      registry.onCtlOk(ctlWith(options), LIVE);
    }
    expect(handle.effective).toEqual({ throttle_ms: 50 }); // nothing thrown or copied, what it had stays
  }, 30_000); // four parses of a million values: slow on a busy machine, not a performance budget

  it("keeps 1 024 values and ignores 1 025", () => {
    const { registry } = setup();
    const handle = registry.consume(spec());
    const list = (n: number) => `{"v":[${new Array<string>(n).fill("1").join(",")}]}`;
    const length = () => {
      const items = handle.effective["v"];
      return Array.isArray(items) ? items.length : -1;
    };
    registry.onSubOk(subWith(list(1022)), LIVE); // the root, the list and 1 022 elements
    expect(length()).toBe(1022);
    registry.onSubOk(subWith(list(1023)), LIVE);
    registry.onCtlOk(ctlWith(list(1023)), LIVE);
    expect(length()).toBe(1022);
  });

  const fresh = (prefix: string, n: number) =>
    `{${Array.from({ length: n }, (_, i) => `"${prefix}${i}":1`).join(",")}}`;
  const keyCount = (options: object) => Object.keys(options).length;

  it("two retunes of 600 fresh keys each: the second is ignored and effective keeps the first 600", () => {
    const { registry } = setup();
    const handle = registry.consume(spec());
    registry.onCtlOk(ctlWith(fresh("a", 600)), LIVE);
    registry.onCtlOk(ctlWith(fresh("b", 600)), LIVE); // 1 200 values between them: no longer options
    expect(Object.keys(handle.effective)).toEqual(Array.from({ length: 600 }, (_, i) => `a${i}`));
  });

  it("effective never passes 1 024 values across retunes: 300 retunes of 1 000 fresh keys keep the first", () => {
    const { registry } = setup();
    const handle = registry.consume(spec());
    for (let i = 0; i < 300; i += 1) {
      registry.onCtlOk(ctlWith(fresh(`r${i}k`, 1000)), LIVE);
      expect(keyCount(handle.effective)).toBeLessThanOrEqual(1024);
    }
    expect(keyCount(handle.effective)).toBe(1000);
  });

  it("retunes add up to the limit and stop there: 10 fresh keys at a time end at 1 020", () => {
    const { registry } = setup();
    const handle = registry.consume(spec());
    for (let i = 0; i < 110; i += 1) registry.onCtlOk(ctlWith(fresh(`r${i}k`, 10)), LIVE);
    expect(keyCount(handle.effective)).toBe(1020); // the root and 1 023 values would fit; the 103rd retune would make 1 030
  });

  it("counts the size of a list from its length alone: nothing of it is enumerated or read", () => {
    const { registry } = setup();
    const handle = registry.consume(spec());
    const touched: (string | symbol)[] = [];
    const list = new Proxy(new Array<number>(5000).fill(1), {
      get: (target, key, receiver) => {
        touched.push(key);
        return Reflect.get(target, key, receiver);
      },
      ownKeys: (target) => {
        touched.push("ownKeys");
        return Reflect.ownKeys(target);
      },
    });
    const frame = ctlOk({});
    Object.assign(frame.p, { effective: { v: list } });
    registry.onCtlOk(frame, LIVE);
    expect(handle.effective).toEqual({}); // 5 000 elements: ignored
    expect(touched).toEqual(["length"]);
  });

  it("still voids the stream when the resnapshot comes with options too deep to keep", () => {
    const { registry, handle, got } = live();
    registry.onCtlOk(ctlWith(deep(50), ',"resnapshot":true'), LIVE);
    expect([handle.effective, handle.status, got()]).toEqual([
      {},
      "resyncing",
      ["reset:resnapshot"],
    ]);
  });
});

describe("resnapshot, narrowing and unsubscribe (C5)", () => {
  it("ctl_ok with resnapshot voids the state and asks for nothing: the snap follows by itself", () => {
    const { registry, host, handle, got } = live();
    registry.onData(delta(101), 1);
    registry.onCtlOk(ctlOk({ depth: 200 }, true), LIVE);
    expect([handle.status, handle.effective["depth"]]).toEqual(["resyncing", 200]);
    registry.onData(snap(103, { meta: { reason: "reconfigure", previous_seq: 101 } }), 1);
    expect(got()).toEqual(["d:101", "reset:resnapshot", "snap:103"]);
    expect(host.resync).not.toHaveBeenCalled();
  });

  it("a delta on a stream that resnapshot voided says the server went on without the snap: one resync", () => {
    const { registry, host, handle, got } = live();
    registry.onCtlOk(ctlOk({}, true), LIVE);
    expect(host.resync).not.toHaveBeenCalled(); // the snap follows by itself
    for (let s = 101; s <= 120; s += 1) registry.onData(delta(s), 1);
    resynced(host, 100, "state_corrupt");
    expect([host.resync.mock.calls.length, handle.status, got()]).toEqual([
      1,
      "resyncing",
      ["reset:resnapshot"],
    ]);
    registry.onData(snap(200), 1);
    registry.onData(delta(201), 1);
    expect(got()).toEqual(["snap:200", "d:201"]);
  });

  it("a resnapshot the snap answers asks for nothing, and a later gap is an ordinary one", () => {
    const { registry, host } = live();
    registry.onCtlOk(ctlOk({}, true), LIVE);
    registry.onData(snap(200), 1);
    registry.onData(delta(202), 1); // a gap after the snap
    expect(host.resync).toHaveBeenCalledTimes(1);
    resynced(host, 200, "sequence_gap");
    registry.onData(delta(203), 1); // dropped: it is not a second ask
    expect(host.resync).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["resnapshot", () => ctlOk({}, true), 0],
    [
      "a narrowing revoked",
      () => revoked("account_scope_changed", { resubscribe_allowed: true }),
      1,
    ],
  ])(
    "after %s the rest of the held set is refused: its tail is never a baseline",
    (_what, frame, asks) => {
      const { registry, host, handle } = live();
      registry.onData(snap(null, { id: "set-1", p: { n: 1 } }), 1);
      const f = frame();
      if (f.t === "ctl_ok") registry.onCtlOk(f, LIVE);
      else registry.onRevoked(f);
      registry.onData(snap(null, { id: "set-1", p: { n: 2 } }), 1);
      registry.onData(snap(300, { id: "set-1", p: { n: 3 } }), 1);
      expect([handle.status, host.resync.mock.calls.length]).toEqual(["resyncing", asks]);
    },
  );

  it("an unsub_ok concerns only a stream with no baseline yet: what it holds is the old subscription's", () => {
    const { registry, handle, got } = live();
    registry.onUnsubOk(unsubOk(), LIVE); // a stream with a baseline is not the one unsubscribed
    registry.onData(delta(101), 1);
    expect([handle.status, got()]).toEqual(["live", ["d:101"]]);
    registry.onData(delta(103), 1); // a gap: resyncing, and still not the one unsubscribed
    registry.onUnsubOk(unsubOk(), LIVE);
    expect([handle.status, got()]).toEqual(["resyncing", ["reset:gap"]]);
    const t = setup(); // re-subscribed after an unsub: a chunk of the old subscription may be held
    const again = t.registry.consume(spec());
    t.registry.onData(snap(null, { id: "old", p: { n: 1 } }), 1);
    t.registry.onUnsubOk(unsubOk(false), LIVE); // refused: nothing happens
    expect([t.registry.heldBytes > 0, t.got()]).toEqual([true, []]);
    t.registry.onUnsubOk(unsubOk(), LIVE);
    expect([t.registry.heldBytes, t.got(), again.status]).toEqual([
      0,
      ["reset:unsubscribed"],
      "pending",
    ]);
    t.registry.onData(snap(500), 1);
    expect(again.status).toBe("live");
  });

  it("an unsub_ok with a scope reaches the stream of its request only", () => {
    const { registry, got } = setup();
    registry.consume(spec());
    registry.consume(spec(), RS);
    registry.onData(snap(null, { id: "a", p: { n: 1 } }), 1); // the live stream holds a chunk
    registry.onData(snap(null, { id: "b", rs: RS, p: { n: 1 } }), 1); // and so does the replay one
    registry.onUnsubOk(unsubOk(), { rs: RS });
    expect([got(), got(BOOK, RS), registry.heldBytes > 0]).toEqual([
      [],
      ["reset:unsubscribed"],
      true,
    ]);
    registry.onUnsubOk(unsubOk(), LIVE); // the live stream's turn
    expect([got(), got(BOOK, RS), registry.heldBytes]).toEqual([["reset:unsubscribed"], [], 0]);
  });

  it.each([
    ["an ending revoked", () => revoked("session_revoked")],
    ["a narrowing revoked", () => revoked("account_scope_changed", { resubscribe_allowed: true })],
    ["ctl_ok with resnapshot", () => ctlOk({}, true)],
  ])("%s discards the set held for the topic", (_what, frame) => {
    const { registry } = live();
    registry.onData(snap(null, { id: "set-1", p: { n: 1 } }), 1);
    expect(registry.heldBytes).toBeGreaterThan(0);
    const f = frame();
    if (f.t === "ctl_ok") registry.onCtlOk(f, LIVE);
    else registry.onRevoked(f);
    expect(registry.heldBytes).toBe(0);
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

describe("revocation (9.5)", () => {
  it.each(["session_revoked", "topic_removed"])("%s ends it", (reason) => {
    const { registry, host, handle, got } = live();
    registry.onRevoked(revoked(reason));
    expect(handle.status).toBe("revoked");
    expect(got()).toEqual(["reset:revoked"]);
    registry.onData(snap(200), 1); // nothing more is delivered to an ended stream, not even a snapshot
    registry.onData(delta(201), 1);
    expect(got()).toEqual([]);
    const again = registry.consume(spec()); // a new consumer starts a fresh subscription
    expect([host.subscribe.mock.calls.length, again.status]).toEqual([2, "pending"]);
    handle.release(); // the dead stream's last handle: nothing to unsubscribe, the new stream untouched
    expect(host.unsubscribe).not.toHaveBeenCalled();
    expect(again.status).toBe("pending");
  });

  it("an account_scope_changed that keeps accounts continues, with the old rows voided", () => {
    const { registry, host, handle, got } = live();
    registry.onRevoked(revoked("account_scope_changed", { resubscribe_allowed: true }));
    expect(handle.status).toBe("resyncing"); // not revoked
    expect(got()).toEqual(["reset:narrowed"]);
    resynced(host, 100, "state_corrupt");
    registry.onData(snap(101, { meta: { reason: "reconfigure" } }), 1);
    expect(handle.status).toBe("live");
    handle.release();
    expect(host.unsubscribe).toHaveBeenCalledWith(BOOK, undefined);
  });

  it.each([
    ["account_scope_changed", false],
    ["session_revoked", true],
  ])("a %s revoked with resubscribe_allowed %s ends the subscription", (reason, resubscribe) => {
    const { registry, host, handle } = live();
    registry.onRevoked(control("revoked", { reason: "session_revoked", message: "m" })); // no topic
    registry.onRevoked(revoked("session_revoked", {}, "orders")); // a topic nobody consumes
    expect(handle.status).toBe("live");
    registry.onRevoked(revoked(reason, { resubscribe_allowed: resubscribe }));
    expect(handle.status).toBe("revoked");
    handle.release();
    expect(host.unsubscribe).not.toHaveBeenCalled(); // the server already ended it
  });

  it("an ended stream gets no control frame: a second revoked, a refusal or a narrowing does nothing", () => {
    const { registry, host, handle, got } = live();
    registry.onRevoked(revoked("session_revoked"));
    expect(got()).toEqual(["reset:revoked"]);
    registry.onRevoked(revoked("session_revoked"));
    registry.onRevoked(revoked("account_scope_changed", { resubscribe_allowed: true }));
    registry.onSubOk(refused(), LIVE);
    registry.onCtlOk(ctlOk({ depth: 200 }, true), LIVE);
    expect([handle.status, got(), host.resync.mock.calls.length]).toEqual(["revoked", [], 0]);
    expect(handle.effective).toEqual({}); // and its options are not retuned
  });
});

describe("a resync names the subscription, once sub_ok has given its id (#572)", () => {
  it("carries sub_id beside the replay session", () => {
    const { registry, host } = live();
    registry.onData(delta(102), 1); // a gap before any sub_ok: no id to name yet
    resynced(host, 100, "sequence_gap");
    registry.onSubOk(subOk({}), LIVE);
    registry.onData(snap(110), 1);
    registry.onData(delta(112), 1);
    resynced(host, 110, "sequence_gap", undefined, "s_01");
    const replay = registry.consume(spec(), RS);
    registry.onSubOk(subOk({}, BOOK, { sub_id: "s_02" }), { rs: RS });
    registry.onData(snap(5, { rs: RS }), 1);
    registry.onData(delta(7, { rs: RS }), 1);
    resynced(host, 5, "sequence_gap", RS, "s_02");
    expect(replay.subId).toBe("s_02");
  });
});

describe("a control reply names a ch, not a stream (23 11, #572)", () => {
  /** A live and a replay stream of one ch, each with a baseline: no reply says which of them it is for. */
  function pair() {
    const t = setup();
    const liveHandle = t.registry.consume(spec());
    const replayHandle = t.registry.consume(spec(), RS);
    t.registry.onData(snap(100), 1);
    t.registry.onData(snap(5, { rs: RS, meta: { source: "replay" } }), 1);
    t.take();
    t.take(BOOK, RS);
    return { ...t, liveHandle, replayHandle, forReplay: { rs: RS } };
  }

  it("a sub_ok that refuses the replay ends the replay stream, and its options land on it alone", () => {
    const { registry, liveHandle, replayHandle, forReplay, got } = pair();
    registry.onSubOk(subOk({ throttle_ms: 50 }), forReplay);
    expect([replayHandle.subId, replayHandle.effective]).toEqual(["s_01", { throttle_ms: 50 }]);
    expect([liveHandle.subId, liveHandle.effective]).toEqual([undefined, {}]);
    registry.onSubOk(refused(), forReplay);
    expect([replayHandle.status, liveHandle.status]).toEqual(["revoked", "live"]);
    expect([got(), got(BOOK, RS)]).toEqual([[], ["reset:revoked"]]);
  });

  it("ctl_ok voids the stream it was for, and the unsub_ok of a released replay leaves live alone", () => {
    const { registry, host, liveHandle, replayHandle, forReplay, got } = pair();
    registry.onCtlOk(ctlOk({ depth: 200 }, true), forReplay);
    expect([replayHandle.status, liveHandle.status]).toEqual(["resyncing", "live"]);
    expect([replayHandle.effective, liveHandle.effective]).toEqual([{ depth: 200 }, {}]);
    expect([got(), got(BOOK, RS)]).toEqual([[], ["reset:resnapshot"]]);
    replayHandle.release();
    expect(host.unsubscribe).toHaveBeenCalledWith(BOOK, RS);
    registry.onUnsubOk(unsubOk(), forReplay);
    registry.onData(delta(101), 1);
    expect([liveHandle.status, got()]).toEqual(["live", ["d:101"]]);
  });

  it("a reply for a stream that is gone applies to nothing, however many streams of the ch remain", () => {
    const { registry, host, liveHandle, replayHandle, forReplay, got } = pair();
    replayHandle.release();
    registry.onCtlOk(ctlOk({ depth: 200 }, true), forReplay); // the released replay stream's resnapshot
    registry.onSubOk(refused(), forReplay);
    registry.onSubOk(subOk({ throttle_ms: 50 }), forReplay);
    for (let s = 101; s <= 120; s += 1) registry.onData(delta(s), 1);
    expect([liveHandle.status, liveHandle.effective, liveHandle.subId]).toEqual([
      "live",
      {},
      undefined,
    ]);
    expect([got().length, host.resync.mock.calls.length]).toEqual([20, 0]); // 20 deltas, no reset
  });

  it("replay_session_ended ends the replay streams only; any other reason ends both", () => {
    const { registry, liveHandle, replayHandle, got } = pair();
    registry.onRevoked(revoked("replay_session_ended"));
    expect([replayHandle.status, liveHandle.status]).toEqual(["revoked", "live"]);
    expect([got(), got(BOOK, RS)]).toEqual([[], ["reset:revoked"]]);
    const both = pair();
    both.registry.onRevoked(revoked("session_revoked"));
    expect([both.liveHandle.status, both.replayHandle.status]).toEqual(["revoked", "revoked"]);
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

  it("drops the deferred resync when the server ends the stream, and its window with it", () => {
    const { registry, host } = live();
    const base = gaps(registry, 5);
    registry.onData(delta(base + 2), 1);
    registry.onRevoked(revoked("session_revoked"));
    vi.advanceTimersByTime(120_000);
    expect(host.resync).toHaveBeenCalledTimes(5);
  });

  it("an ended stream takes the gateway's resync window with it: the next subscription has a new one", () => {
    const { registry, host } = live();
    gaps(registry, 5);
    registry.onRevoked(revoked("session_revoked"));
    registry.consume(spec()); // a fresh subscription of the same ch, inside the minute
    registry.onData(snap(1), 1);
    registry.onData(delta(3), 1);
    expect(host.resync).toHaveBeenCalledTimes(6);
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
