// E24-S01 (#776) slice 1: the OI fields of `ticker.{symbol}` (`23` §14.8) over the recorded stream.
import { describe, expect, it } from "vitest";
import { parseTickerFrames, parseTickerItem } from "../../../src/features/derivatives/oi/ticker";
import { recordedTickerItems, tickerDelta, tickerReset, tickerSnap } from "./support/oiFixtures";

const ITEMS = recordedTickerItems();
const FIRST = ITEMS[0];
if (FIRST === undefined) throw new Error("ticker fixture");

describe("ticker OI parse", () => {
  it("keeps the decimals as sent and the item's time", () => {
    expect(parseTickerItem(FIRST, "BTCUSDT")).toEqual({
      tsMs: FIRST.ts_ms,
      base: "57911.602",
      valueUsdt: "4792254559.42",
      stale: false,
    });
  });

  it("skips another symbol, a missing or numeric OI, and a bad time", () => {
    expect(parseTickerItem(FIRST, "ETHUSDT")).toBeNull();
    expect(parseTickerItem({ ...FIRST, open_interest: undefined }, "BTCUSDT")).toBeNull();
    expect(parseTickerItem({ ...FIRST, open_interest: 57911.6 }, "BTCUSDT")).toBeNull();
    expect(parseTickerItem({ ...FIRST, ts_ms: "1" }, "BTCUSDT")).toBeNull();
    expect(parseTickerItem(null, "BTCUSDT")).toBeNull();
  });

  it("reads a missing value as null and a served stale flag as true", () => {
    expect(
      parseTickerItem({ ...FIRST, open_interest_value: undefined }, "BTCUSDT")?.valueUsdt,
    ).toBeNull();
    expect(parseTickerItem({ ...FIRST, stale: true }, "BTCUSDT")?.stale).toBe(true);
  });

  it("walks snap and delta bodies in order and passes resets through", () => {
    const out = parseTickerFrames(
      [tickerSnap(ITEMS.slice(0, 2)), tickerReset, tickerDelta(ITEMS.slice(2, 3))],
      "BTCUSDT",
    );
    expect(out.map((t) => (t === "reset" ? t : t.tsMs))).toEqual([
      ITEMS[0]?.ts_ms,
      ITEMS[1]?.ts_ms,
      "reset",
      ITEMS[2]?.ts_ms,
    ]);
  });

  it("reads nothing from a binary body", () => {
    const frame = { ...tickerDelta([]), body: { e: "b64" as const, bytes: new ArrayBuffer(4) } };
    expect(parseTickerFrames([frame], "BTCUSDT")).toEqual([]);
  });
});
