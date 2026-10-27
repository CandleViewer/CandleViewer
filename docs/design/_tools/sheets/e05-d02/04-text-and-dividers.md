# E05-D02 / 04 text-and-dividers

File `E05-D02 boards`, page `E05-D02 slice 2 data display and text` (render with `--page`); export `docs/design/E05/img/E05-D02-04-text-and-dividers.png`; sheet `04-text-and-dividers.json` (validated); theme dark.

validator: 04-text-and-dividers.json: 0 errors, 5 warnings, 13 sections, 72675 bytes

## Blocks

- `CMP-018 · Divider` — slice 2 L604-661; spec export `img/CMP-018-divider.png`
- `CMP-020 · Typography primitives` — slice 2 L662-735; spec export `img/CMP-020-typography-primitives-text-heading-numerictext-monotext.png`
- `CMP-021 · Link` — slice 2 L736-811; spec export `img/CMP-021-link.png`
- `CMP-024 · Sparkline` — slice 2 L812-871; spec export `img/CMP-024-sparkline.png`
- `CMP-030 · Divider-Label` — slice 2 L939-1000; spec export `img/CMP-030-divider-label.png`
- `CMP-033 · CopyButton` — slice 2 L1066-1133; spec export `img/CMP-033-copybutton.png`

## Content checks

- every specimen string is say()'d from slice 2; no inst node; no icon (every glyph a text glyph)
- CMP-021 draws default / focus-visible / disabled x External and lists disabled-with-reason as not drawn (E27 PROPOSED), per build-notes §4 board 04
- colorBySign cells carry the sign; the zero cell is unsigned in color.neutral.default

## Live checks for the drawer

- CMP-024 segments: check the stepped polyline reads as one line at 1x
- CMP-018 / CMP-030 rules: 1.31:1 on app (slice 2 §4.3), confirm they render (1 px, not anti-aliased away)
- render on page 'E05-D02 slice 2 data display and text' (mkcall4.py … --page 'E05-D02 slice 2 data display and text'; its default would be 'E05-D02')
- root 'E05-D02 / 04 text-and-dividers': hugs its content (about 3189 x 1176 px estimated)

## Not drawn — the text is binding

- CMP-018: the light Menu / Popover case (border.subtle = surface.overlay, 1.00:1; CMP-018's open question) — not drawn, the text is binding (slice 2 L604-661)
- CMP-018: the decorative / separator semantics (not visual) — not drawn, the text is binding (slice 2 L604-661)
- CMP-020: Format qty / pct / pnl (pnl and colorBySign require SignDisplay=always, E14) — not drawn, the text is binding (slice 2 L662-735)
- CMP-020: SignDisplay=never — not drawn, the text is binding (slice 2 L662-735)
- CMP-020: the right-aligned 160 px numeric column (align-demo) — not drawn, the text is binding (slice 2 L662-735)
- CMP-020: mono-text in every num-* style — not drawn, the text is binding (slice 2 L662-735)
- CMP-021: State=disabled-with-reason: held until slice 2 §5 E27 is answered (s2 L750: a T2 link or none; the host owns the gating) — not drawn, the text is binding (slice 2 L736-811)
- CMP-021: hover, active and visited (E18: none for v0) — not drawn, the text is binding (slice 2 L736-811)
- CMP-021: an inline link wrapping with its sentence — not drawn, the text is binding (slice 2 L736-811)
- CMP-024: the 256 x 64 size demo — not drawn, the text is binding (slice 2 L812-871)
- CMP-024: the y-range floor (E22, proposed) — not drawn, the text is binding (slice 2 L812-871)
- CMP-030: a wrapped caption in a very narrow container — not drawn, the text is binding (slice 2 L939-1000)
- CMP-033: State=disabled-with-reason (E21: copying a visible value is never gated) — not drawn, the text is binding (slice 2 L1066-1133)
- CMP-033: a copy-failure state (E20, proposed) — not drawn, the text is binding (slice 2 L1066-1133)
- CMP-033: comfortable density (32 px) — not drawn, the text is binding (slice 2 L1066-1133)

## Strings used

- 'Take profit' — slice 2 (outside the CMP section)
- '+420.00' — CMP-020 slice 2 L662-735
- '-420.00' — CMP-020 slice 2 L662-735
- '0.00' — CMP-020 slice 2 L662-735
- '420.00' — CMP-020 slice 2 L662-735
- '1.2M' — CMP-020 slice 2 L662-735
- '17279edf' — CMP-020 slice 2 L662-735
- 'Shortcut settings' — CMP-021 slice 2 L736-811
- 'Bybit API documentation' — CMP-021 slice 2 L736-811
- 'Take profit' — CMP-030 slice 2 L939-1000
- 'Stop loss' — CMP-030 slice 2 L939-1000
- 'Copied' — CMP-033 slice 2 L1066-1133

## Stamps

- PROPOSED · slice 2 E13 (slice 2 L290)
- PROPOSED · slice 2 E1 (slice 2 L225)
- PROPOSED · slice 2 E14 (slice 2 L294)
- PROPOSED · slice 2 E15 (slice 2 L299)
- PROPOSED · slice 2 E27 (slice 2 L363)
- PROPOSED · slice 2 E8 (slice 2 L266)
- PROPOSED · slice 2 E18 (slice 2 L312)
- PROPOSED · slice 2 E25 (slice 2 L356)
- PROPOSED · slice 2 E22 (slice 2 L343)
- PROPOSED · slice 2 E24 (slice 2 L351)
- PROPOSED · slice 2 E20 (slice 2 L333)
- PROPOSED · slice 2 E21 (slice 2 L339)

## Kit choices and deviations

- CMP-021: the underline (a text property in Penpot) is drawn as a 1 px color.text.link rect under the label; the external-link icon is not a local icon, drawn as the text glyph → (FALLBACKS ICONS)
- CMP-024: cvsheet has no path node, so the 1.5 px round-capped polyline is drawn as 16 short 4 x 2 px segments on the 64 x 16 sample; the slope and colour read as the spec's (live check)
- kit choice (specimen): Each state is a cell: the specimen on a color.surface.app plate (the matrix cells of slice 1 §1.1), its state caption under it in type.ui.caption color.text.secondary; cells sit in state rows led by a 120 px row label; a block is a color.surface.canvas card with a 1 px color.border.subtle edge
- kit choice (focus): A focus ring is CMP-039's 2 px color.focus.ring (border.focus) rect, positioned 2 px outside the control on a flex wrapper 4 px larger than it (radius.md = radius.control + 2, FALLBACKS RING)
- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS ICONS)
- kit choice (page): mkcall4.py derives a page from the board name ('E05-D02 / NN …' -> 'E05-D02'); the sheet carries its page in sheet['page'] and the renderer passes --page '<page>' (live check)

## Tokens and fallbacks

- token: the CMP-039 ring's radius (radius.control + 2 = 6 px, slice 1 §5.1, no token) binds the Tier-1 primitive radius.md (6 px; validator WARN)

## Copy gaps

## Sources

- spec docs/design/E05/E05-D02-data-display.md at 966f9edcd md5 fa72d69bce5362a9430f20a0feaf39a3 (frozen copy E05-D02-data-display@966f9edcd.md)
- Penpot file 'E05-D02 boards', page 'E05-D02 slice 2 data display and text'; kit e05d02kit.py md5 1af7cacf448b9098924bf67629612f6b

## Shape count

- {"sheet": "04-text-and-dividers.json", "shapes": 438, "texts": 163, "by_type": {"board": 163, "rect": 112, "text": 163}, "sections": 13, "bytes": 72675, "largest_section": 9793, "largest_compacted": 5368}
