// Custom Style Dictionary format: `json/flat-rgba`.
//
// Produces the WebGL chart-engine uniform buffer contract from
// docs/plan/16-design-system-brief.md §11/§11.1: a flat map of every
// chart-relevant colour token to `{ hex, rgba }`, where `rgba` is
// normalised sRGB 0..1 floats (NOT linear — the shader converts to linear,
// per the brief's explicit "chosen: sRGB 0..1" note so E11 never guesses).
//
// No CSS syntax, no unresolved `{alias}` references: Style Dictionary
// resolves aliases before formats run, so `token.value` is already the
// final hex string here.

/**
 * @param {string} hex 6- or 8-digit hex colour, with or without leading `#`.
 * @returns {[number, number, number, number]} sRGB 0..1 RGBA floats.
 */
export function hexToRgba(hex) {
  const clean = hex.replace(/^#/, "");
  if (!/^[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(clean)) {
    throw new Error(`json/flat-rgba: not a hex colour: ${hex}`);
  }
  const r = parseInt(clean.slice(0, 2), 16) / 255;
  const g = parseInt(clean.slice(2, 4), 16) / 255;
  const b = parseInt(clean.slice(4, 6), 16) / 255;
  const a = clean.length === 8 ? parseInt(clean.slice(6, 8), 16) / 255 : 1;
  return [round4(r), round4(g), round4(b), round4(a)];
}

function round4(n) {
  return Math.round(n * 10000) / 10000;
}

/** TOKENS-E003: category prefixes the engine platform is allowed to consume. */
export const ENGINE_CATEGORY_PREFIXES = [
  "color.chart.",
  "color.candle.",
  "color.footprint.",
  "color.profile.",
  "color.order.",
  "color.position.",
  "color.drawing.",
  "color.node.",
  "color.grid.",
  "color.axis.",
  "color.crosshair",
  "color.heatmap.",
  "color.buy.",
  "color.sell.",
  // E11-D05 G16: the CVD-safe palette (E47-S06), so its heatmap stops reach the engine export.
  "color.cvd.",
];

export function isEngineToken(name) {
  return ENGINE_CATEGORY_PREFIXES.some((p) => name === p.replace(/\.$/, "") || name.startsWith(p));
}

/**
 * @param {{ dictionary: { allTokens: Array<{ name: string, value: unknown, original?: { value?: unknown } }> } }} args
 */
export default function jsonFlatRgba({ dictionary }) {
  const out = {};
  const names = [...dictionary.allTokens].map((t) => t.name).sort((a, b) => a.localeCompare(b));
  const byName = new Map(dictionary.allTokens.map((t) => [t.name, t]));

  for (const name of names) {
    const token = byName.get(name);
    if (!token) continue;
    if (!isEngineToken(name)) continue;
    const value = token.value;
    if (typeof value !== "string" || !value.startsWith("#")) {
      throw new Error(
        `TOKENS-E003 unknown category for the engine filter: token "${name}" resolved to a non-hex value (${JSON.stringify(value)})`,
      );
    }
    out[name] = { hex: value.toUpperCase(), rgba: hexToRgba(value) };
  }

  // `out` was built by iterating `names` in sorted order, so insertion
  // order (and therefore JSON.stringify's key order) is already stable.
  return JSON.stringify(out, null, 2) + "\n";
}
