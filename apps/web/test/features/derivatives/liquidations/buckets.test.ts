// E24-S05 (#780) PR 4: the bucket rows (BQ 5) — one row per 250 ms bucket and side, exact sums and average, the
// single print shown as itself, the row bound — and the exact decimal helper behind them.
import { describe, expect, it } from "vitest";
import { feedRows, ROW_BUCKET_MS } from "../../../../src/features/derivatives/liquidations/buckets";
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

  it("marks a bucket's average unserved when a print has no served notional", () => {
    const rows = feedRows([print("long", { notionalUsd: null }), print("long")], 40);
    // no served average without every member's notional: the row says so (review A m1)
    expect(rows[0]).toMatchObject({ prints: 2, notionalUsd: null, avgServed: false });
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

describe("feedRows at the row cut and the bucket edge (review A)", () => {
  /** Prints of size 1.000 and notional 10.00 in bucket `b`, newest first as given. */
  const at = (b: number, side: "long" | "short", k: number): HeldPrint => ({
    seq: 100 - k,
    tsMs: b * ROW_BUCKET_MS + k,
    side,
    price: "10.00",
    size: "1.000",
    notionalUsd: "10.00",
    clusterSize: 1,
  });

  it("still adds an older print to a kept row once the cut is reached", () => {
    // the reviewer's repro: (10, long), (9, long), (9, short), (9, long) with max 2
    const rows = feedRows(
      [at(10, "long", 0), at(9, "long", 1), at(9, "short", 2), at(9, "long", 3)],
      2,
    );
    expect(
      rows.map((r) => [r.side, r.tsMs / ROW_BUCKET_MS, r.prints, r.size, r.notionalUsd]),
    ).toEqual([
      ["long", 10, 1, "1.000", "10.00"],
      ["long", 9, 2, "2.000", "20.00"],
    ]);
  });

  it("cuts rows at the 250 ms edge: two prints 240 ms apart across it are two rows", () => {
    // 10 130 and 10 370 ms sit either side of the 250 ms edge at 10 250, inside one 500 ms span (10 000–10 499),
    // so a 500 ms bucket would merge them
    const newer = { ...at(0, "long", 0), tsMs: 10_370 };
    const older = { ...at(0, "long", 1), tsMs: 10_130 };
    const rows = feedRows([newer, older], 40);
    expect(rows.map((r) => [r.tsMs, r.prints])).toEqual([
      [10_370, 1],
      [10_130, 1],
    ]);
  });
});

/** A small seeded generator (mulberry32): deterministic, no dependency. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Exact sum of decimal strings as a scaled BigInt at `scale`. */
const sumAt = (values: readonly string[], scale: number): bigint =>
  values.reduce((acc, v) => {
    const d = parseDec(v);
    return acc + d.v * BigInt(10) ** BigInt(scale - d.scale);
  }, BigInt(0));

describe("feedRows, seeded properties (300 seeds)", () => {
  it("adds up: per row the count, size and notional equal its members'; one row per (bucket, side)", () => {
    for (let seed = 1; seed <= 300; seed += 1) {
      const r = rng(seed);
      const n = 1 + Math.floor(r() * 120);
      const max = 1 + Math.floor(r() * 12);
      let t = 1_000_000;
      const prints: HeldPrint[] = [];
      for (let k = 0; k < n; k += 1) {
        t += Math.floor(r() * 300);
        prints.push({
          seq: k,
          tsMs: t,
          side: r() < 0.5 ? "long" : "short",
          price: (60_000 + Math.floor(r() * 5_000)).toFixed(2),
          size: (r() * 3).toFixed(3),
          notionalUsd: (r() * 200_000).toFixed(2),
          clusterSize: 1 + Math.floor(r() * 3),
        });
      }
      const newestFirst = [...prints].reverse();
      const rows = feedRows(newestFirst, max);
      const keyOf = (p: { tsMs: number; side: string }) =>
        `${String(Math.floor(p.tsMs / ROW_BUCKET_MS))}|${p.side}`;
      const keys = rows.map(keyOf);
      expect(new Set(keys).size).toBe(rows.length); // one row per (bucket, side)
      expect(rows.length).toBe(Math.min(max, new Set(prints.map(keyOf)).size)); // the cut
      // the kept rows are the newest keys, in order of their newest print
      const firstSeen: string[] = [];
      for (const p of newestFirst) if (!firstSeen.includes(keyOf(p))) firstSeen.push(keyOf(p));
      expect(keys).toEqual(firstSeen.slice(0, max));
      for (const row of rows) {
        const members = prints.filter((p) => keyOf(p) === keyOf(row)); // sides never mixed
        expect(members.every((p) => p.side === row.side)).toBe(true);
        expect(row.prints).toBe(members.length);
        expect(row.clusterSize).toBe(members.reduce((c, p) => c + p.clusterSize, 0));
        if (members.length === 1) continue; // a lone print is shown as sent
        expect(parseDec(row.size).v).toBe(
          sumAt(
            members.map((p) => p.size),
            parseDec(row.size).scale,
          ),
        );
        const notional = row.notionalUsd ?? "";
        expect(parseDec(notional).v).toBe(
          sumAt(
            members.map((p) => p.notionalUsd ?? "0"),
            parseDec(notional).scale,
          ),
        );
      }
    }
  });

  it("divDec matches an exact half-up rational at random scales", () => {
    for (let seed = 1; seed <= 300; seed += 1) {
      const r = rng(seed * 7919);
      const a = { v: BigInt(Math.floor(r() * 1e9)), scale: Math.floor(r() * 6) };
      const b = { v: BigInt(1 + Math.floor(r() * 1e7)), scale: Math.floor(r() * 6) };
      const scale = Math.floor(r() * 6);
      // (a.v / 10^a.s) / (b.v / 10^b.s) at `scale`, half up: floor((2·num + den) / (2·den)) with
      // num = a.v · 10^(b.s + scale), den = b.v · 10^a.s
      const ten = BigInt(10);
      const num = a.v * ten ** BigInt(b.scale + scale);
      const den = b.v * ten ** BigInt(a.scale);
      const expected = (BigInt(2) * num + den) / (BigInt(2) * den);
      expect(divDec(a, b, scale)?.v).toBe(expected);
    }
  });
});

describe("feedRows, the average price (#5766 Minor 1)", () => {
  it("is the served notional over the size: (1.000, 100.00) + (3.000, 600.00) reads avg 175.00", () => {
    const base = { side: "long" as const, clusterSize: 1 };
    const rows = feedRows(
      [
        { ...base, seq: 1, tsMs: 40_010, price: "200.00", size: "3.000", notionalUsd: "600.00" },
        { ...base, seq: 0, tsMs: 40_000, price: "100.00", size: "1.000", notionalUsd: "100.00" },
      ],
      40,
    );
    // neither member's own price: 700.00 / 4.000
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ prints: 2, price: "175.00", avgServed: true });
  });
});
