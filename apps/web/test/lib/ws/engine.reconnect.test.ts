// E17-T04 S4 (23 4.4, 9.2; C7): what the connection does when the socket ends.
import { afterEach, describe, expect, it, vi } from "vitest";
import { onWsError } from "../../../src/lib/ws/errorHandler";
import { backoffDelayWithJitter } from "../../../src/shell/bootstrap/backoff";
import { connectionHarness, tokenOf } from "./support/connectionHarness";
import { BOOK, engineHarness, spec } from "./support/engineHarness";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

/** A seeded LCG: the same samples on every run. */
const seeded = (seed: number) => () =>
  (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32;
/** The waits between the sockets the client created: every connect is refused at once, so each is a reconnect delay. */
const gaps = (conns: readonly { at: number }[]) =>
  conns.slice(1).map((conn, i) => conn.at - (conns[i]?.at ?? 0));

describe("backoff (9.2, C7)", () => {
  it("Backoff is jittered and respects fatal codes", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.close(1011); // the server fails: the first row of the table
    expect(t.events.at(-1)).toEqual({
      type: "reconnecting",
      attempt: 1,
      nextAttemptAtMs: Date.now() + 500,
    });
    await t.advance(499);
    expect(t.gateway.conns).toHaveLength(1);
    await t.advance(1);
    expect(t.gateway.conns).toHaveLength(2);
    // 4403: no reconnect, a fatal state, and `forbidden` reaches the error mapping
    await t.advance(100);
    const errors: string[] = [];
    const off = onWsError((code) => errors.push(code));
    t.gateway.latest.send({ t: "err", p: { code: "forbidden", message: "disabled" } });
    t.gateway.latest.bye("user_disabled", 4403, { reconnect: false });
    off();
    expect(errors).toEqual(["forbidden"]);
    expect(t.events.at(-1)).toEqual({ type: "offline", cause: "fatal", closeCode: 4403 });
    await t.advance(600_000);
    expect(t.gateway.conns).toHaveLength(2);
  });

  it.each([1002, 1009, 4400, 4403])("never reconnects on %i", async (code) => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.close(code);
    await t.advance(600_000);
    expect([t.gateway.conns.length, t.events.at(-1)]).toEqual([
      1,
      { type: "offline", cause: "fatal", closeCode: code },
    ]);
  });

  it("waits the rows of the table with full jitter while connects keep failing", async () => {
    const t = connectionHarness(undefined, { random: seeded(7) });
    t.gateway.refuse(7);
    t.connection.start();
    await t.advance(300_000);
    const random = seeded(7);
    const expected = Array.from({ length: 7 }, (_, i) => backoffDelayWithJitter(i + 1, random));
    expect(gaps(t.gateway.conns)).toEqual(expected);
    expect(new Set(expected).size).toBeGreaterThan(5);
    expect(t.connection.counters.reconnects).toBe(7);
  });

  it("starts the table again at auth_ok, not at open", async () => {
    const t = connectionHarness();
    t.gateway.refuse(2);
    await t.connect();
    await t.advance(1_600); // 500 ms, then 1 000 ms: the third socket opens and authenticates
    expect(t.connection.ready).toBe(true);
    t.gateway.latest.close(1011);
    expect(t.events.at(-1)).toMatchObject({ type: "reconnecting", attempt: 1 });
  });

  it("open-then-4401 keeps the attempt count rising, and the token is renewed before each socket", async () => {
    const t = connectionHarness();
    t.connection.start();
    for (const wait of [0, 500, 1_000]) {
      await t.advance(wait); // the socket opens and `hello` goes; `auth` still waits its 40 ms
      t.gateway.latest.bye("auth_timeout", 4401);
    }
    expect(
      t.events
        .filter((e) => e.type === "reconnecting")
        .map((e) => e.type === "reconnecting" && e.attempt),
    ).toEqual([1, 2, 3]);
    expect(t.tokens.invalidate).toHaveBeenCalledTimes(3);
    expect(t.tokens.invalidate.mock.invocationCallOrder[0]).toBeLessThan(
      t.tokens.getToken.mock.invocationCallOrder[1] ?? 0,
    );
    await t.advance(2_100);
    expect(t.gateway.latest.of("auth")[0]).toMatchObject({ p: { access_token: tokenOf(4) } });
  });

  it("takes bye.retry_after_ms as a floor under the table", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.bye("server_shedding_load", 1013, { retry_after_ms: 5_000 });
    const event = t.events.at(-1);
    const wait = event?.type === "reconnecting" ? event.nextAttemptAtMs - Date.now() : 0;
    expect(wait).toBeGreaterThanOrEqual(5_000);
    expect(wait).toBeLessThanOrEqual(5_500);
  });
});

describe("what the user sees", () => {
  it.each([
    [true, "tailnet_unreachable"],
    [false, "offline"],
  ])(
    "a connect that never opens is offline for the tracker's cause (online %s)",
    async (online, cause) => {
      vi.spyOn(navigator, "onLine", "get").mockReturnValue(online);
      const t = connectionHarness();
      t.gateway.refuse(1);
      t.connection.start();
      await t.advance(0);
      expect(t.events).toEqual([{ type: "connecting" }, { type: "offline", cause }]);
      await t.advance(500);
      expect(t.gateway.conns).toHaveLength(2); // and it keeps trying
    },
  );

  it("an open socket is a reachable network: a later refused token is offline for no network cause", async () => {
    const t = connectionHarness();
    t.gateway.refuse(1);
    t.connection.start();
    await t.advance(0);
    expect(t.events.at(-1)).toEqual({ type: "offline", cause: "tailnet_unreachable" });
    await t.advance(500); // the second attempt opens, and the gateway hangs up before auth_ok
    t.gateway.latest.close(1011);
    t.tokens.queue.push({ kind: "unavailable" }); // the third finds no token
    await t.advance(1_000);
    expect(t.events.at(-1)).toEqual({ type: "offline", cause: "offline" });
  });

  it("tells the streams their baseline is gone before it announces the reconnect", async () => {
    const t = connectionHarness();
    await t.connect();
    let seen = -1;
    t.hooks.down.mockImplementation(() => void (seen = t.events.length));
    t.gateway.latest.close(1011);
    expect(t.hooks.down).toHaveBeenCalledTimes(1);
    expect(t.events[seen]).toMatchObject({ type: "reconnecting" });
  });
});

describe("ending the connection", () => {
  it("a stop closes 1000 and never reconnects, not even from the wait", async () => {
    const t = connectionHarness();
    await t.connect();
    t.connection.stop();
    expect(t.gateway.latest.closedByClient).toEqual({ code: 1000, reason: "client_stop" });
    const u = connectionHarness();
    await u.connect();
    u.gateway.latest.close(1011); // in the wait
    u.connection.stop();
    expect(vi.getTimerCount()).toBe(0); // the reconnect is cancelled, not left to fire
    await t.advance(60_000);
    expect([
      t.gateway.conns.length,
      u.gateway.conns.length,
      t.types().includes("reconnecting"),
    ]).toEqual([1, 1, false]);
  });

  it("a stop during the token wait never opens a socket", async () => {
    const t = connectionHarness();
    t.tokens.getToken.mockImplementationOnce(() => new Promise(() => {}));
    t.connection.start();
    t.connection.stop();
    await t.advance(60_000);
    expect(t.gateway.conns).toHaveLength(0);
  });

  it("frames queued when the socket goes are dropped with it: nothing is retried", async () => {
    const t = connectionHarness();
    t.connection.start();
    await t.advance(0); // hello is out, welcome is back, and auth waits for its 40 ms
    t.gateway.latest.close(1011);
    expect(vi.getTimerCount()).toBe(1); // the reconnect, and not the pacer's wait for a frame with no socket
    await t.advance(500);
    await t.advance(100);
    expect(t.gateway.latest.of("auth")).toHaveLength(1);
  });

  it("ignores what a socket it gave up on still says", async () => {
    const t = connectionHarness();
    await t.connect();
    const old = t.gateway.latest;
    old.mute();
    await t.advance(45_100); // silence: abandoned, reconnect in 500 ms
    old.lateClose(1006); // its close event arrives late
    old.lateMessage({ t: "d", ch: "ticker.BTCUSDT", s: 1, p: {} });
    expect(t.events.filter((e) => e.type === "reconnecting")).toHaveLength(1);
    expect(t.frames.filter((f) => f.t === "d")).toEqual([]); // nor does its data reach the streams
    await t.advance(500);
    expect(t.gateway.conns).toHaveLength(2);
  });

  it("a socket factory that throws fails the attempt like any other", async () => {
    const createSocket = vi.fn(() => {
      throw new SyntaxError("bad url");
    });
    const t = connectionHarness(undefined, { createSocket });
    t.connection.start();
    await t.advance(500);
    expect(createSocket).toHaveBeenCalledTimes(2);
    expect(t.types()).toEqual(["connecting", "offline", "connecting", "offline"]);
  });
});

describe("subscribing again after a reconnect (9.3)", () => {
  /** Consumed in no order that helps: the private topics last, a pane that is not focused first. */
  const consumeWorkspace = (t: ReturnType<typeof engineHarness>) => {
    const priv = (ch: string) => spec(ch, { paneId: "account", priority: "private" });
    t.engine.consume(spec("bars.BTCUSDT.time.5", { paneId: "p3", priority: "other" }));
    t.engine.consume(priv("wallet"));
    t.engine.consume(spec(BOOK, { paneId: "p1" })); // focused
    t.engine.consume(priv("executions"));
    t.engine.consume(spec("trades.BTCUSDT", { paneId: "p1" }));
    t.engine.consume(priv("orders"));
    t.engine.consume(spec("footprint.BTCUSDT.time.5", { paneId: "p2", priority: "other" }));
    t.engine.consume(priv("positions"));
    t.engine.consume(priv("trade_groups")); // private, but not one of the four 9.3 names
  };
  const ORDER = [
    "orders",
    "positions",
    "executions",
    "wallet",
    "trade_groups",
    BOOK,
    "trades.BTCUSDT",
    "bars.BTCUSDT.time.5",
    "footprint.BTCUSDT.time.5",
  ];

  it("Resubscription is prioritised", async () => {
    const t = engineHarness({ limits: { max_topics_per_request: 3 } });
    consumeWorkspace(t);
    await t.start();
    expect(t.subscribed()).toEqual(ORDER); // system is implicit: it is never subscribed
    t.gateway.latest.close(1011);
    t.gateway.refuse(3);
    await t.advance(30_000); // an outage of 30 s
    expect(t.gateway.conns.length).toBeGreaterThan(2);
    const [first, second, third] = t.gateway.latest.of("sub");
    expect(t.subscribed()).toEqual(ORDER); // private, then the focused pane, then the others
    expect(
      [first, second, third].map((f) => (f?.["p"] as { topics: unknown[] }).topics.length),
    ).toEqual([3, 3, 3]);
    expect(t.gateway.latest.received.map((f) => f["t"]).slice(0, 3)).toEqual([
      "hello",
      "auth",
      "sub",
    ]);
  });

  it("a focused pane that changed is the one that comes after the private topics", async () => {
    const t = engineHarness();
    t.engine.consume(spec("trades.BTCUSDT", { paneId: "p2", priority: "focused" }));
    t.engine.consume(spec(BOOK, { paneId: "p1", priority: "focused" }));
    t.engine.consume(spec("orders", { paneId: "account", priority: "private" }));
    t.engine.focusPane("p1"); // both specs say focused; the app has moved the focus to p1
    await t.start();
    expect(t.subscribed()).toEqual(["orders", BOOK, "trades.BTCUSDT"]);
  });
});
