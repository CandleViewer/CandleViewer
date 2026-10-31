/**
 * The WCAG 2.x relative-luminance contrast ratio, ported from the E05-T05 gate's
 * `tools/contrast/color-math.mjs` (no cross-package import, BQ-17); `test/contrast/preview-ratio.test.ts`
 * holds the two in parity over every theme's resolved token pairs.
 */

/** `#RGB` or `#RRGGBB` (any case) as 0..255 channels; anything else (a `var()`, an alpha) is `null`. */
export function parseHex(value: string): readonly [number, number, number] | null {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value.trim());
  if (m === null) return null;
  const raw = m[1] ?? "";
  const h = raw.length === 3 ? [...raw].map((c) => c + c).join("") : raw;
  const ch = (i: number): number => parseInt(h.slice(i, i + 2), 16);
  return [ch(0), ch(2), ch(4)];
}

const linear = (c: number): number => {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};

/** WCAG relative luminance (0..1) of an sRGB colour. */
export function relativeLuminance([r, g, b]: readonly [number, number, number]): number {
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

/** The contrast ratio (1..21) of two hex colours, or `null` when either is not an opaque hex. */
export function contrastRatio(a: string, b: string): number | null {
  const ca = parseHex(a);
  const cb = parseHex(b);
  if (ca === null || cb === null) return null;
  const la = relativeLuminance(ca);
  const lb = relativeLuminance(cb);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
