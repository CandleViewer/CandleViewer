// #5345 (E08-D14 DF-1): the CMP-076 chip's selector, E17-D02 §3, row by row of the §2 matrix, then
// an exhaustive sweep of its precedence (D2) over a grid of links, upstream facts, topics and the
// T3 hold: no stale cause is ever drawn as Live or Delayed, the transport always wins, and a topic
// the chip does not judge (replay, private, `system`, derived, revoked) never moves it.
import { isDeepStrictEqual } from "node:util";
import { describe, expect, it } from "vitest";
import {
  DELAYED_MIN_MS,
  NO_CHIP_MEMORY,
  STALE_T1_MS,
  STALE_T2_FACTOR,
  judgedFamily,
  selectChip,
  stepChipMemory,
  type ChipInput,
  type ChipMemory,
  type ChipView,
  type TopicReading,
} from "../../../src/lib/ws/state/chipState";
import { connectionPresentation } from "../../../src/lib/ws/state/connectionPresentation";
import { reduce } from "../../../src/lib/ws/state/reducer";
import type { WsState } from "../../../src/lib/ws/state/types";
import { OFF, authOk, connecting, notice, quality, stream } from "./support/engineEvents";
import { runEvents } from "./support/fakeActiveClient";

/** The clock the topics' times are on (the client's monotonic one) and the wall time beside it. */
const NOW = 9_000_000;
const WALL = Date.UTC(2026, 10, 1, 13, 42, 5);
const UP = runEvents(connecting, authOk(OFF), stream("live"));
const SATURATED = reduce(UP, quality("saturated"));
const LAGGING = reduce(UP, quality("lagging"));
const SHUTDOWN = reduce(UP, notice({ closing_in_ms: 5000, expected_downtime_ms: 2e4 }));
const LOST = { sinceMs: WALL - 2_000, lastDataMs: WALL - 12_000 };
const RECONNECTING = reduce(UP, {
  type: "reconnecting",
  attempt: 3,
  nextAttemptAtMs: WALL + 4_000,
  lost: LOST,
});
const SHELL_CAUSE = reduce(UP, { type: "offline", cause: "tailnet_unreachable", lost: LOST });
const FATAL = reduce(UP, { type: "offline", cause: "fatal", closeCode: 1002, lost: LOST });
const FIRST = runEvents(connecting);

/** A live topic of the shell's consumers whose last fresh frame was `ageMs` ago. */
const topic = (ch: string, ageMs: number, over: Partial<TopicReading> = {}): TopicReading => ({
  ch,
  rs: undefined,
  source: "live",
  status: "live",
  freshAtMs: NOW - ageMs,
  agedFromMs: NOW - ageMs,
  lastDataMs: WALL - ageMs,
  serverStale: false,
  awaitingReconnect: false,
  ...over,
});
/** A topic with no fresh frame yet, aged from `agedMs` ago (its consume time, or the link's coming up). */
const unfed = (ch: string, agedMs: number, over: Partial<TopicReading> = {}): TopicReading =>
  topic(ch, agedMs, { status: "pending", freshAtMs: null, lastDataMs: null, ...over });
/** A topic a drop left owed a snapshot: its last fresh frame 9 s ago, the link back `sinceUpMs` ago (what it ages from). */
const awaiting = (ch: string, sinceUpMs: number, over: Partial<TopicReading> = {}): TopicReading =>
  topic(ch, sinceUpMs, {
    status: "pending",
    awaitingReconnect: true,
    freshAtMs: NOW - 9_000,
    lastDataMs: WALL - 9_000,
    ...over,
  });
const input = (over: Partial<ChipInput> = {}): ChipInput => ({
  ws: UP,
  upstreamDown: false,
  throttleMultiplier: undefined,
  topics: [],
  clockMs: NOW,
  ...over,
});
const select = (over: Partial<ChipInput> = {}, memory: ChipMemory = NO_CHIP_MEMORY): ChipView =>
  selectChip(input(over), memory);
const T2 = (family: keyof typeof STALE_T1_MS): number => STALE_T1_MS[family] * STALE_T2_FACTOR;

describe("judged families (E17-D01 §4.1 T1)", () => {
  it.each([
    ["book.BTCUSDT.50", "book"],
    ["ticker.BTCUSDT", "ticker"],
    ["trades.ETHUSDT", "trades"],
    ["bars.BTCUSDT.1m", null],
    ["heatmap.BTCUSDT", null],
    ["footprint.BTCUSDT.tick.1000", null],
    ["orders", null],
    ["system", null],
    ["tickers", null],
    ["", null],
  ])("%s → %s", (ch, family) => {
    expect(judgedFamily(ch)).toBe(family);
  });

  it("T1 is book 2 s, ticker 5 s, trades 10 s, and T2 is three times it", () => {
    expect(STALE_T1_MS).toEqual({ book: 2_000, ticker: 5_000, trades: 10_000 });
    expect([T2("book"), T2("ticker"), T2("trades")]).toEqual([6_000, 15_000, 30_000]);
  });
});

describe("the transport first (rows 1, 3, 6; B-1): the link split of connectionPresentation", () => {
  it.each([
    ["a first connect", FIRST, { status: "reconnecting", attempt: undefined, firstConnect: true }],
    ["a running retry", RECONNECTING, { status: "reconnecting", attempt: 3, firstConnect: false }],
    [
      "a shell cause",
      SHELL_CAUSE,
      { status: "reconnecting", attempt: undefined, firstConnect: false },
    ],
    ["a fatal close", FATAL, { status: "offline", attempt: undefined, firstConnect: false }],
  ] as const)("%s", (_name, ws, expected) => {
    // every topic cause at once: none of them shows while the link is down
    const topics = [topic("ticker.BTCUSDT", 60_000, { serverStale: true })];
    const view = select({ ws, upstreamDown: true, topics });
    expect(view).toMatchObject(expected);
    const { lastGoodTs } = connectionPresentation(ws);
    expect(view).toMatchObject({ lastGoodTs });
  });
});

describe("row 13: the exchange's public feed down", () => {
  it("reads Stale with the upstream cause, the oldest topic's last data, never strong", () => {
    const topics = [topic("ticker.BTCUSDT", 1_000), topic("book.BTCUSDT.50", 3_000)];
    expect(select({ upstreamDown: true, topics })).toEqual({
      status: "stale",
      cause: "upstream",
      ageMs: undefined,
      t2AgeMs: undefined,
      strong: false,
      lastGoodTs: WALL - 3_000,
      t2Symbols: [],
    });
  });

  it("with no public topic it still reads the upstream cause, with no last data", () => {
    expect(select({ upstreamDown: true })).toMatchObject({
      status: "stale",
      cause: "upstream",
      lastGoodTs: null,
    });
  });

  it("wins over a server-stale topic, a T2 age and a saturated link (D2)", () => {
    const topics = [
      topic("ticker.BTCUSDT", 60_000, { serverStale: true }),
      topic("book.BTCUSDT.50", 60_000),
    ];
    expect(select({ ws: SATURATED, upstreamDown: true, topics })).toMatchObject({
      status: "stale",
      cause: "upstream",
    });
  });

  it("wins over row 16's wait: the fact comes with auth_ok's system snapshot", () => {
    const waiting = awaiting("ticker.BTCUSDT", 1_000); // inside its T1: row 16 alone would read Reconnecting
    expect(select({ topics: [waiting] })).toMatchObject({ status: "reconnecting" });
    expect(select({ upstreamDown: true, topics: [waiting] })).toMatchObject({
      status: "stale",
      cause: "upstream",
    });
    // and so does its hold, once the fact has cleared, until the topic's first fresh frame
    const memory: ChipMemory = { ...NO_CHIP_MEMORY, upstreamSinceMs: NOW - 5_000 };
    expect(select({ topics: [waiting] }, memory)).toMatchObject({ cause: "upstream" });
  });

  it("holds after the fact clears until each judged topic has a fresh frame (§3 exits)", () => {
    const since = NOW - 5_000;
    const memory: ChipMemory = { ...NO_CHIP_MEMORY, upstreamSinceMs: since };
    const quiet = topic("ticker.BTCUSDT", 6_000); // last fresh before the episode
    const fresh = topic("book.BTCUSDT.50", 100);
    expect(select({ topics: [quiet, fresh] }, memory)).toMatchObject({ cause: "upstream" });
    expect(select({ topics: [fresh] }, memory)).toEqual({ status: "live" });
    expect(select({}, memory)).toEqual({ status: "live" }); // nothing to wait for
  });

  it("a topic made during the outage, with no fresh frame yet, holds it too", () => {
    const memory: ChipMemory = { ...NO_CHIP_MEMORY, upstreamSinceMs: NOW - 5_000 };
    expect(select({ topics: [unfed("ticker.BTCUSDT", 2_000)] }, memory)).toMatchObject({
      status: "stale",
      cause: "upstream",
      lastGoodTs: null,
    });
    expect(select({ topics: [topic("ticker.BTCUSDT", 100)] }, memory)).toEqual({ status: "live" });
  });

  it("holds by the last fresh frame, not by the link's coming up after it", () => {
    const memory: ChipMemory = { ...NO_CHIP_MEMORY, upstreamSinceMs: NOW - 5_000 };
    const relinked = topic("ticker.BTCUSDT", 6_000, { agedFromMs: NOW - 1_000 });
    expect(select({ topics: [relinked] }, memory)).toMatchObject({ cause: "upstream" });
  });

  it("a topic the chip does not judge never holds it", () => {
    const memory: ChipMemory = { ...NO_CHIP_MEMORY, upstreamSinceMs: NOW - 5_000 };
    const topics = [topic("bars.BTCUSDT.1m", 60_000), topic("ticker.BTCUSDT", 60_000, { rs: "r" })];
    expect(select({ topics }, memory)).toEqual({ status: "live" });
  });
});

describe("row 12: Stale (server), meta.stale on ticker or book", () => {
  it.each(["ticker.BTCUSDT", "book.BTCUSDT.50"])("%s reads Stale (server)", (ch) => {
    expect(select({ topics: [topic(ch, 100, { serverStale: true })] })).toEqual({
      status: "stale",
      cause: "server",
      ageMs: undefined,
      t2AgeMs: undefined,
      strong: false,
      lastGoodTs: null,
      t2Symbols: [],
    });
  });

  it("a server-stale trades topic is panel-only: the chip judges its age alone", () => {
    expect(select({ topics: [topic("trades.BTCUSDT", 100, { serverStale: true })] })).toEqual({
      status: "live",
    });
  });

  it("wins over a T2 age on another topic (§3's order)", () => {
    const topics = [
      topic("ticker.BTCUSDT", 100, { serverStale: true }),
      topic("book.ETHUSDT.50", 60_000),
    ];
    expect(select({ topics })).toMatchObject({ cause: "server" });
  });
});

describe("rows 10 and 11: a topic's age against its own T1 and T2", () => {
  it.each([
    ["book.BTCUSDT.50", 1_999, null],
    ["book.BTCUSDT.50", 2_000, false],
    ["book.BTCUSDT.50", 5_999, false],
    ["book.BTCUSDT.50", 6_000, true],
    ["ticker.BTCUSDT", 4_999, null],
    ["ticker.BTCUSDT", 5_000, false],
    ["ticker.BTCUSDT", 7_400, false],
    ["ticker.BTCUSDT", 15_000, true],
    ["trades.BTCUSDT", 9_999, null],
    ["trades.BTCUSDT", 10_000, false],
    ["trades.BTCUSDT", 30_000, true],
  ] as const)("%s at %i ms: strong %s (null = live)", (ch, ageMs, strong) => {
    const view = select({ topics: [topic(ch, ageMs)] });
    if (strong === null) expect(view).toEqual({ status: "live" });
    else expect(view).toMatchObject({ status: "stale", cause: "age", ageMs, strong });
  });

  it("shows the oldest stale topic's age and last data; strong when any topic is past its T2", () => {
    const topics = [
      topic("book.BTCUSDT.50", 7_000), // past book's T2 (6 s)
      topic("trades.ETHUSDT", 12_000), // past trades' T1 only, but the oldest
      topic("ticker.SOLUSDT", 1_000), // fresh
    ];
    expect(select({ topics })).toEqual({
      status: "stale",
      cause: "age",
      ageMs: 12_000,
      t2AgeMs: 7_000, // the T2 sentence's own age: the oldest of the topics past T2
      strong: true,
      lastGoodTs: WALL - 12_000,
      t2Symbols: ["BTCUSDT"],
    });
  });

  it("names each symbol past T2 once, the oldest first", () => {
    const topics = [
      topic("ticker.BTCUSDT", 16_000),
      topic("book.ETHUSDT.50", 20_000),
      topic("book.BTCUSDT.50", 9_000),
      topic("trades.SOLUSDT", 12_000), // T1 only
    ];
    expect(select({ topics })).toMatchObject({
      t2Symbols: ["ETHUSDT", "BTCUSDT"],
      t2AgeMs: 20_000,
    });
  });

  it("a batched ticker past T2 names no symbol: the channel carries many", () => {
    expect(select({ topics: [topic("ticker", 16_000)] })).toMatchObject({
      strong: true,
      t2AgeMs: 16_000,
      t2Symbols: [],
    });
  });

  it("ages a topic from the link's coming up when that is later than its last fresh frame", () => {
    // consumed (or last fed) 40 s ago, the link up 1 s ago: no frame could have come before
    const relinked = unfed("trades.BTCUSDT", 40_000, { agedFromMs: NOW - 1_000 });
    expect(select({ topics: [relinked] })).toEqual({ status: "live" });
    const silent = unfed("trades.BTCUSDT", 40_000, { agedFromMs: NOW - 10_000 });
    expect(select({ topics: [silent] })).toMatchObject({ cause: "age", ageMs: 10_000 });
  });

  it("an age never reads negative: a time read after the clock counts as now", () => {
    expect(select({ topics: [topic("ticker.BTCUSDT", -5_000)] })).toEqual({ status: "live" });
  });

  it.each([
    ["a replay subscription", topic("ticker.BTCUSDT", 60_000, { rs: "rs-1" })],
    ["a stream that says replay", topic("ticker.BTCUSDT", 60_000, { source: "replay" })],
    ["a revoked topic", topic("ticker.BTCUSDT", 60_000, { status: "revoked" })],
    ["a derived topic", topic("bars.BTCUSDT.1m", 60_000)],
    ["a private topic", topic("orders", 60_000)],
    ["the system stream", topic("system", 60_000)],
  ])("never judges %s", (_name, t) => {
    expect(select({ topics: [t] })).toEqual({ status: "live" });
  });
});

describe("row 5: Delayed (saturated), §9 and T3", () => {
  it("reads Delayed with the applied multiplier", () => {
    expect(select({ ws: SATURATED, throttleMultiplier: 4 })).toEqual({
      status: "delayed",
      throttleMultiplier: 4,
    });
  });

  it("lagging is no state (tooltip numbers only), and a shutdown notice is no chip value", () => {
    expect(select({ ws: LAGGING })).toEqual({ status: "live" });
    expect(select({ ws: SHUTDOWN })).toEqual({ status: "live" });
  });

  it.each([
    ["upstream", { upstreamDown: true }],
    ["server", { topics: [topic("ticker.BTCUSDT", 0, { serverStale: true })] }],
    ["age", { topics: [topic("ticker.BTCUSDT", 7_000)] }],
  ] as const)("every stale cause beats it: %s (D2)", (cause, over) => {
    expect(select({ ws: SATURATED, throttleMultiplier: 4, ...over })).toMatchObject({
      status: "stale",
      cause,
    });
  });

  it("is shown 5 s at least after its entry (T3), with the multiplier it had", () => {
    const memory: ChipMemory = {
      ...NO_CHIP_MEMORY,
      delayed: { sinceMs: NOW - 4_999, multiplier: 4 },
    };
    expect(select({}, memory)).toEqual({ status: "delayed", throttleMultiplier: 4 });
    const done: ChipMemory = {
      ...memory,
      delayed: { sinceMs: NOW - DELAYED_MIN_MS, multiplier: 4 },
    };
    expect(select({}, done)).toEqual({ status: "live" });
  });

  it("the T3 hold never beats a stale topic", () => {
    const memory: ChipMemory = {
      ...NO_CHIP_MEMORY,
      delayed: { sinceMs: NOW - 1_000, multiplier: 4 },
    };
    expect(select({ topics: [topic("book.BTCUSDT.50", 2_500)] }, memory)).toMatchObject({
      status: "stale",
    });
  });
});

describe("row 16: after a reconnect, Live waits for the public snapshots (§3 exits)", () => {
  const waiting = awaiting("ticker.BTCUSDT", 1_000);

  it("reads Reconnecting, with no counter, until the topic's snapshot", () => {
    expect(select({ topics: [waiting, topic("book.BTCUSDT.50", 100)] })).toEqual({
      status: "reconnecting",
      attempt: undefined,
      firstConnect: false,
      lastGoodTs: null,
    });
    const fed = { ...waiting, awaitingReconnect: false, freshAtMs: NOW, agedFromMs: NOW };
    expect(select({ topics: [fed] })).toEqual({ status: "live" });
  });

  it("a topic whose snapshot is overdue (status stale) is judged by its age instead", () => {
    expect(
      select({ topics: [awaiting("ticker.BTCUSDT", 9_000, { status: "stale" })] }),
    ).toMatchObject({
      status: "stale",
      cause: "age",
      ageMs: 9_000,
    });
  });

  it.each([
    ["book", "book.BTCUSDT.50"],
    ["ticker", "ticker.BTCUSDT"],
    ["trades", "trades.BTCUSDT"],
  ] as const)(
    "a %s snapshot nobody delivers holds Reconnecting for its T1 from the link's return, then its age reads Stale",
    (family, ch) => {
      // a consumer the engine let go of (a pane that collapsed) is never snapshotted, nor marked overdue
      const t1 = STALE_T1_MS[family];
      expect(select({ topics: [awaiting(ch, t1 - 1)] })).toMatchObject({ status: "reconnecting" });
      expect(select({ topics: [awaiting(ch, t1)] })).toMatchObject({
        status: "stale",
        cause: "age",
        ageMs: t1,
        strong: false,
        lastGoodTs: WALL - 9_000, // the last fresh frame, from before the drop
      });
    },
  );

  it("one topic inside its T1 holds it beside one past its own; once it is fed the age rule reads the other", () => {
    const young = awaiting("ticker.BTCUSDT", 1_000);
    const old = awaiting("book.BTCUSDT.50", 3_000); // past the book's 2 s
    expect(select({ topics: [young, old] })).toMatchObject({ status: "reconnecting" });
    const fed = { ...young, awaitingReconnect: false, freshAtMs: NOW, agedFromMs: NOW };
    expect(select({ topics: [fed, old] })).toMatchObject({ status: "stale", cause: "age" });
  });

  it("a replay or derived topic never holds it", () => {
    const topics = [
      { ...waiting, rs: "rs-1" },
      topic("bars.BTCUSDT.1m", 1_000, { status: "pending", awaitingReconnect: true }),
    ];
    expect(select({ topics })).toEqual({ status: "live" });
  });
});

describe("stepChipMemory: the two holds", () => {
  it("starts the upstream episode at the first fact and keeps its start while it holds", () => {
    const a = stepChipMemory(NO_CHIP_MEMORY, input({ upstreamDown: true }));
    expect(a.upstreamSinceMs).toBe(NOW);
    const later = input({ upstreamDown: true, clockMs: NOW + 3_000 });
    expect(stepChipMemory(a, later)).toBe(a); // unchanged: the same object
    const quiet = input({ clockMs: NOW + 4_000, topics: [topic("ticker.BTCUSDT", 2_000)] });
    expect(stepChipMemory(a, quiet)).toBe(a); // fact gone, the topic not fresh since
    const unfedYet = input({ clockMs: NOW + 4_000, topics: [unfed("ticker.BTCUSDT", 0)] });
    expect(stepChipMemory(a, unfedYet)).toBe(a); // fact gone, no fresh frame at all yet
    const fresh = input({ clockMs: NOW + 4_000, topics: [topic("ticker.BTCUSDT", -1_000)] });
    expect(stepChipMemory(a, fresh).upstreamSinceMs).toBeNull();
  });

  it("enters Delayed at the first saturated state and drops it 5 s on once the link improved", () => {
    const a = stepChipMemory(NO_CHIP_MEMORY, input({ ws: SATURATED, throttleMultiplier: 4 }));
    expect(a.delayed).toEqual({ sinceMs: NOW, multiplier: 4 });
    const b = stepChipMemory(a, input({ ws: SATURATED, clockMs: NOW + 1_000 }));
    expect(b).toBe(a); // the start and the multiplier kept
    expect(stepChipMemory(a, input({ clockMs: NOW + 4_999 }))).toBe(a);
    expect(stepChipMemory(a, input({ clockMs: NOW + 5_000 })).delayed).toBeNull();
    expect(stepChipMemory(a, input({ ws: RECONNECTING, clockMs: NOW + 1 })).delayed).toBeNull();
  });

  it("leaves NO_CHIP_MEMORY as it is when nothing holds", () => {
    expect(stepChipMemory(NO_CHIP_MEMORY, input({ topics: [topic("ticker.X", 0)] }))).toBe(
      NO_CHIP_MEMORY,
    );
  });
});

describe("the precedence, swept (D2): every link × upstream fact × hold × pair of topics", () => {
  const LINKS: readonly (readonly [string, WsState])[] = [
    ["up", UP],
    ["saturated", SATURATED],
    ["lagging", LAGGING],
    ["shutdown", SHUTDOWN],
    ["reconnecting", RECONNECTING],
    ["shell cause", SHELL_CAUSE],
    ["fatal", FATAL],
    ["first connect", FIRST],
  ];
  /** One of each kind the chip meets: fresh, past T1, past T2, server-stale, waiting, unfed, relinked, unjudged. */
  const TOPICS: readonly TopicReading[] = [
    topic("ticker.BTCUSDT", 1_000),
    topic("ticker.BTCUSDT", 7_000),
    topic("book.ETHUSDT.50", 6_500),
    topic("trades.SOLUSDT", 31_000),
    topic("trades.SOLUSDT", 12_000),
    topic("ticker.ETHUSDT", 0, { serverStale: true }),
    topic("trades.BTCUSDT", 0, { serverStale: true }),
    awaiting("ticker.XRPUSDT", 1_000), // owed a snapshot, inside its T1: the hold
    awaiting("ticker.XRPUSDT", 9_000), // owed one, past it (nobody delivers it): its age reads
    awaiting("ticker.XRPUSDT", 9_000, { status: "stale" }), // overdue by the worker's word
    unfed("book.SOLUSDT.50", 1_000),
    topic("trades.ADAUSDT", 40_000, { agedFromMs: NOW - 500 }),
    topic("ticker.BTCUSDT", 60_000, { rs: "rs-1" }),
    topic("bars.BTCUSDT.1m", 60_000),
    topic("orders", 60_000),
    topic("ticker.ADAUSDT", 60_000, { status: "revoked" }),
  ];
  const MEMORIES: readonly ChipMemory[] = [
    NO_CHIP_MEMORY,
    { upstreamSinceMs: NOW - 3_000, delayed: null },
    { upstreamSinceMs: null, delayed: { sinceMs: NOW - 1_000, multiplier: 4 } },
    { upstreamSinceMs: null, delayed: { sinceMs: NOW - 6_000, multiplier: 4 } },
  ];
  const pairs: TopicReading[][] = [[]];
  for (const [i, a] of TOPICS.entries()) {
    pairs.push([a]);
    for (const b of TOPICS.slice(i + 1)) pairs.push([a, b]);
  }
  const judged = (t: TopicReading): boolean =>
    t.rs === undefined &&
    t.source === "live" &&
    t.status !== "revoked" &&
    judgedFamily(t.ch) !== null;
  const ageOf = (t: TopicReading): number => Math.max(0, NOW - t.agedFromMs);
  const t1Of = (t: TopicReading): number => {
    const family = judgedFamily(t.ch);
    if (family === null) throw new Error(`not a judged topic: ${t.ch}`);
    return STALE_T1_MS[family];
  };

  it("holds the invariants on every one of the cases", () => {
    const failures: string[] = [];
    const check = (ok: boolean, what: string, where: () => string): void => {
      if (!ok && failures.length < 20) failures.push(`${what}: ${where()}`);
    };
    let cases = 0;
    for (const [name, ws] of LINKS)
      for (const upstreamDown of [false, true])
        for (const memory of MEMORIES)
          for (const topics of pairs) {
            cases += 1;
            const given = input({ ws, upstreamDown, topics, throttleMultiplier: 4 });
            const view = selectChip(given, memory);
            const where = (): string =>
              JSON.stringify({ name, upstreamDown, memory, topics, view });
            check(isDeepStrictEqual(selectChip(given, memory), view), "pure", where);
            const link = connectionPresentation(ws).chip;
            // 1. the transport wins: a link that is not up is never a topic state
            if (link.status !== "live") {
              check(view.status === link.status, "transport first", where);
              continue;
            }
            const counted = topics.filter(judged);
            const since = memory.upstreamSinceMs;
            const held =
              since !== null && counted.some((t) => t.freshAtMs === null || t.freshAtMs <= since);
            // 2. row 16: a judged topic waiting for its reconnect snapshot holds Reconnecting for
            // its T1 from the link's return at most, below the exchange's feed down and its hold
            // (known with auth_ok's system snapshot); one overdue (the worker says stale), or past
            // that T1 with no snapshot, is judged by its age
            const upstream = upstreamDown || held;
            const holding1 = (t: TopicReading): boolean =>
              t.awaitingReconnect && t.status !== "stale" && ageOf(t) < t1Of(t);
            if (!upstream && counted.some(holding1)) {
              const holding = view.status === "reconnecting" && !view.firstConnect;
              check(holding, "row 16 holds Reconnecting", where);
              continue;
            }
            const stale1 = counted.filter((t) => ageOf(t) >= t1Of(t));
            const serverStale = counted.some(
              (t) => t.serverStale && judgedFamily(t.ch) !== "trades",
            );
            // 3. no stale cause is ever drawn as Live or Delayed
            if (upstream || serverStale || stale1.length > 0) {
              check(view.status === "stale", "a stale cause reads Stale", where);
            }
            if (view.status === "stale") {
              const cause = upstream ? "upstream" : serverStale ? "server" : "age";
              check(view.cause === cause, "the cause's precedence", where);
              // 4. strong only for an age past its own T2, and the ages are the oldest stale
              // topic's (the word) and the oldest past-T2 topic's (the T2 sentence)
              const t2 = stale1.filter((t) => ageOf(t) >= t1Of(t) * STALE_T2_FACTOR);
              check(view.strong === (cause === "age" && t2.length > 0), "strong at T2 only", where);
              const oldest = Math.max(...stale1.map(ageOf));
              const ageMs = cause === "age" ? oldest : undefined;
              check(view.ageMs === ageMs, "the oldest stale topic's age", where);
              const t2AgeMs =
                cause === "age" && t2.length > 0 ? Math.max(...t2.map(ageOf)) : undefined;
              check(view.t2AgeMs === t2AgeMs, "the oldest past-T2 topic's age", where);
            }
            // 5. Delayed exactly when saturated (or within its 5 s) and nothing is stale
            const delayedHold =
              memory.delayed !== null && NOW - memory.delayed.sinceMs < DELAYED_MIN_MS;
            if (view.status !== "stale") {
              const delayed = ws.quality === "saturated" || delayedHold;
              check(view.status === (delayed ? "delayed" : "live"), "Delayed below Stale", where);
            }
            // 6. an unjudged topic never moves the chip
            const without = selectChip({ ...given, topics: counted }, memory);
            check(isDeepStrictEqual(without, view), "unjudged topics ignored", where);
          }
    expect(failures).toEqual([]);
    expect(cases).toBe(LINKS.length * 2 * MEMORIES.length * pairs.length);
  });
});
