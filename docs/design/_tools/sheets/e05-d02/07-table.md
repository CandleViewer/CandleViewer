# E05-D02 / 07 table

File `E05-D02 boards`, page `E05-D02 slice 3 form controls` (render with `--page`); export `docs/design/E05/img/E05-D02-07-table.png`; sheet `07-table.json` (validated); theme dark.

Validator: 07-table.json: 0 errors, 2 warnings, 13 sections, 67297 bytes

## Blocks

- `CMP-049 · Table` — slice 3 L1066-1183; spec export `img/CMP-049-table.png`

## Content checks

- ten named cells of CMP-049 drawn (populated, loading, empty, filtered-empty, error, sorting, reflow, Mode=grid, Selection=multiple, row menu with a T2 item) plus the inline 2b IconButton
- loading, empty and error explicitly drawn (the ticket's Gherkin)
- T2: lock leads the full label, color.text.tertiary; reason color.text.secondary; never disabled tokens
- every specimen string issued by say() (copy gaps logged)

## Live checks for the drawer

- render on page 'E05-D02 slice 3 form controls' (mkcall4.py … --page 'E05-D02 slice 3 form controls'; its default would be 'E05-D02')
- root 'E05-D02 / 07 table': hugs its content (about 2200 x 919 px estimated)

## Not drawn — the text is binding

- CMP-049: invalid (a table holds no input of its own) — not drawn, the text is binding (slice 3 L1066-1183)
- CMP-049: disabled and disabled-with-reason for the whole table (it is read data, and reads in a visible surface are never gated; row actions are T2 one by one) — not drawn, the text is binding (slice 3 L1066-1183)
- CMP-049: read-only (rows are read-only by nature) — not drawn, the text is binding (slice 3 L1066-1183)
- CMP-049: active (opening a row is the host's action) — not drawn, the text is binding (slice 3 L1066-1183)
- CMP-049: every combination beyond the ten named cells (e.g. loading / error in grid mode, a sorted ascending column, the selection with an actions column) — not drawn, the text is binding (slice 3 L1066-1183)
- CMP-049: comfortable density (size.row.height 32: only the row height changes, the Anatomy's compact / comfortable line) — not drawn, the text is binding (slice 3 L1066-1183)
- CMP-049: the live region ("2 selected", sort and load results): announced, never drawn — not drawn, the text is binding (slice 3 L1066-1183)
- CMP-049: the visually hidden caption of a table a heading already names; forced colours (CanvasText rules, Highlight) — not drawn, the text is binding (slice 3 L1066-1183)

## Strings used

- 'trader_01' — slice 3 (outside the CMP section)
- 'manager' — CMP-049 slice 3 L1066-1183
- '4.83' — CMP-049 slice 3 L1066-1183
- 'viewer' — CMP-049 slice 3 L1066-1183
- '4.79' — CMP-049 slice 3 L1066-1183
- 'alex' — CMP-049 slice 3 L1066-1183
- 'owner' — CMP-049 slice 3 L1066-1183
- '1.24' — CMP-049 slice 3 L1066-1183
- 'Name' — CMP-049 slice 3 L1066-1183
- 'Role' — CMP-049 slice 3 L1066-1183
- 'Value' — CMP-049 slice 3 L1066-1183
- 'Loading 5,000 bars…' — CMP-049 slice 3 L1066-1183
- "You're the only user. Invite a manager or viewer to delegate." — CMP-049 slice 3 L1066-1183
- 'No rows match: Bid-stacked, Delta negative' — CMP-049 slice 3 L1066-1183
- 'Clear filters' — CMP-049 slice 3 L1066-1183
- "Couldn't load users — store unavailable." — CMP-049 slice 3 L1066-1183
- 'Retry' — CMP-049 slice 3 L1066-1183
- 'Edit risk caps' — CMP-049 slice 3 L1066-1183
- 'Only the owner can change account settings.' — CMP-049 slice 3 L1066-1183

## Stamps

- PROPOSED · slice 3 G3 (slice 3 L339)
- PROPOSED · slice 3 G12 (slice 3 L393)
- PROPOSED · slice 3 G17 (slice 3 L436)
- PROPOSED · slice 3 G21 (slice 3 L458)

## Kit choices and deviations

- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS ICONS)
- kit choice (specimen): Each state is a cell: the specimen on a color.surface.app plate (the matrix cells of slice 1 §1.1), its state caption under it in type.ui.caption color.text.secondary; cells sit in state rows led by a 120 px row label; a block is a color.surface.canvas card with a 1 px color.border.subtle edge
- CMP-049 grid: the focused cell's CMP-039 ring is drawn on the cell's edge (rows abut, so a ring 2 px outside would be cut by the next row; slice 4 H8's inset ring is the same open question for scrolled containers)
- kit choice (t2): T2 (E09-D09 §2.2, slices 3-4 conventions 24 / 36-37; it supersedes slice 1 §3's trailing lock): the shape loses its enabled look (color.surface.raised fill, 1 px color.border.default hairline), the CMP-019 lock LEADS the full label, label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary (2a inline); icon-only controls carry a size.icon.sm lock badge bottom-right and a CMP-016 echo of the reason (2b); never color.text.disabled, never opacity.disabled on label, glyph or reason
- kit choice (page): mkcall4.py derives a page from the board name ('E05-D02 / NN …' -> 'E05-D02'); the sheet carries its page in sheet['page'] and the renderer passes --page '<page>' (live check)

## Tokens and fallbacks

- fallback: CMP-014's arc has no dashed / partial stroke in cvsheet: drawn as a full ring in color.border.default with a short arc rect in the indicator colour (a static frame of the spin)
- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'
- token: size.icon.sm (12) / size.icon.lg (20) are Tier-1 primitives (slice 1 §1, validator WARN)

## Copy gaps

- CMP-049 names no sample records: the rows draw the section's own words (alex, slice 3's trader_01, the roles owner / manager / viewer of E42-D03's users.empty line) and three numbers the section itself cites (4.83, 4.79, 1.24) as the mono end-aligned numeric column; the third record's name is the em dash (no value) — never an invented name
- CMP-049's row menu names one item ("Edit risk caps"); its other items are the host's (SCR-121) and are not drawn

## Sources

- spec docs/design/E05/E05-D02-form-controls.md at 966f9edcd md5 c768259c5a59fbf6161a52f0cb498b79 (frozen copy E05-D02-form-controls@966f9edcd.md)
- Penpot file 'E05-D02 boards', page 'E05-D02 slice 3 form controls'; kit e05d02kit.py md5 1af7cacf448b9098924bf67629612f6b

## Shape count

- {"sheet": "07-table.json", "shapes": 417, "texts": 166, "by_type": {"board": 219, "ellipse": 1, "icon": 10, "rect": 21, "text": 166}, "sections": 13, "bytes": 67297, "largest_section": 10952, "largest_compacted": 5800}
