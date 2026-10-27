# E05-D02 / 02 selection-and-primitives

File `E05-D02 boards`, page `E05-D02 slice 1 actions and selection` (render with `--page`); export `docs/design/E05/img/E05-D02-02-selection-and-primitives.png`; sheet `02-selection-and-primitives.json` (validated); theme dark.

02-selection-and-primitives.json: 0 errors, 19 warnings, 16 sections, 104991 bytes

## Blocks

- `CMP-005 · Checkbox` — slice 1 L909-977; spec export `img/CMP-005-checkbox.png`
- `CMP-006 · RadioGroup` — slice 1 L978-1045; spec export `img/CMP-006-radiogroup.png`
- `CMP-010 · Slider` — slice 1 L1046-1116; spec export `img/CMP-010-slider.png`
- `CMP-014 · Spinner` — slice 1 L1117-1180; spec export `img/CMP-014-spinner-loader.png`
- `CMP-019 · Icon` — slice 1 L1181-1240; spec export `img/CMP-019-icon.png`
- `CMP-031 · ColorSwatch` — slice 1 L1241-1318; spec export `img/CMP-031-colorswatch-themechip.png`
- `CMP-039 · FocusRing (spec only)` — slice 1 L1319-1372; spec export `img/CMP-039-focusring.png`

## Content checks

- CMP-005 Checked false / true / indeterminate x five States
- CMP-006 vertical x five States, horizontal
- CMP-010 Marks=false x five States, Marks=true
- CMP-014 sm / md, standalone, cancellable load, order submit
- CMP-019 sizes, the five local glyphs, decorative / meaningful
- CMP-031 Selected x five States + picker
- CMP-039 the two reference frames

## Live checks for the drawer

- render on page 'E05-D02 slice 1 actions and selection' (mkcall4.py … --page 'E05-D02 slice 1 actions and selection'; its default would be 'E05-D02')
- root 'E05-D02 / 02 selection-and-primitives': hugs its content (about 4172 x 1180 px estimated)

## Not drawn — the text is binding

- CMP-005: comfortable density (row 32 px; the box stays 16) — not drawn, the text is binding (slice 1 L909-977)
- CMP-005: a hidden-label consumer — not drawn, the text is binding (slice 1 L909-977)
- CMP-006: the option-level lock sample (D7, a documentation sample) — not drawn, the text is binding (slice 1 L978-1045)
- CMP-006: horizontal x every non-default State (derivable) — not drawn, the text is binding (slice 1 L978-1045)
- CMP-006: a group with no selection — not drawn, the text is binding (slice 1 L978-1045)
- CMP-006: comfortable density — not drawn, the text is binding (slice 1 L978-1045)
- CMP-010: Marks=true x every non-default State — not drawn, the text is binding (slice 1 L1046-1116)
- CMP-010: a vertical slider (not catalogued) — not drawn, the text is binding (slice 1 L1046-1116)
- CMP-010: comfortable density — not drawn, the text is binding (slice 1 L1046-1116)
- CMP-014: the motion (rotation; reduced-motion colour fade, D15) — not drawn, the text is binding (slice 1 L1117-1180)
- CMP-014: the surfaces row (app, canvas, raised, overlay, hover) — not drawn, the text is binding (slice 1 L1117-1180)
- CMP-014: comfortable md (32 px) — not drawn, the text is binding (slice 1 L1117-1180)
- CMP-019: the 47-glyph base set (CMP-019 · Icon — base set; the per-set file holds five icons) — not drawn, the text is binding (slice 1 L1181-1240)
- CMP-019: the A10 16 / 20 / 24 optical scale (proposed) — not drawn, the text is binding (slice 1 L1181-1240)
- CMP-031: a user-pickable palette (A5: no tokens) — not drawn, the text is binding (slice 1 L1241-1318)
- CMP-031: ThemeChip (C12) — not drawn, the text is binding (slice 1 L1241-1318)
- CMP-031: a StaticSwatch — not drawn, the text is binding (slice 1 L1241-1318)
- CMP-031: Selected=true x disabled (derivable) — not drawn, the text is binding (slice 1 L1241-1318)
- CMP-039: the D11 halo proposal (canvas gap + halo strokes) — not drawn, the text is binding (slice 1 L1319-1372)
- CMP-039: the A9 thick ring (no token) — not drawn, the text is binding (slice 1 L1319-1372)

## Strings used

- 'Label' — slice 1 (outside the CMP section)
- "Read-only: your role can't change this setting." — CMP-003 slice 1 L765-835
- 'option-1' — CMP-006 slice 1 L978-1045
- 'option-2' — CMP-006 slice 1 L978-1045
- 'option-3' — CMP-006 slice 1 L978-1045
- 'Risk-based' — CMP-006 slice 1 L978-1045
- '40' — CMP-010 slice 1 L1046-1116
- '100' — CMP-010 slice 1 L1046-1116
- 'Loading positions' — CMP-014 slice 1 L1117-1180
- 'Still loading positions…' — CMP-014 slice 1 L1117-1180
- 'Cancel' — CMP-014 slice 1 L1117-1180
- 'Checking with the exchange…' — CMP-014 slice 1 L1117-1180
- 'Buy / Long' — CMP-001 slice 1 L621-694
- 'Cyan' — CMP-031 slice 1 L1241-1318
- 'Amber' — CMP-031 slice 1 L1241-1318
- 'Save' — CMP-001 slice 1 L621-694

## Stamps

- PROPOSED · slice 1 C6 (slice 1 L399)
- PROPOSED · slice 1 A3 (slice 1 L275)
- PROPOSED · slice 1 D13 (slice 1 L481)
- PROPOSED · slice 1 D17 (slice 1 L533)
- PROPOSED · slice 1 C5 (slice 1 L395)
- PROPOSED · slice 1 C7 (slice 1 L403)
- PROPOSED · slice 1 D7 (slice 1 L468)
- PROPOSED · slice 1 B4 (slice 1 L358)
- PROPOSED · slice 1 C8 (slice 1 L406)
- PROPOSED · slice 1 D15 (slice 1 L508)
- PROPOSED · slice 1 C9 (slice 1 L409)
- PROPOSED · slice 1 A8 (slice 1 L311)
- PROPOSED · slice 1 A10 (slice 1 L318)
- PROPOSED · slice 1 B6 (slice 1 L363)
- PROPOSED · slice 1 C11 (slice 1 L415)
- PROPOSED · slice 1 A5 (slice 1 L289)
- PROPOSED · slice 1 B5 (slice 1 L360)
- PROPOSED · slice 1 C12 (slice 1 L418)
- PROPOSED · slice 1 D14 (slice 1 L504)
- PROPOSED · slice 1 A9 (slice 1 L314)
- PROPOSED · slice 1 B2 (slice 1 L345)
- PROPOSED · slice 1 D11 (slice 1 L476)
- RULED · #3925 (slice 1)

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

- CMP-005 / CMP-006: the spec gives no sample label; the boards draw the anatomy part names ('Label', 'option-1' … 'option-3') and 'Risk-based' (CMP-006 option-4 as built)

## Sources

- spec docs/design/E05/E05-D02.md at 966f9edcd md5 72dc9ede4f3ce6a4620ffd50816cb935 (frozen copy E05-D02@966f9edcd.md)
- Penpot file 'E05-D02 boards', page 'E05-D02 slice 1 actions and selection'; kit e05d02kit.py md5 1af7cacf448b9098924bf67629612f6b

## Shape count

- {"sheet": "02-selection-and-primitives.json", "shapes": 631, "texts": 223, "by_type": {"board": 335, "ellipse": 17, "icon": 20, "rect": 36, "text": 223}, "sections": 16, "bytes": 104991, "largest_section": 11611, "largest_compacted": 6608}
