// A drawing as the layer keeps it (E14-T03): `copyInput`'s whitelisted copy plus its anchors in
// chart space and the per-map caches the projection fills. Its own module so `project.ts` (the
// node) and `lines.ts` (the instance ring) both read it with no cycle. DOM- and GL-free.
import { copyInput, type DrawingInput } from "./model.js";

export interface DrawingRecord {
  /** `copyInput`'s whitelisted copy: kind, style, z, visibility and the clamped label. */
  readonly input: DrawingInput;
  readonly t: Float64Array;
  readonly tick: Float64Array;
  /** Each anchor's fractional bar index under the map stamped in `stamp`. */
  readonly idx: Float64Array;
  /** [idxMin, tickMin, idxMax, tickMax], a band's implied fourth corner included. */
  readonly box: Float64Array;
  stamp: number;
  /** The stroke and fill as 0xRRGGBBAA, resolved from a number or a theme token; fill -1: none. */
  colour: number;
  fill: number;
}

/** The colour a token resolves to when the theme lacks it and `color.drawing.default` too. */
export const FALLBACK_COLOUR = 0x808080ff;
/** The theme as the renderer reads it: token name to its CSS colour (`ThemeLut`). */
export type ThemeColours = Readonly<Record<string, string>>;

/** A theme value as 0xRRGGBBAA: `#rgb`, `#rrggbb` or `#rrggbbaa` only; anything else is null. */
export function parseHex(css: string | undefined): number | null {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(css ?? "");
  if (m === null) return null;
  const h = m[1] as string;
  const full = h.length === 3 ? h.replace(/./g, "$&$&") : h;
  return Number.parseInt(full.length === 6 ? `${full}ff` : full, 16);
}

/**
 * BQ-4: a number is taken as is; a token key through the theme object, else the theme's
 * `color.drawing.default`, else `FALLBACK_COLOUR`. No CSS is ever built from it (SR-E14-04).
 */
export function resolveColour(v: number | string, theme: ThemeColours): number {
  if (typeof v === "number") return v;
  return parseHex(theme[v]) ?? parseHex(theme["color.drawing.default"]) ?? FALLBACK_COLOUR;
}

/** Re-resolves a record's colours (on DATA or a theme change: STYLE). */
export function resolveColours(r: DrawingRecord, theme: ThemeColours): void {
  const { colour, fill } = r.input.style;
  r.colour = resolveColour(colour, theme);
  r.fill = fill === undefined ? -1 : resolveColour(fill, theme);
}

export function toRecord(d: DrawingInput): DrawingRecord {
  const input = copyInput(d);
  const n = input.points.length / 2;
  const r = {
    input,
    t: new Float64Array(n),
    tick: new Float64Array(n),
    idx: new Float64Array(n),
    box: new Float64Array(4),
    stamp: -1,
    colour: 0,
    fill: -1,
  };
  resolveColours(r, {});
  for (let i = 0; i < n; i += 1) {
    r.t[i] = input.points[2 * i] as number;
    r.tick[i] = input.points[2 * i + 1] as number;
  }
  return r;
}
