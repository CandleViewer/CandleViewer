# Changelog — `packages/ui/tokens`

Versioned independently from `@candleviewer/ui` (docs/plan/16-design-system-brief.md #11:
"the `tokens/` directory is versioned independently ... since a token-only
change should be shippable and reviewable without touching component code").

## [0.1.1] - 2026-10-20

### Added

- `palette.blue.450` (`#3676EB`, CIE L\* 51.5), the high-contrast pressed fill, interpolated in
  LCh between `palette.blue.400` and `palette.blue.500` (#3896). No existing step fits: under the
  high-contrast near-black label the pressed fill needs L\* 51.17 to 51.76 (4.5:1 for the label,
  5 L\* below the `palette.blue.400` hover), and no blue primitive lies in that window.
- `color.action.selected`, the fill of a pressed toggle IconButton (CMP-002, `aria-pressed=true`)
  and of CMP-003's selected segment, which until now looked like a primary button (#3896): dark and
  high contrast `palette.blue.900` `#0F2650`, light `palette.light.blue.700` `#DDE8FC`. Its glyph
  or label is `color.text.primary`: 12.33, 14.58 and 13.96:1 (dark, light, high contrast). It
  sits at least 12.86 L\* from every primary state fill (dark 12.86, light 43.39, high contrast
  35.71). It is a tint, under 3:1 on the surfaces (1.01 to 1.30), so the boundary rides on:
- `color.border.selected`, the 2 px inner outline of a selected control (#3896): dark
  `palette.blue.400` `#4A86EE`, light `palette.light.blue.500` `#2B6CE8`, high contrast
  `palette.blue.300` `#6EA1F5`. It clears 3:1 on `color.surface.app`, `.raised` and `.overlay`
  (dark 4.52 to 5.47, light 3.80 to 4.76, high contrast 6.15 to 7.45) and on the selected fill
  (4.20, 3.86, 5.72). A fill alone cannot do it in dark: under the white `color.text.on-action`
  label a fill needs L\* ≤ 49.90 and 3:1 on the overlay needs L\* ≥ 45.22, a band in which no
  fill is 5 L\* from the primary rest fill (48.34); under `color.text.primary` the label needs
  L\* ≤ 44.74, below that floor. The outline is not `color.action.selected.outline` because a
  token path cannot be both a value and a group (16 §2 naming edge case; Penpot forbids it, and the
  generated `tokens.ts` would drop the fill).
- A label-on-fill contrast matrix (#3896): `tools/contrast/label-on-fill.json`, gated in CI by
  `packages/ui/test/contrast/label-on-fill.test.ts` and checked by `tests/verify_tokens.py`. In
  every theme, each filled button role's label and the selected glyph clear 4.5:1 on every state
  fill (in every chart colour mode too); a role's states are pairwise at least 5 CIE L\* apart and
  within 10 degrees of the rest fill's LCh hue; the selected fill is at least 5 L\* from each
  primary state; each primary, danger, buy and sell rest fill, and the selected outline, clears 3:1
  against `color.surface.app`, `.raised` and `.overlay`. Disabled with reason (the E05-D02 gated
  state) dims only the fill, outline or track to `opacity.disabled` (0.45): on each rest fill
  composited at 0.45 over each of those surfaces, the full-opacity `color.text.primary` label
  clears 4.5:1 (lowest 5.25) and the `color.text.secondary` locked glyph 3:1 (lowest 3.42); the
  reason text keeps 4.5:1 and a ghost's locked glyph 3:1. `color.focus.ring` clears 3:1 on every
  surface tier, and in high contrast it is at least 20 CIE76 ΔE from the primary and selected
  fills. `verify_tokens.py` also keeps `color.status.danger.default` 8 ΔE from
  `color.sell.hover`, `color.status.danger.strong`, `.warning.default` and `.warning.strong` in
  every theme. Both gates hold the registry's thresholds at or past their floors (4.5:1 label,
  3:1 glyph and boundary, 5 L\* state step, 10 degree hue, 20 ΔE ring), so a data-only edit of the
  registry cannot loosen them, and a matrix token that does not resolve fails by name.

  Not checked, by design: hover and pressed fills against the surfaces, because WCAG 2.2
  SC 1.4.11 does not ask a hover or pressed indicator to contrast with the rest state, and no three
  dark primary states 5 L\* apart fit between the white label's 4.5:1 (L\* ≤ 49.9) and 3:1 on
  `color.surface.app` (L\* ≥ 40.0); and plain `disabled` (no reason), which dims the whole control,
  label included, to `opacity.disabled`: an inactive control, which SC 1.4.3 exempts.

### Changed

- Five label-on-fill pairs were below WCAG 2.2 AA 4.5:1, two state pairs were under 5 L\* apart,
  and the light danger fill was under 3:1 on the raised and overlay surfaces (#3896). Each fix
  re-points a semantic token in the theme that failed; no existing primitive value changed.

  | Theme         | Token                         | Was                                 | Now                                 | Label on fill | Lightness step    |
  | ------------- | ----------------------------- | ----------------------------------- | ----------------------------------- | ------------- | ----------------- |
  | dark          | `color.action.primary.hover`  | `palette.blue.400` `#4A86EE`        | `palette.blue.600` `#1F55BF`        | 3.54 → 6.75   | 9.53 from default |
  | dark          | `color.action.primary.active` | `palette.blue.600` `#1F55BF`        | `palette.blue.700` `#173F8F`        | 6.75 → 9.79   | 10.12 from hover  |
  | dark          | `color.buy.hover`             | `palette.green.400` `#4FC86F`       | `palette.green.300` `#6BD48A`       | 9.05 → 10.51  | 4.51 → 9.51       |
  | light         | `color.status.danger.default` | `palette.light.amber.500` `#B87F0A` | `palette.light.red.800` `#7A1E22`   | 3.45 → 10.31  | (one state)       |
  | light         | `color.buy.hover`             | `palette.light.green.300` `#1E9448` | `palette.light.green.700` `#0E5A27` | 3.90 → 8.37   | 11.90, now darker |
  | light         | `color.sell.hover`            | `palette.light.red.300` `#B8353A`   | `palette.light.red.350` `#962C30`   | 5.82 → 7.78   | 3.08 → 10.91      |
  | high contrast | `color.action.primary.active` | `palette.blue.600` `#1F55BF`        | `palette.blue.450` `#3676EB`        | 2.87 → 4.56   | 5.22 from hover   |
  | high contrast | `color.status.danger.default` | `palette.red.600` `#C93A3F`         | `palette.red.550` `#D8474B`         | 3.83 → 4.54   | (one state)       |

  The light danger rest fill now clears 3:1 on every surface (overlay 2.76 → 8.24, raised
  2.999 → 8.95). High contrast now sets `color.action.primary.hover` (`palette.blue.400`) and
  `color.buy.hover` (`palette.green.400`) itself, so dark's new values leave it unchanged. Light
  buy hover is `palette.light.green.700`, two steps below rest, not the nearer `.600`: its step is
  14.03 ΔE (6.07 with `.600`), and under deuteranopia the hovered buy fill sits 24.91 ΔE from the
  resting sell fill and 9.55 from the hovered one (18.98 and 5.00 with `.600`).

  Thin margins, held by both gates (any later nudge fails them): high-contrast buy rest to hover
  5.0017 L\*, high-contrast danger label 4.54:1 and pressed primary label 4.56:1 (hue 9.13
  degrees from rest). High-contrast `color.status.danger.default` (`palette.red.550`) is 5.14 ΔE
  from `color.env.live` (`palette.red.500`; 8.49 with main's `palette.red.600`); the LIVE accent
  always carries its text label. Lighter reds that clear the near-black label better
  (`palette.red.400`, `.500`) are `color.sell.hover` and `color.env.live` themselves.

- Cascade: `color.data-confidence.disconnected.indicator` aliases `color.status.danger.default`,
  so it follows it (#3896): light `#B87F0A` → `#7A1E22` (no longer the amber of `reconnecting`),
  high contrast `#C93A3F` → `#D8474B`. The E08-D04 data-confidence contrast checks pass.

- Light `color.status.danger.default` is a dark red, as dark's `palette.red.600` is: it was
  `color.status.warning.default`'s colour, and an amber that clears the white label would have been
  `color.status.warning.strong` and `color.status.danger.strong` (`#9A6A05`) too, which collapses
  the light liquidation-intensity ramp to one colour (#3896). It is 27.13 ΔE from
  `color.sell.default` (9.24 from `color.sell.hover`), 48.18 from `color.status.danger.strong`, and
  the ramp now runs `#7A1E22` → `#9A6A05` (9.62 → 4.41:1 on the canvas). Like dark's danger it is
  set apart from sell by lightness, not hue. `color.status.danger.strong` still equals
  `color.status.warning.strong` in light; that split is owner decision A6 of the E05-D02 component
  spec (#161, PR #3914).
- High-contrast `color.focus.ring`: `palette.blue.300` `#6EA1F5` → `palette.white` `#FFFFFF`
  (#3896). It was the primary rest fill (0.00 ΔE) and 16.13 ΔE from the hover fill, so on a
  focused primary button it read as part of the fill. It now clears 15.99 to 21.00:1 on every
  surface tier and is 58.5 to 89.2 ΔE from the primary and selected fills. Dark and light keep
  their rings.
- State direction: under a white label a fill can only darken (4.5:1 needs L\* ≤ 49.9, and dark's
  primary rest fill is at 48.3), so dark's primary hover and pressed fills now darken, as light's
  do; dark's buy and sell hovers still lighten under their near-black label. Light darkens every
  state, and high contrast keeps darkening. Dark's primary hover and pressed fills now measure
  2.87:1 and 1.98:1 on the app surface (hover was 5.47:1).

## [0.1.0] - 2026-09-29

### Added

- Initial authored token source of truth: `primitives.tokens.json` (Tier 1),
  `semantic-dark.tokens.json` (Tier 2 source of truth), `semantic-light.tokens.json`,
  `semantic-hc.tokens.json` (theme overlays), `themes.json` (theme/density
  composition).
- Style Dictionary multi-target build (`scripts/build-tokens.mjs`,
  `style-dictionary.config.json`) producing all six artefacts from
  `docs/plan/16-design-system-brief.md#11`: three theme CSS files, the typed
  TS token object, the WebGL engine uniform buffer, and the Electron main
  JSON.
- Custom Style Dictionary formats `json/flat-rgba`, `json/flat`,
  `typescript/nested-object` in `tools/style-dictionary/formats/`.
- Theme-parity (`TOKENS-E001`), alias-resolution (`TOKENS-E002`), and
  engine-category (`TOKENS-E003`) build-time checks.
- ESLint `candleviewer/no-raw-design-values` rule forbidding raw hex colours
  and raw `px` literals in `packages/ui/src/**`.
