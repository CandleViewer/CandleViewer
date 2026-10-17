// E17-T04 S1 (C10, SR-128, WS-D10): the codec never throws on untrusted input, ignores unknown
// fields (2.3) and maps every malformed frame to a typed `frame_malformed`.
import { describe, expect, it } from "vitest";
import {
  decodeFrame,
  encodeFrame,
  validateCvwb,
  type DataFrame,
} from "../../../src/lib/ws/protocol/codec";
import { ping } from "../../../src/lib/ws/protocol/frames";
import { b64, bookDelta, cvwb } from "./support/cvwb";
import { repoFile } from "./support/schemaHarness";

const wire = (frame: object): string => JSON.stringify(frame);
const DATA = { t: "d", ch: "book.BTCUSDT.50", s: 1001, ts: 1_789_132_262_452 };
/** A valid structured delta: a row built from it is malformed only for the field it changes. */
const DELTA = { ...DATA, p: {} };
const WELCOME = {
  connection_id: "ws_1",
  server_time_ms: 1_789_132_262_000,
  heartbeat: { interval_ms: 15_000, timeout_ms: 45_000 },
  limits: { max_subscriptions: 200, max_topics_per_request: 50, min_throttle_ms: 50 },
};
const AUTH_OK = {
  user_id: "u",
  session_id: "s_1",
  token_expires_at_ms: 1,
  roles: ["owner"],
  permissions: ["marketdata:read"],
  account_scope: [],
};
const RS = "bb000000-0000-4000-8000-000000000001";
const KILL = { engaged: true, scope: "accounts", exchange_account_ids: ["a1"] };
const authOkWith = (kill_switch: unknown) => wire({ t: "auth_ok", p: { ...AUTH_OK, kill_switch } });
const bye = (code: number) => wire({ t: "bye", p: { code, reason: "x", message: "x" } });
const sub_ok_with = (ch: string) => wire({ t: "sub_ok", p: { results: [{ ch, ok: true }] } });
const without = (p: Record<string, unknown>, key: string) =>
  Object.fromEntries(Object.entries(p).filter(([k]) => k !== key));

describe("decodeFrame", () => {
  it("decodes a b64 book delta into an owned buffer that validates as CVWB", () => {
    const frame = decodeFrame(wire({ ...DATA, e: "b64", p: b64(bookDelta()) })) as DataFrame;
    expect(frame).toMatchObject({ t: "d", ch: "book.BTCUSDT.50", s: 1001 });
    if (frame.body.e !== "b64") throw new Error("expected a b64 body");
    expect(frame.body.bytes.byteLength).toBe(41);
    expect(validateCvwb(frame.body.bytes)).toMatchObject({ ok: true, header: { bodyKind: 2 } });
  });

  it("decodes structured frames (C15), keeping a null chunk seq, replay fields and an unknown reason (C18)", () => {
    const chunk = { t: "snap", id: "snap-3", ch: "trades.BTCUSDT", s: null, ts: 1, p: { x: 1 } };
    expect(decodeFrame(wire(chunk))).toMatchObject({ id: "snap-3", s: null, body: { e: "j" } });
    const next = { ...chunk, s: 7, rs: RS, meta: { reason: "from_the_future" } };
    expect(decodeFrame(wire(next))).toMatchObject({ s: 7, rs: RS, meta: next.meta });
  });

  it("decodes the handshake frames, kill switch included", () => {
    const kill_switch = { engaged: true, scope: "global" };
    const welcome = decodeFrame(wire({ t: "welcome", p: WELCOME }));
    const authOk = decodeFrame(wire({ t: "auth_ok", p: { ...AUTH_OK, kill_switch } }));
    expect(welcome).toMatchObject({ p: { limits: { max_topics_per_request: 50 } } });
    expect(authOk).toMatchObject({ p: { kill_switch: { engaged: true } } });
  });

  it("ignores unknown fields on the envelope and in a payload (2.3)", () => {
    const pong = { t: "pong", id: "c-1", future: true, p: { server_ms: 1, extra: [1] } };
    expect(decodeFrame(wire(pong))).toMatchObject({ t: "pong", id: "c-1" });
    expect(decodeFrame(encodeFrame(ping("c-2", 5)))).toMatchObject({ t: "ping" });
  });

  it.each([
    ["a binary message on cv.v1.json", new ArrayBuffer(8)],
    ["bad JSON", "{"],
    ["a client-only type", wire({ t: "hello", p: {} })],
    ["a prototype-chain type", wire({ t: "constructor", p: {} })],
    ["a 65-character id", wire({ t: "pong", id: "x".repeat(65) })],
    ["the msgpack encoding `b`", wire({ ...DATA, e: "b", p: "AAAA" })],
    ["a null delta seq", wire({ ...DATA, s: null, p: {} })],
    ["a snap without a seq", wire({ t: "snap", ch: "orders", ts: 1, p: {} })],
    ["invalid base64", wire({ ...DATA, e: "b64", p: "not base64!" })],
    ["a base64 illegal character", wire({ ...DATA, e: "b64", p: "AA!A" })],
    ["a welcome without limits", wire({ t: "welcome", p: { connection_id: "c" } })],
    ["a sub_ok result without ok", wire({ t: "sub_ok", p: { results: [{ ch: "orders" }] } })],
    ["a bad kill switch", wire({ t: "auth_ok", p: { ...AUTH_OK, kill_switch: { engaged: 1 } } })],
    // S1 lens C: the five guards that survived mutation until they were pinned here.
    ["a kill switch with an unknown scope", authOkWith({ engaged: true, scope: "galaxy" })],
    ["a kill switch with no scope", authOkWith({ engaged: true })],
    ["a non-list exchange_account_ids", authOkWith({ ...KILL, exchange_account_ids: "a1" })],
    [
      "exchange_account_ids holding a non-string among strings",
      authOkWith({ ...KILL, exchange_account_ids: ["a1", 2] }),
    ],
    ["valid JSON `null`", "null"],
    ["a valid JSON array", "[]"],
    ["base64 that is not a whole number of quads (`%4`)", wire({ ...DATA, e: "b64", p: "AAA" })],
    // S1 lens S: server-controlled strings are bounded where they enter.
    ["a ch that is not a topic name", wire({ ...DELTA, ch: "Book BTC" })],
    ["a 121-character ch", wire({ ...DELTA, ch: `book.${"A".repeat(116)}` })],
    ["a replay session id that is not a UUID", wire({ ...DELTA, rs: "bb000000" })],
    [
      "a 36-character rs that is not a UUID",
      wire({ ...DELTA, rs: "zz000000-0000-4000-8000-000000000001" }),
    ],
    ["a span id of the wrong shape", wire({ ...DELTA, sp: "0123456789ABCDEF" })],
    ["an all-zero span id", wire({ ...DELTA, sp: "0".repeat(16) })],
    ["a meta that is an array", wire({ ...DELTA, meta: [] })],
    ["a heartbeat payload that is an array", wire({ t: "pong", p: [] })],
    ["a sub_ok result whose ch is not a topic", sub_ok_with("x y")],
    // S1 lens C: fields S4 reads, now verified rather than only typed.
    [
      "a welcome without server_time_ms",
      wire({ t: "welcome", p: without(WELCOME, "server_time_ms") }),
    ],
    ["an auth_ok without session_id", wire({ t: "auth_ok", p: without(AUTH_OK, "session_id") })],
    ["an auth_ok without permissions", wire({ t: "auth_ok", p: without(AUTH_OK, "permissions") })],
    ["an err without a message", wire({ t: "err", p: { code: "internal_error" } })],
    ["a revoked without a message", wire({ t: "revoked", ch: "orders", p: { reason: "x" } })],
    ["a bye code below 1000", bye(999)],
    ["a bye code above 4999", bye(5000)],
    ["a fractional bye code", bye(4000.5)],
  ])("%s is frame_malformed", (_what, input) => {
    expect(decodeFrame(input)).toMatchObject({ t: "decode_error", code: "frame_malformed" });
  });

  it("names the topic of a malformed data frame so the caller can resync it", () => {
    expect(decodeFrame(wire({ ...DATA, ts: "now" }))).toMatchObject({ ch: "book.BTCUSDT.50" });
  });

  it("echoes ch only when it is a topic name: an unbounded server string is never carried (C-12.6)", () => {
    const error = decodeFrame(wire({ ...DATA, ts: "now", ch: "x".repeat(10_000) }));
    expect(error).toMatchObject({ t: "decode_error" });
    expect((error as { ch?: string }).ch).toBeUndefined();
  });

  it("accepts every limit exactly: a 64-character id, a 120-character topic, a UUID rs, a close code in range", () => {
    expect(decodeFrame(wire(DELTA))).toMatchObject({ t: "d" }); // the control for the rows above
    expect(decodeFrame(wire({ t: "pong", id: "x".repeat(64) }))).toMatchObject({ t: "pong" });
    const ch = `book.${"A".repeat(115)}`;
    expect(decodeFrame(wire({ ...DELTA, ch, rs: RS }))).toMatchObject({ ch, rs: RS });
    for (const code of [1000, 1012, 4429, 4999]) {
      expect(decodeFrame(bye(code))).toMatchObject({ t: "bye", p: { code } });
    }
    const results = { results: [{ ch: "book.BTCUSDT.50", ok: true }] };
    expect(decodeFrame(wire({ t: "sub_ok", p: results }))).toMatchObject({ t: "sub_ok" });
    const err = { t: "err", p: { code: "internal_error", message: "m" } };
    expect(decodeFrame(wire(err))).toMatchObject({ t: "err" });
    const revoked = { t: "revoked", ch: "orders", p: { reason: "session_revoked", message: "m" } };
    expect(decodeFrame(wire(revoked))).toMatchObject({ t: "revoked" });
  });

  it("carries the span id and the message size of a data frame (13.1)", () => {
    const text = wire({ ...DATA, sp: "0123456789abcdef", p: { x: 1 } });
    expect(decodeFrame(text)).toMatchObject({ sp: "0123456789abcdef", size: text.length });
  });
});

describe("validateCvwb (C10)", () => {
  const BARS_BODY = new Array<number>(85).fill(0);
  const badMagic = bookDelta();
  badMagic[0] = 0;

  it("accepts a well-formed body and a bars v2 body of exactly the right length", () => {
    expect(validateCvwb(bookDelta())).toMatchObject({ ok: true });
    expect(validateCvwb(cvwb(4, 2, 1, BARS_BODY))).toMatchObject({ ok: true });
  });

  it.each([
    ["bad magic", badMagic, "cvwb"],
    ["(bars, v1)", cvwb(4, 1, 0), "unsupported_format_version"],
    ["a bars trailing byte", cvwb(4, 2, 1, [...BARS_BODY, 0]), "cvwb"],
    ["an unknown body_kind", cvwb(9, 1, 0), "unsupported_body_kind"],
    ["a truncated header", new Uint8Array(10), "cvwb"],
  ])("%s is frame_malformed", (_what, buf, diagnostic) => {
    const result = validateCvwb(buf);
    expect(result).toMatchObject({ t: "decode_error", code: "frame_malformed", diagnostic });
  });

  it("cvwb corpus: all 71 cases match `expect` and none throws (SR-128, WS-D10)", () => {
    type Seed = { name: string; expect: "ok" | "malformed"; hex: string };
    const corpus = JSON.parse(repoFile("tests/fuzz/ws-frames/corpus.json")) as Seed[];
    expect(corpus).toHaveLength(71);
    const outcome = (hex: string) =>
      "ok" in validateCvwb(Buffer.from(hex, "hex")) ? "ok" : "malformed";
    expect(corpus.filter((c) => outcome(c.hex) !== c.expect).map((c) => c.name)).toEqual([]);
  });
});
