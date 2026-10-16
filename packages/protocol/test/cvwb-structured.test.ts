// E17-T02 follow-up (#2042 part A): a decoded binary frame mapped by toStructured() equals the
// §14 JSON twin the Python encoder side renders (packages/fixtures/golden/cvwb/structured.json),
// typed against the GENERATED §14 types (no casts).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  decodeBars,
  decodeBookDelta,
  decodeBookSnapshot,
  decodeFootprint,
  decodeHeatmapColumn,
  decodeTrades,
  StructuredRangeError,
  toStructured,
  type StructuredBars,
  type StructuredBook,
  type StructuredFootprint,
  type StructuredHeatmap,
  type StructuredTrades,
} from "../src/runtime/index.js";

const dir = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "fixtures", "golden", "cvwb");
const read = (f: string): unknown => JSON.parse(readFileSync(join(dir, f), "utf8"));

interface Vec {
  name: string;
  hex: string;
  body_kind: number;
}
type Twin =
  | { name: string; body_kind: 1 | 2; structured: StructuredBook }
  | { name: string; body_kind: 3; structured: StructuredTrades }
  | { name: string; body_kind: 4; structured: StructuredBars }
  | { name: string; body_kind: 5; structured: StructuredFootprint }
  | { name: string; body_kind: 6; structured: StructuredHeatmap };

const isVecs = (v: unknown): v is Vec[] => Array.isArray(v);
const isTwins = (v: unknown): v is Twin[] => Array.isArray(v);
const rawVectors = read("vectors.json");
const rawTwins = read("structured.json");
if (!isVecs(rawVectors) || !isTwins(rawTwins)) throw new Error("bad fixtures");
const vectors = rawVectors;
const twins = rawTwins;

const bytes = (hex: string): Uint8Array => Uint8Array.from(Buffer.from(hex, "hex"));

/** Typed per kind: each branch compares against the generated-type twin. */
function structuredOf(v: Vec): unknown {
  const buf = bytes(v.hex);
  switch (v.body_kind) {
    case 1:
      return toStructured(decodeBookSnapshot(buf));
    case 2:
      return toStructured(decodeBookDelta(buf));
    case 3:
      return toStructured(decodeTrades(buf));
    case 4:
      return toStructured(decodeBars(buf));
    case 5:
      return toStructured(decodeFootprint(buf));
    default:
      return toStructured(decodeHeatmapColumn(buf));
  }
}

/** Builds a frame by patching a golden vector's bytes at `offset` (little-endian u64). */
function patchU64(hex: string, offset: number, value: bigint): Uint8Array {
  const b = bytes(hex);
  new DataView(b.buffer).setBigUint64(offset, value, true);
  return b;
}

describe("toStructured() equals the §14 JSON twin", () => {
  it("has a twin for every vector and covers all six kinds", () => {
    expect(twins.map((t) => t.name)).toEqual(vectors.map((v) => v.name));
    expect(new Set(twins.map((t) => t.body_kind))).toEqual(new Set([1, 2, 3, 4, 5, 6]));
  });
  it.each(vectors.map((v, i) => [v.name, v, twins[i]] as const))("%s", (_n, v, twin) => {
    if (v.name === "heatmap_column") {
      // The vector carries a u64-extreme row size (> 2**53): §14 types it `number`, so the
      // guarded conversion must refuse it rather than round silently.
      expect(() => structuredOf(v)).toThrow(StructuredRangeError);
      return;
    }
    expect(structuredOf(v)).toEqual(twin?.structured);
  });
  it("emits prices and sizes as exact decimal strings, never numbers", () => {
    const v = vectors.find((x) => x.body_kind === 3);
    if (v === undefined) throw new Error("no trades vector");
    for (const t of toStructured(decodeTrades(bytes(v.hex))).trades) {
      expect(t.price).toMatch(/^-?[0-9]+(\.[0-9]+)?$/);
      expect(t.size).toMatch(/^-?[0-9]+(\.[0-9]+)?$/);
    }
  });
});

describe("toStructured() range checks", () => {
  const trades = vectors.find((x) => x.body_kind === 3);
  const bars = vectors.find((x) => x.name === "bars_v2");
  it("throws StructuredRangeError when ts_base_ms exceeds MAX_SAFE_INTEGER", () => {
    if (trades === undefined) throw new Error("no trades vector");
    const buf = patchU64(trades.hex, 16, BigInt(Number.MAX_SAFE_INTEGER) + 1n);
    expect(() => toStructured(decodeTrades(buf))).toThrow(StructuredRangeError);
  });
  it("accepts exactly MAX_SAFE_INTEGER and rejects one above for bar generation", () => {
    if (bars === undefined) throw new Error("no bars vector");
    // first bar record: generation is the first u64 after the 24-byte header.
    const ok = toStructured(decodeBars(patchU64(bars.hex, 24, BigInt(Number.MAX_SAFE_INTEGER))));
    expect(ok.bars[0]?.generation).toBe(Number.MAX_SAFE_INTEGER);
    const bad = patchU64(bars.hex, 24, BigInt(Number.MAX_SAFE_INTEGER) + 1n);
    expect(() => toStructured(decodeBars(bad))).toThrow(StructuredRangeError);
  });
  const footprint = vectors.find((x) => x.name === "footprint");
  // first group prefix (v2, #2529): u64 generation at 24, u64 index at 32.
  it.each([
    ["generation", 24],
    ["index", 32],
  ] as const)("accepts MAX_SAFE_INTEGER and rejects one above for footprint %s", (key, at) => {
    if (footprint === undefined) throw new Error("no footprint vector");
    const max = BigInt(Number.MAX_SAFE_INTEGER);
    const ok = toStructured(decodeFootprint(patchU64(footprint.hex, at, max)));
    expect(ok.bars[0]?.[key]).toBe(Number.MAX_SAFE_INTEGER);
    const bad = patchU64(footprint.hex, at, max + 1n);
    expect(() => toStructured(decodeFootprint(bad))).toThrow(StructuredRangeError);
  });
});
