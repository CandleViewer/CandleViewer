// E17-T04 S4 (23 5, 7, 8.4, 9, 11; C2, C5): the engine on the wire, against the fake gateway: what it
// subscribes, what it makes of gaps, revocations, closes and the replies of live and replay streams.
import { afterEach, describe, expect, it, vi } from "vitest";
import { b64, bookSnapshot, FLAG_PARTIAL } from "./support/cvwb";
import { assertEngineOrder } from "./support/engineEvents";
import { LEDGER_MAX } from "../../../src/lib/ws/core/engine";
import { BOOK, engineHarness, RS, spec } from "./support/engineHarness";
import type { Json } from "./support/fakeGateway";

afterEach(() => vi.useRealTimers());

/** The topics a `sub` (objects) or an `unsub` (names) frame lists. */
const topicsOf = (frame: Json | undefined) =>
  ((frame?.["p"] as Json)["topics"] as (string | { ch: string })[]).map((t) =>
    typeof t === "string" ? t : t.ch,
  );

/** The id the server gave the first subscription of the book. */
const bookSub = (conn: { subs(): { ch: string; id: string }[] }) =>
  conn.subs().find((s) => s.ch === BOOK)?.id;

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

  it("a sub_ok gives its stream the subscription id and the options the server settled on", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(BOOK, { opts: { throttle_ms: 100 } }));
    await t.start();
    expect([handle.status, handle.subId, handle.effective]).toEqual([
      "live",
      "s_2",
      { throttle_ms: 100 },
    ]);
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

  it("counts a snapshot the server forced", async () => {
    const t = engineHarness({ forceSnapshots: true });
    t.engine.consume(spec(BOOK));
    t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    expect(t.engine.counters.forcedSnapshots).toBe(2);
  });

  it("delivers a chunked snapshot once, whole, with the number of its last chunk", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    await t.start();
    t.got();
    const conn = t.gateway.latest;
    const chunk = (s: number | null, flags: number) => ({
      t: "snap",
      ch: BOOK,
      id: "set-1",
      s,
      e: "b64",
      p: b64(bookSnapshot(flags)),
    });
    conn.send(chunk(null, FLAG_PARTIAL));
    conn.send(chunk(null, FLAG_PARTIAL));
    expect(t.got()).toEqual([]); // a partial snapshot is never applied
    conn.send(chunk(40, 0));
    const [frame] = t.peek();
    expect(frame).toMatchObject({ kind: "snap", seq: 40 });
    expect(frame?.kind === "snap" && frame.bodies).toHaveLength(3);
    conn.send({ t: "d", ch: BOOK, s: 41, e: "j", p: {} });
    expect(t.got()).toEqual(["snap:40", "d:41"]);
  });
});

describe("the connection ends (9.2, 9.3)", () => {
  it("a token that expired: the gateway closes 4401, the token is renewed, and every stream subscribes again", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(BOOK));
    await t.start();
    t.got();
    t.gateway.latest.bye("token_expired", 4401);
    expect(t.got()).toEqual(["reset:reconnect"]);
    expect(handle.status).toBe("pending");
    expect(t.tokens.invalidate).toHaveBeenCalledTimes(1);
    await t.advance(800);
    expect(t.gateway.conns).toHaveLength(2);
    expect(t.gateway.latest.of("auth")[0]).toMatchObject({
      p: { access_token: expect.stringContaining("tok-2") },
    });
    expect(topicsOf(t.gateway.latest.of("sub")[0])).toEqual([BOOK]);
    expect([t.got(), handle.status]).toEqual([["snap:1"], "live"]);
    assertEngineOrder(t.events);
  });

  it("a slow-consumer close is waited out, sheds nothing and keeps the hint", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    t.engine.consume(spec("heatmap.BTCUSDT"));
    await t.start();
    t.gateway.latest.bye("slow_consumer", 4429, {
      retry_after_ms: 3_000,
      hint: { most_expensive_topics: ["heatmap.BTCUSDT"] },
    });
    await t.advance(2_900);
    expect(t.gateway.conns).toHaveLength(1);
    await t.advance(700);
    expect(t.gateway.conns).toHaveLength(2);
    expect(topicsOf(t.gateway.latest.of("sub")[0])).toEqual([BOOK, "heatmap.BTCUSDT"]);
    expect(t.gateway.conns[0]?.of("unsub")).toEqual([]);
    expect(t.engine.slowConsumerHint).toEqual(["heatmap.BTCUSDT"]);
  });

  it("forgets every stream: a handle outlives the connection, and a released stream is not subscribed again", async () => {
    const t = engineHarness();
    const kept = t.engine.consume(spec(BOOK));
    const gone = t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    gone.release();
    await t.advance(100);
    t.gateway.latest.close(1011);
    await t.advance(800);
    expect(topicsOf(t.gateway.latest.of("sub")[0])).toEqual([BOOK]);
    kept.release();
    await t.advance(100);
    expect(topicsOf(t.gateway.latest.of("unsub")[0])).toEqual([BOOK]);
  });
});

describe("live and replay streams of one ch (11)", () => {
  it("keeps their replies, options and numbers apart", async () => {
    const t = engineHarness();
    const live = t.engine.consume(spec(BOOK, { opts: { throttle_ms: 100 } }));
    const replay = t.engine.consume(spec(BOOK, { opts: { throttle_ms: 250 } }), RS);
    await t.start();
    const subs = t.gateway.latest.of("sub");
    expect(subs.map((f) => (f["p"] as Json)["replay_session_id"])).toEqual([undefined, RS]);
    expect(new Set(subs.map((f) => f["id"])).size).toBe(2);
    // each reply carries a ch and no stream: it lands where its request was for
    expect([live.effective, replay.effective]).toEqual([
      { throttle_ms: 100 },
      { throttle_ms: 250 },
    ]);
    expect([live.rs, replay.rs, live.source, replay.source]).toEqual([
      undefined,
      RS,
      "live",
      "replay",
    ]);
    expect([t.got(), t.got(BOOK, RS)]).toEqual([["snap:1"], ["snap:1"]]);
    t.gateway.latest.delta(BOOK, {}, RS);
    expect([t.got(), t.got(BOOK, RS)]).toEqual([[], ["d:2"]]);
  });

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

describe("an unsub and a sub of one stream (5.3)", () => {
  it("a consumer that returns after it waits for the unsub_ok, and the old subscription's late frames are dropped", async () => {
    const t = engineHarness({ hold: ["unsub_ok"] });
    const first = t.engine.consume(spec(BOOK));
    await t.start();
    t.got();
    first.release();
    await t.advance(100);
    const conn = t.gateway.latest;
    expect(conn.of("unsub")).toHaveLength(1);
    const again = t.engine.consume(spec(BOOK));
    await t.advance(300);
    expect(conn.of("sub")).toHaveLength(1); // behind the unsub_ok
    conn.send({ t: "d", ch: BOOK, s: 9, e: "j", p: {} }); // the old subscription's last frame overtakes it
    expect(t.got()).toEqual([]);
    conn.releaseHeld();
    await t.advance(300);
    expect(conn.of("sub")).toHaveLength(2);
    // the old unsub_ok is the old subscription's: it does not reach the new stream, which holds nothing of it
    expect([t.got(), again.status]).toEqual([["snap:1"], "live"]);
  });
});

// A reply says which `(ch, rs)` it is for, not which request: after a stream was let go and made again
// a late reply of the old one would land on the new one. Each request carries the generation of the
// subscription it was sent for (it advances at every `sub` and `unsub`), and a reply of another
// generation applies to nothing.
describe("a reply for a subscription that is gone (5.2, 5.3)", () => {
  /** A `sub`, the stream released, and a new one made while the first sub's reply (and the unsub_ok) are still in flight. */
  async function replaced(held: "sub_ok" | "sub_ok+unsub_ok", failFirstSub = false) {
    const t = engineHarness({ hold: held === "sub_ok" ? ["sub_ok"] : ["sub_ok", "unsub_ok"] });
    await t.start();
    if (failFirstSub) t.gateway.failSubs(1);
    const first = t.engine.consume(spec(BOOK));
    await t.advance(300); // the sub is sent
    first.release();
    await t.advance(300); // the unsub is sent
    const again = t.engine.consume(spec(BOOK));
    await t.advance(300); // behind the unsub_ok, or sent at once when that has come
    return { t, conn: t.gateway.latest, again };
  }

  it("a refusal of the old sub that comes late does not end the stream that replaced it", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined); // invalid_options is a client bug (10.3)
    const { t, conn, again } = await replaced("sub_ok+unsub_ok", true);
    expect([conn.of("sub"), conn.of("unsub")].map((frames) => frames.length)).toEqual([1, 1]);
    conn.releaseHeld(); // the old sub's err, then the unsub_ok
    await t.advance(300);
    expect([again.status, conn.of("sub")]).toEqual([
      "pending",
      [expect.anything(), expect.anything()],
    ]);
    conn.releaseHeld(); // the new sub's reply and snapshot
    await t.advance(300);
    expect([again.status, again.subId, t.got()]).toEqual(["live", bookSub(conn), ["snap:1"]]);
    again.release(); // the stream was never ended: its release unsubscribes it, once
    await t.advance(300);
    expect([conn.of("unsub").length, bookSub(conn)]).toEqual([2, undefined]);
  });

  it("the same when the unsub_ok came first and the new sub is already out", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { t, conn, again } = await replaced("sub_ok", true);
    expect(conn.of("sub")).toHaveLength(2);
    conn.releaseHeld(); // the old sub's err, then the new sub's reply
    await t.advance(300);
    expect([again.status, again.subId]).toEqual(["live", bookSub(conn)]);
    again.release();
    await t.advance(300);
    expect([conn.of("unsub").length, bookSub(conn)]).toEqual([2, undefined]);
  });

  it("an acceptance of the old sub that comes late gives the stream that replaced it nothing", async () => {
    const { t, conn, again } = await replaced("sub_ok+unsub_ok");
    const oldId = bookSub(conn); // the server subscribed it, and its reply is in flight
    conn.releaseHeld(); // the old sub_ok and snapshot, then the unsub_ok
    await t.advance(300);
    expect([again.subId, again.effective, t.got()]).toEqual([undefined, {}, []]);
    conn.releaseHeld();
    await t.advance(300);
    expect([again.status, t.got()]).toEqual(["live", ["snap:1"]]);
    expect([again.subId === oldId, again.subId === bookSub(conn)]).toEqual([false, true]);
  });

  it("a stream made again and again keeps the replies of each sub apart", async () => {
    const t = engineHarness({ hold: ["sub_ok", "unsub_ok"] });
    await t.start();
    const conn = t.gateway.latest;
    const second = t.engine.consume(spec(BOOK));
    await t.advance(300); // sub 1 out
    second.release();
    await t.advance(300); // unsub 2 out
    const third = t.engine.consume(spec(BOOK));
    await t.advance(300);
    conn.releaseHeld(); // sub_ok 1 (old), unsub_ok 2: sub 3 goes out for `third`
    await t.advance(300);
    third.release();
    await t.advance(300); // unsub 4 out
    const fourth = t.engine.consume(spec(BOOK));
    await t.advance(300);
    conn.releaseHeld(); // sub_ok 3 belongs to `third`, which is gone: it must not reach `fourth`
    await t.advance(300);
    expect([fourth.subId, t.got()]).toEqual([undefined, []]);
    conn.releaseHeld(); // sub 5
    await t.advance(300);
    expect([fourth.status, fourth.subId]).toEqual(["live", bookSub(conn)]);
    expect(conn.of("sub")).toHaveLength(3);
  });

  it("a resync pins the subscription it is for: a replay stream's loss is not its live twin's", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    t.engine.consume(spec(BOOK), RS);
    await t.start();
    t.gateway.latest.skip(BOOK, RS);
    t.gateway.latest.delta(BOOK, {}, RS);
    await t.advance(100);
    const replay = t.gateway.latest.subs().find((s) => s.rs === RS);
    expect(t.gateway.latest.of("resync")).toEqual([
      expect.objectContaining({
        ch: BOOK,
        rs: RS,
        p: expect.objectContaining({ sub_id: replay?.id }),
      }),
    ]);
  });

  it("a stream that took the subscription over has the reply to the sub that made it", async () => {
    const t = engineHarness({ hold: ["sub_ok"] });
    await t.start();
    const first = t.engine.consume(spec(BOOK));
    await t.advance(300);
    first.release();
    const again = t.engine.consume(spec(BOOK)); // the same task: the unsub never goes out
    await t.advance(300);
    const conn = t.gateway.latest;
    expect([conn.of("sub").length, conn.of("unsub").length]).toEqual([1, 0]);
    conn.releaseHeld();
    await t.advance(300);
    expect([again.status, again.subId]).toEqual(["live", bookSub(conn)]);
  });

  it.each([undefined, RS])(
    "a stream that took the subscription over reads what the sub_ok said of it (replay stream: %s)",
    async (rs) => {
      const t = engineHarness();
      const asked = spec(BOOK, { opts: { throttle_ms: 200 } });
      const first = t.engine.consume(asked, rs);
      await t.start();
      first.release();
      const again = t.engine.consume(asked, rs); // the same task: nothing is sent
      expect([again.subId, again.effective]).toEqual([
        bookSub(t.gateway.latest),
        { throttle_ms: 200 },
      ]);
      expect([t.gateway.latest.of("sub").length, t.gateway.latest.of("unsub").length]).toEqual([
        1, 0,
      ]);
    },
  );
});

describe("a subscription the gateway refuses (5.2)", () => {
  it("ends the stream of a refused topic, and does not ask again", async () => {
    const t = engineHarness();
    t.gateway.refuseTopic(BOOK);
    const handle = t.engine.consume(spec(BOOK));
    await t.start();
    expect([handle.status, t.got()]).toEqual(["revoked", ["reset:revoked"]]);
    t.engine.consume(spec("trades.BTCUSDT")); // another pass of the reconciliation
    await t.advance(10_000);
    expect(t.gateway.latest.of("sub")).toHaveLength(2); // the refused one, and the new consumer's
    expect(t.gateway.latest.of("unsub")).toEqual([]); // the server holds nothing of it
  });

  it("an err that answers a whole sub refuses each topic of it", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined); // invalid_options is a client bug (10.3)
    const t = engineHarness();
    await t.start();
    t.gateway.failSubs(1);
    const book = t.engine.consume(spec(BOOK));
    const trades = t.engine.consume(spec("trades.BTCUSDT"));
    await t.advance(300);
    expect([book.status, trades.status]).toEqual(["revoked", "revoked"]);
    expect(t.gateway.latest.of("sub")).toHaveLength(1);
    t.engine.consume(spec("ticker.BTCUSDT")); // another pass of the reconciliation
    await t.advance(300);
    expect(t.gateway.latest.of("unsub")).toEqual([]);
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
  it("releasing a handle twice, and frames that answer nothing, do no harm", async () => {
    const t = engineHarness();
    const a = t.engine.consume(spec(BOOK));
    const b = t.engine.consume(spec(BOOK));
    await t.start();
    a.release();
    a.release();
    await t.advance(300);
    expect(t.gateway.latest.of("unsub")).toEqual([]); // b still holds the stream
    const conn = t.gateway.latest;
    conn.send({ t: "unsub_ok", p: { results: [] } });
    conn.send({ t: "ctl_ok", ch: BOOK, p: { effective: {} } });
    conn.send({ t: "err", p: { code: "degraded_data", message: "upstream" } });
    conn.send({ t: "sub_ok", p: { results: [{ ch: BOOK, ok: true, sub_id: "s_x" }] } }); // no options
    expect([b.status, b.effective]).toEqual(["live", { throttle_ms: 50 }]); // the options it had
  });

  it("a malformed frame while the next connection is still authenticating asks for nothing", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(BOOK));
    await t.start();
    t.gateway.latest.close(1011);
    await t.advance(500); // the new socket is open and welcome is back; auth_ok is not
    t.gateway.latest.raw(JSON.stringify({ t: "d", ch: BOOK, s: "x", ts: 1, p: {} }));
    await t.advance(400);
    expect(t.gateway.latest.of("resync")).toEqual([]);
    expect([handle.status, t.engine.counters.malformedFrames]).toEqual(["live", 1]);
    expect([t.engine.counters.resyncsSent, t.engine.counters.pendingRequests]).toEqual([0, 0]); // nothing was sent, so nothing is owed
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

  it("an unsub the gateway refuses does not hold the topic back for an unsub_ok that will not come", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined); // invalid_options is a client bug (10.3)
    const t = engineHarness();
    const first = t.engine.consume(spec(BOOK));
    await t.start();
    t.gateway.failUnsubs(1);
    first.release();
    await t.advance(100);
    t.engine.consume(spec(BOOK));
    await t.advance(300);
    expect(t.gateway.latest.of("sub")).toHaveLength(2); // not stuck behind the unsub
    expect(t.gateway.problems.splice(0)).toEqual([`${BOOK} subscribed twice`]); // the server still held the first
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

  it("an unsub_ok that never came does not hold the stream back on the next connection", async () => {
    const t = engineHarness({ hold: ["unsub_ok"] });
    const first = t.engine.consume(spec(BOOK));
    await t.start();
    first.release();
    await t.advance(300); // the unsub is out; its reply is held
    const again = t.engine.consume(spec(BOOK)); // waits behind it
    await t.advance(300);
    expect(t.gateway.latest.of("sub")).toHaveLength(1);
    t.gateway.latest.close(1011); // the connection is lost before the unsub_ok
    await t.advance(1_000);
    expect([t.gateway.latest.of("sub"), again.status]).toEqual([[expect.anything()], "live"]);
  });

  it("keeps no request pending once it is answered, nor across a lost connection", async () => {
    const t = engineHarness({ hold: ["sub_ok"] });
    t.engine.consume(spec(BOOK));
    await t.start();
    expect(t.engine.counters.pendingRequests).toBe(1); // the sub waits for its reply
    t.gateway.latest.releaseHeld();
    expect(t.engine.counters.pendingRequests).toBe(0); // answered: forgotten
    t.engine.consume(spec("trades.BTCUSDT"));
    await t.advance(300);
    expect(t.engine.counters.pendingRequests).toBe(1);
    t.gateway.latest.close(1011);
    expect(t.engine.counters.pendingRequests).toBe(0); // the lost connection takes what it was owed
  });

  it("an answered resync leaves no pending request", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    await t.start();
    for (let gap = 0; gap < 3; gap += 1) {
      t.gateway.latest.skip(BOOK);
      t.gateway.latest.delta(BOOK);
      await t.advance(100); // the resync goes out, and the snapshot it asked for comes back
    }
    expect([t.gateway.latest.of("resync").length, t.engine.counters.pendingRequests]).toEqual([
      3, 0,
    ]);
  });

  it("the snapshot of another stream of the ch does not answer a resync", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    t.engine.consume(spec(BOOK), RS);
    await t.start();
    t.gateway.latest.skip(BOOK, RS);
    t.gateway.latest.delta(BOOK, {}, RS);
    await t.advance(100); // the replay stream's resync goes out, and the gateway answers the live stream (#572)
    expect(t.engine.counters.pendingRequests).toBe(1);
  });

  it("keeps the requests whose reply is still due bounded", async () => {
    const t = engineHarness({ hold: ["sub_ok"] });
    await t.start();
    for (let i = 0; i < LEDGER_MAX + 20; i += 1) {
      t.engine.consume(spec(`trades.S${i}`, { paneId: `p${i}` }));
      await t.advance(1); // each one is a sub of its own
    }
    expect(t.engine.counters.pendingRequests).toBe(LEDGER_MAX);
  });

  it("a stream released just before the connection drops is not subscribed again", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    const gone = t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    gone.release();
    t.gateway.latest.close(1011); // before the engine reconciles
    expect(t.engine.counters.streams).toBe(1); // what nobody wants and the lost connection held is not kept
    await t.advance(800);
    expect(topicsOf(t.gateway.latest.of("sub")[0])).toEqual([BOOK]);
  });
});
