// E17-T04 S1 (C1): the client's own frames are held to the same schemas as the server (23 16.4,
// "Contract: client frames validate"). The negative controls prove the harness is not vacuous.
import { describe, expect, it } from "vitest";
import { encodeFrame } from "../../../src/lib/ws/protocol/codec";
import * as F from "../../../src/lib/ws/protocol/frames";
import { validateClientFrame } from "./support/schemaHarness";

const NOW = 1_789_132_261_980;
const RS = "bb000000-0000-4000-8000-000000000001";
const PRE_AUTH_CAP_BYTES = 8 * 1024;
const bytes = (f: F.ClientFrame): number => new TextEncoder().encode(encodeFrame(f)).byteLength;
const topics = (n: number) => Array.from({ length: n }, () => ({ ch: "orders" }));
const subWith = (list: object[]) => ({ t: "sub", id: "c-1", p: { topics: list } });

const HELLO = F.hello("c-1", { client_version: "1", shell: "other", locale: "en", clock_ms: NOW });
const FRAMES: Record<string, F.ClientFrame> = {
  hello: HELLO,
  auth: F.auth("c-2", "t".repeat(40), ["live", "demo"]),
  sub: F.sub("c-3", {
    topics: [{ ch: "book.BTCUSDT.50", opts: { throttle_ms: 50 } }, { ch: "orders" }],
    snapshot: true,
    replay_session_id: null,
  }),
  unsub: F.unsub("c-4", ["book.BTCUSDT.50"]),
  "unsub of a replay stream": F.unsub("c-4", ["book.BTCUSDT.50"], RS),
  ctl: F.ctl("c-5", "heatmap.BTCUSDT", { time_bucket_ms: 1000 }),
  "ctl of a replay stream": F.ctl("c-5", "heatmap.BTCUSDT", { time_bucket_ms: 1000 }, RS),
  resync: F.resync("c-6", "book.BTCUSDT.50", { last_seq: 1002, reason: "sequence_gap" }),
  "resync of a replay stream": F.resync(
    "c-6",
    "book.BTCUSDT.50",
    { last_seq: null, reason: "client_restart" },
    RS,
  ),
  ping: F.ping("c-7", NOW),
  pong: F.pong("c-8", NOW),
};

describe("client frames validate against the generated WS schemas (C1)", () => {
  it.each(Object.entries(FRAMES))("%s is valid against envelope and payload schema", (_t, f) => {
    expect(validateClientFrame(f)).toEqual([]);
  });

  it("negative controls: an unknown opts key, 51 topics and a 65-char id are rejected", () => {
    const longId = F.ping("x".repeat(F.MAX_ID_LENGTH + 1), NOW);
    const unknownOpt = subWith([{ ch: "orders", opts: { nope: 1 } }]);
    expect(validateClientFrame(unknownOpt).join()).toMatch(/additional properties/);
    expect(validateClientFrame(subWith(topics(51))).join()).toMatch(/more than 50 items/);
    expect(validateClientFrame(longId).join()).toMatch(/more than 64 characters/);
    expect(validateClientFrame(subWith(topics(50)))).toEqual([]);
  });

  it("a resync, a ctl and an unsub carry the replay session in their envelope (C20), and a live one carries none", () => {
    for (const named of [
      "resync of a replay stream",
      "ctl of a replay stream",
      "unsub of a replay stream",
    ]) {
      expect(FRAMES[named]).toMatchObject({ rs: RS });
    }
    for (const live of ["resync", "ctl", "unsub"]) expect(FRAMES[live]).not.toHaveProperty("rs");
    // negative control: `rs` is a string in the envelope (the harness does not assert `format: uuid`)
    const named = { ...F.ctl("c-5", "heatmap.BTCUSDT", { time_bucket_ms: 1000 }), rs: 5 };
    expect(validateClientFrame(named).join()).toMatch(/must be string/);
  });

  it("ctl needs at least one property: the type refuses what ctl.schema.json refuses (minProperties 1)", () => {
    // @ts-expect-error -- the generated CtlPayload admits {} (a #572 gap); the one used here does not
    const empty = F.ctl("c-9", "heatmap.BTCUSDT", {});
    expect(validateClientFrame(empty).join()).toMatch(/fewer than 1 properties/);
    // @ts-expect-error -- undefined is dropped by JSON, so this would also put an empty ctl on the wire
    const dropped = F.ctl("c-9", "heatmap.BTCUSDT", { throttle_ms: undefined });
    expect(encodeFrame(dropped)).not.toContain("throttle_ms");
  });
});

describe("handshake pins", () => {
  it("offers cv.v1.json only (D3); hello lists each capability once, partial snapshots included", () => {
    expect(F.SUBPROTOCOLS).toEqual(["cv.v1.json"]);
    expect(new Set(F.CAPABILITIES).size).toBe(F.CAPABILITIES.length);
    expect(HELLO.p).toMatchObject({
      encodings: ["binary", "structured"],
      capabilities: F.CAPABILITIES,
    });
    expect(F.CAPABILITIES).toContain("partial_snapshots");
  });

  it("hello and a 4 096-character auth stay under the 8 KiB pre-auth cap (3.6)", () => {
    const maxAuth = F.auth("c-1", "a".repeat(4096), ["live", "demo", "testnet"]);
    expect(validateClientFrame(maxAuth)).toEqual([]);
    expect(bytes(maxAuth)).toBeLessThan(PRE_AUTH_CAP_BYTES);
    expect(bytes(HELLO)).toBeLessThan(PRE_AUTH_CAP_BYTES);
  });

  it("ids are c-<n>, unique per source and within 64 characters", () => {
    const ids = Array.from({ length: 1000 }, F.createIdSource());
    expect(ids.slice(0, 2)).toEqual(["c-1", "c-2"]);
    expect(new Set(ids).size).toBe(1000);
    expect(ids.every((id) => /^c-\d+$/.test(id) && id.length <= F.MAX_ID_LENGTH)).toBe(true);
    expect(F.createIdSource()()).toBe("c-1");
  });
});
