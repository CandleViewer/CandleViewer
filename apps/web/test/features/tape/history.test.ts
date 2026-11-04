// E22-S01 (#714) PR-B: REST `/market/trades` pages (`22` getTrades): the shape check of a
// `PublicTrade`, and the one-page fetch the tape uses for missed prints and history (BQ-214).
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  TRADES_PAGE_LIMIT,
  fetchTradesPage,
  parsePublicTrade,
} from "../../../src/features/tape/model/history";
import {
  FLAG_BIG,
  FLAG_BLOCK,
  FLAG_LIQUIDATION,
  SIDE_BUY,
  SIDE_SELL,
} from "../../../src/features/tape/model/ring";

// The `22` example item of `getTrades`, as written there.
const example = {
  id: "2290000000123",
  ts: "2026-09-14T10:31:01.884Z",
  price: "63120.50",
  size: "2.311",
  side: "buy",
  is_block_trade: false,
  is_liquidation: false,
  is_big_trade: false,
  cluster_size: 1,
  tick_direction: "PlusTick",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("tape history pages", () => {
  it("reads a PublicTrade: id, time, decimals as sent, the feed's side and flags", () => {
    expect(parsePublicTrade(example)).toEqual({
      id: "2290000000123",
      tsMs: Date.parse("2026-09-14T10:31:01.884Z"),
      price: "63120.50",
      size: "2.311",
      side: SIDE_BUY,
      flags: 0,
      clusterSize: 1,
    });
    const flagged = parsePublicTrade({
      ...example,
      side: "sell",
      is_block_trade: true,
      is_liquidation: true,
      is_big_trade: true,
      cluster_size: 7,
    });
    expect(flagged).toMatchObject({
      side: SIDE_SELL,
      flags: FLAG_BLOCK | FLAG_LIQUIDATION | FLAG_BIG,
      clusterSize: 7,
    });
  });

  it.each([
    ["not an object", null],
    ["an array", [example]],
    ["no id", { ...example, id: "" }],
    ["a bad time", { ...example, ts: "yesterday" }],
    ["a bad price", { ...example, price: "1e999" }],
    ["a bad side", { ...example, side: "long" }],
  ])("refuses %s", (_, value) => {
    expect(parsePublicTrade(value)).toBeNull();
  });

  it("asks one bounded page of the hot tape, same origin, and returns its items", async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ items: [example], meta: {} })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const items = await fetchTradesPage({ symbol: "BTCUSDT", fromMs: 0, toMs: 1_000 });
    expect(items).toEqual([example]);
    const url = new URL(String((fetchMock.mock.calls[0] as unknown[])[0]), "http://x");
    expect(url.pathname).toBe("/api/v1/market/trades");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      symbol: "BTCUSDT",
      from: "1970-01-01T00:00:00.000Z",
      to: "1970-01-01T00:00:01.000Z",
      limit: String(TRADES_PAGE_LIMIT),
    });
  });

  it("rejects a refused page and reads a body without items as empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 404 })),
    );
    await expect(fetchTradesPage({ symbol: "BTCUSDT", fromMs: 0, toMs: 1 })).rejects.toThrow("404");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}")),
    );
    await expect(fetchTradesPage({ symbol: "BTCUSDT", fromMs: 0, toMs: 1 })).resolves.toEqual([]);
  });
});
