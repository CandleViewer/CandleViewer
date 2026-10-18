// E17-T04 S5b (23 4.3, ADR-0005; SR-128): the port protocol. A message from a tab is untrusted input to the
// worker: it is checked field by field and rebuilt, or refused; the tab checks what the worker posts the same
// way. A buffer moves between threads once: the first consumer of a frame takes the original, every other one a copy.
import { describe, expect, it } from "vitest";
import type { DeltaFrame, ResetFrame, SnapFrame } from "../../../src/lib/ws/api";
import type { DataBody } from "../../../src/lib/ws/protocol/codec";
import {
  copyFrame,
  isWsUrl,
  parseClientMessage,
  parseWorkerMessage,
  PORT_PROTOCOL_VERSION,
  transferListOf,
} from "../../../src/lib/ws/port/messages";
import { INITIAL_WS_STATE } from "../../../src/lib/ws/state/reducer";

const RS = "bb000000-0000-4000-8000-000000000001";
const CONNECT = {
  t: "connect",
  v: PORT_PROTOCOL_VERSION,
  wsUrl: "wss://cv.test/api/v1/ws",
  shell: "browser",
  locale: "en-GB",
  clientVersion: "1.0.0",
};
const CONSUME = { t: "consume", id: "k1", ch: "book.BTCUSDT.50", pane: "p1", priority: "focused" };

/** Every message of the protocol, each in the form a tab sends it. */
const CLIENT: Record<string, unknown> = {
  connect: CONNECT,
  consume: CONSUME,
  "consume of a replay stream, with options": {
    ...CONSUME,
    rs: RS,
    opts: { throttle_ms: 100, depth: 50 },
  },
  release: { t: "release", id: "k1" },
  resync: { t: "resync", id: "k1" },
  pane: { t: "pane", id: "p1", visibility: "offscreen" },
  "pane with a size": { t: "pane", id: "p1", visibility: "visible", cssWidth: 1190, dpr: 1.5 },
  focus: { t: "focus", id: "p1" },
  "focus of nothing": { t: "focus", id: null },
  visibility: { t: "visibility", hidden: true },
  token: {
    t: "token",
    req: 3,
    result: { kind: "ok", accessToken: "a".repeat(40), expiresAtMs: 1e12 },
  },
  "token locked": { t: "token", req: 4, result: { kind: "locked" } },
  "token unavailable": { t: "token", req: 5, result: { kind: "unavailable" } },
  stop: { t: "stop" },
  fault: { t: "fault", command: { kind: "anything" } },
};

describe("a tab's message (client -> worker)", () => {
  it.each(Object.entries(CLIENT))("%s is accepted as it is", (_name, message) => {
    expect(parseClientMessage(message)).toEqual(message);
  });

  it("keeps the fields it checked and no others, whatever else the message carries", () => {
    const parsed = parseClientMessage({ ...CONSUME, evil: { deep: 1 }, rs: undefined });
    expect(parsed).toEqual(CONSUME);
    expect(Object.keys(parsed ?? {})).not.toContain("evil");
    const proto = JSON.parse('{"t":"stop","__proto__":{"polluted":true}}') as unknown;
    expect(parseClientMessage(proto)).toEqual({ t: "stop" });
    expect(({} as Record<string, unknown>)["polluted"]).toBeUndefined();
  });

  it("copies the options, so the tab cannot change them after the check", () => {
    const opts = { throttle_ms: 100 };
    const parsed = parseClientMessage({ ...CONSUME, opts });
    expect(parsed).toMatchObject({ opts: { throttle_ms: 100 } });
    opts.throttle_ms = 1;
    expect(parsed).toMatchObject({ opts: { throttle_ms: 100 } });
  });

  const cyclic: Record<string, unknown> = {};
  cyclic["self"] = cyclic;
  const connect = (over: object) => ({ ...CONNECT, ...over });
  const consume = (over: object) => ({ ...CONSUME, ...over });
  const pane = (over: object) => ({ t: "pane", id: "p1", visibility: "visible", ...over });
  const token = (result?: object, req: unknown = 1) => ({ t: "token", req, result });
  const granted = (over: object) => ({
    kind: "ok",
    accessToken: "a".repeat(40),
    expiresAtMs: 1,
    ...over,
  });
  const url = (rest: string) => connect({ wsUrl: `wss://cv.test/${rest}` });
  const REFUSED: [string, unknown][] = [
    ["null", null],
    ["a list", [CONNECT]],
    ["a string", "connect"],
    ["no type", {}],
    ["an unknown type", { t: "hello" }],
    ["a type that is not a string", { t: 1 }],
    ["connect of another version", connect({ v: 2 })],
    ["connect to http", connect({ wsUrl: "https://cv.test/api/v1/ws" })],
    ["connect with a token in the query", url("api/v1/ws?token=abc")],
    ["connect with a user and password", connect({ wsUrl: "wss://u:p@cv.test/ws" })],
    ["connect with a password only", connect({ wsUrl: "wss://:secret@cv.test/ws" })],
    ["connect with a user only", connect({ wsUrl: "wss://user@cv.test/ws" })],
    ["connect with a fragment", url("ws#x")],
    ["connect to a URL that is not one", connect({ wsUrl: "not a url" })],
    ["connect to a URL over 512 characters", url("a".repeat(512))],
    ["connect from an unknown shell", connect({ shell: "tauri" })],
    ["connect with a locale over 16 characters", connect({ locale: "x".repeat(17) })],
    ["connect with no locale", connect({ locale: "" })],
    ["connect with a version over 32 characters", connect({ clientVersion: "1".repeat(33) })],
    ["consume of a topic that is not one", consume({ ch: "Book.BTCUSDT" })],
    ["consume with an id over 64 characters", consume({ id: "k".repeat(65) })],
    ["consume with no pane", consume({ pane: "" })],
    ["consume with an unknown priority", consume({ priority: "urgent" })],
    ["consume of a replay session that is not a uuid", consume({ rs: "bb0000" })],
    ["consume with options that are a list", consume({ opts: [1] })],
    ["consume with options over 4 KiB", consume({ opts: { text: "x".repeat(4100) } })],
    ["consume with options that are cyclic", consume({ opts: cyclic })],
    ["release with no id", { t: "release" }],
    ["resync with an empty id", { t: "resync", id: "" }],
    ["pane of an unknown visibility", pane({ visibility: "hidden" })],
    ["pane with a width and no pixel ratio", pane({ cssWidth: 100 })],
    ["pane with a width that is NaN", pane({ cssWidth: Number.NaN, dpr: 1 })],
    ["pane with a width of 0", pane({ cssWidth: 0, dpr: 1 })],
    ["pane with a width over 100 000", pane({ cssWidth: 100_001, dpr: 1 })],
    ["pane with a pixel ratio over 16", pane({ cssWidth: 100, dpr: 17 })],
    ["focus of a number", { t: "focus", id: 5 }],
    ["focus of an empty id", { t: "focus", id: "" }],
    ["visibility that is not a boolean", { t: "visibility", hidden: "yes" }],
    ["token with a request number that is not one", token({ kind: "locked" }, -1)],
    ["token with a fractional request number", token({ kind: "locked" }, 1.5)],
    ["token with no result", token()],
    ["token of a kind that is none", token({ kind: "denied" })],
    ["token ok without a token", token(granted({ accessToken: undefined }))],
    ["token ok with an empty token", token(granted({ accessToken: "" }))],
    [
      "token ok with a token over 8 192 characters",
      token(granted({ accessToken: "a".repeat(8193) })),
    ],
    ["token ok that expires at NaN", token(granted({ expiresAtMs: Number.NaN }))],
    ["token ok with no expiry", token(granted({ expiresAtMs: undefined }))],
  ];
  it.each(REFUSED)("refuses %s", (_name, message) => {
    expect(parseClientMessage(message)).toBeUndefined();
  });

  it("takes values exactly at their limits", () => {
    const kind = (message: unknown) => parseClientMessage(message)?.t;
    expect(kind(connect({ locale: "x".repeat(16), clientVersion: "1".repeat(32) }))).toBe(
      "connect",
    );
    expect(kind(consume({ id: "k".repeat(64), pane: "p".repeat(64) }))).toBe("consume");
    expect(kind(pane({ cssWidth: 100_000, dpr: 16 }))).toBe("pane");
    expect(kind(token(granted({ accessToken: "a".repeat(8192) })))).toBe("token");
    const host = "wss://cv.test/";
    expect(isWsUrl(host + "a".repeat(512 - host.length))).toBe(true);
  });

  it("takes only ws and wss URLs without a userinfo, a query or a fragment", () => {
    for (const url of ["ws://127.0.0.1:8000/api/v1/ws", "wss://cv.test/api/v1/ws"]) {
      expect(isWsUrl(url)).toBe(true);
    }
    for (const url of [
      "http://cv.test/ws",
      "ftp://cv.test/ws",
      "wss://cv.test/ws?",
      undefined,
      5,
      "",
    ]) {
      expect(isWsUrl(url)).toBe(false);
    }
  });
});

describe("the worker's message (worker -> tab)", () => {
  const STATE = { t: "state", state: INITIAL_WS_STATE };
  const DATA = {
    t: "data",
    id: "k1",
    frames: [],
    status: "live",
    effective: { throttle_ms: 100 },
    source: "live",
  };
  const WORKER: Record<string, unknown> = {
    state: STATE,
    data: DATA,
    "data of a replay stream": { ...DATA, status: "stale", source: "replay" },
    system: { t: "system", update: { kind: "health", health: "healthy" } },
    tokenRequest: { t: "tokenRequest", req: 7, invalidate: true },
    diag: {
      t: "diag",
      diag: { engine: {}, host: {}, slowConsumerHint: [], clockSkewMs: undefined },
    },
  };

  it.each(Object.entries(WORKER))("%s is accepted as it is", (_name, message) => {
    expect(parseWorkerMessage(message)).toEqual(message);
  });

  const REFUSED: [string, unknown][] = [
    ["null", null],
    ["a message of no known type", { t: "bye" }],
    ["a state that is not one", { t: "state", state: { transport: 1 } }],
    ["a state with no sequence number", { t: "state", state: { transport: "connected" } }],
    ["data with an unknown status", { ...DATA, status: "dead" }],
    ["data whose frames are not a list", { ...DATA, frames: {} }],
    ["data with no options", { ...DATA, effective: null }],
    ["data from an unknown source", { ...DATA, source: "paper" }],
    ["data with no consumer", { ...DATA, id: "" }],
    ["a system update with no kind", { t: "system", update: {} }],
    ["a token request that is not numbered", { t: "tokenRequest", req: "1", invalidate: false }],
    ["a token request that does not say whether to invalidate", { t: "tokenRequest", req: 1 }],
    ["diagnostics with no engine counters", { t: "diag", diag: { host: {} } }],
  ];
  it.each(REFUSED)("refuses %s", (_name, message) => {
    expect(parseWorkerMessage(message)).toBeUndefined();
  });
});

describe("a buffer reaches one receiver only (ADR-0005)", () => {
  const bytes = (...values: number[]): ArrayBuffer => new Uint8Array(values).buffer;
  /** The buffer of a binary body; a test that asks for another's is wrong. */
  const buf = (body: DataBody | undefined): ArrayBuffer => {
    if (body?.e !== "b64") throw new Error("not a binary body");
    return body.bytes;
  };
  const base = { ts: 1, sp: undefined, decodeMs: 0, meta: undefined };
  const snap: SnapFrame = {
    kind: "snap",
    seq: 1,
    ...base,
    bodies: [
      { e: "b64", bytes: bytes(1, 2, 3) },
      { e: "j", p: { rows: [1] } },
      { e: "b64", bytes: bytes(4) },
    ],
  };
  const delta: DeltaFrame = {
    kind: "d",
    seq: 2,
    ...base,
    body: { e: "b64", bytes: bytes(9, 8) },
  };
  const reset: ResetFrame = { kind: "reset", reason: "gap" };

  it("copies the buffers of a snapshot and of a delta, and shares what is data nobody mutates", () => {
    const copy = copyFrame(snap);
    if (copy.kind !== "snap") throw new Error("not a snap");
    expect(copy).toEqual(snap);
    expect(buf(copy.bodies[0])).not.toBe(buf(snap.bodies[0]));
    expect(buf(copy.bodies[2])).not.toBe(buf(snap.bodies[2]));
    expect(copy.bodies[1]).toBe(snap.bodies[1]); // a structured body is read, never written
    const copyOfDelta = copyFrame(delta);
    if (copyOfDelta.kind !== "d") throw new Error("not a delta");
    expect(copyOfDelta).toEqual(delta);
    expect(buf(copyOfDelta.body)).not.toBe(buf(delta.body));
    expect(copyFrame(reset)).toBe(reset);
  });

  it("a copy outlives the transfer of its original", () => {
    const copy = copyFrame(delta);
    if (copy.kind !== "d") throw new Error("not a delta");
    const sent = structuredClone(delta, { transfer: [buf(delta.body)] });
    expect(buf(delta.body).byteLength).toBe(0); // detached at the sender
    expect(new Uint8Array(buf(copy.body))).toEqual(new Uint8Array([9, 8])); // the other tab's copy is whole
    expect(buf(sent.body).byteLength).toBe(2);
  });

  it("lists each buffer once, in order, and none for a reset or a structured body", () => {
    expect(transferListOf([reset, snap, delta, snap])).toEqual([
      buf(snap.bodies[0]),
      buf(snap.bodies[2]),
      buf(delta.body),
    ]);
    expect(transferListOf([reset, { ...delta, body: { e: "j", p: {} } }])).toEqual([]);
    expect(transferListOf([])).toEqual([]);
  });
});
