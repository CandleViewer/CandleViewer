# E05-D02 / 01 actions

File `E05-D02 boards`, page `E05-D02 slice 1 actions and selection` (render with `--page`); export `docs/design/E05/img/E05-D02-01-actions.png`; sheet `01-actions.json` (validated); theme dark.

01-actions.json: 0 errors, 33 warnings, 23 sections, 147066 bytes

## Blocks

- `CMP-001 · Button` — slice 1 L621-694; spec export `img/CMP-001-button.png`
- `CMP-002 · IconButton` — slice 1 L695-764; spec export `img/CMP-002-iconbutton.png`
- `CMP-003 · SegmentedControl` — slice 1 L765-835; spec export `img/CMP-003-segmentedcontrol.png`
- `CMP-004 · Toggle` — slice 1 L836-908; spec export `img/CMP-004-toggle-switch.png`

## Content checks

- every CMP-001 Variant x the seven States at md; sm / lg at default; buy / sell arrows in every cell
- CMP-002 four variants x five States, sizes, Pressed=true (incl. gated pressed, outline kept)
- CMP-003 text and icon-only x five States; size sm; Options 2
- CMP-004 Checked=false x five States, Checked=true default / hover / focus / T2, Critical off / on, left, hidden
- T2 cells: lock leads, label + lock color.text.tertiary, reason in caption secondary

## Live checks for the drawer

- render on page 'E05-D02 slice 1 actions and selection' (mkcall4.py … --page 'E05-D02 slice 1 actions and selection'; its default would be 'E05-D02')
- root 'E05-D02 / 01 actions': hugs its content (about 4780 x 1471 px estimated)

## Not drawn — the text is binding

- CMP-001: comfortable density (size.control.height 32) — not drawn, the text is binding (slice 1 L621-694)
- CMP-001: sizes sm / lg x every non-default State (derivable, s1 §6 C13) — not drawn, the text is binding (slice 1 L621-694)
- CMP-001: the 5 s slow-path text 'Checking with the exchange…' (CMP-038, board 08) — not drawn, the text is binding (slice 1 L621-694)
- CMP-001: iconLeft / iconRight on the non-directional variants — not drawn, the text is binding (slice 1 L621-694)
- CMP-001: the CMP-044 confirm wrapper Variant=danger opens (board 09) — not drawn, the text is binding (slice 1 L621-694)
- CMP-002: sizes sm / lg x every non-default State — not drawn, the text is binding (slice 1 L695-764)
- CMP-002: Pressed=true on primary / danger (C1 B) — not drawn, the text is binding (slice 1 L695-764)
- CMP-002: the D10 name tooltip (proposed, not in the catalogue) — not drawn, the text is binding (slice 1 L695-764)
- CMP-002: comfortable density (32 px) — not drawn, the text is binding (slice 1 L695-764)
- CMP-003: Options 6 (the spec gives no six sample labels: a copy gap) — not drawn, the text is binding (slice 1 L765-835)
- CMP-003: fullWidth — not drawn, the text is binding (slice 1 L765-835)
- CMP-003: size sm x every non-default State — not drawn, the text is binding (slice 1 L765-835)
- CMP-003: comfortable density — not drawn, the text is binding (slice 1 L765-835)
- CMP-004: Checked=true x disabled (derivable) — not drawn, the text is binding (slice 1 L836-908)
- CMP-004: Critical x every non-default State — not drawn, the text is binding (slice 1 L836-908)
- CMP-004: the critical confirm wrapper (D3: CMP-044, board 09) — not drawn, the text is binding (slice 1 L836-908)
- CMP-004: comfortable density — not drawn, the text is binding (slice 1 L836-908)

## Strings used

- 'Save' — CMP-001 slice 1 L621-694
- 'Buy / Long' — CMP-001 slice 1 L621-694
- 'Sell / Short' — CMP-001 slice 1 L621-694
- "Owner only: your role can't use this action." — CMP-001 slice 1 L621-694
- "Owner only: your role can't use this action." — CMP-002 slice 1 L695-764
- 'Ascending' — CMP-003 slice 1 L765-835
- 'Unsorted' — CMP-003 slice 1 L765-835
- 'Descending' — CMP-003 slice 1 L765-835
- "Read-only: your role can't change this setting." — CMP-003 slice 1 L765-835
- 'Increase focus-ring thickness' — slice 1 (outside the CMP section)
- '1-click arm' — CMP-004 slice 1 L836-908

## Stamps

- PROPOSED · slice 1 D1 (slice 1 L443)
- PROPOSED · slice 1 D13 (slice 1 L481)
- PROPOSED · slice 1 D16 (slice 1 L529)
- PROPOSED · slice 1 A12 (slice 1 L333)
- PROPOSED · slice 1 B3 (slice 1 L349)
- PROPOSED · slice 1 A11 (slice 1 L325)
- PROPOSED · slice 1 A2 (slice 1 L267)
- RULED · #3925 (slice 1)
- RULED · E09-D09 §2.2 (slice 1)
- PROPOSED · slice 1 C1 (slice 1 L375)
- PROPOSED · slice 1 D10 (slice 1 L472)
- PROPOSED · slice 1 A10 (slice 1 L318)
- PROPOSED · slice 1 C2 (slice 1 L384)
- PROPOSED · slice 1 C3 (slice 1 L388)
- PROPOSED · slice 1 C14 (slice 1 L431)
- PROPOSED · slice 1 D5 (slice 1 L464)
- PROPOSED · slice 1 D17 (slice 1 L533)
- PROPOSED · slice 1 D3 (slice 1 L451)
- PROPOSED · slice 1 D4 (slice 1 L458)
- PROPOSED · slice 1 C4 (slice 1 L392)
- PROPOSED · slice 1 A3 (slice 1 L275)

## Kit choices and deviations

- kit choice (specimen): Each state is a cell: the specimen on a color.surface.app plate (the matrix cells of slice 1 §1.1), its state caption under it in type.ui.caption color.text.secondary; cells sit in state rows led by a 120 px row label; a block is a color.surface.canvas card with a 1 px color.border.subtle edge
- kit choice (focus): A focus ring is CMP-039's 2 px color.focus.ring (border.focus) rect, positioned 2 px outside the control on a flex wrapper 4 px larger than it (radius.md = radius.control + 2, FALLBACKS RING)
- kit choice (t2): T2 (E09-D09 §2.2, slices 3-4 conventions 24 / 36-37; it supersedes slice 1 §3's trailing lock): the shape loses its enabled look (color.surface.raised fill, 1 px color.border.default hairline), the CMP-019 lock LEADS the full label, label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary (2a inline); icon-only controls carry a size.icon.sm lock badge bottom-right and a CMP-016 echo of the reason (2b); never color.text.disabled, never opacity.disabled on label, glyph or reason
- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS ICONS)
- kit choice (page): mkcall4.py derives a page from the board name ('E05-D02 / NN …' -> 'E05-D02'); the sheet carries its page in sheet['page'] and the renderer passes --page '<page>' (live check)

## Tokens and fallbacks

- token: the CMP-039 ring's radius (radius.control + 2 = 6 px, slice 1 §5.1, no token) binds the Tier-1 primitive radius.md (6 px; validator WARN)
- token: opacity.disabled / opacity.scrim are Tier-1 primitives (slice 1 §1 names them; validator WARN)
- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'
- fallback: CMP-014's arc has no dashed / partial stroke in cvsheet: drawn as a full ring in color.border.default with a short arc rect in the indicator colour (a static frame of the spin)
- token: size.icon.sm (12) / size.icon.lg (20) are Tier-1 primitives (slice 1 §1, validator WARN)

## Copy gaps

## Sources

- spec docs/design/E05/E05-D02.md at 966f9edcd md5 72dc9ede4f3ce6a4620ffd50816cb935 (frozen copy E05-D02@966f9edcd.md)
- Penpot file 'E05-D02 boards', page 'E05-D02 slice 1 actions and selection'; kit e05d02kit.py md5 1af7cacf448b9098924bf67629612f6b

## Shape count

- {"sheet": "01-actions.json", "shapes": 861, "texts": 291, "by_type": {"board": 463, "ellipse": 19, "icon": 68, "rect": 20, "text": 291}, "sections": 23, "bytes": 147066, "largest_section": 11088, "largest_compacted": 7262}
