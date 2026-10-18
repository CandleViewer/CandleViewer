// E17-T04 S4 (23 3.6, 4.2-4.3, 9.1; C1, C6): the handshake, and what keeps a connection honest (`core/connection.ts`).
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TokenResult } from "../../../src/lib/ws/api";
import {
  MAX_INBOUND_CHARS,
  MAX_TOKEN_LENGTH,
  MIN_TOKEN_LENGTH,
  TOKEN_WAIT_MS,
} from "../../../src/lib/ws/core/connection";
import { assertEngineOrder } from "./support/engineEvents";
import { connectionHarness, tokenOf, URL } from "./support/connectionHarness";

afterEach(() => vi.useRealTimers());

describe("handshake (C1)", () => {
  it("offers cv.v1.json only, and the token is not in the URL", async () => {
    const t = connectionHarness();
    await t.connect();
    const conn = t.gateway.latest;
    expect([conn.url, conn.protocols]).toEqual([URL, ["cv.v1.json"]]);
  });

  it("C1: hello is the first frame and auth the second, and nothing else is sent before auth_ok", async () => {
    const t = connectionHarness();
    const started = Date.now();
    await t.connect();
    const [hello, auth, ...rest] = t.gateway.latest.received;
    expect(hello).toMatchObject({
      t: "hello",
      p: { client: "candleviewer-web", client_version: "1.0.0", shell: "browser", locale: "en-GB" },
    });
    expect((hello?.["p"] as { clock_ms: unknown }).clock_ms).toBe(started); // our clock when it was sent (4.2)
    expect(auth).toMatchObject({ t: "auth", p: { access_token: tokenOf(1) } });
    expect(rest).toEqual([]);
  });

  it("announces the socket, then welcome, then auth_ok, and is ready once", async () => {
    const t = connectionHarness();
    await t.connect();
    expect(t.events).toEqual([
      { type: "connecting" },
      { type: "welcome", connectionId: "ws_1" },
      { type: "auth_ok", killSwitch: { engaged: false, scope: "global" } },
    ]);
    assertEngineOrder(t.events);
    expect([t.connection.ready, t.hooks.ready.mock.calls.length]).toEqual([true, 1]);
  });

  it("honours welcome.limits rather than a constant", async () => {
    const t = connectionHarness({ limits: { max_topics_per_request: 2 } });
    await t.connect();
    expect(t.connection.topicsPerRequest).toBe(2);
  });

  it("answers a server ping with a pong at once, and a pong never counts against the rate limit", async () => {
    const t = connectionHarness();
    await t.connect();
    const conn = t.gateway.latest;
    for (let i = 0; i < 40; i += 1) t.gateway.ping(conn); // 40 in one instant: over 30 a second
    const pongs = conn.of("pong");
    expect(pongs).toHaveLength(40); // no wait: C6 asks for one inside 10 s
    expect(pongs[0]).toMatchObject({ id: "s-hb-1", p: { client_ms: Date.now() } });
  });

  it("pre-auth pings cannot starve the auth frame: a thousand are answered with three pongs", async () => {
    const t = connectionHarness({ pingsBeforeWelcome: 1_000 }); // before auth_ok a pong is paced like any frame
    t.connection.start();
    await t.advance(300); // hello, three pongs 40 ms apart, then auth
    const conn = t.gateway.latest;
    expect(conn.of("pong")).toHaveLength(3);
    expect(conn.of("auth")).toHaveLength(1);
    expect(t.connection.ready).toBe(true);
  });

  it("pings that come while auth is pending are capped like the ones before welcome", async () => {
    const t = connectionHarness();
    t.connection.start();
    await t.advance(1); // hello went and welcome came back: auth waits its 40 ms
    for (let i = 0; i < 50; i += 1) t.gateway.ping(t.gateway.latest);
    await t.advance(300);
    expect(t.gateway.latest.of("pong")).toHaveLength(3);
    expect(t.connection.ready).toBe(true);
  });

  it("pings every welcome.heartbeat.interval_ms", async () => {
    const t = connectionHarness({ heartbeat: { interval_ms: 10_000, timeout_ms: 45_000 } });
    await t.connect();
    const pings = () => t.gateway.latest.of("ping").length;
    await t.advance(9_900);
    expect(pings()).toBe(0);
    await t.advance(100);
    expect(pings()).toBe(1);
    await t.advance(10_000);
    expect(pings()).toBe(2);
  });
});

describe("what welcome says of the heartbeat is bounded", () => {
  it("a zero interval is one ping a second, not a loop", async () => {
    const t = connectionHarness({ heartbeat: { interval_ms: 0, timeout_ms: 45_000 } });
    await t.connect();
    await t.advance(10_000);
    expect(t.gateway.latest.of("ping").length).toBeLessThanOrEqual(10);
    expect(t.gateway.latest.of("ping").length).toBeGreaterThanOrEqual(9);
  });

  it("an interval and a timeout past 5 minutes are 5 minutes", async () => {
    const huge = 3_000_000_000; // a timer past 2^31 ms would fire at once
    const t = connectionHarness({ heartbeat: { interval_ms: huge, timeout_ms: huge } });
    await t.connect();
    await t.advance(299_000);
    expect(t.gateway.latest.of("ping")).toHaveLength(0);
    await t.advance(1_100);
    expect(t.gateway.latest.of("ping")).toHaveLength(1);
    t.gateway.latest.mute();
    await t.advance(301_000); // silence: the 5-minute timeout, not 2^31 ms and not 0
    expect(t.gateway.conns[0]?.closedByClient).toEqual({ code: 4000, reason: "heartbeat_timeout" });
  });
});

describe("silence and bounds", () => {
  it("closes after timeout_ms without a word from the server, and not before", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.mute();
    await t.advance(45_039 - 100); // the last word was auth_ok, at 40 ms: 45 s of silence is 45 040 ms
    expect(t.gateway.latest.closedByClient).toBeUndefined();
    await t.advance(1);
    expect(t.gateway.latest.closedByClient).toEqual({ code: 4000, reason: "heartbeat_timeout" });
    expect(t.types().at(-1)).toBe("reconnecting");
  });

  it("any traffic keeps it alive: a quiet link that still answers pings is not closed", async () => {
    const t = connectionHarness({ heartbeat: { interval_ms: 15_000, timeout_ms: 20_000 } });
    await t.connect();
    await t.advance(120_000); // six times the timeout: each ping's pong is the traffic
    expect(t.gateway.latest.closedByClient).toBeUndefined();
    expect(t.gateway.conns).toHaveLength(1);
  });

  it("abandons a handshake that never completes, after 15 s: the gateway waits 10 s for auth", async () => {
    const t = connectionHarness({ silent: true });
    t.connection.start();
    await t.advance(14_999);
    expect(t.connection.ready).toBe(false);
    expect(t.gateway.conns[0]?.closedByClient).toBeUndefined();
    await t.advance(1);
    expect(t.gateway.conns[0]?.closedByClient).toEqual({ code: 4000, reason: "handshake_timeout" });
  });

  it("closes on a message over 4 MiB without parsing it, but parses one of exactly that size", async () => {
    const t = connectionHarness();
    await t.connect();
    const parse = vi.spyOn(JSON, "parse");
    t.gateway.latest.raw(JSON.stringify({ t: "pong" }).padEnd(MAX_INBOUND_CHARS));
    expect([parse.mock.calls.length, t.connection.counters.malformedFrames]).toEqual([1, 0]);
    t.gateway.latest.raw(" ".repeat(MAX_INBOUND_CHARS + 1));
    expect([parse.mock.calls.length, t.connection.counters.malformedFrames]).toEqual([1, 1]);
    // the server broke the protocol: the socket is closed 1002, and the connection is lost like any other
    const first = t.gateway.latest;
    expect(first.closedByClient).toEqual({ code: 1002, reason: "frame_too_big" });
    expect(t.events.at(-1)).toMatchObject({ type: "reconnecting", attempt: 1 });
    expect([t.connection.ready, t.hooks.down.mock.calls.length]).toEqual([false, 1]);
    await t.advance(500); // 9.2: the first retry, on the ordinary backoff
    expect(t.gateway.conns).toHaveLength(2);
    await t.advance(100);
    expect(t.connection.ready).toBe(true);
  });

  it("counts an undecodable message and reports it", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.raw("not json");
    expect(t.connection.counters.malformedFrames).toBe(1);
    expect(t.hooks.malformed).toHaveBeenCalledWith(
      expect.objectContaining({ t: "decode_error", code: "frame_malformed" }),
    );
  });
});

describe("the token", () => {
  it.each([
    ["locked", { kind: "locked" }],
    ["unavailable", { kind: "unavailable" }],
    [
      "shorter than the 20 characters auth takes",
      { kind: "ok", accessToken: "a".repeat(19), expiresAtMs: Date.now() + 1e6 },
    ],
    [
      "over the 8 KiB pre-auth cap",
      { kind: "ok", accessToken: "a".repeat(MAX_TOKEN_LENGTH + 1), expiresAtMs: Date.now() + 1e6 },
    ],
    ["already expired", { kind: "ok", accessToken: tokenOf(9), expiresAtMs: Date.now() - 1 }],
  ] as const)(
    "a %s token opens no socket, goes offline, and retries on the backoff, not in a loop",
    async (_, answer) => {
      const t = connectionHarness();
      t.tokens.queue.push(answer);
      t.connection.start();
      await t.advance(499);
      expect([t.gateway.conns.length, t.types(), t.tokens.getToken.mock.calls.length]).toEqual([
        0,
        ["offline"],
        1,
      ]);
      await t.advance(1); // 9.2: the first retry waits 500 ms
      expect([t.tokens.getToken.mock.calls.length, t.gateway.conns.length]).toEqual([2, 1]);
    },
  );

  it.each([MIN_TOKEN_LENGTH, MAX_TOKEN_LENGTH])(
    "a token of exactly %i characters is used",
    async (length) => {
      const t = connectionHarness();
      t.tokens.queue.push({
        kind: "ok",
        accessToken: "a".repeat(length),
        expiresAtMs: Date.now() + 1e6,
      });
      await t.connect();
      expect(t.gateway.latest.of("auth")).toEqual([
        expect.objectContaining({ p: { access_token: "a".repeat(length) } }),
      ]);
    },
  );

  it("a source that never answers counts as unavailable after TOKEN_WAIT_MS", async () => {
    const t = connectionHarness();
    t.tokens.getToken.mockImplementationOnce(() => new Promise(() => {}));
    t.connection.start();
    await t.advance(TOKEN_WAIT_MS - 1);
    expect(t.types()).toEqual([]);
    await t.advance(1);
    expect(t.types()).toEqual(["offline"]);
  });

  it("a source that throws counts as unavailable", async () => {
    const t = connectionHarness();
    t.tokens.getToken.mockImplementationOnce(() => {
      throw new Error("no port");
    });
    t.connection.start();
    await t.advance(0);
    expect(t.types()).toEqual(["offline"]);
  });

  it("a source that hangs is awaited once, and not asked again while it is pending", async () => {
    const t = connectionHarness();
    let answer: (result: TokenResult) => void = () => undefined;
    t.tokens.getToken.mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)));
    t.connection.start();
    await t.advance(TOKEN_WAIT_MS + 500); // given up on at 10 s; the retry, 500 ms later, waits for the same call
    expect([t.types(), t.tokens.getToken.mock.calls.length]).toEqual([["offline"], 1]);
    answer({ kind: "ok", accessToken: tokenOf(7), expiresAtMs: Date.now() + 1e6 });
    await t.advance(200);
    expect(t.gateway.latest.of("auth")).toEqual([
      expect.objectContaining({ p: { access_token: tokenOf(7) } }),
    ]);
    expect(t.tokens.getToken).toHaveBeenCalledTimes(1);
  });

  it("is held only until auth is built: it is in the auth frame and nowhere else", async () => {
    const t = connectionHarness();
    await t.connect();
    const seen = JSON.stringify([
      t.events,
      t.frames,
      t.gateway.latest.url,
      t.gateway.latest.of("hello"),
    ]);
    expect(seen).not.toContain(tokenOf(1));
    expect(t.gateway.latest.of("auth")).toHaveLength(1);
  });
});

describe("what the session settles and what it hands on", () => {
  it("hands everything else to the engine, with the time it took to decode", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.send({ t: "d", ch: "ticker.BTCUSDT", s: 1, p: {} });
    t.gateway.latest.send({ t: "sub_ok", id: "c-9", p: { results: [] } });
    t.gateway.latest.send({ t: "err", id: "c-9", p: { code: "degraded_data", message: "m" } });
    expect(t.frames.slice(-3).map((f) => f.t)).toEqual(["d", "sub_ok", "err"]);
    expect(t.hooks.frame).toHaveBeenCalledWith(expect.anything(), expect.any(Number));
  });

  it("answers a server ping that carries no id, and ignores pongs and permission_change", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.send({ t: "ping", p: {} });
    t.gateway.latest.send({ t: "pong", p: {} });
    t.gateway.latest.send({
      t: "permission_change",
      p: { user_id: "u1", roles: ["owner"], permissions: [], account_scope: [] },
    });
    expect(t.gateway.latest.of("pong")).toEqual([
      { t: "pong", id: expect.stringMatching(/^c-\d+$/), p: { client_ms: Date.now() } },
    ]);
    expect(t.frames.filter((f) => ["ping", "pong", "permission_change"].includes(f.t))).toEqual([]); // settled here
  });

  it("ignores a second welcome and an auth_ok nobody asked for", async () => {
    const t = connectionHarness();
    await t.connect();
    const seen = t.events.length;
    const welcome = {
      protocol: "cv.v1",
      encoding: "json",
      server_version: "t",
      connection_id: "ws_x",
      server_time_ms: Date.now(),
      auth_required: true,
      heartbeat: { interval_ms: 1, timeout_ms: 1 },
      limits: {
        max_subscriptions: 1,
        max_topics_per_request: 1,
        max_inbound_frame_bytes: 1,
        max_outbound_frame_bytes: 1,
        min_throttle_ms: 1,
      },
    };
    t.gateway.latest.send({ t: "welcome", p: welcome });
    t.gateway.latest.send({
      t: "auth_ok",
      p: {
        user_id: "u",
        roles: [],
        permissions: [],
        account_scope: [],
        session_id: "s",
        token_expires_at_ms: 1,
      },
    });
    expect(t.events).toHaveLength(seen);
    expect(t.connection.topicsPerRequest).toBe(50);
  });

  it("an err that answers another frame does not end the auth that is pending", async () => {
    const t = connectionHarness();
    t.connection.start();
    await t.advance(1); // auth is waiting
    t.gateway.latest.send({
      t: "err",
      id: "c-999",
      p: { code: "auth_failed", message: "not ours" },
    });
    await t.advance(300);
    expect([t.connection.ready, t.tokens.invalidate.mock.calls.length]).toEqual([true, 0]);
    expect(t.gateway.latest.closedByClient).toBeUndefined();
  });

  it("an auth_ok that answers another frame is not the answer to auth", async () => {
    const t = connectionHarness({ authOkId: "c-999" });
    await t.connect();
    expect([t.connection.ready, t.hooks.ready.mock.calls.length]).toEqual([false, 0]);
    expect(t.types()).toEqual(["connecting", "welcome"]);
  });

  it("keeps what bye says of the costly topics, five at most and each a bounded name", async () => {
    const t = connectionHarness();
    await t.connect();
    const topics = ["heatmap.BTCUSDT", "x".repeat(121), "x".repeat(120), "a", "b", "c", "d"];
    t.gateway.latest.bye("slow_consumer", 4429, { hint: { most_expensive_topics: topics } });
    expect(t.connection.slowConsumerHint).toEqual([
      "heatmap.BTCUSDT",
      "x".repeat(120),
      "a",
      "b",
      "c",
    ]);
  });

  it("keeps no hint that is not a list of names", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.bye("slow_consumer", 4429, {
      hint: { most_expensive_topics: "heatmap.BTCUSDT" },
    });
    expect(t.connection.slowConsumerHint).toEqual([]);
    expect(t.connection.counters.malformedFrames).toBe(0); // and it did not throw out of the handler
  });

  it("surfaces the request_id of an error for the diagnostics, bounded", async () => {
    const t = connectionHarness();
    await t.connect();
    const err = (request_id: unknown) => ({
      t: "err",
      p: { code: "degraded_data", message: "m", request_id },
    });
    t.gateway.latest.send(err("urn:cv:req:1"));
    t.gateway.latest.send(err("x".repeat(121)));
    t.gateway.latest.send(err("y".repeat(120)));
    t.gateway.latest.send(err(7));
    expect(t.events.filter((e) => e.type === "request_id")).toEqual([
      { type: "request_id", requestId: "urn:cv:req:1" },
      { type: "request_id", requestId: "y".repeat(120) },
    ]);
  });

  it("starts once, stops once, and sends nothing before it is ready", async () => {
    const t = connectionHarness();
    t.connection.send({ t: "ping", id: "c-0", p: { client_ms: 0 } });
    t.connection.start();
    t.connection.start();
    await t.advance(100);
    expect(t.gateway.conns).toHaveLength(1);
    expect(t.gateway.latest.of("ping")).toEqual([]);
    t.connection.stop();
    t.connection.stop();
    t.connection.start();
    expect(t.gateway.latest.closedByClient).toEqual({ code: 1000, reason: "client_stop" });
  });

  it("reconnects even when the socket cannot be closed", async () => {
    const t = connectionHarness(
      { silent: true },
      {
        createSocket: (url, protocols, events) => {
          const socket = t.gateway.createSocket(url, protocols, events);
          return {
            send: (data) => socket.send(data),
            close: () => {
              throw new Error("InvalidStateError");
            },
          };
        },
      },
    );
    t.connection.start();
    await t.advance(15_000);
    expect(t.types().at(-1)).toBe("reconnecting");
  });
});
