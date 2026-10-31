/**
 * E08-S08 (#4702): the ticker client. One batched `ticker` subscription per connection, at most 40 symbols shared by
 * every pane (E08-D07 D6, D27; 23 §6.1, §16.2); the client's share of the rebuild budget; the `resync_rate_limited`
 * back-off; 4 Hz coalescing into per-symbol atoms. Fake clock and a fake transport; the frames are the derived golden.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FLUSH_MS,
  MAX_LIVE_SYMBOLS,
  createTickerHub,
  type TickerHub,
} from "../../../src/features/watchlist/ticker/tickerHub";
import { FakeTransport, deltaOf, restItem, snapOf, streamItem, BTC_STREAM } from "./support";

const T0 = Date.UTC(2026, 9, 31, 10, 0, 0);
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
    for (let i = 0; i < 12; i += 1) {
      hub.claim("p1", syms(10, i * 10));
      vi.advanceTimersByTime(500);
    }
    vi.advanceTimersByTime(120_000);
    const starts = transport.opened.map((c) => c.openedAt);
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

describe("4 Hz coalescing into per-symbol atoms", () => {
  it("the recorded stream (20 frames, 100 ms apart) reaches a symbol's listeners at most once per 250 ms", () => {
    hub.claim("p1", ["BTCUSDT", "ETHUSDT"]);
    const heard: number[] = [];
    const eth = vi.fn();
    hub.store.subscribe("BTCUSDT", () => heard.push(Date.now()));
    hub.store.subscribe("ETHUSDT", eth);
    transport.current?.push(snapOf([streamItem(0), restItem("ETHUSDT")]));
    for (let i = 1; i < BTC_STREAM.length; i += 1) {
      vi.advanceTimersByTime(100);
      transport.current?.push(deltaOf([streamItem(i)]));
    }
    vi.advanceTimersByTime(FLUSH_MS);
    for (let i = 1; i < heard.length; i += 1) {
      expect((heard[i] ?? 0) - (heard[i - 1] ?? 0)).toBeGreaterThanOrEqual(FLUSH_MS);
    }
    expect(heard.length).toBeLessThanOrEqual(Math.ceil((1_900 + FLUSH_MS) / FLUSH_MS));
    expect(hub.store.get("BTCUSDT")?.values.lastPrice).toBe(Number(streamItem(19).last_price));
    expect(eth).toHaveBeenCalledOnce(); // its one snapshot item; the BTC deltas do not wake it
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
    expect(hub.lastDataMs()).toBe(T0 + FLUSH_MS);
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

  it("releasing every pane stops the 4 Hz read loop", () => {
    hub.claim("p1", ["BTCUSDT"]);
    hub.release("p1");
    expect(vi.getTimerCount()).toBe(0);
  });
});
