// E17-T04 S5d (ADR-0005, D13; 23 5.4, 7.5, 8.5, 9.3; C8, C9; C-2.18): the host of the shared worker, the half that
// serves streams, against a fake gateway and fake tabs. Each consumer has a queue and buffers of its own; a
// newcomer waits for its snapshot; a consumer that cannot keep up is voided and re-baselined; what the tabs show
// decides how the topics run.
import { afterEach, describe, expect, it, vi } from "vitest";
import { MAX_CONSUMERS_PER_TAB } from "../../../src/lib/ws/worker/portHost";
import { tokenOf } from "./support/connectionHarness";
import { b64, bookDelta } from "./support/cvwb";
import { BOOK } from "./support/engineHarness";
import { FakeTab, hostHarness } from "./support/hostHarness";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const TRADES = "trades.BTCUSDT";
const RS = "bb000000-0000-4000-8000-000000000001";
/** A tab with a consumer of `ch` that the handshake and the snapshot have reached. */
async function watching(ch = BOOK, tabs = 1) {
  const t = hostHarness();
  const list = Array.from({ length: tabs }, () => t.tab());
  list.forEach((tab, i) => t.consume(tab, `k${i + 1}`, ch));
  await t.advance(400);
  return { t, tabs: list, conn: t.gateway.latest };
}
/** The buffers of the binary body of the last data message of a tab. */
const bytesOf = (tab: FakeTab): ArrayBuffer => {
  const frame = tab.last("data").frames.at(-1);
  const body = frame?.kind === "d" ? frame.body : undefined;
  if (body?.e !== "b64") throw new Error("not a binary delta");
  return body.bytes;
};
/** Counted by `diag`, which is posted at most once a second. */
const counted = async (t: ReturnType<typeof hostHarness>, tab: FakeTab) => {
  await t.advance(1_100);
  return tab.last("diag").diag;
};

describe("frames to a tab", () => {
  it("a consumer gets its snapshot and what follows, in one message per flush, with what its handle reads", async () => {
    const { t, tabs, conn } = await watching();
    const [a] = tabs;
    expect(a?.frames("k1")).toEqual(["snap:1"]);
    expect(a?.last("data")).toMatchObject({
      status: "live",
      source: "live",
      effective: { throttle_ms: 50 },
    });
    conn.delta(BOOK);
    expect(a?.frames("k1")).toEqual(["snap:1"]); // nothing leaves before the window closes
    await t.advance(8);
    expect(a?.frames("k1")).toEqual(["snap:1", "d:2"]);
  });

  it("500 frames inside one animation frame leave as one message, inside 16 ms (C9)", async () => {
    const { t, tabs, conn } = await watching();
    const [a] = tabs;
    const before = a?.of("data").length ?? 0;
    for (let i = 0; i < 500; i += 1) conn.delta(BOOK);
    expect(t.host.counters.queuedFrames).toBe(500); // held until the window closes
    await t.advance(16);
    expect(t.host.counters.queuedFrames).toBe(0);
    expect(a?.of("data")).toHaveLength(before + 1);
    expect(a?.last("data").frames).toHaveLength(500);
    expect(a?.last("data").frames.map((f) => (f.kind === "d" ? f.seq : 0))).toEqual(
      Array.from({ length: 500 }, (_, i) => i + 2),
    );
  });

  it("tells a tab what its handle reads when no frame says so: a retune moves `effective`", async () => {
    const { t, tabs } = await watching(TRADES);
    const [a] = tabs;
    a?.say({ t: "visibility", hidden: true });
    await t.advance(300);
    expect(a?.last("data")).toMatchObject({ frames: [], effective: { throttle_ms: 1_000 } });
  });

  it("is not copied for one consumer, and costs one copy for each consumer more (ADR-0005 zero-copy)", async () => {
    const copy = vi.spyOn(ArrayBuffer.prototype, "slice");
    const one = await watching(BOOK, 1);
    copy.mockClear();
    one.conn.delta(BOOK, b64(bookDelta()), undefined, { e: "b64" });
    await one.t.advance(8);
    expect(copy).not.toHaveBeenCalled();
    const three = await watching(BOOK, 3);
    copy.mockClear();
    three.conn.delta(BOOK, b64(bookDelta()), undefined, { e: "b64" });
    await three.t.advance(8);
    expect(copy).toHaveBeenCalledTimes(2);
  });

  it("posts nothing to a consumer when nothing it reads has changed, whatever else made the host flush", async () => {
    const { t, tabs } = await watching();
    const [a] = tabs;
    const before = a?.of("data").length ?? 0;
    a?.say({ t: "release", id: "nope" }); // a refusal makes the host flush, to post its count
    await t.advance(100);
    expect(a?.of("data")).toHaveLength(before);
  });

  it("a consumer that was still waiting for its snapshot reads revoked once the server ends the stream", async () => {
    const t = hostHarness();
    t.gateway.withholdSnaps(true);
    const a = t.tab();
    t.consume(a, "k1", BOOK);
    await t.advance(400);
    expect(a.last("data").status).toBe("pending");
    t.gateway.latest.revoke(BOOK, "permission_revoked");
    await t.advance(8);
    expect(a.last("data").status).toBe("revoked");
  });

  it("lists the buffer of a binary body in the transfer list of its message", async () => {
    const { t, tabs, conn } = await watching();
    conn.delta(BOOK, b64(bookDelta()), undefined, { e: "b64" });
    await t.advance(8);
    const [a] = tabs;
    const sent = a?.sent.filter(({ message }) => message.t === "data").at(-1);
    expect(sent?.transfer).toEqual(a ? [bytesOf(a)] : []);
  });

  it("a stream the server ended reads revoked, and says why in its last frame", async () => {
    const { t, tabs, conn } = await watching();
    const [a] = tabs;
    conn.revoke(BOOK, "permission_revoked");
    await t.advance(8);
    expect(a?.frames("k1")).toEqual(["snap:1", "reset:revoked"]);
    expect(a?.last("data").status).toBe("revoked");
  });

  it("a stream of a replay session reaches the consumer of that session only", async () => {
    const t = hostHarness();
    const a = t.tab();
    t.consume(a, "live", BOOK);
    t.consume(a, "replay", BOOK, { rs: RS });
    await t.advance(400);
    t.gateway.latest.delta(BOOK, {}, RS);
    await t.advance(8);
    expect([a.frames("live"), a.frames("replay")]).toEqual([["snap:1"], ["snap:1", "d:2"]]);
    expect(a.last("data")).toMatchObject({ id: "replay", source: "replay" });
  });
});

describe("one stream, many consumers", () => {
  it("every consumer gets every frame, each with buffers of its own: the last takes the originals, the others copies", async () => {
    const { t, tabs, conn } = await watching(BOOK, 3);
    conn.delta(BOOK, b64(bookDelta()), undefined, { e: "b64" });
    await t.advance(8);
    const buffers = tabs.map(bytesOf);
    expect(new Set(buffers).size).toBe(3);
    for (const buffer of buffers)
      expect(new Uint8Array(buffer)).toEqual(new Uint8Array(buffers[0] ?? new ArrayBuffer(0)));
    tabs.forEach((tab, i) => {
      expect(tab.sent.filter(({ message }) => message.t === "data").at(-1)?.transfer).toEqual([
        buffers[i],
      ]);
    });
  });

  it("two consumers of one tab are two messages, and two buffers", async () => {
    const t = hostHarness();
    const a = t.tab();
    t.consume(a, "k1", BOOK, { pane: "p1" });
    t.consume(a, "k2", BOOK, { pane: "p2" });
    await t.advance(400);
    t.gateway.latest.delta(BOOK, b64(bookDelta()), undefined, { e: "b64" });
    await t.advance(8);
    const lasts = a.of("data").filter((m) => m.frames.some((f) => f.kind === "d"));
    expect(lasts.map((m) => m.id).sort()).toEqual(["k1", "k2"]);
    expect(
      new Set(
        lasts
          .flatMap((m) => m.frames)
          .flatMap((f) => (f.kind === "d" && f.body.e === "b64" ? [f.body.bytes] : [])),
      ).size,
    ).toBe(2);
  });

  it("holds a newcomer back until a snapshot of its own: the deltas before it are not its", async () => {
    const { t, tabs, conn } = await watching();
    const [a] = tabs;
    t.gateway.withholdSnaps(true); // the engine asks for a baseline for the newcomer, and none comes yet
    const b = t.tab();
    t.consume(b, "k9", BOOK);
    await t.advance(300);
    expect(b.last("data")).toMatchObject({ id: "k9", frames: [], status: "pending" });
    conn.delta(BOOK);
    await t.advance(8);
    expect([a?.frames("k1"), b.frames("k9")]).toEqual([["snap:1", "d:2"], []]);
    conn.snap(BOOK, "client_resync"); // its own baseline, and everyone's
    await t.advance(8);
    expect([a?.frames("k1"), b.frames("k9")]).toEqual([["snap:1", "d:2", "snap:3"], ["snap:3"]]);
    expect(b.last("data").status).toBe("live");
    conn.delta(BOOK);
    await t.advance(8);
    expect(b.frames("k9")).toEqual(["snap:3", "d:4"]);
  });

  it("a release leaves the others as they were, and the last one's unsubscribes", async () => {
    const { t, tabs, conn } = await watching(BOOK, 2);
    const [a, b] = tabs;
    a?.say({ t: "release", id: "k1" });
    await t.advance(300);
    expect(conn.of("unsub")).toEqual([]);
    conn.delta(BOOK);
    await t.advance(8);
    expect([a?.frames("k1"), b?.frames("k2")]).toEqual([["snap:1"], ["snap:1", "d:2"]]);
    b?.say({ t: "release", id: "k2" });
    await t.advance(300);
    expect(conn.of("unsub")).toHaveLength(1);
  });
});

describe("a consumer that cannot keep up (C-2.18)", () => {
  async function flooded() {
    const t = hostHarness(undefined, { limits: { maxFrames: 3, maxBytes: 1e9 } });
    const a = t.tab();
    t.consume(a, "k1", BOOK);
    await t.advance(400);
    t.gateway.withholdSnaps(true);
    for (let i = 0; i < 5; i += 1) t.gateway.latest.delta(BOOK); // 5 frames inside one window, 3 allowed
    return { t, a, conn: t.gateway.latest };
  }

  it("is voided, told so in order, kept waiting for a snapshot, and one is asked for", async () => {
    const { t, a, conn } = await flooded();
    await t.advance(100);
    expect(a.frames("k1")).toEqual(["snap:1", "reset:overflow"]);
    expect(a.last("data")).toMatchObject({
      status: "resyncing",
      frames: [{ kind: "reset", reason: "overflow" }],
    });
    expect(conn.of("resync")).toEqual([
      expect.objectContaining({
        ch: BOOK,
        p: expect.objectContaining({ reason: "client_restart" }),
      }),
    ]);
    conn.delta(BOOK); // the stream goes on, and none of it is the voided consumer's
    await t.advance(8);
    expect(a.frames("k1")).toEqual(["snap:1", "reset:overflow"]);
    conn.snap(BOOK, "client_resync");
    await t.advance(8);
    expect(a.frames("k1")).toEqual(["snap:1", "reset:overflow", "snap:8"]);
    expect(a.last("data").status).toBe("live");
    expect((await counted(t, a)).host.overflows).toBe(1);
  });

  it("a consumer that is voided does not void its neighbours: the others read on", async () => {
    const t = hostHarness(undefined, { limits: { maxFrames: 3, maxBytes: 1e9 } });
    const a = t.tab();
    const b = t.tab();
    t.consume(a, "k1", BOOK);
    t.consume(b, "k2", BOOK);
    await t.advance(400);
    for (let i = 0; i < 2; i += 1) t.gateway.latest.delta(BOOK);
    await t.advance(8); // both took 2 frames: neither is over
    expect([a.frames("k1").at(-1), b.frames("k2").at(-1)]).toEqual(["d:3", "d:3"]);
  });

  it("what was queued for a consumer the tab voided is dropped, not sent after it", async () => {
    const { t, tabs, conn } = await watching();
    const [a] = tabs;
    t.gateway.withholdSnaps(true);
    conn.delta(BOOK); // queued, and the window is still open
    a?.say({ t: "resync", id: "k1" });
    await t.advance(300);
    expect(a?.frames("k1")).toEqual(["snap:1"]);
    expect(a?.last("data").status).toBe("resyncing");
  });

  it("the tab can void its own consumer: it is held back like a newcomer, and a snapshot is asked for", async () => {
    const { t, tabs, conn } = await watching();
    const [a] = tabs;
    t.gateway.withholdSnaps(true);
    a?.say({ t: "resync", id: "k1" });
    conn.delta(BOOK);
    await t.advance(300);
    expect(a?.last("data")).toMatchObject({ status: "resyncing" });
    expect(a?.frames("k1")).toEqual(["snap:1"]);
    expect(conn.of("resync")).toHaveLength(1);
    conn.snap(BOOK, "client_resync");
    await t.advance(8);
    expect(a?.last("data").status).toBe("live");
  });
});

describe("what the tabs show decides how the topics run (C8)", () => {
  const throttles = (conn: { of(t: string): Record<string, unknown>[] }) =>
    conn.of("ctl").map((f) => [f["ch"], (f["p"] as { throttle_ms: number }).throttle_ms]);

  it("a hidden tab slows its topics to 1 000 ms and restores them; the fastest consumer of a topic decides", async () => {
    const { t, tabs, conn } = await watching(TRADES, 2);
    const [a, b] = tabs;
    a?.say({ t: "visibility", hidden: true });
    await t.advance(300);
    expect(throttles(conn)).toEqual([]); // the other tab is looking at it
    b?.say({ t: "visibility", hidden: true });
    await t.advance(300);
    expect(throttles(conn)).toEqual([[TRADES, 1_000]]);
    a?.say({ t: "visibility", hidden: false });
    await t.advance(300);
    expect(throttles(conn)).toEqual([
      [TRADES, 1_000],
      [TRADES, 100],
    ]);
    expect(conn.of("unsub")).toEqual([]);
  });

  it("a pane that was never described belongs to its tab: a consumer that arrives in a hidden tab is slowed at once", async () => {
    const t = hostHarness();
    const a = t.tab();
    a.say({ t: "visibility", hidden: true });
    t.consume(a, "k1", TRADES);
    await t.advance(400);
    expect(throttles(t.gateway.latest)).toEqual([[TRADES, 1_000]]);
  });

  it("a collapsed pane lets its topics go, and comes back", async () => {
    const { t, tabs, conn } = await watching(TRADES);
    const [a] = tabs;
    a?.say({ t: "pane", id: "p1", visibility: "collapsed" });
    await t.advance(300);
    expect(conn.of("unsub")).toHaveLength(1);
    a?.say({ t: "pane", id: "p1", visibility: "visible" });
    await t.advance(300);
    expect(conn.of("sub")).toHaveLength(2);
  });

  it("the size of a heatmap's pane is what its bucket is derived from (6.1.1)", async () => {
    const t = hostHarness();
    const a = t.tab();
    a.say({ t: "pane", id: "p1", visibility: "visible", cssWidth: 1190, dpr: 1 });
    t.consume(a, "k1", "heatmap.BTCUSDT");
    await t.advance(400);
    expect(t.gateway.latest.of("sub")[0]).toMatchObject({
      p: { topics: [{ ch: "heatmap.BTCUSDT", opts: { time_bucket_ms: 1_000 } }] },
    });
  });

  it("the focused pane's topics come back first after a reconnect, whichever tab it is in", async () => {
    const t = hostHarness();
    const a = t.tab();
    const b = t.tab();
    t.consume(a, "k1", TRADES, { priority: "other" });
    t.consume(b, "k2", BOOK, { priority: "other" });
    b.say({ t: "focus", id: "p1" });
    a.say({ t: "focus", id: null }); // not the owner: leaves it alone
    await t.advance(400);
    t.gateway.latest.close(1011);
    await t.advance(1_000);
    expect(
      t.gateway.latest
        .of("sub")
        .flatMap((f) => (f["p"] as { topics: { ch: string }[] }).topics.map((x) => x.ch)),
    ).toEqual([BOOK, TRADES]);
    b.say({ t: "focus", id: null }); // the owner lets go
    t.gateway.latest.close(1011);
    await t.advance(1_000);
    expect(t.gateway.conns.at(-1)?.of("sub")[0]).toMatchObject({
      p: { topics: [{ ch: TRADES }, { ch: BOOK }] }, // now each topic is where its own priority puts it
    });
  });
});

describe("a focus that is gone", () => {
  it("is cleared when the tab that held it leaves: the topics are ordered by their own priority again", async () => {
    const t = hostHarness();
    const a = t.tab();
    const b = t.tab();
    t.consume(a, "k1", TRADES, { priority: "other" });
    t.consume(a, "k2", BOOK, { priority: "focused" });
    t.consume(b, "k3", "ticker.BTCUSDT", { pane: "pb" });
    b.say({ t: "focus", id: "pb" });
    await t.advance(400);
    b.say({ t: "stop" });
    await t.advance(300);
    t.gateway.latest.close(1011);
    await t.advance(1_000);
    const order = t.gateway.latest
      .of("sub")
      .flatMap((f) => (f["p"] as { topics: { ch: string }[] }).topics.map((x) => x.ch));
    expect(order).toEqual([BOOK, TRADES]); // not [TRADES, BOOK]: no pane is focused any more
  });
});

describe("what a tab may ask", () => {
  it("is refused when it is a name taken, a name unknown or past a limit, and counted", async () => {
    const { t, tabs } = await watching();
    const [a] = tabs;
    const tab = a ?? new FakeTab(true);
    for (let i = 0; i < MAX_CONSUMERS_PER_TAB; i += 1) t.consume(tab, `c${i}`, TRADES); // the last is one too many
    await t.advance(2_000); // the host goes quiet
    t.consume(tab, "k1", BOOK); // taken
    tab.say({ t: "release", id: "nope" });
    tab.say({ t: "resync", id: "nope" });
    tab.say({ t: "pane", id: "p1", visibility: "bogus" }); // malformed
    expect((await counted(t, tab)).host).toMatchObject({
      consumers: MAX_CONSUMERS_PER_TAB,
      rejectedMessages: 5,
    });
  });
});

describe("diagnostics (D8)", () => {
  it("are posted when the counters move, at most once a second, and carry no token", async () => {
    const { t, tabs } = await watching();
    const [a] = tabs;
    await t.advance(1_100);
    const first = a?.last("diag").diag;
    expect(first).toMatchObject({
      host: { tabs: 1, consumers: 1 },
      engine: { streams: 1 },
      clockSkewMs: 0,
    });
    const count = a?.of("diag").length;
    await t.advance(5_000);
    expect(a?.of("diag")).toHaveLength(count ?? -1); // nothing moved, nothing is said
    expect(JSON.stringify(a?.of("diag"))).not.toContain(tokenOf(1));
  });

  it("are not repeated while frames keep the host flushing and nothing in the counters moved", async () => {
    const { t, tabs, conn } = await watching();
    const [a] = tabs;
    await t.advance(1_100);
    const count = a?.of("diag").length;
    for (let i = 0; i < 4; i += 1) {
      conn.delta(BOOK);
      await t.advance(1_100);
    }
    expect(a?.of("diag")).toHaveLength(count ?? -1);
  });

  it("count the tabs again when one leaves", async () => {
    const { t, tabs } = await watching(BOOK, 2);
    const [a, b] = tabs;
    await t.advance(1_100);
    expect(b?.last("diag").diag.host.tabs).toBe(2);
    a?.say({ t: "stop" });
    await t.advance(1_100);
    expect(b?.last("diag").diag.host.tabs).toBe(1);
  });
});
