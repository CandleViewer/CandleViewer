// E17-T04 S4 (23 5, 7, 8.4, 9, 11; C2, C5): the engine on the wire, against the fake gateway: what it
// subscribes, what it makes of gaps, revocations, closes and the replies of live and replay streams.
import { afterEach, describe, expect, it, vi } from "vitest";
import { BOOK, engineHarness, RS, spec } from "./support/engineHarness";
import type { Json } from "./support/fakeGateway";

afterEach(() => vi.useRealTimers());

/** The topics a `sub` (objects) or an `unsub` (names) frame lists. */
const topicsOf = (frame: Json | undefined) =>
  ((frame?.["p"] as Json)["topics"] as (string | { ch: string })[]).map((t) =>
    typeof t === "string" ? t : t.ch,
  );

describe("subscribing", () => {
  it("subscribes a consumer once the connection is ready, with its options and a snapshot, and delivers its snap", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(BOOK, { opts: { throttle_ms: 100 } })); // before the socket exists
    await t.advance(300);
    expect(t.gateway.conns).toEqual([]); // nothing is sent while the connection is not ready
    await t.start();
    expect(t.gateway.latest.of("sub")).toEqual([
      expect.objectContaining({
        p: { topics: [{ ch: BOOK, opts: { throttle_ms: 100 } }], snapshot: true },
      }),
    ]);
    expect(t.got()).toEqual(["snap:1"]);
    expect([handle.status, handle.source, t.engine.slowConsumerHint]).toEqual(["live", "live", []]);
  });

  it("a consumer that returns before the unsub went out takes the subscription over: one sub, no unsub", async () => {
    const t = engineHarness();
    const first = t.engine.consume(spec(BOOK));
    await t.start();
    first.release();
    t.engine.consume(spec(BOOK)); // the same task: a pane that remounts
    await t.advance(300);
    expect([t.gateway.latest.of("sub").length, t.gateway.latest.of("unsub")]).toEqual([1, []]);
  });

  it("puts the consumers of one task into one sub, chunked at welcome.limits.max_topics_per_request", async () => {
    const t = engineHarness({ limits: { max_topics_per_request: 2 } });
    await t.start();
    for (const ch of [
      "trades.BTCUSDT",
      "ticker.BTCUSDT",
      "metrics.BTCUSDT",
      BOOK,
      "bars.BTCUSDT.time.1",
    ]) {
      t.engine.consume(spec(ch));
    }
    await t.advance(300);
    expect(t.gateway.latest.of("sub").map((f) => topicsOf(f).length)).toEqual([2, 2, 1]);
  });
});

describe("a gap (7.1, C2)", () => {
  it("A gap on the wire resyncs, and nothing reaches the sink until the fresh snap", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    await t.start();
    t.got();
    const conn = t.gateway.latest;
    conn.delta(BOOK);
    conn.skip(BOOK);
    conn.delta(BOOK); // 4 after 2: 3 is lost
    conn.delta(BOOK); // 5: never applied across the gap
    expect(t.got()).toEqual(["d:2", "reset:gap"]);
    await t.advance(100);
    expect(conn.of("resync")).toEqual([
      expect.objectContaining({
        ch: BOOK,
        p: expect.objectContaining({ last_seq: 2, reason: "sequence_gap" }),
      }),
    ]);
    expect(t.got()).toEqual(["snap:6"]);
    conn.delta(BOOK);
    expect(t.got()).toEqual(["d:7"]);
    expect(t.engine.counters).toMatchObject({ gaps: 1, resyncsSent: 1 });
  });

  it("names the replay stream a resync is for in its envelope", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK), RS);
    await t.start();
    t.gateway.latest.skip(BOOK, RS);
    t.gateway.latest.delta(BOOK, {}, RS);
    await t.advance(100);
    expect(t.gateway.latest.of("resync")).toEqual([expect.objectContaining({ ch: BOOK, rs: RS })]);
  });
});

describe("snapshots the server sends unasked (7.4, 7.6, C5, C18)", () => {
  it("replaces the state whatever the reason, a reason from the future included", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    await t.start();
    t.got();
    t.gateway.latest.snap(BOOK, "upstream_desync");
    t.gateway.latest.snap(BOOK, "a_reason_from_the_future");
    t.gateway.latest.delta(BOOK);
    expect(t.got()).toEqual(["snap:2", "snap:3", "d:4"]);
  });
});

describe("live and replay streams of one ch (11)", () => {
  it("does not unsubscribe a ch while another stream of it is wanted: one unsub ends them all (5.3)", async () => {
    const t = engineHarness();
    const live = t.engine.consume(spec(BOOK));
    const replay = t.engine.consume(spec(BOOK), RS);
    await t.start();
    t.got(BOOK, RS);
    live.release();
    await t.advance(300);
    expect(t.gateway.latest.of("unsub")).toEqual([]);
    t.gateway.latest.delta(BOOK, {}, RS);
    expect(t.got(BOOK, RS)).toEqual(["d:2"]); // the replay stream was not taken down with it
    replay.release();
    await t.advance(300);
    expect(t.gateway.latest.of("unsub").map(topicsOf)).toEqual([[BOOK]]);
  });
});

describe("edges of the stream plane", () => {
  it("a stop closes the socket, forgets every stream and the resyncs still waiting, and never reconnects", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    await t.start();
    for (let gap = 0; gap < 6; gap += 1) {
      t.gateway.latest.skip(BOOK);
      t.gateway.latest.delta(BOOK);
      await t.advance(100);
    }
    expect(t.gateway.latest.of("resync")).toHaveLength(5); // the sixth waits for the window to reopen (7.5)
    t.engine.stop();
    expect(t.gateway.latest.closedByClient).toEqual({ code: 1000, reason: "client_stop" });
    expect([t.engine.counters.streams, vi.getTimerCount()]).toEqual([0, 0]);
    await t.advance(600_000);
    expect(t.gateway.conns).toHaveLength(1);
  });
  it("a malformed frame of a stream voids it and asks for a baseline", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(BOOK));
    await t.start();
    t.got();
    t.gateway.latest.raw(JSON.stringify({ t: "d", ch: BOOK, s: "x", ts: 1, p: {} }));
    await t.advance(400);
    expect(t.gateway.latest.of("resync")).toEqual([
      expect.objectContaining({
        ch: BOOK,
        p: expect.objectContaining({ last_seq: 1, reason: "decode_error" }),
      }),
    ]);
    expect([t.got(), handle.status, t.engine.counters.malformedFrames]).toEqual([
      ["reset:malformed", "snap:2"],
      "live",
      1,
    ]);
  });

  it("unsubscribes in frames of at most welcome.limits.max_topics_per_request, and keeps no stream it let go", async () => {
    const t = engineHarness({ limits: { max_topics_per_request: 2 } });
    const chs = ["trades.BTCUSDT", "ticker.BTCUSDT", "metrics.BTCUSDT"];
    const handles = chs.map((ch) => t.engine.consume(spec(ch)));
    await t.start();
    expect(t.engine.counters.streams).toBe(3);
    for (const handle of handles) handle.release();
    await t.advance(500);
    expect(t.gateway.latest.of("unsub").map((f) => topicsOf(f).length)).toEqual([2, 1]);
    t.engine.consume(spec("bars.BTCUSDT.time.1")); // another pass of the reconciliation
    await t.advance(300);
    expect(t.engine.counters.streams).toBe(1); // what was let go is not kept in a table nobody reads
  });
});
