// E17-T02: Python-encoded CVWB vectors decode exactly in TS, and the SR-155
// fuzz corpus (tests/fuzz/ws-frames/corpus.json) is accepted/rejected exactly
// as declared — the same expectations the Python decoder is held to.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CVWB_KINDS } from "../src/generated/cvwb/index.js";
import {
  BinaryFrameError,
  decodeBars,
  decodeBookDelta,
  decodeBookSnapshot,
  decodeFootprint,
  decodeHeatmapColumn,
  decodeTrades,
  FrameMalformedError,
  parseBinaryFrameHeader,
  unscale,
} from "../src/runtime/index.js";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const readJson = <T>(rel: string): T => JSON.parse(readFileSync(join(repo, rel), "utf8")) as T;

interface Vector {
  name: string;
  hex: string;
  body_kind: number;
  flags: number;
  price_scale: number;
  qty_scale: number;
  ts_base_ms: string;
  records: string[][];
  trailer: string[] | null;
  prefix: string[] | null;
  /** body_kind 5: `[[generation, index, ts_offset_ms, flags], cells]` per group (v2, #2529). */
  groups: [string[], string[][]][] | null;
}

const vectors = readJson<Vector[]>("packages/fixtures/golden/cvwb/vectors.json");
const seeds = readJson<{ name: string; expect: "ok" | "malformed"; hex: string }[]>(
  "tests/fuzz/ws-frames/corpus.json",
);

const bytes = (hex: string): Uint8Array => Uint8Array.from(Buffer.from(hex, "hex"));

/** Dispatches on body_kind (the header is parsed — and validated — first). */
function decodeAny(buf: Uint8Array): unknown {
  const decoders = [
    decodeBookSnapshot,
    decodeBookDelta,
    decodeTrades,
    decodeBars,
    decodeFootprint,
    decodeHeatmapColumn,
  ];
  const { bodyKind } = parseBinaryFrameHeader(buf);
  const decoder = decoders[bodyKind - 1];
  if (decoder === undefined) throw new BinaryFrameError(`no decoder for ${bodyKind}`);
  return decoder(buf);
}

const flagBits = (f: {
  estimated: boolean;
  coalesced: boolean;
  replay: boolean;
  partial: boolean;
}) => (f.estimated ? 1 : 0) | (f.coalesced ? 2 : 0) | (f.replay ? 4 : 0) | (f.partial ? 8 : 0);
const bit = (b: boolean, i: number): number => (b ? 1 << i : 0);

/** Re-expresses a TS decode in the vector's raw (scaled-int string) shape. */
function normalise(v: Vector): Pick<Vector, "records" | "trailer" | "prefix" | "groups"> {
  const buf = bytes(v.hex);
  const ps = v.price_scale;
  const qs = v.qty_scale;
  const p = (raw: string): string => unscale(BigInt(raw), ps);
  const q = (raw: string): string => unscale(BigInt(raw), qs);
  const base = BigInt(v.ts_base_ms);
  const t = (raw: string): bigint => base + BigInt(raw);
  switch (v.body_kind) {
    case CVWB_KINDS.bookSnapshot.id:
    case CVWB_KINDS.bookDelta.id: {
      const snap = v.body_kind === 1 ? decodeBookSnapshot(buf) : null;
      const d = snap ?? decodeBookDelta(buf);
      expect(d.levels).toEqual(
        v.records.map(([s, pr, sz]) => ({
          side: s === "0" ? "bid" : "ask",
          price: p(pr!),
          size: q(sz!),
        })),
      );
      const trailer = snap ? [String(snap.trailer.xu), String(snap.trailer.xseq)] : null;
      return { records: v.records, trailer, prefix: null, groups: null };
    }
    case CVWB_KINDS.trades.id: {
      const d = decodeTrades(buf);
      const records = d.trades.map((tr, i) => {
        const src = v.records[i]!;
        expect([tr.tsMs, tr.price, tr.size]).toEqual([t(src[0]!), p(src[1]!), q(src[2]!)]);
        const f = tr.flags;
        const flags =
          bit(f.blockTrade, 0) | bit(f.liquidationOrigin, 1) | bit(f.clusterAggregated, 2);
        return [src[0]!, src[1]!, src[2]!, tr.side === "buy" ? "0" : "1", String(flags)];
      });
      return { records, trailer: null, prefix: null, groups: null };
    }
    case CVWB_KINDS.bars.id: {
      const d = decodeBars(buf);
      const records = d.bars.map((b, i) => {
        const s = v.records[i]!;
        expect(b).toEqual({
          generation: BigInt(s[0]!),
          index: BigInt(s[1]!),
          tsMs: t(s[2]!),
          open: p(s[3]!),
          high: p(s[4]!),
          low: p(s[5]!),
          close: p(s[6]!),
          volume: q(s[7]!),
          turnover: q(s[8]!),
          trades: Number(s[9]),
          delta: q(s[10]!),
          confirmed: (Number(s[11]) & 1) === 1,
        });
        return s;
      });
      return { records, trailer: null, prefix: null, groups: null };
    }
    case CVWB_KINDS.footprint.id: {
      const d = decodeFootprint(buf);
      const groups = d.groups.map((g, gi): [string[], string[][]] => {
        const [prefix, cells] = v.groups![gi]!;
        const [generation, index, ts, flags] = prefix;
        expect([g.generation, g.index, g.tsMs, g.confirmed]).toEqual([
          BigInt(generation!),
          BigInt(index!),
          t(ts!),
          (Number(flags) & 1) === 1,
        ]);
        return [
          // Vectors send reserved flag bits as 0 (§3.4), so bit0 alone rebuilds the byte.
          [String(g.generation), String(g.index), ts!, g.confirmed ? "1" : "0"],
          g.cells.map((c, ci) => {
            const s = cells[ci]!;
            expect([c.price, c.bidVolume, c.askVolume, c.trades]).toEqual([
              p(s[0]!),
              q(s[1]!),
              q(s[2]!),
              Number(s[3]),
            ]);
            const f = c.flags;
            return [
              s[0]!,
              s[1]!,
              s[2]!,
              s[3]!,
              String(
                bit(f.buyImbalance, 0) |
                  bit(f.sellImbalance, 1) |
                  bit(f.inStack, 2) |
                  bit(f.poc, 3),
              ),
            ];
          }),
        ];
      });
      return { records: [], trailer: null, prefix: null, groups };
    }
    default: {
      const d = decodeHeatmapColumn(buf);
      const [ts, min, step] = v.prefix!;
      expect([d.tsMs, d.priceMin, d.priceStep]).toEqual([t(ts!), p(min!), p(step!)]);
      expect(d.rows).toEqual(v.records.map(([b, a]) => ({ bidSize: q(b!), askSize: q(a!) })));
      return { records: v.records, trailer: null, prefix: v.prefix, groups: null };
    }
  }
}

describe("CVWB vectors: Python encode -> TS decode", () => {
  it("covers all six body kinds", () => {
    expect(new Set(vectors.map((v) => v.body_kind))).toEqual(new Set([1, 2, 3, 4, 5, 6]));
  });
  it.each(vectors.map((v) => [v.name, v] as const))("%s decodes exactly", (_name, v) => {
    const header = parseBinaryFrameHeader(bytes(v.hex));
    expect(header.bodyKind).toBe(v.body_kind);
    expect(flagBits(header.flags)).toBe(v.flags);
    expect([header.priceScale, header.qtyScale, header.tsBaseMs]).toEqual([
      v.price_scale,
      v.qty_scale,
      BigInt(v.ts_base_ms),
    ]);
    const { records, trailer, prefix, groups } = v;
    expect(normalise(v)).toEqual({ records, trailer, prefix, groups });
  });
});

describe("SR-155 fuzz corpus (tests/fuzz/ws-frames)", () => {
  it("has at least 40 seeds", () => {
    expect(seeds.length).toBeGreaterThanOrEqual(40);
  });
  it.each(seeds.map((s) => [s.name, s] as const))("%s behaves as declared", (_name, s) => {
    let got: "ok" | "malformed" = "ok";
    try {
      decodeAny(bytes(s.hex));
    } catch (e) {
      expect(e).toBeInstanceOf(FrameMalformedError);
      got = "malformed";
    }
    expect(got).toBe(s.expect);
  });
});
