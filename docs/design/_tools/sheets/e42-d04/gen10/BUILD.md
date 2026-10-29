# E42-D04 cap10b: the ten confirmed boards, composed offline (gen10/)

Plan: `e42d04-plan.md` (main-orchestrator confirmed 2026-10-28 17:49Z). Briefs: `../brief-cap10b.md`, then
the drift fix pass `887/brief-kit.md` (2026-10-28). Outputs: `../../E42-D04-cap10b/NN-<slug>.json` + `.md`
(validator exit 0 each, `--components ../components.offline.json`), packed with `../../compact.py` into
`../../E42-D04-cap10b-v4/`. Spec of record: `design/e42-d04-boards` **cbec19a92** (md5 04dda6e1, 1,083 lines; the
carries G-1..G-39, the board cap, the CMP-044 ruling R-2 and §0 / §17 / §21 restated for these ten boards), pinned as
`gen10/pin/branch-cbec19a92.md` (Fix pass 3 below). Before it: f4418e83b (md5 8168a304, Fix pass 2),
`gen10/pin/branch-f4418e83b.md`, still read by the kit for the earlier ids' frame sizes only (IDS_PIN). **No known
drift remains**; the restatement the boards needed has landed (cbec19a92).

## How the boards are built

- `cap10.py` holds the plan (rows, frames, state ids), the layout and the annotation column; `NN-<slug>.py` (ten thin
  scripts) each call `cap10.main_one(NN)`: compose, write json + md, validate, pack. `cap10.py` only reads gen/, the kit
  and the per-board sheets.
- **Frames.** Each frame is its old board's frame node tree exactly as its generator wrote and validated it
  (`E42-D04/NN-<slug>.json`): same nodes, same sizes, same section split; only the root is renamed (`frame-1280` →
  `<state> · <size> [<old board>]`, since two old boards share a row) and given its x/y.
- **Which generator output.** Six boards were redrawn in the drift fix pass: the kit and gen_18, gen_30, gen_55, gen_59,
  gen_63 and gen_64 are re-pinned to the branch text and re-ran, writing their sheets in place (the pre-drift sheets are
  `E42-D04/NN-<slug>.{json,md}.pre-drift`). `harvest.py` + `sandbox.py` re-run every source generator in `gen10/sb/`
  on the branch pin (`harvest.json`): those six run and their fresh frames are byte-equal to the written sheets. The
  other 19 boards' frames are the recorded output of the cap era, untouched: `harvest.json.pre-drift` (the cap-era
  harvest on 1ef40f20b with the pre-drift kit) proves 02, 13, 32, 34 and 67 re-ran byte-equal then, and names why the
  rest refused (never re-pinned to the cap); on the branch pin they all refuse (their guards hold the cap's md5 or its
  wording), which is why the drift pass did not re-run them: re-pinning them would rewrite their notes' L-numbers and
  change frames the plan does not redraw. Each frame's provenance line (sheet .md and annotation) says which case.
- **Layout.** Plain (non-flex) root, `color.surface.app`, clip; 80 px margin and gutters as positions (no 80 px spacing
  token exists); frames 1:1 left to right in the plan's rows; ONE 400 px annotation column right of the widest row.
  Board name `E42-D04 / NN <slug> · <sizes> · <theme>`, page `E42-D04`, footer "page E42-D04 · board NN · r2".
- **Annotation column.** Per state: heading (state, old board), the frame names, the provenance line, then the old
  board's own annotation blocks (its "Board" and inset blocks dropped: the insets are not frames and are not on these
  boards). Boards 01, 04, 05, 06 add the focus-order overlay (keyboard rider), quoted from the pinned branch text: 01
  SCR-135 L266-275 + L102 + L600, 04 SCR-136 L322-325 + L102, 05 SCR-145 L517-519 + L102, 06 SCR-148 L561 + L102 + L600
  (numbers as at 1ef40f20b; L600 now reads R-2's "skipped while natively disabled"). Then the Board block (name →
  export, frame count, the pending restatement, ★ renders on 01, 02, 08, 09) and the footer.
- **Grid.** x = ((NN−1) mod 5) × 6000 (widest board 5,920 px). y: the row pitch is the tallest first-row board (01,
  9,183 px) plus the margin, rounded up to 100: **9,300 px** (boards 06-10 at y 9300; 9,400 before Fix pass 3 shortened
  the columns, 9,500 before the drift pass). No overlap.

## Boards (after Fix pass 3)

| NN  | slug                            | frames | frame ids → source generator                                                                                                                          | w × h       | grid          | sections | nodes (shapes est.) | validator                                                 |
| --- | ------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------------- | -------- | ------------------- | --------------------------------------------------------- |
| 01  | `scr135-populated` (dark)       | 6      | AL-2 · 1280×800 [02], AL-2 · 2560×1440 [02] ← gen_02; AL-3 [03] ← gen_03; **AL-18 [18] ← gen_18 (redrawn)**; AL-20 [20] ← gen_20; AL-21 [21] ← gen_21 | 5920 × 9183 | (0, 0)        | 89       | 2178 (~2188)        | exit 0: 0 errors, 134 warnings, 89 sections, 510581 bytes |
| 02  | `scr135-tamper-failed` (dark)   | 6      | AL-13 ×2 [13] ← gen_13; AD-5 [34] ← gen_34; AL-14 ×3 [14] ← gen_14                                                                                    | 5920 × 5048 | (6000, 0)     | 75       | 1923 (~1923)        | exit 0: 0 errors, 104 warnings, 75 sections, 442553 bytes |
| 03  | `audit-secret` (dark)           | 4      | AL-4 ×2 [04] ← gen_04; AD-3 ×2 [32] ← gen_32                                                                                                          | 4560 × 3276 | (12000, 0)    | 93       | 2113 (~2113)        | exit 0: 0 errors, 121 warnings, 93 sections, 445999 bytes |
| 04  | `scr136-detail` (dark)          | 3      | **AD-1 · 1280×800 [30], AD-1 · 2560×1440 [30] ← gen_30 (redrawn)**; AD-7 [36] ← gen_36                                                                | 5920 × 3791 | (18000, 0)    | 69       | 1528 (~1528)        | exit 0: 0 errors, 97 warnings, 69 sections, 335477 bytes  |
| 05  | `scr145-live-blocked` (dark)    | 4      | FF-2 ×2 [39] ← gen_39; FF-4 ×2 [41] ← gen_41                                                                                                          | 4560 × 3594 | (24000, 0)    | 57       | 1538 (~1538)        | exit 0: 0 errors, 84 warnings, 57 sections, 315934 bytes  |
| 06  | `scr148-on-and-dialogs` (dark)  | 5      | MM-4 ×2 [57] ← gen_57; MM-5 [58] ← gen_58; **MM-2 [55] ← gen_55; MM-6 [59] ← gen_59 (redrawn)**                                                       | 5920 × 7200 | (0, 9300)     | 26       | 693 (~693)          | exit 0: 0 errors, 18 warnings, 26 sections, 257575 bytes  |
| 07  | `motion-storyboard` (dark)      | 2      | **motion-safe storyboard [63] ← gen_63; motion-reduce twins [64] ← gen_64 (redrawn)**                                                                 | 3280 × 3585 | (6000, 9300)  | 18       | 716 (~756)          | exit 0: 0 errors, 8 warnings, 18 sections, 173062 bytes   |
| 08  | `status-sheet` (dark)           | 4      | theme columns · 4 × 1000×1728 [66] ← gen_66                                                                                                           | 4688 × 2072 | (12000, 9300) | 60       | 1560 (~1600)        | exit 0: 0 errors, 69 warnings, 60 sections, 388456 bytes  |
| 09  | `diff-sheet` (dark)             | 1      | diff-sheet · 1280×800 [67] ← gen_67                                                                                                                   | 1920 × 1885 | (18000, 9300) | 18       | 447 (~447)          | exit 0: 0 errors, 8 warnings, 18 sections, 102155 bytes   |
| 10  | `light-representatives` (light) | 3      | AL-29 [29] ← gen_29; FF-16 [53] ← gen_53; MM-9 [62] ← gen_62                                                                                          | 4640 × 4977 | (24000, 9300) | 29       | 627 (~627)          | exit 0: 0 errors, 31 warnings, 29 sections, 201258 bytes  |

**Frames: 38** (35 frame roots; board 08's container holds four). Nodes 13,323; shapes estimate about 13,413 (one per
node, about 10 per library instance: 9 instances). Board 01 is the heaviest (~2,188).

Packed (`compact.py` v4.1, `compactOf` = the cap10b json and its sha256): all ten pack exit 0, 7-19 % smaller (01 −11.2,
02 −11.2, 03 −9.8, 04 −10.6, 05 −10.9, 06 −7.0, 07 −17.4, 08 −11.1, 09 −18.6, 10 −8.1), largest section 12,858 B (board
06 `main`). `tools/v4check.py` expands every packed sheet (compact.py's expand_styles + materialize, what cvsheet v4.1
does in Penpot): each equals its cap10b sheet section for section, its compactOf sha256 matches, and the expansion
validates exit 0 (`logs/v4check-repin.log`, Fix pass 3; `logs/v4check.log` before it; the v1 validator cannot read a packed sheet directly). Re-pack after any change to
a cap10b json (mkcall4.py refuses a packed sheet whose `compactOf` file changed).

## Spec-vs-kit drift found (cap10b build)

1. **`main` lags the boards branch; no merged change postdates it.** `origin/main` has `docs/design/E42/E42-D04.md` only
   as #4193 merged it (9b5c0d8bf, md5 a58b368b, 906 lines, the pre-fold text). The boards draw the branch text.
2. _(resolved in Fix pass 2)_ The branch moved past the kit's pin (R-2 at f4418e83b).
3. _(resolved in Fix pass 2)_ Frames older than the kit's carries (G-31, G-41).
4. _(closed in Fix pass 3)_ §0 L71's not-drawn run `38–40` dropped [39]'s ★; the restated Count (L94) lists [39] among
   the earlier ★ ids, so the kit's BOARDS[39].star reads True again and SPEC_GAPS is empty.
5. _(resolved in Fix pass 3)_ **Plan vs §0 on the branch.** f4418e83b's §0 drew the earlier ten; cbec19a92 restates §0
   (L78-89) as this plan's ten, and cap10.py checks each board's slug, theme and ★ against its row.

## Fix pass 1 (2026-10-28, review findings on cap10b) — superseded

The first pass recorded six states as "known drift" (R-2 confirm look, G-31 ENV badges, G-41 pager label; the frames
drawn as recorded, the text binding) in `cap10.py`'s DRIFT table, the annotation column, the sheets' notes and the .md
files (`cap10.py.pre-drift`, `pre-drift/cap10b/`). Fix pass 2 redrew those frames instead; every "Known drift" block,
note line and .md section is gone.

## Fix pass 2 (2026-10-28, drift removed: brief `887/brief-kit.md`)

**Re-pins.**

- `e42d04kit.py` (pre-copy `e42d04kit.py.pre-drift`): SPEC is the pinned branch file (`gen10/pin/branch-f4418e83b.md`;
  the boards branch's working file is being rewritten for the restatement and moved past f4418e83b during this pass, md5
  0efc7ba8); SPEC_MD5 8168a304 (SPEC_MD5_CAP keeps 29360883); every spec L-number from L690 on re-pinned by
  `tools/linemap.py` (L1-689 kept; L694-856 +2; the R-2 C-row block inserts 19 lines after L856, so L857-937 +19; L939 on
  +21; 54 citations; the sheet.* label spans L734-735 → L736-737; the S-boards check L821-822 → L823-824); D02, D09 and
  E30 read from `gen10/pin/docs/` (`git show b7154f951`, DOCS_MD5 unchanged: the boards branch's rebase moved them). Self-test on
  the branch text: 68 PASS, 0 FAIL.
- `tools/linemap.py`: `new_line()` (the cap → the branch), `R2_EDITED` (cap lines f4418e83b re-words in place),
  `CAP_EDITED` (fold lines the cap re-words in place), `EDITED`. The generators' repin checks compose
  `repin/linemap-carries.json` (a58b368b → the fold 818bd877 = the cap's numbering) with it.
- gen_18, gen_55, gen_59 (carries era): their spec facts and anchors re-read on the branch (the cap's re-wordings and
  R-2's), their repin checks composed through linemap.py, gen_55's cap_check() extended to the branch, gen_59's E42-D03
  guard accepting e42kit's in-place 7884a33bd text; gen_59's column trimmed to its 1,632 px cap.
- gen_63, gen_64 (pre-carries): the pre-fin repin's layout is now the branch text itself (identity map); the key's D03
  pin is the merge (G-28); facts re-read; obsolete kit-fix notes and the needs_count wording replaced; the copy checks
  accept the kit's labels.* keys (G-29). gen_37 (AD-1's light twin, own mode) re-pinned the same way (facts and its
  repin composed) so gen_30 can use it.
- gen_30: replaced (old: `gen/gen_30.py.pre-drift`, the pre-carries a58b368b drawing). The new gen_30 loads gen_37 as a
  module and draws AD-1 with its own-mode builders (the folded construction; build notes: a light board is its dark
  twin's construction), with board 30's own dark column (§15's dark cells, each checked in its row).

**Kit drawing changes (R-2, D22).** `danger_confirm()`: a dialog's confirm is CMP-044's merged CMP-001 `danger`
(`color.text.on-action` on `color.status.danger.default`, no border; §20 L859-870, §15 L723); `busy()` uses the same look
for a destructive confirm in flight (MM-3); `waiting_confirm()`: a count-wait confirm is natively disabled (the
disabled attribute, skipped by Tab, never T2 or busy: D22 L157, L583, L600), drawn in E42-D03's natively disabled look
(raised fill, border.default hairline, text.tertiary label); rung state "busy" is gone ("waiting"); engage_dialog() and
maint_on_dialog() use it; the kit's own checks assert both (D22 and R-2 lines in the self-test).

**Per frame (vs `pre-drift/cap10b/`).**

| frame                                       | board | what changed                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AL-18 · 1280×800 [18]                       | 01    | [Export] confirm: `color.status.danger.default` fill, label `color.text.on-action`, no stroke (was danger.subtle, a danger.strong hairline, text.primary), R-2 note; spec L-numbers in notes re-pinned (e.g. §15 L733-734, L702-703, Appendix A L998, A-row L853-855). ENV badges were already above the scrim. 279 → 279 nodes                                                                                                             |
| AD-1 · 1280×800 [30], AD-1 · 2560×1440 [30] | 04    | redrawn with the folded AD-1: the pager's T2 pair named "Newest (T2)" / "Newer (T2)" with its one admin.newest notice after Newer (G-41; was "T2 · Newest" / "T2 · Newer"), record 1,204,118 at row 05 selected with D14's check, Previous and Next enabled (G-6, G-38; admin.page_edge in inset A only), the kit's Role cells, page text, export control and folds (G-40..G-48). 331 → 285 and 784 → 828 nodes                             |
| MM-2 · 1280×800 [55]                        | 06    | [Turn on] confirm: CMP-001 danger (R-2) and its note; the frame draws the settled count, so D22's natively disabled confirm is inset 1's (not on these boards); notes re-pinned. 137 → 137 nodes                                                                                                                                                                                                                                            |
| MM-6 · 1280×800 [59]                        | 06    | [Turn off] confirm: CMP-001 danger (R-2); the TopBar's CMP-074 and the StatusBar's CMP-075 'LIVE' badges drawn above the scrim and the card (G-31); with the carries its pre-carries sheet lacked: the markers 'Maintenance off (maintenance.disabled) + Flag changed (flags.change)' under Turn off… and in the dialog (G-8), the lead-in (G-24), CMP-040 Why?, the kit's scrim (G-43), maint.stays folded at 1280. 114 → 120 nodes        |
| motion-safe storyboard · 1280×800 [63]      | 07    | the schematic CMP-043 dialog's confirm `color.status.danger.default`, no border (R-2); schematic CMP-074 / CMP-075 'LIVE' marks above the scrim and card in M5's two key frames and M6's frame 0 (G-31; the viewport edge stands for the chrome); the nine cards in three balanced columns, each in §13's order (the folds lengthened five cells: §13's three rows no longer fit 768 px); notes re-pinned (no needs_count). 390 → 396 nodes |
| motion-reduce twins · 1280×800 [64]         | 07    | the same confirm and ENV marks in M5's twin; board 63's columns, so each twin sits where its storyboard sits; slack under the content 12 px (was 48: the reduce cells grew; the Fit live check reads the render). 235 → 237 nodes                                                                                                                                                                                                           |

**Node-identity proof.** `tools/identity.py` (`logs/identity.log`) rebuilds every frame root of the ten pre-drift sheets
and the ten new ones: **28 frame roots node-identical (json, sorted keys), 7 redrawn — exactly the seven above; 0
diffs outside them.** The real generator runs and their sandbox runs agree frame for frame (the sandbox paths aside).

**Other changes.** Annotation columns: the six states' blocks are their regenerated sheets' (board 06's column 7,051 px,
board 01's 9,061 px estimated); provenance lines name the re-run; the focus overlays quote the branch's L600. Board 07 is
3,608 px tall (was 4,184), board 04 3,860 (was 3,991), board 01 9,221 (was 9,402), board 06 7,211 (was 7,660).

## Spec restatement (finding 4): landed in cbec19a92

The branch's §0 / §17 / §21 now state these ten boards (cbec19a92): §0's table (L78-89: boards 01-10, their frames by
state and earlier id, ★ on 01, 02, 08, 09, every Status PENDING), Count (L91-97: 38 frames, 18 PNGs), the Not-drawn
list (L98-104), the keyboard rider (L105-108: the focus-order overlays on boards 01, 04, 05, 06), the ids kept in
brackets in §4, §5, §9 and §10's Board cells ("[18] `scr135-export-confirm` · board 01 (1280)"), §17's trace (L790-822)
and §21's checklist (L967-975). Fix pass 3 re-pinned to it.

## Fix pass 3 (2026-10-28, re-pin to the restated text cbec19a92)

**The line map.** `tools/linemap.py` gains `restated_line()` and `RESTATED_EDITED` (f4418e83b → cbec19a92, difflib on
the two pins; pre-copy `tools/linemap.py.pre-repin`): L1-54 kept; §0 restated, L55-60, L67-74 and L76-81 without a
line-for-line counterpart (`RESTATED_S0`: re-read by content); L61 → 67; L62-66 +6; L75 → 77; L82-870 +29; L871-930 +36
(the re-base C-row inserted after L870); L931-959 +38 (§21's two new lines); L960 on +44 (the re-base note). Proved:
every line outside `RESTATED_EDITED` is byte-equal at its mapped line, and every line in it differs. The pin is
`pin/branch-cbec19a92.md` (`git -C the boards branch show cbec19a92:docs/design/E42/E42-D04.md`, md5 04dda6e1).

**Re-pins** (each with a `.pre-repin` copy; the tools are `repin3/`): `repin3/rewrite.py` moves every E42-D04
`L<n>` / `L<a>-<b>` citation by `restated_line()`, leaves §0's for a hand re-read and lists those on re-worded lines;
`repin3/movedctx.py` lists moved citations that name an older text or another document (reverted by hand where they
were a58b368b's, E42-D03's or a description of an earlier map: gen_55 L90-91 and 2142, gen_59's two a58b368b
citations and its E42-D03 T2 comment, gen_64's three pre-fin comments, the kit's e42kit-keyed 'Admin' note).

- `e42d04kit.py`: SPEC = the cbec19a92 pin, SPEC_MD5 04dda6e1, SPEC_MD5_BRANCH 8168a304; 489 citations moved, the
  numeric line tables (LABELS spans, SRC_LINES, GROUP_LINE, the self-test's spans and indices) by `repin3/kit_nums.py`
  (two multi-line entries, `copy`/`tokens` and `maint.marker`, by hand). **The board registry is re-read from the
  restated §0:** NEW_BOARDS (the ten rows, L78-89: slug, theme, frames cell, ★, Status, ids), ON (id → board, from
  each state row's "· board NN"), Bd.on / on_1280 / drawn; ★ ids from Count (L91-97) plus a ★ board's single id, S ids
  from §18 (L852-853), light ids from the "in light" rows. **Not re-pinnable:** the earlier ids' own frame sizes
  (e.g. [14]'s three 1280 frames, [27]'s two) and the motion and proof ids' descriptions are no longer tabulated, so
  they are read from f4418e83b's §0 (`IDS_PIN`, kept beside the new pin); the self-test checks them against what the
  restated text still says. The per-id sheets' names keep the earlier per-id form (DEVIATIONS["names"]). The per-id
  Board block names the board that draws the id. Self-test: **71 PASS, 0 FAIL** (the §0 checks rewritten for the ten
  boards: rows, ids on boards vs state rows, the Not-drawn list, the 1280-only ids, 38 frames, 18 PNGs, the fold's
  18 ★ / 6 S / 4 light kept, S on boards 02, 03, 05, the name example, footer, slugs, exports). [39]'s ★ gap closed.
- gen_18, gen_37 (loaded by gen_30), gen_55, gen_59: their repin checks compose a58b368b → fold → cap → f4418e83b →
  cbec19a92 (`restated_line()`, §0 → re-read; `RESTATED_EDITED` counts as edited); anchors and FACTS re-read on the
  restated text (§0's name, frames, insets, cap and Not-drawn bullets; the state rows' "[NN] `slug` · board MM"
  cells; §17 D3, D7, E1-E6; FF-8, MM-2's "an inset on [NN]"); the old phrases kept as OLD_ANCHORS. Their notes now
  say what the restated §0 says (e.g. gen_55: [55] on board 06 with [57], [58], [59]; board 10 draws MM-4's light
  twin [62]).
- gen_30: BRANCH cbec19a92; its .md names board 04. gen_63, gen_64: PRE = the cbec19a92 pin (identity map again);
  §0's motion row is board 07's (L86), Coverage's "Board 07 draws the storyboard [63] and its reduce twins [64]",
  Count, Build order, §21's walkthrough item (L975); "board 63/64/65" prose → [63]/[64]/[65].
- `cap10.py`: PIN_SPEC / PIN_MD5 / PIN_REV cbec19a92; KEY_LINES +29 (L295-304, L131, L629; L351-354; L546-548; L590)
  and the rider's own lines (§0 L105-108); `s0_row()` reads each board's §0 row and stops unless slug, theme and ★
  match the plan; **the Board block** is "name → export (§0 L61-62, L67-69)", "§0 L<row>: <frames cell>; N frames;
  Status PENDING", the ★ renders (§0 L68-69, Count L91-97) and the keyboard rider line; SPEC_RESTATE (the pending
  restatement) is gone from the column, the notes' spec_gaps and the .md; headings name states as "AL-2 [02]";
  provenance says whose L-numbers a state's blocks carry. Footers unchanged ("page E42-D04 · board NN · r2").
- `sandbox.py`, `harvest.py`, `tools/sbrun.sh`: the cbec19a92 pin. `harvest.json` re-run (pre-copy
  `harvest.json.pre-repin`): the six re-pinned generators exit 0 with frames byte-equal to their sheets; the other 19
  refuse as before.

**Results.** The six re-ran (logs/repin-gen_NN.log): each per-id sheet's frames differ from its `.pre-repin` sheet in
node notes only (306, 301, 58, 50, 86, 59 notes); insets (not on these boards) differ in caption text (18, 55) and in
30's insets node name. `repin3/citecheck.py` pairs every text field of each sheet with its `.pre-repin` and finds every
D04 citation moved by the map except E42-D03's, other documents' and §0's (re-read). All ten boards recomposed, each
validator exit 0 (table above), packed exit 0, `tools/v4check.py` all ten True / True / exit 0
(`logs/v4check-repin.log`). **Identity** (`tools/identity.py`, now pre-repin → today, notes stripped;
`logs/identity-repin.log`; `--drift` keeps Fix pass 2's proof): **28 frame roots node-identical, 7 differ only in node
notes (557 notes: AL-18 [18], AD-1 [30] ×2, MM-2 [55], MM-6 [59], [63], [64]), 0 drawing diffs.** The only
non-annotation changes are the boards' root heights (the columns are shorter: 01 9221→9183, 02 5134→5048, 03
3385→3276, 04 3860→3791, 05 3676→3594, 06 7211→7200, 07 3608→3585, 08 2144→2072, 09 1989→1885, 10 5086→4977) and,
from the row pitch, boards 06-10's y 9400 → 9300. No sheet holds a boolean `"wrap"` (cap10b: 308 `"wrap": "wrap"`,
v4: 267; the per-id sheets none).

**Not re-pinned (on purpose).** The 19 recorded boards' carried blocks and notes keep the capped 1ef40f20b's
L-numbers (their generators still refuse; about 3,600 citations, ~1,500 on lines R-2 or the restatement re-worded),
as their provenance lines now say; their prose and the kit's and generators' own prose still call earlier ids
"board NN" in places (cap10's headings, Board blocks and the restated quotes use [NN] and the new board numbers).

## Files

- `cap10.py` (pre-copies: `cap10.py.pre-drift`, `logs/cap10.py.pre-fix`), `NN-<slug>.py` (×10; pre-copies in
  `pre-drift/`), `sandbox.py`, `harvest.py`, `harvest.json` (branch pin), `harvest.json.pre-drift` (cap-era record,
  read by cap10.provenance() for the 19 recorded boards), `pin/branch-cbec19a92.md` (the spec of record since Fix
  pass 3), `pin/branch-f4418e83b.md` (Fix pass 2's; the kit's IDS_PIN),
  `pin/E42-D04.md` (1ef40f20b), `pin/fold-8a3bc3f2d.md`, `pin/15-main.md` (`15` on main: CMP-044 / CMP-001),
  `pin/docs/` (D02, D09, E30 at b7154f951, and D01, E39, E10, E17), `tools/` (linemap.py, ed.py, framediff.py,
  identity.py, v4check.py, sbrun.sh, probe37.sh, probe_anchors.py and the ed*.txt edit scripts of this pass),
  `logs/` (real-gen_NN.log, sb2-gen_NN.log, identity.log, v4check.log), `pre-drift/` (the ten cap10b sheets and packed
  sheets before this pass), `sb/` and `sb2/` (disposable sandboxes), `v4check/` (expanded packed sheets).
- Pre-copies outside gen10: `../e42d04kit.py.pre-drift`, `../gen/gen_{18,30,37,55,59,63,64}.py.pre-drift`,
  `../NN-<slug>.{json,md}.pre-drift` for 18, 30, 55, 59, 63, 64.
- Fix pass 3: `repin3/` (rewrite.py, kit_nums.py, registry_new.py.txt, cites.py/cites.tsv, scan.py, movedctx.py,
  anchorprobe.py, factprobe.py, sheetdiff.py, citecheck.py), `pre-repin/` (the ten cap10b and packed sheets before
  it), `.pre-repin` copies of the kit, gen_18/30/37/55/59/63/64, cap10.py, BUILD.md, sandbox.py, harvest.py(.json),
  tools/identity.py, tools/linemap.py, tools/sbrun.sh, the six per-id sheets (+ 37's) and 00-selftest.json (the
  sandbox's copy), logs/repin-*.log, identity-repin.log, v4check-repin.log.

## Re-run

```
python3 -I -B gen/gen_18.py   # and gen_30, gen_55, gen_59, gen_63, gen_64 (gen_30 loads gen_37.py)
python3 -I -B e42d04kit.py selftest    # 71 PASS on the cbec19a92 pin
python3 -I -B gen10/harvest.py          # sandbox re-runs on the branch pin, writes harvest.json
for f in gen10/[01][0-9]-*.py; do python3 -I -B $f; done
python3 -I gen10/tools/identity.py; python3 -I -B gen10/tools/v4check.py
```

## Fix pass 4 (2026-10-29): no CMP-014 component in the per-set file

The live render of board 01 stopped at section 72 with "component not found: CMP-014 · Spinner": the per-set file
"E42-D04 boards" has tokens and local icons only, no catalogue components. The nine `inst` CMP-014 nodes (01 ×1,
07 ×4, 08 ×4, every one inside a loading CMP-001) are now the e42kit `SPINNER` fallback: the registry glyph `refresh`
at size.icon.sm in the button's label colour (action.secondary → text.primary; outlined → text.primary). Patched in
the cap10b json (pre copies in gen10/pre-spinner/), re-packed with compact.py; tools/v4check.py: all ten expand, match
compactOf and validate exit 0. Generators: carry the same substitution when re-run (cap10.py).
