// E17-T04 S4 (23 3.6, 4.2-4.3, 9.1; C1, C6): the handshake, and what keeps a connection honest (`core/connection.ts`).
import { afterEach, describe, expect, it, vi } from "vitest";
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
});

describe("silence and bounds", () => {
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
});
