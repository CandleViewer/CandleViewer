/** E08-S09: the client instrument index and the symbol lookup (E08-D05 §3, §6.2) on fake timers. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  SYSTEM_CLOCK,
  createInstrumentIndex,
  lookupSymbol,
  type Clock,
  type InstrumentIndex,
  type Lookup,
} from "../../../src/features/symbol-search/instrumentIndex";
import type { Instrument } from "../../../src/features/symbol-search/ranking";

const LIST = "/api/v1/instruments?status=Trading&limit=500";
const HOUR = 3_600_000;
type Status = NonNullable<Instrument["status"]>;
const inst = (symbol: string, status: Status = "Trading"): Instrument => ({
  symbol,
  category: "linear",
  status,
  tick_size: "0.1",
  qty_step: "0.001",
});
const LUNA = inst("LUNAUSDT", "Closed");
const reply = (status: number, body: unknown, headers: Record<string, string> = {}): Response =>
  new Response(JSON.stringify(body), { status, headers });
const page = (items: unknown[], next: string | null = null, meta: object = {}): Response =>
  reply(200, {
    items,
    meta: {
      next_cursor: next,
      has_more: next !== null,
      count: items.length,
      cache_age_s: 120,
      stale_since: null,
      ...meta,
    },
  });
const listed = (...symbols: string[]): Response => page(symbols.map((s) => inst(s)));
/** `_problem` of services/api/candleviewer/api/instruments.py, plus the contract's optional fields. */
const problem = (status: number, headers: Record<string, string> = {}, extra: object = {}) =>
  reply(status, { type: "about:blank", title: "x", status, ...extra }, headers);
const never = (): Promise<Response> => new Promise<Response>(() => {});
/** As `fetch` does on a hung connection: no answer, and a rejection once the signal aborts. */
const hang = (_url: string, init?: RequestInit): Promise<Response> =>
  new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () =>
      reject(new DOMException("Aborted", "AbortError")),
    );
  });

let index: InstrumentIndex;
const snap = () => index.getSnapshot();
const symbols = () => snap().entries.map((e) => e.symbol);
const flush = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
const signalOf = (call: number) => apiFetch.mock.calls[call]?.[1]?.signal;
/** The system clock, holding the microtasks it is given for the test to run. */
const holding = (queued: (() => void)[]): Clock => ({
  ...SYSTEM_CLOCK,
  queueMicrotask: (run) => void queued.push(run),
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(Date.UTC(2026, 9, 29, 13, 2));
  index = createInstrumentIndex();
});
afterEach(() => {
  index.stop();
  vi.useRealTimers();
  apiFetch.mockReset();
});

describe("loading the listing", () => {
  it("follows next_cursor to the last page", async () => {
    apiFetch
      .mockResolvedValueOnce(page([inst("BTCUSDT")], "c/1"))
      .mockResolvedValueOnce(listed("ETHUSDT"));
    index.start();
    await flush();
    expect(apiFetch.mock.calls.map(([url]) => url)).toEqual([LIST, `${LIST}&cursor=c%2F1`]);
    expect(symbols()).toEqual(["BTCUSDT", "ETHUSDT"]);
  });

  it("start() twice reads once", async () => {
    apiFetch.mockResolvedValueOnce(listed("BTCUSDT"));
    index.start();
    index.start();
    await flush();
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("keeps the Trading rows, normalised once, and the list's freshness", async () => {
    apiFetch.mockResolvedValueOnce(
      page([inst("1000PEPEUSDT"), LUNA], null, {
        cache_age_s: 42,
        stale_since: "2026-10-29T00:00:00Z",
      }),
    );
    index.start();
    expect(snap()).toMatchObject({ phase: "loading", retryAt: null, failure: null });
    await flush();
    expect(snap()).toMatchObject({
      phase: "ready",
      loadedAt: Date.now(),
      cacheAgeS: 42,
      staleSince: "2026-10-29T00:00:00Z",
    });
    expect(snap().entries.map((e) => [e.symbol, e.stripped])).toEqual([["1000PEPEUSDT", "PEPE"]]);
  });

  it("drops the rows its guard refuses, and the list still lands", async () => {
    apiFetch.mockResolvedValueOnce(
      page([
        inst("BTCUSDT"),
        { symbol: "bad", status: "Trading" },
        { ...inst("ETHUSDT"), base_coin: 7 },
        { ...inst("SOLUSDT"), status: 5 },
      ]),
    );
    index.start();
    await flush();
    expect(snap().phase).toBe("ready");
    expect(symbols()).toEqual(["BTCUSDT"]);
  });

  it("keeps one row per symbol when pages repeat one", async () => {
    apiFetch
      .mockResolvedValueOnce(page([inst("BTCUSDT"), inst("ETHUSDT")], "c1"))
      .mockResolvedValueOnce(listed("ETHUSDT", "SOLUSDT"));
    index.start();
    await flush();
    expect(symbols()).toEqual(["BTCUSDT", "ETHUSDT", "SOLUSDT"]);
  });

  it("a 503 is 'loading': next tries after 2, 4, 8, 16 and 30 s, then 'failed' after 60 s of 503s", async () => {
    apiFetch.mockImplementation(() => Promise.resolve(problem(503)));
    index.start();
    await flush();
    const waits: number[] = [];
    for (let i = 0; i < 5; i += 1) {
      expect(snap().phase).toBe("loading");
      const wait = (snap().retryAt ?? 0) - Date.now();
      waits.push(wait / 1000);
      await flush(wait);
    }
    expect(waits).toEqual([2, 4, 8, 16, 30]);
    expect(apiFetch).toHaveBeenCalledTimes(6);
    expect(snap()).toMatchObject({
      phase: "failed",
      failure: { cause: "unavailable" },
      retryAt: Date.now() + 30_000,
    });
  });

  it("a restart begins the 503 ladder again at 2 s", async () => {
    apiFetch.mockImplementation(() => Promise.resolve(problem(503)));
    index.start();
    await flush(2_000);
    index.stop();
    index.start();
    await flush();
    expect((snap().retryAt ?? 0) - Date.now()).toBe(2_000);
  });

  it.each([
    ["the Retry-After header", { "Retry-After": "5" }, {}, 5],
    ["the problem's retry_after_seconds", {}, { retry_after_seconds: 7 }, 7],
    ["the header over the body", { "Retry-After": "5" }, { retry_after_seconds: 7 }, 5],
    ["600 s, honoured", { "Retry-After": "600" }, {}, 600],
    ["3,601 s, capped at an hour", { "Retry-After": "3601" }, {}, 3600],
    ["0 s, raised to 1 s", { "Retry-After": "0" }, {}, 1],
    ["a null retry_after_seconds, as not sent", {}, { retry_after_seconds: null }, 2],
    ["an HTTP date, as not sent", { "Retry-After": "Thu, 29 Oct 2026 13:03:00 GMT" }, {}, 2],
    ["1.5 s, as not sent", { "Retry-After": "1.5" }, {}, 2],
  ])("a 503 with %s waits that long", async (_, headers, extra, seconds) => {
    apiFetch.mockResolvedValueOnce(problem(503, headers, extra));
    index.start();
    await flush();
    expect(snap()).toMatchObject({ phase: "loading", retryAt: Date.now() + seconds * 1000 });
  });

  it("a 503 asking for 45 s is tried again at 45 s, not before", async () => {
    apiFetch.mockImplementation(() => Promise.resolve(problem(503, { "Retry-After": "45" })));
    index.start();
    await flush(44_999);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    await flush(1);
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });

  it("in 'failed', the server's Retry-After sets the next try", async () => {
    apiFetch
      .mockResolvedValueOnce(problem(503, { "Retry-After": "61" }))
      .mockResolvedValueOnce(problem(503, { "Retry-After": "45" }));
    index.start();
    await flush(61_000);
    expect(snap()).toMatchObject({
      phase: "failed",
      failure: { cause: "unavailable" },
      retryAt: Date.now() + 45_000,
    });
  });

  it("in 'failed', a Retry-After under 30 s keeps the 30 s", async () => {
    apiFetch.mockResolvedValueOnce(problem(500, { "Retry-After": "10" }));
    index.start();
    await flush();
    expect(snap()).toMatchObject({ phase: "failed", retryAt: Date.now() + 30_000 });
  });

  it("503s for 60 s are 'failed' on time, while a long Retry-After keeps its retry", async () => {
    apiFetch.mockImplementation(() => Promise.resolve(problem(503, { "Retry-After": "3600" })));
    index.start();
    await flush();
    const retryAt = Date.now() + HOUR;
    await flush(59_999);
    expect(snap()).toMatchObject({ phase: "loading", retryAt });
    await flush(1);
    expect(snap()).toMatchObject({ phase: "failed", failure: { cause: "unavailable" }, retryAt });
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("a short Retry-After due past the 60 s mark waits as 'failed' does: 30 s", async () => {
    apiFetch
      .mockResolvedValueOnce(problem(503, { "Retry-After": "50" }))
      .mockResolvedValueOnce(problem(503, { "Retry-After": "20" }));
    index.start();
    await flush(50_000);
    expect(snap()).toMatchObject({ phase: "loading", retryAt: Date.now() + 30_000 });
  });

  it("the 60 s run from the first 503, not from the first GET", async () => {
    apiFetch.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          setTimeout(() => resolve(problem(503, { "Retry-After": "3600" })), 5_000);
        }),
    );
    index.start();
    await flush(64_999);
    expect(snap().phase).toBe("loading");
    await flush(1);
    expect(snap().phase).toBe("failed");
  });

  it("the retry a long Retry-After asked for still comes at its time", async () => {
    apiFetch.mockImplementation(() => Promise.resolve(problem(503, { "Retry-After": "3600" })));
    index.start();
    await flush(HOUR - 1);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    await flush(1);
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });

  it("stop() while a long Retry-After is pending leaves no timer", async () => {
    apiFetch.mockResolvedValueOnce(problem(503, { "Retry-After": "3600" }));
    index.start();
    await flush();
    index.stop();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("the 503s failure keeps the problem's instance", async () => {
    apiFetch.mockImplementation(() =>
      Promise.resolve(problem(503, {}, { instance: "urn:cv:req:2" })),
    );
    index.start();
    await flush(60_000);
    expect(snap().failure).toEqual({ cause: "unavailable", instance: "urn:cv:req:2" });
  });

  it.each([
    ["a network error", () => Promise.reject(new TypeError("offline")), { cause: "network" }],
    [
      "a 500",
      () => Promise.resolve(problem(500, {}, { instance: "urn:cv:req:1" })),
      { cause: "http", status: 500, instance: "urn:cv:req:1" },
    ],
    ["a 403", () => Promise.resolve(problem(403)), { cause: "http", status: 403, instance: null }],
    [
      "a 200 without items",
      () => Promise.resolve(reply(200, { meta: {} })),
      { cause: "http", status: 200, instance: null },
    ],
  ])("%s is 'failed' at once, with the next try in 30 s", async (_, answer, failure) => {
    apiFetch.mockImplementationOnce(answer);
    index.start();
    await flush();
    expect(snap()).toMatchObject({ phase: "failed", failure, retryAt: Date.now() + 30_000 });
  });

  it("'failed' tries again after 30 s, and a list makes it 'ready'", async () => {
    apiFetch
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(listed("BTCUSDT"));
    index.start();
    await flush(29_999);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    await flush(1);
    expect(snap()).toMatchObject({ phase: "ready", failure: null, retryAt: null });
  });

  it("a first read with no answer fails after 10 s, as a network failure", async () => {
    apiFetch.mockImplementationOnce(hang);
    index.start();
    await flush(9_999);
    expect(snap()).toMatchObject({ phase: "loading", failure: null });
    await flush(1);
    expect(snap()).toMatchObject({
      phase: "failed",
      failure: { cause: "network" },
      retryAt: Date.now() + 30_000,
    });
  });

  it("the first load is not 'refreshing', however long it takes", async () => {
    apiFetch.mockImplementationOnce(hang);
    index.start();
    await flush(5_000);
    expect(snap()).toMatchObject({ phase: "loading", refreshing: false });
  });

  it("a retry while 'failed' is not 'refreshing'", async () => {
    apiFetch.mockRejectedValueOnce(new TypeError("offline")).mockImplementationOnce(hang);
    index.start();
    await flush(31_000);
    expect(snap()).toMatchObject({ phase: "failed", refreshing: false });
  });

  it("getSnapshot() is one object until something changes", async () => {
    const before = index.getSnapshot();
    expect(index.getSnapshot()).toBe(before);
    apiFetch.mockResolvedValueOnce(listed("BTCUSDT"));
    index.start();
    await flush();
    expect(index.getSnapshot()).not.toBe(before);
    expect(index.getSnapshot()).toBe(index.getSnapshot());
  });

  it("a throwing subscriber stops neither the others nor the hourly re-read", async () => {
    index = createInstrumentIndex(holding([]));
    const told = vi.fn();
    index.subscribe(() => {
      throw new Error("a subscriber's bug");
    });
    index.subscribe(told);
    apiFetch.mockResolvedValueOnce(listed("BTCUSDT")).mockResolvedValueOnce(listed("ETHUSDT"));
    index.start();
    await flush(HOUR);
    expect(told).toHaveBeenCalled();
    expect(symbols()).toEqual(["ETHUSDT"]);
  });

  it("a subscriber's error is raised again on its own, never swallowed", async () => {
    const queued: (() => void)[] = [];
    index = createInstrumentIndex(holding(queued));
    const bug = new Error("a subscriber's bug");
    index.subscribe(() => {
      throw bug;
    });
    apiFetch.mockResolvedValueOnce(listed("BTCUSDT"));
    index.start();
    await flush();
    expect(queued).toHaveLength(1);
    expect(() => queued[0]?.()).toThrow(bug);
  });
});

describe("re-reads", () => {
  it("re-reads hourly; past 1 s it is 'refreshing' and the old list stays until the new one lands", async () => {
    let land: (res: Response) => void = () => {};
    apiFetch
      .mockResolvedValueOnce(listed("BTCUSDT"))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (land = resolve)));
    index.start();
    await flush();
    await flush(HOUR + 999);
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(snap().refreshing).toBe(false);
    await flush(1);
    expect(snap()).toMatchObject({ phase: "ready", refreshing: true });
    expect(symbols()).toEqual(["BTCUSDT"]);
    land(listed("BTCUSDT", "ETHUSDT"));
    await flush();
    expect(snap().refreshing).toBe(false);
    expect(symbols()).toEqual(["BTCUSDT", "ETHUSDT"]);
  });

  it("a failed re-read keeps the list and tries again in an hour", async () => {
    apiFetch
      .mockResolvedValueOnce(listed("BTCUSDT"))
      .mockResolvedValueOnce(problem(503))
      .mockResolvedValueOnce(listed("ETHUSDT"));
    index.start();
    await flush(HOUR);
    expect(snap()).toMatchObject({ phase: "ready", failure: null, refreshing: false });
    expect(symbols()).toEqual(["BTCUSDT"]);
    await flush(HOUR);
    expect(symbols()).toEqual(["ETHUSDT"]);
  });

  it("a re-read with no answer ends after 10 s: the list stays, the next re-read is an hour later", async () => {
    apiFetch
      .mockResolvedValueOnce(listed("BTCUSDT"))
      .mockImplementationOnce(hang)
      .mockResolvedValueOnce(listed("ETHUSDT"));
    index.start();
    await flush(HOUR + 10_000);
    expect(snap()).toMatchObject({ phase: "ready", refreshing: false, failure: null });
    expect(symbols()).toEqual(["BTCUSDT"]);
    await flush(HOUR);
    expect(symbols()).toEqual(["ETHUSDT"]);
  });

  it("reread() (an instrument_revision) aborts the read in flight and reads again now", async () => {
    apiFetch.mockImplementationOnce(never).mockResolvedValueOnce(listed("SOLUSDT"));
    index.start();
    index.reread();
    await flush();
    expect(signalOf(0)?.aborted).toBe(true);
    expect(symbols()).toEqual(["SOLUSDT"]);
  });

  it("reread() before start() reads nothing", () => {
    index.reread();
    expect(apiFetch).not.toHaveBeenCalled();
  });
});

describe("lookupSymbol and learn()", () => {
  it.each([
    ["a Trading answer is listed", () => Promise.resolve(reply(200, inst("NEWUSDT"))), "listed"],
    [
      "another status is the status rule",
      () => Promise.resolve(reply(200, inst("NEWUSDT", "Closed"))),
      "status",
    ],
    ["a 404 is not listed", () => Promise.resolve(problem(404)), "not_listed"],
    ["a 503 is unchecked", () => Promise.resolve(problem(503)), "unchecked"],
    [
      "another symbol's answer is unchecked",
      () => Promise.resolve(reply(200, inst("OLDUSDT"))),
      "unchecked",
    ],
    [
      "a malformed answer is unchecked",
      () => Promise.resolve(reply(200, { ...inst("NEWUSDT"), base_coin: 7 })),
      "unchecked",
    ],
    [
      "a non-string status is unchecked",
      () => Promise.resolve(reply(200, { ...inst("NEWUSDT"), status: 5 })),
      "unchecked",
    ],
    ["a network error is unchecked", () => Promise.reject(new TypeError("offline")), "unchecked"],
  ])("GET /instruments/{symbol}: %s", async (_, answer, kind) => {
    apiFetch.mockImplementationOnce(answer);
    const lookup = lookupSymbol("NEWUSDT", new AbortController().signal);
    await flush();
    expect(await lookup).toMatchObject({ kind, symbol: "NEWUSDT" });
    expect(apiFetch.mock.calls[0]?.[0]).toBe("/api/v1/instruments/NEWUSDT");
  });

  it("OPUSDT, two characters before USDT, is sent", async () => {
    apiFetch.mockResolvedValueOnce(problem(404));
    const lookup = lookupSymbol("OPUSDT", new AbortController().signal);
    await flush();
    expect(await lookup).toEqual({ kind: "not_listed", symbol: "OPUSDT" });
    expect(apiFetch.mock.calls[0]?.[0]).toBe("/api/v1/instruments/OPUSDT");
  });

  it.each(["AUSDT", "btcusdt", "ABUSDT/../x", "A".repeat(17) + "USDT"])(
    "%j is never sent",
    async (symbol) => {
      expect(await lookupSymbol(symbol, new AbortController().signal)).toEqual({
        kind: "unchecked",
        symbol,
      });
      expect(apiFetch).not.toHaveBeenCalled();
    },
  );

  it("an aborted lookup sends nothing", async () => {
    const abort = new AbortController();
    abort.abort();
    expect(await lookupSymbol("NEWUSDT", abort.signal)).toEqual({
      kind: "unchecked",
      symbol: "NEWUSDT",
    });
    expect(apiFetch).not.toHaveBeenCalled();
  });

  const routes: [string, Lookup, string[], string[], string[]][] = [
    [
      "listed joins the list",
      { kind: "listed", symbol: "NEWUSDT", instrument: inst("NEWUSDT") },
      ["NEWUSDT"],
      [],
      [],
    ],
    [
      "status joins the non-Trading cache",
      { kind: "status", symbol: "LUNAUSDT", instrument: LUNA },
      [],
      ["LUNAUSDT"],
      [],
    ],
    [
      "not_listed joins the 404 cache",
      { kind: "not_listed", symbol: "OLDUSDT" },
      [],
      [],
      ["OLDUSDT"],
    ],
    ["unchecked changes nothing", { kind: "unchecked", symbol: "OLDUSDT" }, [], [], []],
  ];
  it.each(routes)("learn(): %s", (_, answer, entries, known, unlisted) => {
    index.learn(answer);
    expect([symbols(), snap().known.map((e) => e.symbol), snap().unlisted]).toEqual([
      entries,
      known,
      unlisted,
    ]);
  });

  it("learn(): a newer answer replaces the cached one", () => {
    index.learn({ kind: "status", symbol: "LUNAUSDT", instrument: LUNA });
    index.learn({ kind: "status", symbol: "LUNAUSDT", instrument: inst("LUNAUSDT", "Delivering") });
    expect(snap().known.map((e) => e.instrument.status)).toEqual(["Delivering"]);
    index.learn({ kind: "listed", symbol: "LUNAUSDT", instrument: inst("LUNAUSDT") });
    expect([symbols(), snap().known]).toEqual([["LUNAUSDT"], []]);
  });

  it("a list that holds a cached symbol takes it out of the caches", async () => {
    index.learn({ kind: "status", symbol: "LUNAUSDT", instrument: LUNA });
    index.learn({ kind: "not_listed", symbol: "OLDUSDT" });
    apiFetch.mockResolvedValueOnce(listed("LUNAUSDT", "OLDUSDT"));
    index.start();
    await flush();
    expect([snap().known, snap().unlisted]).toEqual([[], []]);
  });

  it("an unsubscribed listener is not told", () => {
    const listener = vi.fn();
    index.subscribe(listener)();
    index.learn({ kind: "not_listed", symbol: "OLDUSDT" });
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("stop()", () => {
  it("with the hourly re-read pending, stop() leaves no timer and reads no more", async () => {
    apiFetch.mockResolvedValueOnce(listed("BTCUSDT"));
    index.start();
    await flush();
    index.stop();
    expect(vi.getTimerCount()).toBe(0);
    await flush(2 * HOUR);
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("mid-read, stop() aborts the read and its timers, and publishes nothing after", async () => {
    let land: (res: Response) => void = () => {};
    apiFetch
      .mockResolvedValueOnce(listed("BTCUSDT"))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (land = resolve)));
    index.start();
    await flush(HOUR);
    const listener = vi.fn();
    index.subscribe(listener);
    index.stop();
    expect(vi.getTimerCount()).toBe(0);
    expect(signalOf(1)?.aborted).toBe(true);
    land(listed("ETHUSDT"));
    await flush(2 * HOUR);
    expect(listener).not.toHaveBeenCalled();
    expect(symbols()).toEqual(["BTCUSDT"]);
  });
});
