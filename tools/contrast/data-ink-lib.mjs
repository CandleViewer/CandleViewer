// Data-ink validation library (E47-T03): continuous gradients, high-contrast
// 7:1 body text, compact-density large-text downgrade, CVD discriminability.
// Evidence only: failures are listed; palettes are fixed under E47-S06.
// Codes: A11Y-C004 gradient stop, A11Y-C005 text pair, A11Y-C006 CVD, A11Y-C007 stale matrix.
import {
  contrastRatio,
  simulateCvd,
  deltaE76,
  CVD_JND_FLOOR,
  CVD_DEFICIENCIES,
} from "./color-math.mjs";
import { PAIRS, THRESHOLD } from "./pairs.mjs";

export const DEFAULT_STOPS = 16; // ticket: N >= 16
export const DENSITIES = ["comfortable", "compact"];
export const CANVAS = "color.surface.canvas";
// Large-text (3:1) labels that drop to 4.5:1 in compact density (WCAG 1.4.3).
export const DENSITY_TEXT_PAIRS = ["color.axis.text on color.surface.canvas"];
// Palettes under test. US-SET-005 alternative palettes are added here once
// their tokens ship; `token` maps a canonical name to the palette's token.
const CVD_MAP = {
  "color.buy.default": "color.cvd.buy",
  "color.sell.default": "color.cvd.sell",
  "color.buy.hc": "color.cvd.buy",
  "color.sell.hc": "color.cvd.sell",
  "color.candle.up": "color.cvd.buy",
  "color.candle.down": "color.cvd.sell",
  "color.footprint.bid": "color.cvd.buy",
  "color.footprint.ask": "color.cvd.sell",
  "color.footprint.imbalance": "color.cvd.imbalance",
  "color.heatmap.bid.5": "color.cvd.heatmap.bid.5",
  "color.heatmap.ask.5": "color.cvd.heatmap.ask.5",
};
export const PALETTES = [
  { id: "default", token: (n) => n },
  { id: "cvd-safe", token: (n) => CVD_MAP[n] ?? n },
];
export const CODE = { gradient: "A11Y-C004", text: "A11Y-C005", cvd: "A11Y-C006" };

/** Gradient definitions: ordered colour-token anchors, evenly spaced.
 * E47-S06: ramps start at the first *visible* stop. `color.heatmap.zero` is the
 * "no data" cell (it intentionally equals the canvas) and the diverging
 * mid-point is the zero-delta state, which always carries a text/sign channel
 * (see encoding registry); neither is data-ink, so they are not ramp stops. */
const side = (s) => [1, 2, 3, 4, 5].map((i) => `color.heatmap.${s}.${i}`);
export const GRADIENTS = [
  { id: "heatmap.bid", anchors: side("bid") },
  { id: "heatmap.ask", anchors: side("ask") },
  { id: "delta.positive", anchors: ["color.heatmap.bid.1", "color.buy.default"] },
  { id: "delta.negative", anchors: ["color.heatmap.ask.1", "color.sell.default"] },
  { id: "profile.histogram", anchors: ["color.profile.bar", "color.profile.valuearea"] },
  {
    id: "liquidation.intensity",
    anchors: ["color.status.danger.default", "color.status.danger.strong"],
  },
];

/** CVD discriminability pairs: [kind, a, b]. */
export const CVD_PAIRS = [
  ["buy-sell", "color.buy.default", "color.sell.default"],
  ["buy-sell", "color.buy.hc", "color.sell.hc"],
  ["buy-sell", "color.candle.up", "color.candle.down"],
  ["bid-ask", "color.footprint.bid", "color.footprint.ask"],
  ["bid-ask", "color.heatmap.bid.5", "color.heatmap.ask.5"],
  ["imbalance", "color.footprint.imbalance", "color.footprint.bid"],
  ["imbalance", "color.footprint.imbalance", "color.footprint.ask"],
];

const r2 = (n) => Math.round(n * 100) / 100;
const toRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const toHex = (c) =>
  "#" +
  c
    .map((v) => Math.round(v).toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase();

/** The single interpolation used for sampling: piecewise-linear in sRGB
 * between evenly spaced anchors (matches a GPU `mix()` on sRGB uniforms).
 * Chart-engine layers are still placeholders (E06/E11); when the renderer
 * lands, replace this with an import of its ramp function (ticket tech note). */
export function sampleRamp(anchorHexes, n) {
  if (!Number.isInteger(n) || n < 2) throw new Error("A11Y-C000 need at least 2 stops");
  const rgb = anchorHexes.map(toRgb);
  const segs = rgb.length - 1;
  const out = [];
  for (let i = 0; i < n; i++) {
    const pos = i / (n - 1);
    const scaled = pos * segs;
    const k = Math.min(Math.floor(scaled), segs - 1);
    const t = scaled - k;
    out.push({ pos: r2(pos), hex: toHex(rgb[k].map((v, c) => v + (rgb[k + 1][c] - v) * t)) });
  }
  return out;
}

function gradientRows(theme, hex, stops, rows) {
  const bg = hex(CANVAS);
  for (const g of GRADIENTS) {
    const anchors = g.anchors.map(hex);
    if (!bg || anchors.some((a) => !a)) continue;
    for (const s of sampleRamp(anchors, stops)) {
      const ratio = contrastRatio(s.hex, bg);
      rows.push({
        kind: "gradient",
        theme,
        density: "all",
        palette: "default",
        id: g.id,
        key: `${theme}:${g.id}@${s.pos.toFixed(2)}`,
        pos: s.pos,
        hex: s.hex,
        ratio: r2(ratio),
        threshold: THRESHOLD.NON_TEXT,
        pass: ratio >= THRESHOLD.NON_TEXT,
      });
    }
  }
}

function textRows(theme, hex, rows) {
  for (const { fg, bg, threshold } of PAIRS) {
    const a = hex(fg);
    const b = hex(bg);
    if (!a || !b) continue;
    const id = `${fg} on ${bg}`;
    const isBody = threshold === THRESHOLD.TEXT && fg.startsWith("color.text.");
    const densityText = DENSITY_TEXT_PAIRS.includes(id);
    if (!isBody && !densityText) continue;
    const ratio = contrastRatio(a, b);
    for (const density of DENSITIES) {
      let req = threshold;
      if (densityText && density === "compact") req = THRESHOLD.TEXT;
      if (isBody && theme === "high-contrast") req = THRESHOLD.HIGH_CONTRAST;
      rows.push({
        kind: "text",
        theme,
        density,
        palette: "default",
        id,
        key: `${theme}:${density}:${id}`,
        ratio: r2(ratio),
        threshold: req,
        pass: ratio >= req,
      });
    }
  }
}

function cvdRows(theme, hex, rows) {
  for (const palette of PALETTES) {
    for (const [kind, an, bn] of CVD_PAIRS) {
      const a = hex(palette.token(an));
      const b = hex(palette.token(bn));
      if (!a || !b) continue;
      for (const def of CVD_DEFICIENCIES) {
        const sa = simulateCvd(a, def);
        const sb = simulateCvd(b, def);
        const de = deltaE76(sa, sb);
        rows.push({
          kind: "cvd",
          cvdKind: kind,
          theme,
          density: "all",
          palette: palette.id,
          id: `${an} vs ${bn}`,
          key: `${theme}:${palette.id}:${an} vs ${bn}:${def}`,
          deficiency: def,
          simulatedA: sa,
          simulatedB: sb,
          deltaE: r2(de),
          threshold: CVD_JND_FLOOR,
          pass: de >= CVD_JND_FLOOR,
        });
      }
    }
  }
}

/** @param {Record<string, Record<string, {$value: string}>>} themes */
export function evaluate(themes, { stops = DEFAULT_STOPS } = {}) {
  const rows = [];
  for (const [theme, tokens] of Object.entries(themes)) {
    const hex = (n) => tokens[n]?.$value;
    gradientRows(theme, hex, stops, rows);
    textRows(theme, hex, rows);
    cvdRows(theme, hex, rows);
  }
  return rows;
}

/** One verdict per gradient: a ramp fails if any stop fails. */
export function summarise(rows) {
  const ramps = {};
  for (const r of rows.filter((x) => x.kind === "gradient")) {
    const k = `${r.theme}:${r.id}`;
    ramps[k] ??= { theme: r.theme, id: r.id, stops: 0, failing: [] };
    ramps[k].stops++;
    if (!r.pass) ramps[k].failing.push({ pos: r.pos, ratio: r.ratio });
  }
  const failingPerTheme = {};
  for (const r of rows) {
    failingPerTheme[r.theme] ??= 0;
    if (!r.pass) failingPerTheme[r.theme]++;
  }
  return {
    ramps: Object.values(ramps).map((x) => ({ ...x, pass: x.failing.length === 0 })),
    failingPerTheme,
  };
}

export function toMarkdown(rows, stops) {
  const s = summarise(rows);
  const L = [
    "# Data-ink contrast and CVD matrix (E47-T03)",
    "",
    `Generated by \`tools/contrast/data-ink.mjs\` (${stops} stops per gradient). Pass/fail is stated in words; this file never relies on colour. Do not edit by hand.`,
    `CVD transform: Brettel/Vienot dichromacy projection for protanopia and deuteranopia, Machado, Oliveira & Fernandes 2009 (severity 1.0, linear RGB) for tritanopia (\`tools/contrast/color-math.mjs\`); discriminability = CIE76 dE >= ${CVD_JND_FLOOR} (\`CVD_JND_FLOOR\`).`,
    "",
    "## Failing checks per theme",
    "",
    "| Theme | Failing checks |",
    "|---|---|",
  ];
  for (const [t, n] of Object.entries(s.failingPerTheme)) L.push(`| ${t} | ${n} |`);
  L.push(
    "",
    "## Gradient ramps",
    "",
    "| Theme | Ramp | Stops | Result | Failing stops (position: ratio) |",
    "|---|---|---|---|---|",
  );
  for (const x of s.ramps) {
    const f = x.failing.map((v) => `${v.pos}: ${v.ratio}`).join(", ") || "none";
    L.push(`| ${x.theme} | ${x.id} | ${x.stops} | ${x.pass ? "PASS" : "FAIL"} | ${f} |`);
  }
  L.push(
    "",
    "## Text pairs (theme x density)",
    "",
    "| Theme | Density | Pair | Ratio | Required | Result |",
    "|---|---|---|---|---|---|",
  );
  for (const r of rows.filter((x) => x.kind === "text")) {
    L.push(
      `| ${r.theme} | ${r.density} | ${r.id} | ${r.ratio} | ${r.threshold} | ${r.pass ? "PASS" : "FAIL"} |`,
    );
  }
  L.push(
    "",
    "## CVD discriminability",
    "",
    "| Theme | Palette | Kind | Pair | Deficiency | Simulated A | Simulated B | dE76 | Result |",
    "|---|---|---|---|---|---|---|---|---|",
  );
  for (const r of rows.filter((x) => x.kind === "cvd")) {
    L.push(
      `| ${r.theme} | ${r.palette} | ${r.cvdKind} | ${r.id} | ${r.deficiency} | ${r.simulatedA} | ${r.simulatedB} | ${r.deltaE} | ${r.pass ? "PASS" : "FAIL"} |`,
    );
  }
  return L.join("\n") + "\n";
}
