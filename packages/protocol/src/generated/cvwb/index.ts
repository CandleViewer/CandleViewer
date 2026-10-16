// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with `pnpm --filter @candleviewer/protocol generate`.
// Source: packages/protocol/cvwb-layout.json (docs/plan/23-ws-protocol.md §3.4)
// via scripts/generate-cvwb-layout.mjs. The Python twin is
// services/api/candleviewer/ws/_generated/cvwb_layout.py (same generator).
// ==========================================================================
/* eslint-disable */

export const CVWB_MAGIC = 1129731906;
export const CVWB_HEADER = {
  bytes: 24,
  offsets: {
    magic: 0,
    formatVersion: 4,
    bodyKind: 5,
    flags: 6,
    priceScale: 7,
    qtyScale: 8,
    recordCount: 12,
    tsBaseMs: 16,
  },
  types: {
    magic: "u32",
    formatVersion: "u8",
    bodyKind: "u8",
    flags: "u8",
    priceScale: "u8",
    qtyScale: "u8",
    recordCount: "u32",
    tsBaseMs: "u64",
  },
} as const;
export const CVWB_HEADER_FLAGS = { estimated: 1, coalesced: 2, replay: 4, partial: 8 } as const;
export const CVWB_KINDS = {
  bookSnapshot: {
    id: 1,
    formatVersion: 1,
    lengthRule: "min",
    record: {
      bytes: 17,
      offsets: { side: 0, price: 1, size: 9 },
      types: { side: "u8", price: "i64", size: "u64" },
    },
    trailer: { bytes: 16, offsets: { xu: 0, xseq: 8 }, types: { xu: "u64", xseq: "u64" } },
  },
  bookDelta: {
    id: 2,
    formatVersion: 1,
    lengthRule: "min",
    record: {
      bytes: 17,
      offsets: { side: 0, price: 1, size: 9 },
      types: { side: "u8", price: "i64", size: "u64" },
    },
  },
  trades: {
    id: 3,
    formatVersion: 1,
    lengthRule: "min",
    record: {
      bytes: 22,
      offsets: { tsOffsetMs: 0, price: 4, size: 12, side: 20, flags: 21 },
      types: { tsOffsetMs: "u32", price: "i64", size: "u64", side: "u8", flags: "u8" },
    },
  },
  bars: {
    id: 4,
    formatVersion: 2,
    lengthRule: "exact",
    record: {
      bytes: 85,
      offsets: {
        generation: 0,
        index: 8,
        tsOffsetMs: 16,
        open: 20,
        high: 28,
        low: 36,
        close: 44,
        volume: 52,
        turnover: 60,
        trades: 68,
        delta: 72,
        flags: 80,
      },
      types: {
        generation: "u64",
        index: "u64",
        tsOffsetMs: "u32",
        open: "i64",
        high: "i64",
        low: "i64",
        close: "i64",
        volume: "u64",
        turnover: "u64",
        trades: "u32",
        delta: "i64",
        flags: "u8",
      },
    },
  },
  footprint: {
    id: 5,
    formatVersion: 2,
    lengthRule: "min",
    record: {
      bytes: 33,
      offsets: { price: 0, bidVolume: 8, askVolume: 16, trades: 24, flags: 28 },
      types: { price: "i64", bidVolume: "u64", askVolume: "u64", trades: "u32", flags: "u8" },
    },
    groupPrefix: {
      bytes: 28,
      offsets: { generation: 0, index: 8, tsOffsetMs: 16, cellCount: 20, flags: 24 },
      types: { generation: "u64", index: "u64", tsOffsetMs: "u32", cellCount: "u32", flags: "u8" },
    },
  },
  heatmapColumn: {
    id: 6,
    formatVersion: 1,
    lengthRule: "min",
    record: {
      bytes: 16,
      offsets: { bidSize: 0, askSize: 8 },
      types: { bidSize: "u64", askSize: "u64" },
    },
    bodyPrefix: {
      bytes: 24,
      offsets: { tsOffsetMs: 0, priceMin: 4, priceStep: 12, rowCount: 20 },
      types: { tsOffsetMs: "u32", priceMin: "i64", priceStep: "i64", rowCount: "u32" },
    },
  },
} as const;
