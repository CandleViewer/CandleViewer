# E47-D03 / 03 scr116-high-contrast

File `E47-D03 boards`, page `E47-D03 themes and SCR-116`; export `docs/design/E47/img/E47-D03-03-scr116-high-contrast.png`; sheet `03-scr116-high-contrast.json` (validated); theme hc.

Board 03 of 10 (§0 L68: V-3: high contrast with the border.control weight and the retuned link (hc+: Blue clears 7, no W-1)). Grid (12000, 0); 1920 x 1000 px; "page E47-D03 themes and SCR-116 · board 03 · r1".

## Frames

- `SCR-116∕default · hc` (§G: `SCR-116/default · hc`)

## Validator and size

- `03-scr116-high-contrast.json: 0 errors, 0 warnings, 11 sections, 39471 bytes` (exit 0)
- 11 sections, 39471 bytes

## Live checks (7)

- swatch 'Purple' (hc): rebind its fill from color.node.logic to palette.purple.400 (§8.2's primitive, BQ-8); read back that the check glyph stays color.text.inverse
- board 03: color.text.link and color.border.strong resolve to the base hc values until E47-D10 applies D03-D1 … D03-D3; if the hc set is unchanged at render, export with the PROPOSED values bound (palette.blue.200 for the link, palette.neutral.600 for color.border.strong) and say so in §0
- root 'E47-D03 / 03 scr116-high-contrast' at (12000, 0): read back the name exactly after the first section call; size 1920 x 1000
- after touchTexts + relayout: the annotation column (estimated 610 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'SCR-116∕default · hc': read back 1280 x 800 at (80, 80); clip on, no child spills
- theme: activate the hc token set before exporting board 03; read back one bound fill (color.surface.canvas) as the hc value
- export docs/design/E47/img/E47-D03-03-scr116-high-contrast.png: every frame is 1280 x 800; record the board id and the PNG size in §0

## Ambiguities (1)

- Board 03 draws hc+ (§0: 'Blue clears 7, no W-1') but binds tokens that resolve to the base hc values today (palette.blue.200 does not exist yet): the export shows hc+ only after E47-D10 or a live rebind; border.control is drawn as border.thick

## Spec gaps (0)

## Deviations (0)

## Copy keys (11)

- W-20 (§13 L550, PROPOSED): Sample data
- W-19 (§13 L549, PROPOSED): Preview: dark theme, Blue accent, default chart palette, compact
- W-18 (§13 L548, PROPOSED): Reset appearance
- W-4 (§13 L534, verbatim): Default (green / red)
- W-5 (§13 L535, verbatim): Colour-blind safe (blue / orange)
- W-22 (§13 L552, PROPOSED): Match system theme
- W-9 (§13 L539, PROPOSED): Accent: Blue · Cyan · Amber · Purple
- W-6 (§13 L536, verbatim): Invert buy/sell colours
- W-11 (§13 L541, PROPOSED): Text size: 100 % · 112 % · 125 % · 150 %
- W-10 (§13 L540, PROPOSED): Grid lines: Off · Subtle · Strong
- W-2 (§13 L532, verbatim): Theme changed to High Contrast

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

- spec E47-D03.md md5 b42ea2be and hand-off E47-D03-handoff.md md5 9115b708 (§0 L68; hand-off §G L127)

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
- border.thick
- space.inset.md
- color.surface.selected
- color.surface.sunken
- color.focus.ring
- border.focus
- radius.badge
- type.ui.heading-sm
- space.stack.sm
- color.text.inverse
- size.icon
- color.text.link
- color.border.selected
- color.status.info.strong
- color.status.warning.strong
- color.node.logic
- color.action.primary.default
- space.stack.lg
- space.inset.xl
- color.surface.app
- color.surface.hover
- space.stack.xs
- type.ui.label
- color.text.tertiary
