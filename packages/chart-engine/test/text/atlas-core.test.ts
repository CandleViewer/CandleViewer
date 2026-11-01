// E11-S11 PR A: the atlas's pure parts — EDT and SDF, the shelf packer, the glyph set, the hashes
// and the packed-rows cache record. Seeded loops stand in for property tests (no fast-check).
import { describe, expect, it, vi } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  bounded,
  cacheKey,
  checksum,
  decodeRecord,
  encodeRecord,
  RECORD_VERSION,
} from "../../src/text/atlas-cache.js";
import { METRIC_STRIDE, packAtlas } from "../../src/text/atlas-build.js";
import { ATLAS_CONFIG, type AtlasConfig } from "../../src/text/config.js";
import { edt2d, sdfFromCoverage } from "../../src/text/edt.js";
import { atlasGlyphs, glyphSetHash } from "../../src/text/glyph-set.js";
import { fnv1a, fnv1aHex, fnv64Hex } from "../../src/text/hash.js";
import { shelfPack } from "../../src/text/shelf-packer.js";

describe("edt: the two-pass Felzenszwalb transform", () => {
  it.each([false, true])("matches brute force on 60 seeded bitmaps up to 16×16 (f32 %s)", (f32) => {
    const next = mulberry32(20261031);
    for (let k = 0; k < 60; k += 1) {
      const [w, h] = [1 + Math.floor(next() * 16), 1 + Math.floor(next() * 16)];
      const zero = Array.from({ length: w * h }, (_, i) => i === 0 || next() < 0.1);
      const grid = f32 ? new Float32Array(w * h) : new Float64Array(w * h);
      zero.forEach((z, i) => (grid[i] = z ? 0 : 1e20));
      edt2d(grid, w, h, f32);
      const brute = Array.from({ length: w * h }, (_, i) => {
        let best = Infinity;
        zero.forEach((z, j) => {
          const d2 = ((i % w) - (j % w)) ** 2 + (Math.floor(i / w) - Math.floor(j / w)) ** 2;
          if (z) best = Math.min(best, d2);
        });
        return best;
      });
      expect(Array.from(grid), `bitmap ${k}`).toEqual(brute);
    }
  });

  it("sdf: inside above 128, the edge between 96 and 159, spread px maps to 0 and 255", () => {
    const [w, h, spread] = [16, 1, 4];
    const cov = Uint8Array.from({ length: w }, (_, x) => (x < 8 ? 255 : 0));
    const sdf = Array.from(sdfFromCoverage(cov, w, h, spread));
    expect(sdf.slice(6, 10)).toEqual([191, 159, 96, 64]);
    expect([sdf[0], sdf[15]]).toEqual([255, 0]);
    expect(sdf).toEqual([...sdf].sort((a, b) => b - a)); // monotone across the edge
  });
});

describe("shelf packer", () => {
  const items = (n: number, seed: number) => {
    const next = mulberry32(seed);
    return Array.from({ length: n }, (_, i) => ({
      w: 4 + Math.floor(next() * 30),
      h: 4 + Math.floor(next() * 30),
      cp: 32 + i,
    }));
  };

  it("places every item inside the texture without overlap, deterministically", () => {
    for (const seed of [1, 2, 3]) {
      const it = items(194, seed);
      const p = shelfPack(it, 1024, 1024, 1);
      expect(p).not.toBeNull();
      expect(shelfPack(it, 1024, 1024, 1)).toEqual(p);
      const rects = it.map((r, i) => [p?.x[i] ?? 0, p?.y[i] ?? 0, r.w, r.h] as const);
      const bad: number[] = [];
      for (const [i, [x, y, w, h]] of rects.entries()) {
        if (x + w > 1024 || y + h > (p?.usedHeight ?? 0)) bad.push(i);
        for (const [x2, y2, w2, h2] of rects.slice(i + 1)) {
          if (!(x + w <= x2 || x2 + w2 <= x || y + h <= y2 || y2 + h2 <= y)) bad.push(i);
        }
      }
      expect(bad, `seed ${seed}`).toEqual([]);
      const ink = it.reduce((s, r) => s + r.w * r.h, 0);
      expect(p?.occupancyPct).toBeCloseTo((100 * ink) / 1024 ** 2, 9);
    }
  });

  it("an overflow is null: the atlas never grows", () => {
    expect(shelfPack(items(194, 1), 64, 64, 1)).toBeNull();
    expect(shelfPack([{ w: 65, h: 1, cp: 65 }], 64, 64, 1)).toBeNull();
  });
});

describe("glyph set and hashes", () => {
  it("194 slots: printable ASCII per family, × ▲ ▼ for mono and · for ui", () => {
    const g = atlasGlyphs(ATLAS_CONFIG);
    expect(g).toHaveLength(194);
    expect(
      g
        .filter((e) => e.family === 0)
        .map((e) => e.ch)
        .slice(-3)
        .join(""),
    ).toBe("×▲▼");
    expect(g.at(-1)).toEqual({ family: 1, ch: "·", cp: 0xb7 });
    expect(glyphSetHash(ATLAS_CONFIG)).toBe(glyphSetHash({ ...ATLAS_CONFIG }));
    const swapped = { ...ATLAS_CONFIG, families: [...ATLAS_CONFIG.families].reverse() };
    expect(glyphSetHash(swapped)).not.toBe(glyphSetHash(ATLAS_CONFIG));
  });

  it("FNV-1a 32 and 64 match their reference vectors", () => {
    expect(fnv1aHex("a")).toBe("e40c292c");
    expect(fnv1a(Uint8Array.of(0x61))).toBe(0xe40c292c);
    expect(fnv64Hex(Uint8Array.of(0x61))).toBe("af63dc4c8601ec8c");
  });
});

describe("cache key and record", () => {
  const digests = ["sha256:aa", "sha256:bb"];
  const img = packAtlas(
    ATLAS_CONFIG,
    atlasGlyphs(ATLAS_CONFIG).map((g, i) => ({
      cp: g.cp,
      source: g.family,
      w: 10,
      h: 12,
      sdf: new Uint8Array(120).fill(i % 251),
      advance: 9,
      bearingX: -4,
      bearingY: -20,
    })),
  );

  it("every table field, each digest and the set hash change the key", () => {
    const key = (c: AtlasConfig, d = digests) => cacheKey(c, d, glyphSetHash(c));
    const fam0 = ATLAS_CONFIG.families[0];
    const fam = (o: object) => ({
      ...ATLAS_CONFIG,
      families: [{ ...fam0, ...o }, ATLAS_CONFIG.families[1]],
    });
    const variants = [
      key(ATLAS_CONFIG, ["sha256:ab", "sha256:bb"]),
      key({ ...ATLAS_CONFIG, generatorVersion: 2 }),
      key({ ...ATLAS_CONFIG, edt: "f32" }),
      key({ ...ATLAS_CONFIG, width: 512 }),
      key({ ...ATLAS_CONFIG, height: 512 }),
      key({ ...ATLAS_CONFIG, pad: 2 }),
      key(fam({ rasterPx: 16 }) as AtlasConfig),
      key(fam({ spread: 3 }) as AtlasConfig),
      key(fam({ weight: 500 }) as AtlasConfig),
      key(fam({ family: "Other" }) as AtlasConfig),
    ];
    expect(new Set([key(ATLAS_CONFIG), ...variants]).size).toBe(variants.length + 1);
  });

  it("a record round-trips; wrong shape, version, size or checksum decodes to null", () => {
    const rec = encodeRecord(img, "k");
    expect(decodeRecord(rec, ATLAS_CONFIG, 194, "k")).toEqual({ ...img });
    const flipped = rec.rows.slice();
    flipped[5] = (flipped[5] as number) ^ 1;
    const bad: unknown[] = [
      null,
      "x",
      { ...rec, v: RECORD_VERSION + 1 },
      { ...rec, usedHeight: 0 },
      { ...rec, usedHeight: 2048 },
      { ...rec, rows: rec.rows.subarray(1) },
      { ...rec, rows: Array.from(rec.rows) },
      { ...rec, metrics: rec.metrics.subarray(8) },
      { ...rec, rows: flipped },
      { ...rec, checksum: rec.checksum ^ 1 },
    ];
    for (const raw of bad) expect(decodeRecord(raw, ATLAS_CONFIG, 194, "k")).toBeNull();
    expect(checksum(flipped, rec.metrics, "k")).not.toBe(rec.checksum);
  });

  it("a record is bound to its key: under another key it decodes to null", () => {
    expect(decodeRecord(encodeRecord(img, "k"), ATLAS_CONFIG, 194, "k2")).toBeNull();
  });

  it("a slot outside the packed rows or with a non-finite metric decodes to null", () => {
    const at = (slot: number, k: number) => slot * METRIC_STRIDE + k;
    const set = (edits: [number, number][]) => {
      const metrics = img.metrics.slice();
      for (const [i, v] of edits) metrics[i] = v;
      return encodeRecord({ ...img, metrics }, "k"); // a recomputed checksum
    };
    const w = img.metrics[at(16, 2)] as number;
    const h = img.metrics[at(16, 3)] as number;
    const bad = [
      set([[at(16, 0), ATLAS_CONFIG.width - 1]]), // x + w past the right edge
      set([[at(16, 0), -1]]),
      set([[at(16, 1), img.usedHeight - h + 1]]), // y + h past the used rows
      set([[at(16, 0), 0.5]]),
      set([[at(16, 2), 0]]),
      set([[at(16, 4), Number.NaN]]),
      set([[at(16, 5), Number.POSITIVE_INFINITY]]),
      set([[at(16, 7), 2]]), // no third family
    ];
    expect(w).toBeGreaterThan(1);
    for (const raw of bad) expect(decodeRecord(raw, ATLAS_CONFIG, 194, "k")).toBeNull();
  });

  it("bounded: cancels its timer once the promise settles", async () => {
    const cancel = vi.fn();
    await expect(bounded(Promise.resolve(4), () => cancel)).resolves.toBe(4);
    await expect(bounded(Promise.reject(new Error("x")), () => cancel)).rejects.toThrow("x");
    expect(cancel).toHaveBeenCalledTimes(2);
  });

  it("bounded: resolves with the promise, rejects when the timer fires first", async () => {
    let fire: () => void = () => undefined;
    const timer = (cb: () => void) => void (fire = cb);
    await expect(bounded(Promise.resolve(4), timer)).resolves.toBe(4);
    const hung = bounded(new Promise<number>(() => undefined), timer, 250);
    fire();
    await expect(hung).rejects.toThrow("no answer in 250 ms");
  });
});
