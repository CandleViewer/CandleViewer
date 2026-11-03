// E11-Q02 (#444, BQ-05): the named fixtures of E11-Q01 plan section 6, as seeded generators.
//
// Provenance: these are SYNTHETIC. The recorded corpus (C-13.5, packages/fixtures/bybit) holds no
// 100 000-bar session, and nothing here pretends to be a Bybit capture or invents an exchange payload:
// "btcusdt-*" names the price scale (BTCUSDT's 1-minute shape), not a source. Bars come from a seeded
// mulberry32 random walk with slow volatility clustering (the shape of the engine bench's generator,
// written out here rather than imported: the bench is not a declared export of the engine package);
// the same name and seed give byte-identical output (engine-harness.test.ts hashes it). Prices are integer ticks from `priceOrigin`.
export const FIXTURE_NAMES = ["btcusdt-1m-100k"] as const;
export type FixtureName = (typeof FIXTURE_NAMES)[number];

export const SEED = 20260928;
export const BAR_MS = 60_000;
export const START_MS = Date.UTC(2026, 0, 1);
const ORIGIN = 6_000_000;

export interface Bars {
  readonly name: FixtureName;
  readonly time: Float64Array; // µs epoch
  readonly open: Int32Array;
  readonly high: Int32Array;
  readonly low: Int32Array;
  readonly close: Int32Array;
  readonly volume: Float32Array;
  readonly priceOrigin: number;
  readonly tickSize: number;
  /** Trailing bars the first viewport shows. */
  readonly initialVisible: number;
}

interface Row {
  tMs: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

/** mulberry32: the same sequence on every platform and Node version. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A random walk in absolute ticks around ORIGIN with a clustered volatility regime. */
export function walk(count: number, seed = SEED): Row[] {
  const rng = mulberry32(seed);
  let price = ORIGIN;
  let regime = 1;
  return Array.from({ length: count }, (_, i) => {
    regime = Math.min(4, Math.max(0.3, regime + (rng() - 0.5) * 0.08));
    const o = price;
    let hi = o;
    let lo = o;
    for (let s = 0; s < 4; s += 1) {
      price += Math.round((rng() - 0.5) * 60 * regime);
      hi = Math.max(hi, price);
      lo = Math.min(lo, price);
    }
    return {
      tMs: START_MS + i * BAR_MS,
      o,
      h: hi,
      l: lo,
      c: price,
      v: 1 + Math.round(rng() * 5000 * regime),
    };
  });
}

function pack(name: FixtureName, rows: readonly Row[], origin: number, visible: number): Bars {
  const col = <T extends Int32Array | Float64Array | Float32Array>(
    A: new (n: number) => T,
    f: (r: Row) => number,
  ): T => {
    const a = new A(rows.length);
    rows.forEach((r, i) => (a[i] = f(r)));
    return a;
  };
  return {
    name,
    time: col(Float64Array, (r) => r.tMs * 1000),
    open: col(Int32Array, (r) => r.o - origin),
    high: col(Int32Array, (r) => r.h - origin),
    low: col(Int32Array, (r) => r.l - origin),
    close: col(Int32Array, (r) => r.c - origin),
    volume: col(Float32Array, (r) => r.v),
    priceOrigin: origin,
    tickSize: 1,
    initialVisible: visible,
  };
}

export function buildFixture(name: FixtureName): Bars {
  return pack(name, walk(100_000), ORIGIN, 200);
}
