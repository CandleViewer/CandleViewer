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
  it("after a reply, and not after a data frame", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(TRADES));
    await t.start();
    const settled = t.changes();
    expect(settled).toBeGreaterThan(0); // the sub_ok
    t.gateway.latest.delta(TRADES);
    expect(t.changes()).toBe(settled); // a frame goes through deliver alone
    t.engine.setPane("p1", hidden);
    await t.advance(300);
    expect(t.changes()).toBe(settled + 1); // the ctl_ok moved `effective`, and no frame says so
    expect(handle.effective).toEqual({ throttle_ms: 1_000 });
  });

  it("when a snapshot is overdue and the stream reads stale", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec(TRADES));
    t.gateway.withholdSnaps(true);
    await t.start();
    const waiting = t.changes();
    await t.advance(BASELINE_DEADLINE_MS); // asked again, within the budget: nothing to report yet
    expect(t.changes()).toBe(waiting);
    await t.advance(BASELINE_DEADLINE_MS);
    expect(handle.status).toBe("stale"); // no snapshot came in time
    expect(t.changes()).toBe(waiting + 2); // trades, and system, whose snapshot is withheld too
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
