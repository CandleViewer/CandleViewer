// The atlas glyph set (E11-K01 BQ-172, ADR-0002 "O2 atlas configuration"): printable ASCII
// U+0020–U+007E per family, plus `× ▲ ▼` for mono and `·` for ui — 194 glyphs, one R8 texture.
// An out-of-set character is the glyph runs' concern (`?`, BQ-269); the atlas never grows (DR8).
import type { AtlasConfig, FamilyConfig } from "./config.js";
import { fnv1aHex } from "./hash.js";

const ASCII = Array.from({ length: 0x7e - 0x20 + 1 }, (_, i) => String.fromCharCode(0x20 + i));
const EXTRAS: Record<FamilyConfig["key"], string> = { mono: "×▲▼", ui: "·" };

/** One atlas slot: the family it belongs to (index into `families`) and its character. */
export interface GlyphEntry {
  readonly family: number;
  readonly ch: string;
  readonly cp: number;
}

/** A family's characters, in atlas order. */
export const familyChars = (key: FamilyConfig["key"]): string[] => [...ASCII, ...EXTRAS[key]];

/** Every slot, family-major in `families` order; metrics rows follow this order. */
export function atlasGlyphs(cfg: AtlasConfig): GlyphEntry[] {
  return cfg.families.flatMap((f, family) =>
    familyChars(f.key).map((ch) => ({ family, ch, cp: ch.codePointAt(0) ?? 0 })),
  );
}

/** The glyph-set hash in the cache key. */
export const glyphSetHash = (cfg: AtlasConfig): string =>
  fnv1aHex(cfg.families.map((f) => familyChars(f.key).join("")).join("\u0000"));
