import { describe, expect, it } from "vitest";
import {
  DIRECTION_GLYPH,
  directionOf,
  footprintCellSentence,
  heatmapCellSentence,
  ladderRowSentence,
  orUnavailable,
  sizeText,
} from "../../../src/chart/a11y/orderflowFormat";
import { formatBarSentence } from "../../../src/chart/a11y/format";

describe("footprint cell sentence (CMP-109)", () => {
  it("price, bid, ask, signed delta and the imbalance word", () => {
    expect(
      footprintCellSentence({
        price: "64010.5",
        bid: "12",
        ask: "20",
        delta: "8",
        imbalance: "ask",
      }),
    ).toBe("64,010.5, bid 12, ask 20, delta +8, ask imbalance");
    expect(
      footprintCellSentence({
        price: "64010.5",
        bid: "20",
        ask: "12",
        delta: "-8",
        imbalance: null,
      }),
    ).toBe("64,010.5, bid 20, ask 12, delta −8");
    expect(
      footprintCellSentence({
        price: "1",
        bid: "3",
        ask: "1",
        delta: "-2",
        imbalance: "bid",
        estimated: true,
      }),
    ).toBe("1, bid 3, ask 1, delta −2, bid imbalance, estimated");
  });

  it("zero, negative and very large values", () => {
    expect(
      footprintCellSentence({ price: "0.0001", bid: "0", ask: "0", delta: "0", imbalance: null }),
    ).toBe("0.0001, bid 0, ask 0, delta +0");
    expect(
      footprintCellSentence({
        price: "123456789.5",
        bid: "98765432101.25",
        ask: "1",
        delta: "-98765432100.25",
        imbalance: "bid",
      }),
    ).toBe("123,456,789.5, bid 98,765,432,101.25, ask 1, delta −98,765,432,100.25, bid imbalance");
  });

  it("reads a price exactly as the bar sentence does (one formatter family)", () => {
    const bar = formatBarSentence(
      {
        timeUs: 0,
        open: "64010.5",
        high: "64010.5",
        low: "64010.5",
        close: "64010.5",
        volume: "1",
      },
      60_000,
    );
    const cell = footprintCellSentence({
      price: "64010.5",
      bid: "1",
      ask: "1",
      delta: "0",
      imbalance: null,
    });
    expect(bar).toContain("open 64,010.5");
    expect(cell.startsWith("64,010.5,")).toBe(true);
  });
});

describe("ladder row sentence (CMP-108)", () => {
  it("price, bid, ask, side and the caller's own order", () => {
    expect(
      ladderRowSentence({
        price: "64010",
        bid: "12",
        ask: "0",
        side: "bid",
        own: [{ side: "buy", qty: "0.1" }],
      }),
    ).toBe("64,010, bid 12, ask 0, bid side, your buy order 0.1 working");
  });

  it("several own orders read as a count; a position and the spread are said", () => {
    expect(
      ladderRowSentence({
        price: "64011",
        bid: "0",
        ask: "0",
        side: "spread",
        own: [
          { side: "buy", qty: "1" },
          { side: "sell", qty: "2" },
        ],
        position: { side: "short", qty: "0.5" },
      }),
    ).toBe(
      "64,011, bid 0, ask 0, inside the spread, 2 of your orders working, your short position 0.5",
    );
    expect(
      ladderRowSentence({ price: "64012", bid: "0", ask: "7", side: "ask", position: null }),
    ).toBe("64,012, bid 0, ask 7, ask side");
  });
});

describe("heatmap cell readout (CMP-111)", () => {
  it("price, size and side on focus", () => {
    expect(heatmapCellSentence({ price: "64010", size: "125.5", side: "bid" })).toBe(
      "64,010, resting 125.5, bid side",
    );
    expect(heatmapCellSentence({ price: "64010", size: "0", side: "ask" })).toBe(
      "64,010, resting 0, ask side",
    );
  });
});

describe("sign and size helpers", () => {
  it("direction: up, down, flat (−0 and 0.00 are flat)", () => {
    expect(directionOf("8")).toBe("up");
    expect(directionOf("-8")).toBe("down");
    expect(directionOf("0")).toBe("flat");
    expect(directionOf("-0")).toBe("flat");
    expect(directionOf("0.00")).toBe("flat");
    expect(DIRECTION_GLYPH.up).toBe("▲");
    expect(DIRECTION_GLYPH.down).toBe("▼");
  });

  it("a negative size or a non-decimal is a RangeError, never shown", () => {
    expect(() => sizeText("-1")).toThrow(RangeError);
    expect(() => sizeText("1e3")).toThrow(RangeError);
    expect(sizeText("1234567.125")).toBe("1,234,567.125");
  });

  it("a ladder row never throws: a faulty field reads 'not available', the rest still reads (code m4)", () => {
    expect(ladderRowSentence({ price: "1", bid: "-1", ask: "0", side: "bid" })).toBe(
      "1, bid not available, ask 0, bid side",
    );
    expect(
      ladderRowSentence({
        price: "x",
        bid: "2",
        ask: "0",
        side: "bid",
        own: [{ side: "buy", qty: "-1" }],
        position: { side: "short", qty: "1e2" },
      }),
    ).toBe(
      "not available, bid 2, ask 0, bid side, your buy order not available working, " +
        "your short position not available",
    );
    expect(orUnavailable(sizeText, "-3", "—")).toBe("—");
  });

  it("a footprint cell and a heatmap cell never throw: a faulty field reads 'not available' (record minor)", () => {
    expect(
      footprintCellSentence({ price: "x", bid: "-1", ask: "1e3", delta: "NaN", imbalance: "ask" }),
    ).toBe(
      "not available, bid not available, ask not available, delta not available, ask imbalance",
    );
    expect(
      footprintCellSentence({ price: "1", bid: "2", ask: "3", delta: "-", imbalance: null }),
    ).toBe("1, bid 2, ask 3, delta not available");
    expect(heatmapCellSentence({ price: "64010", size: "-5", side: "bid" })).toBe(
      "64,010, resting not available, bid side",
    );
    expect(heatmapCellSentence({ price: "", size: "5", side: "ask" })).toBe(
      "not available, resting 5, ask side",
    );
  });
});
