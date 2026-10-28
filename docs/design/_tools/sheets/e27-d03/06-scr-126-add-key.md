# E27-D03 / 06 scr-126-add-key

File `E27-D03 boards`, page `E27-D03 Accounts and key vault hi-fi` (render with `--page`); export `docs/design/E27/img/E27-D03-06-scr-126-add-key.png`; sheet `06-scr-126-add-key.json` (validated); theme dark.

06-scr-126-add-key.json: 0 errors, 77 warnings, 108 sections, 421535 bytes

## Frames

- `SCR-126 / register the account shell` — hi-fi row E27-D03 L1185; E27-D02 §7 E27-D02 L939
- `SCR-126 / paste the key: write-only fields and the allowlist row` — hi-fi row E27-D03 L1186; E27-D02 §7 E27-D02 L940 · PROPOSED HD11, HD14, D03-G1
- `SCR-126 / validating state` — hi-fi row E27-D03 L1187; E27-D02 §7 E27-D02 L941 · PROPOSED HD11, HD14
- `SCR-126 / verified and stored: the result panel` — hi-fi row E27-D03 L1188; E27-D02 §7 E27-D02 L942 · PROPOSED D03-C15
- `SCR-126 / validation: format, duplicate UID, the sixth sub-account` — hi-fi row E27-D03 L1189; E27-D02 §7 E27-D02 L943
- `SCR-126 / refused: withdrawal or transfer right` — hi-fi row E27-D03 L1190; E27-D02 §7 E27-D02 L944
- `SCR-126 / refused: IP allowlist, Bybit refused the egress IP` — hi-fi row E27-D03 L1191; E27-D02 §7 E27-D02 L945
- `SCR-126 / refused: IP allowlist, CandleViewer's rule` — hi-fi row E27-D03 L1192; E27-D02 §7 E27-D02 L946
- `SCR-126 / refused: the other checks` — hi-fi row E27-D03 L1193; E27-D02 §7 E27-D02 L947
- `SCR-126 / no verdict: nothing stored` — hi-fi row E27-D03 L1194; E27-D02 §7 E27-D02 L948 · PROPOSED HD14
- `SCR-126 / activation failed after a pass` — hi-fi row E27-D03 L1195; E27-D02 §7 E27-D02 L949
- `SCR-126 / KEK unavailable` — hi-fi row E27-D03 L1196; E27-D02 §7 E27-D02 L950 · shows T2 · PROPOSED HD6, HD14
- `SCR-126 / step-up gate before save` — hi-fi row E27-D03 L1197; E27-D02 §7 E27-D02 L951 · PROPOSED HD14
- `SCR-126 / edit mode: no key field, the key row with Rotate` — hi-fi row E27-D03 L1198; E27-D02 §7 E27-D02 L952
- `SCR-126 / edit conflict and refusals` — hi-fi row E27-D03 L1199; E27-D02 §7 E27-D02 L953
- `SCR-016 / step 3 loading: verifying` — hi-fi row E27-D03 L1223; E27-D02 §7 E27-D02 L993 · PROPOSED HD14
- `SCR-016 / step 3 valid: verified and stored` — hi-fi row E27-D03 L1224; E27-D02 §7 E27-D02 L994 · PROPOSED D03-C15
- `SCR-016 / step 3 invalid: a check refused` — hi-fi row E27-D03 L1225; E27-D02 §7 E27-D02 L995
- `SCR-016 / step 3 skipped: Skip for now` — hi-fi row E27-D03 L1226; E27-D02 §7 E27-D02 L996

## Content checks

- every frame text issued from the deck / pinned text / fixtures (write_sheet)
- write-only wells show dots, never characters; no reveal control (BQ-8)
- T2 only on frame 29 (E27-D02 §7 'shows T2'); never color.text.disabled / opacity.disabled

## Live checks for the drawer

- frames 18, 19, 21, 30 and 31 (800 high): the form card's buttons sit above the StatusBar (about 20 px spare by the estimate); frames taller than 800 draw §3.1's continuation under the viewport line
- the masked dots and the loading spinner render (no characters in a write-only well)
- render on page 'E27-D03 Accounts and key vault hi-fi' (mkcall4.py … --page 'E27-D03 Accounts and key vault hi-fi'; its default would be 'E27-D03')
- root 'E27-D03 / 06 scr-126-add-key': hugs its content (about 5640 x 5888 px estimated, 4 cells per row)
- rename frame 'SCR-126 ∕ register the account shell' to 'SCR-126 / register the account shell' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ paste the key: write-only fields and the allowlist row' to 'SCR-126 / paste the key: write-only fields and the allowlist row' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ validating state' to 'SCR-126 / validating state' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ verified and stored: the result panel' to 'SCR-126 / verified and stored: the result panel' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ validation: format, duplicate UID, the sixth sub-account' to 'SCR-126 / validation: format, duplicate UID, the sixth sub-account' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ refused: withdrawal or transfer right' to 'SCR-126 / refused: withdrawal or transfer right' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ refused: IP allowlist, Bybit refused the egress IP' to 'SCR-126 / refused: IP allowlist, Bybit refused the egress IP' after the board's last section (split across sections)
- rename frame "SCR-126 ∕ refused: IP allowlist, CandleViewer's rule" to "SCR-126 / refused: IP allowlist, CandleViewer's rule" after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ refused: the other checks' to 'SCR-126 / refused: the other checks' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ no verdict: nothing stored' to 'SCR-126 / no verdict: nothing stored' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ activation failed after a pass' to 'SCR-126 / activation failed after a pass' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ KEK unavailable' to 'SCR-126 / KEK unavailable' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ step-up gate before save' to 'SCR-126 / step-up gate before save' after the board's last section (split across sections)
- rename frame 'SCR-126 ∕ edit mode: no key field, the key row with Rotate' to 'SCR-126 / edit mode: no key field, the key row with Rotate' after the board's last section (split across sections)
- rename frame 'SCR-016 ∕ step 3 loading: verifying' to 'SCR-016 / step 3 loading: verifying' after the board's last section (split across sections)
- rename frame 'SCR-016 ∕ step 3 valid: verified and stored' to 'SCR-016 / step 3 valid: verified and stored' after the board's last section (split across sections)
- rename frame 'SCR-016 ∕ step 3 invalid: a check refused' to 'SCR-016 / step 3 invalid: a check refused' after the board's last section (split across sections)

## Not yet served (annotation layer)

- not yet served — D03-G1, #896 · the egress address and its Copy before any check (E27-D03 L1026)

## PROPOSED stamps

- PROPOSED · HD11 (E27-D03 L285)
- PROPOSED · HD14 (E27-D03 L288)
- PROPOSED · D03-G1 (E27-D03 L2673)
- PROPOSED · D03-C15 (E27-D03 L2671)
- PROPOSED · HD6 (E27-D03 L280)

## Not drawn — the text is binding

## Strings used

- e27.scr126.register.fields[0] — E27-D03 L2189 (consumed)
- e27.scr126.register.fields[1] — E27-D03 L2189 (consumed)
- e27.scr126.register.fields[2] — E27-D03 L2189 (consumed)
- e27.scr126.register.fields[3] — E27-D03 L2189 (consumed)
- e27.scr126.register.fields[4] — E27-D03 L2189 (consumed)
- e27.scr126.register.fields[5] — E27-D03 L2189 (consumed)
- e27.scr126.register.env[0] — E27-D03 L2190 (refined)
- '(this deployment)' — E27-D03 (quoted)
- e27.shared.cancel[0] — E27-D03 L2471 (consumed)
- e27.scr126.register.buttons[0] — E27-D03 L2191 (consumed)
- e27.scr126.h1[0] — E27-D03 L2186 (consumed)
- e27.scr126.stepper[0] — E27-D03 L2187 (consumed)
- e27.scr126.stepper[1] — E27-D03 L2187 (consumed)
- e27.shell.band[0] — E27-D03 L2039 (consumed)
- e27.shell.strip.none[0] — E27-D03 L2041 (consumed)
- 'Admin area · Accounts · Add a Bybit account' — E27-D03 (quoted)
- e27.scr126.key.h2[0] — E27-D03 L2192 (refined)
- e27.scr126.key.instructions[0] — E27-D03 L2193 (consumed)
- e27.scr126.key.instructions[1] — E27-D03 L2193 (consumed)
- e27.scr126.key.instructions[2] — E27-D03 L2193 (consumed)
- e27.scr126.key.instructions[3] — E27-D03 L2193 (consumed)
- e27.scr126.allowlist.help[0] — E27-D03 L2195 (refined)
- e27.shared.copy[0] — E27-D03 L2469 (consumed)
- e27.scr126.allowlist.label[0] — E27-D03 L2194 (consumed)
- e27.scr126.key.label[0] — E27-D03 L2196 (consumed)
- e27.scr126.key.label[1] — E27-D03 L2196 (consumed)
- e27.scr126.secret.label[0] — E27-D03 L2197 (consumed)
- e27.scr126.secret.help[0] — E27-D03 L2198 (unchanged)
- e27.shared.ask[0] — E27-D03 L2468 (consumed)
- e27.scr126.marker[0] — E27-D03 L2199 (consumed)
- e27.scr126.buttons[0] — E27-D03 L2200 (consumed)
- e27.scr126.validating[0] — E27-D03 L2201 (consumed)
- e27.scr126.validating.long[0] — E27-D03 L2202 (consumed)
- e27.scr126.saved[0] — E27-D03 L2203 (consumed)
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
- e27.checks.row[0] — E27-D03 L2077 (consumed)
- e27.scr126.saved.done[0] — E27-D03 L2205 (consumed)
- e27.scr126.result.h3[0] — E27-D03 L2206 (new)
- e27.scr126.invalid.key_format[0] — E27-D03 L2212 (new)
- e27.scr126.invalid.secret_format[0] — E27-D03 L2213 (new)
- e27.scr126.invalid.uid[0] — E27-D03 L2214 (new)
- e27.scr126.invalid.duplicate_uid[0] — E27-D03 L2217 (refined)
- e27.scr126.invalid.sixth_sub[0] — E27-D03 L2218 (refined)
- e27.scr126.invalid.parent_env[0] — E27-D03 L2219 (new)
- e27.scr126.refused.withdrawal[0] — E27-D03 L2221 (unchanged)
- e27.cmp175.withdrawal_detected[0] — E27-D03 L2454 (consumed)
- e27.checks.not_checked[0] — E27-D03 L2079 (consumed)
- e27.scr126.refused.ip_bybit[0] — E27-D03 L2222 (refined)
- e27.scr126.refused.lead[0] — E27-D03 L2220 (consumed)
- e27.scr126.refused.ip_rule[0] — E27-D03 L2223 (refined)
- e27.scr126.refused.ip_read[0] — E27-D03 L2224 (refined)
- e27.checks.env.failed[0] — E27-D03 L2081 (refined)
- e27.checks.rights.failed[0] — E27-D03 L2084 (consumed)
- e27.checks.trade.failed[0] — E27-D03 L2086 (consumed)
- e27.checks.uta.failed[0] — E27-D03 L2088 (consumed)
- e27.checks.uid.failed[0] — E27-D03 L2090 (consumed)
- e27.checks.expiry.failed[0] — E27-D03 L2095 (consumed)
- e27.checks.probe.failed[0] — E27-D03 L2098 (consumed)
- e27.scr126.no_verdict.timeout[0] — E27-D03 L2225 (consumed)
- e27.scr126.no_verdict.error[0] — E27-D03 L2226 (consumed)
- e27.scr126.activation_failed[0] — E27-D03 L2227 (consumed)
- e27.shell.banner.kek[0] — E27-D03 L2053 (consumed)
- keys.kek_unavailable — E27-D03 L2489 (T2 reason key)
- e27.shared.kek_notice[0] — E27-D03 L2474 (consumed)
- 'SCR-006 code-only, E09-D06' — E27-D03 (quoted)
- e27.scr126.stepup.title[0] — E27-D03 L2241 (consumed)
- "Import API key for account 'demo-1' (demo, UID 9000001)" — E27-D03 (quoted)
- e27.scr125.menu.items[0] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[1] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[2] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[3] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[4] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[5] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[6] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[7] — E27-D03 L2140 (consumed)
- 'sub-account of Main' — E27-D03 (quoted)
- e27.scr126.edit.key_row[0] — E27-D03 L2234 (refined)
- e27.scr126.edit.write_only[0] — E27-D03 L2235 (refined)
- e27.scr126.edit.buttons[0] — E27-D03 L2236 (new)
- e27.scr126.edit.h1[0] — E27-D03 L2233 (new)
- e27.scr126.edit.conflict[0] — E27-D03 L2237 (refined)
- e27.scr126.edit.reload[0] — E27-D03 L2238 (new)
- e27.scr126.edit.label_taken[0] — E27-D03 L2239 (new)
- e27.scr126.edit.unchanged[0] — E27-D03 L2240 (refined)
- e27.scr016.buttons[0] — E27-D03 L2252 (consumed)
- e27.scr016.buttons[1] — E27-D03 L2252 (consumed)
- e27.scr016.buttons[2] — E27-D03 L2252 (consumed)
- e27.scr016.stepper[0] — E27-D03 L2248 (consumed)
- e27.scr016.stepper[1] — E27-D03 L2248 (consumed)
- e27.scr016.stepper[2] — E27-D03 L2248 (consumed)
- e27.scr016.stepper[3] — E27-D03 L2248 (consumed)
- e27.scr016.stepper[4] — E27-D03 L2248 (consumed)
- e27.scr016.stepper[5] — E27-D03 L2248 (consumed)
- e27.scr016.h1[0] — E27-D03 L2249 (consumed)
- e27.scr016.lead[0] — E27-D03 L2250 (consumed)
- e27.scr016.continue_early[0] — E27-D03 L2253 (refined)
- e27.scr016.result[0] — E27-D03 L2251 (refined)
- e27.scr016.skipped[0] — E27-D03 L2254 (refined)

## Kit choices and deviations

- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS GLYPHS)
- kit choice (chrome): The consumed chrome (CMP-072 TopBar, CMP-071 NavRail, CMP-209 RightRail, CMP-208 StatusBar; §3.1 block A) is drawn as placeholders at its redline geometry with the environment badges; it is consumed and never redrawn (§2.6)
- kit choice (cell): Each frame is a CELL: a caption row (the frame's exact §0 name in type.ui.heading-sm, then its PROPOSED stamp), the frame nested under its E27-D02 name, then its annotation-layer row (the 'not yet served' strips and notes; never inside the frame, never product UI)
- kit choice (strip): A 'not yet served — {gap}, {owner}' strip is board annotation (§0 L199-200): a warning-stroked pill on the cell's annotation layer, never inside the frame
- kit choice (t2): T2 per §10.1: 2a inline everywhere; CMP-079 wraps the control; the CMP-019 lock LEADS the full label; label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary; a filled control loses its fill (color.surface.raised + 1 px color.border.default); never color.text.disabled, never opacity.disabled
- kit choice (inset): SCR-016 step 3 rides as 800 px card insets on board 06 (BQ-1); its CMP-097 chrome is E09's
- kit choice (page): mkcall4.py derives a page from the board name ('E27-D03 / NN …' -> 'E27-D03'); the sheet carries its page in sheet['page'] and the renderer passes --page 'E27-D03 Accounts and key vault hi-fi'
- kit choice (split): A frame whose JSON exceeds the section budget is split across sections under its name with '∕' (U+2215) for '/' (cvsheet splits section paths on '/'); the drawer renames it after the board's last section (live check)

## Tokens and fallbacks

- token: CMP-075's radius.pill is a Tier-1 primitive (§3.1 block I names it; validator WARN)
- token: control heights bind the Tier-1 size.control.compact (24) / size.control.comfortable (32) (BQ-4, HD12: the admin screens comfortable, SCR-079 compact; the semantic size.control.height resolves through the active density set, so the boards bind the mode's own primitive; validator WARN)
- fallback: no typography token carries font.weight.bold at caption / body size; the critical word (BQ-6) binds type.ui.label (medium) and keeps its other carriers — 'BLOCKED' first, the octagon and the 2 px border.thick color.status.danger.strong border; the LIVE pill's bold word likewise (§3.1 block I)
- fallback: the per-set file holds only the local icons locked, arrow-up, arrow-down, close and drag-handle; CMP-175's class glyphs are drawn so each class keeps its own SHAPE (BQ-6: the shape is the carrier): check = text glyph ✓, triangle = text glyph ⚠, octagon = a 16 px square with clipped look (radius.control) filled in the class token holding a '!' (cvsheet has no polygon), clock = a stroked ring with two hands, dash = a 10 x 2 bar, info = a stroked ring holding 'i', slashed circle = text glyph ⊘; plus, chevron, more and copy are text glyphs (+ ▾ ⋮ ⧉)
- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'
- token: opacity.scrim is a Tier-1 primitive (validator WARN): the modal scrim under CMP-046 / CMP-043

## Copy gaps

- frames 23 and 74: no e27.checks.withdrawal.failed deck row; the failed row reads CMP-175's e27.cmp175.withdrawal_detected word

## Sources

- spec docs/design/E27/E27-D03.md at 1983363fa md5 f386f58eeeb8aaadc18696c0ceba3e81 (frozen copy E27-D03@1983363fa.md)
- spec docs/design/E27/E27-D03-handoff.md at 1983363fa md5 4036e46f59e34d55af53cfa4480bdc15 (frozen copy E27-D03-handoff@1983363fa.md)
- spec docs/design/E27/E27-D02.md at 1983363fa md5 ec56733e286dd5cf2f7d0282d24ba9b2 (frozen copy E27-D02@1983363fa.md)
- Penpot file 'E27-D03 boards', page 'E27-D03 Accounts and key vault hi-fi'; kit e27d03kit.py md5 241e3b7d5bda4f99f4e0d1a3023aa720; renderer cvsheet-v4.3.js
- SCR-126 / register the account shell: hi-fi row E27-D03 L1185 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L939
- SCR-126 / paste the key: write-only fields and the allowlist row: hi-fi row E27-D03 L1186 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L940
- SCR-126 / validating state: hi-fi row E27-D03 L1187 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L941
- CMP-203: E27-D03 L909
- SCR-126 / verified and stored: the result panel: hi-fi row E27-D03 L1188 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L942
- SCR-126 / validation: format, duplicate UID, the sixth sub-account: hi-fi row E27-D03 L1189 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L943
- SCR-126 / refused: withdrawal or transfer right: hi-fi row E27-D03 L1190 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L944
- SCR-126 / refused: IP allowlist, Bybit refused the egress IP: hi-fi row E27-D03 L1191 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L945
- SCR-126 / refused: IP allowlist, CandleViewer's rule: hi-fi row E27-D03 L1192 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L946
- SCR-126 / refused: the other checks: hi-fi row E27-D03 L1193 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L947
- SCR-126 / no verdict: nothing stored: hi-fi row E27-D03 L1194 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L948
- SCR-126 / activation failed after a pass: hi-fi row E27-D03 L1195 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L949
- CMP-028 KEK notice: E27-D03 L705
- SCR-126 / KEK unavailable: hi-fi row E27-D03 L1196 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L950
- SCR-126 / step-up gate before save: hi-fi row E27-D03 L1197 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L951
- SCR-126 / edit mode: no key field, the key row with Rotate: hi-fi row E27-D03 L1198 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L952
- SCR-126 / edit conflict and refusals: hi-fi row E27-D03 L1199 (4.3 The hi-fi rows); E27-D02 §7 E27-D02 L953
- SCR-016 / step 3 loading: verifying: hi-fi row E27-D03 L1223 (4.4 SCR-016 step 3 — the account step as insets); E27-D02 §7 E27-D02 L993
- SCR-016 / step 3 valid: verified and stored: hi-fi row E27-D03 L1224 (4.4 SCR-016 step 3 — the account step as insets); E27-D02 §7 E27-D02 L994
- SCR-016 / step 3 invalid: a check refused: hi-fi row E27-D03 L1225 (4.4 SCR-016 step 3 — the account step as insets); E27-D02 §7 E27-D02 L995
- SCR-016 / step 3 skipped: Skip for now: hi-fi row E27-D03 L1226 (4.4 SCR-016 step 3 — the account step as insets); E27-D02 §7 E27-D02 L996

## Shape count

- {"sheet": "06-scr-126-add-key.json", "shapes": 2632, "texts": 957, "by_type": {"board": 1128, "ellipse": 225, "icon": 1, "rect": 321, "text": 957}, "sections": 108, "bytes": 421535, "largest_section": 11911, "largest_compacted": 8771}
