# E27-D03 / 02 cmp-175-key-states-light

File `E27-D03 boards`, page `E27-D03 Accounts and key vault hi-fi` (render with `--page`); export `docs/design/E27/img/E27-D03-02-cmp-175-key-states-light.png`; sheet `02-cmp-175-key-states-light.json` (validated); theme light.

## Frames

- `Pattern / withdrawal verdict: dated, overdue, failed, unavailable, no keys` — hi-fi row E27-D03 L941; E27-D02 §7 E27-D02 L923 · PROPOSED HD1, HD2
- specimen `CMP-175 key scope · the thirteen variants (badge, inline; comfortable, compact)`
- specimen `CMP-011 row chips · CMP-176's state slot`
- specimen `CMP-034 MaskedValue · masked is its only state`

## Content checks

- frame 2 draws the eight aggregate forms of §2.1 L386-393 from the deck (e27.scr125.verdict.*)
- the three negated forms sit under CMP-092's blocking row (key_stale, key_failed, key_unchecked)
- loading is a static skeleton with its words, never OFF
- the thirteen CMP-175 variants with their deck words; one glyph per class; the critical alone bold + 2 px
- the nine CMP-011 words of CMP-176's slot with their tones and glyphs
- CMP-034 is text only (type.num.base), fixture key ids

## Live checks for the drawer

- export -greyscale, -deuteranopia and -protanopia renders through docs/design/_tools/cvd_sim.py (BQ-16)
- render on page 'E27-D03 Accounts and key vault hi-fi' (mkcall4.py … --page 'E27-D03 Accounts and key vault hi-fi'; its default would be 'E27-D03')
- root 'E27-D03 / 02 cmp-175-key-states-light': hugs its content (about 1728 x 1998 px estimated, 1 cells per row)

## Not yet served (annotation layer)

- not yet served — G-12, #3657 · "Off by policy" (BQ-7), a target state (E27-D03 L181)

## PROPOSED stamps

- PROPOSED · HD1 (E27-D03 L275)
- PROPOSED · HD2 (E27-D03 L276)
- PROPOSED · BQ-5 (E27-D03 L179)
- PROPOSED · BQ-6 (E27-D03 L180)
- PROPOSED · D03-C3 (E27-D03 L2659)
- PROPOSED · HD3 (E27-D03 L277)
- PROPOSED · HD4 (E27-D03 L278)
- PROPOSED · HD5 (E27-D03 L279)
- PROPOSED · BQ-8 (E27-D03 L182)

## Not drawn — the text is binding

## Strings used

- 'dated' — E27-D03 (quoted)
- e27.scr125.verdict.dated[0] — E27-D03 L2064 (refined)
- 'overdue' — E27-D03 (quoted)
- e27.shell.banner.key_stale[0] — E27-D03 L2055 (consumed)
- e27.scr125.verdict.overdue[0] — E27-D03 L2065 (refined)
- 'failed' — E27-D03 (quoted)
- e27.shell.banner.key_failed[0] — E27-D03 L2054 (consumed)
- e27.scr125.verdict.failed[0] — E27-D03 L2066 (refined)
- 'unavailable' — E27-D03 (quoted)
- e27.shell.banner.key_unchecked[0] — E27-D03 L2056 (consumed)
- e27.scr125.verdict.unavailable[0] — E27-D03 L2067 (consumed)
- 'read failed' — E27-D03 (quoted)
- e27.scr125.verdict.read_failed[0] — E27-D03 L2068 (consumed)
- 'no keys' — E27-D03 (quoted)
- e27.scr125.verdict.no_keys[0] — E27-D03 L2069 (consumed)
- 'loading' — E27-D03 (quoted)
- e27.scr125.verdict.loading[0] — E27-D03 L2070 (consumed)
- 'cleared' — E27-D03 (quoted)
- e27.cmp175.verified[0] — E27-D03 L2451 (new)
- e27.cmp175.trade_only[0] — E27-D03 L2452 (consumed)
- e27.cmp175.read_only.stored[0] — E27-D03 L2453 (new)
- e27.cmp175.withdrawal_detected[0] — E27-D03 L2454 (consumed)
- e27.cmp175.ip_missing[0] — E27-D03 L2455 (new)
- e27.cmp175.ip_mismatch[0] — E27-D03 L2456 (consumed)
- e27.cmp175.expiring[0] — E27-D03 L2457 (consumed)
- e27.cmp175.expired[0] — E27-D03 L2458 (new)
- e27.cmp175.not_checked[0] — E27-D03 L2459 (new)
- e27.cmp175.check_overdue[0] — E27-D03 L2460 (new)
- e27.cmp175.allowlist_matches[0] — E27-D03 L2461 (refined)
- e27.cmp175.allowlist_not_checked[0] — E27-D03 L2462 (new)
- 'comfortable' — E27-D03 (quoted)
- 'compact' — E27-D03 (quoted)
- 'inline' — E27-D03 (quoted)
- 'matches' — E27-D03 (quoted)
- 'no match' — E27-D03 (quoted)
- 'none set' — E27-D03 (quoted)
- 'not checked' — E27-D03 (quoted)
- 'IP allowlist' — E27-D03 (quoted)

## Kit choices and deviations

- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS GLYPHS)
- kit choice (doc): The Pattern frames (§2.6) are 1280 px documentation surfaces on color.surface.canvas, height hugging
- kit choice (cell): Each frame is a CELL: a caption row (the frame's exact §0 name in type.ui.heading-sm, then its PROPOSED stamp), the frame nested under its E27-D02 name, then its annotation-layer row (the 'not yet served' strips and notes; never inside the frame, never product UI)
- kit choice (strip): A 'not yet served — {gap}, {owner}' strip is board annotation (§0 L199-200): a warning-stroked pill on the cell's annotation layer, never inside the frame
- kit choice (light): Boards 02 and 05 are the light twins of 01 and 04: the same frames drawn again with the same token names; semantic-light is applied through the file's light theme at export (§0 L227-228; HD13)
- kit choice (page): mkcall4.py derives a page from the board name ('E27-D03 / NN …' -> 'E27-D03'); the sheet carries its page in sheet['page'] and the renderer passes --page 'E27-D03 Accounts and key vault hi-fi'

## Tokens and fallbacks

- fallback: the per-set file holds only the local icons locked, arrow-up, arrow-down, close and drag-handle; CMP-175's class glyphs are drawn so each class keeps its own SHAPE (BQ-6: the shape is the carrier): check = text glyph ✓, triangle = text glyph ⚠, octagon = a 16 px square with clipped look (radius.control) filled in the class token holding a '!' (cvsheet has no polygon), clock = a stroked ring with two hands, dash = a 10 x 2 bar, info = a stroked ring holding 'i', slashed circle = text glyph ⊘; plus, chevron, more and copy are text glyphs (+ ▾ ⋮ ⧉)
- fallback: CMP-015's skeleton is a static bar in color.surface.hover (reduced-motion form, §2.5)
- token: control heights bind the Tier-1 size.control.compact (24) / size.control.comfortable (32) (BQ-4, HD12: the admin screens comfortable, SCR-079 compact; the semantic size.control.height resolves through the active density set, so the boards bind the mode's own primitive; validator WARN)
- fallback: no typography token carries font.weight.bold at caption / body size; the critical word (BQ-6) binds type.ui.label (medium) and keeps its other carriers — 'BLOCKED' first, the octagon and the 2 px border.thick color.status.danger.strong border; the LIVE pill's bold word likewise (§3.1 block I)

## Copy gaps

## Sources

- spec docs/design/E27/E27-D03.md at 1983363fa md5 f386f58eeeb8aaadc18696c0ceba3e81 (frozen copy E27-D03@1983363fa.md)
- spec docs/design/E27/E27-D03-handoff.md at 1983363fa md5 4036e46f59e34d55af53cfa4480bdc15 (frozen copy E27-D03-handoff@1983363fa.md)
- spec docs/design/E27/E27-D02.md at 1983363fa md5 ec56733e286dd5cf2f7d0282d24ba9b2 (frozen copy E27-D02@1983363fa.md)
- Penpot file 'E27-D03 boards', page 'E27-D03 Accounts and key vault hi-fi'; kit e27d03kit.py md5 241e3b7d5bda4f99f4e0d1a3023aa720; renderer cvsheet-v4.3.js
- CMP-175 aggregate dated: E27-D03 L386
- CMP-175 aggregate overdue: E27-D03 L387
- CMP-175 aggregate failed: E27-D03 L388
- CMP-175 aggregate unavailable: E27-D03 L389
- CMP-175 aggregate read failed: E27-D03 L390
- CMP-175 aggregate no keys: E27-D03 L391
- CMP-175 aggregate loading: E27-D03 L392
- CMP-175 aggregate cleared: E27-D03 L393
- Pattern / withdrawal verdict: dated, overdue, failed, unavailable, no keys: hi-fi row E27-D03 L941 (2.6 The cross-screen pattern frames); E27-D02 §7 E27-D02 L923
- CMP-175 verified: E27-D03 L308
- CMP-175 trade-only: E27-D03 L309
- CMP-175 read-only (stored; BQ-5 rider, OWNER-LEVEL): E27-D03 L311
- CMP-175 withdrawal-detected (critical): E27-D03 L312
- CMP-175 IP-missing: E27-D03 L313
- CMP-175 IP-mismatch: E27-D03 L314
- CMP-175 expiring: E27-D03 L315
- CMP-175 expired: E27-D03 L316
- CMP-175 not checked: E27-D03 L317
- CMP-175 check overdue: E27-D03 L318
- CMP-175 allowlist matches: E27-D03 L319
- CMP-175 allowlist not checked: E27-D03 L320
- CMP-175 read-only (import): E27-D03 L310
- CMP-176 state slot 'Key refused by Bybit': E27-D03 L512
- CMP-176 state slot 'Down — order entry off for this account': E27-D03 L515
- CMP-176 state slot 'Off by policy': E27-D03 L516
- CMP-176 state slot 'Rotation overdue': E27-D03 L519
- CMP-176 state slot 'Degraded — REST only': E27-D03 L520
- CMP-176 state slot 'Rotation due in {n} d': E27-D03 L521
- CMP-176 state slot 'No key — inactive': E27-D03 L523
- CMP-176 state slot 'Disabled': E27-D03 L524
- CMP-176 state slot 'OK': E27-D03 L525

## Shape count

- {"sheet": "02-cmp-175-key-states-light.json", "shapes": 397, "texts": 179, "by_type": {"board": 187, "ellipse": 9, "rect": 22, "text": 179}, "sections": 14, "bytes": 75244, "largest_section": 11884, "largest_compacted": 6688}
