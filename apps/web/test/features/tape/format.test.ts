// E22-S01 (#714) PR-B: the tape's text (AC1: millisecond time, price, size, side; G-61 zone).
import { describe, expect, it } from "vitest";
import {
  baseAsset,
  formatAge,
  formatCount,
  formatDecimal,
  formatNotional,
  formatSecond,
  formatTime,
  rowName,
  sideWord,
  splitTime,
} from "../../../src/features/tape/format";
import { SIDE_BUY, SIDE_SELL } from "../../../src/features/tape/model/ring";

const local = (h: number, m: number, s: number, ms: number): number =>
  new Date(2026, 9, 31, h, m, s, ms).getTime();

describe("tape format", () => {
  it("writes HH:MM:SS.mmm in the browser's zone, padded, with millisecond precision", () => {
    expect(formatTime(local(14, 2, 11, 208))).toBe("14:02:11.208");
    expect(formatTime(local(9, 5, 3, 7))).toBe("09:05:03.007");
    expect(formatTime(local(0, 0, 0, 40))).toBe("00:00:00.040");
    expect(formatSecond(local(13, 58, 2, 999))).toBe("13:58:02");
  });

  it("splits the dimmable HH:MM: prefix from the rest (D7)", () => {
    expect(splitTime("14:02:11.208")).toEqual(["14:02:", "11.208"]);
  });

  it("groups counts by a space as the deck writes them", () => {
    expect(formatCount(412)).toBe("412");
    expect(formatCount(1_240)).toBe("1 240");
    expect(formatCount(2_010)).toBe("2 010");
    expect(formatCount(10_000)).toBe("10 000");
    expect(formatCount(-3)).toBe("0");
  });

  it("groups a feed decimal's integer part by commas and never re-rounds it", () => {
    expect(formatDecimal("64012.0")).toBe("64,012.0");
    expect(formatDecimal("18.75")).toBe("18.75");
    expect(formatDecimal("1234567.00010")).toBe("1,234,567.00010");
    expect(formatDecimal("-1200")).toBe("-1,200");
  });

  it("writes the notional compact, as D02 §3 draws it", () => {
    expect(formatNotional(256_100)).toBe("256.1k");
    expect(formatNotional(1_200_000)).toBe("1.2M");
    expect(formatNotional(7_680)).toBe("7.7k");
    expect(formatNotional(410_000)).toBe("410k");
    expect(formatNotional(640.04)).toBe("640");
    expect(formatNotional(Number.NaN)).toBe("—");
  });

  it("names a row side first, the tier word only on tiers 1-2, the tags, then the full time", () => {
    const base = {
      side: SIDE_SELL,
      size: "18.75",
      base: "BTC",
      price: "64012.0",
      notional: 1_200_225,
      time: "14:02:11.208",
      clusterSize: 1,
      liquidation: false,
      block: false,
    } as const;
    expect(rowName({ ...base, tier: 2 })).toBe(
      "Sell, 18.75 BTC at 64,012.0, 1.2M, whale, 14:02:11.208",
    );
    expect(rowName({ ...base, tier: 1, side: SIDE_BUY })).toBe(
      "Buy, 18.75 BTC at 64,012.0, 1.2M, big, 14:02:11.208",
    );
    expect(rowName({ ...base, tier: 0, clusterSize: 7, liquidation: true, block: true })).toBe(
      "Sell, 18.75 BTC at 64,012.0, 1.2M, cluster of 7, liquidation, block trade, 14:02:11.208",
    );
  });

  it("reads the base asset and the side word", () => {
    expect(baseAsset("BTCUSDT")).toBe("BTC");
    expect(sideWord(SIDE_BUY)).toBe("Buy");
    expect(sideWord(SIDE_SELL)).toBe("Sell");
    expect(formatAge(12_400)).toBe("00:12");
  });
});
