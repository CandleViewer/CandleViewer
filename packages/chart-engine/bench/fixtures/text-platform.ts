// A procedural `TextPlatform` (E11-S11 PR A): the deterministic stand-in rasteriser the atlas
// tests and bench scenes run on (the E06-K03 shape). No font is read from the system, nothing is
// downloaded: a "face" is a seed taken from the bytes, so different bytes draw different glyphs.
import { fnv64Hex } from "../../src/text/hash.js";
import type { ChartFont, GlyphRaster, KvStore, TextPlatform } from "../../src/text/platform.js";

/** An in-memory `KvStore` (IndexedDB's shape) that counts its calls. */
export class MemoryKv implements KvStore {
  readonly map = new Map<string, unknown>();
  readonly calls = { get: 0, put: 0, delete: 0 };
  /** The keys `put` wrote, in order. */
  readonly puts: string[] = [];
  /** How many times the connection was closed. */
  closes = 0;
  close(): void {
    this.closes += 1;
  }
  async get(key: string): Promise<unknown> {
    this.calls.get += 1;
    return this.map.get(key);
  }
  async put(key: string, value: unknown): Promise<void> {
    this.calls.put += 1;
    this.puts.push(key);
    this.map.set(key, value);
  }
  async keys(): Promise<string[]> {
    return [...this.map.keys()];
  }
  async delete(key: string): Promise<void> {
    this.calls.delete += 1;
    this.map.delete(key);
  }
}

export interface ProceduralOptions {
  /** Codepoints each family's "cmap" lacks, by family name. */
  readonly missing?: Readonly<Record<string, readonly number[]>>;
  readonly failLoad?: boolean;
  /** A codepoint whose raster throws. */
  readonly failRaster?: number;
  /** The store `store()` yields (default: a fresh MemoryKv); a function may throw or hang. */
  readonly store?: KvStore | null | (() => Promise<KvStore | null>);
}

export type ProceduralPlatform = TextPlatform & {
  rasters: number;
  loads: number;
  releases: number;
  kv: KvStore | null;
};

/** Two fonts the atlas configuration matches (mono 400, ui 600), with distinct bytes. */
export const TEST_FONTS: readonly ChartFont[] = [
  { family: "JetBrains Mono", weight: 400, bytes: Uint8Array.of(7, 1, 2, 3).buffer },
  { family: "Inter", weight: 600, bytes: Uint8Array.of(11, 5, 8, 13).buffer },
];

/** A glyph box of the ink plus `pad`; the pattern follows the codepoint and the face's seed. */
export function proceduralRaster(seed: number, ch: string, px: number, pad: number): GlyphRaster {
  const cp = ch.codePointAt(0) ?? 0;
  const iw = Math.round(px * 0.6);
  const [w, h] = [iw + 2 * pad, px + 2 * pad];
  const coverage = new Uint8Array(w * h);
  for (let y = 0; y < px && cp !== 0x20; y += 1) {
    for (let x = 0; x < iw; x += 1) {
      const stem = x < 3 || x >= iw - 3;
      const bar = y < 3 || y >= px - 3 || Math.abs(y - px / 2) < 1.5;
      const on =
        (stem && ((cp >> (y % 7)) & 1) === 1) ||
        (bar && (((cp + seed) >> (x % 5)) & 1) === 1) ||
        x === (y + seed) % iw;
      if (on) coverage[(y + pad) * w + x + pad] = 255;
    }
  }
  return { w, h, coverage, advance: iw + 1, bearingX: -pad, bearingY: -px - pad };
}

export function proceduralPlatform(opts: ProceduralOptions = {}): ProceduralPlatform {
  const kv =
    opts.store === undefined
      ? new MemoryKv()
      : typeof opts.store === "function"
        ? null
        : opts.store;
  const p: ProceduralPlatform = {
    rasters: 0,
    loads: 0,
    releases: 0,
    kv,
    async loadFace(font: ChartFont) {
      p.loads += 1;
      if (opts.failLoad === true) throw new Error("bad font bytes");
      return { seed: new Uint8Array(font.bytes)[0] ?? 0 };
    },
    releaseFace() {
      p.releases += 1;
    },
    rasterize(face: unknown, ch: string, px: number, pad: number) {
      p.rasters += 1;
      if (ch.codePointAt(0) === opts.failRaster) throw new Error("raster fault");
      return proceduralRaster((face as { seed: number }).seed, ch, px, pad);
    },
    cmapHas: (font: ChartFont, cp: number) => !(opts.missing?.[font.family] ?? []).includes(cp),
    digest: async (bytes: ArrayBuffer) => `fnv64:${fnv64Hex(new Uint8Array(bytes))}`,
    store: typeof opts.store === "function" ? opts.store : async () => kv,
  };
  return p;
}
