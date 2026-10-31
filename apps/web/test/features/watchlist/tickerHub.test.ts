/**
 * E08-S08 (#4702): the ticker client. One batched `ticker` subscription per connection, at most 40 symbols shared by
 * every pane (E08-D07 D6, D27; 23 §6.1, §16.2); the client's share of the rebuild budget; the `resync_rate_limited`
 * back-off; frames read on animation frames (C9) and coalesced into per-symbol atoms, one write per slot. Fake clock
 * and a fake transport; the frames are the derived golden.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FLUSH_MS,
  FRAME_MS,
  IDLE_READ_MS,
  MAX_LIVE_SYMBOLS,
  SYSTEM_HUB_CLOCK,
  createTickerHub,
  type TickerHub,
} from "../../../src/features/watchlist/ticker/tickerHub";
import type { TickerItem } from "../../../src/features/watchlist/ticker/tickerValues";
import {
  FakeTransport,
  asRecorded,
  deltaOf,
  restItem,
  serverPaced,
  snapOf,
  streamItem,
  BTC_STREAM,
  type Timed,
} from "./support";

const T0 = Date.UTC(2026, 9, 31, 10, 0, 0);
/** The hub's coalescing slot: a frame shorter than the server's 250 ms window. */
const SLOT_MS = FLUSH_MS - FRAME_MS;
const syms = (n: number, from = 0): string[] =>
  Array.from({ length: n }, (_, i) => `S${String(from + i).padStart(3, "0")}USDT`);

let transport: FakeTransport;
let hub: TickerHub;

beforeEach(() => {
  vi.useFakeTimers({ now: T0 });
  transport = new FakeTransport();
  hub = createTickerHub(transport);
});
afterEach(() => {
  hub.dispose();
  vi.useRealTimers();
});

describe("one batched subscription per connection", () => {
  it("opens one `ticker` subscription for a pane's symbols", () => {
    hub.claim("p1", ["BTCUSDT", "ETHUSDT", "SOLUSDT"]);
    expect(transport.opened.map((c) => c.symbols)).toEqual([["BTCUSDT", "ETHUSDT", "SOLUSDT"]]);
    expect([...hub.getState().live].sort()).toEqual(["BTCUSDT", "ETHUSDT", "SOLUSDT"]);
  });

  it("shares it between panes: the union, each symbol once, and never past 40", () => {
    hub.claim("p1", syms(39));
    hub.claim("p2", ["XRPUSDT", "S000USDT"]);
    vi.advanceTimersByTime(2_000);
    const held = transport.current?.symbols ?? [];
    expect(held).toHaveLength(40);
    expect(new Set(held).size).toBe(40);
    expect(held).toContain("XRPUSDT");
    hub.claim("p3", ["ZZZUSDT"]);
    vi.advanceTimersByTime(2_000);
    expect(transport.current?.symbols).toHaveLength(MAX_LIVE_SYMBOLS);
    expect(transport.current?.symbols).not.toContain("ZZZUSDT");
  });

  it("budgetFor: 40 less the distinct symbols the other panes hold that the list does not", () => {
    hub.claim("other", ["XRPUSDT"]);
    expect(hub.budgetFor("watch", syms(120))).toBe(39);
    expect(hub.budgetFor("watch", [...syms(120), "XRPUSDT"])).toBe(40);
    expect(hub.othersHolding("watch", syms(120))).toBe(1);
    expect(hub.budgetFor("other", ["XRPUSDT"])).toBe(40);
  });

  it("a removal alone never re-subscribes; the symbol leaves with the next change", () => {
    hub.claim("p1", ["BTCUSDT", "ETHUSDT", "SOLUSDT"]);
    hub.claim("p1", ["BTCUSDT", "ETHUSDT"]);
    vi.advanceTimersByTime(10_000);
    expect(transport.opened).toHaveLength(1);
    hub.claim("p1", ["BTCUSDT", "ETHUSDT", "XRPUSDT"]);
    vi.advanceTimersByTime(2_000);
    expect(transport.opened).toHaveLength(2);
    expect(transport.opened[1]?.symbols).toEqual(["BTCUSDT", "ETHUSDT", "XRPUSDT"]);
    expect(transport.opened[0]?.released).toBe(true);
  });

  it("the last pane letting go releases the subscription at once (an unsub draws nothing)", () => {
    hub.claim("p1", ["BTCUSDT"]);
    hub.release("p1");
    expect(transport.opened[0]?.released).toBe(true);
    expect(hub.getState().live.size).toBe(0);
  });
});

describe("the client's share of the rebuild budget", () => {
  it("starts changes at least 2 s apart, and only while fewer than 4 draws fall in the last 60 s", () => {
    // A new window every 2.5 s for 70 s: each one may start on its own spacing, so only the share holds the fifth back
    // until the first draw leaves the 60 s window (a share of 5 would start it at 10 s).
    for (let i = 0; i < 28; i += 1) {
      hub.claim("p1", syms(10, i * 10));
      vi.advanceTimersByTime(2_500);
    }
    vi.advanceTimersByTime(120_000);
    const starts = transport.opened.map((c) => c.openedAt);
    expect(starts.slice(0, 5).map((at) => at - T0)).toEqual([0, 2_500, 5_000, 7_500, 60_000]);
    for (let i = 1; i < starts.length; i += 1) {
      expect((starts[i] ?? 0) - (starts[i - 1] ?? 0)).toBeGreaterThanOrEqual(2_000);
    }
    for (const at of starts) expect(transport.drawsWithin(at)).toBeLessThanOrEqual(4);
  });

  it("a waiting change subscribes the window wanted when it may go, not the ones asked for meanwhile", () => {
    hub.claim("p1", syms(5));
    hub.claim("p1", syms(5, 5));
    expect(hub.getState().waitingUntil).toBe(T0 + 2_000);
    hub.claim("p1", syms(5, 10));
    vi.advanceTimersByTime(2_000);
    expect(transport.opened.map((c) => c.symbols[0])).toEqual(["S000USDT", "S010USDT"]);
    expect(hub.getState().waitingUntil).toBeNull();
  });

  it("a change that waited asks the share again when its wait ends: a reconnect's restore meanwhile puts it back", () => {
    hub.claim("p1", ["BTCUSDT"]);
    hub.claim("p1", ["ETHUSDT"]);
    expect(hub.getState().waitingUntil).toBe(T0 + 2_000);
    vi.advanceTimersByTime(1_500);
    transport.current?.push({ kind: "reset", reason: "reconnect" });
    vi.advanceTimersByTime(FLUSH_MS);
    const restored = Date.now() - FLUSH_MS;
    vi.advanceTimersByTime(T0 + 2_000 - Date.now());
    // the restore drew on the share: the change goes 2 s after it, not when the first wait ended
    expect(transport.opened).toHaveLength(1);
    expect(hub.getState().waitingUntil).toBeGreaterThan(T0 + 2_000);
    vi.advanceTimersByTime(restored + 2_000 + FLUSH_MS - Date.now());
    expect(transport.opened.map((c) => c.symbols)).toEqual([["BTCUSDT"], ["ETHUSDT"]]);
  });

  it("a reconnect's restore is a draw too (the client re-subscribes the held stream)", () => {
    hub.claim("p1", ["BTCUSDT"]);
    transport.current?.push(snapOf([streamItem(0)]), { kind: "reset", reason: "reconnect" });
    vi.advanceTimersByTime(FLUSH_MS);
    for (let i = 0; i < 2; i += 1) {
      vi.advanceTimersByTime(2_000);
      hub.claim("p1", syms(3, i * 3));
    }
    vi.advanceTimersByTime(2_000);
    hub.claim("p1", syms(3, 30));
    vi.advanceTimersByTime(2_000);
    // three subscriptions and one restore: the fourth change waits for the window
    expect(transport.opened).toHaveLength(3);
    expect(hub.getState().waitingUntil).not.toBeNull();
  });
});

describe("resync_rate_limited: paused, then back off 5 s doubling to 60 s", () => {
  it("a refused sub subscribes nothing: no live symbol, the paused notice, a retry after 5 s", () => {
    hub.claim("p1", ["BTCUSDT"]);
    transport.current?.revoke();
    vi.advanceTimersByTime(FLUSH_MS);
    expect(hub.getState().live.size).toBe(0);
    expect(hub.getState().paused).toMatchObject({ delayMs: 5_000 });
    vi.advanceTimersByTime(5_000);
    expect(transport.opened).toHaveLength(2);
  });

  it("each further refusal doubles the wait, up to 60 s, never in a loop", () => {
    hub.claim("p1", ["BTCUSDT"]);
    const waits: number[] = [];
    for (let i = 0; i < 6; i += 1) {
      transport.current?.revoke();
      vi.advanceTimersByTime(FLUSH_MS);
      waits.push(hub.getState().paused?.delayMs ?? 0);
      vi.advanceTimersByTime(60_000);
    }
    expect(waits).toEqual([5_000, 10_000, 20_000, 40_000, 60_000, 60_000]);
    expect(transport.opened).toHaveLength(7);
  });

  it("a snapshot ends the pause and resets the back-off", () => {
    hub.claim("p1", ["BTCUSDT"]);
    transport.current?.revoke();
    vi.advanceTimersByTime(FLUSH_MS + 5_000);
    transport.current?.push(snapOf([streamItem(0)]));
    vi.advanceTimersByTime(FLUSH_MS);
    expect(hub.getState().paused).toBeNull();
    expect([...hub.getState().live]).toEqual(["BTCUSDT"]);
    transport.current?.revoke();
    vi.advanceTimersByTime(FLUSH_MS);
    expect(hub.getState().paused?.delayMs).toBe(5_000);
  });
});

describe("frames read on animation frames, coalesced into per-symbol atoms a slot at a time (C9; E08-D07 D32)", () => {
  /** Pushes each frame of `replay` at `from` + its `at`, on the fake clock: the first as the snapshot. */
  function play(replay: readonly Timed[], from: number): void {
    replay.forEach(({ at, item }, i) => {
      setTimeout(
        () => transport.current?.push(i === 0 ? snapOf([item]) : deltaOf([item])),
        from + at - Date.now(),
      );
    });
  }

  /** When each frame of `replay` first reached BTCUSDT's store (it, or a later one), less when it arrived. */
  function latencies(replay: readonly Timed[], from: number, paints: readonly Paint[]): number[] {
    return replay.map(({ at, item }) => {
      const paint = paints.find((p) => p.tsMs >= item.ts_ms);
      return (paint?.at ?? Number.POSITIVE_INFINITY) - (from + at);
    });
  }

  interface Paint {
    readonly at: number;
    readonly tsMs: number;
  }
  const listen = (): Paint[] => {
    const paints: Paint[] = [];
    hub.store.subscribe("BTCUSDT", () =>
      paints.push({ at: Date.now(), tsMs: hub.store.get("BTCUSDT")?.values.tsMs ?? Number.NaN }),
    );
    return paints;
  };

  it("a frame after a quiet spell reaches the store on the next animation frame (the leading edge)", () => {
    hub.claim("p1", ["BTCUSDT"]);
    const paints = listen();
    vi.advanceTimersByTime(10);
    transport.current?.push(snapOf([streamItem(0)]));
    vi.advanceTimersByTime(FRAME_MS);
    expect(paints).toHaveLength(1);
    expect((paints[0]?.at ?? 0) - (T0 + 10)).toBeLessThanOrEqual(FRAME_MS);
  });

  it.each([250, 20, 100, 140])(
    "the golden at the server's own pace lands within a frame of each arrival, never drifting: its first delta %i ms after the snapshot",
    (gap) => {
      hub.claim("p1", ["BTCUSDT"]);
      const paints = listen();
      // the recording as the server sends it, four times over (44 frames, 11 s), from 10 ms after the subscription
      // opened; its deltas keep the topic's own 250 ms window, so the first may follow the snapshot at any point of one
      const once = serverPaced(BTC_STREAM);
      const lap = (once.at(-1)?.at ?? 0) + 250;
      const replay = [0, 1, 2, 3].flatMap((n) =>
        once.map(({ at, item }, i) => ({
          at: n === 0 && i === 0 ? 0 : at + n * lap + gap - 250,
          item,
        })),
      );
      const from = T0 + 10;
      play(replay, from);
      vi.advanceTimersByTime((replay.at(-1)?.at ?? 0) + FLUSH_MS + 10);
      // one paint per frame, each within one animation frame of its arrival
      expect(paints).toHaveLength(replay.length);
      paints.forEach((paint, i) => {
        const arrived = from + (replay[i]?.at ?? 0);
        expect(paint.at - arrived).toBeGreaterThanOrEqual(0);
        expect(paint.at - arrived).toBeLessThanOrEqual(FRAME_MS);
      });
    },
  );

  it("a window move's snapshot takes no slot: two moves 2 s apart hold none of the stream's deltas", () => {
    hub.claim("p1", ["BTCUSDT"]);
    const paints = listen();
    // the stream at the server's pace, its first delta 20 ms after the opening snapshot, each a recorded item a window
    // later in time; two moves 2 s apart (the client's share allows them), each snapshot 40 ms after its `sub` and
    // holding the latest item, while the deltas keep the topic's own window
    const itemAt = (k: number): TickerItem => ({
      ...streamItem(k % BTC_STREAM.length),
      ts_ms: streamItem(0).ts_ms + 250 * k,
    });
    const from = T0 + 10;
    const deltas = Array.from({ length: 24 }, (_, k) => ({
      at: from + 20 + 250 * k,
      item: itemAt(k + 1),
    }));
    const latest = (): TickerItem =>
      deltas.filter(({ at }) => at <= Date.now()).at(-1)?.item ?? itemAt(0);
    setTimeout(() => transport.current?.push(snapOf([itemAt(0)])), from - Date.now());
    for (const { at, item } of deltas)
      setTimeout(() => transport.current?.push(deltaOf([item])), at - Date.now());
    for (const [move, other] of [
      [T0 + 2_000, "ETHUSDT"],
      [T0 + 4_000, "SOLUSDT"],
    ] as const) {
      setTimeout(() => hub.claim("p1", ["BTCUSDT", other]), move - Date.now());
      setTimeout(
        () => transport.current?.push(snapOf([latest(), restItem(other)])),
        move + 40 - Date.now(),
      );
    }
    vi.advanceTimersByTime((deltas.at(-1)?.at ?? 0) + FLUSH_MS - Date.now());
    expect(transport.opened).toHaveLength(3);
    const waited = deltas.map(
      ({ at, item }) =>
        (paints.find((p) => p.at >= at && p.tsMs >= item.ts_ms)?.at ?? Number.POSITIVE_INFINITY) -
        at,
    );
    expect(Math.max(...waited)).toBeLessThanOrEqual(FRAME_MS);
  });

  it("a read that throws ends its own animation frame, never the loop: the next frame reads again", () => {
    hub.dispose();
    const frames: (() => void)[] = [];
    hub = createTickerHub(transport, {
      ...SYSTEM_HUB_CLOCK,
      requestFrame: (run) => frames.push(run),
      cancelFrame: () => undefined,
    });
    hub.claim("p1", ["BTCUSDT"]);
    const channel = transport.current;
    if (channel === undefined) throw new Error("no subscription");
    vi.spyOn(channel, "read").mockImplementationOnce(() => {
      throw new Error("a frame the client cannot decode");
    });
    expect(() => frames.shift()?.()).toThrow("a frame the client cannot decode");
    channel.push(snapOf([streamItem(0)]));
    frames.shift()?.();
    expect(hub.store.get("BTCUSDT")?.values.lastPrice).toBe(Number(streamItem(0).last_price));
  });

  it("the recording at its own ~100 ms is coalesced, one paint per slot with one in hand; none waits past its slot", () => {
    hub.claim("p1", ["BTCUSDT", "ETHUSDT"]);
    const paints = listen();
    const eth = vi.fn();
    hub.store.subscribe("ETHUSDT", eth);
    const replay = asRecorded(BTC_STREAM);
    const from = T0 + 10;
    transport.current?.push(snapOf([restItem("ETHUSDT")]));
    play(replay, from);
    vi.advanceTimersByTime((replay.at(-1)?.at ?? 0) + FLUSH_MS + FRAME_MS + 10);
    // the snapshots' paint takes no slot; each later one takes a slot, the slots a frame shorter than the server's
    // 250 ms with one in hand: any k of them span at least k − 1 slots (two in any slot; 4.3 Hz over a run, where a
    // 250 ms grid would hold a stream at the server's own pace whose phase it missed)
    const later = paints.slice(1).map((paint) => paint.at);
    for (let i = 0; i < later.length; i += 1)
      for (let j = i + 1; j < later.length; j += 1)
        expect((later[j] ?? 0) - (later[i] ?? 0)).toBeGreaterThanOrEqual((j - i - 1) * SLOT_MS);
    expect(later.length).toBeLessThan(replay.length - 1); // the ~100 ms is coalesced
    // the trailing edge: no frame waits past its slot and a frame, and the last one lands
    expect(Math.max(...latencies(replay, from, paints))).toBeLessThanOrEqual(SLOT_MS + FRAME_MS);
    expect(hub.store.get("BTCUSDT")?.values.lastPrice).toBe(Number(streamItem(19).last_price));
    expect(eth).toHaveBeenCalledOnce(); // its one snapshot item; the BTC deltas do not wake it
  });

  it("a document that paints no frames (a hidden tab) is still read, once a second", () => {
    hub.dispose();
    hub = createTickerHub(transport, {
      ...SYSTEM_HUB_CLOCK,
      requestFrame: () => 0,
      cancelFrame: () => undefined,
    });
    hub.claim("p1", ["BTCUSDT"]);
    transport.current?.push(snapOf([streamItem(0)]));
    vi.advanceTimersByTime(IDLE_READ_MS - 1);
    expect(hub.store.get("BTCUSDT")).toBeUndefined();
    vi.advanceTimersByTime(1);
    expect(hub.store.get("BTCUSDT")?.values.lastPrice).toBe(Number(streamItem(0).last_price));
  });

  it("a symbol that leaves the live set forgets its value: back in, it initialises with none (E08-D07 D7)", () => {
    hub.claim("p1", ["BTCUSDT"]);
    transport.current?.push(snapOf([streamItem(0)]));
    vi.advanceTimersByTime(FLUSH_MS);
    expect(hub.store.get("BTCUSDT")).toBeDefined();
    hub.claim("p1", ["ETHUSDT"]);
    vi.advanceTimersByTime(2_000);
    expect(hub.store.get("BTCUSDT")).toBeUndefined();
  });

  it("keeps the last fresh time apart from a server-stale item's arrival", () => {
    hub.claim("p1", ["BTCUSDT"]);
    transport.current?.push(snapOf([streamItem(0)]));
    vi.advanceTimersByTime(FLUSH_MS);
    const fresh = hub.store.get("BTCUSDT")?.freshAtMs;
    vi.advanceTimersByTime(5_000);
    transport.current?.push(deltaOf([{ ...streamItem(0), stale: true }]));
    vi.advanceTimersByTime(FLUSH_MS);
    expect(hub.store.get("BTCUSDT")?.freshAtMs).toBe(fresh);
    expect(hub.store.get("BTCUSDT")?.values.serverStale).toBe(true);
  });

  it("records the last data and counts snapshots (Disconnected ends with the snap after a reconnect)", () => {
    hub.claim("p1", ["BTCUSDT"]);
    expect(hub.lastDataMs()).toBeNull();
    transport.current?.push(snapOf([streamItem(0)]));
    vi.advanceTimersByTime(FLUSH_MS);
    // read on the first animation frame after it arrived
    expect(hub.lastDataMs()).toBeGreaterThan(T0);
    expect(hub.lastDataMs()).toBeLessThanOrEqual(T0 + FRAME_MS);
    expect(hub.getState().snaps).toBe(1);
  });
});

describe("teardown", () => {
  it("dispose releases the subscription and leaves no timer", () => {
    hub.claim("p1", ["BTCUSDT"]);
    hub.claim("p1", ["ETHUSDT"]);
    hub.dispose();
    expect(transport.opened.every((c) => c.released)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("releasing every pane stops the frame loop and its idle read", () => {
    hub.claim("p1", ["BTCUSDT"]);
    hub.release("p1");
    expect(vi.getTimerCount()).toBe(0);
  });
});
