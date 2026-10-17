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
import { repoFile } from "./support/schemaHarness";

const le = (n: number): number[] => [...new Uint8Array(new BigUint64Array([BigInt(n)]).buffer)];

/** 24-byte common header (23 3.4: magic "CVWB", version, kind, flags, scales 2 and 3) + `body`. */
function cvwb(kind: number, version: number, count: number, body: readonly number[] = []) {
  const out = new Uint8Array(24 + body.length);
  out.set([0x42, 0x57, 0x56, 0x43, version, kind, 0, 2, 3]);
  new DataView(out.buffer).setUint32(12, count, true);
  out.set(body, 24);
  return out;
}

const bookDelta = () => cvwb(2, 1, 1, [0, ...le(10050), ...le(1500)]); // one 17-byte level
const b64 = (bin: Uint8Array): string => btoa(String.fromCharCode(...bin));
const wire = (frame: object): string => JSON.stringify(frame);
const DATA = { t: "d", ch: "book.BTCUSDT.50", s: 1001, ts: 1_789_132_262_452 };
const WELCOME = {
  connection_id: "ws_1",
  heartbeat: { interval_ms: 15_000, timeout_ms: 45_000 },
  limits: { max_subscriptions: 200, max_topics_per_request: 50, min_throttle_ms: 50 },
};
const AUTH_OK = { user_id: "u", token_expires_at_ms: 1, roles: ["owner"], account_scope: [] };

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
    const next = { ...chunk, s: 7, rs: "bb", meta: { reason: "from_the_future" } };
    expect(decodeFrame(wire(next))).toMatchObject({ s: 7, rs: "bb", meta: next.meta });
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
  ])("%s is frame_malformed", (_what, input) => {
    expect(decodeFrame(input)).toMatchObject({ t: "decode_error", code: "frame_malformed" });
  });

  it("names the topic of a malformed data frame so the caller can resync it", () => {
    expect(decodeFrame(wire({ ...DATA, ts: "now" }))).toMatchObject({ ch: "book.BTCUSDT.50" });
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
