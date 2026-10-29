/** E08-S09: the one ranking rule (E08-D05 §4), its worked vectors V1–V11 and its edges. Pure: no fetch. */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  normaliseQuery,
  rankSymbols,
  toEntry,
  type Instrument,
  type RankContext,
} from "../../../src/features/symbol-search/ranking";

type Status = NonNullable<Instrument["status"]>;
const inst = (symbol: string, status: Status = "Trading"): Instrument => ({
  symbol,
  category: "linear",
  status,
  tick_size: "0.1",
  qty_step: "0.001",
});

// D05 §4's set: the four fixture symbols (packages/fixtures/bybit/2026-10-05/rest/instruments_after.json)
// plus its illustrative ETHFIUSDT, 1000PEPEUSDT and 1INCHUSDT. Recent = ETHUSDT, LUNAUSDT; Favourite = SOLUSDT.
const LISTED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ETHFIUSDT", "1000PEPEUSDT", "1INCHUSDT"].map(
  (s) => inst(s),
);
const LUNA = inst("LUNAUSDT", "Closed");
const CTX: RankContext = {
  phase: "ready",
  entries: LISTED.map(toEntry),
  known: [toEntry(LUNA)],
  recent: ["ETHUSDT", "LUNAUSDT"],
  favourites: ["SOLUSDT"],
};

/** Synthetic Trading symbols (made up, not market data). */
const synthetic = (
  symbols: string[],
  extra: Omit<RankContext, "phase" | "entries"> = {},
): RankContext => ({ phase: "ready", entries: symbols.map((s) => toEntry(inst(s))), ...extra });
const ranked = (query: string, ctx: RankContext = CTX) => {
  const result = rankSymbols(query, ctx);
  return result.kind === "results" ? result.rows : [];
};
const order = (query: string, ctx: RankContext = CTX): string[] | string => {
  const result = rankSymbols(query, ctx);
  if (result.kind !== "results") return result.kind;
  return result.rows.map((row) => `${row.instrument.symbol} T${row.tier}`);
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("E08-D05 §4 worked vectors", () => {
  it.each([
    ["V1", "btc", ["BTCUSDT T1"]],
    ["V2", "eth", ["ETHUSDT T1", "ETHFIUSDT T2"]],
    ["V3", "btc/usdt", ["BTCUSDT T1"]],
    ["V4", "pepe", ["1000PEPEUSDT T1"]],
    ["V5", "inch", ["1INCHUSDT T4"]],
    ["V6", "sol", ["SOLUSDT T1"]],
    ["V7", "slu", "none"],
    ["V9", "xyzzy", "none"],
    ["V10", "usdt", "none"],
  ])("%s %j ranks %j", (_vector, query, expected) => {
    expect(order(query)).toEqual(expected);
  });

  it("V2 tags ETHUSDT recent ↺, and ETHFIUSDT nothing", () => {
    expect(ranked("eth").map((r) => [r.recent, r.favourite])).toEqual([
      [true, false],
      [false, false],
    ]);
  });

  it("V6 tags SOLUSDT favourite ★", () => {
    expect(ranked("sol").map((r) => [r.recent, r.favourite])).toEqual([[false, true]]);
  });

  it.each(["luna", "lunausdt"])("V8 %j ranks nothing: the status rule names LUNAUSDT", (query) => {
    expect(rankSymbols(query, CTX)).toEqual({ kind: "status", instrument: LUNA });
  });

  it("V8b: ranked Trading rows win over the status rule ('luna' with LUNA2USDT listed)", () => {
    const ctx: RankContext = { ...CTX, entries: [...CTX.entries, toEntry(inst("LUNA2USDT"))] };
    expect(order("luna", ctx)).toEqual(["LUNA2USDT T2"]);
  });

  it("V8c: 'names' is an exact match on symbol, base or stripped base ('lun' is none)", () => {
    expect(rankSymbols("lun", CTX)).toEqual({ kind: "none" });
  });

  it("V11 the empty query: Recent, then Favourites; the delisted LUNAUSDT is not openable", () => {
    expect(rankSymbols(" ", CTX)).toEqual({
      kind: "idle",
      recent: [
        { symbol: "ETHUSDT", instrument: LISTED[1], openable: true },
        { symbol: "LUNAUSDT", instrument: LUNA, openable: false },
      ],
      favourites: [{ symbol: "SOLUSDT", instrument: LISTED[2], openable: true }],
      moreFavourites: 0,
    });
  });

  it("the idle groups show 8 recents and 8 favourites, and count the other favourites", () => {
    const symbols = Array.from({ length: 20 }, (_, i) => `F${String(i).padStart(2, "0")}USDT`);
    const result = rankSymbols(
      "",
      synthetic(symbols, { recent: symbols.slice(0, 9), favourites: symbols }),
    );
    expect(
      result.kind === "idle" && [
        result.recent.length,
        result.favourites.length,
        result.moreFavourites,
      ],
    ).toEqual([8, 8, 12]);
  });

  it.each([
    ["loading", "loading"],
    ["failed", "failed"],
    ["ready", "none"],
  ] as const)(
    "'xyzzy' on an empty list while %s is %j: 'none' needs a list in memory",
    (phase, kind) => {
      expect(rankSymbols("xyzzy", { phase, entries: [] })).toEqual({ kind });
    },
  );
});

describe("normalisation", () => {
  it.each([
    [" btc/usdt ", "BTCUSDT"],
    ["e t-h_", "ETH"],
    ["Btc\tUsdt", "BTCUSDT"],
    ["x".repeat(40), "X".repeat(32)],
  ])("the query %j reads %j", (raw, expected) => {
    expect(normaliseQuery(raw)).toBe(expected);
  });

  it.each([
    ["1000PEPEUSDT", "1000PEPE", "PEPE"],
    ["1000000MOGUSDT", "1000000MOG", "MOG"],
    ["10000000XUSDT", "10000000X", "10000000X"],
    ["1INCHUSDT", "1INCH", "1INCH"],
  ])("%s: base %s, stripped %s", (symbol, base, stripped) => {
    expect(toEntry(inst(symbol))).toMatchObject({ symbol, base, stripped });
  });

  it.each(["PEPE", "1000PEPE"])("base_coin %s gives the same fields (D05 §4)", (coin) => {
    expect(toEntry({ ...inst("1000PEPEUSDT"), base_coin: coin })).toMatchObject({
      base: "1000PEPE",
      stripped: "PEPE",
    });
  });

  it("the quote is never matched", () => {
    expect(order("usd")).toBe("none");
  });

  it("a subsequence needs three characters", () => {
    expect(order("ac", synthetic(["ABCUSDT"]))).toBe("none");
  });
});

describe("tiers, tie-breaks, the cap and the match ranges", () => {
  it("ranks T1 to T5: T4 by earlier position, T5 by shorter span then earlier start, before any tie-break", () => {
    const set = synthetic(
      [
        "AXBXCUSDT",
        "XYABCUSDT",
        "ZAXBCUSDT",
        "1000ABCXUSDT",
        "XABCUSDT",
        "ABCDUSDT",
        "AXBCZUSDT",
        "ABCUSDT",
      ],
      { favourites: ["AXBXCUSDT"], recent: ["ZAXBCUSDT", "XYABCUSDT"] },
    );
    expect(order("abc", set)).toEqual([
      "ABCUSDT T1",
      "ABCDUSDT T2",
      "1000ABCXUSDT T3",
      "XABCUSDT T4",
      "XYABCUSDT T4",
      "AXBCZUSDT T5",
      "ZAXBCUSDT T5",
      "AXBXCUSDT T5",
    ]);
  });

  it("breaks ties by favourite, then recent (newer first), then symbol in ASCII order", () => {
    const set = synthetic(["ABCAUSDT", "ABCBUSDT", "ABCCUSDT", "ABCDUSDT", "ABCEUSDT"], {
      favourites: ["ABCEUSDT"],
      recent: ["ABCCUSDT", "ABCBUSDT"],
    });
    expect(order("abc", set)).toEqual([
      "ABCEUSDT T2",
      "ABCCUSDT T2",
      "ABCBUSDT T2",
      "ABCAUSDT T2",
      "ABCDUSDT T2",
    ]);
  });

  it("ranks at most 50 rows and reports the total, for 'Showing 50 of 213'", () => {
    const many = synthetic(
      Array.from({ length: 213 }, (_, i) => `A${String(i).padStart(3, "0")}USDT`),
    );
    const result = rankSymbols("a", many);
    expect(result.kind === "results" && [result.rows.length, result.total]).toEqual([50, 213]);
    expect(ranked("a", many)[0]?.instrument.symbol).toBe("A000USDT");
  });

  it.each([
    ["btcusdt", "BTCUSDT", [[0, 7]]],
    ["1000pepe", "1000PEPEUSDT", [[0, 8]]],
    ["pepe", "1000PEPEUSDT", [[4, 8]]],
    ["eth", "ETHFIUSDT", [[0, 3]]],
    ["pep", "1000PEPEUSDT", [[4, 7]]],
    ["inch", "1INCHUSDT", [[1, 5]]],
    [
      "ppe",
      "1000PEPEUSDT",
      [
        [4, 5],
        [6, 8],
      ],
    ],
  ])("%j bolds %s at %j", (query, symbol, ranges) => {
    expect(ranked(query).find((r) => r.instrument.symbol === symbol)?.ranges).toEqual(ranges);
  });

  it.each([
    [
      "the shortest window, not the first",
      "AXXBXAYBCUSDT",
      [
        [5, 6],
        [7, 9],
      ],
    ],
    [
      "on equal spans, the earlier start",
      "AXBCAXBCUSDT",
      [
        [0, 1],
        [2, 4],
      ],
    ],
  ])("a T5 match takes %s", (_, symbol, ranges) => {
    expect(ranked("abc", synthetic([symbol]))[0]?.ranges).toEqual(ranges);
  });

  it("ranks a synthetic 500-instrument list locally, with no request", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const set = synthetic([...Array.from({ length: 499 }, (_, i) => `SYN${i}BTCUSDT`), "BTCUSDT"]);
    const result = rankSymbols("btc", set);
    expect(result.kind === "results" && [result.rows[0]?.instrument.symbol, result.total]).toEqual([
      "BTCUSDT",
      500,
    ]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
