// `atlas-build` and `atlas-cache` scenes (E11-S11 PR A, BQ-275). `atlas-build` is the cold path on
// the procedural stand-in rasteriser (raster, EDT, pack): informational only, as the real cost is
// the font's (K2 gates it in PR C). `atlas-cache` is the warm path's CPU side on a record of the
// K01 size: key, shape, FNV-1a checksum and every slot's bounds, gated at <= 1 ms. Neither imports the prototypes.
import { glyphSdf, packAtlas, sources, type AtlasImage } from "../../src/text/atlas-build.js";
import {
  cacheKey,
  decodeRecord,
  encodeRecord,
  type AtlasRecord,
} from "../../src/text/atlas-cache.js";
import { ATLAS_CONFIG } from "../../src/text/config.js";
import { atlasGlyphs, glyphSetHash } from "../../src/text/glyph-set.js";
import { proceduralPlatform, TEST_FONTS } from "../fixtures/text-platform.js";

const glyphs = atlasGlyphs(ATLAS_CONFIG);

/** One cold build of all 194 glyphs, synchronously. */
export function buildAtlas(): AtlasImage {
  const p = proceduralPlatform({ store: null });
  const faces = TEST_FONTS.map((f) => ({ seed: new Uint8Array(f.bytes)[0] ?? 0 }));
  const src = sources(p, TEST_FONTS, glyphs);
  return packAtlas(
    ATLAS_CONFIG,
    glyphs.map((g, i) => glyphSdf(p, ATLAS_CONFIG, faces, g, src[i] as number)),
  );
}

export class AtlasCacheBench {
  readonly record: AtlasRecord;
  private readonly digests = ["sha256:" + "ab".repeat(32), "sha256:" + "cd".repeat(32)];

  constructor(image: AtlasImage = buildAtlas()) {
    this.record = encodeRecord(image, this.key());
  }

  private key(): string {
    return cacheKey(ATLAS_CONFIG, this.digests, glyphSetHash(ATLAS_CONFIG));
  }

  /** The cache read's CPU work: the key, then the record's shape, checksum and slot bounds. */
  step(): boolean {
    return decodeRecord(this.record, ATLAS_CONFIG, glyphs.length, this.key()) !== null;
  }
}
