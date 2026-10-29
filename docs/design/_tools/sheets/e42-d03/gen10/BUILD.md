# E42-D03 (#886) cap10 — the ten confirmed boards, composed offline

Plan of record: the confirmed plan (#886 comment 6498384157), confirmed by main-orchestrator 2026-10-29 13:57Z.
Outputs (from the kit folder, `docs/design/_tools/sheets/e42-d03/`): `cap10/NN-<slug>.json` (validated with
`../tools/validate_sheet.py --components ../tools/components.offline.json`; not committed), `NN-<slug>.md` beside the
kit, and `v4/NN-<slug>.json` (packed with `../tools/compact.py`). Regenerate:
`E42D03_SOURCES=<folder> python3 -I -B gen10/NN-<slug>.py` for each board, run from the kit folder; then
`python3 -I -B gen10/tools/v4check.py` and `python3 -I -B gen10/tools/asdrawn.py` (below, Rebuild).

## Rebuild: what is committed, what is a record

A checkout rebuilds the ten boards from committed files plus one recorded input:

- **Committed and run:** the kit (`e42kit.py`, read-only here: its estimator), `gen10/cap10.py` and the ten
  `gen10/NN-<slug>.py`, `gen10/harvest.json`, `../tools/` (validator, inventory, packer), `gen10/tools/`.
- **Spec pins (no copies committed):** `cap10.py` and `e42kit.py` read a pin from `gen10/pin/` or `spec/` when the
  frozen copy is there, else with `git show` (repo-relative, read-only): boards-branch text 4babb1f62 (md5 d91202f9)
  via 4babb1f62, then this PR's 3dafe78a7 (the same bytes; 4babb1f62 was rebased away), then blob 378a4989; main
  58660d32f (md5 2e87d809, on `main`); the kit's SPEC 7884a33bd (md5 3f909f5f; this PR's 357a0b097). Every read is
  md5-checked. After the squash merge the PR commits stay fetchable as the PR's head ref (`refs/pull/4978/head`);
  58660d32f is on `main`.
- **Records, not committed:** the ten source sheets `09-tint-proof.json`, `26-scr120-trading-unknown.json`,
  `94-scr120-withdrawal.json`, `53-scr122-unbind-unknown.json`, `57-scr122-invited.json`, `72-scr124-active.json`,
  `88-role-matrix.json`, `90-status-treatments.json`, `91-components.json`, `92-redlines.json` (about 2 MB, 63,000
  lines of JSON) are read from `E42D03_SOURCES`. They are the validated outputs of the old per-board generators
  `gen_NN.py` (15,000 lines for these ten), which are not committed either: they hard-code local checkout paths in
  dozens of places, read E42-D02 and E10-D02 from a second checkout, and read `15` at 4babb1f62, which no commit on
  `main` or in this PR holds. The harvest that re-ran them (`harvest.json`, committed as the record `cap10.py` reads)
  and its runner scripts drive those generators, so the runners are not committed. 90 and 91 would regenerate with
  the CMP-015 `State` prop (drift 5 below), which `cap10.py`'s `substitute()` removes.
- **Proof (review fold, 2026-10-29):** in a fresh detached worktree, with only committed files plus the ten source
  sheets, the ten scripts regenerate `v4/` byte-identical to the committed sheets and the ten `.md` files
  byte-identical (`git status` clean but the untracked `cap10/`), and `gen10/tools/v4check.py` expands every packed
  sheet to its `cap10/` sheet, sha256 matching, validator exit 0. The same run at cf47ac05b (before this fold)
  reproduced that commit's `v4/` byte for byte. `gen10/tools/asdrawn.py` proves the committed `v4/` equals the sheets
  the boards were drawn from (cf47ac05b) section for section but the two carries (Carries below).

## Method

- `cap10.py` (shared) + one `NN-<slug>.py` per board. Each frame is the old board's frame node tree taken from the
  recorded source sheet `NN-<slug>.json` (the generator's validated output), only the root renamed
  `<state> · <size> [<old id>]` and placed by x/y; `cap10.py` re-checks that every carried tree is byte-identical to
  the recorded one apart from name/x/y. No generator, the kit or the old sheets was edited.
- The harvest (method of E42-D04's gen10): the ten source generators re-run unchanged in logic in an isolated copy
  of the kit (copied byte-identical), each board's annotation calling it "the sandbox". Result (`harvest.json`): all
  ten exit 0;
  frames byte-equal to the recorded sheet for 09, 26, 94, 53, 57, 72, 88, 92; for 90 and 91 the fresh frames equal
  the generators' own `.pre-skel` output and the recorded sheets differ only by the CMP-015 Skeleton inst's `State`
  prop, dropped after generation (live read-back) — the recorded (fixed) frames are used.
- Board: plain root (fill `color.surface.app`, clip), 80 px margin, frames 1:1 left to right in one row with 80 px
  gutters (positions, no 80 px token); the old boards' non-frame panels keep their offset under the frame they sat
  under. ONE 400 px annotation column right of the row: title, subtitle, then per old board a group (heading with the
  state ids, the frames/panels list, provenance, every old annotation block unchanged — source, state and trigger,
  decision ids, roles, keyboard path and focus, announcement, copy keys, tokens, analytics/audit, budget/insets/notes),
  the focus-order overlay on boards 04 and 06 (the plan's keyboard rider, quoted from the boards-branch text), the Board
  block (name → export, old ids, boards-branch §0 row, frame count, renders), the footer `page E42-D03 · board NN · r2`.
  Root h = max(content bottom, column bottom) + 80 (hugs the column + 80 px).
- Name `E42-D03 / NN <slug> · <sizes> · <theme>`; page `E42-D03`; file `E42-D03 boards`; grid x = ((NN−1) mod 5) ×
  6000, y = floor((NN−1)/5) × 3200 (tallest board 2964 px, widest 4640 px: no overlap, no widening needed).
- Baked-in Penpot rules (checked in `write()`; a hit refuses the board): no boolean `wrap`; no CMP-014 Spinner inst
  (none on these boards); no section over 24,000 B; no `chars` / `name` / note / board name / `.md` text matching
  `cap10.LEAK` (local paths and lane names; five carried note lines were scrubbed:
  [53] a briefs path, [57]/[72] gate-record paths, [90]/[91] the boards-branch worktree name). Packed files'
  `compactOf.file` is rewritten after packing to the bare file name (`NN-<slug>.json`, sha256 unchanged), so no
  packed file carries a local path; `../tools/mkcall4.py` resolves it against its cwd, so run it from `cap10/`.
- Spec pins: boards-branch `origin/design/e42-d03-boards` = `4babb1f62` (fetched 2026-10-29; md5 d91202f9, 969 lines;
  = the kit's frozen `SPEC_RULED`) as `gen10/pin/branch-4babb1f62.md`; main unchanged since `58660d32f` (md5
  2e87d809) as `gen10/pin/main-58660d32f.md`; neither copy is committed (Rebuild: `git show`). No re-pin of the kit or
  any generator was needed (they run on their own frozen pins: SPEC 7884a33bd, SPEC_RULED 4babb1f62).

## Boards (frame ids → source generator)

| NN  | slug                   | theme      | frames / panels (→ source)                                                                                               | §0 frames (drawn) | ★   | size        | nodes |
| --- | ---------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------- | --- | ----------- | ----- |
| 01  | tint-proof             | dark+light | OV-2 SCR-120 overview · 1280 [09], SCR-010 workspace · 1280 [09] → gen_09                                                | 4 (2)             | ★   | 3280 × 2291 | 234   |
| 02  | scr120-trading-unknown | dark       | OV-6 · 1280, OV-6 · 2560 [26] → gen_26                                                                                   | 2                 | —   | 4560 × 2173 | 403   |
| 03  | scr120-withdrawal      | dark       | OV-9 · 1280, OV-9 · 2560 [94] → gen_94                                                                                   | 2                 | ★   | 4560 × 2168 | 451   |
| 04  | scr122-unbind-unknown  | dark       | UD-12 · 1280, UD-12 · 2560 [53] → gen_53; + SCR-122 focus overlay                                                        | 2                 | —   | 4560 × 2964 | 465   |
| 05  | scr122-invited         | dark       | UD-16 · 1280, UD-16 · 2560 [57] → gen_57                                                                                 | 2                 | —   | 4560 × 2100 | 421   |
| 06  | scr124-active          | dark       | V-4 · 1280, V-4 · 2560 [72] + panel: V-4's two insets under the 1280 frame → gen_72; + SCR-124 focus overlay             | 2                 | ★   | 4560 × 2779 | 629   |
| 07  | role-matrix            | dark       | N-6 Owner (basiltt), Manager (alex), Viewer (erin) · 1280 [88] → gen_88                                                  | 3                 | —   | 4640 × 2085 | 207   |
| 08  | status-treatments      | dark       | dark, light, hc columns · 1280×1688 [90] → gen_90                                                                        | 3                 | ★   | 4640 × 2249 | 1430  |
| 09  | components             | dark       | CMP-087 stories · 1280 [91]; panels: sheet page 2 (old frame-2560, the other contracts' stories), SCR-121 parts → gen_91 | 1                 | —   | 4560 × 2345 | 941   |
| 10  | redlines               | dark       | OV-2 redlines · 1280, · 2560 [92]; panels: legend, focus order stop by stop → gen_92                                     | 2                 | —   | 4560 × 2187 | 814   |

Counts: **23 frames by §0's count rule (21 drawn)** — 01 = 4 (2 drawn), 02–06 = 2 each, 07 = 3, 08 = 3, 09 = 1,
10 = 2, exactly the plan's 23. Shapes estimate (nodes, before packing): 5,995 in all; packed node counts are 3–12 %
lower (clones). Validator: every sheet exit 0, 0 errors, warnings equal to its source sheet's (1, 3, 3, 27, 29, 52, 0,
34, 27, 3; all Tier-1 primitive notes such as `size.control.comfortable`). Renders: boards 01, 03, 06, 08 (8 PNGs; 18
PNGs with the 10 exports).

## Brief vs plan (flagged)

- The brief's Task block names a different set (01 scr135-populated … 10 light-representatives, "total must be 38",
  "board 08 = old 66 … 10 = AL-29 / FF-16 / MM-9", "boards 01, 04, 05, 06 carry overlays"): that is E42-D04's cap10
  brief. Its own Source-of-truth line and the "E42-D03 specifics" block point at the confirmed plan, so the ten boards,
  their frames (23, not 38) and the keyboard rider (boards 04 and 06, plus board 10) follow that plan.
- Board 01: the plan's table says "four 1280 frames (5120 px)", its count note says the old 09 sheet draws two and the
  light pair is the same board exported under the light theme. Drawn as two (the sheet's content unchanged), counted
  four, with a note block in the column. If the orchestrator wants the light pair drawn as two more frames, it is a
  copy of the same trees renamed `· light` (no new content).
- Board 09: "frame-2560 is dropped" taken as "not a frame": its tree (CMP-044 TwoChoice / TwoChoiceUnknown, Rung3,
  CMP-093, CMP-138's merged stories, CMP-178, CMP-088, CMP-173) is carried unchanged as a DEV panel beside the 1280
  frame, so the plan's "CMP-044's TwoChoice … drawn once" still holds; the name reads `1280×800`. A note block says the
  old blocks' "frame-2560" means that panel. If a literal drop is wanted, remove the panel item from `BOARDS[9]`.

## Spec-vs-kit drift found

1. **Board 04 (old 53), keyboard:** its Keyboard block reads "… → tick → Cancel → Remove access" and "on Remove
   access, moves focus to the group or tick" — the pre-R-2 focusable `aria-disabled` confirm. The boards-branch text
   (4babb1f62 §12 L575-581, §13 L607) binds R-2: natively disabled, skipped by Tab. §0 L84-91 records this as a
   PROPOSED deviation ("kept until redrawn on request; the text binds"). Not redrawn (gen/ is out of scope); the focus
   overlay quotes the ruled text and says so. Merged `main` (58660d32f) has no R-2, so the merged spec does not
   contradict the drawing.
2. **§0 L84-91 vs boards 08/09 (old 90/91):** the text says 90 and 91 keep the pre-ruling CMP-138 / validity drawing;
   build-notes "RULINGS R-1 / R-2" record both were redrawn to the ruled contracts (and the harvest confirms the
   generators produce that). The boards are ahead of §0's sentence: §0 L84-91 needs a restatement when the plan's
   re-points land.
3. **§0 not restated for the new numbers:** branch §0 (L64-77) still names the old ids (09, 26, 53, 57, 72, 88, 90,
   91, 92, 94), "20 PNGs" with renders of 09, 26, 72, 90, 94, and "23 frames"; the plan's re-points (01–10, 18 PNGs,
   26's renders removed, §17 / §21 re-points) are not in the text yet. Each board's Board block therefore cites the
   old id's §0 row (L64, L66, L68, L70, L71, L72; checked to say "Drawn") and the plan.
4. **gen_26 refuses on today's tree:** `WT = k.SPEC.parents[3]` resolved to the worktree until R-1/R-2 froze `SPEC`
   under the kit's `spec/`; now it points at the kit's parent folder and `git show e69a9200c:…` fails. The harvest
   substitutes the checkout path (one counted replacement); with it the frames are byte-equal. Fix in gen_26 when it
   is next touched.
5. **CMP-015 Skeleton `State` prop:** boards 08 / 09 (old 90 / 91) carry the post-generation fix (no `State`), but
   `components.offline.json` still lists `State` on CMP-015 and the generators still emit it: regenerating 90 / 91
   would bring the prop back. Fix the inventory and the kit's skeleton helper together.
6. Merged spec on `main`: unchanged since 58660d32f (md5 2e87d809) — no merged change to any drawn state postdates the
   generators.

## Review fix pass (2026-10-29)

Three MINOR findings from the light review lens, all closed:

1. **Board 01 count (two drawn, four counted; 3280 px root, not the plan's 5120 px).** Kept as drawn. The count is by
   the §0 rule: the light pair is the same board exported under the light theme, not two more drawn frames. **PR text
   (use verbatim):** "Board 01 draws two 1280 frames (OV-2 SCR-120 overview, SCR-010 workspace) and counts four by
   the §0 rule: the light pair is the same board under the light theme, exported separately. So the root is 3280 px,
   not the 5120 px in the plan's table, and the total is 23 frames by §0 (21 drawn)." If four drawn frames are wanted
   instead, add renamed `· light` copies of the same two trees to `BOARDS[1]`. This adds no new content.
2. **`compactOf.file` absolute paths in the packed sheets.** Each is rewritten to a relative path, and each
   sha256 is re-verified against the unpacked sheet before the rewrite. Packed-file bytes are otherwise unchanged
   (compact JSON). `compactOf` is never sent to Penpot (`mkcall4.py` reads it only for its staleness check). A leak
   scan (`cap10.LEAK`) over every
   unpacked and packed file finds no hits. `mkcall4.py <sheet> count` exits 0 on all ten packed files when run from
   the unpacked sheets' folder.
3. **Review depth: validator and content fidelity.**
   - Validator re-run (`validate_sheet.py <sheet> --components components.offline.json`): all ten exit 0 with 0
     errors. Warnings are 1, 3, 3, 27, 29, 52, 0, 34, 27, 3, the same as recorded above.
   - Frame-by-frame diff of every board against its source sheet (`09, 26, 94, 53, 57, 72, 88, 90, 91, 92`,
     the recorded sheets, not `.pre-skel`), ignoring the root name, x and y and mapping the renamed root through each
     child section's `into`: every frame group matches exactly, all 21 drawn frames on the ten boards, including 02 ← 26,
     03 ← 94 (OV-9 withdrawal check) and 06 ← 72 (V-4).
   - The four carried non-frame panels (06 V-4 insets, 09 SCR-121 parts, 10 legend and focus order) differ only by the
     panel root's `abs: true`. It is dropped on purpose: the old root was a flex row, the new root is a plain board
     (no `dir`), and `cap10.py` places each panel at its old flex offset. Every other node is identical.

## Fix pass: CMP-015 / CMP-016 instances -> compositions (2026-10-29)

The per-set file `E42-D03 boards` has no CMP-015 Skeleton or CMP-016 Tooltip component, so their 6 carried `inst`
nodes would fail rendering ("component not found"). `cap10.py` now replaces them in `build()` (`substitute()`, after
`rename()`), so a regeneration keeps the fix; nothing else in the carried trees changes.

- **CMP-016 Tooltip · echo** (×2, board 06, V-4 · 1280 and · 2560, under "T2 2b · cancel with its echo") -> board
  `CMP-016 Tooltip (composition) · echo`: row, fill `color.surface.overlay`, shadow `elevation.popover`,
  `radius.control`, padX `space.inset.sm`, padY `space.inset.xs`; text `content` = the inst's own text
  "Read-only while viewing as alex." (`rbac.view_as`, no new copy) in `type.ui.caption` `color.text.primary`. Tokens
  follow E10-D03's CMP-016 tooltip (overlay, elevation.popover, radius.control, caption primary) and the E42 kit's
  overlays (`OVERLAY` + `E_POPOVER`). The inst's note is kept, prefixed `role="tooltip"`.
- **CMP-015 Skeleton · text ×3** (×3 on board 08, dark / light / hc columns; ×1 on board 09's DEV panel; all under
  "CMP-178 SystemHealthTile (composition) · Recorder and storage") -> board `CMP-015 Skeleton (composition)`: column,
  gap `space.stack.xs`, `Count` (3) rects `bar 1..3`, each the inst's slot width (275 px) × 12 px, fill
  `color.surface.hover`, `radius.control` (E27-D03 kit FALLBACKS["SKELETON"]: a static bar in color.surface.hover,
  the reduced-motion form; its bar is 12 px tall).
- Notes: the carried `inst 'CMP-015 …'` / `inst 'CMP-016 …'` live-check lines are dropped on the boards that
  substitute (nothing to verify live); each such board gains a `fallbacks`, a `tokens` and a `live_checks` line
  prefixed "fix pass:".
- Also folded into `cap10.py` so a regeneration reproduces the reviewed outputs: the `compactOf.file` rewrite
  (review fix pass item 2; sha256 checked in `pack()`) and board 01's `.md` theme wording.
- Results: all ten sheets validate exit 0, 0 errors, warnings unchanged (1, 3, 3, 27, 29, 52, 0, 34, 27, 3); 0
  `"t": "inst"` nodes and no boolean `wrap` in the unpacked and packed sheets; leak scan clean;
  `mkcall4.py <packed> count` exit 0 on 06, 08, 09.
- Identity check (against the pre-fix outputs, a record not committed): boards 01-05, 07, 10 are byte-identical
  (`.json`, `.md`, packed). On 06, 08, 09 the board, export, section list and `into` paths are unchanged and every
  section equals `substitute(pre-fix section)` exactly (2 + 3 + 1 sections touched, 6 nodes replaced); `.md` differs
  only in the validator byte count and the node / instance counts; notes differ only in `fallbacks`, `live_checks`,
  `tokens`. Node estimates: 06 629 -> 631, 08 1430 -> 1439, 09 941 -> 944.

## Live-check fold (2026-10-29)

The SHEET-FIX lines of the live-check report (boards 04, 06, 09, 10 and the all-boards lines) are folded into
`cap10.py` (`livefix()`, run in `build()` after `substitute()`; `ROOT_H` in `write()`), so a regeneration reproduces
what was fixed live. The pre-fold `cap10.py`, its outputs and the diff script are records (not committed). No text
string, token or other node changed.

- 06 `T2 2b · cancel with its echo` (1280 frame only, as fixed live): w 32, h 58, `clip` false; the CMP-016 echo
  is `abs`, x = 32 - 186 = -154, y = 36 (right-aligned to the IconButton, 4 px under it). The 2560 frame is unchanged
  (the report names 1280).
- 06 'pending' glyph pin at (1, 1): NOT expressible in the sheet schema (an icon node has no child offset; the svg
  group is a renderer detail). Recorded as a `live_checks` line on board 06; the renderer step must pin it.
- 09 `unknown line (radiogroup label)/tail`: `w` 212 dropped (auto-width). The last capacity line's `text`: w 890 -> 888.
- 04 rung-2 dialog y 171 -> 167 (1280), 491 -> 487 (2560).
- `underline` w = measured word width (the report's per-word deltas): Change 46->48, BTC scalp 61->62, Default 43->45,
  Workspace 68->70, Journal 44->47, Settings 49->51, Security and backups 147->148, Flags 36->37, Recorder and storage
  148->146, Record tier 66->68 (02 x2, 03 x2, 04 x4, 07 x3, 08 x9, 09 x4, 10 x2; 25 underlines in all).
- Roots h = annotation foot + 80: 2349, 2248, 2276, 3131, 2244, 2944, 2174, 2359, 2470, 2275 (01-10). The grid row
  pitch (`step_y`) still uses the estimate, so board positions are unchanged; 04 (h 3131) now ends 69 px above the
  row-2 boards at y 3200.
- 10 pills (measured vs estimate): focus 3 x+1, 5 x-2, 8 x+2 (both frames); 10, 15, 16 x+1 and 11-14 y+3 (2560).
- Results: all ten validate exit 0 with 0 errors, warnings unchanged (1, 3, 3, 27, 29, 52, 0, 34, 27, 3); re-packed
  with `compactOf.file` rewritten (sha256 checked; the committed form is the bare file name); scan: 0 `inst`, no
  boolean `wrap`, no local-path string in the sheets, `.md` or packed files.

## Review fold (2026-10-29, PR #4978 lenses)

- **Rebuild (B-1):** pins read with `git show` when no frozen copy is present (`cap10._pin_bytes`,
  `e42kit.pin_bytes`, appended after the kit's last block so no kit line moves); the source sheets read from
  `E42D03_SOURCES`; `harvest.json` committed with its run paths reduced to file names; each board `.md` written
  beside the kit in its committed form (no trailing blank line). The section "Rebuild" above lists what is a record
  and the proof.
- **Paths and wording (B-2):** this file and `cap10.py` cite the repo tools and "the confirmed plan (#886 comment
  6498384157)"; the board `.md` files name the generators as `gen_NN.py` and the harvest as `gen10/harvest.json`.
  The drawn annotation keeps its provenance words ("re-run in the sandbox"), so the sheets still match the boards.
- **Tools:** `gen10/tools/v4check.py` (E42-D04's, pointed at this kit), `gen10/tools/framediff.py` (E42-D04's, its
  files read through `Path`) and `gen10/tools/asdrawn.py` (the committed `v4/` against the as-drawn sheets at a
  revision); all three ruff- and black-clean.
- **Carries for the next redraw (C-3, C-8):** two carried annotation strings were stale when drawn; `cap10.CARRIES`
  fixes them in the sheets (each must occur once; a `deviations` note names both), the drawn boards keep them until
  the next redraw, and E42-D03 §0's as-built record names them verbatim. Board 08 [90], the frames block: "Boards
  90–92 draw 3 + 2 + 2 = 7 frames: board 91 has two, so §0 L73's 6 / 211 hold only if 91 becomes one frame (open
  item 1)." → "Under the cap [90]–[92] count 3 + 1 + 2 = 6 frames: [91] is board 09's one 1280 frame (its old 2560
  page a DEV panel beside it), so §0's 6, and its 23 of 211, hold." Board 01 [09], the questions block: "Q4 (L150,
  owner, due 2026-10-27): the neutral band;" → "Q4 (§3, owner, #2701; the neutral default stands until ruled): the
  neutral band;". `asdrawn.py`: every other section of the ten boards is node-identical to cf47ac05b; notes differ in
  `sources` (the plan's name) and, on 01 and 08, `deviations` (the carry) and 01's `live_checks` (its column
  estimate, 2131 → 2149 px, inside the 2349 px root).
