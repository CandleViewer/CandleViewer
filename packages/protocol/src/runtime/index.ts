// Runtime binary frame decoders and sequence/resync helpers for the WS
// protocol (docs/plan/23-ws-protocol.md §3.4, §3.6, §7). This module parses
// *untrusted* input from the network — flagged as a fuzz target for E03's
// Schemathesis/contract job (E02-T09).

import type * as generated from "../generated/index.js";
import { CVWB_HEADER, CVWB_KINDS, CVWB_MAGIC } from "../generated/cvwb/index.js";

/** Result of a sequence-gap check against the last-seen frame sequence number. */
export type SeqCheckResult = "ok" | "gap" | "duplicate" | "out-of-order";

/**
 * Compares an incoming frame sequence number against the last-accepted one.
 * A `"gap"`, `"duplicate"` or `"out-of-order"` result means the caller must
 * resync from a fresh snapshot (C-2.5) — this helper only classifies, it
 * never resyncs itself.
 */
export function checkSequence(lastSeq: number, incomingSeq: number): SeqCheckResult {
  if (incomingSeq === lastSeq + 1) return "ok";
  if (incomingSeq === lastSeq) return "duplicate";
  if (incomingSeq < lastSeq) return "out-of-order";
  return "gap";
}

// ---------------------------------------------------------------------------
// §3.4 binary payload format (e: "b")
// ---------------------------------------------------------------------------

// Every offset, stride and format_version below comes from the ONE layout
// declaration packages/protocol/cvwb-layout.json (E17-T02), compiled to
// src/generated/cvwb by scripts/generate-cvwb-layout.mjs. The Python
// encoder/decoder (services/api/candleviewer/ws/binary.py) reads the same file.
const K = CVWB_KINDS;
const H = CVWB_HEADER.offsets;

/** `0x43565742` ("CVWB"), the magic number every binary frame body starts with. */
export const BINARY_FRAME_MAGIC: number = CVWB_MAGIC;

export const BODY_KIND = {
  BOOK_SNAPSHOT: 1,
  BOOK_DELTA: 2,
  TRADES: 3,
  BARS: 4,
  FOOTPRINT: 5,
  HEATMAP_COLUMN: 6,
} as const;

export type BodyKind = (typeof BODY_KIND)[keyof typeof BODY_KIND];

/** Bit flags carried in the common header's `flags` byte (§3.4). */
export interface BinaryFrameFlags {
  estimated: boolean;
  coalesced: boolean;
  replay: boolean;
  partial: boolean;
}

/** The 24-byte common header prefixing every binary frame body. */
export interface BinaryFrameHeader {
  magic: number;
  formatVersion: number;
  bodyKind: BodyKind;
  flags: BinaryFrameFlags;
  /** Decimal exponent: real price = int / 10^priceScale. */
  priceScale: number;
  /** Decimal exponent: real size = int / 10^qtyScale. */
  qtyScale: number;
  recordCount: number;
  /** Epoch-ms base; per-record times are u32 offsets from this. */
  tsBaseMs: bigint;
}

export const COMMON_HEADER_BYTES: number = CVWB_HEADER.bytes;

/** body_kind 4 (bars) format_version (#2014/#2018): v2 adds generation + index. */
export const BARS_FORMAT_VERSION: number = K.bars.formatVersion;

/** body_kind 5 (footprint) format_version (#2529): v2 adds generation + index to each group. */
export const FOOTPRINT_FORMAT_VERSION: number = K.footprint.formatVersion;

/** Thrown by every decoder below on any malformed input (§3.4 "Client obligations"). */
export class BinaryFrameError extends Error {
  constructor(
    message: string,
    readonly code:
      | "frame_malformed"
      | "unsupported_body_kind"
      | "unsupported_format_version" = "frame_malformed",
  ) {
    super(message);
    this.name = "BinaryFrameError";
  }
}

/** Ticket name for {@link BinaryFrameError} (E17-T02); same class. */
export const FrameMalformedError = BinaryFrameError;
export type FrameMalformedError = BinaryFrameError;

const FORMAT_VERSION_BY_KIND: Readonly<Record<number, number>> = Object.fromEntries(
  Object.values(K).map((k) => [k.id, k.formatVersion]),
);

/**
 * SR-128: rejects `count` records of `stride` bytes that cannot fit in the
 * `available` bytes, BEFORE anything sized from `count` is allocated.
 */
function assertFits(count: number, stride: number, available: number, what: string): void {
  if (count * stride > available) {
    throw new BinaryFrameError(
      `${what}: count=${count} x ${stride} bytes exceeds the ${available} bytes left in the buffer`,
    );
  }
}

function readFlags(byte: number): BinaryFrameFlags {
  return {
    estimated: (byte & 0b0001) !== 0,
    coalesced: (byte & 0b0010) !== 0,
    replay: (byte & 0b0100) !== 0,
    partial: (byte & 0b1000) !== 0,
  };
}

/**
 * Parses the 24-byte common header (§3.4). Per the client-obligations
 * paragraph, this validates `magic` and `format_version` but never rejects
 * trailing bytes it does not recognise — callers ignore anything after the
 * body they know how to decode, for forward compatibility.
 */
export function parseBinaryFrameHeader(buf: ArrayBufferView): BinaryFrameHeader {
  if (buf.byteLength < COMMON_HEADER_BYTES) {
    throw new BinaryFrameError(
      `binary frame too short for the ${COMMON_HEADER_BYTES}-byte common header (got ${buf.byteLength} bytes)`,
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const magic = view.getUint32(H.magic, true);
  if (magic !== BINARY_FRAME_MAGIC) {
    throw new BinaryFrameError(
      `bad magic 0x${magic.toString(16)}, expected 0x${BINARY_FRAME_MAGIC.toString(16)} ("CVWB")`,
    );
  }
  const formatVersion = view.getUint8(H.formatVersion);
  const rawBodyKind = view.getUint8(H.bodyKind);
  const expectedVersion = FORMAT_VERSION_BY_KIND[rawBodyKind];
  if (expectedVersion === undefined) {
    throw new BinaryFrameError(`unknown body_kind ${rawBodyKind}`, "unsupported_body_kind");
  }
  if (formatVersion !== expectedVersion) {
    throw new BinaryFrameError(
      `unsupported (body_kind=${rawBodyKind}, format_version=${formatVersion}); expected format_version ${expectedVersion}`,
      "unsupported_format_version",
    );
  }
  return {
    magic,
    formatVersion,
    bodyKind: rawBodyKind as BodyKind,
    flags: readFlags(view.getUint8(H.flags)),
    priceScale: view.getUint8(H.priceScale),
    qtyScale: view.getUint8(H.qtyScale),
    // bytes 9-11 reserved, deliberately skipped.
    recordCount: view.getUint32(H.recordCount, true),
    tsBaseMs: view.getBigUint64(H.tsBaseMs, true),
  };
}

/** Converts a scaled 64-bit integer (price or size) back to a decimal string, per §3.4. */
export function unscale(value: bigint, scale: number): string {
  const negative = value < 0n;
  const magnitude = negative ? -value : value;
  const divisor = 10n ** BigInt(scale);
  const whole = magnitude / divisor;
  const frac = magnitude % divisor;
  const sign = negative ? "-" : "";
  if (scale === 0) return `${sign}${whole.toString()}`;
  return `${sign}${whole.toString()}.${frac.toString().padStart(scale, "0")}`;
}

export interface BookLevel {
  side: "bid" | "ask";
  price: string;
  /** `size === "0"` means delete this level (§3.4). */
  size: string;
}

export interface BookSnapshotTrailer {
  /** Bybit update id, carried for diagnostics only — never used for our own sequencing. */
  xu: bigint;
  /** Bybit cross-sequence, carried for diagnostics only. */
  xseq: bigint;
}

export interface DecodedBookSnapshot {
  header: BinaryFrameHeader;
  levels: BookLevel[];
  trailer: BookSnapshotTrailer;
}

export interface DecodedBookDelta {
  header: BinaryFrameHeader;
  levels: BookLevel[];
}

const BOOK = K.bookDelta.record;
const BOOK_RECORD_BYTES = BOOK.bytes;
const BOOK_TRAILER_BYTES = K.bookSnapshot.trailer.bytes;

function decodeBookLevels(
  view: DataView,
  offset: number,
  header: BinaryFrameHeader,
): { levels: BookLevel[]; nextOffset: number } {
  assertFits(header.recordCount, BOOK_RECORD_BYTES, view.byteLength - offset, "book levels");
  const levels: BookLevel[] = [];
  let cursor = offset;
  for (let i = 0; i < header.recordCount; i += 1) {
    if (cursor + BOOK_RECORD_BYTES > view.byteLength) {
      throw new BinaryFrameError(
        `book record ${i} runs past the buffer (record_count=${header.recordCount})`,
      );
    }
    const sideByte = view.getUint8(cursor + BOOK.offsets.side);
    if (sideByte !== 0 && sideByte !== 1) {
      throw new BinaryFrameError(`invalid book side byte ${sideByte} at record ${i}`);
    }
    const price = view.getBigInt64(cursor + BOOK.offsets.price, true);
    const size = view.getBigUint64(cursor + BOOK.offsets.size, true);
    levels.push({
      side: sideByte === 0 ? "bid" : "ask",
      price: unscale(price, header.priceScale),
      size: unscale(size, header.qtyScale),
    });
    cursor += BOOK_RECORD_BYTES;
  }
  return { levels, nextOffset: cursor };
}

/** Decodes a `body_kind: 1` (book_snapshot) binary frame body. */
export function decodeBookSnapshot(buf: ArrayBufferView): DecodedBookSnapshot {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.BOOK_SNAPSHOT) {
    throw new BinaryFrameError(
      `expected body_kind=1 (book_snapshot), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const { levels, nextOffset } = decodeBookLevels(view, COMMON_HEADER_BYTES, header);
  if (nextOffset + BOOK_TRAILER_BYTES > view.byteLength) {
    throw new BinaryFrameError("book snapshot missing its 16-byte xu/xseq trailer");
  }
  return {
    header,
    levels,
    trailer: {
      xu: view.getBigUint64(nextOffset + K.bookSnapshot.trailer.offsets.xu, true),
      xseq: view.getBigUint64(nextOffset + K.bookSnapshot.trailer.offsets.xseq, true),
    },
  };
}

/** Decodes a `body_kind: 2` (book_delta) binary frame body. */
export function decodeBookDelta(buf: ArrayBufferView): DecodedBookDelta {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.BOOK_DELTA) {
    throw new BinaryFrameError(
      `expected body_kind=2 (book_delta), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const { levels } = decodeBookLevels(view, COMMON_HEADER_BYTES, header);
  return { header, levels };
}

export interface TradeFlags {
  blockTrade: boolean;
  liquidationOrigin: boolean;
  clusterAggregated: boolean;
}

export interface DecodedTrade {
  tsMs: bigint;
  price: string;
  size: string;
  side: "buy" | "sell";
  flags: TradeFlags;
}

export interface DecodedTrades {
  header: BinaryFrameHeader;
  trades: DecodedTrade[];
}

const TRADE = K.trades.record;
const TRADE_RECORD_BYTES = TRADE.bytes;

/** Decodes a `body_kind: 3` (trades) binary frame body. */
export function decodeTrades(buf: ArrayBufferView): DecodedTrades {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.TRADES) {
    throw new BinaryFrameError(
      `expected body_kind=3 (trades), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  assertFits(
    header.recordCount,
    TRADE_RECORD_BYTES,
    view.byteLength - COMMON_HEADER_BYTES,
    "trades",
  );
  const trades: DecodedTrade[] = [];
  let cursor = COMMON_HEADER_BYTES;
  for (let i = 0; i < header.recordCount; i += 1) {
    if (cursor + TRADE_RECORD_BYTES > view.byteLength) {
      throw new BinaryFrameError(
        `trade record ${i} runs past the buffer (record_count=${header.recordCount})`,
      );
    }
    const tsOffsetMs = view.getUint32(cursor + TRADE.offsets.tsOffsetMs, true);
    const price = view.getBigInt64(cursor + TRADE.offsets.price, true);
    const size = view.getBigUint64(cursor + TRADE.offsets.size, true);
    const sideByte = view.getUint8(cursor + TRADE.offsets.side);
    if (sideByte !== 0 && sideByte !== 1) {
      throw new BinaryFrameError(`invalid trade side byte ${sideByte} at record ${i}`);
    }
    const flagsByte = view.getUint8(cursor + TRADE.offsets.flags);
    trades.push({
      tsMs: header.tsBaseMs + BigInt(tsOffsetMs),
      price: unscale(price, header.priceScale),
      size: unscale(size, header.qtyScale),
      side: sideByte === 0 ? "buy" : "sell",
      flags: {
        blockTrade: (flagsByte & 0b0001) !== 0,
        liquidationOrigin: (flagsByte & 0b0010) !== 0,
        clusterAggregated: (flagsByte & 0b0100) !== 0,
      },
    });
    cursor += TRADE_RECORD_BYTES;
  }
  return { header, trades };
}

export interface DecodedBar {
  /** ADR-0033 series generation; with `index`, the §8.2 coalescing key. */
  generation: bigint;
  index: bigint;
  tsMs: bigint;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  turnover: string;
  trades: number;
  delta: string;
  /** bit0 `confirm` — this bar is closed and will not be revised further. */
  confirmed: boolean;
}

export interface DecodedBars {
  header: BinaryFrameHeader;
  bars: DecodedBar[];
}

const BAR = K.bars.record;
export const BAR_RECORD_BYTES: number = BAR.bytes;

/** Decodes a `body_kind: 4` (bars) binary frame body. */
export function decodeBars(buf: ArrayBufferView): DecodedBars {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.BARS) {
    throw new BinaryFrameError(
      `expected body_kind=4 (bars), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  // Fixed stride (§3.4): exact length, trailing bytes are malformed too.
  const expected = COMMON_HEADER_BYTES + header.recordCount * BAR_RECORD_BYTES;
  if (view.byteLength !== expected) {
    throw new BinaryFrameError(
      `bars body is ${view.byteLength} bytes, expected ${expected} for record_count=${header.recordCount}`,
    );
  }
  const bars: DecodedBar[] = [];
  let cursor = COMMON_HEADER_BYTES;
  for (let i = 0; i < header.recordCount; i += 1) {
    if (cursor + BAR_RECORD_BYTES > view.byteLength) {
      throw new BinaryFrameError(
        `bar record ${i} runs past the buffer (record_count=${header.recordCount})`,
      );
    }
    const o = BAR.offsets;
    const generation = view.getBigUint64(cursor + o.generation, true);
    const index = view.getBigUint64(cursor + o.index, true);
    const tsOffsetMs = view.getUint32(cursor + o.tsOffsetMs, true);
    const open = view.getBigInt64(cursor + o.open, true);
    const h = view.getBigInt64(cursor + o.high, true);
    const l = view.getBigInt64(cursor + o.low, true);
    const c = view.getBigInt64(cursor + o.close, true);
    const v = view.getBigUint64(cursor + o.volume, true);
    const turnover = view.getBigUint64(cursor + o.turnover, true);
    const tradeCount = view.getUint32(cursor + o.trades, true);
    const delta = view.getBigInt64(cursor + o.delta, true);
    const flagsByte = view.getUint8(cursor + o.flags);
    bars.push({
      generation,
      index,
      tsMs: header.tsBaseMs + BigInt(tsOffsetMs),
      open: unscale(open, header.priceScale),
      high: unscale(h, header.priceScale),
      low: unscale(l, header.priceScale),
      close: unscale(c, header.priceScale),
      volume: unscale(v, header.qtyScale),
      turnover: unscale(turnover, header.qtyScale),
      trades: tradeCount,
      delta: unscale(delta, header.qtyScale),
      confirmed: (flagsByte & 0b0001) !== 0,
    });
    cursor += BAR_RECORD_BYTES;
  }
  return { header, bars };
}

export interface FootprintCellFlags {
  buyImbalance: boolean;
  sellImbalance: boolean;
  inStack: boolean;
  poc: boolean;
}

export interface FootprintCell {
  price: string;
  bidVolume: string;
  askVolume: string;
  trades: number;
  flags: FootprintCellFlags;
}

export interface FootprintGroup {
  /** ADR-0033 series generation; with `index`, the §8.2 bar key (#2529). */
  generation: bigint;
  index: bigint;
  tsMs: bigint;
  /** Group flags bit0 `confirm`: this bar is closed. Reserved bits 1-7 are ignored (§3.4). */
  confirmed: boolean;
  cells: FootprintCell[];
}

export interface DecodedFootprint {
  header: BinaryFrameHeader;
  groups: FootprintGroup[];
}

const FP = K.footprint;
const GP = FP.groupPrefix.offsets;
/**
 * One group prefix (v2): u64 generation, u64 index, u32 ts_offset_ms, u32 cell_count, u8 flags,
 * then 3 reserved bytes.
 */
export const FOOTPRINT_GROUP_PREFIX_BYTES: number = FP.groupPrefix.bytes;
const FOOTPRINT_CELL_BYTES = FP.record.bytes;

/**
 * Decodes a `body_kind: 5` (footprint) binary frame body. `record_count` in
 * the common header is the number of per-bar groups, per §3.4.
 */
export function decodeFootprint(buf: ArrayBufferView): DecodedFootprint {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.FOOTPRINT) {
    throw new BinaryFrameError(
      `expected body_kind=5 (footprint), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  assertFits(
    header.recordCount,
    FOOTPRINT_GROUP_PREFIX_BYTES,
    view.byteLength - COMMON_HEADER_BYTES,
    "footprint groups",
  );
  const groups: FootprintGroup[] = [];
  let cursor = COMMON_HEADER_BYTES;
  for (let g = 0; g < header.recordCount; g += 1) {
    if (cursor + FOOTPRINT_GROUP_PREFIX_BYTES > view.byteLength) {
      throw new BinaryFrameError(
        `footprint group ${g} prefix runs past the buffer (record_count=${header.recordCount})`,
      );
    }
    const generation = view.getBigUint64(cursor + GP.generation, true);
    const index = view.getBigUint64(cursor + GP.index, true);
    const tsOffsetMs = view.getUint32(cursor + GP.tsOffsetMs, true);
    const cellCount = view.getUint32(cursor + GP.cellCount, true);
    const groupFlags = view.getUint8(cursor + GP.flags);
    cursor += FOOTPRINT_GROUP_PREFIX_BYTES;
    assertFits(cellCount, FOOTPRINT_CELL_BYTES, view.byteLength - cursor, `footprint group ${g}`);
    const cells: FootprintCell[] = [];
    for (let i = 0; i < cellCount; i += 1) {
      if (cursor + FOOTPRINT_CELL_BYTES > view.byteLength) {
        throw new BinaryFrameError(
          `footprint cell ${i} in group ${g} runs past the buffer (cell_count=${cellCount})`,
        );
      }
      const co = FP.record.offsets;
      const price = view.getBigInt64(cursor + co.price, true);
      const bidVolume = view.getBigUint64(cursor + co.bidVolume, true);
      const askVolume = view.getBigUint64(cursor + co.askVolume, true);
      const tradeCount = view.getUint32(cursor + co.trades, true);
      const flagsByte = view.getUint8(cursor + co.flags);
      cells.push({
        price: unscale(price, header.priceScale),
        bidVolume: unscale(bidVolume, header.qtyScale),
        askVolume: unscale(askVolume, header.qtyScale),
        trades: tradeCount,
        flags: {
          buyImbalance: (flagsByte & 0b0001) !== 0,
          sellImbalance: (flagsByte & 0b0010) !== 0,
          inStack: (flagsByte & 0b0100) !== 0,
          poc: (flagsByte & 0b1000) !== 0,
        },
      });
      cursor += FOOTPRINT_CELL_BYTES;
    }
    groups.push({
      generation,
      index,
      tsMs: header.tsBaseMs + BigInt(tsOffsetMs),
      confirmed: (groupFlags & 0b0001) !== 0,
      cells,
    });
  }
  return { header, groups };
}

export interface HeatmapRow {
  bidSize: string;
  askSize: string;
}

export interface DecodedHeatmapColumn {
  header: BinaryFrameHeader;
  tsMs: bigint;
  priceMin: string;
  priceStep: string;
  rows: HeatmapRow[];
}

const HM = K.heatmapColumn;
const HEATMAP_COLUMN_PREFIX_BYTES = HM.bodyPrefix.bytes;
const HEATMAP_ROW_BYTES = HM.record.bytes;

/** Decodes a `body_kind: 6` (heatmap_column) binary frame body. */
export function decodeHeatmapColumn(buf: ArrayBufferView): DecodedHeatmapColumn {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.HEATMAP_COLUMN) {
    throw new BinaryFrameError(
      `expected body_kind=6 (heatmap_column), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  if (COMMON_HEADER_BYTES + HEATMAP_COLUMN_PREFIX_BYTES > view.byteLength) {
    throw new BinaryFrameError("heatmap column body shorter than its fixed prefix");
  }
  let cursor = COMMON_HEADER_BYTES;
  const tsOffsetMs = view.getUint32(cursor + HM.bodyPrefix.offsets.tsOffsetMs, true);
  const priceMin = view.getBigInt64(cursor + HM.bodyPrefix.offsets.priceMin, true);
  const priceStep = view.getBigInt64(cursor + HM.bodyPrefix.offsets.priceStep, true);
  const rowCount = view.getUint32(cursor + HM.bodyPrefix.offsets.rowCount, true);
  cursor += HEATMAP_COLUMN_PREFIX_BYTES;
  assertFits(rowCount, HEATMAP_ROW_BYTES, view.byteLength - cursor, "heatmap rows");
  const rows: HeatmapRow[] = [];
  for (let i = 0; i < rowCount; i += 1) {
    if (cursor + HEATMAP_ROW_BYTES > view.byteLength) {
      throw new BinaryFrameError(`heatmap row ${i} runs past the buffer (row_count=${rowCount})`);
    }
    rows.push({
      bidSize: unscale(
        view.getBigUint64(cursor + HM.record.offsets.bidSize, true),
        header.qtyScale,
      ),
      askSize: unscale(
        view.getBigUint64(cursor + HM.record.offsets.askSize, true),
        header.qtyScale,
      ),
    });
    cursor += HEATMAP_ROW_BYTES;
  }
  return {
    header,
    tsMs: header.tsBaseMs + BigInt(tsOffsetMs),
    priceMin: unscale(priceMin, header.priceScale),
    priceStep: unscale(priceStep, header.priceScale),
    rows,
  };
}

/** A decoded value does not fit the generated §14 type (a JS `number`). */
export class StructuredRangeError extends Error {
  constructor(
    readonly field: string,
    readonly value: bigint | number,
  ) {
    super(
      `${field}=${String(value)} exceeds Number.MAX_SAFE_INTEGER; not representable as §14 number`,
    );
    this.name = "StructuredRangeError";
  }
}

const MAX_SAFE = BigInt(Number.MAX_SAFE_INTEGER);

function safeInt(field: string, v: bigint): number {
  if (v > MAX_SAFE) throw new StructuredRangeError(field, v);
  return Number(v);
}

/** Heatmap row sizes are `number[]` in §14; refuse magnitudes a double cannot hold exactly. */
function safeSize(field: string, decimal: string): number {
  const n = Number(decimal);
  if (!Number.isFinite(n) || Math.abs(n) > Number.MAX_SAFE_INTEGER) {
    throw new StructuredRangeError(field, n);
  }
  return n;
}

type Gen<T, K extends keyof T> = Pick<T, K>;
type Item<T, K extends keyof T> = T[K] extends readonly (infer U)[] ? U : never;

export type StructuredBook = Gen<
  generated.ws.BookSymbolDepth,
  "bids" | "asks" | "coalesced" | "price_scale" | "qty_scale" | "xu" | "xseq"
>;
export type StructuredTrades = Gen<generated.ws.TradesSymbol, "trades">;
export type StructuredBars = Gen<generated.ws.BarsSymbolBarTypeParam, "bars" | "coalesced">;
export type StructuredFootprint = Gen<generated.ws.FootprintSymbolBarTypeParam, "bars"> & {
  coalesced: boolean;
};
export type StructuredHeatmap = Gen<generated.ws.HeatmapSymbol, "columns" | "estimated">;
/** Generated item types, for consumers that want a single record. */
export type StructuredBar = Item<generated.ws.BarsSymbolBarTypeParam, "bars">;

const bookSide = (levels: BookLevel[], side: "bid" | "ask"): [string, string][] =>
  levels.filter((l) => l.side === side).map((l): [string, string] => [l.price, l.size]);

function bookStructured(
  d: DecodedBookSnapshot | DecodedBookDelta,
  trailer: BookSnapshotTrailer | undefined,
): StructuredBook {
  const h = d.header;
  const out: StructuredBook = {
    price_scale: h.priceScale,
    qty_scale: h.qtyScale,
    bids: bookSide(d.levels, "bid"),
    asks: bookSide(d.levels, "ask"),
    coalesced: h.flags.coalesced,
  };
  // xu/xseq are diagnostics-only (§14.1); a u64 above 2**53 is omitted rather than rounded.
  if (trailer !== undefined) {
    if (trailer.xu <= MAX_SAFE) out.xu = Number(trailer.xu);
    if (trailer.xseq <= MAX_SAFE) out.xseq = Number(trailer.xseq);
  }
  return out;
}

/**
 * Maps a decoded CVWB frame onto the GENERATED §14 item types (topic fields such as `symbol`
 * are not on the wire, hence `Pick`). Prices/sizes are decimal strings; epoch-ms, generation
 * and index are converted to `number` and throw {@link StructuredRangeError} above 2**53-1.
 *
 * This is an equivalence / debug utility proving binary == §14 JSON. It is NOT the render hot
 * path: it allocates per record, against the ADR-0005 zero-copy intent. Struct-of-arrays
 * consumption stays an open question in #2042.
 */
export function toStructured(d: DecodedBookSnapshot): StructuredBook;
export function toStructured(d: DecodedBookDelta): StructuredBook;
export function toStructured(d: DecodedTrades): StructuredTrades;
export function toStructured(d: DecodedBars): StructuredBars;
export function toStructured(d: DecodedFootprint): StructuredFootprint;
export function toStructured(d: DecodedHeatmapColumn): StructuredHeatmap;
export function toStructured(
  d:
    | DecodedBookSnapshot
    | DecodedBookDelta
    | DecodedTrades
    | DecodedBars
    | DecodedFootprint
    | DecodedHeatmapColumn,
): StructuredBook | StructuredTrades | StructuredBars | StructuredFootprint | StructuredHeatmap {
  const h = d.header;
  switch (h.bodyKind) {
    case BODY_KIND.BOOK_SNAPSHOT:
      return bookStructured(d as DecodedBookSnapshot, (d as DecodedBookSnapshot).trailer);
    case BODY_KIND.BOOK_DELTA:
      return bookStructured(d as DecodedBookDelta, undefined);
    case BODY_KIND.TRADES:
      return {
        trades: (d as DecodedTrades).trades.map((t) => ({
          ts_ms: safeInt("ts_ms", t.tsMs),
          price: t.price,
          size: t.size,
          side: t.side,
          is_block_trade: t.flags.blockTrade,
          is_liquidation: t.flags.liquidationOrigin,
        })),
      };
    case BODY_KIND.BARS:
      return {
        bars: (d as DecodedBars).bars.map((b) => ({
          generation: safeInt("generation", b.generation),
          index: safeInt("index", b.index),
          t_ms: safeInt("t_ms", b.tsMs),
          o: b.open,
          h: b.high,
          l: b.low,
          c: b.close,
          v: b.volume,
          turnover: b.turnover,
          trades: b.trades,
          delta: b.delta,
          confirm: b.confirmed,
        })),
        coalesced: h.flags.coalesced,
      };
    case BODY_KIND.FOOTPRINT:
      return {
        bars: (d as DecodedFootprint).groups.map((g) => ({
          generation: safeInt("generation", g.generation),
          index: safeInt("index", g.index),
          t_ms: safeInt("t_ms", g.tsMs),
          confirm: g.confirmed,
          cells: g.cells.map((c) => ({
            price: c.price,
            bid_volume: c.bidVolume,
            ask_volume: c.askVolume,
            trades: c.trades,
            is_poc: c.flags.poc,
          })),
        })),
        coalesced: h.flags.coalesced,
      };
    default: {
      const c = d as DecodedHeatmapColumn;
      return {
        columns: [
          {
            t_ms: safeInt("t_ms", c.tsMs),
            price_min: c.priceMin,
            price_step: c.priceStep,
            bids: c.rows.map((r) => safeSize("bids", r.bidSize)),
            asks: c.rows.map((r) => safeSize("asks", r.askSize)),
          },
        ],
        estimated: h.flags.estimated,
      };
    }
  }
}
