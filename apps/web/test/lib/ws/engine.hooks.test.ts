// E17-T04 S5 (23 5.3, 5.4, 7.5; C20): what the shared worker needs of the engine, and what S4's reviews
// left for it: replay streams are named on `ctl` and `unsub`, a snapshot answers the resync of its own
// stream only, the sink hears of what a reply changes, and a stream the sink dropped frames of is asked
// for again.
import { afterEach, describe, expect, it, vi } from "vitest";
import { BASELINE_DEADLINE_MS } from "../../../src/lib/ws/core/engine";
import { BOOK, engineHarness, RS, spec } from "./support/engineHarness";
import type { Json } from "./support/fakeGateway";

afterEach(() => vi.useRealTimers());

const TRADES = "trades.BTCUSDT";
const hidden = { visibility: "offscreen", tabHidden: false } as const;
const collapsed = { visibility: "collapsed", tabHidden: false } as const;
/** `[ch, rs]` of each frame; a live stream's frame has no `rs` key at all. */
const named = (frames: readonly Json[]) =>
  frames.map((f) => [f["ch"] ?? (f["p"] as { topics: string[] }).topics[0], f["rs"]]);

describe("a replay stream is named on ctl and unsub (23 5.3, 5.4, C20)", () => {
  it("puts the replay session in the envelope of the frames for its stream, and none in the live one's", async () => {
    const t = engineHarness();
    t.engine.consume(spec(TRADES, { paneId: "live" }));
    t.engine.consume(spec(BOOK, { paneId: "replay" }), RS);
    await t.start();
    t.engine.setPane("live", hidden);
    t.engine.setPane("replay", hidden);
    await t.advance(300);
    const ctls = t.gateway.latest.of("ctl");
    expect(named(ctls)).toEqual([
      [TRADES, undefined],
      [BOOK, RS],
    ]);
    expect(Object.hasOwn(ctls[0] ?? {}, "rs")).toBe(false);
    t.engine.setPane("live", collapsed);
    t.engine.setPane("replay", collapsed);
    await t.advance(300);
    const unsubs = t.gateway.latest.of("unsub");
    expect(named(unsubs)).toEqual([
      [TRADES, undefined],
      [BOOK, RS],
    ]);
    expect(Object.hasOwn(unsubs[0] ?? {}, "rs")).toBe(false);
    expect(t.gateway.problems).toEqual([]); // every one of them validated against the schemas
  });

  it("a ctl the gateway keeps refusing for its rate is asked for once more, not for ever; a reply starts it again", async () => {
    const t = engineHarness({ keepsDenying: true });
    t.engine.consume(spec(TRADES));
    await t.start();
    t.gateway.deny(6);
    t.engine.setPane("p1", hidden);
    await t.advance(10_000);
    expect(t.gateway.latest.of("ctl")).toHaveLength(2); // the ctl, and the one more try
    t.gateway.deny(0);
    t.engine.setPane("p1", { visibility: "offscreen", tabHidden: false }); // any change is a new pass: what is wanted is asked for, and answered
    await t.advance(300);
    expect(t.gateway.latest.of("ctl")).toHaveLength(3);
    t.gateway.deny(1);
    t.engine.setPane("p1", { visibility: "visible", tabHidden: false }); // refused once, and asked again: the refusals before did not use it up
    await t.advance(300);
    expect(t.gateway.latest.of("ctl")).toHaveLength(5);
  });

  it("a ctl the gateway refused for its rate goes again with the same replay session", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK), RS);
    await t.start();
    t.gateway.deny(1);
    t.engine.setPane("p1", hidden);
    await t.advance(300);
    expect(named(t.gateway.latest.of("ctl"))).toEqual([
      [BOOK, RS],
      [BOOK, RS],
    ]);
  });
});

describe("a snapshot answers the resync of its own stream only (7.5)", () => {
  /** Two live streams that both lost a number: each has asked for a baseline, and none comes. */
  async function twoLost(hold: boolean) {
    const t = engineHarness(hold ? { hold: ["ctl_ok"] } : {});
    t.engine.consume(spec(BOOK));
    t.engine.consume(spec(TRADES));
    await t.start();
    t.gateway.withholdSnaps(true);
    const conn = t.gateway.latest;
    for (const ch of [BOOK, TRADES]) {
      conn.skip(ch);
      conn.delta(ch);
    }
    await t.advance(100);
    return { t, conn };
  }

  it("the snapshot of one ch leaves the resync of another pending (the ch conjunct)", async () => {
    const { t, conn } = await twoLost(false);
    expect(t.engine.counters.pendingRequests).toBe(2);
    conn.snap(BOOK, "client_resync");
    expect(t.engine.counters.pendingRequests).toBe(1);
    conn.snap(TRADES, "client_resync");
    expect(t.engine.counters.pendingRequests).toBe(0);
  });

  it("the snapshot of a ch leaves a request of another kind for it pending, and its reply still lands (the resync conjunct)", async () => {
    const { t, conn } = await twoLost(true);
    t.engine.setPane("p1", hidden); // a ctl for each: its ctl_ok is held back
    await t.advance(300);
    expect(t.engine.counters.pendingRequests).toBe(4); // two resyncs and two ctls
    conn.snap(TRADES, "client_resync");
    expect(t.engine.counters.pendingRequests).toBe(3); // the resync of trades, and only that, is answered
    conn.releaseHeld();
    expect(t.engine.counters.pendingRequests).toBe(1); // the ctl_oks were not forgotten: both of them were read
  });
});

describe("the sink hears what a reply changes (changed)", () => {
  // Each test reads the state of a handle at the moment the sink is told: the reply is already applied then.
  it("after a retune is confirmed, and not after a data frame", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(TRADES));
    await t.start();
    const reads = t.watch(() => handle.effective["throttle_ms"]);
    t.gateway.latest.delta(TRADES);
    expect(reads).toEqual([]); // a frame goes through deliver alone
    t.engine.setPane("p1", hidden);
    await t.advance(300);
    expect(reads).toEqual([1_000]); // the ctl_ok moved `effective`, and no frame says so
  });

  it("after the server ends a stream", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(TRADES));
    await t.start();
    const reads = t.watch(() => handle.status);
    t.gateway.latest.revoke(TRADES, "permission_revoked");
    expect(reads).toEqual(["revoked"]);
  });

  it("after an err answers a sub: its streams are refused", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined); // invalid_options is a client bug (10.3)
    const t = engineHarness();
    t.gateway.failSubs(1);
    const handle = t.engine.consume(spec(TRADES));
    const reads = t.watch(() => handle.status);
    await t.start();
    expect(reads).toEqual(["revoked"]);
  });

  it("after an unsub is answered: the request that waited for it is settled", async () => {
    const t = engineHarness({ hold: ["unsub_ok"] });
    const handle = t.engine.consume(spec(TRADES));
    await t.start();
    handle.release();
    await t.advance(300);
    const reads = t.watch(() => t.engine.counters.pendingRequests);
    t.gateway.latest.releaseHeld();
    expect(reads).toEqual([0]);
  });

  it("when a snapshot is overdue: the stream reads stale", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(TRADES));
    t.gateway.withholdSnaps(true);
    await t.start();
    const reads = t.watch(() => handle.status);
    await t.advance(BASELINE_DEADLINE_MS); // asked again, within the budget: nothing to report yet
    expect(reads).toEqual([]);
    await t.advance(BASELINE_DEADLINE_MS);
    expect(reads.at(-1)).toBe("stale"); // no snapshot came in time
  });
});

describe("rebaseline: the sink dropped frames of a stream", () => {
  it("asks for a fresh snapshot, as a consumer that joined late does (client_restart)", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    await t.start();
    t.got();
    t.engine.rebaseline(BOOK);
    await t.advance(100);
    expect(t.gateway.latest.of("resync")).toEqual([
      expect.objectContaining({
        ch: BOOK,
        p: expect.objectContaining({ last_seq: null, reason: "client_restart" }),
      }),
    ]);
    expect(t.got()).toEqual(["snap:2"]);
  });

  it("names the replay stream, takes the implicit system stream, and ignores a stream it does not hold", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK), RS);
    await t.start();
    t.engine.rebaseline(BOOK, RS);
    t.engine.rebaseline("system");
    t.engine.rebaseline("trades.ETHUSDT"); // not subscribed
    t.engine.rebaseline(BOOK); // the live stream of the ch is not the replay one
    await t.advance(100);
    expect(named(t.gateway.latest.of("resync"))).toEqual([
      [BOOK, RS],
      ["system", undefined],
    ]);
  });

  it("ignores the session it is given for system: it has no replay twin", async () => {
    const t = engineHarness();
    await t.start();
    t.engine.rebaseline("system", RS);
    await t.advance(100);
    expect(named(t.gateway.latest.of("resync"))).toEqual([["system", undefined]]);
  });

  it("does nothing while there is no connection, and spends none of the resync budget on it", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    for (let i = 0; i < 6; i += 1) t.engine.rebaseline(BOOK); // before the socket is up: nothing can leave
    await t.start();
    for (let i = 0; i < 5; i += 1) {
      t.engine.rebaseline(BOOK);
      await t.advance(50);
    }
    expect(t.gateway.latest.of("resync")).toHaveLength(5); // all five of the minute are still there
  });

  it("is held to the resync budget: the sixth in a minute waits", async () => {
    const t = engineHarness();
    t.engine.consume(spec(BOOK));
    await t.start();
    for (let i = 0; i < 6; i += 1) {
      t.engine.rebaseline(BOOK);
      await t.advance(50);
    }
    expect(t.gateway.latest.of("resync")).toHaveLength(5);
    await t.advance(61_000);
    expect(t.gateway.latest.of("resync")).toHaveLength(6);
  });
});

describe("the server's clock", () => {
  it("is the welcome's skew while the socket is up, and nothing before or after", async () => {
    const t = engineHarness({ skewMs: 2_500 });
    expect(t.engine.clockSkewMs).toBeUndefined();
    await t.start();
    expect(t.engine.clockSkewMs).toBe(2_500);
    t.gateway.latest.close(1011);
    expect(t.engine.clockSkewMs).toBeUndefined();
  });

  it("is not known before the welcome: a socket that is open and silent has no skew, not a skew of 0", async () => {
    const t = engineHarness({ skewMs: 2_500, silent: true });
    await t.start();
    expect(t.gateway.conns).toHaveLength(1);
    expect(t.engine.clockSkewMs).toBeUndefined();
  });
});
