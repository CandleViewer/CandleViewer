# E42-D03 (#886) — Penpot board sheets: build notes

**Committed form (2026-10-29).** This folder is the kit the ten E42-D03 boards (page `E42-D03`, file `E42-D03 boards`)
were built with:

- `e42kit.py` (Python 3.12+, stdlib only): the shared sheet kit. It draws the CMP-087 admin shell (TopBar, NavRail,
  band, strip, PageHeader, StatusBar, RightRail), the T2 control, buttons, fields, dialogs, the scrim and the text
  metrics, and E42-D04's kit (`../e42-d04/`) imports it read-only. Paths are repo-relative (`../tools/` for the
  validator, the components list and the token sync).
- `gen10/`: `cap10.py` (the confirmed ten-board plan, the layout and the annotation column), the ten thin board
  scripts `NN-<slug>.py` and `BUILD.md` (how the ten boards were composed, the review and live-check fix passes).
- `NN-<slug>.md` (×10): each board's sidecar.
- `v4/NN-<slug>.json` (×10): the packed sheets the boards were rendered from, byte-identical apart from
  `compactOf.file` (a bare file name). `compactOf.sha256` stays the rendered original's.

Not committed: the unpacked sheets (each `v4/` sheet expands, with `../tools/compact.py`'s inverse, to its original
section for section: checked on 2026-10-29, every original validator exit 0), the 104 per-id generators (`gen/`) and
their per-id sheets the frames were harvested from, the harvest and sandbox scripts, the spec pins (`spec/`,
`gen10/pin/`: re-create each with the `git show` its constant names), the line maps (`repin/`), logs, pre-copies and
caches. `cap10.py` writes the unpacked sheets to `cap10/` and packs into `v4/`.

The history below is the kit's own, kept as written (the per-id era, the folds, the merge and the cap); the ten boards'
build is `gen10/BUILD.md`.

## The per-id kit (#886, PR #4138): build notes as written

Source of truth: the spec `docs/design/E42/E42-D03.md` in the spec's worktree (head `782eb0e4d`, text
approved pending boards). Read §0 (boards, names, counts, build order) and §4 (CMP-087 shell, admin tint, re-auth
countdown) in full for batch 1; later batches read their screen's section (§5–§11), §12–§15 and §14's copy deck.

## The pipeline (same as E08-D07)

1. OFFLINE: each board is a JSON sheet (schema: the header of `cvsheet-v1.js`; `../lib/` vendors its successors),
   produced by a small Python generator that uses the shared kit
   `e42kit.py` (this folder), validated with `python3 -I
../tools/validate_sheet.py <sheet.json> --components
../tools/components.offline.json` (exit 0 required).
2. LIVE (later): the renderer draws one section per execute_code call; touch + relayout; export.

## Page and board frame (spec §0, binding)

- Page `E42-D03`. Board name `E42-D03 / NN <screen>/<state> · <size> · <theme>`, e.g.
  `E42-D03 / 31 SCR-121/populated · 1280×800+2560×1440 · dark`; `<size>` is `1280×800` only on boards 08 and 88.
- A state board holds BOTH sizes side by side at 1:1 (a 1280 × 800 frame and a 2560 × 1440 frame), with the
  annotation column outside the frames. Every board carries a title, its source line (the spec § and state id) and the
  footer "page E42-D03 · board NN · r1".
- Grid placement: board NN at x = ((NN − 1) mod 5) × 4600, y = floor((NN − 1) / 5) × 1800 (a 2-frame board is about
  1280 + 2560 + annotation ≈ 4400 wide and 1440 + header ≈ 1650 tall).
- Root board: flex row, align start, fill `color.surface.app`, padding `space.inset.lg`, gap `space.inset.lg`, clip
  on. Children: `frame-1280` (1280 × 800, clip), `frame-2560` (2560 × 1440, clip), `annotations` (400 wide column:
  title, source line, state id and trigger, decision ids, roles, keyboard path and focus, announcement, copy keys used,
  tokens, analytics/audit event, footer).
- Theme: dark boards are drawn once; light boards (10, 20, 29, …) are the same construction exported under the light
  token theme by the coordinator ([THEME-WINDOW]); the light board is its own board in the plan, so draw it as a copy of
  its dark twin's sheet with the name ending `· light` (the theme switch happens at export).

## Content rules

- Copy: only §14's keyed strings (verbatim) and the spec's sample data (the worked example §1); never invent a string.
- Tokens: only names in `../tools/token-sync.json`; colour/typography from the
  semantic sets; where the spec names a proposed token (DS-1..DS-3), draw the spec's fallback and annotate it.
- Library components: instance only sets that exist (components.offline.json is approximate — list every inst node in
  the sheet's `notes.live_checks`); compose the rest locally from tokens and name them `<CMP id> <Name> (composition)`.
- The admin tint and the band/strip anatomy exactly as §4 states (sizes, tokens, contrast pairs); the re-auth
  countdown per §4/§5.
- Keep each section under ~20 KB of JSON (split the 2560 frame into sub-sections: band, strip, header, content parts).

## SPEC MOVED — the standing T2 gate folds (07:1xZ, 2026-10-23): binding for every sheet from now on

- The spec is now PR #4138's head `9644f23f0` (`docs/design/E42/E42-D03.md`, md5 `b4ef3ab8aedb…`, 929 lines;
  it was md5 `92d95c06…`, 907 lines). Read it from the spec's worktree (committed).
- **Line map:** `repin/linemap.json` (not committed) maps every old line n to its
  new line (`new`), and says whether the line's content was edited in place (`edited: true` → re-read it and re-check
  what you cite). 20 old lines have no counterpart (null): find the cited fact in the new spec by content. Re-pin every
  E42-D03 citation (`L<n>`, `§x Ln`, `spec:n`) by this map; other documents' line numbers do not move; LOD or other
  `L0`-style names are not line numbers. The kit (e42kit.py) is re-pinned centrally; take its numbers as they are.
- **What the gate changed** (read the records before drawing a changed board): the fold-gate
  records fold-gate.md, fold-gate-2.md and fold-gate-3.md (not committed) ("Changed boards" lists). In short: one T2 rule now lives at
  the end of §13 (lock glyph leading the full label, the reason node per rendering: inline 2a, a menu item's second
  line, a shared panel notice, 2b for icon-only), cited "(T2, §13)" from every gated control; view-as panel notices
  (§10); UD-20 "disabled user" → NEW board 104 `scr122-disabled`; the row menu by status (§7); writes under an expired
  admin window stay T1 (SH-4, board 04 draws them enabled); busy is never T2 (CMP-002 busy trigger on 36).
- **Counts:** 104 boards, 90 dark state boards plus 08 and 88, 211 frames, 134 PNGs (§0). Board 104 sits at the grid
  slot the placement rule gives NN = 104.

## SPEC MERGED — PR #4138 merged at 58660d32f (2026-10-24): binding for every sheet from now on

- The spec is the merged text: `docs/design/E42/E42-D03.md` at main `58660d32f`, md5 `2e87d809cdb23a4cc311f21a272abf33`,
  928 lines, read from the boards branch's worktree (e42kit.SPEC). Against 9644f23f0 it edits +31/−31 lines in
  place and moves none, so every L-number above still holds; re-read the content of L26-27, L185, L304-305, L322, L335,
  L402, L592, L602, L617, L619, L655-656, L692, L750, L837, L843, L870 and L908-910 before quoting them.
- What changed (the approval's M1, M2 and Minors): a sort is an availability state, never T2 (§7 L304-305: a header
  pressed while `has_more` reads the remaining pages first, busy; a failed read keeps the rows with `users.error`
  [Retry]); `users.sorting` joins §14 L617 and `admin.sort_needs_all` is gone; CMP-049 gains `sortPending` (§16 L692,
  Appendix A L908-910); an invited / expired-invite row has no Reset two-factor (left out, not T2; §7 L322, UD-16
  L402, `users.mfa_pending` states the fact); SH-4 (L185): the expiry adds no T2, each write keeps its §13 treatment.
- Kit: e42kit.table_header(sort_pending=, sort_cleared=, focus=) draws the busy and the cleared header (never T2);
  copy() and the T2 helpers refuse admin.sort_needs_all (COPY_REMOVED); ROW_MENU['invited'] has four items; NEVER_T2
  names users.sorting and users.mfa_pending. Historical lines about the gate fold keep naming 9644f23f0.

## RULINGS 01:48Z 2026-10-24 (orchestrator, lane thread) — the four post-merge drawing choices

All four as defaulted, with two C-rows so the boards never read as deciding spec gaps:

- (31) the failed sort read's `{detail}` borrows U-6's "store unavailable" AND a C-row to E42-D03's owner: §7 names no
  detail for a failed sort read.
- (30 / U-1) headers unsorted and not busy during the first read AND a C-row: the spec does not say what a header press
  shows then (drawing nothing the spec does not define is the safe default).
- (57) the `users.mfa_pending` sentence as body text.
- (90) took the L656 change — list it in the boards PR body's delta section.
  The two C-rows go into the spec text in the boards PR (the boards branch), in place where possible.

## SPEC CAPPED (2026-10-24) — the lever-4 board cap: ten boards drawn (09, 26, 53, 57, 72, 88, 90, 91, 92, 94)

- **Spec.** `docs/design/E42/E42-D03.md` at the boards branch's HEAD `7884a33bd` (branch design/e42-d03-boards), md5
  `3f909f5f71e333b6c112f595fefaae8c`, 928 lines. Since the merged text (58660d32f, md5 2e87d809): 3f145ad47 (two C-rows),
  8e43ac137 (cap §0) and 7884a33bd (cap pass 2) edit lines in place and move none, so every L-number above still holds.
  §0 now says what is drawn (L61-69 "Drawn: …", L74 "Drawn: 10 boards, 23 frames and 20 PNGs", L75 "the five drawn
  state boards (26, 53, 57, 72 and 94)"); 104 / 211 / 134 stay "as catalogued". Every other evidence pointer to a board
  not drawn gains "not drawn — the text binds" and names a drawn board that shows the same (e.g. L701, L703, L705, L151).
- **Kit.** e42kit.SPEC_MD5 2e87d809 -> 3f909f5f, one line (L50, its comment names 7884a33bd); no line added, so
  board 94's computed `e42kit.py:2900` citation holds; kit md5 a4012ae6 -> 7c393933. Backup: e42kit.py.pre-cap.
  Self-test (`python3 -I -B e42kit.py selftest`): exit 0, 46 PASS, 0 FAIL, 0 WARN (the spec-revision line was the one
  WARN before); 00-selftest.json byte-identical. No kit quote needed re-quoting (the registry, the copy deck and the T2
  anchors stand on their lines).
- **Rule applied to the ten boards.** Visible text only: every pointer to a board the cap does not draw keeps its words
  and gains "not drawn — the text binds" (the spec's evidence-pointer words; every board that prints them proves them
  on L470, L701, L703, L705 or L151 in its facts list), naming the drawn board that shows the same where the spec does; each visible spec pin 58660d32f -> 7884a33bd (SPEC_AT /
  SPEC_HEAD maps gain 3f909f5f -> 7884a33bd). No frame content, token or layout rule changed. postcap/tools/capcheck.py:
  52 visible nodes failed before, 0 after (plus two pointers without a number, fixed by hand: 88's "on their boards",
  90's "its state board"). The nine generators that changed a pointer gained the §0 rows they rely on (L61-L67, L75)
  and the §17 rows it quotes (L151, L701, L703, L705); no check was removed or loosened.
- **Per board** (generator exit 0, validator 0 errors with the same warning counts as before, then compact.py exit 0):
  - 09: State block "light twin board 29" + ", not drawn — the text binds". Board h 1752 -> 1760 (one more annotation line; H_SLACK 48 hits
    the 1760 pitch cap, 40 px left). Notes: "spec md5 3f909f5f at 7884a33bd".
  - 26: source "spec 7884a33bd"; State "Target: OV-2, board 22 (not drawn — the text binds; 92 and 09 draw OV-2)." (L701);
    Board notes "(OV-1 is board 21, not drawn — the text binds)" and "(§17 L701; 22 not drawn — the text binds)". Board h 1752 -> 1760 (slack 72 -> 40 px,
    the live check says so).
  - 53: source "· 7884a33bd" only (nothing it draws became false). Dims unchanged.
  - 57: source "· 7884a33bd"; Board notes "(not loading: board 42, not drawn — the text binds)". Board h 1744 -> 1760 (headroom 96 kept).
  - 72: source "spec 7884a33bd"; inset 1's notes "V-1's body is va.entry.body_ro (board 69, not drawn — the text binds)." Dims unchanged.
  - 88: source "spec 7884a33bd"; State (Owner) "…drawn in CMP-087 on their boards; under the cap SCR-120's on 26 and 94,
    SCR-122's on 53 and 57, the rest not drawn — the text binds)" (§0 L63-65); Decisions "Q5 (L151): E10-D02's rail entry (board 08 draws
    both, not drawn — the text binds: SH-8; 09 and 88 draw the rail entry)". Board h 1712 -> 1752.
  - 90: State "Each treatment as its state board draws it (…; under the cap the five drawn state boards are 26, 53, 57,
    72 and 94, §0 L75, the rest not drawn — the text binds)". KIT_MD5 a4012ae6 -> 7c393933 (the kit's only change is SPEC_MD5; the helpers
    this board uses are unchanged). Dims unchanged (1720).
  - 91: source "spec 7884a33bd"; the 32 story captions that name an undrawn board (01-07, 22, 23, 24, 25, 31-41, 31, 32,
    33, 34, 35, 38, 39, 43, 51, 52, 55, 95) gain ", not drawn — the text binds"; 26 and 53 unchanged. Dims unchanged; frame-1280 still
    772 of 800 px, frame-2560 column 3 1301 -> 1314 of 1392, panel bottom 1574 -> 1587 of 1752.
  - 92: legend title and source "at 7884a33bd"; the title, the source, Copy keys and Data and budget blocks, legend rows
    A, B, I and J (px and tokens), focus stops "skip" and 14: each "board 22('s)" + "not drawn — the text binds" (source cites §17 L701);
    the legend's not-here note opens "(drawn elsewhere or, under the cap, text only; …)" and its boards 43/58, 11/28,
    01-05/07 and 23 gain "not drawn — the text binds" plus the drawn boards that show them (53 and 57 SCR-122; 53 and 91 Large dialogs;
    90 and 91 the badge and the grace line, §17 L705; 90 and 91 strip items, §17 L703; no drawn board has a Default
    480 px dialog, hence "text only"). Dims unchanged (1760 fixed): legend 824 -> 850 of 912 px, focus table 147 -> 160
    of 272, column 1610 -> 1682 of 1728.
  - 94: source "at 7884a33bd"; State "The rest: OV-2 (L276; 22 not drawn — the text binds)." (was "OV-2, as board 22 (L276)"): the column
    sits 15 px under its ANN_MAX (1656 px), so no extra line fits and L701's short form replaced "as board" (L276's
    board column names 22; facts L276, L701). Dims unchanged.
- **Compaction.** compact.py on each of the ten into ../E42-D03-v4/<same name>, exit 0; every compactOf.sha256 equals
  its source's sha256 and compactOf.file its path (re-checked after a final idempotent re-run of all ten generators).
- **Not changed, still true:** board 90's "§0 L73's 6 / 211 hold only if 91 becomes one frame (open item 1)" (the cap's
  L74 "23 frames" rests on the same assumption: 90-92 draw 3 + 2 + 2 = 7, not 6); every sheet's notes keep their
  historical pins (9644f23f0, 58660d32f) where they describe earlier rounds.
- **Not re-run:** the other 94 generators (not drawn). A board drawn on request needs this same pass first: its pins
  (SPEC_AT / SPEC_HEAD) and its visible pointers to undrawn boards.
- Snapshots, logs, edit lists and tools: postcap/ (before/, logs/, edits/, tools/: sheetdiff, texts, sim, linesim,
  capcheck, edit, wrap).

## RULINGS R-1 / R-2 (orchestrator 2026-10-25 01:30Z): CMP-138 and CMP-044 as merged; boards 90 and 91 redrawn

- **Spec.** The boards branch moved to `4babb1f62` (md5 d91202f9, 969 lines; +41 lines, so 7884a33bd's L-numbers no longer
  hold there). e42kit.SPEC now reads a frozen copy of 7884a33bd (spec/E42-D03@7884a33bd.md, md5 3f909f5f, `git show`):
  every existing pin and the kit's self-test hold unchanged. The ruled text is frozen beside it:
  spec/E42-D03@4babb1f62.md (e42kit.SPEC_RULED) and spec/15@4babb1f62.md (CAT_RULED, md5 310980c4; CMP-044
  `15:473-480` from #4414, CMP-138 `15:1576-1586` from #4134). New citations name the revision ("4babb1f62 L412",
  "`15:1580`"); `check_ruled()` proves each on its line at build time.
- **Kit.** One line edited in place (SPEC's path, same bytes) and one block appended after the self-test, so no kit
  line moves (board 94 computes `e42kit.py:2900`): SPEC_RULED / CAT_RULED, ruled_lines(), check_ruled(),
  RULED_KIT_FACTS; validity_native() (CMP-044's merged validity form: validity_button()'s look, natively disabled, out
  of the Tab order, the hint naming the first unmet input; DEVIATIONS / SRC "validity-native"); cap138_meter(),
  cap138_state(), cap138_glyph() (E39-D02's merged CMP-138: color.surface.sunken pill track, fills ok text.secondary,
  WARN warning.default, LOCK / CAP danger.default clipped at 100 %, the 1 px text.secondary 80 % tick, the danger.strong
  overflow marker, the unknown hatch; circle ok, diamond WARN (text ◆), square LOCK, bar CAP; FALLBACKS["CMP138"];
  radius.pill is a Tier-1 primitive, validator WARN). validity_button(), meter() and METER_FILL are unchanged (boards
  53 and the CMP-023 capacity meter still use them). Self-test exit 0, 00-selftest.json byte-identical. Kit md5
  063e3e3b; backup 886/extras/sheets/pre/e42kit.py.
- **Boards.** 90 and 91 only (88, 92 and 94 draw neither contract: re-run, byte-identical JSON, the old .md kept;
  09, 26, 53, 57 and 72 untouched). 90: UD-14's meter is CMP-138 OverCapAfterTightening (`15:1580`; 4babb1f62 L412),
  its §15 lines 4babb1f62's L679-680; U-8's waiting confirm validity_native(); sections re-packed by split_big()
  (every section over 12,000 B at a 12,000 B budget: 35 sections, the largest 8.2 KB compacted). 91: the CMP-138
  group draws six merged stories (Ok, NearCap, Breached, OverCapAfterTightening, Unknown, AccountScope); the CMP-044
  confirms waiting on inputs are validity_native(); the dialogs pass role="alertdialog" through `role?`. Spec §0 L84-91
  still says 90 and 91 keep the old drawing: routed in both sheets' notes (90 open item, 91 deviation "rulings").
  Record: 886/extras/sheets/notes.md.
