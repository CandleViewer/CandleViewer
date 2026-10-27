# E05-D02 / 03 tags-badges-avatars

File `E05-D02 boards`, page `E05-D02 slice 2 data display and text` (render with `--page`); export `docs/design/E05/img/E05-D02-03-tags-badges-avatars.png`; sheet `03-tags-badges-avatars.json` (validated); theme dark.

validator: 03-tags-badges-avatars.json: 0 errors, 4 warnings, 12 sections, 71980 bytes

## Blocks

- `CMP-011 · Tag` — slice 2 L384-466; spec export `img/CMP-011-tag-chip.png`
- `CMP-012 · Badge` — slice 2 L467-540; spec export `img/CMP-012-badge-status-dot-count.png`
- `CMP-013 · Avatar` — slice 2 L541-603; spec export `img/CMP-013-avatar-profilebadge-base.png`
- `CMP-025 · Avatar Group` — slice 2 L872-938; spec export `img/CMP-025-avatar-group-stack.png`
- `CMP-032 · Confidence Dots` — slice 2 L1001-1065; spec export `img/CMP-032-rating-confidence-dots.png`
- `CMP-037 · SwatchLegendItem` — slice 2 L1134-1199; spec export `img/CMP-037-swatchlegenditem.png`

## Content checks

- every specimen string is say()'d from slice 2 (or slice 1's rbac reason); no inst node; icons: close, locked
- every gated cell is T2: CMP-011's remove button 2b (lock badge + CMP-016 echo), no disabled token on it
- status chips and dots carry a glyph and a word; Badge numerals in color.text.primary (E3 tinted count)

## Live checks for the drawer

- set the estimated chip's 1 px outline to Penpot's default dash (cvsheet has no dash key)
- check the CMP-025 cut-out rings read on the app plate (E23: an outline on app)
- render on page 'E05-D02 slice 2 data display and text' (mkcall4.py … --page 'E05-D02 slice 2 data display and text'; its default would be 'E05-D02')
- root 'E05-D02 / 03 tags-badges-avatars': hugs its content (about 3153 x 1324 px estimated)

## Not drawn — the text is binding

- CMP-011: Removable=true on info / warning / danger / estimated (E10: neutral only) — not drawn, the text is binding (slice 2 L384-466)
- CMP-011: estimated State=disabled (E19: an honesty marker is never dimmed; CMP-227 has no disabled state, so the drawn variant becomes a note) — not drawn, the text is binding (slice 2 L384-466)
- CMP-011: Icon=true on the status chips (their registry glyph is always shown, E10) — not drawn, the text is binding (slice 2 L384-466)
- CMP-011: comfortable density (32 px chip and remove target) — not drawn, the text is binding (slice 2 L384-466)
- CMP-012: multi-digit counts and the "99+" cap (E11, held) — not drawn, the text is binding (slice 2 L467-540)
- CMP-012: a dot alone (never rendered alone: always with its word) — not drawn, the text is binding (slice 2 L467-540)
- CMP-013: Size lg (no token above size.control.height) — not drawn, the text is binding (slice 2 L541-603)
- CMP-013: the ColorPalette story (E2: no avatar palette token yet) — not drawn, the text is binding (slice 2 L541-603)
- CMP-013: comfortable density (md 32 px) — not drawn, the text is binding (slice 2 L541-603)
- CMP-025: the ring on raised / hover surfaces (E23) — not drawn, the text is binding (slice 2 L872-938)
- CMP-025: comfortable density (16 px overlap) — not drawn, the text is binding (slice 2 L872-938)
- CMP-032: a label override (it must still name the level) — not drawn, the text is binding (slice 2 L1001-1065)
- CMP-032: inside CMP-227 ("Estimated, low confidence") — not drawn, the text is binding (slice 2 L1001-1065)
- CMP-037: HasValue=false + HasGlyph=true (not in the draw list; E16) — not drawn, the text is binding (slice 2 L1134-1199)
- CMP-037: the color.heatmap.ask.3 "Ask liquidity" 0.8M override row (a third keyed sample) — not drawn, the text is binding (slice 2 L1134-1199)
- CMP-037: a two-line label (the row grows in code) — not drawn, the text is binding (slice 2 L1134-1199)

## Strings used

- 'Breakout' — CMP-011 slice 2 L384-466
- '(estimated)' — CMP-011 slice 2 L384-466
- "Owner only: your role can't use this action." — slice 1 (outside the CMP section)
- 'Syncing' — CMP-012 slice 2 L467-540
- 'Degraded' — CMP-012 slice 2 L467-540
- 'Blocked' — CMP-012 slice 2 L467-540
- 'Alerts' — CMP-012 slice 2 L467-540
- 'Idle' — CMP-012 slice 2 L467-540
- 'Healthy' — CMP-012 slice 2 L467-540
- 'AD' — slice 2 (outside the CMP section)
- 'A' — CMP-013 slice 2 L541-603
- 'Alpha Desk' — CMP-013 slice 2 L541-603
- 'BS' — slice 2 (outside the CMP section)
- 'CF' — slice 2 (outside the CMP section)
- '+2' — CMP-025 slice 2 L872-938
- 'Low confidence' — CMP-032 slice 2 L1001-1065
- 'Medium confidence' — CMP-032 slice 2 L1001-1065
- 'High confidence' — CMP-032 slice 2 L1001-1065
- 'Bid liquidity' — CMP-037 slice 2 L1134-1199
- '1.2M' — CMP-037 slice 2 L1134-1199
- '▼' — CMP-037 slice 2 L1134-1199
- 'Sell volume' — CMP-037 slice 2 L1134-1199
- '0.9M' — CMP-037 slice 2 L1134-1199
- 'Zero intensity' — CMP-037 slice 2 L1134-1199

## Stamps

- PROPOSED · slice 2 E10 (slice 2 L277)
- PROPOSED · slice 2 E18 (slice 2 L312)
- PROPOSED · slice 2 E19 (slice 2 L323)
- PROPOSED · slice 2 E9 (slice 2 L270)
- RULED · #3953 (slice 2)
- PROPOSED · slice 2 E11 (slice 2 L282)
- PROPOSED · slice 2 E5 (slice 2 L250)
- PROPOSED · slice 2 E3 (slice 2 L238)
- PROPOSED · slice 2 E2 (slice 2 L233)
- PROPOSED · slice 2 E12 (slice 2 L286)
- PROPOSED · slice 2 E6 (slice 2 L257)
- PROPOSED · slice 2 E23 (slice 2 L346)
- PROPOSED · slice 2 E4 (slice 2 L248)
- PROPOSED · slice 2 E17 (slice 2 L309)
- PROPOSED · slice 2 E16 (slice 2 L303)
- PROPOSED · slice 2 E26 (slice 2 L359)

## Kit choices and deviations

- CMP-011 estimated chip: cvsheet has no dash key; the 1 px color.status.info.strong outline is drawn solid and set to Penpot's default dash live (live check); CMP-227 governs its look (E19)
- CMP-011 icon-left: the hidden placeholder icon/pin is not a local icon; drawn as the text glyph ●
- CMP-012 / CMP-032 dots: drawn as 8 x 8 px radius.badge rects (cvsheet sizes by w / h); the spec's space.inset.xs-padded empty board and its 0.01 px spacer are Penpot workarounds (§4.1, E5)
- CMP-025 overlap: avatars and the +N chip sit at 16 px pitch (the size.icon slot width) inside a fixed board, positioned (abs) because cvsheet has no clip-off slot; the spec's flex slots are the build's
- kit choice (specimen): Each state is a cell: the specimen on a color.surface.app plate (the matrix cells of slice 1 §1.1), its state caption under it in type.ui.caption color.text.secondary; cells sit in state rows led by a 120 px row label; a block is a color.surface.canvas card with a 1 px color.border.subtle edge
- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS ICONS)
- kit choice (focus): A focus ring is CMP-039's 2 px color.focus.ring (border.focus) rect, positioned 2 px outside the control on a flex wrapper 4 px larger than it (radius.md = radius.control + 2, FALLBACKS RING)
- kit choice (t2): T2 (E09-D09 §2.2, slices 3-4 conventions 24 / 36-37; it supersedes slice 1 §3's trailing lock): the shape loses its enabled look (color.surface.raised fill, 1 px color.border.default hairline), the CMP-019 lock LEADS the full label, label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary (2a inline); icon-only controls carry a size.icon.sm lock badge bottom-right and a CMP-016 echo of the reason (2b); never color.text.disabled, never opacity.disabled on label, glyph or reason
- kit choice (page): mkcall4.py derives a page from the board name ('E05-D02 / NN …' -> 'E05-D02'); the sheet carries its page in sheet['page'] and the renderer passes --page '<page>' (live check)

## Tokens and fallbacks

- token: the CMP-039 ring's radius (radius.control + 2 = 6 px, slice 1 §5.1, no token) binds the Tier-1 primitive radius.md (6 px; validator WARN)
- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'
- token: size.icon.sm (12) / size.icon.lg (20) are Tier-1 primitives (slice 1 §1, validator WARN)

## Copy gaps

## Sources

- spec docs/design/E05/E05-D02-data-display.md at 966f9edcd md5 fa72d69bce5362a9430f20a0feaf39a3 (frozen copy E05-D02-data-display@966f9edcd.md)
- Penpot file 'E05-D02 boards', page 'E05-D02 slice 2 data display and text'; kit e05d02kit.py md5 1af7cacf448b9098924bf67629612f6b

## Shape count

- {"sheet": "03-tags-badges-avatars.json", "shapes": 379, "texts": 174, "by_type": {"board": 180, "icon": 6, "rect": 19, "text": 174}, "sections": 12, "bytes": 71980, "largest_section": 11990, "largest_compacted": 7310}
