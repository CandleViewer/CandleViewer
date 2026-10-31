/** E08-S08 (#4702): a CV `ticker` item (23 §14.8) as SCR-100 reads it (E08-D07 §4.1, D9), on the derived golden. */
import { describe, expect, it } from "vitest";
import {
  tickerItemsOf,
  tickerValues,
  type TickerItem,
} from "../../../src/features/watchlist/ticker/tickerValues";
import { restItem, streamItem } from "./support";

describe("tickerValues", () => {
  it("reads the recorded snapshot's decimals as numbers, percentages in points (wire fraction × 100)", () => {
    const values = tickerValues(streamItem(0));
    expect(values).toMatchObject({
      symbol: "BTCUSDT",
      lastPrice: 82751.2,
      turnover24h: 3412632305.4093,
      volume24h: 41760.372,
      nextFundingTimeMs: 1792396800000,
      tsMs: 1792391746229,
      serverStale: false,
    });
    expect(values?.pctChange24h).toBeCloseTo(1.2297, 10);
    expect(values?.fundingRate).toBeCloseTo(0.00771, 10);
  });

  it("derives the spread in bps from the same frame's bid and ask: (ask − bid) ÷ mid × 10 000", () => {
    const values = tickerValues(streamItem(0));
    expect(values?.spreadBps).toBeCloseTo((0.1 / 82751.15) * 10_000, 10);
  });

  it("reads every recorded REST item, each with its own price and time", () => {
    for (const symbol of ["BTCUSDT", "ETHUSDT", "SOLUSDT"]) {
      const item = restItem(symbol);
      expect(tickerValues(item)).toMatchObject({ symbol, lastPrice: Number(item.last_price) });
    }
  });

  it("leaves out a value the item lacks, and no spread without both sides", () => {
    const { bid1_price: bid, ...rest } = streamItem(0);
    expect(bid).toBe("82751.10"); // the recorded side this case leaves out
    const values = tickerValues(rest);
    expect(values).not.toBeNull();
    expect(values && "spreadBps" in values).toBe(false);
    expect(values && "bid1Price" in values).toBe(false);
  });

  it("refuses an item whose last price is not a finite decimal: no value is better than a wrong one", () => {
    const item: TickerItem = { ...streamItem(0), last_price: "NaN" };
    expect(tickerValues(item)).toBeNull();
  });

  it("carries the per-item stale flag (the server's 'Stale (server)')", () => {
    expect(tickerValues({ ...streamItem(0), stale: true })?.serverStale).toBe(true);
  });

  it("tickerItemsOf takes a TickerUpdate body's items and nothing from anything else", () => {
    expect(tickerItemsOf({ tickers: [streamItem(0)] })).toHaveLength(1);
    expect(tickerItemsOf({ tickers: "x" })).toEqual([]);
    expect(tickerItemsOf(null)).toEqual([]);
    expect(tickerItemsOf({ tickers: [{ symbol: 3 }] })).toEqual([]);
  });
});
