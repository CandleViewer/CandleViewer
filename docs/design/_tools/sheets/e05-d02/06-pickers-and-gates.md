# E05-D02 / 06 pickers-and-gates

File `E05-D02 boards`, page `E05-D02 slice 3 form controls` (render with `--page`); export `docs/design/E05/img/E05-D02-06-pickers-and-gates.png`; sheet `06-pickers-and-gates.json` (validated); theme dark.

## Blocks

- `CMP-009 · Select` — slice 3 L671-747; spec export `img/CMP-009-select.png`
- `CMP-047 · DatePicker` — slice 3 L913-1003; spec export `img/CMP-047-datepicker.png`
- `CMP-048 · Combobox` — slice 3 L1004-1065; spec export `img/CMP-048-combobox.png`
- `CMP-079 · RbacGate` — slice 3 L1287-1332; spec export `img/CMP-079-rbacgate.png`

## Content checks

- every named cell drawn once: CMP-009 9 (+ the CMP-231 validity sample), CMP-047 11, CMP-048 10, CMP-079 4
- T2: lock first in the well / option, value or label color.text.tertiary, reason type.ui.caption color.text.secondary; no color.text.disabled / opacity.disabled on a T2 path (write_sheet)
- status rows never colour alone: danger glyph + words; loading = spinner + words
- no inst node; only the local locked icon

## Live checks for the drawer

- the popups' elevation.popover shadow and 1 px edge read on the color.surface.app plate
- CMP-047's today ring (1 px color.text.tertiary) and the focused day's ring both read at 1x
- render on page 'E05-D02 slice 3 form controls' (mkcall4.py … --page 'E05-D02 slice 3 form controls'; its default would be 'E05-D02')
- root 'E05-D02 / 06 pickers-and-gates': hugs its content (about 3396 x 1270 px estimated)

## Not drawn — the text is binding

- CMP-009: active (opening is the open cell), read-only (a value nobody may change is plain text, CMP-020), loading (a Select's list is closed and local; an async list is CMP-048), empty (a Select always has options). — not drawn, the text is binding (slice 3 L671-747)
- CMP-009: every combination beyond the named cells — not drawn, the text is binding (slice 3 L671-747)
- CMP-009: comfortable density (only the height changes: 32) — not drawn, the text is binding (slice 3 L671-747)
- CMP-047: active (a press focuses or opens), loading (dates are computed, not fetched; recorded coverage is the host's caption), empty (the field's placeholder, "YYYY-MM-DD"). — not drawn, the text is binding (slice 3 L913-1003)
- CMP-047: every combination beyond the named cells — not drawn, the text is binding (slice 3 L913-1003)
- CMP-047: comfortable density (only the height changes: 32) — not drawn, the text is binding (slice 3 L913-1003)
- CMP-047: Mode=range, open: weeks 3-5 of October (the band and the ends are in weeks 1-2) — not drawn, the text is binding (slice 3 L913-1003)
- CMP-048: active (typing is the interaction), read-only (a value nobody may change is plain text), empty (the no-results cell). — not drawn, the text is binding (slice 3 L1004-1065)
- CMP-048: every combination beyond the named cells — not drawn, the text is binding (slice 3 L1004-1065)
- CMP-048: comfortable density (only the height changes: 32) — not drawn, the text is binding (slice 3 L1004-1065)
- CMP-079: every other state belongs to the wrapped control. — not drawn, the text is binding (slice 3 L1287-1332)
- CMP-079: every combination beyond the named cells — not drawn, the text is binding (slice 3 L1287-1332)
- CMP-079: comfortable density (only the height changes: 32) — not drawn, the text is binding (slice 3 L1287-1332)
- CMP-079: the sentence form (CMP-026 with cta omitted, D09 §8): not this component — not drawn, the text is binding (slice 3 L1287-1332)

## Strings used

- 'sub_001' — CMP-009 slice 3 L671-747
- 'You can view this account, not trade it.' — CMP-009 slice 3 L671-747
- 'sub_002' — CMP-009 slice 3 L671-747
- 'IOC' — CMP-009 slice 3 L671-747
- 'FOK' — CMP-009 slice 3 L671-747
- 'Market orders are always IOC on Bybit' — CMP-009 slice 3 L671-747
- 'Choose…' — CMP-009 slice 3 L671-747
- '2026-10-23' — CMP-047 slice 3 L913-1003
- 'UTC' — CMP-047 slice 3 L913-1003
- 'Nothing is recorded for that window.' — CMP-047 slice 3 L913-1003
- "Your role can't control replay." — CMP-047 slice 3 L913-1003
- '10' — CMP-047 slice 3 L913-1003
- '11' — CMP-047 slice 3 L913-1003
- '12' — slice 3 (outside the CMP section)
- '13' — slice 3 (outside the CMP section)
- '14' — CMP-047 slice 3 L913-1003
- '15' — CMP-047 slice 3 L913-1003
- '16' — slice 3 (outside the CMP section)
- '17' — slice 3 (outside the CMP section)
- '18' — slice 3 (outside the CMP section)
- '19' — slice 3 (outside the CMP section)
- '20' — CMP-047 slice 3 L913-1003
- '21' — CMP-047 slice 3 L913-1003
- '22' — slice 3 (outside the CMP section)
- '23' — CMP-047 slice 3 L913-1003
- '24' — CMP-047 slice 3 L913-1003
- '25' — slice 3 (outside the CMP section)
- '26' — CMP-047 slice 3 L913-1003
- '27' — slice 3 (outside the CMP section)
- '28' — CMP-047 slice 3 L913-1003
- '29' — CMP-047 slice 3 L913-1003
- '30' — slice 3 (outside the CMP section)
- '31' — slice 3 (outside the CMP section)
- 'October 2026' — CMP-047 slice 3 L913-1003
- 'Recorded history: 2026-09-01 – today' — CMP-047 slice 3 L913-1003
- '2026-10-01' — CMP-047 slice 3 L913-1003
- 'Start' — CMP-047 slice 3 L913-1003
- '2026-10-07' — CMP-047 slice 3 L913-1003
- 'End' — CMP-047 slice 3 L913-1003
- 'YYYY-MM-DD' — CMP-047 slice 3 L913-1003
- '14:05' — CMP-047 slice 3 L913-1003
- 'BTC' — CMP-048 slice 3 L1004-1065
- 'Read-only while viewing as alex.' — CMP-048 slice 3 L1004-1065
- 'USDT' — CMP-048 slice 3 L1004-1065
- 'Searching…' — CMP-048 slice 3 L1004-1065
- 'xyz' — CMP-048 slice 3 L1004-1065
- "No USDT perpetual matches 'xyz'." — CMP-048 slice 3 L1004-1065
- 'catalogue load failed' — CMP-048 slice 3 L1004-1065
- 'Only the owner can change account settings.' — CMP-079 slice 3 L1287-1332
- 'Default SL/TP offsets' — CMP-065 slice 3 L1233-1286
- "Your role can't change settings." — CMP-065 slice 3 L1233-1286
- 'trader_01' — CMP-007 slice 3 L522-603
- 'Username' — CMP-040 slice 3 L842-912
- 'Read-only while viewing as alex.' — CMP-079 slice 3 L1287-1332

## Stamps

- PROPOSED · slice 3 G3 (slice 3 L339)
- PROPOSED · slice 3 G7 (slice 3 L364)
- PROPOSED · slice 3 G9 (slice 3 L373)
- PROPOSED · slice 3 G23 (slice 3 L418)
- PROPOSED · slice 3 G5 (slice 3 L355)
- PROPOSED · slice 3 G11 (slice 3 L386)
- PROPOSED · slice 3 G17 (slice 3 L436)
- PROPOSED · slice 3 G15 (slice 3 L410)

## Kit choices and deviations

- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS ICONS)
- kit choice (specimen): Each state is a cell: the specimen on a color.surface.app plate (the matrix cells of slice 1 §1.1), its state caption under it in type.ui.caption color.text.secondary; cells sit in state rows led by a 120 px row label; a block is a color.surface.canvas card with a 1 px color.border.subtle edge
- kit choice (focus): A focus ring is CMP-039's 2 px color.focus.ring (border.focus) rect, positioned 2 px outside the control on a flex wrapper 4 px larger than it (radius.md = radius.control + 2, FALLBACKS RING)
- kit choice (t2): T2 (E09-D09 §2.2, slices 3-4 conventions 24 / 36-37; it supersedes slice 1 §3's trailing lock): the shape loses its enabled look (color.surface.raised fill, 1 px color.border.default hairline), the CMP-019 lock LEADS the full label, label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary (2a inline); icon-only controls carry a size.icon.sm lock badge bottom-right and a CMP-016 echo of the reason (2b); never color.text.disabled, never opacity.disabled on label, glyph or reason
- kit choice (page): mkcall4.py derives a page from the board name ('E05-D02 / NN …' -> 'E05-D02'); the sheet carries its page in sheet['page'] and the renderer passes --page '<page>' (live check)

## Tokens and fallbacks

- token: the CMP-039 ring's radius (radius.control + 2 = 6 px, slice 1 §5.1, no token) binds the Tier-1 primitive radius.md (6 px; validator WARN)
- token: opacity.disabled / opacity.scrim are Tier-1 primitives (slice 1 §1 names them; validator WARN)
- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'
- fallback: CMP-014's arc has no dashed / partial stroke in cvsheet: drawn as a full ring in color.border.default with a short arc rect in the indicator colour (a static frame of the spin)
- token: size.icon.sm (12) / size.icon.lg (20) are Tier-1 primitives (slice 1 §1, validator WARN)

## Copy gaps

- option label (rest): the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)
- option label (active): the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)
- option label (plain disabled): the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)
- weekday abbreviation (CMP-047): the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)
- result remainder (CMP-048): the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)

## Sources

- spec docs/design/E05/E05-D02-form-controls.md at 966f9edcd md5 c768259c5a59fbf6161a52f0cb498b79 (frozen copy E05-D02-form-controls@966f9edcd.md)
- Penpot file 'E05-D02 boards', page 'E05-D02 slice 3 form controls'; kit e05d02kit.py md5 1af7cacf448b9098924bf67629612f6b

## Shape count

- {"sheet": "06-pickers-and-gates.json", "shapes": 685, "texts": 243, "by_type": {"board": 371, "ellipse": 1, "icon": 8, "rect": 62, "text": 243}, "sections": 18, "bytes": 116702, "largest_section": 11881, "largest_compacted": 6962}
