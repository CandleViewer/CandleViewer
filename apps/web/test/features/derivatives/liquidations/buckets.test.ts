// E24-S05 (#780) PR 4: the bucket rows (BQ 5) — one row per 250 ms bucket and side, exact sums and average, the
// single print shown as itself, the row bound — and the exact decimal helper behind them.
import { describe, expect, it } from "vitest";
import { feedRows } from "../../../../src/features/derivatives/liquidations/buckets";
import {
  addDec,
  divDec,
  formatDec,
  parseDec,
} from "../../../../src/features/derivatives/liquidations/decimal";
import type { HeldPrint } from "../../../../src/features/derivatives/liquidations/ring";

// D02 §6's cascade: 600 longs at 82,500.00 × 0.080 (6,600.00 each) in one 250 ms bucket, 20 shorts at
// 82,600.00 × 0.060 (4,956.00 each) in the same bucket
const T = Date.parse("2026-10-21T09:31:10Z");
let seq = 0;
const print = (side: "long" | "short", over: Partial<HeldPrint> = {}): HeldPrint => ({
  seq: seq++,
  tsMs: T + (seq % 200),
  side,
  price: side === "long" ? "82500.00" : "82600.00",
  size: side === "long" ? "0.080" : "0.060",
  notionalUsd: side === "long" ? "6600.00" : "4956.00",
  clusterSize: 1,
  ...over,
});

describe("feedRows", () => {
  it("reads D02 §6's cascade as its two bucket rows, exactly", () => {
    const prints = [
      ...Array.from({ length: 600 }, () => print("long")),
      ...Array.from({ length: 20 }, () => print("short")),
    ];
    const rows = feedRows([...prints].reverse(), 40);
    expect(rows.map((r) => [r.side, r.tsMs, r.prints, r.size, r.price, r.notionalUsd])).toEqual([
      ["short", T, 20, "1.200", "82600.00", "99120.00"],
      ["long", T, 600, "48.000", "82500.00", "3960000.00"],
    ]);
  });

  it("shows a lone print as itself, and keeps at most `max` rows, newest first", () => {
    const lone = print("long", {
      tsMs: T + 1_000,
      price: "82751.20",
      size: "0.498",
      notionalUsd: "41210.10",
      clusterSize: 8,
    });
    const older = Array.from({ length: 5 }, (_, k) => print("long", { tsMs: T - k * 250 }));
    const rows = feedRows([lone, ...older], 3);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toMatchObject({ prints: 1, price: "82751.20", size: "0.498", clusterSize: 8 });
  });

  it("keeps the newest print's price when a print has no served notional", () => {
    const rows = feedRows([print("long", { notionalUsd: null }), print("long")], 40);
    expect(rows[0]).toMatchObject({ prints: 2, notionalUsd: null, price: "82500.00" });
  });
});

describe("decimal", () => {
  it("adds across scales and divides half up, never through a float", () => {
    expect(formatDec(addDec(parseDec("0.1"), parseDec("0.2")))).toBe("0.3");
    expect(
      formatDec(
        addDec(parseDec("123456789012345678901234567890"), parseDec("0.000000000000000001")),
      ),
    ).toBe("123456789012345678901234567890.000000000000000001");
    expect(formatDec(divDec(parseDec("1"), parseDec("3"), 2) ?? parseDec("0"))).toBe("0.33");
    expect(formatDec(divDec(parseDec("2"), parseDec("3"), 2) ?? parseDec("0"))).toBe("0.67");
    expect(divDec(parseDec("1"), parseDec("0"), 2)).toBeNull();
  });
});
