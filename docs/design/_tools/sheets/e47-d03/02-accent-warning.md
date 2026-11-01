# E47-D03 / 02 accent-warning

File `E47-D03 boards`, page `E47-D03 themes and SCR-116`; export `docs/design/E47/img/E47-D03-02-accent-warning.png`; sheet `02-accent-warning.json` (validated); theme light.

Board 02 of 10 (§0 L67: V-2: Amber in light below 4.5:1 on a selected row, W-1 with its warning glyph, the live-region note, the accent kept off text). Grid (6000, 0); 1920 x 1000 px; "page E47-D03 themes and SCR-116 · board 02 · r1".

## Frames

- `SCR-116∕accent-below-bar · light` (§G: `SCR-116/accent-below-bar · light`)

## Validator and size

- `02-accent-warning.json: 0 errors, 0 warnings, 12 sections, 41773 bytes` (exit 0)
- 12 sections, 41773 bytes

## Live checks (8)

- PreviewTile positions row (light): rebind its 2 px selected-row stroke from color.status.warning.strong to palette.light.amber.700 (the Amber accent on non-text emphasis, §8.2)
- swatch 'Cyan' (light): rebind its fill from color.status.info.strong to palette.cyan.700 (§8.2's primitive, BQ-8); read back that the check glyph stays color.text.inverse
- swatch 'Amber' (light): rebind its fill from color.status.warning.strong to palette.light.amber.700 (§8.2's primitive, BQ-8); read back that the check glyph stays color.text.inverse
- root 'E47-D03 / 02 accent-warning' at (6000, 0): read back the name exactly after the first section call; size 1920 x 1000
- after touchTexts + relayout: the annotation column (estimated 777 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'SCR-116∕accent-below-bar · light': read back 1280 x 800 at (80, 80); clip on, no child spills
- theme: activate the light token set before exporting board 02; read back one bound fill (color.surface.canvas) as the light value
- export docs/design/E47/img/E47-D03-02-accent-warning.png: every frame is 1280 x 800; record the board id and the PNG size in §0

## Ambiguities (1)

- Board 02: Amber's light primitive (palette.light.amber.700) and Cyan's (palette.cyan.700) have no semantic alias in the light set; the swatches and the selected-row border bind same-hue stand-ins and carry live rebind steps

## Spec gaps (0)

## Deviations (0)

## Copy keys (12)

- W-20 (§13 L550, PROPOSED): Sample data
- W-19 (§13 L549, PROPOSED): Preview: dark theme, Blue accent, default chart palette, compact
- W-18 (§13 L548, PROPOSED): Reset appearance
- W-4 (§13 L534, verbatim): Default (green / red)
- W-5 (§13 L535, verbatim): Colour-blind safe (blue / orange)
- W-22 (§13 L552, PROPOSED): Match system theme
- W-9 (§13 L539, PROPOSED): Accent: Blue · Cyan · Amber · Purple
- W-1 (§13 L531, verbatim): This combination fails contrast — text may be hard to read.
- W-21 (§13 L551, PROPOSED): Purple is used for borders and highlights only until it passes.
- W-6 (§13 L536, verbatim): Invert buy/sell colours
- W-11 (§13 L541, PROPOSED): Text size: 100 % · 112 % · 125 % · 150 %
- W-10 (§13 L540, PROPOSED): Grid lines: Off · Subtle · Strong

## Copy gaps (9)

- "Price": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Bid": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Ask": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Delta": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Symbol": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Size": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Entry": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "PnL": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)
- "Appearance": the current settings entry and the h1, from §0 L62 (the shipped AppearanceScreen) and §8.4 L462; §13 has no title string

## Fallbacks (3)

- fallback: border.control (D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind its values directly, border.hairline in dark and light, border.thick in high contrast
- fallback: where no semantic alias resolves to a preset's §8.2 primitive in the board's theme, the swatch binds the same-hue stand-in and the live drawer rebinds it to the primitive (the validator refuses primitive colour binds)
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and CMP-086's settings list drawn as neutral placeholders; only SCR-116's content, the PreviewTile and the env badges of board 08 are drawn

## Sources (1)

- spec E47-D03.md md5 dcf7a14b and hand-off E47-D03-handoff.md md5 9115b708 (§0 L67; hand-off §G L126)

## Tokens (46)

- type.ui.heading-md
- color.text.primary
- type.num.base
- space.inset.sm
- space.inset.xs
- radius.control
- color.footprint.bid
- color.footprint.ask
- color.surface.raised
- type.ui.body
- color.surface.selected
- color.status.warning.strong
- border.thick
- type.ui.caption
- color.text.secondary
- space.stack.md
- space.inset.lg
- color.surface.canvas
- radius.card
- color.border.subtle
- border.hairline
- type.ui.body-strong
- space.button.paddingX
- color.action.secondary.default
- color.border.strong
- space.inset.md
- color.surface.sunken
- radius.badge
- type.ui.heading-sm
- space.stack.sm
- color.text.link
- color.status.info.strong
- color.text.inverse
- size.icon
- color.border.selected
- color.focus.ring
- border.focus
- color.node.logic
- space.stack.xs
- color.action.primary.default
- space.inset.xl
- space.stack.lg
- color.surface.app
- color.surface.hover
- type.ui.label
- color.text.tertiary
