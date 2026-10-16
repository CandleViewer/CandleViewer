import { describe, expect, it } from "vitest";
import {
  BINARY_FRAME_MAGIC,
  BinaryFrameError,
  BODY_KIND,
  COMMON_HEADER_BYTES,
  BAR_RECORD_BYTES,
  FOOTPRINT_FORMAT_VERSION,
  FOOTPRINT_GROUP_PREFIX_BYTES,
  decodeBars,
  decodeBookDelta,
  decodeBookSnapshot,
  decodeFootprint,
  decodeHeatmapColumn,
  decodeTrades,
  parseBinaryFrameHeader,
  toStructured,
  unscale,
} from "../src/runtime/index.js";

/** Builds a valid 24-byte common header (§3.4) with the given overrides. */
function buildHeader(opts: {
  bodyKind: number;
  priceScale?: number;
  qtyScale?: number;
  recordCount: number;
  tsBaseMs?: bigint;
  flags?: number;
}): DataView {
  const buf = new ArrayBuffer(COMMON_HEADER_BYTES);
  const view = new DataView(buf);
  view.setUint32(0, BINARY_FRAME_MAGIC, true);
  view.setUint8(4, 1); // format_version
  view.setUint8(5, opts.bodyKind);
  view.setUint8(6, opts.flags ?? 0);
  view.setUint8(7, opts.priceScale ?? 2);
  view.setUint8(8, opts.qtyScale ?? 3);
  view.setUint8(9, 0);
  view.setUint8(10, 0);
  view.setUint8(11, 0);
  view.setUint32(12, opts.recordCount, true);
  view.setBigUint64(16, opts.tsBaseMs ?? 0n, true);
  return view;
}

function concatBuffers(...parts: ArrayBufferView[]): Uint8Array {
  const total = parts.reduce((sum, p) => sum + p.byteLength, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const p of parts) {
    out.set(new Uint8Array(p.buffer, p.byteOffset, p.byteLength), offset);
    offset += p.byteLength;
  }
  return out;
}

describe("unscale", () => {
  it("converts a positive scaled integer to a decimal string", () => {
    expect(unscale(123456n, 2)).toBe("1234.56");
  });
  it("converts a negative scaled integer to a decimal string", () => {
    expect(unscale(-500n, 2)).toBe("-5.00");
  });
  it("pads fractional digits with leading zeros", () => {
    expect(unscale(100005n, 2)).toBe("1000.05");
  });
  it("returns a whole number string when scale is 0", () => {
    expect(unscale(42n, 0)).toBe("42");
  });
});

describe("parseBinaryFrameHeader", () => {
  it("parses a well-formed header", () => {
    const view = buildHeader({ bodyKind: 1, recordCount: 0, tsBaseMs: 1789132262104n });
    const header = parseBinaryFrameHeader(view);
    expect(header.magic).toBe(BINARY_FRAME_MAGIC);
    expect(header.formatVersion).toBe(1);
    expect(header.bodyKind).toBe(1);
    expect(header.priceScale).toBe(2);
    expect(header.qtyScale).toBe(3);
    expect(header.recordCount).toBe(0);
    expect(header.tsBaseMs).toBe(1789132262104n);
    expect(header.flags).toEqual({
      estimated: false,
      coalesced: false,
      replay: false,
      partial: false,
    });
  });

  it("decodes every flag bit independently", () => {
    const view = buildHeader({ bodyKind: 1, recordCount: 0, flags: 0b1111 });
    const header = parseBinaryFrameHeader(view);
    expect(header.flags).toEqual({
      estimated: true,
      coalesced: true,
      replay: true,
      partial: true,
    });
  });

  it("rejects a buffer shorter than the common header", () => {
    const short = new Uint8Array(10);
    expect(() => parseBinaryFrameHeader(short)).toThrow(BinaryFrameError);
  });

  it("rejects a bad magic number", () => {
    const view = buildHeader({ bodyKind: 1, recordCount: 0 });
    view.setUint32(0, 0xdeadbeef, true);
    expect(() => parseBinaryFrameHeader(view)).toThrow(/bad magic/);
  });

  it("rejects an unknown body_kind", () => {
    const view = buildHeader({ bodyKind: 9, recordCount: 0 });
    expect(() => parseBinaryFrameHeader(view)).toThrow(/unknown body_kind/);
  });
});

describe("decodeBookSnapshot / decodeBookDelta", () => {
  function buildBookRecord(side: 0 | 1, price: bigint, size: bigint): Uint8Array {
    const buf = new ArrayBuffer(17);
    const view = new DataView(buf);
    view.setUint8(0, side);
    view.setBigInt64(1, price, true);
    view.setBigUint64(9, size, true);
    return new Uint8Array(buf);
  }

  it("round-trips a book snapshot with its xu/xseq trailer", () => {
    const header = buildHeader({ bodyKind: BODY_KIND.BOOK_SNAPSHOT, recordCount: 2 });
    const rec1 = buildBookRecord(0, 5000000n, 100000n);
    const rec2 = buildBookRecord(1, 5001000n, 50000n);
    const trailer = new ArrayBuffer(16);
    new DataView(trailer).setBigUint64(0, 111n, true);
    new DataView(trailer).setBigUint64(8, 222n, true);
    const frame = concatBuffers(header, rec1, rec2, new Uint8Array(trailer));

    const decoded = decodeBookSnapshot(frame);
    expect(decoded.levels).toEqual([
      { side: "bid", price: "50000.00", size: "100.000" },
      { side: "ask", price: "50010.00", size: "50.000" },
    ]);
    expect(decoded.trailer).toEqual({ xu: 111n, xseq: 222n });
  });

  it("treats size 0 as a level deletion marker, not an error", () => {
    const header = buildHeader({ bodyKind: BODY_KIND.BOOK_DELTA, recordCount: 1 });
    const rec = buildBookRecord(0, 5000000n, 0n);
    const frame = concatBuffers(header, rec);
    const decoded = decodeBookDelta(frame);
    expect(decoded.levels[0]?.size).toBe("0.000");
  });

  it("rejects a snapshot whose body disagrees with record_count", () => {
    const header = buildHeader({ bodyKind: BODY_KIND.BOOK_SNAPSHOT, recordCount: 2 });
    const rec1 = buildBookRecord(0, 5000000n, 100000n);
    const frame = concatBuffers(header, rec1); // only 1 of 2 records present, no trailer
    expect(() => decodeBookSnapshot(frame)).toThrow(BinaryFrameError);
  });

  it("rejects a body_kind mismatch", () => {
    const header = buildHeader({ bodyKind: BODY_KIND.TRADES, recordCount: 0 });
    expect(() => decodeBookSnapshot(header)).toThrow(/expected body_kind=1/);
  });
});

describe("decodeTrades", () => {
  it("decodes trade records including flags and aggressor side", () => {
    const header = buildHeader({
      bodyKind: BODY_KIND.TRADES,
      recordCount: 1,
      tsBaseMs: 1000n,
    });
    const rec = new ArrayBuffer(22);
    const rv = new DataView(rec);
    rv.setUint32(0, 500, true); // ts_offset_ms
    rv.setBigInt64(4, 4200000n, true); // price
    rv.setBigUint64(12, 1500n, true); // size
    rv.setUint8(20, 1); // side = sell
    rv.setUint8(21, 0b0101); // block trade + cluster-aggregated
    const frame = concatBuffers(header, new Uint8Array(rec));

    const decoded = decodeTrades(frame);
    expect(decoded.trades).toEqual([
      {
        tsMs: 1500n,
        price: "42000.00",
        size: "1.500",
        side: "sell",
        flags: { blockTrade: true, liquidationOrigin: false, clusterAggregated: true },
      },
    ]);
  });
});

function barRecord(generation: bigint, index: bigint, close: bigint, confirm: number): Uint8Array {
  const rec = new ArrayBuffer(BAR_RECORD_BYTES);
  const rv = new DataView(rec);
  rv.setBigUint64(0, generation, true);
  rv.setBigUint64(8, index, true);
  rv.setUint32(16, 60000, true); // ts_offset_ms
  rv.setBigInt64(20, 100000n, true); // o
  rv.setBigInt64(28, 110000n, true); // h
  rv.setBigInt64(36, 90000n, true); // l
  rv.setBigInt64(44, close, true); // c
  rv.setBigUint64(52, 200000n, true); // v
  rv.setBigUint64(60, 400000n, true); // turnover
  rv.setUint32(68, 42, true); // trades
  rv.setBigInt64(72, -5000n, true); // delta
  rv.setUint8(80, confirm); // confirm
  return new Uint8Array(rec);
}

function barsHeader(recordCount: number, version = 2): DataView {
  const header = buildHeader({ bodyKind: BODY_KIND.BARS, recordCount, tsBaseMs: 0n });
  header.setUint8(4, version);
  return header;
}

describe("decodeBars", () => {
  it("uses 85-byte records", () => {
    expect(BAR_RECORD_BYTES).toBe(85);
  });

  it("round-trips generation/index and decodes a confirmed bar record", () => {
    const frame = concatBuffers(barsHeader(1), barRecord(7n, 2n ** 40n, 105000n, 1));
    const decoded = decodeBars(frame);
    expect(decoded.bars).toEqual([
      {
        generation: 7n,
        index: 2n ** 40n,
        tsMs: 60000n,
        open: "1000.00",
        high: "1100.00",
        low: "900.00",
        close: "1050.00",
        volume: "200.000",
        turnover: "400.000",
        trades: 42,
        delta: "-5.000",
        confirmed: true,
      },
    ]);
  });

  it("keeps same-open-time bars distinct by index", () => {
    const frame = concatBuffers(
      barsHeader(2),
      barRecord(0n, 0n, 105000n, 1),
      barRecord(0n, 1n, 106000n, 0),
    );
    const { bars } = decodeBars(frame);
    expect(bars.map((b) => b.index)).toEqual([0n, 1n]);
    expect(bars[0]?.tsMs).toBe(bars[1]?.tsMs);
  });

  it("rejects v1 (69-byte) bars with a typed error", () => {
    const frame = concatBuffers(barsHeader(1, 1), new Uint8Array(69));
    expect(() => decodeBars(frame)).toThrow(BinaryFrameError);
    try {
      decodeBars(frame);
    } catch (e) {
      expect((e as BinaryFrameError).code).toBe("unsupported_format_version");
    }
  });

  it("rejects an unknown format_version", () => {
    const frame = concatBuffers(barsHeader(1, 9), barRecord(0n, 0n, 1n, 0));
    expect(() => decodeBars(frame)).toThrow(/format_version/);
  });

  it("rejects trailing bytes and a count/length mismatch", () => {
    const trailing = concatBuffers(barsHeader(1), barRecord(0n, 0n, 1n, 0), new Uint8Array(7));
    expect(() => decodeBars(trailing)).toThrow(BinaryFrameError);
    const extra = concatBuffers(barsHeader(0), barRecord(0n, 0n, 1n, 0));
    expect(() => decodeBars(extra)).toThrow(BinaryFrameError);
    const huge = concatBuffers(barsHeader(0xffffffff), barRecord(0n, 0n, 1n, 0));
    expect(() => decodeBars(huge)).toThrow(BinaryFrameError);
  });

  it("rejects a truncated record", () => {
    const frame = concatBuffers(barsHeader(1), new Uint8Array(69));
    expect(() => decodeBars(frame)).toThrow(BinaryFrameError);
  });
});

/** The `BinaryFrameError` code `fn` throws, `"untyped"` for any other throw, `undefined` if none. */
function errorCode(fn: () => unknown): string | undefined {
  try {
    fn();
  } catch (e) {
    return e instanceof BinaryFrameError ? e.code : "untyped";
  }
  return undefined;
}

function footprintCell(price: bigint, bid: bigint, ask: bigint, flags: number): Uint8Array {
  const buf = new ArrayBuffer(33);
  const v = new DataView(buf);
  v.setBigInt64(0, price, true);
  v.setBigUint64(8, bid, true);
  v.setBigUint64(16, ask, true);
  v.setUint32(24, 10, true); // trades
  v.setUint8(28, flags);
  return new Uint8Array(buf);
}

/**
 * One v2 group (#2529): u64 generation, u64 index, u32 ts_offset_ms, u32 cell_count, u8 flags
 * (bit0 confirm), 3 reserved zero bytes, then the cells.
 */
function footprintGroup(
  generation: bigint,
  index: bigint,
  tsOffsetMs: number,
  cells: Uint8Array[],
  flags = 0,
): Uint8Array {
  const prefix = new ArrayBuffer(28);
  const gv = new DataView(prefix);
  gv.setBigUint64(0, generation, true);
  gv.setBigUint64(8, index, true);
  gv.setUint32(16, tsOffsetMs, true);
  gv.setUint32(20, cells.length, true);
  gv.setUint8(24, flags);
  return concatBuffers(new Uint8Array(prefix), ...cells);
}

function footprintHeader(groupCount: number, version = 2): DataView {
  const header = buildHeader({ bodyKind: BODY_KIND.FOOTPRINT, recordCount: groupCount });
  header.setUint8(4, version);
  return header;
}

describe("decodeFootprint", () => {
  it("uses format_version 2 and 28-byte group prefixes", () => {
    expect(FOOTPRINT_FORMAT_VERSION).toBe(2);
    expect(FOOTPRINT_GROUP_PREFIX_BYTES).toBe(28);
  });

  it("round-trips generation/index and decodes one bar group with two cells", () => {
    const cell1 = footprintCell(100000n, 5000n, 1000n, 0b1000); // POC
    const cell2 = footprintCell(100100n, 500n, 6000n, 0b0010); // sell imbalance
    const group = footprintGroup(7n, 2n ** 40n, 60000, [cell1, cell2], 1); // closed
    const decoded = decodeFootprint(concatBuffers(footprintHeader(1), group));
    expect(decoded.groups).toHaveLength(1);
    expect(decoded.groups[0]?.generation).toBe(7n);
    expect(decoded.groups[0]?.index).toBe(2n ** 40n);
    expect(decoded.groups[0]?.tsMs).toBe(60000n);
    expect(decoded.groups[0]?.confirmed).toBe(true);
    expect(decoded.groups[0]?.cells).toEqual([
      {
        price: "1000.00",
        bidVolume: "5.000",
        askVolume: "1.000",
        trades: 10,
        flags: { buyImbalance: false, sellImbalance: false, inStack: false, poc: true },
      },
      {
        price: "1001.00",
        bidVolume: "0.500",
        askVolume: "6.000",
        trades: 10,
        flags: { buyImbalance: false, sellImbalance: true, inStack: false, poc: false },
      },
    ]);
  });

  it("reads u64-extreme generation and index exactly, per group", () => {
    const frame = concatBuffers(
      footprintHeader(2),
      footprintGroup(2n ** 64n - 1n, 2n ** 63n, 1, []),
      footprintGroup(1n, 2n ** 64n - 1n, 2, [footprintCell(1n, 1n, 1n, 0)]),
    );
    const { groups } = decodeFootprint(frame);
    expect(groups.map((g) => [g.generation, g.index, g.tsMs])).toEqual([
      [2n ** 64n - 1n, 2n ** 63n, 1n],
      [1n, 2n ** 64n - 1n, 2n],
    ]);
  });

  it("keeps same-open-time bars distinct by index (#2529)", () => {
    const frame = concatBuffers(
      footprintHeader(2),
      footprintGroup(0n, 5n, 900, [footprintCell(100000n, 5000n, 0n, 0)], 1), // bar N, closed
      footprintGroup(0n, 6n, 900, [footprintCell(100000n, 0n, 7000n, 0)], 0), // bar N+1, forming
    );
    const { groups } = decodeFootprint(frame);
    expect(groups.map((g) => g.index)).toEqual([5n, 6n]);
    expect(groups[0]?.tsMs).toBe(groups[1]?.tsMs);
    const { bars } = toStructured(decodeFootprint(frame));
    expect(bars.map((b) => [b.generation, b.index, b.t_ms, b.confirm, b.cells.length])).toEqual([
      [0, 5, 900, true, 1],
      [0, 6, 900, false, 1],
    ]);
  });

  it("maps group flags bit0 to confirmed and ignores reserved bits 1-7 (§3.4)", () => {
    const frame = concatBuffers(
      footprintHeader(4),
      footprintGroup(0n, 1n, 0, [], 0b0000_0000),
      footprintGroup(0n, 2n, 0, [], 0b0000_0001),
      footprintGroup(0n, 3n, 0, [], 0b1111_1110),
      footprintGroup(0n, 4n, 0, [], 0b1111_1111),
    );
    const decoded = decodeFootprint(frame);
    expect(decoded.groups.map((g) => g.confirmed)).toEqual([false, true, false, true]);
    expect(toStructured(decoded).bars.map((b) => b.confirm)).toEqual([false, true, false, true]);
  });

  it("rejects a v1 footprint body (8-byte group prefix) with a typed error", () => {
    const v1 = new DataView(new ArrayBuffer(8));
    v1.setUint32(0, 60000, true); // ts_offset_ms
    v1.setUint32(4, 1, true); // cell_count
    const cell = footprintCell(100000n, 1n, 1n, 0);
    const frame = concatBuffers(footprintHeader(1, 1), v1, cell);
    expect(errorCode(() => decodeFootprint(frame))).toBe("unsupported_format_version");
  });

  it("rejects an unknown format_version", () => {
    const frame = concatBuffers(footprintHeader(1, 9), footprintGroup(0n, 0n, 0, []));
    expect(() => decodeFootprint(frame)).toThrow(/format_version/);
  });

  it("rejects a truncated group prefix, a v1-sized group and a truncated cell", () => {
    const group = footprintGroup(0n, 7n, 60000, [footprintCell(1n, 1n, 1n, 0)]);
    const prefix27 = concatBuffers(footprintHeader(1), group.subarray(0, 27));
    expect(errorCode(() => decodeFootprint(prefix27))).toBe("frame_malformed");
    const v1Sized = concatBuffers(footprintHeader(1), new Uint8Array(8));
    expect(errorCode(() => decodeFootprint(v1Sized))).toBe("frame_malformed");
    const shortCell = concatBuffers(footprintHeader(1), group.subarray(0, group.byteLength - 1));
    expect(errorCode(() => decodeFootprint(shortCell))).toBe("frame_malformed");
  });

  it("refuses the group count up front at the 28-byte v2 stride (SR-128)", () => {
    // Two groups in 48 bytes would pass a 24-byte (pre-flags) or 8-byte (v1) stride and only fail
    // later, per group, with "prefix runs past the buffer"; the message names the up-front check.
    const frame = concatBuffers(footprintHeader(2), new Uint8Array(48));
    expect(() => decodeFootprint(frame)).toThrow(/footprint groups: count=2 x 28 bytes exceeds/);
  });

  it("ignores trailing bytes after the last group (variable layout, §3.4)", () => {
    const frame = concatBuffers(
      footprintHeader(1),
      footprintGroup(3n, 4n, 5, []),
      new Uint8Array(8),
    );
    const { groups } = decodeFootprint(frame);
    expect(groups).toEqual([{ generation: 3n, index: 4n, tsMs: 5n, confirmed: false, cells: [] }]);
  });
});

describe("decodeHeatmapColumn", () => {
  it("decodes a column with its row grid", () => {
    const header = buildHeader({
      bodyKind: BODY_KIND.HEATMAP_COLUMN,
      recordCount: 1,
      tsBaseMs: 0n,
    });
    const prefix = new ArrayBuffer(24);
    const pv = new DataView(prefix);
    pv.setUint32(0, 30000, true); // ts_offset_ms
    pv.setBigInt64(4, 90000n, true); // price_min
    pv.setBigInt64(12, 100n, true); // price_step
    pv.setUint32(20, 2, true); // row_count

    function buildRow(bid: bigint, ask: bigint): Uint8Array {
      const buf = new ArrayBuffer(16);
      const v = new DataView(buf);
      v.setBigUint64(0, bid, true);
      v.setBigUint64(8, ask, true);
      return new Uint8Array(buf);
    }

    const row1 = buildRow(1000n, 2000n);
    const row2 = buildRow(3000n, 4000n);
    const frame = concatBuffers(header, new Uint8Array(prefix), row1, row2);

    const decoded = decodeHeatmapColumn(frame);
    expect(decoded.tsMs).toBe(30000n);
    expect(decoded.priceMin).toBe("900.00");
    expect(decoded.priceStep).toBe("1.00");
    expect(decoded.rows).toEqual([
      { bidSize: "1.000", askSize: "2.000" },
      { bidSize: "3.000", askSize: "4.000" },
    ]);
  });

  it("rejects a column shorter than its fixed prefix", () => {
    const header = buildHeader({
      bodyKind: BODY_KIND.HEATMAP_COLUMN,
      recordCount: 1,
    });
    expect(() => decodeHeatmapColumn(header)).toThrow(BinaryFrameError);
  });
});
