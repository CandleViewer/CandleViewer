// Outline contrast (E11-S11 PR B, README BQ-274; E06-D01 §5): the WCAG 2.x ratio of the cell text
// against what surrounds each glyph — the outline composited at its alpha over the cell's fill.
// Pure: hex in, a ratio out; the test runs it over every delta-ramp endpoint of every theme.

/** `#rrggbb` to linear-light relative luminance (WCAG 2.x). */
export function luminance(rgb: readonly number[]): number {
  const lin = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(rgb[0] ?? 0) + 0.7152 * lin(rgb[1] ?? 0) + 0.0722 * lin(rgb[2] ?? 0);
}

/** `#rrggbb` to sRGB channels in 0..1. */
export function rgbOf(hex: string): number[] {
  const n = Number.parseInt(hex.replace("#", "").slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => c / 255);
}

/** WCAG contrast of `text` over `outline` at `alpha` composited on `fill` (all `#rrggbb`). */
export function outlineContrast(
  text: string,
  outline: string,
  alpha: number,
  fill: string,
): number {
  const o = rgbOf(outline);
  const f = rgbOf(fill);
  const under = f.map((c, i) => alpha * (o[i] ?? 0) + (1 - alpha) * c);
  const a = luminance(rgbOf(text));
  const b = luminance(under);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
