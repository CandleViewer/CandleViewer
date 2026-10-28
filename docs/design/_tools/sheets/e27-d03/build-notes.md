# E27-D03 (#816) — accounts and key-vault hi-fi boards: build notes (binding for board authors, builders, reviewers)

Source of truth: the MERGED `docs/design/E27/E27-D03.md` (3,072 lines), its handoff `E27-D03-handoff.md` and
E27-D02 `docs/design/E27/E27-D02.md` (the frame inventory, its "## 7. State inventory") on `origin/main` at
`1983363fa` (never edited), read by the kit from a frozen copy in `spec/` if present, else with
`git show 1983363fa:<path>`, and pinned by md5 in `e27d03kit.DOCS`:

| Key     | Doc                   | Repo path                            | Frozen copy                         | md5                                |
| ------- | --------------------- | ------------------------------------ | ----------------------------------- | ---------------------------------- |
| d03     | the spec              | `docs/design/E27/E27-D03.md`         | `spec/E27-D03@1983363fa.md`         | `f386f58eeeb8aaadc18696c0ceba3e81` |
| handoff | its handoff           | `docs/design/E27/E27-D03-handoff.md` | `spec/E27-D03-handoff@1983363fa.md` | `4036e46f59e34d55af53cfa4480bdc15` |
| d02     | the wires (inventory) | `docs/design/E27/E27-D02.md`         | `spec/E27-D02@1983363fa.md`         | `ec56733e286dd5cf2f7d0282d24ba9b2` |

Every `Lnnn` below and in the kit is a line of the frozen copy. Never `cat` the spec (3,072 lines, very wide tables):
use the kit's CLI (`boards`, `frame`, `deck`) or `grep -n` / `sed -n` windows piped through `cut -c1-400`. Read, per
board: §0 (L192-247, binding), the BQ table (L166-190, all RULED) and §1.2's HD1-HD17 (L268-291, PROPOSED), then
the hi-fi rows of your frames (§2.6 L933-945, §3.4 L1072-1092, §4.3 L1178-1200, §4.4 L1201-1227, §5 L1228-1304,
§6 L1305-1388, §7 L1389-1480, §8 L1481-1565), §2's component sections for every CMP your rows name, §9's matrix
(L1566-1825) for the pair ids a row cites, §10.1 (L1828-1859, the T2 rule) and §12 (the deck, L2003-2611). The
spec's audit tool `docs/design/_tools/e27_d03_hifi_audit.py` is read-only context: never run it against the sheets.
The lane's standing T2 gate applies to every board.

The kit is `e27d03kit.py`: `python3 -I -B e27d03kit.py selftest` must end `OK: 0 failing check(s)` (158 checks: the
three md5s and a WARN if main moved; BOARDS = §0's ten = the brief's; the page name as §0 L194; the twins; 75 frames
on the dark boards, none twice; the 78-frame inventory and its 3 undrawn SCR-019 frames; 78 hi-fi rows whose Board
cell names each frame's board and twin; 20 "shows T2" frames; 327 deck rows; 15 reason keys of <= 60 characters;
CMP-175's 13 variants on their deck keys; the 8 aggregate forms; CMP-176's 16 state words; the fixtures; the decision
ids; the 6 "not yet served" gaps; PAIRS; the renderer; §9's 60 pair ids; every kit token in token-sync.json; 21
refusals; then it builds one cell per surface and shared piece, writes and validates `00-selftest.json`, compacts it
into `v4/` and writes `00-selftest.md`). Never draw `00-selftest`; never edit another set's kit.
CLI: `… boards [NN]` (a board's frames with their hi-fi line and T2 flag), `… frame '<name>'` (one frame's hi-fi row,
condensed, and its inventory line), `… deck <prefix>` (deck ids and strings), `… report|compact <sheet.json>`.

## 1. Pipeline (as E05-D02 / E27-D02)

1. OFFLINE, one generator per board, `gen/gen_NN.py`: `sys.dont_write_bytecode = True; sys.path.insert(0,
KIT_DIR); import e27d03kit as k`. Per frame: `k.frame(name, build, strips=[(gap, what)], notes=[…],
proposed=[ids])` where `build()` returns the surface builder's kwargs (or the frame node itself, named exactly
   `name`); the board `k.board(nn, cells, source="E27-D03 §… Lnnn-mmm", notes=[…], not_drawn=[…], cols=N)`; then
   `k.write_sheet(k.KIT_DIR / f"{k.stem(nn)}.json", bd)`, `k.compact_sheet(path)`, `k.write_board_md(nn, bd,
checks=[…], live=[…])`. Extra non-frame evidence (CVD strips on 01, the CMP sets on 03, everything on 10) is a
   `k.specimen(title, kids)` cell; board() counts only frame cells against §0.
2. The twins: `gen_02.py` imports `gen_01`'s cell builder and calls `k.board(2, cells, …)` (same frames, same names,
   same tokens; `gen_05.py` likewise from `gen_04`). board() requires exactly the dark board's frames and logs kit
   choice `light`; the .md's line 3 says `theme light.`
3. `write_sheet()` refuses: a frame text that `copy()` / `copies()` / `reason()` / `say()` / `fixture()` did not issue
   (invented copy = BLOCKER; record a missing string with `k.gap()`); a stamp or "not yet served" strip INSIDE a frame;
   a text-free board without `h`; a hug board holding text inside a non-flex board; a node inside a non-flex board
   without `x`/`y` (v4.3 puts it at the parent origin: use `k.at(n, x, y)`); `color.text.disabled` /
   `opacity.disabled` anywhere (§10.1, §2.2: never dimmed); an `inst` node or an icon outside `k.ICONS`. `cell()`
   refuses a frame name outside E27-D02 §7 and a frame that draws T2 where §7 says it does not (or misses it where §7
   says "shows T2": name every gated node `T2 …`, as `t2_button`, `t2_radio`, `menu_item(reason_key=…)` do).
   `fit_row()` refuses a fixed-width footer row narrower than its children (a full-intent label never clips).
   Sections: `SECTION_BUDGET` 12,000 bytes json.dumps; a frame too big for one section is renamed with `∕` (U+2215)
   for `/` and its live check says to rename it after the board's last section. The validator
   (`../tools/validate_sheet.py --components ../tools/components.offline.json`) must exit 0 (WARNs for the Tier-1 primitives the
   kit names in FALLBACKS are expected).
4. COMPACT: `k.compact_sheet(path)` runs `../tools/compact.py` into `v4/<same name>`, checks `compactOf`, the
   page key and that no compacted section passes `COMPACT_MAX` (9.5 KB).
5. LIVE (a later step, never in this lane): renderer `../lib/cvsheet-v4.3.js` over cvlib v8, one section per call, then
   `touchTexts` + `relayout` + the pads fix (`S.report`), every live check in the sheet notes and the .md (frame
   renames first), then the PNG at 1x; boards 01 and 02 also get `-greyscale`, `-deuteranopia`, `-protanopia`
   renders through `docs/design/_tools/cvd_sim.py` (BQ-16). **Pass `--page 'E27-D03 Accounts and key vault hi-fi'`
   to `mkcall4.py`**: its default page for "E27-D03 / NN …" would be "E27-D03" (kit choice `page`).

## 2. File, page, boards

- **Penpot file `E27-D03 boards`** (the per-set file, not the shared DS file). It holds NO library component; only the
  local icons `locked`, `arrow-up`, `arrow-down`, `close`, `drag-handle` (`k.ICONS`). No `inst` node anywhere.
  CMP-175's class glyphs keep their SHAPES (BQ-6: the shape is the carrier) via `k.glyph(kind, colour)`: check `✓`,
  triangle `⚠` (text glyphs), octagon = a 16 px `radius.control` square in the class token holding `!`, clock = a
  stroked ring with two hands, dash = a 10 × 2 bar, info = a stroked ring holding `i` (primitives), slashed circle
  `⊘`, plus `+`, chevron `▾`, more `⋮`, copy `⧉`; lock = the local `icon / locked` (FALLBACKS GLYPHS, LOCK).
- **One page `E27-D03 Accounts and key vault hi-fi`** (§0 L194, 36 characters), created by name at the boards step and
  its id recorded then. The ten boards sit side by side on it, `x = (NN − 1) × 6,400`, `y = 0` (`k.grid_xy`), in NN
  order; each board's height stays under 6,360 px (board() raises).
- **Board names** `E27-D03 / NN slug`, exactly (§0 L216-227); each board's footer is §0 L234's stamp
  `page E27-D03 · board NN · r1`; its head carries the name, `Source: …`, the theme line and `File E27-D03 boards ·
page E27-D03 Accounts and key vault hi-fi`. Exports `docs/design/E27/img/E27-D03-NN-<slug>.png` at 1:1.
- **Build order** (§0 L236-238): 01, 03, 04, 06, 07, 08, 09, 10, then the twins 02 and 05.

## 3. Boards, frames and sizes

Frame sizes (kit choices where no source gives px): admin frames 1280 × 800 at comfortable (§3.1: TopBar and
StatusBar 48, NavRail 64, RightRail 240, content 976 with 16 px padding = 944 inside, body y 48-752; band 32, rule 4,
strip 32; a frame may be taller only to draw §3.1's page continuation under the 800 px viewport line, which
`admin_frame(h=…)` marks); SCR-079 frames 1280 × 800 on SCR-010's trading host at compact, the CMP-046 drawer 480 ×
704 at x 800, y 48 (§8 L1497); CMP-043 Large dialogs 640, SCR-127's wizard 720; SCR-016 step 3 insets 800 wide
(BQ-1); Pattern frames 1280 wide documentation surfaces. Densities (BQ-4, HD12): SCR-125..129 and SCR-016
comfortable (32 px controls), SCR-079 compact (24 px) with ONE comfortable inset (`density_="comfortable"`, board 09).

### E27-D03 / 01 cmp-175-key-states — theme dark

Draws (§0 L218): every CMP-175 state in its key and aggregate forms (frame 2 nested); the CMP-011 row chips; CMP-034; the greyscale, deuteranopia and protanopia strips of the variant set. Export `docs/design/E27/img/E27-D03-01-cmp-175-key-states.png`.

| E27-D02 # | Frame (exact name)                                                           | Size                                    | hi-fi row | T2 (E27-D02 §7) |
| --------- | ---------------------------------------------------------------------------- | --------------------------------------- | --------- | --------------- |
| 2         | `Pattern / withdrawal verdict: dated, overdue, failed, unavailable, no keys` | 1280 wide, height hugging (doc surface) | L941      | —               |

### E27-D03 / 02 cmp-175-key-states-light — theme light (twin of 01: draw board 01's frames again, same names, same tokens)

Draws (§0 L219): board 01 in semantic-light. Export `docs/design/E27/img/E27-D03-02-cmp-175-key-states-light.png`.

Frames: board 01's 1, in the same order; no frame of its own (§0 reconciliation).

### E27-D03 / 03 components-and-looks — theme dark

Draws (§0 L220): CMP-176 rows (BQ-7) and their 200 % card; CMP-178 inline; CMP-203 tri-state; CMP-201 write-only; the CMP-028 KEK notice; CMP-035; CMP-066; CMP-044 rung 1 and rung 3; the T2 anatomy beside the validity look. Export `docs/design/E27/img/E27-D03-03-components-and-looks.png`.

| E27-D02 # | Frame (exact name)                                  | Size                                    | hi-fi row | T2 (E27-D02 §7) |
| --------- | --------------------------------------------------- | --------------------------------------- | --------- | --------------- |
| 3         | `Pattern / check list: passed, failed, not checked` | 1280 wide, height hugging (doc surface) | L942      | —               |
| 4         | `Pattern / T2 anatomy with the E27 state keys`      | 1280 wide, height hugging (doc surface) | L943      | shows T2        |
| 5         | `Pattern / rung 1 and rung 3 dialogs as used here`  | 1280 wide, height hugging (doc surface) | L944      | —               |

### E27-D03 / 04 scr-125-128-accounts — theme dark

Draws (§0 L221): the anatomy redline at 1280 × 800; the warnings beside BLOCKED; the LIVE and DEMO groups; SCR-128's table, policy and compromise card. Export `docs/design/E27/img/E27-D03-04-scr-125-128-accounts.png`.

| E27-D02 # | Frame (exact name)                                                          | Size                                                                           | hi-fi row | T2 (E27-D02 §7) |
| --------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | --------- | --------------- |
| 1         | `CMP-087 / the accounts route in the admin shell`                           | 1280 × 800 (admin shell, comfortable)                                          | L1079     | —               |
| 6         | `SCR-125 / ok`                                                              | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1080     | —               |
| 7         | `SCR-125 / empty`                                                           | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1081     | —               |
| 8         | `SCR-125 / loading and error`                                               | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1082     | —               |
| 9         | `SCR-125 / key expiring (<14 d): rotation due and Bybit expiry`             | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1083     | —               |
| 10        | `SCR-125 / within Bybit's 48 h new-key restriction`                         | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1084     | —               |
| 11        | `SCR-125 / row menu and Test`                                               | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1085     | shows T2        |
| 12        | `SCR-125 / at the sub-account cap`                                          | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1086     | —               |
| 13        | `SCR-125 / withdrawal permission detected: blocking error`                  | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1087     | shows T2        |
| 14        | `SCR-125 / IP whitelist missing or mismatched`                              | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1088     | —               |
| 15        | `SCR-125 / key invalid`                                                     | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1089     | —               |
| 16        | `SCR-125 / health degraded and down`                                        | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1090     | —               |
| 17        | `SCR-125 / KEK unavailable`                                                 | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1091     | shows T2        |
| 42        | `SCR-128 / key table and the secrets-at-rest policy`                        | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1381     | —               |
| 43        | `SCR-128 / overdue rotation`                                                | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1382     | —               |
| 44        | `SCR-128 / Test passed while trading is read-only`                          | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1383     | —               |
| 45        | `SCR-128 / KEK unavailable: one panel notice`                               | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1384     | shows T2        |
| 46        | `SCR-128 / mark as compromised: the ordered card`                           | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1385     | —               |
| 47        | `SCR-128 / compromise card: the revoke refused`                             | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1386     | —               |
| 48        | `SCR-128 / compromise card: after the Bybit delete, the account reads dead` | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1387     | —               |

### E27-D03 / 05 scr-125-128-accounts-light — theme light (twin of 04: draw board 04's frames again, same names, same tokens)

Draws (§0 L222): board 04 in semantic-light. Export `docs/design/E27/img/E27-D03-05-scr-125-128-accounts-light.png`.

Frames: board 04's 20, in the same order; no frame of its own (§0 reconciliation).

### E27-D03 / 06 scr-126-add-key — theme dark

Draws (§0 L223): key add with the step-up; the C-2.8 refusal (CP-5); SCR-016 step 3 as insets. Export `docs/design/E27/img/E27-D03-06-scr-126-add-key.png`.

| E27-D02 # | Frame (exact name)                                                   | Size                                                                           | hi-fi row | T2 (E27-D02 §7) |
| --------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------ | --------- | --------------- |
| 18        | `SCR-126 / register the account shell`                               | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1185     | —               |
| 19        | `SCR-126 / paste the key: write-only fields and the allowlist row`   | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1186     | —               |
| 20        | `SCR-126 / validating state`                                         | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1187     | —               |
| 21        | `SCR-126 / verified and stored: the result panel`                    | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1188     | —               |
| 22        | `SCR-126 / validation: format, duplicate UID, the sixth sub-account` | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1189     | —               |
| 23        | `SCR-126 / refused: withdrawal or transfer right`                    | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1190     | —               |
| 24        | `SCR-126 / refused: IP allowlist, Bybit refused the egress IP`       | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1191     | —               |
| 25        | `SCR-126 / refused: IP allowlist, CandleViewer's rule`               | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1192     | —               |
| 26        | `SCR-126 / refused: the other checks`                                | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1193     | —               |
| 27        | `SCR-126 / no verdict: nothing stored`                               | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1194     | —               |
| 28        | `SCR-126 / activation failed after a pass`                           | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1195     | —               |
| 29        | `SCR-126 / KEK unavailable`                                          | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1196     | shows T2        |
| 30        | `SCR-126 / step-up gate before save`                                 | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1197     | —               |
| 31        | `SCR-126 / edit mode: no key field, the key row with Rotate`         | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1198     | —               |
| 32        | `SCR-126 / edit conflict and refusals`                               | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1199     | —               |
| 72        | `SCR-016 / step 3 loading: verifying`                                | 800 wide card inset, height hugging (comfortable)                              | L1223     | —               |
| 73        | `SCR-016 / step 3 valid: verified and stored`                        | 800 wide card inset, height hugging (comfortable)                              | L1224     | —               |
| 74        | `SCR-016 / step 3 invalid: a check refused`                          | 800 wide card inset, height hugging (comfortable)                              | L1225     | —               |
| 75        | `SCR-016 / step 3 skipped: Skip for now`                             | 800 wide card inset, height hugging (comfortable)                              | L1226     | —               |

### E27-D03 / 07 scr-127-rotate — theme dark

Draws (§0 L224): rotate with the step-up; the countdown; the refused new key. Export `docs/design/E27/img/E27-D03-07-scr-127-rotate.png`.

| E27-D02 # | Frame (exact name)                                                     | Size                                                                           | hi-fi row | T2 (E27-D02 §7) |
| --------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------ | --------- | --------------- |
| 33        | `SCR-127 / stage 1: create the new key at Bybit`                       | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1295     | —               |
| 34        | `SCR-127 / stage 2: paste and confirm`                                 | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1296     | —               |
| 35        | `SCR-127 / stage 3: verifying, elapsed time per stage`                 | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1297     | —               |
| 36        | `SCR-127 / stage 3 refused: nothing changed, the old key still active` | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1298     | —               |
| 37        | `SCR-127 / stage 3 no verdict: nothing changed`                        | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1299     | —               |
| 38        | `SCR-127 / stage 4: switched, the 900 s overlap`                       | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1300     | —               |
| 39        | `SCR-127 / stage 5: old key revoked here, delete it at Bybit`          | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1301     | —               |
| 40        | `SCR-127 / not yet served: drain read, rollback, early revoke, failed` | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1302     | —               |
| 41        | `SCR-127 / KEK unavailable: Rotate is T2`                              | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1303     | shows T2        |

### E27-D03 / 08 scr-129-confirm — theme dark

Draws (§0 L225): revoke, disable and delete; the typed label; no confirm while the summary loads. Export `docs/design/E27/img/E27-D03-08-scr-129-confirm.png`.

| E27-D02 # | Frame (exact name)                                                        | Size                                                                           | hi-fi row | T2 (E27-D02 §7) |
| --------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | --------- | --------------- |
| 49        | `SCR-129 / revoke a key that is not the last: rung 1`                     | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1467     | —               |
| 50        | `SCR-129 / revoke the last key with exposure: two choices, none selected` | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1468     | —               |
| 51        | `SCR-129 / revoke refused: a position without its stop-loss`              | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1469     | shows T2        |
| 52        | `SCR-129 / revoked: the outcome and the Bybit line`                       | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1470     | —               |
| 53        | `SCR-129 / loading the consequence summary`                               | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1471     | —               |
| 54        | `SCR-129 / disable: consequences and the typed label`                     | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1472     | —               |
| 55        | `SCR-129 / disable with exposure: two choices, none selected`             | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1473     | —               |
| 56        | `SCR-129 / exposure unknown: dead or fixable`                             | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1474     | —               |
| 57        | `SCR-129 / exchange error`                                                | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1475     | —               |
| 58        | `SCR-129 / delete (keeps history): no exposure`                           | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1476     | —               |
| 59        | `SCR-129 / delete blocked by open exposure`                               | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1477     | —               |
| 60        | `SCR-129 / delete on an account that never had a key: T2`                 | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1478     | shows T2        |
| 61        | `SCR-129 / disabled and deleted: the outcome lines`                       | 1280 × 800 (admin shell, comfortable; > 800 high only for §3.1’s continuation) | L1479     | —               |

### E27-D03 / 09 scr-079-drawer — theme dark

Draws (§0 L226): the compact host plus one comfortable inset; the Manager and Viewer legs; stale at full contrast. Export `docs/design/E27/img/E27-D03-09-scr-079-drawer.png`.

| E27-D02 # | Frame (exact name)                        | Size                                                                  | hi-fi row | T2 (E27-D02 §7) |
| --------- | ----------------------------------------- | --------------------------------------------------------------------- | --------- | --------------- |
| 62        | `SCR-079 / healthy (owner)`               | 1280 × 800 trading host, compact; the drawer 480 × 704 at x 800, y 48 | L1539     | shows T2        |
| 63        | `SCR-079 / key expiring soon`             | 1280 × 800 trading host, compact; the drawer 480 × 704 at x 800, y 48 | L1540     | shows T2        |
| 64        | `SCR-079 / key invalid`                   | 1280 × 800 trading host, compact; the drawer 480 × 704 at x 800, y 48 | L1541     | shows T2        |
| 65        | `SCR-079 / IP-whitelist mismatch`         | 1280 × 800 trading host, compact; the drawer 480 × 704 at x 800, y 48 | L1542     | shows T2        |
| 66        | `SCR-079 / stale balance`                 | 1280 × 800 trading host, compact; the drawer 480 × 704 at x 800, y 48 | L1543     | shows T2        |
| 67        | `SCR-079 / healthy (manager)`             | 1280 × 800 trading host, compact; the drawer 480 × 704 at x 800, y 48 | L1544     | shows T2        |
| 68        | `SCR-079 / healthy (viewer)`              | 1280 × 800 trading host, compact; the drawer 480 × 704 at x 800, y 48 | L1545     | shows T2        |
| 69        | `SCR-079 / viewing as a manager`          | 1280 × 800 trading host, compact; the drawer 480 × 704 at x 800, y 48 | L1546     | shows T2        |
| 70        | `SCR-079 / disabled or suspended account` | 1280 × 800 trading host, compact; the drawer 480 × 704 at x 800, y 48 | L1547     | shows T2        |
| 71        | `SCR-079 / no API key yet`                | 1280 × 800 trading host, compact; the drawer 480 × 704 at x 800, y 48 | L1548     | shows T2        |

### E27-D03 / 10 keyboard-zoom-forced-colours — theme dark

Draws (§0 L227): focus order, landmarks and live regions for SCR-125, SCR-126, SCR-127, SCR-129 and SCR-079; 125 %, 200 % and 150 %-text specimens; a forced-colours strip. Export `docs/design/E27/img/E27-D03-10-keyboard-zoom-forced-colours.png`.

Frames: none (specimen cells via `k.specimen(title, kids)`): focus order, landmarks and live regions for SCR-125, SCR-126, SCR-127, SCR-129 and SCR-079 (§11 L1918-2002); 125 %, 200 % and 150 %-text specimens (§3.6 L1108-1124, §11 R1); a forced-colours strip (§9, R2). Size: each specimen card ≤ 1280 wide.

**Not drawn — the text is binding; drawn on request** (§0 L229-235; the annotation column prints it on every board):
SCR-019's three frames (content-only rows in §8; their CMP-097 chrome is E09's, BQ-1); the light twins of boards 03
and 06-10; every high-contrast board (§9's matrix proves it, BQ-3); per-state sheets; SCR-079's comfortable frames
beyond board 09's one inset (BQ-4). Board-specific extras (e.g. a CMP set drawn on 03) go in `not_drawn=[…]`.

## 4. Cells, the annotation layer and the annotation column

- **Cell** (kit choice `cell`): the caption row (the frame's exact name, `type.ui.heading-sm`, then its PROPOSED
  stamp), the frame nested under its E27-D02 name, then its **annotation layer** row: `not yet served — {gap},
{owner}` strips and short notes. Strips and stamps are board annotation, never product UI and never inside a frame
  (§0 L199-200; write_sheet refuses). The gaps the spec writes (`k.GAPS`): `G-1, #895 / #896` (per-key facets, the
  drawer's rights and allowlist statements, the blocked row form), `G-8, #895 / #898` (the disable / delete ask
  line), `G-12, #3657` (Off by policy), `D03-G1, #896` (the egress IP and its Copy before any check, HD14),
  `G-4, #897` (SCR-127's drain read / rollback / early revoke / failed), `G-7, #898` (no side-effect-free read).
  Pass `strips=[(gap, what)]`; `what` names the target state it stamps.
- **PROPOSED stamps**: `proposed=[ids]` on the cell; ids are spec row ids only (`k.DECISION_IDS`): HD1-HD17 (every one
  PROPOSED until the owner's approval), the BQ riders still the owner's (BQ-5 stored read-only, BQ-6 critical hue,
  BQ-8's supersession of E05-D02's reveal), and the §14 rows D03-A / C / G / H / D / Q (all PROPOSED unless they say
  RULED). Stamp a frame wherever it draws a PROPOSED decision (e.g. HD3 on every CMP-176 slot, HD6 on the KEK frames,
  HD8 on the rung dialogs, HD14 with the D03-G1 strip). E27-D02's own strings stay PROPOSED there; the BQ table is
  RULED (its defaults are drawn unstamped).
- **Annotation column** (400 px, `color.surface.canvas` card, beside the grid): Sources (the spec @ 1983363fa, §0's
  board row, the frames' hi-fi row lines, then `sources=`), PROPOSED stamps (per cell), Not yet served (every strip on
  the board), Not drawn (§0's set + `not_drawn=`), Kit choices (the keys used), Notes (`notes=`).

## 5. Copy, fixtures and tokens

- Inside a frame every string comes from the deck: `k.copy(id, i=0, **fills)` / `k.copies(id, **fills)` (§12.1's 327
  rows; a fill kwarg writes `:` as `_`: `hh_mm="14:02"` fills `{hh:mm}`, `m_ss="02:14"` fills `{m:ss}`),
  `k.reason(key, **fills)` (§12.2's T2 reasons), `k.say(chars)` (a string a hi-fi row quotes outside the deck, found
  in the pinned E27-D03 / handoff / E27-D02 text) or `k.fixture(v)`. Fill values must be fixtures, numbers, UTC times,
  dates or pinned strings. Fixtures only (L62-65): LIVE `Main` 1234567, `sub_001` 1234568, `sub_002` 1234569; DEMO
  `demo-1` 9000001; users `alex`, `bea`; key ids `...a1b2`, `...c3d4`, `...e5f6`, `...a7b8`, `...d9e0`; addresses
  `203.0.113.10`, `198.51.100.7`. Every time reads UTC. The deck wins where a hi-fi row paraphrases (HD15). The copy
  gate's banned words (§12.1 L2017-2020: "reveal", "irreversible", "permanently", "step-up", "re-authentication",
  "Bybit says", "n/a"; "OFF" only beside its verified time) never appear.
- Hi-fi row readers: `k.hifi(name)` (the row's cells by header), `k.hifi_tokens(name)` (the tokens it cites, directly
  or through a §9 pair id; 13 rows read "as §3.1" / "as frame N" — take that anatomy's), `k.hifi_copy_keys(name)` (the
  deck ids it cites), `k.hifi_t2(name)`; `k.PAIRS9[id]` gives a §9 pair's fg / bg.
- Tokens are exact Penpot names; light binds the same names through `semantic-light` (the twins), never a hand-picked
  colour. Fallbacks (FALLBACKS, printed per board): BOLD (no bold typography token: the critical word and the LIVE
  word bind `type.ui.label`, their other carriers kept), DENSITY (`size.control.compact` / `.comfortable` primitives),
  PILL (`radius.pill`), RING (`radius.md`), OPACITY (`opacity.scrim`), RULE4 (the blocked row's 4 px rule as a rect),
  SKELETON, LOCK, GLYPHS.

## 6. Shared pieces (e27d03kit)

| Piece                                                                                                                                          | Kit call                                                                                                                                                                                                                         | Source                |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| CMP-087 admin shell (TopBar with DEMO / LIVE badges, NavRail, RightRail, StatusBar, band + grace, 4 px rule, strip, PageHeader, footer marker) | `admin_frame(name, content=, verdict=, notices=, banners=, strip_items=, grace=, meta=, primary=, overlays=, h=)`, `band()`, `strip()`, `strip_item()`, `page_header()`, `section_heading()`, `footer_marker()`, `add_account()` | §3.1 L973-1008        |
| CMP-092 blocking banner                                                                                                                        | `banner("e27.shell.banner.kek")`                                                                                                                                                                                                 | §3.1 block B          |
| CMP-175 badge / inline                                                                                                                         | `cmp175(variant, form, lead=, **fills)` (13 variants, `k.CMP175`)                                                                                                                                                                | §2.1 L295-464         |
| CMP-175 aggregate (the verdict line)                                                                                                           | `verdict_line(form, **fills)` (dated, overdue, failed, unavailable, read failed, no keys, loading, cleared)                                                                                                                      | §2.1 L380-393, §3.1 E |
| CMP-176 state slot / CMP-011 chip                                                                                                              | `state_badge(word, **fills)` (§2.2's 16 words), `chip(word, tone, glyph)`                                                                                                                                                        | §2.2 L498-528         |
| CMP-075 DEMO / LIVE pill                                                                                                                       | `env_pill("LIVE" or "DEMO")`                                                                                                                                                                                                     | §3.1 I, §3.5          |
| CMP-034 masked id                                                                                                                              | `masked_id("...a1b2")`                                                                                                                                                                                                           | §2.3, HD5             |
| CMP-001 buttons, focus                                                                                                                         | `button(label, variant, state)` (primary, secondary, ghost, destructive; default, hover, focus, busy, t2, validity), `focus_ring(n)`                                                                                             | §2.4, §10.1           |
| T2 lock + reason (CMP-079)                                                                                                                     | `t2_button(label, reason_key)`, `t2_label()`, `t2_reason()`, `t2_radio()`, `menu_item(label, reason_key=…)`, `menu()`                                                                                                            | §10.1 L1828-1859      |
| CMP-007 / CMP-201 writeOnly fields                                                                                                             | `field(label, value, write_only=, hint=)`                                                                                                                                                                                        | HD11, §2.3            |
| CMP-203 check list                                                                                                                             | `check_list([(check, outcome, words)])`, `check_row()`                                                                                                                                                                           | §2.5 L909-932, HD17   |
| CMP-028 KEK notice / notices                                                                                                                   | `kek_notice()`, `notice(lines, tone=)`                                                                                                                                                                                           | §2.4 L705-734, HD6    |
| CMP-044 rung dialogs                                                                                                                           | `rung_dialog(title, consequences, rung=, confirm=, choices=, typed=, marker=, error=)`, `two_choices()`, `radio()`, `overlay(panel)`                                                                                             | §2.4 L761-807, HD8    |
| SCR-079 drawer chrome                                                                                                                          | `trading_frame(name, overlays=[drawer(h2, blocks, close_focused=)])`                                                                                                                                                             | §8 L1481-1536         |
| Pattern / inset / specimen surfaces                                                                                                            | `doc_frame()`, `inset_frame()`, `specimen()`                                                                                                                                                                                     | §2.6, §4.4, §0 L227   |
| annotation layer                                                                                                                               | `not_served(gap, what)`, `proposed_stamp(ids)` via `frame(…, strips=, proposed=)`                                                                                                                                                | §0 L199-200           |

Glyph and size helpers: `glyph(kind, colour)`, `tglyph()`, `lock()`, `caption()`, `pill()`, `fit_row()`, `at()`,
`place()`, `density("compact")`, `dens()`.

## 7. Parallel board authors (PAIRS)

Five pairs, one author each: **01-02** (CMP-175 states and its light twin), **03-10** (components and looks; the
keyboard / zoom / forced-colours specimens), **04-05** (SCR-125 and SCR-128 in the accounts route and its light twin),
**06-07** (SCR-126 add key with SCR-016 step 3 insets; SCR-127 rotate), **08-09** (SCR-129 confirms; SCR-079
drawer). A twin's author writes the dark generator so the twin imports its cells. Each author writes only
`gen/gen_NN.py` and its sheets; never edits the kit (report a kit gap instead).

## Board 09 fixes after review2-08-09 (2026-10-27)

- MAJOR fixed: the SCR-079 key line (frames 62, 64-66 and the comfortable inset) now reads "Rotation due 2027-01-09 UTC",
  sub_001's date (D02:784; D03 L1381); frame 63 keeps the spec's own "Rotation due in 12 d · 2026-11-04 UTC" (L1540).
- G-11 (frame 66) and OQ-6 (frame 68) stay as plain annotation notes, not strips: the spec names no owner for either,
  `not_served()` accepts only the spec's "{gap}, {owner}" pairs, and an invented owner would be invented copy.
- The drawer header's `close` icon stays: kit-registered local icon for the spec's CMP-002 [Close].

## Live fixes not yet in the generators (SHEET-FIX, live check 2026-10-28)

The ten boards were live-checked after rendering and fixed in Penpot (E27-D03 §0, "As built"). The sheets in `v4/`
are the ones rendered; regenerate with these fixes before any redraw:

- 09 SCR-079 "Balances" CMP-036 rows: term width 118 -> 102.
- 08 "revoke refused…" T2 RbacGate radio label: auto-height, width 548; the rung-3 ConfirmDialog hugs (515).
- 07 "KEK unavailable: Rotate is T2" CMP-041 Menu: height = the last item's bottom + 4 px.
- 04 / 05 every CMP-041 Menu: height = the last item's bottom + 4 px; focus ring 280 (item 276 at +2).
- 04 / 05 "health degraded and down" CMP-011 chip: fixed 232 px, the word wraps.
- generator: the CMP-019 glyph text box is 2 px taller than its 16 px icon box (lint noise only).
