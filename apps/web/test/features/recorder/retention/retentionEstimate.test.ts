/**
 * E16-S03 (#485): the steady-state estimate and the preview fallback (E16-D03 §5, §9; D03-D7;
 * BQ-3). Pure: integer bytes, UTC dates, no deck strings. The worked numbers are D03's, on the `22`
 * storage example: BTCUSDT pinned at 780 MB/day, ETHUSDT at 520 MB/day holding about 2.3 days.
 */
import { describe, expect, it } from "vitest";
import {
  fallbackPreview,
  gigabytes,
  previewSource,
  steadyState,
  type PreviewSource,
} from "../../../../src/features/recorder/retention/retentionEstimate";
import {
  addOverride,
  classify,
  load,
  setAction,
  setDays,
  stageRemoval,
  symbolsOf,
  type Draft,
  type Reduction,
  type RowKey,
  type StorageUsage,
  type StreamKind,
} from "../../../../src/features/recorder/retention/retentionModel";
import { POLICIES_DEFAULTS, STORAGE_USAGE, policy } from "./fixtures";

type Step = (draft: Draft) => Draft;
const G = (stream: StreamKind): RowKey => ({ symbol: null, stream });
const O = (symbol: string, stream: StreamKind): RowKey => ({ symbol, stream });
const edit = (draft: Draft, ...steps: Step[]): Draft => steps.reduce((d, step) => step(d), draft);

const BASE = load(POLICIES_DEFAULTS.items);
const K1 = edit(
  BASE,
  (d) => setAction(d, G("trades"), "drop"),
  (d) => setDays(d, G("trades"), 7),
);
const reductionOf = (draft: Draft, storage: StorageUsage = STORAGE_USAGE): Reduction => {
  const result = classify(draft, { ...symbolsOf(storage), applyNow: false });
  if (result.kind !== "reduction") throw new Error(`expected a reduction, got ${result.kind}`);
  return result;
};
/** Synthetic: SOLUSDT holds exactly 10 days at 1 GB/day on 2026-09-14 00:00 UTC (not market data). */
const SOL: StorageUsage = {
  generated_at: "2026-09-14T00:00:00.000Z",
  symbols: [
    {
      symbol: "SOLUSDT",
      used_bytes: 10_000_000_000,
      daily_growth_bytes: 1_000_000_000,
      pinned: false,
    },
  ],
};

describe("steadyState (D03 §9, D03-D7)", () => {
  it("steadyState - the 22 examples - 520 MB/day x 365 d = 189.8 GB, 9 % of 2,000 GB, pinned 780 MB/day apart", () => {
    const estimate = steadyState(STORAGE_USAGE, BASE);
    expect(estimate).toEqual({
      growthPerDay: 520_000_000,
      windowDays: 365,
      bytes: 189_800_000_000,
      capBytes: 2_000_000_000_000,
      pct: 9,
      pinnedGrowthPerDay: 780_000_000,
    });
    expect([gigabytes(estimate.bytes), gigabytes(2_000_000_000_000)]).toEqual([189.8, 2000]);
  });

  const WINDOWS: [string, Step[], number][] = [
    ["trades 30 to 90 d (365 d still the longest)", [(d) => setDays(d, G("trades"), 90)], 365],
    ["trades to 1000 d", [(d) => setDays(d, G("trades"), 1000)], 1000],
    [
      "funding to 30 d Delete after",
      [(d) => setAction(d, G("funding"), "drop"), (d) => setDays(d, G("funding"), 30)],
      90,
    ],
    [
      "an ETHUSDT funding override at 3000 d",
      [
        (d) => addOverride(d, "ETHUSDT", "funding"),
        (d) => setDays(d, O("ETHUSDT", "funding"), 3000),
      ],
      3000,
    ],
    [
      "a BTCUSDT override at 3000 d (pinned: stated apart)",
      [
        (d) => addOverride(d, "BTCUSDT", "funding"),
        (d) => setDays(d, O("BTCUSDT", "funding"), 3000),
      ],
      365,
    ],
    [
      "an ETHUSDT override at 3000 d staged for removal",
      [
        (d) => addOverride(d, "ETHUSDT", "funding"),
        (d) => setDays(d, O("ETHUSDT", "funding"), 3000),
        (d) => stageRemoval(d, O("ETHUSDT", "funding")),
      ],
      365,
    ],
    ["an invalid field (4000 d)", [(d) => setDays(d, G("funding"), 4000)], 365],
  ];
  it.each(WINDOWS)("steadyState - %s - window %i d", (_name, steps, window) => {
    const estimate = steadyState(STORAGE_USAGE, edit(BASE, ...steps));
    expect([estimate.windowDays, estimate.bytes]).toEqual([window, 520_000_000 * window]);
  });

  it("steadyState - a hand-built draft with no rows - the eight seeds' longest window, 365 d", () => {
    expect(steadyState(STORAGE_USAGE, { base: [], rows: [] })).toMatchObject({
      windowDays: 365,
      bytes: 189_800_000_000,
      pct: 9,
    });
  });

  it("steadyState - no cap, a zero cap, no symbols - no percent, nothing grows", () => {
    expect(steadyState({ ...STORAGE_USAGE, cap_bytes: 0 }, BASE).pct).toBeNull();
    expect(steadyState({ cap_bytes: 1000, symbols: [{ symbol: "ETHUSDT" }] }, BASE)).toMatchObject({
      growthPerDay: 0,
      bytes: 0,
      pct: 0,
    });
    expect(steadyState({}, BASE)).toEqual({
      growthPerDay: 0,
      windowDays: 365,
      bytes: 0,
      capBytes: null,
      pct: null,
      pinnedGrowthPerDay: 0,
    });
  });
});

describe("fallbackPreview (D03 §5; BQ-3)", () => {
  it("the 22 storage example - ETHUSDT - holds about 2.3 days", () => {
    const eth = STORAGE_USAGE.symbols.find((s) => s.symbol === "ETHUSDT");
    expect(eth && Math.round((eth.used_bytes / eth.daily_growth_bytes) * 10) / 10).toBe(2.3);
  });

  it("fallbackPreview - the worked K1 - nothing before 2026-09-07, about 0 GB, recording started about 2026-09-12", () => {
    expect(fallbackPreview(STORAGE_USAGE, K1, reductionOf(K1))).toEqual({
      source: "estimate",
      rows: [
        {
          symbol: "ETHUSDT",
          streams: ["trades"],
          to: "2026-09-07",
          since: "2026-09-12",
          bytes: 0,
          nothingBefore: true,
        },
      ],
      exempt: [{ symbol: "BTCUSDT", streams: ["trades"] }],
      totalBytes: 0,
      symbolCount: 1,
    });
  });

  it("fallbackPreview - K7 1000 d to 30 d Move to Parquet after - the cut-off 24 months back, 2024-09-14", () => {
    const k7 = edit(load([policy("trades", 1000, "archive_parquet")]), (d) =>
      setDays(d, G("trades"), 30),
    );
    expect(fallbackPreview(STORAGE_USAGE, k7, reductionOf(k7)).rows).toMatchObject([
      { symbol: "ETHUSDT", to: "2024-09-14", since: "2026-09-12", bytes: 0, nothingBefore: true },
    ]);
  });

  it("fallbackPreview - 10 days recorded, trades 7 to 3 d Delete after - 7 GB from 2026-09-04 to 2026-09-11", () => {
    const k2 = edit(load([policy("trades", 7, "drop")]), (d) => setDays(d, G("trades"), 3));
    expect(fallbackPreview(SOL, k2, reductionOf(k2, SOL))).toEqual({
      source: "estimate",
      rows: [
        {
          symbol: "SOLUSDT",
          streams: ["trades"],
          to: "2026-09-11",
          since: "2026-09-04",
          bytes: 7_000_000_000,
          nothingBefore: false,
        },
      ],
      exempt: [],
      totalBytes: 7_000_000_000,
      symbolCount: 1,
    });
  });

  it("fallbackPreview - two streams of one symbol shrink - one row, both streams, the shorter total's cut-off", () => {
    const draft = edit(
      load([
        policy("trades", 30, "archive_parquet"),
        policy("orderbook_delta", 7, "archive_parquet"),
      ]),
      (d) => setAction(d, G("trades"), "drop"),
      (d) => setDays(d, G("trades"), 7),
      (d) => setAction(d, G("orderbook_delta"), "drop"),
      (d) => setDays(d, G("orderbook_delta"), 3),
    );
    expect(fallbackPreview(SOL, draft, reductionOf(draft, SOL)).rows).toMatchObject([
      {
        symbol: "SOLUSDT",
        streams: ["trades", "orderbook_delta"],
        to: "2026-09-11",
        bytes: 7_000_000_000,
      },
    ]);
  });

  it("fallbackPreview - a stopped symbol and an empty one - all of it may predate; nothing recorded", () => {
    const storage: StorageUsage = {
      generated_at: "2026-09-14T00:00:00.000Z",
      symbols: [
        { symbol: "ADAUSDT", used_bytes: 5_000_000_000, daily_growth_bytes: 0, pinned: false },
        { symbol: "XRPUSDT", used_bytes: 0, daily_growth_bytes: 0, pinned: false },
      ],
    };
    const preview = fallbackPreview(storage, K1, reductionOf(K1, storage));
    expect(preview.rows).toEqual([
      {
        symbol: "ADAUSDT",
        streams: ["trades"],
        to: "2026-09-07",
        since: null,
        bytes: 5_000_000_000,
        nothingBefore: false,
      },
      {
        symbol: "XRPUSDT",
        streams: ["trades"],
        to: "2026-09-07",
        since: null,
        bytes: 0,
        nothingBefore: true,
      },
    ]);
    expect([preview.totalBytes, preview.symbolCount]).toEqual([5_000_000_000, 2]);
  });

  it("fallbackPreview - one stream through two rules - a row per symbol, in symbol order", () => {
    const two: StorageUsage = {
      generated_at: "2026-09-14T00:00:00.000Z",
      symbols: [
        { symbol: "SOLUSDT", used_bytes: 10_000_000_000, daily_growth_bytes: 1_000_000_000 },
        { symbol: "ETHUSDT", used_bytes: 10_000_000_000, daily_growth_bytes: 1_000_000_000 },
      ],
    };
    const draft = edit(
      K1,
      (d) => addOverride(d, "ETHUSDT", "trades"),
      (d) => setAction(d, O("ETHUSDT", "trades"), "drop"),
      (d) => setDays(d, O("ETHUSDT", "trades"), 3),
    );
    expect(fallbackPreview(two, draft, reductionOf(draft, two))).toMatchObject({
      rows: [
        { symbol: "ETHUSDT", to: "2026-09-11", since: "2026-09-04", bytes: 7_000_000_000 },
        { symbol: "SOLUSDT", to: "2026-09-07", since: "2026-09-04", bytes: 3_000_000_000 },
      ],
      totalBytes: 10_000_000_000,
      symbolCount: 2,
    });
  });

  it("fallbackPreview - symbols the report does not list - nothing recorded, no start", () => {
    const result = classify(K1, {
      symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
      pinned: ["BTCUSDT"],
      applyNow: false,
    });
    if (result.kind !== "reduction") throw new Error(`expected a reduction, got ${result.kind}`);
    expect(fallbackPreview(STORAGE_USAGE, K1, result).rows.slice(1)).toEqual(
      ["SOLUSDT", "XRPUSDT"].map((symbol) => ({
        symbol,
        streams: ["trades"],
        to: "2026-09-07",
        since: null,
        bytes: 0,
        nothingBefore: true,
      })),
    );
  });

  it("fallbackPreview - a report without generated_at - no dates, the symbol's whole size", () => {
    const storage: StorageUsage = { symbols: STORAGE_USAGE.symbols };
    expect(fallbackPreview(storage, K1, reductionOf(K1, storage)).rows).toEqual([
      {
        symbol: "ETHUSDT",
        streams: ["trades"],
        to: null,
        since: null,
        bytes: 1_220_004_410,
        nothingBefore: false,
      },
    ]);
  });

  /** Synthetic (not market data): one symbol whose start is over 3650 days back at its growth. */
  const slow = (used: number, growth: number): StorageUsage => ({
    generated_at: "2026-09-14T00:00:00.000Z",
    symbols: [{ symbol: "SOLUSDT", used_bytes: used, daily_growth_bytes: growth, pinned: false }],
  });
  it.each([
    ["1.22 GB at 3 B/day (no date can hold the start)", 1_220_004_410, 3],
    ["100 GB at 1 kB/day (about 274,000 years back)", 100_000_000_000, 1_000],
  ])("fallbackPreview - %s - no start, the whole size, never a throw", (_n, used, growth) => {
    const storage = slow(used, growth);
    expect(fallbackPreview(storage, K1, reductionOf(K1, storage)).rows).toEqual([
      {
        symbol: "SOLUSDT",
        streams: ["trades"],
        to: "2026-09-07",
        since: null,
        bytes: used,
        nothingBefore: false,
      },
    ]);
  });

  it("fallbackPreview - a reduction classified with no report - no row: only a report names the symbols", () => {
    const result = classify(K1, { ...symbolsOf(null), applyNow: false });
    if (result.kind !== "reduction") throw new Error(`expected a reduction, got ${result.kind}`);
    expect(fallbackPreview(STORAGE_USAGE, K1, result)).toEqual({
      source: "estimate",
      rows: [],
      exempt: [],
      totalBytes: 0,
      symbolCount: 0,
    });
  });

  it("fallbackPreview - a report that lists no symbols - nothing recorded, no start", () => {
    const storage: StorageUsage = { generated_at: STORAGE_USAGE.generated_at };
    expect(fallbackPreview(storage, K1, reductionOf(K1)).rows).toEqual([
      {
        symbol: "ETHUSDT",
        streams: ["trades"],
        to: "2026-09-07",
        since: null,
        bytes: 0,
        nothingBefore: true,
      },
    ]);
  });

  it("previewSource - the fallback - is a PreviewSource a server preview can replace", async () => {
    const source: PreviewSource = previewSource;
    const reduction = reductionOf(K1);
    expect(source).toBe(fallbackPreview);
    expect(await source(STORAGE_USAGE, K1, reduction)).toEqual(
      fallbackPreview(STORAGE_USAGE, K1, reduction),
    );
  });
});
