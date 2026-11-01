// Declarative pair registry for the contrast-matrix gate (E05-T05).
//
// Every colour token that is actually rendered as text, a non-text UI
// component, or chart data-ink MUST have an entry here (directly, or via a
// `ramp` block, or via `exemptions.json` with a reason+owner) — an
// undeclared token fails the gate loudly (A11Y-C002) rather than silently
// passing. Thresholds: 4.5:1 text, 3:1 non-text/chart-ink, 7:1 buy/sell
// high-contrast (`docs/plan/16-design-system-brief.md#11`,
// `docs/plan/05-accessibility-standard.md` sections 4, 5).
//
// `bg`/`fg` reference token names resolved against the theme's flattened
// colour map (`packages/ui/build/electron/tokens.main.json` shape — see
// `tools/contrast/generate.mjs`).

export const THRESHOLD = {
  TEXT: 4.5,
  NON_TEXT: 3.0,
  HIGH_CONTRAST: 7.0,
};

/**
 * `themes`: which theme(s) (as produced by build-tokens.mjs: "dark",
 * "light", "high-contrast") this pair applies to. Omit to apply to all
 * themes that define both tokens.
 */
export const PAIRS = [
  // --- Text-on-surface pairs (4.5:1) --------------------------------
  { fg: "color.text.primary", bg: "color.surface.app", threshold: THRESHOLD.TEXT },
  { fg: "color.text.primary", bg: "color.surface.canvas", threshold: THRESHOLD.TEXT },
  { fg: "color.text.primary", bg: "color.surface.raised", threshold: THRESHOLD.TEXT },
  { fg: "color.text.secondary", bg: "color.surface.app", threshold: THRESHOLD.TEXT },
  { fg: "color.text.secondary", bg: "color.surface.canvas", threshold: THRESHOLD.TEXT },
  { fg: "color.text.secondary", bg: "color.surface.raised", threshold: THRESHOLD.TEXT },
  { fg: "color.text.tertiary", bg: "color.surface.app", threshold: THRESHOLD.TEXT },
  { fg: "color.text.link", bg: "color.surface.app", threshold: THRESHOLD.TEXT },
  { fg: "color.text.on-action", bg: "color.action.primary.default", threshold: THRESHOLD.TEXT },
  { fg: "color.text.primary", bg: "color.action.selected", threshold: THRESHOLD.TEXT },
  { fg: "color.axis.text", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },

  // --- Focus ring on every surface tier (3:1 non-text) ---------------
  { fg: "color.focus.ring", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.focus.ring", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.focus.ring", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.focus.ring", bg: "color.surface.overlay", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.focus.ring", bg: "color.surface.sunken", threshold: THRESHOLD.NON_TEXT },

  // --- Buy/sell default (3:1 non-text; carried by icon/text too) -----
  { fg: "color.buy.default", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sell.default", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.buy.default", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sell.default", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  // E22-S01 (#714) G-63 / D02-G5: the SCR-053 tape's rows. The tier-2 band's text, and the side
  // glyph and 2 px accent on the row surface and on the band (D02 §14's seven PROPOSED rows).
  { fg: "color.text.primary", bg: "color.buy.subtle", threshold: THRESHOLD.TEXT },
  { fg: "color.text.primary", bg: "color.sell.subtle", threshold: THRESHOLD.TEXT },
  { fg: "color.text.tertiary", bg: "color.sell.subtle", threshold: THRESHOLD.TEXT },
  { fg: "color.buy.default", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sell.default", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.buy.default", bg: "color.buy.subtle", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sell.default", bg: "color.sell.subtle", threshold: THRESHOLD.NON_TEXT },

  // --- Buy/sell high-contrast (7:1 stretch target) --------------------
  { fg: "color.buy.hc", bg: "color.surface.app", threshold: THRESHOLD.HIGH_CONTRAST },
  { fg: "color.sell.hc", bg: "color.surface.app", threshold: THRESHOLD.HIGH_CONTRAST },

  // --- Chart data-ink on canvas (3:1) --------------------------------
  { fg: "color.candle.up", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.candle.down", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.candle.wick", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.footprint.bid", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.footprint.ask", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.footprint.imbalance", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.profile.bar", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.profile.poc", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.profile.valuearea", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.grid.line", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.crosshair", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.order.line", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.position.entry", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.position.sl", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.position.tp", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.drawing.default", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.drawing.selected", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },

  // --- Rule-graph node colours on canvas (3:1) ------------------------
  { fg: "color.node.trigger", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.node.condition", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.node.action", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.node.logic", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.node.comment", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },

  // --- Borders (3:1 non-text) -----------------------------------------
  { fg: "color.border.default", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.border.strong", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.border.selected", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },

  // --- Status/severity tokens (text + strong variants at 4.5:1/3:1) --
  { fg: "color.status.success.default", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.status.warning.default", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.status.danger.default", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.status.info.default", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.status.success.strong", bg: "color.surface.app", threshold: THRESHOLD.TEXT },
  { fg: "color.status.warning.strong", bg: "color.surface.app", threshold: THRESHOLD.TEXT },
  { fg: "color.status.danger.strong", bg: "color.surface.app", threshold: THRESHOLD.TEXT },
  { fg: "color.status.info.strong", bg: "color.surface.app", threshold: THRESHOLD.TEXT },

  // --- Environment badge (LIVE/DEMO, text-carrying) -------------------
  { fg: "color.env.demo", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.env.live", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },

  // --- Data-confidence chip text (4.5:1) -------------------------------
  { fg: "color.data-confidence.live.text", bg: "color.surface.app", threshold: THRESHOLD.TEXT },
  {
    fg: "color.data-confidence.stale.text",
    bg: "color.data-confidence.stale.surface",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.data-confidence.reconnecting.text",
    bg: "color.surface.app",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.data-confidence.disconnected.text",
    bg: "color.surface.app",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.data-confidence.resyncing.text",
    bg: "color.surface.app",
    threshold: THRESHOLD.TEXT,
  },
  { fg: "color.data-confidence.gapped.text", bg: "color.surface.app", threshold: THRESHOLD.TEXT },
  {
    fg: "color.data-confidence.backfilling.text",
    bg: "color.surface.app",
    threshold: THRESHOLD.TEXT,
  },
  { fg: "color.data-confidence.delisted.text", bg: "color.surface.app", threshold: THRESHOLD.TEXT },
  {
    fg: "color.data-confidence.live.indicator",
    bg: "color.surface.app",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.stale.indicator",
    bg: "color.data-confidence.stale.surface",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.reconnecting.indicator",
    bg: "color.surface.app",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.disconnected.indicator",
    bg: "color.surface.app",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.resyncing.indicator",
    bg: "color.surface.app",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.gapped.indicator",
    bg: "color.surface.app",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.backfilling.indicator",
    bg: "color.surface.app",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.delisted.indicator",
    bg: "color.surface.app",
    threshold: THRESHOLD.NON_TEXT,
  },

  // --- CVD-safe palette (E47-S06) -------------------------------------
  { fg: "color.cvd.buy", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.sell", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.imbalance", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.heatmap.bid.1", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.heatmap.bid.2", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.heatmap.bid.3", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.heatmap.bid.4", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.heatmap.bid.5", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.heatmap.ask.1", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.heatmap.ask.2", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.heatmap.ask.3", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.heatmap.ask.4", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.cvd.heatmap.ask.5", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },

  // --- Action/neutral chrome (3:1 non-text) ---------------------------
  { fg: "color.action.primary.default", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.action.secondary.default", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.neutral.default", bg: "color.surface.app", threshold: THRESHOLD.NON_TEXT },

  // --- Drawer surfaces and notice tints (E08-D06 SCR-103, spec §13) --
  // Held out (E47-D03 retune): `color.text.link` on `color.surface.overlay`, 6.15:1 in HC (H-8).
  { fg: "color.text.primary", bg: "color.surface.overlay", threshold: THRESHOLD.TEXT },
  { fg: "color.text.secondary", bg: "color.surface.overlay", threshold: THRESHOLD.TEXT },
  { fg: "color.text.tertiary", bg: "color.surface.overlay", threshold: THRESHOLD.TEXT },
  { fg: "color.text.secondary", bg: "color.surface.sunken", threshold: THRESHOLD.TEXT },
  { fg: "color.text.tertiary", bg: "color.surface.sunken", threshold: THRESHOLD.TEXT },
  { fg: "color.text.primary", bg: "color.status.warning.subtle", threshold: THRESHOLD.TEXT },
  { fg: "color.text.primary", bg: "color.status.info.subtle", threshold: THRESHOLD.TEXT },
  { fg: "color.text.primary", bg: "color.status.danger.subtle", threshold: THRESHOLD.TEXT },
  { fg: "color.status.warning.strong", bg: "color.surface.sunken", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.status.warning.strong", bg: "color.surface.overlay", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.status.danger.strong", bg: "color.surface.overlay", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.status.info.strong", bg: "color.surface.overlay", threshold: THRESHOLD.NON_TEXT },

  // --- Replay page chrome and marks (E26-D02 SCR-097, spec §12.2) ----
  // Left out: CR-4 `color.replay.border` (E11-D02 §11.4). It resolves only to `palette.purple`
  // primitives and is not in the theme maps, so its canvas and raised pairs wait for the token.
  // Never registered, as the spec marks them: `border.strong` on `surface.raised` and
  // `text.primary` on `neutral.default` (both under 3:1), and `text.disabled` on `surface.raised`.
  { fg: "color.text.tertiary", bg: "color.surface.raised", threshold: THRESHOLD.TEXT },
  { fg: "color.text.primary", bg: "color.surface.selected", threshold: THRESHOLD.TEXT },
  { fg: "color.env.demo", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.neutral.default", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.neutral.default", bg: "color.surface.sunken", threshold: THRESHOLD.NON_TEXT },
  // Status inks on their own subtle fill (E04 #5134): the DegradedModeBanner severity word
  // (CMP-092) and the ConnectionRegion age line are text; the StatusBar ok glyph is non-text.
  // All themes: dark and high-contrast already pass these with room to spare.
  {
    fg: "color.status.danger.strong",
    bg: "color.status.danger.subtle",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.status.warning.strong",
    bg: "color.status.warning.subtle",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.status.info.strong",
    bg: "color.status.info.subtle",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.status.success.strong",
    bg: "color.surface.sunken",
    threshold: THRESHOLD.NON_TEXT,
  },

  // --- Symbol search rows (E08-D05 SCR-102 / SCR-041, spec §9.5; CMP-213, CMP-160) --
  // The overlay pairs, the selected fill's primary text and the ARMED pill are registered above.
  // Never registered, as §9.5 rejects it: `color.text.tertiary` on `color.surface.selected` (3.98:1 dark).
  { fg: "color.text.primary", bg: "color.surface.hover", threshold: THRESHOLD.TEXT },
  { fg: "color.text.secondary", bg: "color.surface.hover", threshold: THRESHOLD.TEXT },
  { fg: "color.text.secondary", bg: "color.surface.selected", threshold: THRESHOLD.TEXT },
  {
    fg: "color.data-confidence.delisted.text",
    bg: "color.surface.overlay",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.data-confidence.delisted.text",
    bg: "color.surface.hover",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.data-confidence.delisted.text",
    bg: "color.surface.selected",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.data-confidence.delisted.indicator",
    bg: "color.surface.overlay",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.delisted.indicator",
    bg: "color.surface.hover",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.delisted.indicator",
    bg: "color.surface.selected",
    threshold: THRESHOLD.NON_TEXT,
  },
  { fg: "color.border.selected", bg: "color.surface.selected", threshold: THRESHOLD.NON_TEXT },

  // --- Watchlist grid (E08-D07 SCR-100, spec §7.2; CMP-049 grid, CMP-161, CMP-239 compact) --
  // The pairs above already cover the stale tint, the T1 chip's text, the active bar and the dash on row fills.
  // Held in packages/ui/test/contrast/watchlist-pairs.test.ts instead: §7.3 item 1's Disconnected fallback,
  // `color.text.primary` at `opacity.muted` on `color.surface.sunken` (an alpha this registry cannot express).
  {
    fg: "color.data-confidence.stale.text",
    bg: "color.surface.selected",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.text.inverse",
    bg: "color.data-confidence.stale.indicator",
    threshold: THRESHOLD.TEXT,
  },
  {
    fg: "color.data-confidence.delisted.text",
    bg: "color.surface.raised",
    threshold: THRESHOLD.TEXT,
  },
  { fg: "color.text.tertiary", bg: "color.surface.hover", threshold: THRESHOLD.TEXT },
  { fg: "color.buy.default", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sell.default", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.buy.default", bg: "color.surface.hover", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sell.default", bg: "color.surface.hover", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.buy.default", bg: "color.surface.selected", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sell.default", bg: "color.surface.selected", threshold: THRESHOLD.NON_TEXT },
  {
    fg: "color.data-confidence.stale.indicator",
    bg: "color.surface.hover",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.stale.indicator",
    bg: "color.status.warning.subtle",
    threshold: THRESHOLD.NON_TEXT,
  },
  {
    fg: "color.data-confidence.delisted.indicator",
    bg: "color.surface.raised",
    threshold: THRESHOLD.NON_TEXT,
  },
  { fg: "color.status.warning.strong", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.status.warning.strong", bg: "color.surface.hover", threshold: THRESHOLD.NON_TEXT },
  {
    fg: "color.status.warning.strong",
    bg: "color.surface.selected",
    threshold: THRESHOLD.NON_TEXT,
  },

  // --- Dock sync-group edges (E15-D13 §6 P-1 … P-6) --------------------
  // The tile edge sits on the panel header (`raised`) or a grid cell's header (`canvas`);
  // the group letter always carries the group, the hue only repeats it.
  { fg: "color.sync.a", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sync.b", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sync.c", bg: "color.surface.raised", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sync.a", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sync.b", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
  { fg: "color.sync.c", bg: "color.surface.canvas", threshold: THRESHOLD.NON_TEXT },
];

/**
 * Every heatmap ramp stop (both bid and ask sides, all 5 stops each) is
 * validated individually against `color.surface.canvas` at the non-text
 * threshold — not just the extremes (ticket AC "Heatmap stops validated
 * individually"), plus `color.heatmap.zero`.
 */
export const HEATMAP_RAMP = {
  bg: "color.surface.canvas",
  threshold: THRESHOLD.NON_TEXT,
  stops: [
    "color.heatmap.zero",
    "color.heatmap.bid.1",
    "color.heatmap.bid.2",
    "color.heatmap.bid.3",
    "color.heatmap.bid.4",
    "color.heatmap.bid.5",
    "color.heatmap.ask.1",
    "color.heatmap.ask.2",
    "color.heatmap.ask.3",
    "color.heatmap.ask.4",
    "color.heatmap.ask.5",
  ],
};

/** Adjacent-stop pairs (ordered by "distance from zero") for the CVD check. */
export const HEATMAP_ADJACENT_PAIRS = [
  ["color.heatmap.bid.1", "color.heatmap.bid.2"],
  ["color.heatmap.bid.2", "color.heatmap.bid.3"],
  ["color.heatmap.bid.3", "color.heatmap.bid.4"],
  ["color.heatmap.bid.4", "color.heatmap.bid.5"],
  ["color.heatmap.ask.1", "color.heatmap.ask.2"],
  ["color.heatmap.ask.2", "color.heatmap.ask.3"],
  ["color.heatmap.ask.3", "color.heatmap.ask.4"],
  ["color.heatmap.ask.4", "color.heatmap.ask.5"],
];

/** The buy/sell pair checked for CVD collapse (A11Y-C003). */
export const CVD_BUY_SELL_PAIR = ["color.buy.default", "color.sell.default"];

/**
 * Every `color.*` token declared in the semantic token files. Used by the
 * gate to detect an undeclared token (A11Y-C002): any name in this list not
 * covered by `PAIRS`/`HEATMAP_RAMP`/`CVD_BUY_SELL_PAIR` and not present in
 * `exemptions.json` fails the build.
 */
export function collectDeclaredTokenNames() {
  const names = new Set();
  for (const p of PAIRS) {
    names.add(p.fg);
    names.add(p.bg);
  }
  names.add(HEATMAP_RAMP.bg);
  for (const s of HEATMAP_RAMP.stops) names.add(s);
  for (const pair of CVD_BUY_SELL_PAIR) names.add(pair);
  return names;
}
