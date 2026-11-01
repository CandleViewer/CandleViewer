// The SDF atlas configuration (E11-S11 PR A, BQ-260): every E11-K01 parameter in one table. Each
// field is part of the cache key (`atlas-cache.ts`), so the K1–K3 re-confirmation on the shipped
// fonts (PR C) is a table edit plus a `GENERATOR_VERSION` bump; nothing is frozen before it.
// Provisional values: ADR-0002 "O2 atlas configuration" and docs/plan/spikes/E11-K01.md.

/** Bumped on any change to the table, the EDT, the packer or the record (BQ-262). */
export const GENERATOR_VERSION = 1;

export interface FamilyConfig {
  /** `mono`: cells, axis ticks and GL pills; `ui`: the watermark (E11-D02 §6, D13). */
  readonly key: "mono" | "ui";
  /** Matched against `ChartFont.family` and `weight` (BQ-258). */
  readonly family: string;
  readonly weight: number;
  /** One raster per family; classes and DPR are shader scales (K01 BQ-174, BQ-175). */
  readonly rasterPx: number;
  /** Pixels mapped to the 8-bit range; a stored atlas property, not a shader constant. */
  readonly spread: number;
}

export interface AtlasConfig {
  readonly width: number;
  readonly height: number;
  /** Gap between packed glyphs, px. */
  readonly pad: number;
  /** Float64 is K01's measured baseline; Float32 is K2's lever 2 (off). */
  readonly edt: "f64" | "f32";
  readonly generatorVersion: number;
  /** Generation order: one task per family, mono first (BQ-276). */
  readonly families: readonly FamilyConfig[];
}

export const ATLAS_CONFIG: AtlasConfig = {
  width: 1024,
  height: 1024,
  pad: 1,
  edt: "f64",
  generatorVersion: GENERATOR_VERSION,
  families: [
    { key: "mono", family: "JetBrains Mono", weight: 400, rasterPx: 24, spread: 4 },
    { key: "ui", family: "Inter", weight: 600, rasterPx: 32, spread: 6 },
  ],
};

/**
 * The mono glyphs re-derived before a cached atlas is first used (F-03, BQ-265): E06-D01's
 * numeric set, plus every other glyph a formatted number or time can carry — the space (a digit's
 * advance in a mono face: grouping and padding), `?` (BQ-269's replacement) and `:` `/` (time
 * axis). A slot outside this set is trusted on the checksum; the Inter digits are (by ruling).
 */
export const TRADING_GLYPHS = "0123456789.,-+%×KMB▲▼() ?:/";
