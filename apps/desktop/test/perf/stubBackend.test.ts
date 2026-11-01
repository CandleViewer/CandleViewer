import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import type { Duplex } from "node:stream";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  decodeFrames,
  encodeFrame,
  gatewayReplies,
  startStubBackend,
  type StubBackend,
} from "../../e2e/perf/support/stubBackend";

// E10-Q04 PR-2: the loopback stub backend the cold-start harness boots the shell against
// (BQ-Q04-08). Fixed payloads and a fixed clock; the server binds 127.0.0.1 only.

const now = () => 1_000;

/** A client → server frame: masked, as RFC 6455 requires of a client. */
function masked(text: string): Buffer {
  const body = Buffer.from(text, "utf8");
  const mask = Buffer.from([1, 2, 3, 4]);
  const head =
    body.length < 126
      ? Buffer.from([0x81, 0x80 | body.length])
      : Buffer.from([0x81, 0x80 | 126, body.length >> 8, body.length & 0xff]);
  return Buffer.concat([head, mask, body.map((b, i) => b ^ (mask[i % 4] as number))]);
}

describe("WebSocket framing", () => {
  it("decodeFrames_maskedShortAndExtended_unmasksBoth", () => {
    const long = "x".repeat(300);
    const { frames, rest } = decodeFrames(Buffer.concat([masked("hi"), masked(long)]));
    expect(frames.map((f) => f.payload.toString())).toEqual(["hi", long]);
    expect(rest.length).toBe(0);
  });

  it("decodeFrames_partialFrame_isKeptAsRest", () => {
    const whole = masked("hello");
    const { frames, rest } = decodeFrames(whole.subarray(0, 5));
    expect(frames).toEqual([]);
    expect(rest.length).toBe(5);
  });

  it("decodeFrames_eightByteLength_isRefusedNotMisread", () => {
    const header = Buffer.from([0x81, 0x80 | 127]);
    expect(() => decodeFrames(header)).toThrow(RangeError);
  });

  it("encodeFrame_roundTrips_throughDecode", () => {
    for (const text of ["", "a", "y".repeat(126), "z".repeat(60_000)]) {
      const [frame] = decodeFrames(encodeFrame(text)).frames;
      expect(frame?.opcode).toBe(0x1);
      expect(frame?.payload.toString()).toBe(text);
    }
  });
});

describe("gatewayReplies", () => {
  it("gatewayReplies_hello_welcomesWithTheBuildVersion", () => {
    const [welcome] = gatewayReplies({ t: "hello", id: "h1" }, "1.2.3", now);
    expect(welcome).toMatchObject({
      t: "welcome",
      id: "h1",
      p: { protocol: "cv.v1", server_version: "1.2.3" },
    });
  });

  it("gatewayReplies_auth_answersAuthOkThenTheSystemSnapshot", () => {
    const replies = gatewayReplies({ t: "auth", id: "a1", p: {} }, "1.2.3", now);
    expect(replies.map((r) => r.t)).toEqual(["auth_ok", "snap"]);
    expect(replies[1]).toMatchObject({
      ch: "system",
      s: 1,
      p: { kind: "health", health: "healthy" },
    });
  });

  it("gatewayReplies_subAndPing_areAcknowledged", () => {
    const [subOk] = gatewayReplies(
      { t: "sub", id: "s1", p: { topics: ["ticker.BTCUSDT", { ch: "system" }] } },
      "v",
      now,
    );
    expect(subOk).toMatchObject({
      t: "sub_ok",
      p: {
        results: [
          { ch: "ticker.BTCUSDT", ok: true },
          { ch: "system", ok: true },
        ],
      },
    });
    expect(gatewayReplies({ t: "ping", id: "p1" }, "v", now)[0]).toMatchObject({
      t: "pong",
      p: { server_ms: 1_000 },
    });
    expect(gatewayReplies({ t: "unsub", id: "u1" }, "v", now)).toEqual([]);
  });
});

describe("startStubBackend", () => {
  let root: string;
  let stub: StubBackend;

  beforeAll(async () => {
    root = mkdtempSync(path.join(os.tmpdir(), "cv-stub-test-"));
    writeFileSync(path.join(root, "index.html"), "<p>shell</p>");
    stub = await startStubBackend({
      webRoot: root,
      rest: { "/api/v1/me": { role: "owner" } },
      version: "1.2.3",
      now,
    });
  });

  afterAll(async () => {
    await stub.close();
    rmSync(root, { recursive: true, force: true });
  });

  it("startStubBackend_origin_isLoopbackOnly", () => {
    expect(stub.origin).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/u);
  });

  it("startStubBackend_tableAndSpa_answerAndRecordTheRest", async () => {
    expect(await (await fetch(`${stub.origin}/api/v1/me`)).json()).toEqual({ role: "owner" });
    expect(await (await fetch(`${stub.origin}/terminal/last`)).text()).toBe("<p>shell</p>");
    expect((await fetch(`${stub.origin}/assets/missing.js`)).status).toBe(404);
    expect((await fetch(`${stub.origin}/api/v1/unknown`, { method: "POST" })).status).toBe(404);
    expect(stub.unanswered()).toEqual(["POST /api/v1/unknown"]);
  });

  it("startStubBackend_ws_completesTheHandshakeAndWelcomes", async () => {
    // A raw upgrade (Node 20 has no WebSocket client): the handshake, then one masked `hello`.
    const req = http.request(`${stub.origin}/api/v1/ws`, {
      headers: {
        connection: "Upgrade",
        upgrade: "websocket",
        "sec-websocket-version": "13",
        "sec-websocket-key": Buffer.from("the sample nonce").toString("base64"),
        "sec-websocket-protocol": "cv.v1.json",
      },
    });
    const [res, socket] = await new Promise<[http.IncomingMessage, Duplex]>((resolve) => {
      req.on("upgrade", (r: http.IncomingMessage, s: Duplex) => resolve([r, s]));
      req.end();
    });
    // RFC 6455 §1.3's worked example: this key's accept value.
    expect(res.headers["sec-websocket-accept"]).toBe("s3pPLMBiTxaQ9kYGzzhZRbK+xOo=");
    expect(res.headers["sec-websocket-protocol"]).toBe("cv.v1.json");
    const reply = new Promise<string>((resolve) =>
      socket.on("data", (chunk: Buffer) => {
        const [frame] = decodeFrames(chunk).frames;
        if (frame !== undefined) resolve(frame.payload.toString());
      }),
    );
    socket.write(masked(JSON.stringify({ t: "hello", id: "h1" })));
    expect(JSON.parse(await reply)).toMatchObject({ t: "welcome", id: "h1" });
    socket.destroy();
  });

  it("startStubBackend_ws_malformedTextFrame_closesTheSocketNotTheStub", async () => {
    const req = http.request(`${stub.origin}/api/v1/ws`, {
      headers: {
        connection: "Upgrade",
        upgrade: "websocket",
        "sec-websocket-version": "13",
        "sec-websocket-key": Buffer.from("the sample nonce").toString("base64"),
        "sec-websocket-protocol": "cv.v1.json",
      },
    });
    const socket = await new Promise<Duplex>((resolve) => {
      req.on("upgrade", (_r: http.IncomingMessage, s: Duplex) => resolve(s));
      req.end();
    });
    const closed = new Promise<void>((resolve) => socket.on("close", () => resolve()));
    socket.write(masked("{not json"));
    await closed;
    // The stub still answers after the bad frame.
    const res = await fetch(`${stub.origin}/api/v1/me`);
    expect(res.status).toBeLessThan(500);
  });
});
