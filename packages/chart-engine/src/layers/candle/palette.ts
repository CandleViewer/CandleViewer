// The minimal candle palette (E12-S06, BQ-4; E11-T04 #390 absorbs it): four theme tokens resolved
// to `u_palette`'s six RGBA colours at theme load, never per frame. Up, down and wick come from
// the theme; the tints are the 42 % mix over the canvas colour. The inverted convention swaps up
// and down only; the wick is never remapped (R-6). A missing or unreadable token is a refusal,
// never a hard-coded colour: the caller posts a recoverable error and draws no series.

export const CANDLE_TOKENS = {
  up: "color.candle.up",
  down: "color.candle.down",
  wick: "color.candle.wick",
  canvas: "color.surface.canvas",
} as const;
/** `u_palette` rows. */
export const PALETTE = { up: 0, down: 1, wick: 2, upTint: 3, downTint: 4, neutral: 5 } as const;
export const PALETTE_FLOATS = 24;
export const TINT = 0.42;
export const ENGINE_THEME_TOKEN_MISSING = "ENGINE_THEME_TOKEN_MISSING";

export class PaletteError extends Error {
  readonly code = ENGINE_THEME_TOKEN_MISSING;
  constructor(readonly token: string) {
    super(`chart-engine: theme token ${token} is missing or not a colour`);
    this.name = "PaletteError";
  }
}

const HEX = /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
const RGB = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([01]|0?\.\d+)\s*)?\)$/i;

/** `#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa`, `rgb()` or `rgba()` into out[at..at+4) in 0..1. */
export function parseColor(css: string | undefined, out: Float32Array, at: number): boolean {
  const hex = HEX.exec(css ?? "")?.[1];
  if (hex !== undefined) {
    const full = hex.length <= 4 ? hex.replace(/./g, "$&$&") : hex;
    for (let i = 0; i < 4; i += 1) {
      const pair = full.slice(i * 2, i * 2 + 2);
      out[at + i] = pair === "" ? 1 : Number.parseInt(pair, 16) / 255;
    }
    return true;
  }
  const m = RGB.exec(css ?? "");
  if (m === null) return false;
  const rgb = [m[1], m[2], m[3]].map(Number);
  if (rgb.some((v) => v > 255)) return false;
  for (let i = 0; i < 3; i += 1) out[at + i] = (rgb[i] as number) / 255;
  out[at + 3] = m[4] === undefined ? 1 : Number(m[4]);
  return true;
}

/** Resolves the palette into `out` (24 floats); throws `PaletteError` and leaves `out` as it was. */
export function candlePalette(
  theme: Readonly<Record<string, string>>,
  inverted: boolean,
  out: Float32Array,
): void {
  const next = new Float32Array(PALETTE_FLOATS + 4); // theme load only, never per frame
  const read = (token: string, row: number): void => {
    if (!parseColor(theme[token], next, row * 4)) throw new PaletteError(token);
  };
  read(inverted ? CANDLE_TOKENS.down : CANDLE_TOKENS.up, PALETTE.up);
  read(inverted ? CANDLE_TOKENS.up : CANDLE_TOKENS.down, PALETTE.down);
  read(CANDLE_TOKENS.wick, PALETTE.wick);
  read(CANDLE_TOKENS.canvas, 6); // scratch row: the tints' base
  const tint = (from: number, row: number): void => {
    for (let i = 0; i < 3; i += 1) {
      const base = next[24 + i] as number;
      next[row * 4 + i] = base + ((next[from * 4 + i] as number) - base) * TINT;
    }
    next[row * 4 + 3] = 1;
  };
  tint(PALETTE.up, PALETTE.upTint);
  tint(PALETTE.down, PALETTE.downTint);
  tint(PALETTE.wick, PALETTE.neutral);
  out.set(next.subarray(0, PALETTE_FLOATS));
}
