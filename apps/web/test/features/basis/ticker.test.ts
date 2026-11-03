// E24-S08 (#783) slice 1: the ticker fields the basis readout reads, from the recorded capture.
import { describe, expect, it } from "vitest";
import { basisOf } from "../../../src/features/basis/basis";
import { parseBasisFrames, parseBasisItem } from "../../../src/features/basis/ticker";
import { recordedTickerItems, tickerDelta, tickerReset, tickerSnap } from "./support/basisFixtures";

const items = recordedTickerItems();
const first = items[0];
if (first === undefined) throw new Error("ticker fixture");

describe("parseBasisItem", () => {
  it("reads last, mark and index off the recorded snapshot", () => {
    expect(parseBasisItem(first, "BTCUSDT")).toEqual({
      tsMs: first.ts_ms,
      last: "82751.20",
      mark: "82751.20",
      index: "82782.37",
      stale: false,
    });
  });
  it("reads a missing or malformed mark / index as null, never 0", () => {
    const t = parseBasisItem({ ...first, mark_price: undefined, index_price: "abc" }, "BTCUSDT");
    expect(t?.mark).toBeNull();
    expect(t?.index).toBeNull();
  });
  it("skips another symbol, a bad last price and a bad timestamp", () => {
    expect(parseBasisItem(first, "ETHUSDT")).toBeNull();
    expect(parseBasisItem({ ...first, last_price: "1e5" }, "BTCUSDT")).toBeNull();
    expect(parseBasisItem({ ...first, ts_ms: 0 }, "BTCUSDT")).toBeNull();
    expect(parseBasisItem(null, "BTCUSDT")).toBeNull();
  });
  it("carries the served stale flag", () => {
    expect(parseBasisItem({ ...first, stale: true }, "BTCUSDT")?.stale).toBe(true);
  });
});

describe("parseBasisFrames", () => {
  it("walks snapshot, delta and reset in order and skips a binary body", () => {
    const second = items[1] ?? first;
    const out = parseBasisFrames(
      [
        tickerSnap([first]),
        tickerReset,
        tickerDelta([second]),
        { ...tickerDelta([second]), body: { e: "b", p: new Uint8Array(1) } } as never,
      ],
      "BTCUSDT",
    );
    expect(out.map((o) => (o === "reset" ? o : o.tsMs))).toEqual([
      first.ts_ms,
      "reset",
      second.ts_ms,
    ]);
  });
});

describe("basisOf (the D03 §3 sample)", () => {
  const tick = parseBasisItem(first, "BTCUSDT");
  if (tick === null) throw new Error("tick");
  it("last − index is −31.17 (−0.038 %)", () => {
    expect(basisOf(tick, "last")).toEqual({ source: "last", basis: "-31.17", pct: "-0.038" });
  });
  it("mark − index is the same on this capture (mark = last)", () => {
    expect(basisOf(tick, "mark")?.basis).toBe("-31.17");
  });
  it("differs by source when mark differs", () => {
    expect(basisOf({ ...tick, mark: "82780.00" }, "mark")?.basis).toBe("-2.37");
  });
  it("is null without the index or without the source price", () => {
    expect(basisOf({ ...tick, index: null }, "last")).toBeNull();
    expect(basisOf({ ...tick, mark: null }, "mark")).toBeNull();
    expect(basisOf({ ...tick, mark: null }, "last")).not.toBeNull();
  });
});
