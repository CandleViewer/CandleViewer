// E11-T04 PR-3 (E11-D05 §5.1, G4): sRGB ↔ linear ↔ OkLab, the interpolation space of the colour
// LUTs. The sRGB transfer is `tools/contrast/color-math.mjs`'s (0.04045 / 12.92 / 2.4 /
// 0.0031308) and the OkLab matrices are Björn Ottosson's published pair as D05 §5.1 pins them
// (`docs/design/_tools/e11_d05_ds_audit.py` M1 / M2 and their inverses), so the engine and the
// design audit agree to the digit (test/theme/oklab.test.ts holds the parity vectors).
//
// Pure, DOM-free (C-2.16), and allocation-free: every converter writes into a caller-owned
// `out` array at `o`, so the LUT writer converts 256 entries without a temporary.

/** Writable numeric storage the converters fill (a typed array or a plain array). */
export type Vec3Out = { [index: number]: number; readonly length: number };

/** sRGB-encoded channel in [0, 1] → linear light (IEC 61966-2-1, as `tools/contrast`). */
export function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** Linear light → sRGB-encoded, clamped to [0, 1] first (out-of-gamut OkLab clamps here). */
export function linearToSrgb(c: number): number {
  const x = c <= 0 ? 0 : c >= 1 ? 1 : c;
  return x <= 0.0031308 ? x * 12.92 : 1.055 * x ** (1 / 2.4) - 0.055;
}

/** WCAG 2.x relative luminance of a straight-sRGB colour (channels 0..1). */
export function relativeLuminance(r: number, g: number, b: number): number {
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}

/** Linear sRGB → OkLab [L, a, b] into `out[o..o+2]`. */
export function linearToOklab(r: number, g: number, b: number, out: Vec3Out, o = 0): void {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  out[o] = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  out[o + 1] = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  out[o + 2] = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
}

/** OkLab → linear sRGB into `out[o..o+2]`, unclamped (may leave the gamut). */
export function oklabToLinear(L: number, a: number, b: number, out: Vec3Out, o = 0): void {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  out[o] = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  out[o + 1] = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  out[o + 2] = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
}

/** Straight sRGB (channels 0..1) → OkLab into `out[o..o+2]`. */
export function srgbToOklab(r: number, g: number, b: number, out: Vec3Out, o = 0): void {
  linearToOklab(srgbToLinear(r), srgbToLinear(g), srgbToLinear(b), out, o);
}

/** OkLab → straight sRGB in [0, 1] into `out[o..o+2]`, clamped after conversion (D05 §5.5). */
export function oklabToSrgb(L: number, a: number, b: number, out: Vec3Out, o = 0): void {
  oklabToLinear(L, a, b, out, o);
  out[o] = linearToSrgb(out[o] as number);
  out[o + 1] = linearToSrgb(out[o + 1] as number);
  out[o + 2] = linearToSrgb(out[o + 2] as number);
}
