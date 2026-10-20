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
- A label-on-fill contrast matrix (#3896): `tools/contrast/label-on-fill.json`, gated in CI by
  `packages/ui/test/contrast/label-on-fill.test.ts` and checked by `tests/verify_tokens.py`. In
  every theme, each filled button role's label clears 4.5:1 on every state fill (in every chart
  colour mode too); a role's states are pairwise at least 5 CIE L\* apart and within 10 degrees of
  the rest fill's LCh hue; each primary, danger, buy and sell rest fill clears 3:1 against
  `color.surface.app`, `.raised` and `.overlay`; and with disabled-with-reason the reason text
  keeps 4.5:1 and the locked glyph 3:1.

  Not checked, by design: hover and pressed fills against the surfaces, because WCAG 2.2
  SC 1.4.11 does not ask a hover or pressed indicator to contrast with the rest state, and no three
  dark primary states 5 L\* apart fit between the white label's 4.5:1 (L\* ≤ 49.9) and 3:1 on
  `color.surface.app` (L\* ≥ 40.0); and the dimmed label of an inactive control
  (`opacity.disabled`, 0.45), which SC 1.4.3 exempts.

### Changed

- Five label-on-fill pairs were below WCAG 2.2 AA 4.5:1, two state pairs were under 5 L\* apart,
  and the light danger fill was under 3:1 on the raised and overlay surfaces (#3896). Each fix
  re-points a semantic token in the theme that failed; no existing primitive value changed.

  | Theme         | Token                         | Was                                 | Now                                 | Label on fill | Lightness step    |
  | ------------- | ----------------------------- | ----------------------------------- | ----------------------------------- | ------------- | ----------------- |
  | dark          | `color.action.primary.hover`  | `palette.blue.400` `#4A86EE`        | `palette.blue.600` `#1F55BF`        | 3.54 → 6.75   | 9.53 from default |
  | dark          | `color.action.primary.active` | `palette.blue.600` `#1F55BF`        | `palette.blue.700` `#173F8F`        | 6.75 → 9.79   | 10.12 from hover  |
  | dark          | `color.buy.hover`             | `palette.green.400` `#4FC86F`       | `palette.green.300` `#6BD48A`       | 9.05 → 10.51  | 4.51 → 9.51       |
  | light         | `color.status.danger.default` | `palette.light.amber.500` `#B87F0A` | `palette.light.amber.300` `#9A6A05` | 3.45 → 4.73   | (one state)       |
  | light         | `color.buy.hover`             | `palette.light.green.300` `#1E9448` | `palette.light.green.600` `#136B30` | 3.90 → 6.62   | 5.57, now darker  |
  | light         | `color.sell.hover`            | `palette.light.red.300` `#B8353A`   | `palette.light.red.350` `#962C30`   | 5.82 → 7.78   | 3.08 → 10.91      |
  | high contrast | `color.action.primary.active` | `palette.blue.600` `#1F55BF`        | `palette.blue.450` `#3676EB`        | 2.87 → 4.56   | 5.22 from hover   |
  | high contrast | `color.status.danger.default` | `palette.red.600` `#C93A3F`         | `palette.red.550` `#D8474B`         | 3.83 → 4.54   | (one state)       |

  The light danger rest fill now clears 3:1 on every surface (overlay 2.76 → 3.78, raised
  2.999 → 4.11). High contrast now sets `color.action.primary.hover` (`palette.blue.400`) and
  `color.buy.hover` (`palette.green.400`) itself, so dark's new values leave it unchanged.

- State direction: under a white label a fill can only darken (4.5:1 needs L\* ≤ 49.9, and dark's
  primary rest fill is at 48.3), so dark's primary hover and pressed fills now darken, as light's
  do; dark's buy and sell hovers still lighten under their near-black label. Light darkens every
  state, and high contrast keeps darkening. Dark's primary hover and pressed fills now measure
  2.87:1 and 1.98:1 on the app surface (hover was 5.47:1).
- Light `color.status.danger.default` now equals `color.status.danger.strong`, so the light
  liquidation-intensity data-ink ramp (default to strong) is one colour (`#9A6A05`, 4.41:1 on the
  canvas). It needs its own anchors or the danger/warning split of owner decision A6 in the E05-D02
  component spec (#161, PR #3914).

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
