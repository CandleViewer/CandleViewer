/** E08-D05 §6.2 "Checking a symbol": its gates, the 300 ms rest, one lookup in flight, the cooldown. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  SYSTEM_CLOCK,
  type Clock,
  type Lookup,
} from "../../../src/features/symbol-search/instrumentIndex";
import {
  toEntry,
  type Instrument,
  type RankContext,
} from "../../../src/features/symbol-search/ranking";
import {
  checkableSymbol,
  createSymbolCheck,
  type SymbolCheck,
} from "../../../src/features/symbol-search/symbolCheck";

type Status = NonNullable<Instrument["status"]>;
const inst = (symbol: string, status: Status = "Trading"): Instrument => ({
  symbol,
  category: "linear",
  status,
  tick_size: "0.1",
  qty_step: "0.001",
});
const reply = (status: number, body: unknown): Promise<Response> =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));
const notFound = () => reply(404, { type: "about:blank", title: "Not found", status: 404 });
/** As `fetch` does on a hung connection: no answer, and a rejection once the signal aborts. */
const hang = (_url: string, init?: RequestInit): Promise<Response> =>
  new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () =>
      reject(new DOMException("Aborted", "AbortError")),
    );
  });
const settle = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
const urls = () => apiFetch.mock.calls.map(([url]) => url);
/** The system clock, holding the microtasks it is given for the test to run. */
const holding = (queued: (() => void)[]): Clock => ({
  ...SYSTEM_CLOCK,
  queueMicrotask: (run) => void queued.push(run),
});

/** The index the check reads: a list in memory, empty unless a test says otherwise. */
let listing: RankContext;
const learn = vi.fn<(answer: Lookup) => void>();
let check: SymbolCheck;
const snap = () => check.getSnapshot();

beforeEach(() => {
  vi.useFakeTimers();
  listing = { phase: "ready", entries: [] };
  check = createSymbolCheck({ getSnapshot: () => listing, learn });
});
afterEach(() => {
  check.stop();
  vi.useRealTimers();
  apiFetch.mockReset();
  learn.mockReset();
});

describe("checkableSymbol", () => {
  it.each([
    ["ab", null],
    ["abc", "ABCUSDT"],
    ["a".repeat(16), `${"A".repeat(16)}USDT`],
    ["a".repeat(17), null],
    ["slu", "SLUUSDT"],
    ["xyzzy", "XYZZYUSDT"],
    ["usdt", null],
    ["abc usdt", "ABCUSDT"],
    ["btc.x", null],
  ])("%j checks %s", (query, symbol) => {
    expect(checkableSymbol(query)).toBe(symbol);
  });
});

describe("the check", () => {
  it.each([
    ["V7", "slu", "SLUUSDT"],
    ["V9", "xyzzy", "XYZZYUSDT"],
  ])(
    "%s %j: after the 300 ms rest one lookup of %s answers 404: not listed",
    async (_v, query, symbol) => {
      apiFetch.mockImplementationOnce(notFound);
      check.request(query);
      expect(snap()).toMatchObject({ phase: "waiting", symbol });
      await settle(299);
      expect(apiFetch).not.toHaveBeenCalled();
      await settle(1);
      expect(urls()).toEqual([`/api/v1/instruments/${symbol}`]);
      expect(snap()).toMatchObject({
        phase: "not_listed",
        symbol,
        checkedAt: Date.now(),
        coolingDown: true,
      });
    },
  );

  it("while the lookup runs the phase is 'checking'", async () => {
    apiFetch.mockImplementationOnce(hang);
    check.request("xyzzy");
    await settle(300);
    expect(snap()).toMatchObject({ phase: "checking", symbol: "XYZZYUSDT" });
  });

  it("V10 'usdt' is never checked", async () => {
    check.request("usdt");
    await settle(1_000);
    expect(apiFetch).not.toHaveBeenCalled();
    expect(snap()).toMatchObject({ phase: "idle", symbol: null });
  });

  const gates: [string, RankContext, string][] = [
    [
      "the query ranks a listed symbol",
      { phase: "ready", entries: [toEntry(inst("BTCUSDT"))] },
      "btc",
    ],
    [
      "the query names a known non-Trading symbol",
      { phase: "ready", entries: [], known: [toEntry(inst("LUNAUSDT", "Closed"))] },
      "luna",
    ],
    ["no list is in memory (loading)", { phase: "loading", entries: [] }, "xyzzy"],
    ["no list is in memory (failed)", { phase: "failed", entries: [] }, "xyzzy"],
  ];
  it.each(gates)("nothing is checked when %s", async (_, index, query) => {
    listing = index;
    check.request(query);
    await settle(1_000);
    expect(apiFetch).not.toHaveBeenCalled();
    expect(snap().phase).toBe("idle");
  });

  it.each([
    ["listed", () => reply(200, inst("NEWUSDT")), "NEWUSDT"],
    ["status", () => reply(200, inst("NEWUSDT", "Closed")), "NEWUSDT"],
    ["unchecked", () => reply(503, { status: 503 }), undefined],
  ])("a %s answer is learnt and becomes the phase", async (kind, answer, instrument) => {
    apiFetch.mockImplementationOnce(answer);
    check.request("new");
    await settle(300);
    expect(learn.mock.calls.map(([a]) => [a.kind, a.symbol])).toEqual([[kind, "NEWUSDT"]]);
    expect([snap().phase, snap().instrument?.symbol]).toEqual([kind, instrument]);
  });

  it("a lookup with no answer is 'unchecked' after 10 s", async () => {
    apiFetch.mockImplementationOnce(hang);
    check.request("xyzzy");
    await settle(300 + 9_999);
    expect(snap().phase).toBe("checking");
    await settle(1);
    expect(snap()).toMatchObject({ phase: "unchecked", coolingDown: true });
  });

  it("one lookup in flight: a newer query aborts it and its late answer is dropped", async () => {
    let land: (res: Response) => void = () => {};
    apiFetch
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (land = resolve)))
      .mockImplementationOnce(notFound);
    check.request("abc");
    await settle(300);
    check.request("abc usdt");
    expect(apiFetch.mock.calls[0]?.[1]?.signal?.aborted).toBe(false);
    check.request("abcd");
    expect(apiFetch.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    await settle(200);
    check.request("abcde");
    await settle(299);
    land(new Response(JSON.stringify(inst("ABCUSDT")), { status: 200 }));
    await settle(1);
    expect(urls()).toEqual(["/api/v1/instruments/ABCUSDT", "/api/v1/instruments/ABCDEUSDT"]);
    expect(snap()).toMatchObject({ phase: "not_listed", symbol: "ABCDEUSDT" });
    expect(learn.mock.calls.map(([a]) => a.symbol)).toEqual(["ABCDEUSDT"]);
  });

  it("a query that ranks again cancels the check", async () => {
    apiFetch.mockImplementationOnce(notFound);
    check.request("xyzzy");
    await settle(300);
    check.request("");
    expect(snap()).toMatchObject({ phase: "idle", symbol: null, instrument: null });
  });

  it("'Check again' is inert while waiting and for 60 s after a check, then checks at once", async () => {
    apiFetch.mockImplementation(notFound);
    check.checkAgain();
    check.request("xyzzy");
    check.checkAgain();
    await settle(300);
    check.checkAgain();
    await settle(59_999);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(snap().coolingDown).toBe(true);
    await settle(1);
    expect(snap().coolingDown).toBe(false);
    check.checkAgain();
    await settle();
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(snap()).toMatchObject({ phase: "not_listed", coolingDown: true });
  });

  it("a throwing subscriber stops neither the check nor the others", async () => {
    check = createSymbolCheck({ getSnapshot: () => listing, learn }, holding([]));
    const told = vi.fn();
    check.subscribe(() => {
      throw new Error("a subscriber's bug");
    });
    check.subscribe(told);
    apiFetch.mockImplementationOnce(notFound);
    check.request("xyzzy");
    await settle(300);
    expect(told).toHaveBeenCalled();
    expect(snap().phase).toBe("not_listed");
  });

  it("a subscriber's error is raised again on its own, never swallowed", () => {
    const queued: (() => void)[] = [];
    check = createSymbolCheck({ getSnapshot: () => listing, learn }, holding(queued));
    const bug = new Error("a subscriber's bug");
    check.subscribe(() => {
      throw bug;
    });
    check.request("xyzzy");
    expect(queued).toHaveLength(1);
    expect(() => queued[0]?.()).toThrow(bug);
  });

  it("an unsubscribed listener is not told", () => {
    const listener = vi.fn();
    check.subscribe(listener)();
    check.request("xyzzy");
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("stop()", () => {
  it("clears the rest and the cooldown, and aborts the lookup in flight, whose answer is dropped", async () => {
    let land: (res: Response) => void = () => {};
    apiFetch
      .mockImplementationOnce(notFound)
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (land = resolve)));
    check.request("xyzzy");
    await settle(300);
    check.request("abcd");
    await settle(300);
    const listener = vi.fn();
    check.subscribe(listener);
    check.stop();
    expect(vi.getTimerCount()).toBe(0);
    expect(apiFetch.mock.calls[1]?.[1]?.signal?.aborted).toBe(true);
    land(new Response(null, { status: 404 }));
    await settle(60_000);
    expect(listener).not.toHaveBeenCalled();
  });

  it("is final: request() and checkAgain() after it send nothing and arm no timer", async () => {
    apiFetch.mockImplementation(notFound);
    check.request("xyzzy");
    await settle(60_300);
    check.stop();
    check.request("abcde");
    check.checkAgain();
    expect(vi.getTimerCount()).toBe(0);
    await settle(1_000);
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });
});
