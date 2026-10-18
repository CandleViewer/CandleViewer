// E17-T04 S5b (23 4.3, ADR-0005; SR-128): the port protocol. A message from a tab is untrusted input to the
// worker: it is checked field by field and rebuilt, or refused; the tab checks what the worker posts the same
// way, for its shape. Each field is read once, so what was checked is what is returned.
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

/** `message` with a field that answers `first` when it is read the first time and `later` every time after: a getter that changes between a check and a copy. */
const changing = <T extends object>(
  message: T,
  name: string,
  first: unknown,
  later: unknown,
): T => {
  let reads = 0;
  return Object.defineProperty({ ...message }, name, {
    enumerable: true,
    get: () => (reads++ === 0 ? first : later),
  });
};

/** Every message of the protocol, each in the form a tab sends it. */
const CLIENT: Record<string, Record<string, unknown>> = {
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

  it.each(Object.entries(CLIENT))(
    "%s is rebuilt: a plain object of the checked fields, whatever else the message carries",
    (_name, message) => {
      const parsed = parseClientMessage({ ...message, polluted: true, evil: { deep: 1 } });
      expect(parsed).toEqual(message);
      expect(Object.getPrototypeOf(parsed)).toBe(Object.prototype);
      expect(Object.keys(parsed ?? {})).not.toContain("polluted");
      expect(Object.keys(parsed ?? {})).not.toContain("evil");
      expect((parsed as Record<string, unknown> | undefined)?.["polluted"]).toBeUndefined();
    },
  );

  it("keeps the fields it checked and no others, and a key named __proto__ never reaches a prototype", () => {
    const parsed = parseClientMessage({ ...CONSUME, evil: { deep: 1 }, rs: undefined });
    expect(parsed).toEqual(CONSUME);
    const proto = JSON.parse('{"t":"stop","__proto__":{"polluted":true}}') as unknown;
    const stopped = parseClientMessage(proto);
    expect(stopped).toEqual({ t: "stop" });
    expect(Object.getPrototypeOf(stopped)).toBe(Object.prototype);
    expect(({} as Record<string, unknown>)["polluted"]).toBeUndefined();
  });

  it("copies the options, so the tab cannot change them after the check", () => {
    const opts = { throttle_ms: 100 };
    const parsed = parseClientMessage({ ...CONSUME, opts });
    expect(parsed).toMatchObject({ opts: { throttle_ms: 100 } });
    opts.throttle_ms = 1;
    expect(parsed).toMatchObject({ opts: { throttle_ms: 100 } });
  });

  it("keeps __proto__ and constructor keys of the options as data of the copy, its prototype intact", () => {
    const opts = JSON.parse(
      '{"__proto__":{"polluted":true},"constructor":{"x":1},"depth":50}',
    ) as unknown;
    const parsed = parseClientMessage({ ...CONSUME, opts });
    const kept = (parsed as { opts?: Record<string, unknown> } | undefined)?.opts;
    expect(kept).toBeDefined();
    expect(Object.getPrototypeOf(kept)).toBe(Object.prototype);
    expect(kept?.["polluted"]).toBeUndefined(); // it did not become a property of the copy through its prototype
    expect(Object.keys(kept ?? {}).sort()).toEqual(["__proto__", "constructor", "depth"]);
    expect(Object.getOwnPropertyDescriptor(kept, "__proto__")?.value).toEqual({ polluted: true });
    expect(({} as Record<string, unknown>)["polluted"]).toBeUndefined();
  });

  it("keeps of the options what the wire would carry", () => {
    const parsed = parseClientMessage({ ...CONSUME, opts: { depth: 50, gone: undefined } });
    expect(Object.keys((parsed as { opts?: object } | undefined)?.opts ?? {})).toEqual(["depth"]);
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
  /** An options record whose JSON text is exactly `n` characters. */
  const optsOfLength = (n: number) => ({
    text: "x".repeat(n - JSON.stringify({ text: "" }).length),
  });
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
    ["consume with a pane over 64 characters", consume({ pane: "p".repeat(65) })],
    ["consume with an unknown priority", consume({ priority: "urgent" })],
    ["consume of a replay session that is not a uuid", consume({ rs: "bb0000" })],
    ["consume with options that are a list", consume({ opts: [1] })],
    ["consume with options that are null", consume({ opts: null })],
    ["consume with options that are a text", consume({ opts: "depth" })],
    ["consume with options one character over 4 096", consume({ opts: optsOfLength(4097) })],
    ["consume with options that are cyclic", consume({ opts: cyclic })],
    ["consume with an option no JSON holds", consume({ opts: { depth: 10n } })],
    ["consume with options that are a function", consume({ opts: () => 1 })],
    ["consume with options that turn into a list", consume({ opts: { toJSON: () => [1] } })],
    ["release with no id", { t: "release" }],
    ["release with an id over 64 characters", { t: "release", id: "k".repeat(65) }],
    ["resync with an empty id", { t: "resync", id: "" }],
    ["resync with an id over 64 characters", { t: "resync", id: "k".repeat(65) }],
    ["pane of an unknown visibility", pane({ visibility: "hidden" })],
    ["pane with a width and no pixel ratio", pane({ cssWidth: 100 })],
    ["pane with a width that is NaN", pane({ cssWidth: Number.NaN, dpr: 1 })],
    ["pane with a width of 0", pane({ cssWidth: 0, dpr: 1 })],
    ["pane with a width over 100 000", pane({ cssWidth: 100_001, dpr: 1 })],
    ["pane with a pixel ratio over 16", pane({ cssWidth: 100, dpr: 17 })],
    ["focus of a number", { t: "focus", id: 5 }],
    ["focus of an empty id", { t: "focus", id: "" }],
    ["focus of an id over 64 characters", { t: "focus", id: "k".repeat(65) }],
    ["visibility that is not a boolean", { t: "visibility", hidden: "yes" }],
    ["token with a request number that is not one", token({ kind: "locked" }, -1)],
    ["token with a fractional request number", token({ kind: "locked" }, 1.5)],
    ["token with no result", token()],
    ["token with a result that is null", { t: "token", req: 1, result: null }],
    ["token with a result that is a text", { t: "token", req: 1, result: "ok" }],
    ["token of a kind that is none", token({ kind: "denied" })],
    ["token ok without a token", token(granted({ accessToken: undefined }))],
    ["token ok with a token that is not a text", token(granted({ accessToken: 5 }))],
    ["token ok with an empty token", token(granted({ accessToken: "" }))],
    [
      "token ok with a token over 4 096 characters, what the connection takes",
      token(granted({ accessToken: "a".repeat(4097) })),
    ],
    ["token ok that expires at NaN", token(granted({ expiresAtMs: Number.NaN }))],
    ["token ok that expires at infinity", token(granted({ expiresAtMs: Infinity }))],
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
    expect(kind({ t: "release", id: "k".repeat(64) })).toBe("release");
    expect(kind({ t: "resync", id: "k".repeat(64) })).toBe("resync");
    expect(kind({ t: "focus", id: "k".repeat(64) })).toBe("focus");
    expect(kind(pane({ cssWidth: 100_000, dpr: 16 }))).toBe("pane");
    expect(kind(token(granted({ accessToken: "a".repeat(4096) })))).toBe("token");
    const host = "wss://cv.test/";
    expect(isWsUrl(host + "a".repeat(512 - host.length))).toBe(true);
  });

  it("takes options of 4 096 characters of JSON, and not one more", () => {
    expect(JSON.stringify(optsOfLength(4096))).toHaveLength(4096);
    const parsed = parseClientMessage(consume({ opts: optsOfLength(4096) }));
    expect(parsed?.t).toBe("consume");
    expect(parseClientMessage(consume({ opts: optsOfLength(4097) }))).toBeUndefined();
  });

  it("takes every member of each closed list, and nothing that is not one", () => {
    const shells = ["electron", "browser", "other"].map((shell) => connect({ shell }));
    const sights = ["visible", "offscreen", "collapsed"].map((visibility) => pane({ visibility }));
    const ranks = ["private", "focused", "other"].map((priority) => consume({ priority }));
    for (const message of [...shells, ...sights, ...ranks]) {
      expect(parseClientMessage(message)).toEqual(message);
    }
  });

  it("refuses a token result whose kind says there is no token, and rebuilds it without one", () => {
    for (const kind of ["locked", "unavailable"]) {
      const parsed = parseClientMessage(
        token({ kind, accessToken: "a".repeat(40), expiresAtMs: 1 }),
      );
      expect(parsed).toEqual({ t: "token", req: 1, result: { kind } });
      expect(JSON.stringify(parsed)).not.toContain("aaaa"); // the worker never holds a token a tab said it has not
    }
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

  const CHANGING: [string, unknown, unknown][] = [
    [
      "the type of a release",
      changing({ t: "release", id: "k1" }, "t", "release", "stop"),
      { t: "release", id: "k1" },
    ],
    [
      "the type of a resync",
      changing({ t: "resync", id: "k1" }, "t", "resync", "stop"),
      { t: "resync", id: "k1" },
    ],
    [
      "the id of a release",
      changing({ t: "release", id: "k1" }, "id", "k1", "k".repeat(100)),
      { t: "release", id: "k1" },
    ],
    [
      "the id of a resync",
      changing({ t: "resync", id: "k1" }, "id", "k1", "k".repeat(100)),
      { t: "resync", id: "k1" },
    ],
    [
      "the id of a focus",
      changing({ t: "focus", id: "p1" }, "id", "p1", 5),
      { t: "focus", id: "p1" },
    ],
    [
      "the flag of a visibility",
      changing({ t: "visibility", hidden: true }, "hidden", true, "yes"),
      { t: "visibility", hidden: true },
    ],
    [
      "the request number of a token",
      changing(token({ kind: "locked" }), "req", 3, -1),
      { t: "token", req: 3, result: { kind: "locked" } },
    ],
    [
      "the kind of a token result",
      token(changing({ kind: "locked" }, "kind", "locked", "ok")),
      { t: "token", req: 1, result: { kind: "locked" } },
    ],
    [
      "the token of a token result",
      token(changing(granted({}), "accessToken", "a".repeat(40), "a".repeat(5000))),
      { t: "token", req: 1, result: { kind: "ok", accessToken: "a".repeat(40), expiresAtMs: 1 } },
    ],
    [
      "the expiry of a token result",
      token(changing(granted({}), "expiresAtMs", 1, Number.NaN)),
      { t: "token", req: 1, result: { kind: "ok", accessToken: "a".repeat(40), expiresAtMs: 1 } },
    ],
    [
      "an option, which the copy of the options keeps as it was measured",
      consume({ opts: changing({}, "text", "ok", "x".repeat(10_000)) }),
      { ...CONSUME, opts: { text: "ok" } },
    ],
  ];
  it.each(CHANGING)(
    "reads %s once: what was checked is what is returned",
    (_name, message, expected) => {
      expect(parseClientMessage(message)).toEqual(expected);
    },
  );
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

  it("takes every status a topic can have, and a consumer id of 64 characters", () => {
    for (const status of ["pending", "live", "resyncing", "stale", "revoked"]) {
      expect(parseWorkerMessage({ ...DATA, status })).toEqual({ ...DATA, status });
    }
    const long = { ...DATA, id: "k".repeat(64) };
    expect(parseWorkerMessage(long)).toEqual(long);
  });

  const REFUSED: [string, unknown][] = [
    ["null", null],
    ["a message of no known type", { t: "bye" }],
    ["a state that is not one", { t: "state", state: { transport: 1 } }],
    ["a state with no sequence number", { t: "state", state: { transport: "connected" } }],
    ["a state that is null", { t: "state", state: null }],
    ["data with an unknown status", { ...DATA, status: "dead" }],
    ["data whose frames are not a list", { ...DATA, frames: {} }],
    ["data with no options", { ...DATA, effective: null }],
    ["data whose options are a list", { ...DATA, effective: [] }],
    ["data from an unknown source", { ...DATA, source: "paper" }],
    ["data with no consumer", { ...DATA, id: "" }],
    ["data with a consumer id over 64 characters", { ...DATA, id: "k".repeat(65) }],
    ["a system update with no kind", { t: "system", update: {} }],
    ["a system update whose kind is not a text", { t: "system", update: { kind: 1 } }],
    ["a system update that is null", { t: "system", update: null }],
    ["a token request that is not numbered", { t: "tokenRequest", req: "1", invalidate: false }],
    ["a token request with a negative number", { t: "tokenRequest", req: -1, invalidate: false }],
    [
      "a token request with a fractional number",
      { t: "tokenRequest", req: 1.5, invalidate: false },
    ],
    ["a token request that does not say whether to invalidate", { t: "tokenRequest", req: 1 }],
    ["diagnostics with no engine counters", { t: "diag", diag: { host: {} } }],
    ["diagnostics with no host counters", { t: "diag", diag: { engine: {} } }],
    ["diagnostics whose host counters are null", { t: "diag", diag: { engine: {}, host: null } }],
    ["diagnostics whose engine counters are null", { t: "diag", diag: { engine: null, host: {} } }],
    ["diagnostics that are null", { t: "diag", diag: null }],
  ];
  it.each(REFUSED)("refuses %s", (_name, message) => {
    expect(parseWorkerMessage(message)).toBeUndefined();
  });

  it.each([
    [
      "the request number of a token request",
      changing({ t: "tokenRequest", req: 7, invalidate: true }, "req", 7, "x"),
    ],
    [
      "the invalidate flag of a token request",
      changing({ t: "tokenRequest", req: 7, invalidate: true }, "invalidate", true, "no"),
    ],
  ])("reads %s once: what was checked is what is returned", (_name, message) => {
    expect(parseWorkerMessage(message)).toEqual({ t: "tokenRequest", req: 7, invalidate: true });
  });
});

describe("a buffer reaches one receiver only (ADR-0005)", () => {
  const bytes = (...values: number[]): ArrayBuffer => new Uint8Array(values).buffer;
  /** The buffer of a binary body; a test that asks for another's is wrong. */
  const buf = (body: DataBody | undefined): ArrayBuffer => {
    if (body?.e !== "b64") throw new Error("not a binary body");
    return body.bytes;
  };
  const base = { ts: 1, sp: undefined, decodeMs: 0, size: 12, meta: undefined };
  /** Frames made afresh in each test: one of them detaches a buffer, and no other may feel it (any order, any seed). */
  const snap = (): SnapFrame => ({
    kind: "snap",
    seq: 1,
    ...base,
    bodies: [
      { e: "b64", bytes: bytes(1, 2, 3) },
      { e: "j", p: { rows: [1] } },
      { e: "b64", bytes: bytes(4) },
    ],
  });
  const delta = (): DeltaFrame => ({
    kind: "d",
    seq: 2,
    ...base,
    body: { e: "b64", bytes: bytes(9, 8) },
  });
  const reset = (): ResetFrame => ({ kind: "reset", reason: "gap" });

  it("copies the buffers of a snapshot and of a delta, and shares what is data nobody mutates", () => {
    const original = snap();
    const copy = copyFrame(original);
    if (copy.kind !== "snap") throw new Error("not a snap");
    expect(copy).toEqual(original);
    expect(buf(copy.bodies[0])).not.toBe(buf(original.bodies[0]));
    expect(buf(copy.bodies[2])).not.toBe(buf(original.bodies[2]));
    expect(copy.bodies[1]).toBe(original.bodies[1]); // a structured body is read, never written
    const originalDelta = delta();
    const copyOfDelta = copyFrame(originalDelta);
    if (copyOfDelta.kind !== "d") throw new Error("not a delta");
    expect(copyOfDelta).toEqual(originalDelta);
    expect(buf(copyOfDelta.body)).not.toBe(buf(originalDelta.body));
    const gap = reset();
    expect(copyFrame(gap)).toBe(gap);
  });

  it("a copy outlives the transfer of its original", () => {
    const original = delta();
    const copy = copyFrame(original);
    if (copy.kind !== "d") throw new Error("not a delta");
    const sent = structuredClone(original, { transfer: [buf(original.body)] });
    expect(buf(original.body).byteLength).toBe(0); // detached at the sender
    expect(new Uint8Array(buf(copy.body))).toEqual(new Uint8Array([9, 8])); // the other tab's copy is whole
    expect(buf(sent.body).byteLength).toBe(2);
  });

  it("lists each buffer once, in order, and none for a reset or a structured body", () => {
    const first = snap();
    const second = delta();
    expect(transferListOf([reset(), first, second, first])).toEqual([
      buf(first.bodies[0]),
      buf(first.bodies[2]),
      buf(second.body),
    ]);
    expect(transferListOf([reset(), { ...delta(), body: { e: "j", p: {} } }])).toEqual([]);
    expect(transferListOf([])).toEqual([]);
  });
});
