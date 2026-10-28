# E27-D03 / 07 scr-127-rotate

File `E27-D03 boards`, page `E27-D03 Accounts and key vault hi-fi` (render with `--page`); export `docs/design/E27/img/E27-D03-07-scr-127-rotate.png`; sheet `07-scr-127-rotate.json` (validated); theme dark.

07-scr-127-rotate.json: 0 errors, 65 warnings, 36 sections, 205302 bytes

## Frames

- `SCR-127 / stage 1: create the new key at Bybit` — hi-fi row E27-D03 L1295; E27-D02 §7 E27-D02 L954 · PROPOSED HD9, HD14, D03-G1
- `SCR-127 / stage 2: paste and confirm` — hi-fi row E27-D03 L1296; E27-D02 §7 E27-D02 L955 · PROPOSED HD8, HD9, HD11
- `SCR-127 / stage 3: verifying, elapsed time per stage` — hi-fi row E27-D03 L1297; E27-D02 §7 E27-D02 L956 · PROPOSED HD9
- `SCR-127 / stage 3 refused: nothing changed, the old key still active` — hi-fi row E27-D03 L1298; E27-D02 §7 E27-D02 L957 · PROPOSED HD9, D03-C15
- `SCR-127 / stage 3 no verdict: nothing changed` — hi-fi row E27-D03 L1299; E27-D02 §7 E27-D02 L958 · PROPOSED HD9
- `SCR-127 / stage 4: switched, the 900 s overlap` — hi-fi row E27-D03 L1300; E27-D02 §7 E27-D02 L959 · PROPOSED HD7, HD9
- `SCR-127 / stage 5: old key revoked here, delete it at Bybit` — hi-fi row E27-D03 L1301; E27-D02 §7 E27-D02 L960 · PROPOSED HD9
- `SCR-127 / not yet served: drain read, rollback, early revoke, failed` — hi-fi row E27-D03 L1302; E27-D02 §7 E27-D02 L961 · PROPOSED HD7, HD9
- `SCR-127 / KEK unavailable: Rotate is T2` — hi-fi row E27-D03 L1303; E27-D02 §7 E27-D02 L962 · shows T2 · PROPOSED HD6

## Content checks

- every frame text issued from the deck / pinned text / fixtures (write_sheet)
- no frame shows more of a key than its masked id; write-only wells show dots only (BQ-8)
- T2 only on frame 41 (E27-D02 §7 'shows T2'); the busy confirm is never T2

## Live checks for the drawer

- every dialog sits inside the viewport less 48 px; a body taller than that clips and is marked to scroll
- frame 34: the wizard left of centre and SCR-006's footprint beside it, neither overlapping
- render on page 'E27-D03 Accounts and key vault hi-fi' (mkcall4.py … --page 'E27-D03 Accounts and key vault hi-fi'; its default would be 'E27-D03')
- root 'E27-D03 / 07 scr-127-rotate': hugs its content (about 5640 x 2828 px estimated, 4 cells per row)
- rename frame 'SCR-127 ∕ stage 1: create the new key at Bybit' to 'SCR-127 / stage 1: create the new key at Bybit' after the board's last section (split across sections)
- rename frame 'SCR-127 ∕ stage 2: paste and confirm' to 'SCR-127 / stage 2: paste and confirm' after the board's last section (split across sections)
- rename frame 'SCR-127 ∕ stage 3: verifying, elapsed time per stage' to 'SCR-127 / stage 3: verifying, elapsed time per stage' after the board's last section (split across sections)
- rename frame 'SCR-127 ∕ stage 3 refused: nothing changed, the old key still active' to 'SCR-127 / stage 3 refused: nothing changed, the old key still active' after the board's last section (split across sections)
- rename frame 'SCR-127 ∕ stage 3 no verdict: nothing changed' to 'SCR-127 / stage 3 no verdict: nothing changed' after the board's last section (split across sections)
- rename frame 'SCR-127 ∕ stage 4: switched, the 900 s overlap' to 'SCR-127 / stage 4: switched, the 900 s overlap' after the board's last section (split across sections)
- rename frame 'SCR-127 ∕ stage 5: old key revoked here, delete it at Bybit' to 'SCR-127 / stage 5: old key revoked here, delete it at Bybit' after the board's last section (split across sections)
- rename frame 'SCR-127 ∕ not yet served: drain read, rollback, early revoke, failed' to 'SCR-127 / not yet served: drain read, rollback, early revoke, failed' after the board's last section (split across sections)
- rename frame 'SCR-127 ∕ KEK unavailable: Rotate is T2' to 'SCR-127 / KEK unavailable: Rotate is T2' after the board's last section (split across sections)

## Not yet served (annotation layer)

- not yet served — D03-G1, #896 · the address and its Copy before any check (E27-D03 L1026)
- not yet served — G-4, #897 · no drain read, no rollback, no early revoke, state: failed undefined, no schedule control (E27-D03 L1302)

## PROPOSED stamps

- PROPOSED · HD9 (E27-D03 L283)
- PROPOSED · HD14 (E27-D03 L288)
- PROPOSED · D03-G1 (E27-D03 L2673)
- PROPOSED · HD8 (E27-D03 L282)
- PROPOSED · HD11 (E27-D03 L285)
- PROPOSED · D03-C15 (E27-D03 L2671)
- PROPOSED · HD7 (E27-D03 L281)
- PROPOSED · HD6 (E27-D03 L280)

## Not drawn — the text is binding

## Strings used

- e27.scr127.stage1.create[0] — E27-D03 L2264 (refined)
- e27.scr127.stage1.allowlist[0] — E27-D03 L2266 (refined)
- e27.shared.copy[0] — E27-D03 L2469 (consumed)
- e27.scr127.stage1.policy[0] — E27-D03 L2267 (consumed)
- e27.scr127.stage1.no_wait[0] — E27-D03 L2268 (consumed)
- e27.scr127.stage1.h2[0] — E27-D03 L2265 (new)
- e27.shared.cancel[0] — E27-D03 L2471 (consumed)
- e27.scr127.stage1.next[0] — E27-D03 L2269 (new)
- e27.scr127.title[0] — E27-D03 L2260 (refined)
- e27.scr127.stepper[0] — E27-D03 L2261 (consumed)
- e27.scr127.stepper[1] — E27-D03 L2261 (consumed)
- e27.scr127.stepper[2] — E27-D03 L2261 (consumed)
- e27.scr127.stepper[3] — E27-D03 L2261 (consumed)
- e27.scr127.stepper[4] — E27-D03 L2261 (consumed)
- e27.scr127.stepper.status[0] — E27-D03 L2263 (refined)
- e27.scr127.stepper.status[1] — E27-D03 L2263 (refined)
- e27.scr127.stepper.status[2] — E27-D03 L2263 (refined)
- e27.scr127.stepper.status[3] — E27-D03 L2263 (refined)
- e27.scr125.verdict.dated[0] — E27-D03 L2064 (refined)
- e27.shell.region.accounts[0] — E27-D03 L2049 (consumed)
- e27.shell.cta.add[0] — E27-D03 L2047 (consumed)
- e27.shell.band[0] — E27-D03 L2039 (consumed)
- e27.shell.strip.none[0] — E27-D03 L2041 (consumed)
- e27.shell.h1[0] — E27-D03 L2045 (consumed)
- e27.shell.footer[0] — E27-D03 L2051 (consumed)
- e27.scr127.buttons[0] — E27-D03 L2276 (consumed)
- e27.scr127.buttons[1] — E27-D03 L2276 (consumed)
- e27.scr127.stage2.lead[0] — E27-D03 L2271 (consumed)
- e27.scr127.stage2.no_undo[0] — E27-D03 L2272 (refined)
- e27.scr127.stage2.fields[0] — E27-D03 L2273 (consumed)
- e27.scr127.stage2.fields[1] — E27-D03 L2273 (consumed)
- e27.scr126.key.label[0] — E27-D03 L2196 (consumed)
- e27.scr126.key.label[1] — E27-D03 L2196 (consumed)
- e27.scr127.secret.help[0] — E27-D03 L2274 (unchanged)
- e27.shared.ask[0] — E27-D03 L2468 (consumed)
- e27.scr127.marker[0] — E27-D03 L2275 (consumed)
- e27.scr127.stage2.h2[0] — E27-D03 L2270 (consumed)
- 'SCR-006 code-only, E09-D06' — E27-D03 (quoted)
- e27.scr126.stepup.title[0] — E27-D03 L2241 (consumed)
- e27.scr126.validating[0] — E27-D03 L2201 (consumed)
- e27.scr126.validating.long[0] — E27-D03 L2202 (consumed)
- e27.scr127.stage3.h2[0] — E27-D03 L2278 (new)
- e27.shared.close[0] — E27-D03 L2472 (consumed)
- e27.scr127.stage3.meta[0] — E27-D03 L2277 (refined)
- e27.scr127.stage3.refused[0] — E27-D03 L2279 (consumed)
- e27.checks.names[0] — E27-D03 L2078 (refined)
- e27.checks.names[1] — E27-D03 L2078 (refined)
- e27.checks.names[2] — E27-D03 L2078 (refined)
- e27.checks.names[3] — E27-D03 L2078 (refined)
- e27.checks.names[4] — E27-D03 L2078 (refined)
- e27.checks.names[5] — E27-D03 L2078 (refined)
- e27.checks.names[6] — E27-D03 L2078 (refined)
- e27.checks.names[7] — E27-D03 L2078 (refined)
- e27.checks.names[8] — E27-D03 L2078 (refined)
- e27.checks.env.passed[0] — E27-D03 L2080 (refined)
- e27.checks.withdrawal.passed[0] — E27-D03 L2082 (refined)
- e27.checks.rights.passed[0] — E27-D03 L2083 (consumed)
- e27.checks.trade.passed[0] — E27-D03 L2085 (consumed)
- e27.checks.uta.passed[0] — E27-D03 L2087 (consumed)
- e27.checks.uid.passed[0] — E27-D03 L2089 (refined)
- e27.checks.allowlist.passed[0] — E27-D03 L2091 (refined)
- e27.checks.expiry.passed[0] — E27-D03 L2092 (consumed)
- e27.checks.probe.passed[0] — E27-D03 L2096 (refined)
- e27.scr126.refused.ip_read[0] — E27-D03 L2224 (refined)
- e27.checks.row[0] — E27-D03 L2077 (consumed)
- e27.scr126.refused.ip_rule[0] — E27-D03 L2223 (refined)
- e27.scr127.stage3.new_key_lives[0] — E27-D03 L2282 (consumed)
- e27.scr127.stage3.refused_h2[0] — E27-D03 L2280 (new)
- e27.scr127.stage3.back[0] — E27-D03 L2281 (refined)
- e27.scr127.stage3.no_verdict[0] — E27-D03 L2284 (refined)
- e27.scr127.stage3.no_verdict_h2[0] — E27-D03 L2283 (consumed)
- e27.scr127.stage4.h2[0] — E27-D03 L2285 (new)
- e27.scr127.stage4.switched[0] — E27-D03 L2286 (consumed)
- 'Switched at 10:40:01 UTC. New requests use ...d9e0. The old key ...e5f6 keeps working here' — E27-D03 (quoted)
- e27.scr127.stage4.no_undo[0] — E27-D03 L2287 (consumed)
- e27.scr127.stage5.revoked[0] — E27-D03 L2291 (unchanged)
- e27.shared.bybit_note[0] — E27-D03 L2473 (refined)
- e27.scr127.stage5.h2[0] — E27-D03 L2290 (new)
- e27.scr125.menu.items[0] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[1] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[2] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[3] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[4] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[5] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[6] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[7] — E27-D03 L2140 (consumed)
- keys.kek_unavailable — E27-D03 L2489 (T2 reason key)
- e27.shell.banner.kek[0] — E27-D03 L2053 (consumed)
- e27.shared.kek_notice[0] — E27-D03 L2474 (consumed)
- e27.scr125.verdict.unavailable[0] — E27-D03 L2067 (consumed)

## Kit choices and deviations

- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS GLYPHS)
- kit choice (chrome): The consumed chrome (CMP-072 TopBar, CMP-071 NavRail, CMP-209 RightRail, CMP-208 StatusBar; §3.1 block A) is drawn as placeholders at its redline geometry with the environment badges; it is consumed and never redrawn (§2.6)
- kit choice (cell): Each frame is a CELL: a caption row (the frame's exact §0 name in type.ui.heading-sm, then its PROPOSED stamp), the frame nested under its E27-D02 name, then its annotation-layer row (the 'not yet served' strips and notes; never inside the frame, never product UI)
- kit choice (strip): A 'not yet served — {gap}, {owner}' strip is board annotation (§0 L199-200): a warning-stroked pill on the cell's annotation layer, never inside the frame
- kit choice (t2): T2 per §10.1: 2a inline everywhere; CMP-079 wraps the control; the CMP-019 lock LEADS the full label; label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary; a filled control loses its fill (color.surface.raised + 1 px color.border.default); never color.text.disabled, never opacity.disabled
- kit choice (focus): A focus ring is CMP-039's 2 px color.focus.ring stroke on a wrapper 2 px outside the control
- kit choice (page): mkcall4.py derives a page from the board name ('E27-D03 / NN …' -> 'E27-D03'); the sheet carries its page in sheet['page'] and the renderer passes --page 'E27-D03 Accounts and key vault hi-fi'
- kit choice (split): A frame whose JSON exceeds the section budget is split across sections under its name with '∕' (U+2215) for '/' (cvsheet splits section paths on '/'); the drawer renames it after the board's last section (live check)

## Tokens and fallbacks

- fallback: the per-set file holds only the local icons locked, arrow-up, arrow-down, close and drag-handle; CMP-175's class glyphs are drawn so each class keeps its own SHAPE (BQ-6: the shape is the carrier): check = text glyph ✓, triangle = text glyph ⚠, octagon = a 16 px square with clipped look (radius.control) filled in the class token holding a '!' (cvsheet has no polygon), clock = a stroked ring with two hands, dash = a 10 x 2 bar, info = a stroked ring holding 'i', slashed circle = text glyph ⊘; plus, chevron, more and copy are text glyphs (+ ▾ ⋮ ⧉)
- token: control heights bind the Tier-1 size.control.compact (24) / size.control.comfortable (32) (BQ-4, HD12: the admin screens comfortable, SCR-079 compact; the semantic size.control.height resolves through the active density set, so the boards bind the mode's own primitive; validator WARN)
- token: CMP-075's radius.pill is a Tier-1 primitive (§3.1 block I names it; validator WARN)
- fallback: no typography token carries font.weight.bold at caption / body size; the critical word (BQ-6) binds type.ui.label (medium) and keeps its other carriers — 'BLOCKED' first, the octagon and the 2 px border.thick color.status.danger.strong border; the LIVE pill's bold word likewise (§3.1 block I)
- token: opacity.scrim is a Tier-1 primitive (validator WARN): the modal scrim under CMP-046 / CMP-043
- fallback: CMP-015's skeleton is a static bar in color.surface.hover (reduced-motion form, §2.5)
- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'
- token: the CMP-039 ring (2 px color.focus.ring, its offset) binds radius.md (6 px) on a wrapper 2 px outside the control (validator WARN)

## Copy gaps

## Sources

- spec docs/design/E27/E27-D03.md at 1983363fa md5 f386f58eeeb8aaadc18696c0ceba3e81 (frozen copy E27-D03@1983363fa.md)
- spec docs/design/E27/E27-D03-handoff.md at 1983363fa md5 4036e46f59e34d55af53cfa4480bdc15 (frozen copy E27-D03-handoff@1983363fa.md)
- spec docs/design/E27/E27-D02.md at 1983363fa md5 ec56733e286dd5cf2f7d0282d24ba9b2 (frozen copy E27-D02@1983363fa.md)
- Penpot file 'E27-D03 boards', page 'E27-D03 Accounts and key vault hi-fi'; kit e27d03kit.py md5 241e3b7d5bda4f99f4e0d1a3023aa720; renderer cvsheet-v4.3.js
- CMP-175 aggregate dated: E27-D03 L386
- SCR-127 / stage 1: create the new key at Bybit: hi-fi row E27-D03 L1295 (5. SCR-127 — Key rotation); E27-D02 §7 E27-D02 L954
- SCR-127 / stage 2: paste and confirm: hi-fi row E27-D03 L1296 (5. SCR-127 — Key rotation); E27-D02 §7 E27-D02 L955
- SCR-127 / stage 3: verifying, elapsed time per stage: hi-fi row E27-D03 L1297 (5. SCR-127 — Key rotation); E27-D02 §7 E27-D02 L956
- SCR-127 / stage 3 refused: nothing changed, the old key still active: hi-fi row E27-D03 L1298 (5. SCR-127 — Key rotation); E27-D02 §7 E27-D02 L957
- SCR-127 / stage 3 no verdict: nothing changed: hi-fi row E27-D03 L1299 (5. SCR-127 — Key rotation); E27-D02 §7 E27-D02 L958
- SCR-127 / stage 4: switched, the 900 s overlap: hi-fi row E27-D03 L1300 (5. SCR-127 — Key rotation); E27-D02 §7 E27-D02 L959
- SCR-127 / stage 5: old key revoked here, delete it at Bybit: hi-fi row E27-D03 L1301 (5. SCR-127 — Key rotation); E27-D02 §7 E27-D02 L960
- SCR-127 / not yet served: drain read, rollback, early revoke, failed: hi-fi row E27-D03 L1302 (5. SCR-127 — Key rotation); E27-D02 §7 E27-D02 L961
- CMP-028 KEK notice: E27-D03 L705
- CMP-175 aggregate unavailable: E27-D03 L389
- SCR-127 / KEK unavailable: Rotate is T2: hi-fi row E27-D03 L1303 (5. SCR-127 — Key rotation); E27-D02 §7 E27-D02 L962

## Shape count

- {"sheet": "07-scr-127-rotate.json", "shapes": 1261, "texts": 442, "by_type": {"board": 534, "ellipse": 97, "icon": 3, "rect": 185, "text": 442}, "sections": 36, "bytes": 205302, "largest_section": 11856, "largest_compacted": 8497}
