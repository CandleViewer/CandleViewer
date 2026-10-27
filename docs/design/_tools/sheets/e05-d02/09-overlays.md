# E05-D02 / 09 overlays

File `E05-D02 boards`, page `E05-D02 slice 4 feedback and overlays` (render with `--page`); export `docs/design/E05/img/E05-D02-09-overlays.png`; sheet `09-overlays.json` (validated); theme dark.

Board 09: slice 4's overlays, six blocks, the spec's named cells.

## Blocks

- `CMP-016 · Tooltip` — slice 4 L1057-1122; spec export `img/CMP-016-tooltip.png`
- `CMP-017 · Popover` — slice 4 L1123-1183; spec export `img/CMP-017-popover.png`
- `CMP-041 · Menu` — slice 4 L1518-1607; spec export `img/CMP-041-menu.png`
- `CMP-043 · Dialog` — slice 4 L1608-1682; spec export `img/CMP-043-dialog-modal.png`
- `CMP-044 · ConfirmDialog` — slice 4 L1683-1778; spec export `img/CMP-044-confirmdialog.png`
- `CMP-046 · Drawer` — slice 4 L1861-1930; spec export `img/CMP-046-drawer-side-panel.png`

## Content checks

- every block draws the spec's named cells
- every specimen string k.say()'d from the frozen spec (slice 3 for nested fields)
- modal cells over the scrim stand-in; floating surfaces on conventions 30's tokens
- CMP-041 items are flex rows with explicit h; T2 item lock-led with its reason line
- CMP-044 gated Confirm in T2 2a; no inst node; only the local icons locked and close

## Live checks for the drawer

- the scrim (color.surface.sunken at opacity.scrim) reads as a 60 % black veil at 1x; rebind it to palette.black when the drawer allows a primitive colour
- clipped bodies (CMP-017 scrolls, CMP-043 scrolls / reflow) clip at their h
- render on page 'E05-D02 slice 4 feedback and overlays' (mkcall4.py … --page 'E05-D02 slice 4 feedback and overlays'; its default would be 'E05-D02')
- root 'E05-D02 / 09 overlays': hugs its content (about 5400 x 2749 px estimated)

## Not drawn — the text is binding

- CMP-016: closed (nothing renders); Side=left (derivable, slice 1 C13); every state of its own (the trigger's). — not drawn, the text is binding (slice 4 L1057-1122)
- CMP-016: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1057-1122)
- CMP-016: comfortable density — not drawn, the text is binding (slice 4 L1057-1122)
- CMP-017: closed (nothing renders); hover, active, disabled (the trigger's); loading, empty, error (its content's). — not drawn, the text is binding (slice 4 L1123-1183)
- CMP-017: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1123-1183)
- CMP-017: comfortable density — not drawn, the text is binding (slice 4 L1123-1183)
- CMP-041: closed (the trigger alone); loading, empty and error of the menu itself (its items are known: an item that waits is ItemState=busy; a command list is CMP-059). — not drawn, the text is binding (slice 4 L1518-1607)
- CMP-041: the checked cell's Scale mode radio group (E11-D03's values) — not drawn, the text is binding (slice 4 L1518-1607)
- CMP-041: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1518-1607)
- CMP-041: comfortable density — not drawn, the text is binding (slice 4 L1518-1607)
- CMP-043: closed; hover, active, disabled (not a control; never gated); error (CMP-027 inline in the body). — not drawn, the text is binding (slice 4 L1608-1682)
- CMP-043: the md default's own title and description (the host's; drawn with lg's content) — not drawn, the text is binding (slice 4 L1608-1682)
- CMP-043: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1608-1682)
- CMP-043: comfortable density — not drawn, the text is binding (slice 4 L1608-1682)
- CMP-044: a typed mismatch (the empty cell's look); hover and active (CMP-001's); a disabled dialog (never gated); timed-out as a cell of its own (the dialog has closed: the order cell's inset). — not drawn, the text is binding (slice 4 L1683-1778)
- CMP-044: the typed and hold cards' titles (E42-D02's, E39-D03's: drawn as crops) — not drawn, the text is binding (slice 4 L1683-1778)
- CMP-044: SCR-072's partial-failure line; SCR-076's restatement and rows (the hosts') — not drawn, the text is binding (slice 4 L1683-1778)
- CMP-044: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1683-1778)
- CMP-044: comfortable density — not drawn, the text is binding (slice 4 L1683-1778)
- CMP-046: closed; interactive states (a container); error (CMP-027 in the body, E40-D02 §4.6); empty (CMP-026). — not drawn, the text is binding (slice 4 L1861-1930)
- CMP-046: SCR-103's instrument-rules content (E08-D06's) — not drawn, the text is binding (slice 4 L1861-1930)
- CMP-046: every combination beyond the named cells — not drawn, the text is binding (slice 4 L1861-1930)
- CMP-046: comfortable density — not drawn, the text is binding (slice 4 L1861-1930)

## Strings used

- 'Retry now' — slice 4 (outside the CMP section)
- 'Details' — slice 4 (outside the CMP section)
- 'Last data 00:12 ago.' — slice 4 (outside the CMP section)
- 'Closes 4 positions at market — all accounts, LIVE + DEMO · hold 800 ms or press twice' — CMP-016 slice 4 L1057-1122
- 'Journal' — slice 4 (outside the CMP section)
- 'Only the owner can change account settings.' — CMP-016 slice 4 L1057-1122
- '10' — slice 3 (outside the CMP section)
- '11' — CMP-017 slice 4 L1123-1183
- '12' — slice 3 (outside the CMP section)
- '13' — slice 3 (outside the CMP section)
- '14' — CMP-017 slice 4 L1123-1183
- 'October 2026' — slice 3 (outside the CMP section)
- 'Auto-scale margin' — slice 3 (outside the CMP section)
- 'Save as default' — CMP-017 slice 4 L1123-1183
- 'Delete' — CMP-017 slice 4 L1123-1183
- 'Open chart' — slice 4 (outside the CMP section)
- 'Snooze' — CMP-041 slice 4 L1518-1607
- 'Disable' — CMP-041 slice 4 L1518-1607
- '15 m' — CMP-041 slice 4 L1518-1607
- '1 h' — CMP-041 slice 4 L1518-1607
- 'until tomorrow' — CMP-041 slice 4 L1518-1607
- 'Duplicate' — CMP-041 slice 4 L1518-1607
- 'Reveal on chart' — CMP-041 slice 4 L1518-1607
- 'Remove' — CMP-041 slice 4 L1518-1607
- 'Del' — CMP-041 slice 4 L1518-1607
- 'Move up' — CMP-041 slice 4 L1518-1607
- 'Move down' — CMP-041 slice 4 L1518-1607
- 'Lock' — CMP-041 slice 4 L1518-1607
- 'Invert' — CMP-041 slice 4 L1518-1607
- 'Merge' — CMP-041 slice 4 L1518-1607
- 'Scale price only' — CMP-041 slice 4 L1518-1607
- 'Edit risk caps' — CMP-041 slice 4 L1518-1607
- 'Only the owner can change account settings.' — CMP-041 slice 4 L1518-1607
- 'Flatten account…' — CMP-041 slice 4 L1518-1607
- 'Loading Sub-1 · LIVE…' — CMP-041 slice 4 L1518-1607
- 'Go to date' — CMP-043 slice 4 L1608-1682
- 'YYYY-MM-DD' — slice 3 (outside the CMP section)
- 'Cancel' — CMP-043 slice 4 L1608-1682
- 'Delete 497 drawings on BTCUSDT?' — CMP-043 slice 4 L1608-1682
- '3 locked drawings stay. One undo.' — CMP-043 slice 4 L1608-1682
- 'Delete 497' — CMP-043 slice 4 L1608-1682
- 'Username' — slice 3 (outside the CMP section)
- 'Display name (optional)' — slice 3 (outside the CMP section)
- 'Account' — slice 3 (outside the CMP section)
- 'Invite a user' — CMP-043 slice 4 L1608-1682
- 'alex' — slice 3 (outside the CMP section)
- 'Cancel' — CMP-044 slice 4 L1683-1778
- 'Delete' — slice 4 (outside the CMP section)
- 'alex' — CMP-044 slice 4 L1683-1778
- 'Press again to flatten 4 positions — all accounts, LIVE + DEMO' — CMP-044 slice 4 L1683-1778
- 'Retry' — CMP-044 slice 4 L1683-1778
- 'Confirm order - BTCUSDT - LIVE - Main' — CMP-044 slice 4 L1683-1778
- 'BUY 0.250 BTCUSDT limit 64,010.0 · stop 63,900.0' — CMP-044 slice 4 L1683-1778
- 'Cancels in 0:20' — CMP-044 slice 4 L1683-1778
- 'Confirmation timed out — nothing was sent. Attempt recorded' — CMP-044 slice 4 L1683-1778
- 'Freeze sub_001 — cancel 3 working orders' — CMP-044 slice 4 L1683-1778
- 'Freeze sub_001?' — CMP-044 slice 4 L1683-1778
- 'What this does' — CMP-044 slice 4 L1683-1778
- 'Open positions are NOT closed' — CMP-044 slice 4 L1683-1778
- "Your role can't use the kill switch." — CMP-044 slice 4 L1683-1778
- 'Closes 4 positions at market — all accounts, LIVE + DEMO' — slice 4 (outside the CMP section)
- '0 %' — CMP-044 slice 4 L1683-1778
- '50 %' — CMP-044 slice 4 L1683-1778
- 'BTC above 65k' — slice 4 (outside the CMP section)
- 'Last price 65,012.5 crossed above 65,000' — slice 4 (outside the CMP section)
- 'BTCUSDT · 5m' — slice 4 (outside the CMP section)

## Stamps

- PROPOSED · slice 4 H10 (slice 4 L607)
- PROPOSED · slice 4 H11 (slice 4 L625)
- PROPOSED · slice 4 H8 (slice 4 L596)
- PROPOSED · slice 4 H16 (slice 4 L665)
- PROPOSED · slice 4 H1 (slice 4 L520)
- PROPOSED · slice 4 H17 (slice 4 L674)
- PROPOSED · slice 4 H22 (slice 4 L734)
- PROPOSED · slice 4 H33 (slice 4 L863)
- PROPOSED · slice 4 H24 (slice 4 L756)
- PROPOSED · slice 4 H25 (slice 4 L779)
- PROPOSED · slice 4 H30 (slice 4 L830)
- PROPOSED · slice 4 H32 (slice 4 L848)
- PROPOSED · slice 4 H31 (slice 4 L835)

## Kit choices and deviations

- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS ICONS)
- kit choice (t2): T2 (E09-D09 §2.2, slices 3-4 conventions 24 / 36-37; it supersedes slice 1 §3's trailing lock): the shape loses its enabled look (color.surface.raised fill, 1 px color.border.default hairline), the CMP-019 lock LEADS the full label, label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary (2a inline); icon-only controls carry a size.icon.sm lock badge bottom-right and a CMP-016 echo of the reason (2b); never color.text.disabled, never opacity.disabled on label, glyph or reason
- kit choice (specimen): Each state is a cell: the specimen on a color.surface.app plate (the matrix cells of slice 1 §1.1), its state caption under it in type.ui.caption color.text.secondary; cells sit in state rows led by a 120 px row label; a block is a color.surface.canvas card with a 1 px color.border.subtle edge
- kit choice (focus): A focus ring is CMP-039's 2 px color.focus.ring (border.focus) rect, positioned 2 px outside the control on a flex wrapper 4 px larger than it (radius.md = radius.control + 2, FALLBACKS RING)
- kit choice (page): mkcall4.py derives a page from the board name ('E05-D02 / NN …' -> 'E05-D02'); the sheet carries its page in sheet['page'] and the renderer passes --page '<page>' (live check)

## Tokens and fallbacks

- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'
- token: size.icon.sm (12) / size.icon.lg (20) are Tier-1 primitives (slice 1 §1, validator WARN)
- token: the CMP-039 ring's radius (radius.control + 2 = 6 px, slice 1 §5.1, no token) binds the Tier-1 primitive radius.md (6 px; validator WARN)
- token: opacity.disabled / opacity.scrim are Tier-1 primitives (slice 1 §1 names them; validator WARN)
- fallback: CMP-014's arc has no dashed / partial stroke in cvsheet: drawn as a full ring in color.border.default with a short arc rect in the indicator colour (a static frame of the spin)
- fallback: the scrim is palette.black at opacity.scrim (conventions 31, §6 H1 PROPOSED color.surface.scrim); the validator refuses a primitive colour, so it is drawn color.surface.sunken (#000000 in dark, the boards' theme) at opacity.scrim; live check: rebind the fill to palette.black
- token: the hold ring's 3 px stroke has no token; border.thick (2 px) stands in; its arc is a static frame (a short rect), the percentage text carries the progress

## Copy gaps

- CMP-016: slice 4 gives no short tooltip string; CMP-028's 'Last data 00:12 ago.' describes its 'Retry now' in the default, focus, right and bottom cells; the long cell's trigger is the host's (a CMP-002 stand-in)
- CMP-017: SCR-037's property field label and the calendar's days are the hosts'; slice 3's 'Auto-scale margin', 'October 2026' and day numbers stand in
- CMP-041 checked: the 'Scale mode' radio values are E11-D03's (not in slice 4): the radio group is not drawn, the four checkboxes are; the button trigger's label is the host's ('Details' stands in)
- CMP-043 default / lg / scrolls / busy: slice 4 names E42-D03's 'Invite a user' (lg) only; its fields are slice 3's 'Username' and 'Display name (optional)' and its primary is drawn with the title's words; the default md cell's own title and description are the host's (not drawn: the md card reuses lg's content)
- CMP-044 typed / hold cells are drawn as crops (body and footer): the titles of E42-D02's rung 3 and E39-D03's hold confirm are the hosts'; the typed confirm's label is drawn 'Delete' (slice 4) — its full-effect label is E42-D02's; the hold confirm names its effect with E39-D03 S20's 'Closes 4 positions at market — all accounts, LIVE + DEMO'
- CMP-044 partial failure: SCR-072's failure line is the host's: the inline CMP-027 is drawn as its glyph and Retry; order: the restatement and the host's rows are E30-D03's (not drawn)
- CMP-046: SCR-103's instrument-rules content is E08-D06's; every drawer cell draws E40-D02's alert detail content ('BTC above 65k', its body and meta, 'Open chart') from slice 4's CMP-045 cell

## Sources

- spec docs/design/E05/E05-D02-feedback-overlays.md at 966f9edcd md5 fb6e8b12d79fc6c057f0b695d495867d (frozen copy E05-D02-feedback-overlays@966f9edcd.md)
- Penpot file 'E05-D02 boards', page 'E05-D02 slice 4 feedback and overlays'; kit e05d02kit.py md5 1af7cacf448b9098924bf67629612f6b

## Shape count

- {"sheet": "09-overlays.json", "shapes": 1003, "texts": 330, "by_type": {"board": 548, "ellipse": 6, "icon": 16, "rect": 103, "text": 330}, "sections": 25, "bytes": 177382, "largest_section": 11940, "largest_compacted": 8003}
