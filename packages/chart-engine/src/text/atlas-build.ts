// Atlas generation (E11-S11): rasterise each family through the platform, run the EDT, pack
// every slot into one R8 texture's rows and write per-glyph metrics. A glyph a family's cmap
// lacks is borrowed from the other family; missing from both is a coverage failure (K01 item 1).
import type { AtlasConfig } from "./config.js";
import { sdfFromCoverage } from "./edt.js";
import type { GlyphEntry } from "./glyph-set.js";
import type { ChartFont, TextPlatform } from "./platform.js";
import { shelfPack } from "./shelf-packer.js";

/** `details.atlasReason` of `ENGINE_ATLAS_GENERATION_FAILED` (BQ-272): codes, never prose. */
export type AtlasReason = "no-font" | "font-load" | "coverage" | "overflow" | "raster";

export class AtlasBuildError extends Error {
  constructor(
    readonly reason: AtlasReason,
    message: string,
  ) {
    super(message);
    this.name = "AtlasBuildError";
  }
}

/** Floats per glyph in `metrics`: x, y, w, h (atlas px), advance, bearingX, bearingY, source. */
export const METRIC_STRIDE = 8;

/** The CPU atlas: the packed rows of a width × height R8 texture, and the metrics. */
export interface AtlasImage {
  readonly width: number;
  readonly height: number;
  readonly usedHeight: number;
  /** width × usedHeight bytes; the rows below are zero. */
  readonly rows: Uint8Array;
  /** One `METRIC_STRIDE` row per slot, in `atlasGlyphs` order. */
  readonly metrics: Float32Array;
  readonly occupancyPct: number;
}

/** One rasterised slot. */
export interface GlyphSdf {
  readonly cp: number;
  readonly source: number;
  readonly w: number;
  readonly h: number;
  readonly sdf: Uint8Array;
  readonly advance: number;
  readonly bearingX: number;
  readonly bearingY: number;
}

/** The family each slot is drawn from: its own, else the other that has it (BQ-180). */
export function sources(
  platform: TextPlatform,
  fonts: readonly ChartFont[],
  glyphs: readonly GlyphEntry[],
): number[] {
  return glyphs.map(({ family, cp, ch }) => {
    const order = [family, ...fonts.keys()].filter((f, i, a) => a.indexOf(f) === i);
    const src = order.find((f) => platform.cmapHas(fonts[f] as ChartFont, cp));
    if (src === undefined) throw new AtlasBuildError("coverage", `no font maps U+${hex(cp)} ${ch}`);
    return src;
  });
}

const hex = (cp: number): string => cp.toString(16).toUpperCase().padStart(4, "0");

/** Rasterises and distance-transforms one slot at its own family's size and spread. */
export function glyphSdf(
  platform: TextPlatform,
  cfg: AtlasConfig,
  faces: readonly unknown[],
  entry: GlyphEntry,
  source: number,
): GlyphSdf {
  const fam = cfg.families[entry.family];
  if (fam === undefined) throw new AtlasBuildError("raster", `no family ${entry.family}`);
  const r = platform.rasterize(faces[source], entry.ch, fam.rasterPx, fam.spread);
  const ok = Number.isInteger(r.w) && Number.isInteger(r.h) && r.w > 0 && r.h > 0;
  if (!ok || r.coverage.length !== r.w * r.h) {
    throw new AtlasBuildError("raster", `bad raster for U+${hex(entry.cp)}`);
  }
  const sdf = sdfFromCoverage(r.coverage, r.w, r.h, fam.spread, cfg.edt === "f32");
  const { w, h, advance, bearingX, bearingY } = r;
  return { cp: entry.cp, source, w, h, sdf, advance, bearingX, bearingY };
}

/** Packs every slot into the texture's rows; an overflow fails, never grows (BQ-263). */
export function packAtlas(cfg: AtlasConfig, slots: readonly GlyphSdf[]): AtlasImage {
  const packed = shelfPack(slots, cfg.width, cfg.height, cfg.pad);
  if (packed === null) {
    throw new AtlasBuildError(
      "overflow",
      `${slots.length} glyphs exceed ${cfg.width}x${cfg.height}`,
    );
  }
  const { width } = cfg;
  const rows = new Uint8Array(width * packed.usedHeight);
  const metrics = new Float32Array(slots.length * METRIC_STRIDE);
  slots.forEach((g, i) => {
    const [x, y] = [packed.x[i] as number, packed.y[i] as number];
    for (let r = 0; r < g.h; r += 1)
      rows.set(g.sdf.subarray(r * g.w, (r + 1) * g.w), (y + r) * width + x);
    metrics.set([x, y, g.w, g.h, g.advance, g.bearingX, g.bearingY, g.source], i * METRIC_STRIDE);
  });
  const { usedHeight, occupancyPct } = packed;
  return { width, height: cfg.height, usedHeight, rows, metrics, occupancyPct };
}

/** F-03: true when `g` is byte-identical to slot `i` of `img` (metrics and SDF rows). */
export function matchesSlot(img: AtlasImage, i: number, g: GlyphSdf): boolean {
  const m = img.metrics.subarray(i * METRIC_STRIDE, (i + 1) * METRIC_STRIDE);
  const want = [g.w, g.h, g.advance, g.bearingX, g.bearingY, g.source];
  if (want.some((v, k) => Math.fround(v) !== m[k + 2])) return false;
  const [x, y] = [m[0] as number, m[1] as number];
  // Defence in depth (decodeRecord checks it too): the compared rectangle is the drawn one.
  const inside = Number.isInteger(x) && Number.isInteger(y) && x >= 0 && y >= 0;
  if (!inside || x + g.w > img.width || y + g.h > img.usedHeight) return false;
  for (let r = 0; r < g.h; r += 1) {
    const at = (y + r) * img.width + x;
    for (let c = 0; c < g.w; c += 1) if (img.rows[at + c] !== g.sdf[r * g.w + c]) return false;
  }
  return true;
}
