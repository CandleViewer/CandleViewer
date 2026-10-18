// E17-T04 S4 (23 5, 7, 8.4, 9, 11; C2, C5): the engine on the wire, against the fake gateway: what it
// subscribes, what it makes of gaps, revocations, closes and the replies of live and replay streams.
import { afterEach, describe, expect, it, vi } from "vitest";
import { b64, bookSnapshot, FLAG_PARTIAL } from "./support/cvwb";
import { assertEngineOrder } from "./support/engineEvents";
import { BASELINE_DEADLINE_MS, LEDGER_MAX } from "../../../src/lib/ws/core/engine";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import { BOOK, engineHarness, RS, spec } from "./support/engineHarness";
import type { FakeGateway, Json } from "./support/fakeGateway";

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

  it("never subscribes to system; its stream drives the reducer, the status first", async () => {
    const t = engineHarness();
    await t.start();
    expect(t.gateway.latest.of("sub")).toEqual([]);
    expect(t.events.slice(2)).toEqual([
      { type: "auth_ok", killSwitch: { engaged: false, scope: "global" } },
      { type: "system_stream", status: "live" },
      { type: "system", update: expect.objectContaining({ kind: "health" }) },
    ]);
    t.gateway.latest.delta("system", {
      kind: "kill_switch",
      kill_switch: { engaged: true, scope: "global" },
    });
    expect(t.events.at(-1)).toMatchObject({ type: "system", update: { kind: "kill_switch" } });
    t.gateway.latest.skip("system");
    t.gateway.latest.delta("system", { kind: "notice" }); // a gap in system: not trusted until its snap
    await t.advance(100);
    const last = t.events.slice(-3).map((e) => (e.type === "system_stream" ? e.status : e.type));
    expect(last).toEqual(["resyncing", "live", "system"]);
    assertEngineOrder(t.events);
    const seen = t.events.length;
    t.gateway.latest.delta("system", {} as never); // an object with no kind is no update
    t.gateway.latest.delta("system", [] as never);
    expect(t.events).toHaveLength(seen);
    t.gateway.latest.close(1011); // a reconnect is the reducer's business: no stream status of its own
    expect(t.events.at(-1)).toMatchObject({ type: "reconnecting" });
    expect(t.events.at(-2)).not.toMatchObject({ type: "system_stream" });
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

describe("a subscription the server ends (9.5)", () => {
  it("is not subscribed again, and a new consumer replaces it", async () => {
    const t = engineHarness();
    const first = t.engine.consume(spec(BOOK));
    await t.start();
    t.got();
    t.gateway.latest.revoke(BOOK, "permission_revoked");
    expect([first.status, t.got()]).toEqual(["revoked", ["reset:revoked"]]);
    await t.advance(5_000);
    expect(t.gateway.latest.of("sub")).toHaveLength(1);
    t.engine.consume(spec("trades.BTCUSDT")); // another pass of the reconciliation
    await t.advance(300);
    expect(t.gateway.latest.of("unsub")).toEqual([]); // the server ended it: there is nothing to unsubscribe
    const second = t.engine.consume(spec(BOOK));
    await t.advance(300);
    expect(t.gateway.latest.of("sub")).toHaveLength(3);
    expect([second.status, first.status]).toEqual(["live", "revoked"]);
    first.release(); // the old handle is still safe to release
  });

  it("continues through a narrowing that keeps accounts, and asks for a baseline", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(BOOK));
    await t.start();
    t.got();
    t.gateway.latest.revoke(BOOK, "account_scope_changed", { resubscribe_allowed: true });
    await t.advance(100);
    expect(t.got()).toEqual(["reset:narrowed", "snap:2"]);
    expect(handle.status).toBe("live");
    expect(t.gateway.latest.of("sub")).toHaveLength(1);
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

describe("a frame the gateway refused (8.5)", () => {
  it("is sent again, with its id", async () => {
    const t = engineHarness();
    await t.start();
    t.gateway.deny(1);
    const handle = t.engine.consume(spec(BOOK));
    await t.advance(300);
    const subs = t.gateway.latest.of("sub");
    expect(subs).toHaveLength(2); // the refused one, and the same frame again
    expect(subs[0]?.["id"]).toBe(subs[1]?.["id"]);
    // its reply is the stream's own: the sub id and the options came with it
    const held = t.gateway.latest.subs().find((s) => s.ch === BOOK);
    expect([handle.status, handle.subId, t.engine.counters.deniedFrames]).toEqual([
      "live",
      held?.id,
      1,
    ]);
  });

  it("an unsub that was denied goes again, and its reply still reaches the stream", async () => {
    const t = engineHarness();
    t.gateway.withholdSnaps(true);
    t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    expect(t.got("trades.BTCUSDT")).toEqual([]); // subscribed, and no baseline yet
    t.gateway.deny(1);
    t.engine.setPane("p1", { visibility: "collapsed", tabHidden: false }); // let go: the unsub is denied once
    await t.advance(300);
    const conn = t.gateway.latest;
    expect(conn.of("unsub")).toHaveLength(2);
    expect(t.got("trades.BTCUSDT")).toEqual(["reset:unsubscribed"]); // the unsub_ok of the second try
    expect(conn.subs().map((s) => s.ch)).toEqual(["system"]);
  });

  it("a denied sub goes again only for the streams it is still about, not for one let go meanwhile", async () => {
    const t = engineHarness({ hold: ["sub_ok"] });
    await t.start();
    const book = t.engine.consume(spec(BOOK));
    const trades = t.engine.consume(spec("trades.BTCUSDT"));
    t.gateway.deny(1);
    await t.advance(300); // one sub of both goes out and is dropped by the gateway; its err is in flight
    trades.release();
    await t.advance(300); // the unsub of trades goes out behind it
    const conn = t.gateway.latest;
    conn.releaseHeld(); // the err: the sub goes again, for the book alone
    await t.advance(300);
    conn.releaseHeld();
    await t.advance(300);
    expect(conn.of("sub").map((frame) => topicsOf(frame).sort())).toEqual([
      [BOOK, "trades.BTCUSDT"],
      [BOOK],
    ]);
    expect(conn.of("sub")[1]?.["id"]).toBe(conn.of("sub")[0]?.["id"]);
    expect([conn.subs().map((s) => s.ch), book.status]).toEqual([["system", BOOK], "live"]);
  });

  it("a denied sub of streams that are all gone is not sent again", async () => {
    const t = engineHarness({ hold: ["sub_ok"] });
    await t.start();
    const book = t.engine.consume(spec(BOOK));
    t.gateway.deny(1);
    await t.advance(300); // the sub is dropped by the gateway; its err is in flight
    book.release();
    await t.advance(300);
    const conn = t.gateway.latest;
    conn.releaseHeld();
    await t.advance(300);
    expect([
      conn.of("sub").length,
      conn.of("unsub").length,
      t.engine.counters.deniedFrames,
    ]).toEqual([1, 1, 1]);
  });

  it("a second refusal closes the connection, which reconnects after the gateway's retry_after and subscribes afresh", async () => {
    const t = engineHarness();
    await t.start();
    t.gateway.deny(2);
    const handle = t.engine.consume(spec(BOOK));
    await t.advance(300);
    expect(t.gateway.conns[0]?.of("sub")).toHaveLength(2);
    expect(t.events.at(-1)).toMatchObject({ type: "reconnecting", attempt: 1 });
    await t.advance(1_000);
    expect(t.gateway.conns).toHaveLength(2); // retry_after 1 000 ms, over the table's 500
    await t.advance(300);
    expect([handle.status, topicsOf(t.gateway.latest.of("sub")[0])]).toEqual(["live", [BOOK]]);
  });

  it("a second denial of the same request refuses it and sends nothing more", async () => {
    const t = engineHarness({ keepsDenying: true }); // refuses the same id again and again, and never closes
    await t.start();
    t.gateway.deny(6);
    const handle = t.engine.consume(spec(BOOK));
    await t.advance(10_000);
    const subs = t.gateway.latest.of("sub");
    expect(subs).toHaveLength(2); // the frame, and the one more try
    expect(subs[0]?.["id"]).toBe(subs[1]?.["id"]);
    const { deniedFrames, pendingRequests } = t.engine.counters;
    expect([handle.status, deniedFrames, pendingRequests]).toEqual(["revoked", 2, 0]);
  });

  it("a second denial of an unsub lets go of what waited behind it, and sends nothing more", async () => {
    const t = engineHarness({ keepsDenying: true });
    const first = t.engine.consume(spec(BOOK));
    await t.start();
    t.gateway.deny(2);
    first.release();
    await t.advance(300);
    expect(t.gateway.latest.of("unsub")).toHaveLength(2); // the frame, and the one more try
    t.engine.consume(spec(BOOK)); // it would wait for an unsub_ok that is not coming
    await t.advance(300);
    expect(t.gateway.latest.of("sub")).toHaveLength(2);
    expect(t.gateway.problems.splice(0)).toEqual([`${BOOK} subscribed twice`]); // the server never heard the unsub
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

  it("twin streams that both need a baseline inside a spent resync window are both asked for, oldest first", async () => {
    const t = engineHarness();
    let live = t.engine.consume(spec(BOOK));
    let replay = t.engine.consume(spec(BOOK), RS);
    t.engine.consume(spec(BOOK), "bb000000-0000-4000-8000-000000000002"); // keeps the ch (and its window) alive
    await t.start();
    const conn = t.gateway.latest;
    for (let i = 0; i < 5; i += 1) {
      live.release();
      live = t.engine.consume(spec(BOOK)); // the same task: it takes the held subscription over and asks for a baseline
      await t.advance(100);
    }
    expect(conn.of("resync")).toHaveLength(5); // the budget of the ch is spent
    live.release();
    replay.release();
    live = t.engine.consume(spec(BOOK));
    replay = t.engine.consume(spec(BOOK), RS); // both attach at once: both ask, and both wait
    await t.advance(1_000);
    expect(conn.of("resync")).toHaveLength(5);
    await t.advance(61_000);
    expect(
      conn
        .of("resync")
        .slice(5)
        .map((f) => f["rs"]),
    ).toEqual([undefined, RS]);
  });

  it("replay_session_ended ends the replay stream and leaves the live one", async () => {
    const t = engineHarness();
    const live = t.engine.consume(spec(BOOK));
    const replay = t.engine.consume(spec(BOOK), RS);
    await t.start();
    t.gateway.latest.revoke(BOOK, "replay_session_ended");
    expect([live.status, replay.status]).toEqual(["live", "revoked"]);
    t.gateway.latest.delta(BOOK);
    expect(t.got()).toEqual(["snap:1", "d:2"]);
  });
});

describe("an unsub and a sub of one stream (5.3)", () => {
  it("a consumer that returns before the unsub went out keeps the subscription and asks for a baseline", async () => {
    const t = engineHarness();
    const first = t.engine.consume(spec(BOOK));
    await t.start();
    t.got();
    first.release();
    const again = t.engine.consume(spec(BOOK)); // the same task: a pane that remounts
    await t.advance(300);
    const conn = t.gateway.latest;
    expect([conn.of("unsub"), conn.of("sub")]).toEqual([[], [expect.anything()]]);
    expect(conn.of("resync")).toEqual([
      expect.objectContaining({
        ch: BOOK,
        p: { last_seq: null, reason: "client_restart", sub_id: bookSub(conn) },
      }),
    ]);
    expect([t.got(), again.status]).toEqual([["snap:2"], "live"]);
    t.engine.consume(spec("trades.BTCUSDT")); // another pass of the reconciliation
    await t.advance(5_000);
    expect(conn.of("resync")).toHaveLength(1); // the baseline was asked for once
  });

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

  it("a retune confirmed late does not retune the stream that replaced its subscription", async () => {
    const t = engineHarness({ hold: ["sub_ok", "ctl_ok", "unsub_ok"] });
    const first = t.engine.consume(spec("trades.BTCUSDT", { paneId: "p1" }));
    await t.start();
    const conn = t.gateway.latest;
    conn.releaseHeld(); // the first sub_ok
    t.engine.setPane("p1", { visibility: "offscreen", tabHidden: false });
    await t.advance(100); // the ctl is sent, its reply in flight
    first.release();
    await t.advance(300);
    const again = t.engine.consume(spec("trades.BTCUSDT", { paneId: "p2" }));
    await t.advance(300);
    conn.releaseHeld(); // the old ctl_ok, then the unsub_ok
    await t.advance(300);
    expect(again.effective).toEqual({}); // not the old subscription's 1 000 ms
    conn.releaseHeld(); // the new sub_ok
    await t.advance(300);
    expect([again.status, again.effective]).toEqual(["live", { throttle_ms: 100 }]);
  });

  it("a stream let go by its pane and wanted again is the same stream, and still ignores the replies of its earlier sub", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const t = engineHarness({ hold: ["sub_ok", "unsub_ok"] });
    await t.start();
    t.gateway.failSubs(1); // the first sub is refused, and the err is in flight
    const handle = t.engine.consume(spec("trades.BTCUSDT"));
    await t.advance(300);
    t.engine.setPane("p1", { visibility: "collapsed", tabHidden: false });
    await t.advance(300); // let go: the unsub is sent
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false });
    await t.advance(300); // wanted again, behind the unsub_ok
    const conn = t.gateway.latest;
    conn.releaseHeld(); // the old sub's err, then the unsub_ok
    await t.advance(300);
    expect(handle.status).toBe("pending"); // the err belonged to the sub that was let go
    conn.releaseHeld();
    await t.advance(300);
    expect([handle.status, conn.of("sub")]).toEqual([
      "live",
      [expect.anything(), expect.anything()],
    ]);
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
  it("a consumer of system shares the implicit stream: nothing is subscribed, and the frames reach it", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec("system", { paneId: "banner", priority: "private" }));
    await t.start();
    expect(t.gateway.latest.of("sub")).toEqual([]);
    expect([handle.status, t.got("system")]).toEqual(["live", ["snap:1"]]);
    t.gateway.latest.delta("system", { kind: "notice", reason: "net.binding_safe" });
    expect(t.got("system")).toEqual(["d:2"]);
    handle.release(); // system is permanent: nothing to unsubscribe
    await t.advance(300);
    expect(t.gateway.latest.of("unsub")).toEqual([]);
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

  it("a stream released before its snapshot has no baseline deadline left", async () => {
    const t = engineHarness();
    t.gateway.withholdSnaps(true);
    const handle = t.engine.consume(spec(BOOK));
    await t.start();
    handle.release();
    await t.advance(3 * BASELINE_DEADLINE_MS);
    expect(t.gateway.latest.of("resync").filter((f) => f["ch"] === BOOK)).toEqual([]);
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

describe("panes and what they show (8.5, C8)", () => {
  const PANES = [
    ["p1", BOOK, 50],
    ["p2", "trades.BTCUSDT", 100],
    ["p3", "bars.BTCUSDT.time.1", 250],
    ["p4", "heatmap.BTCUSDT", 500],
  ] as const;
  const workspace = async () => {
    const t = engineHarness();
    for (const [paneId, ch] of PANES) t.engine.consume(spec(ch, { paneId }));
    await t.start();
    return t;
  };
  const setTab = (t: Awaited<ReturnType<typeof workspace>>, tabHidden: boolean) =>
    PANES.forEach(([paneId]) => t.engine.setPane(paneId, { visibility: "visible", tabHidden }));
  const throttles = (gateway: FakeGateway) =>
    gateway.latest.of("ctl").map((f) => [f["ch"], (f["p"] as Json)["throttle_ms"]]);
  const running = (gateway: FakeGateway) =>
    gateway.latest.subs().map(({ ch, effective }) => [ch, effective["throttle_ms"]]);

  it("Hidden tab throttles but does not unsubscribe", async () => {
    const t = await workspace();
    const conn = t.gateway.latest;
    const subs = conn.of("sub").length;
    setTab(t, true);
    await t.advance(500);
    expect(throttles(t.gateway)).toEqual(PANES.map(([, ch]) => [ch, 1_000])); // every visual topic, at least 1 000 ms
    expect(conn.of("unsub")).toEqual([]);
    setTab(t, false);
    await t.advance(500);
    expect(throttles(t.gateway).slice(4)).toEqual(PANES.map(([, ch, natural]) => [ch, natural]));
    expect(running(t.gateway)).toEqual([
      ["system", 250],
      ...PANES.map(([, ch, natural]) => [ch, natural]),
    ]);
    expect([conn.of("sub").length, conn.of("resync")]).toEqual([subs, []]); // no re-snapshot
  });

  it("an off-screen pane goes to 1 000 ms, a collapsed one is let go, and both come back", async () => {
    const t = engineHarness();
    t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    const conn = t.gateway.latest;
    t.engine.setPane("p1", { visibility: "offscreen", tabHidden: false });
    await t.advance(100);
    expect(throttles(t.gateway)).toEqual([["trades.BTCUSDT", 1_000]]);
    t.engine.setPane("p1", { visibility: "collapsed", tabHidden: false });
    await t.advance(300);
    expect(conn.of("unsub").map(topicsOf)).toEqual([["trades.BTCUSDT"]]);
    t.got("trades.BTCUSDT");
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false });
    await t.advance(500);
    expect(conn.of("sub")).toHaveLength(2); // subscribed again, and snapshotted
    expect(t.got("trades.BTCUSDT")).toEqual(["snap:1"]);
    expect(conn.of("ctl")).toHaveLength(1); // nothing to retune: it is back at its own cadence
  });

  it("a topic runs at the fastest of its consumers, and a pane that is gone counts no more", async () => {
    const t = engineHarness();
    t.engine.consume(spec("trades.BTCUSDT", { paneId: "p1" }));
    t.engine.consume(spec("trades.BTCUSDT", { paneId: "p2" }));
    await t.start();
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(100);
    expect(t.gateway.latest.of("ctl")).toEqual([]); // p2 still watches it
    t.engine.setPane("p2", { visibility: "visible", tabHidden: true });
    await t.advance(100);
    expect(t.gateway.latest.of("ctl")).toHaveLength(1);
    t.engine.removePane("p2");
    t.engine.removePane("p1"); // both back to the defaults: visible
    await t.advance(100);
    expect(running(t.gateway).at(-1)).toEqual(["trades.BTCUSDT", 100]);
  });

  it("never retunes a private topic or system", async () => {
    const t = engineHarness();
    t.engine.consume(spec("orders", { paneId: "p1", priority: "private" }));
    await t.start();
    t.engine.setPane("p1", { visibility: "collapsed", tabHidden: true });
    await t.advance(500);
    expect([t.gateway.latest.of("ctl"), t.gateway.latest.of("unsub")]).toEqual([[], []]);
  });

  it("floors a restored throttle at welcome.limits.min_throttle_ms", async () => {
    const t = engineHarness({ limits: { min_throttle_ms: 200 } });
    t.engine.consume(spec(BOOK, { opts: { throttle_ms: 20 } })); // asks for faster than the server allows
    await t.start();
    expect(t.gateway.latest.subs().at(-1)?.effective["throttle_ms"]).toBe(200);
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(100);
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false });
    await t.advance(100);
    const asked = t.gateway.latest.of("ctl").map((f) => (f["p"] as Json)["throttle_ms"]);
    expect(asked).toEqual([1_000, 200]); // back to the server's minimum, not to the 20 that was asked
  });

  it("a hide and a show before the first ctl_ok still sends the restore", async () => {
    const t = engineHarness({ hold: ["ctl_ok"] });
    t.engine.consume(spec(BOOK));
    await t.start();
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(100); // the ctl is out, its ctl_ok is not back
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false });
    await t.advance(100);
    expect(t.gateway.latest.of("ctl").map((f) => (f["p"] as Json)["throttle_ms"])).toEqual([
      1_000, 50,
    ]);
  });

  it("keeps what the registry kept of the server's options, never the frame's: an effective over their limits is not believed", async () => {
    const t = engineHarness({ bloatEffective: true }); // every effective carries 2 000 values more than options can hold
    const handle = t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    expect(handle.effective).toEqual({}); // the registry ignored it, and flow control did too
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(300);
    expect(throttles(t.gateway)).toEqual([]); // it knows no pace to slow down from
  });

  it("a ctl the gateway refused is asked for again from what is wanted now", async () => {
    const t = await workspace();
    t.gateway.deny(1);
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(500);
    expect(throttles(t.gateway)).toEqual([
      [BOOK, 1_000],
      [BOOK, 1_000],
    ]);
    expect(t.engine.counters.deniedFrames).toBe(1);
    expect(running(t.gateway)[1]).toEqual([BOOK, 1_000]);
  });

  it("a restore the gateway refused is asked for again, from what the server was told last", async () => {
    const t = await workspace();
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(500); // slowed to 1 000 ms, and confirmed
    t.gateway.deny(1);
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false });
    await t.advance(500);
    expect(throttles(t.gateway).filter(([ch]) => ch === BOOK)).toEqual([
      [BOOK, 1_000],
      [BOOK, 50], // refused
      [BOOK, 50],
    ]);
    expect(running(t.gateway)[1]).toEqual([BOOK, 50]);
  });

  it("a refused ctl is asked for again from what is wanted now, never replayed as it was", async () => {
    const t = engineHarness({ hold: ["ctl_ok"] });
    t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    t.gateway.deny(1);
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true }); // slowed: refused, and the err is in flight
    await t.advance(100);
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false }); // and back before it is heard
    await t.advance(100);
    t.gateway.latest.releaseHeld();
    await t.advance(500);
    expect(throttles(t.gateway)).toEqual([
      ["trades.BTCUSDT", 1_000],
      ["trades.BTCUSDT", 100],
    ]);
    expect(running(t.gateway)[1]).toEqual(["trades.BTCUSDT", 100]);
  });

  it("a lost connection forgets what the server was told: a hidden tab is slowed again on the next", async () => {
    const t = engineHarness();
    t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(100);
    t.gateway.latest.close(1011);
    await t.advance(1_000); // reconnected, and subscribed again at its own pace
    expect(throttles(t.gateway)).toEqual([["trades.BTCUSDT", 1_000]]);
  });

  it("a topic's pace is the fastest of its consumers, and changes when one arrives or leaves", async () => {
    const t = engineHarness();
    t.engine.consume(spec("trades.BTCUSDT", { paneId: "p1" }));
    await t.start();
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(100);
    expect(running(t.gateway)[1]).toEqual(["trades.BTCUSDT", 1_000]);
    const shown = t.engine.consume(spec("trades.BTCUSDT", { paneId: "p2" })); // a pane that is watched joins
    await t.advance(100);
    expect(running(t.gateway)[1]).toEqual(["trades.BTCUSDT", 100]);
    shown.release(); // and leaves: only the hidden one is left
    await t.advance(100);
    expect(running(t.gateway)[1]).toEqual(["trades.BTCUSDT", 1_000]);
  });

  it("forgets what the server was told of a topic once it is unsubscribed: the next consumer starts clean", async () => {
    const t = engineHarness();
    const first = t.engine.consume(spec("trades.BTCUSDT", { paneId: "p1" }));
    await t.start();
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(100); // slowed: one ctl
    first.release();
    await t.advance(300); // unsubscribed
    t.engine.consume(spec("trades.BTCUSDT", { paneId: "p2" })); // a pane that is watched
    await t.advance(300);
    expect(throttles(t.gateway)).toEqual([["trades.BTCUSDT", 1_000]]); // nothing to retune: it runs at its own pace
  });

  it("a retune of a ch with a live and a replay stream lands on the live one, the one the gateway takes", async () => {
    const t = engineHarness();
    const replay = t.engine.consume(spec("trades.BTCUSDT"), RS); // first in the table
    const live = t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    t.engine.setPane("p1", { visibility: "offscreen", tabHidden: false });
    await t.advance(300);
    expect([live.effective, replay.effective]).toEqual([
      { throttle_ms: 1_000 },
      { throttle_ms: 100 },
    ]);
  });

  it("a stream a remounting consumer takes over is still slowed when its tab is hidden", async () => {
    const t = engineHarness();
    const first = t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    first.release();
    t.engine.consume(spec("trades.BTCUSDT")); // the same task: taken over, nothing is sent
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(300);
    expect(throttles(t.gateway)).toEqual([["trades.BTCUSDT", 1_000]]);
  });

  it("a hide, a remount and a show leave the server at the pace of a visible pane", async () => {
    const t = engineHarness();
    const first = t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(300); // slowed to 1 000 ms
    first.release();
    t.engine.consume(spec("trades.BTCUSDT"));
    await t.advance(300);
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false });
    await t.advance(300);
    expect(throttles(t.gateway)).toEqual([
      ["trades.BTCUSDT", 1_000],
      ["trades.BTCUSDT", 100],
    ]);
  });

  it("a topic the server ended is not retuned", async () => {
    const t = engineHarness();
    t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    t.gateway.latest.revoke("trades.BTCUSDT", "permission_revoked");
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(300);
    expect(t.gateway.latest.of("ctl")).toEqual([]); // there is nothing to retune: the gateway would say not_subscribed
  });

  it("a ctl the pacer merges into a newer one leaves no request waiting for its reply", async () => {
    const t = engineHarness({ hold: ["ctl_ok"] });
    t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    for (let cycle = 0; cycle < 3; cycle += 1) {
      t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
      t.engine.setPane("p1", { visibility: "visible", tabHidden: false });
    }
    await t.advance(300); // six ctls in one task leave as one frame
    expect(t.gateway.latest.of("ctl")).toHaveLength(1);
    expect(t.engine.counters.pendingRequests).toBe(1);
  });

  it("retunes the replay stream that is left when the live one was refused", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined); // invalid_options is a client bug (10.3)
    const t = engineHarness();
    t.gateway.failSubs(1); // the live sub is refused whole; the replay's goes through
    const live = t.engine.consume(spec("trades.BTCUSDT"));
    const replay = t.engine.consume(spec("trades.BTCUSDT"), RS);
    await t.start();
    expect(live.status).toBe("revoked");
    t.engine.setPane("p1", { visibility: "offscreen", tabHidden: false });
    await t.advance(300);
    expect(replay.effective).toEqual({ throttle_ms: 1_000 });
  });

  it("lets go of a live and a replay stream in a frame each, and each reply reaches its own stream", async () => {
    const t = engineHarness();
    t.gateway.withholdSnaps(true); // no baseline: the unsub_ok is what ends them
    t.engine.consume(spec("trades.BTCUSDT", { paneId: "p1" }));
    t.engine.consume(spec(BOOK, { paneId: "p2" }), RS);
    await t.start();
    t.engine.setPane("p1", { visibility: "collapsed", tabHidden: false });
    t.engine.setPane("p2", { visibility: "collapsed", tabHidden: false });
    await t.advance(300);
    expect(t.gateway.latest.of("unsub").map(topicsOf)).toEqual([["trades.BTCUSDT"], [BOOK]]);
    expect([t.got("trades.BTCUSDT"), t.got(BOOK, RS)]).toEqual([
      ["reset:unsubscribed"],
      ["reset:unsubscribed"],
    ]);
  });
});

describe("a heatmap's bucket follows its pane (6.1.1)", () => {
  const HEATMAP = "heatmap.BTCUSDT";
  const size = (cssWidth: number) =>
    ({ visibility: "visible", tabHidden: false, size: { cssWidth, dpr: 1 } }) as const;
  const topicsEntry = (frame: Json | undefined) => ((frame?.["p"] as Json)["topics"] as Json[])[0];
  /** The buckets the client asked for with a `ctl` (a throttle ctl asks for none). */
  const bucketCtls = (t: ReturnType<typeof engineHarness>) =>
    t.gateway.latest
      .of("ctl")
      .map((f) => (f["p"] as Json)["time_bucket_ms"])
      .filter((bucket) => bucket !== undefined);

  it("is derived from the pane's size and sent on the sub, so nothing is retuned", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(1190));
    t.engine.consume(spec(HEATMAP));
    await t.start();
    expect(t.gateway.latest.of("sub")[0]).toMatchObject({
      p: { topics: [{ ch: HEATMAP, opts: { time_bucket_ms: 1_000 } }] },
    });
    await t.advance(5_000);
    expect(t.gateway.latest.of("ctl")).toEqual([]);
  });

  it("a bucket the user chose is sent as it is, and never retuned", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(1190));
    t.engine.consume(spec(HEATMAP, { opts: { time_bucket_ms: 250 } }));
    await t.start();
    t.engine.setPane("p1", size(300));
    await t.advance(5_000);
    expect(t.gateway.latest.of("sub")[0]).toMatchObject({
      p: { topics: [{ ch: HEATMAP, opts: { time_bucket_ms: 250 } }] },
    });
    expect(t.gateway.latest.of("ctl")).toEqual([]);
  });

  it("Heatmap bucket is derived and debounced: a resize across a ladder boundary sends one ctl", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(1190));
    const handle = t.engine.consume(spec(HEATMAP));
    await t.start();
    t.got(HEATMAP);
    for (let i = 0; i < 20; i += 1) {
      if (i > 0) await t.advance(10);
      t.engine.setPane("p1", size(1190 - i * 31)); // down to 601 px
    }
    await t.advance(399);
    expect(bucketCtls(t)).toEqual([]);
    await t.advance(1);
    expect(bucketCtls(t)).toEqual([5_000]);
    await t.advance(10_000);
    expect(t.gateway.latest.of("ctl")).toHaveLength(1); // not one per event, and no throttle ctl after it
    expect(t.got(HEATMAP)).toEqual(["reset:resnapshot", "snap:2"]); // the server re-snapshots (6.1.1)
    expect([handle.effective["time_bucket_ms"], handle.status]).toEqual([5_000, "live"]);
    t.engine.setPane("p1", size(1190)); // back across the boundary: the server runs 5 000 ms now, so this is a change
    await t.advance(400);
    expect(bucketCtls(t)).toEqual([5_000, 1_000]);
  });

  it("is first derived when the pane is measured after the sub, and a pane without a size asks for nothing", async () => {
    const t = engineHarness();
    t.engine.consume(spec(HEATMAP));
    await t.start();
    expect(topicsEntry(t.gateway.latest.of("sub")[0])).toEqual({ ch: HEATMAP });
    t.engine.setPane("p1", {
      visibility: "visible",
      tabHidden: false,
      size: { cssWidth: 0, dpr: 1 },
    });
    await t.advance(1_000);
    expect(t.gateway.latest.of("ctl")).toEqual([]); // a hidden pane is 0 px wide: no bucket to derive
    t.engine.setPane("p1", size(1190)); // the server runs 500 ms; 1 190 px derives 1 000 ms
    await t.advance(400);
    expect(bucketCtls(t)).toEqual([1_000]);
  });

  it("is one bucket per ch: with several panes the widest decides, and the narrow one's resize sends nothing", async () => {
    const t = engineHarness();
    t.engine.setPane("wide", size(1190));
    t.engine.setPane("narrow", size(1190));
    t.engine.consume(spec(HEATMAP, { paneId: "wide" }));
    t.engine.consume(spec(HEATMAP, { paneId: "narrow" }));
    await t.start();
    t.engine.setPane("narrow", size(601));
    await t.advance(5_000);
    expect(t.gateway.latest.of("ctl")).toEqual([]);
    t.engine.setPane("wide", size(601)); // now both are narrow
    await t.advance(400);
    expect(bucketCtls(t)).toEqual([5_000]);
  });

  it("a collapsed pane's width does not count: the widest pane that is shown decides", async () => {
    const t = engineHarness();
    t.engine.setPane("wide", {
      visibility: "collapsed",
      tabHidden: false,
      size: { cssWidth: 1190, dpr: 1 },
    });
    t.engine.setPane("narrow", size(601));
    t.engine.consume(spec(HEATMAP, { paneId: "wide" }));
    t.engine.consume(spec(HEATMAP, { paneId: "narrow" }));
    await t.start();
    expect(topicsEntry(t.gateway.latest.of("sub")[0])).toEqual({
      ch: HEATMAP,
      opts: { time_bucket_ms: 5_000 },
    });
  });

  it("derives the bucket of the sub from the window the consumer asked for", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(5_400)); // 500 ms over the default 900 s; 250 ms over 300 s
    t.engine.consume(spec(HEATMAP, { opts: { window_seconds: 300 } }));
    await t.start();
    expect(topicsEntry(t.gateway.latest.of("sub")[0])).toEqual({
      ch: HEATMAP,
      opts: { window_seconds: 300, time_bucket_ms: 250 },
    });
  });

  it("re-derives the bucket from the window the server confirmed, not the one asked for", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(800));
    t.engine.consume(spec(HEATMAP, { opts: { window_seconds: 900 } })); // the server keeps 300 s at most
    await t.start();
    expect(topicsEntry(t.gateway.latest.of("sub")[0])).toEqual({
      ch: HEATMAP,
      opts: { window_seconds: 900, time_bucket_ms: 5_000 },
    });
    await t.advance(1_000);
    expect(bucketCtls(t)).toEqual([1_000]); // 300 s over 800 px
  });

  it("a resize while the sub is still unanswered is derived as soon as the server answers", async () => {
    const t = engineHarness({ hold: ["sub_ok"] });
    t.engine.setPane("p1", size(1190));
    t.engine.consume(spec(HEATMAP));
    await t.start(); // the sub carries 1 000 ms; its reply is in flight
    t.engine.setPane("p1", size(601)); // nothing is confirmed to compare it with yet
    await t.advance(1_000);
    expect(bucketCtls(t)).toEqual([]);
    t.gateway.latest.releaseHeld();
    await t.advance(500);
    expect(bucketCtls(t)).toEqual([5_000]);
  });

  it("derives a refused bucket ctl again", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(1190));
    t.engine.consume(spec(HEATMAP));
    await t.start();
    t.gateway.deny(1);
    t.engine.setPane("p1", size(601));
    await t.advance(1_000);
    expect(bucketCtls(t)).toEqual([5_000, 5_000]);
    expect(t.gateway.latest.subs().at(-1)?.effective["time_bucket_ms"]).toBe(5_000);
  });

  it("a heatmap a remounting consumer takes over still follows its pane's size", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(1190));
    const first = t.engine.consume(spec(HEATMAP));
    await t.start();
    first.release();
    t.engine.consume(spec(HEATMAP)); // the same task: taken over, nothing is sent
    t.engine.setPane("p1", size(601));
    await t.advance(1_000);
    expect(bucketCtls(t)).toEqual([5_000]);
  });

  it("removing the widest pane of a heatmap derives the bucket from the panes that are left", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(601));
    t.engine.setPane("p2", size(1190));
    t.engine.consume(spec(HEATMAP, { paneId: "p1" }));
    t.engine.consume(spec(HEATMAP, { paneId: "p2" }));
    await t.start(); // the widest decides: 1 000 ms
    t.engine.removePane("p2");
    await t.advance(1_000);
    expect(bucketCtls(t)).toEqual([5_000]);
  });

  it("releasing the widest consumer of a heatmap derives the bucket from the panes that are left", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(601));
    t.engine.setPane("p2", size(1190));
    t.engine.consume(spec(HEATMAP, { paneId: "p1" }));
    const wide = t.engine.consume(spec(HEATMAP, { paneId: "p2" }));
    await t.start();
    wide.release();
    await t.advance(1_000);
    expect(bucketCtls(t)).toEqual([5_000]);
  });

  it("a heatmap with a throttle of its own is slowed from that throttle, not from its bucket, and comes back to it", async () => {
    const t = engineHarness();
    t.engine.consume(spec(HEATMAP, { opts: { time_bucket_ms: 1_000, throttle_ms: 250 } }));
    await t.start();
    const throttles = () => t.gateway.latest.of("ctl").map((f) => (f["p"] as Json)["throttle_ms"]);
    expect(throttles()).toEqual([]); // visible it runs at the 250 it asked for: nothing to retune
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(300);
    expect(throttles()).toEqual([1_000]); // it ran at 250: slowing it to its bucket's 1 000 is a change
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false });
    await t.advance(300);
    expect(throttles()).toEqual([1_000, 250]); // shown again, it goes back to its own pace and not its bucket's
  });

  it("a throttle retune that the server echoes without the bucket sends no bucket ctl", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(10_800)); // a bucket of 250 ms (the formula of 6.1.1 asks for a pane this wide)
    t.engine.consume(spec(HEATMAP));
    await t.start();
    t.engine.setPane("p1", { ...size(10_800), tabHidden: true });
    await t.advance(1_000); // slowed to 1 000 ms: the ctl_ok names the throttle and no bucket
    expect(bucketCtls(t)).toEqual([]);
  });

  it("a resize after a throttle retune is derived against the bucket the server runs", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(10_800)); // a bucket of 250 ms (the formula of 6.1.1 asks for a pane this wide)
    t.engine.consume(spec(HEATMAP));
    await t.start();
    t.engine.setPane("p1", { ...size(10_800), tabHidden: true });
    await t.advance(1_000);
    t.engine.setPane("p1", { ...size(5_400), tabHidden: true }); // 500 ms: not what the server runs
    await t.advance(1_000);
    expect(bucketCtls(t)).toEqual([500]);
  });

  it("a pass that changes nothing does not postpone a resize that is about to settle", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", size(1190));
    t.engine.consume(spec(HEATMAP));
    await t.start();
    t.engine.setPane("p1", size(601)); // the 400 ms of the debounce start
    await t.advance(300);
    t.engine.setPane("p2", size(500)); // a pane no heatmap is on: nothing it says concerns the bucket
    await t.advance(150);
    expect(bucketCtls(t)).toEqual([5_000]);
  });

  it("a retune the server echoes in part leaves the bucket the stream runs at alone", async () => {
    const t = engineHarness();
    t.engine.consume(spec(HEATMAP, { opts: { time_bucket_ms: 250 } }));
    await t.start();
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(300); // slowed to 1 000 ms: the ctl_ok names the throttle and nothing of the bucket
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false });
    await t.advance(300);
    const throttles = t.gateway.latest.of("ctl").map((f) => (f["p"] as Json)["throttle_ms"]);
    expect(throttles).toEqual([1_000, 250]); // back at its bucket, not at the 500 ms of a heatmap that names none
  });
});

describe("a snapshot that does not come (7.1, WS-E06)", () => {
  it("is asked for once more, then the stream reads stale until the snapshot arrives", async () => {
    const t = engineHarness();
    t.gateway.withholdSnaps(true);
    const handle = t.engine.consume(spec(BOOK));
    await t.start();
    const conn = t.gateway.latest;
    await t.advance(BASELINE_DEADLINE_MS);
    const resyncs = () => conn.of("resync").filter((f) => f["ch"] === BOOK);
    expect(resyncs()).toEqual([
      expect.objectContaining({
        p: { last_seq: null, reason: "client_restart", sub_id: bookSub(conn) },
      }),
    ]);
    expect(handle.status).toBe("pending");
    await t.advance(BASELINE_DEADLINE_MS);
    expect(handle.status).toBe("stale");
    await t.advance(120_000);
    expect(resyncs()).toHaveLength(1); // one retry, not a loop
    t.gateway.withholdSnaps(false);
    conn.snap(BOOK, "client_resync");
    expect([handle.status, t.got()]).toEqual(["live", ["snap:1"]]);
  });

  it("a stream the server ends has no snapshot due, and neither has one that is unsubscribed", async () => {
    const t = engineHarness();
    t.gateway.withholdSnaps(true);
    t.engine.consume(spec(BOOK));
    t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    t.gateway.latest.revoke(BOOK, "permission_revoked");
    await t.advance(3 * BASELINE_DEADLINE_MS);
    expect(t.gateway.latest.of("resync").filter((f) => f["ch"] === BOOK)).toEqual([]);
    expect(t.gateway.latest.of("resync").filter((f) => f["ch"] === "trades.BTCUSDT")).toHaveLength(
      1,
    );
  });

  it("a resnapshot that never comes is asked for once more, like any snapshot", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", {
      visibility: "visible",
      tabHidden: false,
      size: { cssWidth: 1190, dpr: 1 },
    });
    const handle = t.engine.consume(spec("heatmap.BTCUSDT"));
    await t.start();
    t.gateway.withholdSnaps(true); // from now on the server promises snapshots and sends none
    t.engine.setPane("p1", {
      visibility: "visible",
      tabHidden: false,
      size: { cssWidth: 601, dpr: 1 },
    });
    await t.advance(500); // the ctl, and ctl_ok with resnapshot
    expect(handle.status).toBe("resyncing");
    const resyncs = () =>
      t.gateway.latest.of("resync").filter((f) => f["ch"] === "heatmap.BTCUSDT");
    await t.advance(BASELINE_DEADLINE_MS);
    expect(resyncs()).toHaveLength(1);
    await t.advance(BASELINE_DEADLINE_MS);
    expect(handle.status).toBe("stale");
  });

  it("costs nothing when the snapshot comes in time", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    await t.start();
    await t.advance(3 * BASELINE_DEADLINE_MS);
    expect(t.gateway.latest.of("resync")).toEqual([]);
  });

  it("a new wait for a snapshot replaces the one before it: it is due 10 s after the last ask", async () => {
    const t = engineHarness();
    t.gateway.withholdSnaps(true);
    const first = t.engine.consume(spec(BOOK));
    await t.start(); // sub_ok: a snapshot is due in 10 s
    await t.advance(5_000);
    first.release();
    t.engine.consume(spec(BOOK)); // takes the subscription over and asks for a baseline: due 10 s from now
    await t.advance(5_000); // the first wait would be over by now
    const asks = () => t.gateway.latest.of("resync").filter((f) => f["ch"] === BOOK).length;
    expect(asks()).toBe(1);
    await t.advance(5_500);
    expect(asks()).toBe(2); // the one retry, 10 s after the last ask
  });

  it("a system stream that misses its snapshot stops the kill switch being trusted (WS-E06)", async () => {
    const t = engineHarness();
    t.gateway.withholdSnaps(true);
    await t.start();
    const state = () => t.events.reduce(reduce, INITIAL_WS_STATE);
    expect(state().orderEntry).toEqual({ enabled: true, reason: null }); // auth_ok said: not engaged
    await t.advance(2 * BASELINE_DEADLINE_MS);
    expect(t.events.at(-1)).toEqual({ type: "system_stream", status: "stale" });
    expect(state().orderEntry).toEqual({ enabled: false, reason: "kill_switch_unknown" });
    t.gateway.withholdSnaps(false);
    t.gateway.latest.snap("system", "client_resync"); // the snapshot arrives late: trusted again
    expect(state().orderEntry).toEqual({ enabled: true, reason: null });
    assertEngineOrder(t.events);
  });
});

describe("stopping", () => {
  it("closes the socket, forgets every stream and leaves no timer behind", async () => {
    const t = engineHarness();
    t.engine.setPane("p1", {
      visibility: "visible",
      tabHidden: false,
      size: { cssWidth: 1190, dpr: 1 },
    });
    t.engine.consume(spec("heatmap.BTCUSDT"));
    t.engine.consume(spec(BOOK, { paneId: "p2" }));
    t.gateway.withholdSnaps(true); // a deadline is waiting
    await t.start();
    t.engine.setPane("p1", {
      visibility: "visible",
      tabHidden: false,
      size: { cssWidth: 601, dpr: 1 },
    });
    t.engine.stop();
    expect(t.gateway.latest.closedByClient).toEqual({ code: 1000, reason: "client_stop" });
    expect(vi.getTimerCount()).toBe(0);
    await t.advance(600_000);
    expect(t.gateway.conns).toHaveLength(1);
  });
});

describe("the rest of what a pane decides", () => {
  it("the focused pane's topics come back first, whatever each spec says, until the app stops saying", async () => {
    const t = engineHarness();
    t.engine.consume(spec("trades.BTCUSDT", { paneId: "p1", priority: "other" }));
    t.engine.consume(spec(BOOK, { paneId: "p2", priority: "other" }));
    t.engine.consume(spec("bars.BTCUSDT.time.1", { paneId: "p3", priority: "focused" }));
    t.engine.consume(spec("orders", { paneId: "account", priority: "private" }));
    t.engine.focusPane("p2");
    await t.start();
    expect(t.subscribed()).toEqual(["orders", BOOK, "trades.BTCUSDT", "bars.BTCUSDT.time.1"]);
    t.engine.focusPane(null); // each spec says its own again
    t.gateway.latest.close(1011);
    await t.advance(1_000);
    expect(t.subscribed()).toEqual(["orders", "bars.BTCUSDT.time.1", "trades.BTCUSDT", BOOK]);
  });

  it("retunes a replay stream that has no live twin, and the reply lands on it", async () => {
    const t = engineHarness();
    const replay = t.engine.consume(spec(BOOK), RS);
    await t.start();
    t.engine.setPane("p1", { visibility: "visible", tabHidden: true });
    await t.advance(100);
    expect(t.gateway.latest.of("ctl")).toEqual([
      expect.objectContaining({ ch: BOOK, p: { throttle_ms: 1_000 } }),
    ]);
    expect(replay.effective["throttle_ms"]).toBe(1_000);
  });
});
