// E17-T02 part B: decode benchmarks vs 23 section 16.3 (book delta 50 levels <0.15 ms p99,
// footprint 400 cells <1 ms p99). Run by the perf project WITHOUT coverage. Absolute bounds are
// the section 16.3 hard-fail figures (huge margin); linear scaling is asserted as a ratio.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { COMMON_HEADER_BYTES, decodeBookDelta, decodeFootprint } from "../src/runtime/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const seeds = JSON.parse(
  readFileSync(join(HERE, "../../../tests/fuzz/ws-frames/corpus.json"), "utf8"),
) as { name: string; hex: string }[];
const header = (name: string): Uint8Array => {
  const seed = seeds.find((s) => s.name === name);
  if (!seed) throw new Error(`missing corpus seed ${name}`);
  return Uint8Array.from(Buffer.from(seed.hex, "hex")).subarray(0, COMMON_HEADER_BYTES);
};

/** book_delta frame (kind 2) with n 17-byte records (side u8, price i64, size u64). */
function delta(n: number): Uint8Array {
  const out = new Uint8Array(COMMON_HEADER_BYTES + n * 17);
  out.set(header("zero-length-delta"));
  const v = new DataView(out.buffer);
  v.setUint32(12, n, true);
  for (let i = 0; i < n; i++) {
    const o = COMMON_HEADER_BYTES + i * 17;
    v.setUint8(o, i % 2);
    v.setBigInt64(o + 1, BigInt(6_500_000 + i), true);
    v.setBigUint64(o + 9, BigInt(1000 + i), true);
  }
  return out;
}

/** footprint frame (kind 5, v2): one 28-byte group prefix, then `cells` 33-byte cells. */
function footprint(cells: number): Uint8Array {
  const prefix = 28; // u64 generation, u64 index, u32 ts_offset_ms, u32 cell_count, u8 flags, pad3
  const stride = 33;
  const out = new Uint8Array(COMMON_HEADER_BYTES + prefix + cells * stride);
  out.set(header("footprint-empty-group"));
  const v = new DataView(out.buffer);
  v.setUint32(12, 1, true);
  v.setUint32(COMMON_HEADER_BYTES + 20, cells, true);
  for (let i = 0; i < cells; i++) {
    v.setBigInt64(COMMON_HEADER_BYTES + prefix + i * stride, BigInt(6_500_000 + i), true);
  }
  return out;
}

function bestMs(fn: () => unknown, rounds = 15, inner = 20): number {
  let best = Infinity;
  for (let r = 0; r < rounds; r++) {
    const t0 = performance.now();
    for (let i = 0; i < inner; i++) fn();
    best = Math.min(best, (performance.now() - t0) / inner);
  }
  return best;
}

describe("CVWB decode performance (§16.3)", () => {
  it("fixtures decode (guards the builders against layout drift)", () => {
    expect(decodeBookDelta(delta(50)).levels).toHaveLength(50);
    expect(decodeFootprint(footprint(400)).groups[0]?.cells).toHaveLength(400);
  });

  it("book delta, 50 levels, is far inside the 0.5 ms hard fail", () => {
    const d = delta(50);
    for (let i = 0; i < 200; i++) decodeBookDelta(d);
    const t = bestMs(() => decodeBookDelta(d));
    console.info(`book delta 50 levels: ${t.toFixed(4)} ms (best of 15)`);
    expect(t).toBeGreaterThan(0);
    expect(t).toBeLessThan(0.5);
  });

  it("footprint, 400 cells, is far inside the 3 ms hard fail", () => {
    const d = footprint(400);
    for (let i = 0; i < 200; i++) decodeFootprint(d);
    const t = bestMs(() => decodeFootprint(d));
    console.info(`footprint 400 cells: ${t.toFixed(4)} ms (best of 15)`);
    expect(t).toBeGreaterThan(0);
    expect(t).toBeLessThan(3);
  });

  it("decode time scales linearly with record_count (x8 records < x20 time)", () => {
    const a = delta(100);
    const b = delta(800);
    for (let i = 0; i < 100; i++) {
      decodeBookDelta(a);
      decodeBookDelta(b);
    }
    const ratio = bestMs(() => decodeBookDelta(b)) / bestMs(() => decodeBookDelta(a));
    console.info(`x8 records -> x${ratio.toFixed(2)} time`);
    expect(ratio).toBeLessThan(20);
  });
});
