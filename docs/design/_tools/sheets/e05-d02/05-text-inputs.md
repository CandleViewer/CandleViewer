# E05-D02 / 05 text-inputs

File `E05-D02 boards`, page `E05-D02 slice 3 form controls` (render with `--page`); export `docs/design/E05/img/E05-D02-05-text-inputs.png`; sheet `05-text-inputs.json` (validated); theme dark.

## Blocks

- `CMP-007 · TextInput` — slice 3 L522-603; spec export `img/CMP-007-textinput.png`
- `CMP-008 · NumericStepperInput` — slice 3 L604-670; spec export `img/CMP-008-numericstepperinput.png`
- `CMP-034 · MaskedValue` — slice 3 L748-841; spec export `img/CMP-034-maskedvalue.png`
- `CMP-040 · FormField` — slice 3 L842-912; spec export `img/CMP-040-formfield.png`
- `CMP-054 · SearchBox` — slice 3 L1184-1232; spec export `img/CMP-054-searchbox.png`
- `CMP-065 · FormSection` — slice 3 L1233-1286; spec export `img/CMP-065-formsection.png`

## Content checks

- every cell the six Variants x States paragraphs / tables name is drawn once (CMP-007 9, CMP-008 9, CMP-034 4, CMP-040 8, CMP-054 5, CMP-065 6)
- T2 cells: lock first in the well, value color.text.tertiary, label color.text.secondary, reason type.ui.caption color.text.secondary; no color.text.disabled / opacity.disabled on a T2 path (write_sheet)
- invalid: 2 px color.status.danger.default boundary + danger glyph + words (CMP-040's line)
- no inst node; only the local locked icon (close ✕ is a text glyph)

## Live checks for the drawer

- the 1 px color.text.tertiary well boundary reads on the color.surface.app plate
- CMP-008 at-max: only [+] is dimmed
- render on page 'E05-D02 slice 3 form controls' (mkcall4.py … --page 'E05-D02 slice 3 form controls'; its default would be 'E05-D02')
- root 'E05-D02 / 05 text-inputs': hugs its content (about 3576 x 1505 px estimated)

## Not drawn — the text is binding

- CMP-007: active — a press focuses the field, which is the focus look; loading — no catalogued async state (a submitting form is the host's busy state, conventions 25); error — the invalid state; empty — the Value axis. — not drawn, the text is binding (slice 3 L522-603)
- CMP-007: every combination beyond the named cells — not drawn, the text is binding (slice 3 L522-603)
- CMP-007: comfortable density (only the height changes: 32) — not drawn, the text is binding (slice 3 L522-603)
- CMP-008: active (the step buttons' pressed look is CMP-002's), loading (none catalogued), error (the invalid state), empty (an empty number field is invalid on blur when the host requires a value; otherwise it shows its placeholder as CMP-007 does). — not drawn, the text is binding (slice 3 L604-670)
- CMP-008: every combination beyond the named cells — not drawn, the text is binding (slice 3 L604-670)
- CMP-008: comfortable density (only the height changes: 32) — not drawn, the text is binding (slice 3 L604-670)
- CMP-034: every combination beyond the named cells — not drawn, the text is binding (slice 3 L748-841)
- CMP-034: comfortable density (only the height changes: 32) — not drawn, the text is binding (slice 3 L748-841)
- CMP-040: hover, focus-visible and active belong to the child; loading (a field has none; the form's busy state is its host's); empty (the child's placeholder). — not drawn, the text is binding (slice 3 L842-912)
- CMP-040: every combination beyond the named cells — not drawn, the text is binding (slice 3 L842-912)
- CMP-040: comfortable density (only the height changes: 32) — not drawn, the text is binding (slice 3 L842-912)
- CMP-054: active, invalid (every query is valid; no matches is the host's availability state), disabled-with-reason (searching is a read, and a visible surface's search is never gated: D09 §2.1), read-only, loading and empty (the host's results own them). — not drawn, the text is binding (slice 3 L1184-1232)
- CMP-054: every combination beyond the named cells — not drawn, the text is binding (slice 3 L1184-1232)
- CMP-054: comfortable density (only the height changes: 32) — not drawn, the text is binding (slice 3 L1184-1232)
- CMP-065: hover, focus-visible and active belong to the disclosure button (the CMP-039 ring on focus) and the fields; loading, error and empty are the host's. — not drawn, the text is binding (slice 3 L1233-1286)
- CMP-065: every combination beyond the named cells — not drawn, the text is binding (slice 3 L1233-1286)
- CMP-065: comfortable density (only the height changes: 32) — not drawn, the text is binding (slice 3 L1233-1286)

## Strings used

- 'trader_01' — CMP-007 slice 3 L522-603
- 'USDT' — CMP-007 slice 3 L522-603
- 'Hides in 8 s' — CMP-034 slice 3 L748-841
- 'Hides in 2 s' — CMP-034 slice 3 L748-841
- 'Username' — CMP-040 slice 3 L842-912
- 'Enter your username.' — CMP-040 slice 3 L842-912
- "Your role can't change settings." — CMP-040 slice 3 L842-912
- '(rounded to nearest tick)' — CMP-040 slice 3 L842-912
- 'Display name' — CMP-040 slice 3 L842-912
- '(optional)' — CMP-040 slice 3 L842-912
- 'alex' — CMP-054 slice 3 L1184-1232
- 'Default SL/TP offsets' — CMP-065 slice 3 L1233-1286
- "Your role can't change settings." — CMP-065 slice 3 L1233-1286
- '2 problems' — CMP-065 slice 3 L1233-1286

## Stamps

- PROPOSED · slice 3 G1 (slice 3 L321)
- PROPOSED · slice 3 G2 (slice 3 L328)
- PROPOSED · slice 3 G4 (slice 3 L349)
- PROPOSED · slice 3 G23 (slice 3 L418)
- PROPOSED · slice 3 G8 (slice 3 L366)
- PROPOSED · slice 3 G18 (slice 3 L443)
- PROPOSED · slice 3 G22 (slice 3 L464)
- PROPOSED · slice 3 G19 (slice 3 L448)
- PROPOSED · slice 3 G20 (slice 3 L454)
- PROPOSED · slice 3 G6 (slice 3 L360)
- PROPOSED · slice 3 G10 (slice 3 L380)
- PROPOSED · slice 3 G16 (slice 3 L415)
- PROPOSED · slice 3 G17 (slice 3 L436)
- PROPOSED · slice 3 G13 (slice 3 L403)
- PROPOSED · slice 3 G14 (slice 3 L405)

## Kit choices and deviations

- kit choice (specimen): Each state is a cell: the specimen on a color.surface.app plate (the matrix cells of slice 1 §1.1), its state caption under it in type.ui.caption color.text.secondary; cells sit in state rows led by a 120 px row label; a block is a color.surface.canvas card with a 1 px color.border.subtle edge
- kit choice (focus): A focus ring is CMP-039's 2 px color.focus.ring (border.focus) rect, positioned 2 px outside the control on a flex wrapper 4 px larger than it (radius.md = radius.control + 2, FALLBACKS RING)
- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS ICONS)
- kit choice (t2): T2 (E09-D09 §2.2, slices 3-4 conventions 24 / 36-37; it supersedes slice 1 §3's trailing lock): the shape loses its enabled look (color.surface.raised fill, 1 px color.border.default hairline), the CMP-019 lock LEADS the full label, label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary (2a inline); icon-only controls carry a size.icon.sm lock badge bottom-right and a CMP-016 echo of the reason (2b); never color.text.disabled, never opacity.disabled on label, glyph or reason
- kit choice (page): mkcall4.py derives a page from the board name ('E05-D02 / NN …' -> 'E05-D02'); the sheet carries its page in sheet['page'] and the renderer passes --page '<page>' (live check)

## Tokens and fallbacks

- token: the CMP-039 ring's radius (radius.control + 2 = 6 px, slice 1 §5.1, no token) binds the Tier-1 primitive radius.md (6 px; validator WARN)
- token: opacity.disabled / opacity.scrim are Tier-1 primitives (slice 1 §1 names them; validator WARN)
- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'

## Copy gaps

- placeholder (CMP-007): the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)
- revealed value (CMP-034: no sample value; S4, S6): the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)
- placeholder (CMP-054, the host's): the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)
- description (CMP-065): the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)
- field label: the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)

## Sources

- spec docs/design/E05/E05-D02-form-controls.md at 966f9edcd md5 c768259c5a59fbf6161a52f0cb498b79 (frozen copy E05-D02-form-controls@966f9edcd.md)
- Penpot file 'E05-D02 boards', page 'E05-D02 slice 3 form controls'; kit e05d02kit.py md5 1af7cacf448b9098924bf67629612f6b

## Shape count

- {"sheet": "05-text-inputs.json", "shapes": 532, "texts": 240, "by_type": {"board": 263, "icon": 5, "rect": 24, "text": 240}, "sections": 14, "bytes": 97246, "largest_section": 11792, "largest_compacted": 7273}
