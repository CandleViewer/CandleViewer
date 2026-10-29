# E42-D05 (#960) — Penpot board sheets: build notes (binding for board generators)

Kit: `e42d05kit.py` beside this file (Python 3.12+, stdlib only), built on E42-D03's `e42kit.py` (imported read-only:
the CMP-087 shell, the primitives, the text metrics, `sections_for_board`). Self-test: `python3 -I -B e42d05kit.py
selftest` → 22 PASS, 0 FAIL; `00-selftest.json` validator exit 0.

## Sources of truth (the kit reads and checks them)

- **Spec**: `spec/E42-D05@72ee4fb32.md`, a frozen copy of `git show 72ee4fb32:docs/design/E42/E42-D05.md` (the merged
  spec text; not committed, re-create it with that command), **md5 `caa2ca66de34951efc989eac875def0a`, 931 lines**. The kit refuses to import on any other md5: re-pin first.
  Every line the kit records is read there (`L(n)`, `find_line()`); anatomy strings are line-checked by `label()`.
- **Plan**: `spec/e42d05-plan.md`, the ten-board plan posted as #960 comment 6477436230 (confirmed 18:44Z, comment
  6477583631; not committed, copy the comment body):
  ten boards, 57 frames, renders on 02, 03, 04, 06. `BOARDS` encodes it; the self-test checks every slug, state id
  and old-board bracket against the plan's rows.
- **Schema**: the header of `../lib/cvsheet-v4.3.js` (v1 node schema, unchanged). Validator: `python3 -I
../tools/validate_sheet.py <sheet.json> --components ../tools/components.offline.json` (exit 0 required). Packer:
  `../tools/compact.py` (the one E42-D04 used for its v4 sheets) into `v4/`.
- **E42-D03's kit**: `e42kit.py`, imported read-only from `../e42-d03/` (`D03_DIR`), where E42-D03's boards PR commits
  it; until then the kit runs only beside a copy of that kit.

## Rules for a board generator (`gen/NN-<slug>.py`)

- Write only `gen/NN-<slug>.py`, `NN-<slug>.json`, `NN-<slug>.md` (and the packed copy). Never edit the kit; a missing
  block is written inside the generator and reported. No /tmp, no Penpot, no GitHub, no network. Never pkill/killall.
- Import: `import sys; from pathlib import Path; sys.dont_write_bytecode = True;
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); import e42d05kit as d`.
- The shortest correct generator:

```python
rows, groups = d.board_parts(NN, {"HL-2": {"decisions": "D1-D5, D9, D10", "keyboard": "…"}, …})
extra = [d.focus_overlay(s, dialogs=True, stepper=True) for s in d.BOARDS[NN].keys]   # the keyboard rider
ann = d.ann_column(NN, groups, extra)
r = d.write_board(NN, rows, ann)          # NN-<slug>.json + .md, validated (raises on exit != 0), packed
print(r["valid"], r["nodes"], r["sections"])
```

`board_parts()` builds every planned frame with the kit's presets (`build_frame(F)`) in the plan's rows and one
annotation group per state; pass per-state blocks to add or override annotation entries. A generator that needs a
different drawing builds its frames with the public builders below and names them with `at(frame, F)`.

- **Frames.** 1:1 at 1280 × 800 or 2560 × 1440, named `<state id>[ · <tag>] · <size> [<old §0 board>]` (`frame_name`),
  e.g. `HL-2 · 2560×1440 [06]`, `RW-14 · 200 % zoom · 1280×800 [65]`, `status sheet · hc · 1280×800 [02]`. Every frame
  the plan lists, nothing else.
- **Insets** sit inside the frame §0 names them on (`inset(px, sid, what, kids)`): an absolute raised card at a corner,
  titled `Inset · <sid> — <what>`, never a frame. The plan's insets are in `F.insets` and drawn by the presets
  (client-tile, HL-5-gate, HL-7, HL-15, link-expired, 404, RW-16, loading, today, config-only, outcome-unknown, WZ-15,
  IW-9, rowless).
- **Annotation column** (400 px, outside the frames, right of the widest row): per state `ann_group(sid, frames,
blocks)` with Source (the state row's line and §0 board), State id and trigger (the row's When), Decision ids,
  Roles (`ROLES`), Keyboard path and focus, Announcement (the row's), Copy keys (the row's + every key recorded since
  `mark()`), Tokens (recorded since `mark()`), Analytics and audit events (the screen's events paragraph). The kit
  fills every default but **Decision ids** and **Keyboard path and focus**: the generator passes them per state (read
  §2's D-rows and the screen's Keys paragraph). Then the focus overlays (boards 03, 05, 06, 08, 09: the plan's
  keyboard rider), the Board block (name → export, frame count, ★ renders) and the footer.
- **Composition** (`compose`, called by `write_board`): non-flex root `color.surface.app`, clip; 80 px margin and
  gutters by x/y (no 80 px space token); rows top to bottom; root w ≤ 6000, h ≤ 9500 (boards with four 1280 frames in
  a row are exactly 6000 wide and abut the next cell; the neighbour's 80 px margin keeps content apart).
- **Grid, page, names.** Board NN at x = ((NN−1) mod 5) × 6000, y = floor((NN−1)/5) × 9500; page `E42-D05` in the
  file `E42-D05 boards`; board name `E42-D05 / NN <slug> · <sizes> · <theme>` (sizes `1280×800` or
  `1280×800+2560×1440`); footer `page E42-D05 · board NN · r1`; export `docs/design/E42/img/E42-D05-NN-<slug>.png`;
  ★ renders `<stem>-greyscale.png`, `<stem>-deuteranopia.png` on boards 02, 03, 04, 06.
- **Sections** ≤ 14,000 bytes (`SECTION_BUDGET`; `write_board` refuses > 20,000); the `.md`'s line 3 is
  "File `E42-D05 boards`, page `E42-D05`; export …".

## Binding rules the kit enforces (do not work around them)

- **Copy by key, verbatim.** `copy(key, **fills)` (all fills given), `rich(key, …)` (a fill passed as `None` draws a
  neutral bar named by the fill; `[Action]`s become controls; `fill_map=` for a fill named `name`), `words()` (one text
  node). Keys: §15 L707-714 and §8.2 L471-485 parsed into `COPY` (267 keys; fill names normalised: `{yyyy-mm-dd hh:mm}`
  → `yyyy_mm_dd_hh_mm`), `INHERITED` (D04 banners and `admin.rate_limited`, "This always needs a fresh code.", D02:708's
  spent-code sentence, E17's banner and chip, D09's `scr017.cannot` and "Ask the owner…", `14:425`), and E42-D03's
  `tile.*`, `meta.asof`, `footer.area_entered`, `strip.*`, `save.*`, `inv.*`, `ud.*`, `cap.at_capacity`, `dlg.*`,
  `admin.locked`, `admin.ack_first` (by reference, §15 L715). `label(chars, line)` draws an anatomy string the screen
  sections give outside §15 (line-checked, recorded as a copy gap); `ext_label(chars, source)` one from another doc
  (`14`, D03). Kit-named sub-keys (§15's unnamed lists, e.g. `backup.status.*`, `incident.detail.*`) are recorded.
- **Values** come from §1's worked example only (`AS_OF` 14:02:11, SCR-144's 14:06:02, `EXAMPLE_HEALTH`, `INCIDENTS`,
  `BACKUPS`, `RESTORE_POINT` 2026-10-21 01:00 pg_basebackup 820 MB, `ONBOARD_EXAMPLE`, `GROUPS`, the B1 / B8 latches);
  every value §1 does not give is `bar(field)`, never an invented number or word.
- **Tokens by name** (exact Penpot names; colour and type from the semantic sets, §16): surfaces app / raised /
  overlay / sunken / hover / selected; text primary / secondary / tertiary / link / on-action; status *.subtle /
  *.strong; `color.neutral.default` (the neutral tone, CG-30); `color.border.selected` (current step, the diagram's
  current state); `color.data-confidence.stale.{indicator,text,surface}` (clock, CMP-239); CMP-023's track
  `color.surface.hover` (color.track's stand-in). Never `color.text.disabled` or `opacity.disabled` (`write_board`
  raises). Tier-1 warnings for `size.control.comfortable` and `opacity.scrim` are expected (e42kit's bindings).
- **T2 (§4.1)** = `t2(label, reason)`: native role and full label, aria-disabled, the CMP-019 `lock` leading the label,
  label and glyph `color.text.tertiary`, a filled variant drops to `color.surface.raised` with a `color.border.default`
  hairline, the reason (an `admin.*` key ≤ 60 characters with a full stop: checked) under it in
  `color.text.secondary`; `beside=` holds an exact time or a "→ Maintenance" link beside the reason, never in it.
  One notice, many pointers: `t2_notice(reason)` + `t2(…, shared=True)`. `t2_radio` arrows-focus, never checks. **Not
  T2**: `busy()` (a control whose own job runs or that waits on a read), `validity()` / `confirm_bar("validity")`
  (form validity, native disabled allowed), outcome lines in place of finished actions (IL-2, BK-13, BK-15, SI-7).
- **Security looks (§8.2, BK-12/13/14, WZ-4, WZ-6, SI-6; the Fable lens).** `impact_lines(scope)` draws §8.2's lines
  in its order with its "shown when" rules (bybit first always; rewind, secrets, sign-in, security_today with
  `postgres`; config with `config`; trading and reconcile always; market, or market_on when a market store is
  ticked; audit labelled "(target, D7)"); nothing says "safe", "undo" or "recover your trades". RW-5's target reads
  "if D7 decides as proposed" with the list and its tick and the sign-out line before step 3; today's inset has no
  list and no tick. RW-6: `restore.confirm.reason_replaced` + `restore.confirm.marker_replaced` while `postgres` is
  in scope (CG-7 open), `restore.confirm.reason` + "Backup restored (backup.restore)" in the config-only inset; the
  confirm "Restore from 2026-10-21 01:00" waits on form validity. Download: rung 4, the warning, who can fetch it, the
  typed token with its note (client ceremony, said so), "This always needs a fresh code.", the marker; the link shown
  once with [Download] and its expiry, never [Copy link], the close warning. The secret: write-only, no reveal,
  `onboard.secret_once` on `warning.subtle` in `text.primary`; the revisit shows no field, value or hash. The latch:
  rung 4, the effect, the trips, the fresh-code line, a marker without a code. Dialogs: Cancel focused (ring), the
  scrim black at `opacity.scrim` (bound `color.surface.sunken`, dark only), the TopBar's and StatusBar's ENV badges
  drawn again above the scrim (`modal()`; C-2.11).
- **Health (D2, D9).** Words are the contract's (`healthy`, `degraded`, `warning`, `down`, "Not built yet",
  "stale since …") with check / triangle / octagon / ring / clock; `health.safe` follows the stops sentence only where
  D9 allows (`safe=False` withholds it, never rewords it; HL-5's inset is today's withheld state); numbers from the
  report only ("— not received" when absent, stale with CMP-239 after a failed read).
- **Light** boards are the same construction ("· light"); the theme switches at export. Board 02's dark, light and hc
  columns are one construction each at 1280 × 800 (deviation (4)); the forced-colours column is `fc_column()`:
  HL-6, RW-3 and WZ-5 crops under `forced()` (Canvas / CanvasText / LinkText / Highlight / HighlightText stand-ins,
  FALLBACKS["FC"]).

## Per board (plan → kit)

| NN  | frames (presets)                                                                                               | focus overlay              | renders |
| --- | -------------------------------------------------------------------------------------------------------------- | -------------------------- | ------- |
| 01  | HL-2, HL-5, HL-14, IL-2 at 1280, each tagged with its E04 counterpart; add `anchors()` (§5.2) as a block       | —                          | —       |
| 02  | `status_sheet_column("dark"/"light"/"hc")`, `fc_column()`                                                      | —                          | ★       |
| 03  | HL-2 1280 (client-tile inset) + 2560, HL-5 (gate inset), HL-6 (HL-7 inset), IL-2 1280 + 2560                   | SCR-143, SCR-144           | ★       |
| 04  | HL-11 1280 + 2560, HL-12 (HL-15 inset), HL-14 1280 + 2560, HL-18 (export dialog)                               | —                          | ★       |
| 05  | BK-4 1280 + 2560, BK-2, BK-12 1280 + 2560 (download dialog), BK-9, BK-13 (link-expired, 404 insets), BK-14     | SCR-146                    | —       |
| 06  | RW-1 1280 + 2560 (RW-16 inset), RW-3 1280 + 2560, RW-4 (loading), RW-5 (today), RW-6 1280 + 2560 (config-only) | restore                    | ★       |
| 07  | RW-8 1280 + 2560 (outcome-unknown inset), RW-10, RW-12, RW-14 × 2 (200 % zoom, 200 % text)                     | —                          | —       |
| 08  | WZ-4 1280 + 2560, WZ-5, WZ-1 (WZ-15 inset), WZ-6, WZ-11, WZ-12                                                 | wizard                     | —       |
| 09  | IW-3 (IW-9 inset), IW-4, GV-1, SI-1 (rowless inset), SI-6 (latch dialog)                                       | wizard, SCR-062, inspector | —       |
| 10  | HL-20 (= HL-6), RW-15 (= RW-3), WZ-16 (= WZ-5), light                                                          | —                          | —       |

Measured with the presets (validator exit 0 on every board, 2026-10-28): 01 6000 × 3352, 02 6000 × 1344, 03 5920 ×
4200, 04 5920 × 3256, 05 5920 × 5168, 06 5920 × 4640, 07 5920 × 3968, 08 6000 × 4912, 09 4640 × 4992, 10 4640 × 2760;
largest section 13,958 B; board 05 packs 430 → 376 kB.

## Public builders (one line each; docstrings in the kit)

Copy: `copy`, `rich`, `words`, `label`, `ext_label`, `raw`, `fills_of`, `norm_fill`. Spec: `L`, `find_line`, `state`
(STATES), `keys_text`, `events_text`, `shared_keys`, `anchors`. Plan: `plan_frames`, `frame_name`, `board_name`,
`board_sizes`, `grid_xy`, `export_path`, `footer_text`. Primitives: `bar`, `action`, `t2`, `t2_reason`, `t2_notice`,
`t2_radio`, `lock_glyph`, `busy`, `validity`, `confirm_bar`, `marker`, `marker_line`, `status_word`, `health_word`,
`health_status`, `stale_chip`, `progress`, `banner`, `notice`, `disclosure`, `token_field`, `fresh_code_line`,
`grid_table`. Frames: `admin_frame`, `page_head`, `plain_frame`, `modal`, `env_badges_above`, `inset`, `at`,
`build_frame`. SCR-143: `scr143`, `health_set`, `hl6_comps`, `overall_state`, `comp_label`, `health_tile`,
`client_tile`, `tile_grid`, `overall_line`, `reread_meta`, `build_line`, `e17_banner`, `export_dialog`. SCR-144:
`scr144`, `incident_cols`, `incident_row`, `severity_cell`, `segmented`, `incident_filters`. SCR-146: `scr146`,
`backup_cols`, `backup_rows`, `backup_status`, `backup_actions`, `backup_summary`, `kind_label`, `when_cell`,
`download_dialog`, `delete_dialog`. Restore: `restore_frame`, `restore_step1`, `restore_step2`, `restore_step3`,
`restore_outcome`, `impact_lines`, `scope_picker`, `backup_radio`, `cancel_restore`, `restore_statuses`, `fold`,
`wide_200`. Steppers: `stepper`, `step_word`, `step_glyph`, `step_body`, `wizard_layout`. Onboarding:
`onboard_frame`, `onboard_statuses`, `onboard_start`, `onboard_step3`, `onboard_invite`, `onboard_resume_top`,
`continue_to`, `wz15_inset`. SCR-017: `invitee_frame`, `invitee_totp`, `orientation_card`, `iw9_inset`. SCR-062:
`scr062`, `group_row`. Inspector: `inspector`, `kind_counters`, `machine_table`, `latch_dialog`. Board 02:
`status_sheet_column`, `fc_column`, `forced`. Annotations: `mark`, `ann_group`, `ann_block`, `ann_text`,
`focus_overlay`, `board_block`, `ann_column`. Output: `board_parts`, `compose`, `write_board`, `pack`, `walk`,
`note`, `reset_notes`, `selftest`.

## Recorded gaps and deviations (they ride in every sheet's notes; repeat them in the board's .md)

- **Spec gap:** §15 L714 proposes `admin.invite_pending` "The invite hasn't been accepted yet.", a key E42-D03 §14
  already holds as "Available once the invite is accepted." — the kit draws D05's (WZ-14 is not drawn).
- **No source names**: dialog confirm labels for Download and Delete (bars), the export dialog's field labels and
  confirm (kit words), the tile's history-disclosure label (a bar), SCR-144 / SCR-062 column headers, the backup
  kinds' plain labels other than "Postgres full (pg_basebackup)" (bars + enum), the failed row's "Code" disclosure,
  SCR-017's step names, the restore stepper's status words (§9.1's reused), the BK-13 [Close].
- **Kit judgements (DJ):** the component order is §15's label order (the server order is not given); HL-6 / HL-7's
  not-built component is `bars_writer`; single-file kinds are pg_dump and config_bundle (CG-13's inference);
  INCIDENTS' statuses beyond §1 (the chain break open, the break-glass row acknowledged); the download warning in the
  warning tone; HL-14 shows `health.report_failed` + [Retry] under the overall line.
- **Not expressible in cvsheet:** board 01's E04 frames are E04-D01's own boards (not redrawn: each D05 frame names
  its counterpart; a live step can duplicate E04's boards beside them); RW-14's 200 % has no 2× type tokens (drawn as
  the reflow with `type.ui.heading-lg` / `display`); the diagram's 3 px border is `border.thick` + `border.hairline`
  nested; forced colours have no token theme (stand-ins); light theme happens at export; the scrim cannot bind black
  (sunken, dark only); IW-3 embeds E09-D04's SCR-003 as a named region.
- **Clipping at 1280:** SCR-143 (16 tiles), SCR-146 (9 rows with 2a reasons) and long steps exceed 704 px of main
  column: they clip as a page scroll (a live check per frame); the drawn part shows the state's subject first.

## v4 packing (the committed sheets)

The packer is `../tools/compact.py` (cvsheet v4.1 clone nodes and styles, as E42-D04's v4 sheets). The validator runs
on the original sheet (the packed form has styles and clone nodes, which the plain validator rejects); exit 0 on all
ten. `v4/` holds the ten packed sheets the boards were rendered from, byte-identical apart from `compactOf.file` (a
bare file name) and the absolute paths in `notes.sources` (made repo-relative); the unpacked originals are not
committed (regenerate them with `gen/`; the regenerated sheets equal the rendered ones apart from those two strings).

| sheet                           | validator | errors/warns/sections | nodes | bytes orig → packed |
| ------------------------------- | --------- | --------------------- | ----- | ------------------- |
| 01-e04-continuity.json          | exit 0    | 0/13/48               | 1370  | 376681 → 157556     |
| 02-status-sheet.json            | exit 0    | 0/7/14                | 685   | 189607 → 72140      |
| 03-scr143-144-populated.json    | exit 0    | 0/19/63               | 1822  | 488310 → 200353     |
| 04-scr143-outage.json           | exit 0    | 0/19/72               | 2274  | 626611 → 248044     |
| 05-scr146-list-download.json    | exit 0    | 0/178/89              | 2570  | 754841 → 381451     |
| 06-restore-gate-impact.json     | exit 0    | 0/29/40               | 1284  | 364492 → 155474     |
| 07-restore-outcomes.json        | exit 0    | 0/38/29               | 939   | 269632 → 126992     |
| 08-onboard-key.json             | exit 0    | 0/23/30               | 1053  | 291900 → 116261     |
| 09-scr017-scr062-inspector.json | exit 0    | 0/15/28               | 696   | 200352 → 95738      |
| 10-light-representatives.json   | exit 0    | 0/8/21                | 656   | 183890 → 80563      |

Byte counts are before the wrap fix below. Warnings are Tier-1 primitive tokens (`size.control.comfortable` and the
like). `00-selftest` is not packed or committed.

## The wrap-boolean lesson (render failure, 2026-10-28)

Penpot's `FlexLayout.wrap` takes `"wrap"` or `"nowrap"`, not a boolean. The kit passed `"wrap": True` at nine call
sites, and section 0 of board 01 failed with "[PENPOT PLUGIN] Value not valid". The offline validator does not check
the value's type, so the error showed only at render. The kit now passes `"wrap"`; all ten boards were regenerated,
validated and re-packed. The wrap-aware height estimate moves two insets (05 BK-13, 07 RW-8) by 11-23 px. Lesson: any
Penpot enum (wrap, sizing, alignment) goes in as its string; a dry render of section 0 catches the rest before a full
run.

## Committed form (2026-10-29)

Paths are repo-relative (`KIT_DIR`, `TOOLS_DIR`, `spec/`); the kit and generators are black (100) and ruff clean, and
the regenerated sheets equal the rendered ones. One fix rides with the move: the validator's components path
(`COMPONENTS_FILE`) was shadowed by the SCR-143 label tuple `COMPONENTS`, so `write_board()` validated without the
component inventory; every board was re-validated with it, exit 0, 0 errors.

## Live fixes not yet in the generators (SHEET-FIX, live check 2026-10-28)

The live check fixed these on the boards; the next regeneration fixes them in the kit or generators.

- All ten boards, `annotations`: the root-height estimate is 87 to 244 px short; size the root from the column's real
  height (the column ended 7 to 161 px past the root; every root was grown to hug, outside-root 10 → 0).
- `e42d05kit.py` backups table at 1280: `kind` is the leftover column and gets 12 px. Use when 136, kind 136, size 64,
  status 194, verified 88, keep 74, actions 252. At 2560 use status 240 (kind 856).
- Incidents table at 1280: `message` is the leftover column and gets 56 px. Use subsystem 132, severity 80, message 96,
  duration 112, resolution 156.
- Machines table at 1280: `machine` is the leftover column and gets 8 px. Use machine 116, kind 64, env 96, state 88,
  hash 160, trips 88, latched 188, deferred 72, updated 72.
- cvsheet wrap boxes (`actions`, `duration`, `status · *`, the T2 boxes): they hug their content, so they never wrap.
  Make them fill the cell's inner width; the T2 Download… box and its reason are 236 px.
- `outcome line/words-N` and inset `words-1` texts: draw them as wrapping text (fixed width, auto-height), not
  auto-width.
- SCR-152 banner `words` (boards 01, 04): fill the width that is left (1077 px at 1280), so the Details link is never
  pushed out.
- `EnvBadgeLocal`: its x is 1 px right of the StatusBar badge.
- Dialogs: centre them on their real height, not the estimate (recentred by 1 to 13 px; BK-14 was 13 px off).
- Insets that grow: re-anchor them to the StatusBar top minus 16 after relayout (RW-8 on 07, RW-4 on 06).
- Placeholder bars in narrowed cells (message, kind, keep, verified): size them to the cell width.
- RW-3 (board 06) and RW-15 (board 10) at 1280: the step body adds up to 773 px against main's 704, so Cancel
  restore, Back and Next were cut 23 px. Fixed live by binding the gaps of `impact (§8.2)` `space.stack.sm` →
  `space.stack.xs` and `step body` `space.stack.md` → `space.stack.sm`; the kit should fit the step body in 704 px
  with those tokens. The footer marker below the restore buttons still continues under the fold (5 px, a page
  scroll): recorded, not a defect.
- Annotations: SCR-144's note on boards 01 and 03 gains "A virtualised CMP-049 keeps `aria-rowindex` (`15:498`)";
  SCR-146's on board 07 gains the APG-grid line (row actions reached by ← →; Enter acts once). Both were added live.

## Boards review round 1 (2026-10-29): live patches and their sheet fixes

- M-1, board 06, RW-6 at 1280 and 2560: the step-3 footer gains the ghost "Cancel restore" before [Back] (D24, §8.1,
  §8.3), built like RW-3's; `restore_step3` now returns [Cancel restore, Back, confirm] (the committed sidecar sheets
  predate it). RW-6's keyboard annotation lists Tab … → Back → [Restore …] → Cancel restore, as RW-1, RW-3 and RW-4
  do, with "Esc = Cancel restore".
- M-3, board 01: E04-D01's own PNGs (`docs/design/E04/img/scr-143-all-green.png`, `scr-143-degraded-outage.png`,
  `scr-143-unreachable-backend.png`, `scr-144-incident-log.png`, each 1440 × 900) are placed at 1:1 as image fills in
  the four slots (each slot 1440 wide, image then caption). The board grows to 6640 wide (x −640 so board 02 keeps its
  place); the annotation column moves to x 6160. A sheet cannot carry an image fill: a regeneration needs the same
  live upload step (`penpot.uploadMediaData`, one PNG per call).
- M-2, board 02: the light and high-contrast columns are exported under their own themes (`semantic-light`,
  `semantic-hc`) and composited column by column into the one PNG; each column passes its own theme's text-colour
  check. The board itself is unchanged.
