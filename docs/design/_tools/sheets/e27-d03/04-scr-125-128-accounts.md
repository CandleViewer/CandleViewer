# E27-D03 / 04 scr-125-128-accounts

File `E27-D03 boards`, page `E27-D03 Accounts and key vault hi-fi` (render with `--page`); export `docs/design/E27/img/E27-D03-04-scr-125-128-accounts.png`; sheet `04-scr-125-128-accounts.json` (validated); theme dark.

## Frames

- `CMP-087 / the accounts route in the admin shell` — hi-fi row E27-D03 L1079; E27-D02 §7 E27-D02 L922 · PROPOSED HD3, HD5, HD10
- `SCR-125 / ok` — hi-fi row E27-D03 L1080; E27-D02 §7 E27-D02 L927 · PROPOSED HD3, HD5, HD10
- `SCR-125 / empty` — hi-fi row E27-D03 L1081; E27-D02 §7 E27-D02 L928
- `SCR-125 / loading and error` — hi-fi row E27-D03 L1082; E27-D02 §7 E27-D02 L929
- `SCR-125 / key expiring (<14 d): rotation due and Bybit expiry` — hi-fi row E27-D03 L1083; E27-D02 §7 E27-D02 L930 · PROPOSED HD3, HD5, HD10, D03-C6
- `SCR-125 / within Bybit's 48 h new-key restriction` — hi-fi row E27-D03 L1084; E27-D02 §7 E27-D02 L931 · PROPOSED HD3, HD5, HD10
- `SCR-125 / row menu and Test` — hi-fi row E27-D03 L1085; E27-D02 §7 E27-D02 L932 · shows T2 · PROPOSED HD3, HD5, HD10
- `SCR-125 / at the sub-account cap` — hi-fi row E27-D03 L1086; E27-D02 §7 E27-D02 L933
- `SCR-125 / withdrawal permission detected: blocking error` — hi-fi row E27-D03 L1087; E27-D02 §7 E27-D02 L934 · shows T2 · PROPOSED HD3, HD5, HD10, HD4, BQ-6, D03-C7
- `SCR-125 / IP whitelist missing or mismatched` — hi-fi row E27-D03 L1088; E27-D02 §7 E27-D02 L935 · PROPOSED HD3, HD5, HD10, HD14
- `SCR-125 / key invalid` — hi-fi row E27-D03 L1089; E27-D02 §7 E27-D02 L936 · PROPOSED HD3, HD5, HD10
- `SCR-125 / health degraded and down` — hi-fi row E27-D03 L1090; E27-D02 §7 E27-D02 L937 · PROPOSED HD3, HD5, HD10
- `SCR-125 / KEK unavailable` — hi-fi row E27-D03 L1091; E27-D02 §7 E27-D02 L938 · shows T2 · PROPOSED HD3, HD5, HD10, HD6
- `SCR-128 / key table and the secrets-at-rest policy` — hi-fi row E27-D03 L1381; E27-D02 §7 E27-D02 L963 · PROPOSED HD16, HD14
- `SCR-128 / overdue rotation` — hi-fi row E27-D03 L1382; E27-D02 §7 E27-D02 L964 · PROPOSED HD16
- `SCR-128 / Test passed while trading is read-only` — hi-fi row E27-D03 L1383; E27-D02 §7 E27-D02 L965 · PROPOSED HD3, HD5, HD10, HD4, HD16
- `SCR-128 / KEK unavailable: one panel notice` — hi-fi row E27-D03 L1384; E27-D02 §7 E27-D02 L966 · shows T2 · PROPOSED HD6
- `SCR-128 / mark as compromised: the ordered card` — hi-fi row E27-D03 L1385; E27-D02 §7 E27-D02 L967
- `SCR-128 / compromise card: the revoke refused` — hi-fi row E27-D03 L1386; E27-D02 §7 E27-D02 L968
- `SCR-128 / compromise card: after the Bybit delete, the account reads dead` — hi-fi row E27-D03 L1387; E27-D02 §7 E27-D02 L969

## Content checks

- §0's 20 frames by exact name, in §0's order; T2 only on frames 11, 13, 17, 45 (E27-D02 §7 'shows T2')
- every frame string issued from the deck / §12.2 reasons / quoted hi-fi text / fixtures
- stamps and 'not yet served' strips on the annotation layer only

## Live checks for the drawer

- fit: SCR-128 / mark as compromised: the ordered card: content about 1360 px for 760 px — the frame clips (a page scroll, §3.1: the board may draw the continuation under the viewport line); check the export
- fit: SCR-128 / compromise card: the revoke refused: content about 1383 px for 784 px — the frame clips (a page scroll, §3.1: the board may draw the continuation under the viewport line); check the export
- fit: SCR-128 / compromise card: after the Bybit delete, the account reads dead: content about 1463 px for 848 px — the frame clips (a page scroll, §3.1: the board may draw the continuation under the viewport line); check the export
- render on page 'E27-D03 Accounts and key vault hi-fi' (mkcall4.py … --page 'E27-D03 Accounts and key vault hi-fi'; its default would be 'E27-D03')
- root 'E27-D03 / 04 scr-125-128-accounts': hugs its content (about 5640 x 6001 px estimated, 4 cells per row)
- rename frame 'CMP-087 ∕ the accounts route in the admin shell' to 'CMP-087 / the accounts route in the admin shell' after the board's last section (split across sections)
- rename frame 'SCR-125 ∕ ok' to 'SCR-125 / ok' after the board's last section (split across sections)
- rename frame 'SCR-125 ∕ empty' to 'SCR-125 / empty' after the board's last section (split across sections)
- rename frame 'SCR-125 ∕ loading and error' to 'SCR-125 / loading and error' after the board's last section (split across sections)
- rename frame 'SCR-125 ∕ key expiring (<14 d): rotation due and Bybit expiry' to 'SCR-125 / key expiring (<14 d): rotation due and Bybit expiry' after the board's last section (split across sections)
- rename frame "SCR-125 ∕ within Bybit's 48 h new-key restriction" to "SCR-125 / within Bybit's 48 h new-key restriction" after the board's last section (split across sections)
- rename frame 'SCR-125 ∕ row menu and Test' to 'SCR-125 / row menu and Test' after the board's last section (split across sections)
- rename frame 'SCR-125 ∕ withdrawal permission detected: blocking error' to 'SCR-125 / withdrawal permission detected: blocking error' after the board's last section (split across sections)
- rename frame 'SCR-125 ∕ IP whitelist missing or mismatched' to 'SCR-125 / IP whitelist missing or mismatched' after the board's last section (split across sections)
- rename frame 'SCR-125 ∕ key invalid' to 'SCR-125 / key invalid' after the board's last section (split across sections)
- rename frame 'SCR-125 ∕ health degraded and down' to 'SCR-125 / health degraded and down' after the board's last section (split across sections)
- rename frame 'SCR-125 ∕ KEK unavailable' to 'SCR-125 / KEK unavailable' after the board's last section (split across sections)
- rename frame 'SCR-128 ∕ key table and the secrets-at-rest policy' to 'SCR-128 / key table and the secrets-at-rest policy' after the board's last section (split across sections)
- rename frame 'SCR-128 ∕ overdue rotation' to 'SCR-128 / overdue rotation' after the board's last section (split across sections)
- rename frame 'SCR-128 ∕ Test passed while trading is read-only' to 'SCR-128 / Test passed while trading is read-only' after the board's last section (split across sections)
- rename frame 'SCR-128 ∕ KEK unavailable: one panel notice' to 'SCR-128 / KEK unavailable: one panel notice' after the board's last section (split across sections)
- rename frame 'SCR-128 ∕ mark as compromised: the ordered card' to 'SCR-128 / mark as compromised: the ordered card' after the board's last section (split across sections)
- rename frame 'SCR-128 ∕ compromise card: the revoke refused' to 'SCR-128 / compromise card: the revoke refused' after the board's last section (split across sections)
- rename frame 'SCR-128 ∕ compromise card: after the Bybit delete, the account reads dead' to 'SCR-128 / compromise card: after the Bybit delete, the account reads dead' after the board's last section (split across sections)

## Not yet served (annotation layer)

- not yet served — G-8, #895 / #898 · the password-and-code ask on Disable… and Delete… (E27-D03 L123)
- not yet served — G-1, #895 / #896 · the blocked record, its strip item and its gated Rotate key… (E27-D03 L179)
- not yet served — D03-G1, #896 · the egress IP and its Copy before a Test this client ran (E27-D03 L1026)
- not yet served — G-1, #895 / #896 · the record (E27-D03 L179)
- not yet served — D03-G1, #896 · the policy's address (BQ-15 item 7) (E27-D03 L1026)
- not yet served — G-12, #3657 · Main's off-by-policy form (E27-D03 L181)

## PROPOSED stamps

- PROPOSED · HD3 (E27-D03 L277)
- PROPOSED · HD5 (E27-D03 L279)
- PROPOSED · HD10 (E27-D03 L284)
- PROPOSED · D03-C6 (E27-D03 L2662)
- PROPOSED · HD4 (E27-D03 L278)
- PROPOSED · BQ-6 (E27-D03 L180)
- PROPOSED · D03-C7 (E27-D03 L2663)
- PROPOSED · HD14 (E27-D03 L288)
- PROPOSED · HD6 (E27-D03 L280)
- PROPOSED · HD16 (E27-D03 L290)

## Not drawn — the text is binding

## Strings used

- e27.scr125.verdict.dated[0] — E27-D03 L2064 (refined)
- e27.cmp175.allowlist_matches[0] — E27-D03 L2461 (refined)
- 'matches' — E27-D03 (quoted)
- e27.cmp175.trade_only[0] — E27-D03 L2452 (consumed)
- e27.cmp175.verified[0] — E27-D03 L2451 (new)
- e27.scr125.row.health[0] — E27-D03 L2113 (refined)
- 'Actions' — E27-D03 (quoted)
- e27.scr125.row.actions[0] — E27-D03 L2115 (refined)
- 'Details' — E27-D03 (quoted)
- e27.scr125.row.details[0] — E27-D03 L2116 (refined)
- e27.scr125.row.age[0] — E27-D03 L2112 (refined)
- e27.scr125.table.headers[0] — E27-D03 L2107 (consumed)
- e27.scr125.table.headers[1] — E27-D03 L2107 (consumed)
- e27.scr125.table.headers[2] — E27-D03 L2107 (consumed)
- e27.scr125.table.headers[3] — E27-D03 L2107 (consumed)
- e27.scr125.table.headers[4] — E27-D03 L2107 (consumed)
- e27.scr125.table.headers[5] — E27-D03 L2107 (consumed)
- e27.scr125.table.headers[6] — E27-D03 L2107 (consumed)
- e27.scr125.group[0] — E27-D03 L2108 (refined)
- e27.scr125.group[1] — E27-D03 L2108 (refined)
- e27.scr125.table.caption[0] — E27-D03 L2106 (new)
- e27.shell.region.accounts[0] — E27-D03 L2049 (consumed)
- e27.scr125.cap.recorded[0] — E27-D03 L2165 (consumed)
- e27.shell.region.health[0] — E27-D03 L2050 (consumed)
- e27.shell.strip.rotation_due[0] — E27-D03 L2042 (refined)
- e27.shell.meta[0] — E27-D03 L2046 (refined)
- e27.shell.cta.add[0] — E27-D03 L2047 (consumed)
- e27.shell.band[0] — E27-D03 L2039 (consumed)
- e27.shell.grace.keys[0] — E27-D03 L2052 (refined)
- e27.shell.strip.title[0] — E27-D03 L2040 (consumed)
- e27.shell.h1[0] — E27-D03 L2045 (consumed)
- e27.shell.footer[0] — E27-D03 L2051 (consumed)
- e27.shell.strip.none[0] — E27-D03 L2041 (consumed)
- e27.scr125.empty[0] — E27-D03 L2117 (refined)
- e27.scr125.verdict.no_keys[0] — E27-D03 L2069 (consumed)
- e27.scr125.error[0] — E27-D03 L2118 (refined)
- e27.scr125.verdict.read_failed[0] — E27-D03 L2068 (consumed)
- e27.scr125.verdict.loading[0] — E27-D03 L2070 (consumed)
- e27.cmp175.expiring[0] — E27-D03 L2457 (consumed)
- e27.scr125.details.overdue_note[0] — E27-D03 L2157 (consumed)
- e27.scr125.details.bybit_expiry[0] — E27-D03 L2158 (refined)
- e27.shared.first_key_48h[0] — E27-D03 L2475 (consumed)
- e27.scr125.row.health_none[0] — E27-D03 L2114 (new)
- e27.scr125.menu.items[0] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[1] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[2] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[3] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[4] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[5] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[6] — E27-D03 L2140 (consumed)
- e27.scr125.menu.items[7] — E27-D03 L2140 (consumed)
- e27.scr125.menu.ask.keys[0] — E27-D03 L2141 (refined)
- e27.scr125.menu.ask.label[0] — E27-D03 L2142 (refined)
- keys.test_throttled — E27-D03 L2491 (T2 reason key)
- e27.shared.cancel[0] — E27-D03 L2471 (consumed)
- e27.scr125.test.buttons[0] — E27-D03 L2175 (consumed)
- 'Tested at 14:03:10 UTC; the next test can run at 14:04:10 UTC.' — E27-D03 (quoted)
- e27.scr125.test.title[0] — E27-D03 L2173 (refined)
- e27.scr125.test.before[0] — E27-D03 L2174 (unchanged)
- e27.scr125.test.result[0] — E27-D03 L2176 (new)
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
- e27.checks.rest_probe[0] — E27-D03 L2099 (refined)
- e27.checks.ws_probe[0] — E27-D03 L2100 (consumed)
- e27.scr125.test.passed[0] — E27-D03 L2177 (new)
- e27.shared.close[0] — E27-D03 L2472 (consumed)
- e27.scr125.cap.unrecorded[0] — E27-D03 L2166 (consumed)
- e27.scr125.cap.unavailable[0] — E27-D03 L2167 (consumed)
- e27.scr125.chip.degraded[0] — E27-D03 L2131 (consumed)
- e27.cmp175.withdrawal_detected[0] — E27-D03 L2454 (consumed)
- e27.scr125.blocked.line2[0] — E27-D03 L2163 (refined)
- e27.scr125.blocked.action[0] — E27-D03 L2164 (consumed)
- e27.scr125.verdict.failed[0] — E27-D03 L2066 (refined)
- e27.scr125.verdict.audit_hint[0] — E27-D03 L2071 (refined)
- e27.shell.banner.key_failed[0] — E27-D03 L2054 (consumed)
- e27.shell.strip.withdrawal[0] — E27-D03 L2044 (new)
- keys.compromise_path — E27-D03 L2492 (T2 reason key)
- e27.scr125.details.allowlist[0] — E27-D03 L2162 (refined)
- e27.shared.copy[0] — E27-D03 L2469 (consumed)
- e27.cmp175.ip_missing[0] — E27-D03 L2455 (new)
- 'none set' — E27-D03 (quoted)
- e27.cmp175.ip_mismatch[0] — E27-D03 L2456 (consumed)
- 'no match' — E27-D03 (quoted)
- e27.scr125.chip.down[0] — E27-D03 L2128 (consumed)
- e27.scr125.details.key_refused[0] — E27-D03 L2159 (refined)
- e27.scr125.details.degraded[0] — E27-D03 L2160 (new)
- e27.scr125.details.down[0] — E27-D03 L2161 (refined)
- keys.kek_unavailable — E27-D03 L2489 (T2 reason key)
- e27.shared.kek_notice[0] — E27-D03 L2474 (consumed)
- e27.scr125.verdict.unavailable[0] — E27-D03 L2067 (consumed)
- e27.shell.banner.kek[0] — E27-D03 L2053 (consumed)
- e27.scr128.rate_budget[0] — E27-D03 L2297 (refined)
- e27.scr128.status[0] — E27-D03 L2300 (refined)
- e27.scr128.status[1] — E27-D03 L2300 (refined)
- e27.scr128.status[2] — E27-D03 L2300 (refined)
- e27.scr128.status[3] — E27-D03 L2300 (refined)
- e27.scr128.row.actions[0] — E27-D03 L2301 (refined)
- e27.scr128.table.caption[0] — E27-D03 L2298 (new)
- e27.scr128.table.headers[0] — E27-D03 L2299 (refined)
- e27.scr128.table.headers[1] — E27-D03 L2299 (refined)
- e27.scr128.table.headers[2] — E27-D03 L2299 (refined)
- e27.scr128.table.headers[3] — E27-D03 L2299 (refined)
- e27.scr128.table.headers[4] — E27-D03 L2299 (refined)
- e27.scr128.table.headers[5] — E27-D03 L2299 (refined)
- e27.scr128.table.headers[6] — E27-D03 L2299 (refined)
- e27.scr128.table.headers[7] — E27-D03 L2299 (refined)
- e27.scr128.test_note[0] — E27-D03 L2302 (refined)
- e27.scr128.policy.encrypted[0] — E27-D03 L2306 (refined)
- e27.scr128.policy.write_only[0] — E27-D03 L2307 (refined)
- e27.scr128.policy.backups[0] — E27-D03 L2308 (unchanged)
- e27.scr128.policy.allowlist[0] — E27-D03 L2309 (refined)
- e27.scr128.policy.withdrawal[0] — E27-D03 L2310 (refined)
- e27.scr128.policy.rotation[0] — E27-D03 L2311 (refined)
- e27.scr128.policy.kek[0] — E27-D03 L2312 (consumed)
- e27.scr128.policy.h3[0] — E27-D03 L2305 (consumed)
- e27.scr128.off_by_policy[0] — E27-D03 L2304 (refined)
- e27.scr125.test.passed_read_only[0] — E27-D03 L2178 (unchanged)
- e27.scr128.card.step3[0] — E27-D03 L2324 (consumed)
- e27.scr128.card.step3.button[0] — E27-D03 L2325 (consumed)
- e27.scr128.card.step3.note[0] — E27-D03 L2326 (consumed)
- e27.scr128.card.h2[0] — E27-D03 L2318 (refined)
- e27.scr128.card.close[0] — E27-D03 L2319 (consumed)
- e27.scr128.card.step1[0] — E27-D03 L2321 (refined)
- e27.scr128.card.step1.button[0] — E27-D03 L2322 (refined)
- e27.scr128.card.step2[0] — E27-D03 L2323 (refined)
- e27.shared.bybit_note[0] — E27-D03 L2473 (refined)
- e27.scr128.card.step4[0] — E27-D03 L2327 (refined)
- e27.scr128.card.step5[0] — E27-D03 L2328 (consumed)
- e27.scr128.card.step5.button[0] — E27-D03 L2329 (consumed)
- e27.scr128.card.lead[0] — E27-D03 L2320 (refined)
- e27.scr128.card.tail[0] — E27-D03 L2330 (consumed)
- e27.scr128.card.marker[0] — E27-D03 L2331 (refined)
- e27.scr128.card.refused[0] — E27-D03 L2332 (refined)
- e27.scr128.card.refused.next[0] — E27-D03 L2334 (refined)
- e27.scr128.card.dead[0] — E27-D03 L2335 (refined)
- e27.scr128.card.containment[0] — E27-D03 L2336 (refined)

## Kit choices and deviations

- kit choice (glyphs): glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS GLYPHS)
- kit choice (chrome): The consumed chrome (CMP-072 TopBar, CMP-071 NavRail, CMP-209 RightRail, CMP-208 StatusBar; §3.1 block A) is drawn as placeholders at its redline geometry with the environment badges; it is consumed and never redrawn (§2.6)
- kit choice (cell): Each frame is a CELL: a caption row (the frame's exact §0 name in type.ui.heading-sm, then its PROPOSED stamp), the frame nested under its E27-D02 name, then its annotation-layer row (the 'not yet served' strips and notes; never inside the frame, never product UI)
- kit choice (focus): A focus ring is CMP-039's 2 px color.focus.ring stroke on a wrapper 2 px outside the control
- kit choice (t2): T2 per §10.1: 2a inline everywhere; CMP-079 wraps the control; the CMP-019 lock LEADS the full label; label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary; a filled control loses its fill (color.surface.raised + 1 px color.border.default); never color.text.disabled, never opacity.disabled
- kit choice (strip): A 'not yet served — {gap}, {owner}' strip is board annotation (§0 L199-200): a warning-stroked pill on the cell's annotation layer, never inside the frame
- kit choice (page): mkcall4.py derives a page from the board name ('E27-D03 / NN …' -> 'E27-D03'); the sheet carries its page in sheet['page'] and the renderer passes --page 'E27-D03 Accounts and key vault hi-fi'
- kit choice (split): A frame whose JSON exceeds the section budget is split across sections under its name with '∕' (U+2215) for '/' (cvsheet splits section paths on '/'); the drawer renames it after the board's last section (live check)

## Tokens and fallbacks

- fallback: the per-set file holds only the local icons locked, arrow-up, arrow-down, close and drag-handle; CMP-175's class glyphs are drawn so each class keeps its own SHAPE (BQ-6: the shape is the carrier): check = text glyph ✓, triangle = text glyph ⚠, octagon = a 16 px square with clipped look (radius.control) filled in the class token holding a '!' (cvsheet has no polygon), clock = a stroked ring with two hands, dash = a 10 x 2 bar, info = a stroked ring holding 'i', slashed circle = text glyph ⊘; plus, chevron, more and copy are text glyphs (+ ▾ ⋮ ⧉)
- token: CMP-075's radius.pill is a Tier-1 primitive (§3.1 block I names it; validator WARN)
- fallback: no typography token carries font.weight.bold at caption / body size; the critical word (BQ-6) binds type.ui.label (medium) and keeps its other carriers — 'BLOCKED' first, the octagon and the 2 px border.thick color.status.danger.strong border; the LIVE pill's bold word likewise (§3.1 block I)
- token: control heights bind the Tier-1 size.control.compact (24) / size.control.comfortable (32) (BQ-4, HD12: the admin screens comfortable, SCR-079 compact; the semantic size.control.height resolves through the active density set, so the boards bind the mode's own primitive; validator WARN)
- fallback: CMP-015's skeleton is a static bar in color.surface.hover (reduced-motion form, §2.5)
- token: the CMP-039 ring (2 px color.focus.ring, its offset) binds radius.md (6 px) on a wrapper 2 px outside the control (validator WARN)
- fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file's local 'icon / locked'
- token: opacity.scrim is a Tier-1 primitive (validator WARN): the modal scrim under CMP-046 / CMP-043
- fallback: the blocked record's 4 px inline-start rule (§2.2; 4 px is space.1, no border.* width is 4) is a 4 px rect in color.status.danger.strong at the row's start edge

## Copy gaps

- SCR-125 / loading and error: e27.scr125.error's {detail} is the server's text and no pinned doc gives an example, so the frame draws the slot '{detail}' as the deck writes it (never an invented reason)

## Sources

- spec docs/design/E27/E27-D03.md at 1983363fa md5 f386f58eeeb8aaadc18696c0ceba3e81 (frozen copy E27-D03@1983363fa.md)
- spec docs/design/E27/E27-D03-handoff.md at 1983363fa md5 4036e46f59e34d55af53cfa4480bdc15 (frozen copy E27-D03-handoff@1983363fa.md)
- spec docs/design/E27/E27-D02.md at 1983363fa md5 ec56733e286dd5cf2f7d0282d24ba9b2 (frozen copy E27-D02@1983363fa.md)
- Penpot file 'E27-D03 boards', page 'E27-D03 Accounts and key vault hi-fi'; kit e27d03kit.py md5 241e3b7d5bda4f99f4e0d1a3023aa720; renderer cvsheet-v4.3.js
- CMP-175 aggregate dated: E27-D03 L386
- CMP-176 state slot 'OK': E27-D03 L525
- CMP-175 allowlist matches: E27-D03 L319
- CMP-175 trade-only: E27-D03 L309
- CMP-175 verified: E27-D03 L308
- CMP-087 / the accounts route in the admin shell: hi-fi row E27-D03 L1079 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L922
- SCR-125 / ok: hi-fi row E27-D03 L1080 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L927
- CMP-175 aggregate no keys: E27-D03 L391
- SCR-125 / empty: hi-fi row E27-D03 L1081 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L928
- CMP-175 aggregate read failed: E27-D03 L390
- CMP-175 aggregate loading: E27-D03 L392
- SCR-125 / loading and error: hi-fi row E27-D03 L1082 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L929
- CMP-176 state slot 'Rotation due in {n} d': E27-D03 L521
- CMP-176 state slot 'Bybit expiry in {n} d': E27-D03 L522
- CMP-175 expiring: E27-D03 L315
- SCR-125 / key expiring (<14 d): rotation due and Bybit expiry: hi-fi row E27-D03 L1083 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L930
- CMP-176 state slot 'No key — inactive': E27-D03 L523
- SCR-125 / within Bybit's 48 h new-key restriction: hi-fi row E27-D03 L1084 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L931
- CMP-203: E27-D03 L909
- SCR-125 / row menu and Test: hi-fi row E27-D03 L1085 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L932
- SCR-125 / at the sub-account cap: hi-fi row E27-D03 L1086 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L933
- CMP-176 state slot 'Degraded — REST only': E27-D03 L520
- CMP-176 state slot 'BLOCKED — fund right found': E27-D03 L511
- CMP-175 withdrawal-detected (critical): E27-D03 L312
- CMP-175 aggregate failed: E27-D03 L388
- SCR-125 / withdrawal permission detected: blocking error: hi-fi row E27-D03 L1087 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L934
- CMP-176 state slot 'IP allowlist: none set': E27-D03 L514
- CMP-175 IP-missing: E27-D03 L313
- CMP-176 state slot 'IP allowlist: no match': E27-D03 L514
- CMP-175 IP-mismatch: E27-D03 L314
- SCR-125 / IP whitelist missing or mismatched: hi-fi row E27-D03 L1088 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L935
- CMP-176 state slot 'Key refused by Bybit': E27-D03 L512
- SCR-125 / key invalid: hi-fi row E27-D03 L1089 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L936
- CMP-176 state slot 'Down — order entry off for this account': E27-D03 L515
- SCR-125 / health degraded and down: hi-fi row E27-D03 L1090 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L937
- CMP-028 KEK notice: E27-D03 L705
- CMP-175 aggregate unavailable: E27-D03 L389
- SCR-125 / KEK unavailable: hi-fi row E27-D03 L1091 (3.4 The hi-fi rows); E27-D02 §7 E27-D02 L938
- SCR-128 / key table and the secrets-at-rest policy: hi-fi row E27-D03 L1381 (6. SCR-128 — Key health and secrets policy); E27-D02 §7 E27-D02 L963
- CMP-176 state slot 'Rotation overdue': E27-D03 L519
- SCR-128 / overdue rotation: hi-fi row E27-D03 L1382 (6. SCR-128 — Key health and secrets policy); E27-D02 §7 E27-D02 L964
- CMP-176 state slot 'Off by policy': E27-D03 L516
- SCR-128 / Test passed while trading is read-only: hi-fi row E27-D03 L1383 (6. SCR-128 — Key health and secrets policy); E27-D02 §7 E27-D02 L965
- SCR-128 / KEK unavailable: one panel notice: hi-fi row E27-D03 L1384 (6. SCR-128 — Key health and secrets policy); E27-D02 §7 E27-D02 L966
- SCR-128 / mark as compromised: the ordered card: hi-fi row E27-D03 L1385 (6. SCR-128 — Key health and secrets policy); E27-D02 §7 E27-D02 L967
- SCR-128 / compromise card: the revoke refused: hi-fi row E27-D03 L1386 (6. SCR-128 — Key health and secrets policy); E27-D02 §7 E27-D02 L968
- SCR-128 / compromise card: after the Bybit delete, the account reads dead: hi-fi row E27-D03 L1387 (6. SCR-128 — Key health and secrets policy); E27-D02 §7 E27-D02 L969

## Shape count

- {"sheet": "04-scr-125-128-accounts.json", "shapes": 5933, "texts": 2251, "by_type": {"board": 2975, "ellipse": 151, "icon": 8, "rect": 548, "text": 2251}, "sections": 246, "bytes": 925650, "largest_section": 11991, "largest_compacted": 8530}
