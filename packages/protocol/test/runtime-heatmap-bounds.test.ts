// E21-X02 (#652; 23 §3.4, AC-HM-04): the client's heatmap column decoder refuses a `row_count` above
// the grid's 512 rows and a `price_step` of zero or less, as `frame_malformed`, before anything is
// read or sized from the wire, as the server's decoder does (tests/unit/ws/test_cvwb_heatmap_bounds.py).
// The shared fuzz corpus (tests/fuzz/ws-frames/corpus.json) runs the same cases on both decoders.
import { describe, expect, it } from "vitest";
import {
  BINARY_FRAME_MAGIC,
  BinaryFrameError,
  BODY_KIND,
  COMMON_HEADER_BYTES,
  HEATMAP_MAX_ROWS,
  decodeHeatmapColumn,
} from "../src/runtime/index.js";

const ROW_BYTES = 16;
const PREFIX_BYTES = 24;

/** One kind-6 frame: the header (one column), its prefix, then `bodyRows` rows of bytes. */
function column(rowCount: number, priceStep: bigint, bodyRows = rowCount): Uint8Array {
  const out = new Uint8Array(COMMON_HEADER_BYTES + PREFIX_BYTES + bodyRows * ROW_BYTES);
  const view = new DataView(out.buffer);
  view.setUint32(0, BINARY_FRAME_MAGIC, true);
  view.setUint8(4, 1); // format_version
  view.setUint8(5, BODY_KIND.HEATMAP_COLUMN);
  view.setUint8(7, 1); // price_scale
  view.setUint8(8, 3); // qty_scale
  view.setUint32(12, 1, true); // record_count: one column
  view.setBigInt64(COMMON_HEADER_BYTES + 4, 99_000n, true); // price_min
  view.setBigInt64(COMMON_HEADER_BYTES + 12, priceStep, true);
  view.setUint32(COMMON_HEADER_BYTES + 20, rowCount, true);
  return out;
}

function refusal(frame: Uint8Array): BinaryFrameError {
  try {
    decodeHeatmapColumn(frame);
  } catch (error) {
    if (error instanceof BinaryFrameError) return error;
    throw error;
  }
  throw new Error("the column was accepted");
}

describe("Malformed binary frame", () => {
  it("the grid's row bound is 512 (24 §6.1 rows)", () => {
    expect(HEATMAP_MAX_ROWS).toBe(512);
    expect(decodeHeatmapColumn(column(512, 1n)).rows).toHaveLength(512);
  });

  it("refuses a row_count above 512 before any row is read, whatever the body holds", () => {
    const error = refusal(column(513, 1n));
    expect(error.code).toBe("frame_malformed");
    expect(error.message).toBe("heatmap column row_count=513 is above the grid's 512 rows");
    for (const rowCount of [513, 0xffffffff]) {
      const short = refusal(column(rowCount, 1n, 0)); // rows the body lacks: SR-128's check first
      expect(short.code).toBe("frame_malformed");
      expect(short.message).toMatch(/exceeds/);
    }
  });

  it("refuses a price_step of zero or less", () => {
    for (const step of [0n, -1n, -(2n ** 63n)]) {
      const error = refusal(column(2, step));
      expect(error.code).toBe("frame_malformed");
      expect(error.message).toBe(`heatmap column price_step=${step} is not positive`);
    }
    expect(decodeHeatmapColumn(column(2, 1n)).priceStep).toBe("0.1");
  });

  it("refuses a column shorter than its rows, by one byte or by one row", () => {
    const full = column(3, 1n);
    expect(decodeHeatmapColumn(full).rows).toHaveLength(3);
    expect(refusal(full.subarray(0, full.byteLength - 1)).code).toBe("frame_malformed");
    expect(refusal(column(3, 1n, 2)).code).toBe("frame_malformed");
  });
});
