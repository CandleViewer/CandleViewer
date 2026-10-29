# E42-D04 (#887) — Penpot board sheets: build notes

**Committed form (2026-10-29).** This folder is the kit the ten E42-D04 boards (page `E42-D04`, file `E42-D04 boards`)
were built with:

- `e42d04kit.py` (Python 3.12+, stdlib only), built on **E42-D03's `e42kit.py`, imported read-only** from `../e42-d03/`
  (`D03_DIR`), where E42-D03's boards PR commits it; until then the kit runs only beside a copy of that kit. e42kit
  draws the CMP-087 admin shell (TopBar, NavRail, band, strip, StatusBar, RightRail), the T2 control, buttons, fields,
  dialogs, the scrim and the text metrics; this kit adds the D04 surfaces.
- `gen10/`: `cap10.py` (the confirmed ten-board plan, the layout and the annotation column), the ten thin board
  scripts `NN-<slug>.py`, `BUILD.md` (how the ten boards were composed, Fix passes 1-4) and `tools/` (`linemap.py`,
  the spec line maps; `framediff.py` and `identity.py`, the frame-identity proofs; `v4check.py`, the packed-sheet
  check).
- `NN-<slug>.md` (×10): each board's sidecar (line 3 names the page and theme).
- `v4/NN-<slug>.json` (×10): the packed sheets the boards were rendered from, byte-identical apart from
  `compactOf.file` (a bare file name) and the local paths in `notes.sources` and in two provenance texts (boards 02
  and 05), made repo-relative or named in words. `compactOf.sha256` stays the rendered original's.

Not committed: the unpacked sheets (each `v4/` sheet expands, with `../tools/compact.py`, to its original section for
section: checked on 2026-10-29, every expansion validator exit 0), the 74 per-id generators (`gen/`) and their per-id
sheets the frames were harvested from, the spec pins (`gen10/pin/`, `spec/`: re-create each with the `git show` its
constant names), the sandboxes, logs, pre-copies and caches. Paths are repo-relative; `cap10.py` writes the unpacked
sheets to `cap10b/` and packs into `v4/`.

The history below is the kit's own, kept as written (the per-id era, then the folds and the cap); the ten boards'
build is `gen10/BUILD.md`.

## The per-id kit (#887, PR #4193): build notes as written

Source of truth: the spec `docs/design/E42/E42-D04.md` in the spec's worktree (text APPROVED pending
boards; the round-2 carries may be folded in the working tree while you work — read the working-tree file). Read §0
(74 boards, names, sizes, themes, ★ renders, build order) in full, §1 (the worked example and the objects), the screen
section and the state table of your board (§4 SCR-135 AL-1..29, §5 SCR-136 AD-1..8, §9 SCR-145 FF-1..17, §10 SCR-148
MM-1..12), §6 (the diff language), §12.1 (the T2 rule), §13 (motion), §14 (the copy deck), §15 (tokens and contrast).
The admin shell (CMP-087: band, strip, tint, TopBar/NavRail/StatusBar/RightRail) is E42-D03's and is ALREADY BUILT in
the E42-D03 kit ../e42-d03/e42kit.py — reuse it, never redraw it.

## The pipeline (same as E42-D03)

1. OFFLINE: each board is a JSON sheet (schema: the header of ../lib/cvsheet-v4.3.js),
   produced by a small Python generator that uses the D04 kit
   e42d04kit.py (which imports e42kit for the shell),
   validated with `python3 -I ../tools/validate_sheet.py <sheet.json>
--components ../tools/components.offline.json` (exit 0 required).
2. LIVE (later, on the hpe transport): cvsheet v4.1, one section per call; lint; export.

## Page and board frame (spec §0, binding)

- Page `E42-D04`. Board name `E42-D04 / NN <screen>/<state> · <size> · <theme>` exactly as §0 and the state tables give
  it; export `docs/design/E42/img/E42-D04-NN-<slug>.png` (`<slug>` from the board column of §4, §5, §9, §10).
- A state board holds BOTH sizes side by side at 1:1 (1280 × 800 and 2560 × 1440) unless §0 says otherwise for it,
  with the 400 px annotation column outside the frames (title, source line: operation, budget, events, mount state;
  state id and trigger; decision ids; roles; keyboard path and focus; announcement; copy keys; tokens; analytics/audit
  event; footer "page E42-D04 · board NN · r1").
- Grid placement: board NN at x = ((NN − 1) mod 5) × 4600, y = floor((NN − 1) / 5) × 1800.
- Light boards (29, 37, 53, 62) are the same construction as their dark twin, named "· light"; the theme switch
  happens at export ([THEME-WINDOW]).
- Root board: flex row, align start, fill `color.surface.app`, padding `space.inset.lg`, gap `space.inset.lg`, clip on.

## Content rules

- Copy: only §14's keyed strings (verbatim) and the worked example's data (§1); never invent a string or a number.
- Tokens: only names in ../tools/token-sync.json; proposed tokens drawn as their
  fallback and annotated.
- Every gated control is §12.1's T2 (standing gate briefs/standing-gates.md
  G-T2): the `lock` glyph leading the full label, the reason under it, the label `color.text.tertiary`, the raised fill
  with a `color.border.default` hairline; the Manager's "My activity" keeps every Owner-only control visible, T2.
- The diff language (§6): added / removed / changed values, nested objects, long values, secrets as fingerprints only.
- Library components: instance only sets that exist (components.offline.json is approximate — list every inst node in
  `notes.live_checks`); compose the rest locally and name them `<CMP id> <Name> (composition)`.
- Keep each section under ~14 KB of JSON (split the 2560 frame into sub-sections).

## SPEC MOVED (boards PR carries) — 2026-10-23, hcl-worker-2 (binding from here on; supersedes the source line above)

**The spec is now the boards PR's folded text:** `docs/design/E42/E42-D04.md`,
branch `design/e42-d04-boards` at fold commit `8a3bc3f2d` (the folds `b2072bc8e`, `7e88a5357`, `8a3bc3f2d` = G-1..G-39,
`gaps/fold-log.md`), **md5 `818bd87704658faaf05a3738659b4348`, 1,018 lines**. Read it there, never in the spec's worktree (which holds
the merged `a58b368b`, 906 lines). `e42d04kit.py` now reads WT = the boards branch, SPEC_MD5 = 818bd877 (backup:
`e42d04kit.py.pre-carries`).

- **How the kit was re-pinned.** The kit's L-numbers were read at `58f901df`, a working tree no copy keeps; its 22 line
  checks pass on `3bdb03c1` (a434afa1f, `repin/spec-kit-proxy-3bdb03c1.md`), so every citation went kit → `a58b368b`
  (`repin/linemap-kit-to-old.json`) → `818bd877` (`repin/linemap-carries.json`, the brief's map: difflib over
  whitespace-normalised lines; it agrees with fold-log's "untouched deltas" on all 668 untouched lines). 342
  L-citations: 320 moved, 22 unchanged; 269 re-read by content (a line edited on either side, or an override where
  the cited unit grew: e.g. §1's worked example L101-106 → L107-120, §4 Columns L184-185 → L210-214, §15 L610-616 →
  L691-701), 73 by the map alone (`repin/kit-repin-tokens.json`, `repin/tools/repin_tokens.py`). Data pins:
  `repin/kit-datapins.json`.
- **Every other `path:line` reads at the key's pin `b7154f951`** (spec L16-17). DOCS: D02, D01, D09, E30-D02, E39-D03,
  E10-D02, E17-D01 from the boards branch (identical at the pin; the self-test checks their md5s); `catalogue.py`, `scopes.py`
  and `15` from `repin/pin-b7154f951/` (main moved: catalogue.py serves 18 flags since #4227, `15` lines shifted). D03 =
  merged `58660d32f`: e42kit's E42-D03 L-numbers (read at PR #4138's head `9644f23f0`) hold line for line (22 lines
  re-worded, none moved; `repin/linemap-d03.json`), so every sheet whose notes carry a re-qualified "E42-D03 … L…" also
  gets that sources line (G-48). `15` lines the kit cites at the pin: `15:699` (NavRail's Admin item: e42kit's
  `nav_admin` copy gap now cites it), the chrome deviation's `15:702, :711, :2485, :2475` and `15:693` (were
  `:699, :708, :2421, :2411` and `:690`), `15:348` (CMP-033 "Copied"), `16:307` (motion tokens code-only).
- **Self-test:** `python3 -I e42d04kit.py selftest` → 64 PASS, `00-selftest.json` validator exit 0 (0 errors; 195
  WARNs, all Tier-1 `size.control.comfortable` / `size.icon.sm`). It now also proves each carry below on a built node
  (`_kit_checks()`).

### The rulings (gaps/rulings.md, 17:22Z and 18:16Z) as the kit draws them

- **G-30 chrome:** `DEVIATIONS["chrome"]` (the line every shell board prints) now says E10-D02 owns the shell chrome
  and binds the build (80 px TopBar, the Safety cluster at its right, E10-D02:65-73); the boards keep D03's drawn chrome
  (48 px bars, CMP-211 at the RightRail's top; `15:2500`) so D03's sheets and these match; two merged specs disagree:
  a **C-row for the owner with E42-D03** (§20 L847-850), not an A-row (§0 L82-87). The four FREEZE… strings are §14's
  (COPY: `tamper.failed.safe`, `dlg.engage.order_entry.list`, `dlg.release.order_entry`, `dlg.maint_off.body`).
- **G-31 ENV badge above the scrim:** `modal(px, dialog, *, env="LIVE", fill=False)` replaces `e42kit.modal()`: the scrim,
  the dialog, then the TopBar's CMP-074 and the StatusBar's CMP-075 badges drawn again **above** both at their chrome
  places (`env_badges_above()`; §11 L570-573, C-2.11, E10-D02:264; a live check aligns them after relayout); `fill=True`
  is the 200 % rule: the dialog fills only the area between the TopBar and the StatusBar (AL-28 L263, FF-15 L513).
- **G-38 selected row:** SCR-135's grid has §4's 24 px expander column (CMP-173's button, L210-211); `audit_row(...,
selected=True)` draws the `check` glyph (CMP-019, `color.text.primary`, `aria-hidden`) at the cell's left edge before
  its chevron (two 12 px `size.icon.sm` glyphs in one 24 px cell, E11-D04:296's convention), keeps the
  `color.surface.selected` fill and notes `aria-selected="true"` (D14 L149, §15 L714). The drawer's h2 and summary stay
  at both sizes (`record_drawer()` already draws both).
- **G-39 one banner per cause:** `maintenance_banners(px, *, mode=True, verified=True, exchange=False)` → D03's
  `banner.maintenance` (or `banner.maintenance_unverified`, CG-32), never also E17-D01's Read-only banner; `exchange=True`
  adds E17-D01's availability banner (`exchange_banner()`, "Exchange feed down — the server is restoring the
  connection", E17-D01:148); both show when both hold (MM-5 L552). `ticket_submit_t2(w=336, *, label_=None)` is the
  ticket's new-risk submit in T2 with the PROPOSED E30-D02 state key `maintenance` "Order entry is paused for
  maintenance." (COPY["maintenance"], §14 L684; `reason()` accepts it; the label a bar unless E30-D02's is passed).
- Also drawn from the rulings: **G-33** the grace words "flag changes" / "audit exports" (D21 L156, PROPOSED A-row to
  D03): `step_up_line("flags"|"audit", grace=s)` and the new `grace_line(cls, seconds)` for `shell(right=…)`; **G-1**
  a running export is busy (`export_control("running")`), **G-3** a confirm waiting on the count read is busy (rung
  state `"busy"`), **G-4** FF-10's confirm in the form-validity form (`validity_button()`, rung state
  `"validity:dlg.conflict_first"`) — all never T2.

### The KIT items (carries.md G-40..G-48), helper by helper (existing signatures kept; new parameters have defaults)

- **G-40** `bar_row(cols, name, px=None)`: Role reads "—" at 1280 and "not recorded" at 2560 as `audit_row()` does (new
  `role_text(px)`; px defaults to the columns' size); the expander cell carries its chevron.
- **G-41** `pager()`: on page 1 the one `admin.newest` notice sits right after Newer, under the pair it describes
  (`vbox "T2 pair and its reason"`), Older after it; the T2 buttons keep e42kit's names "CMP-001 Button (composition) ·
  Newest (T2)" (no more "T2 · Newest"); `t2_notice()`'s lock is decorative (aria-hidden) everywhere it is used: the
  pager, the window section, FF-12's `admin.flags_store`, AD-7's notice.
- **G-42** `append_only()` binds `color.text.tertiary` (§15 L711).
- **G-43** the scrim: `SCRIM`, `scrim(w, h, *, theme="dark")`, `FALLBACKS["SCRIM"]` (also what e42kit's scrim line
  re-qualifies to). The rule is black at `opacity.scrim` in every theme (§15 L700-701, E09-D08 D2), but cvsheet v1
  binds tokens only and `validate_sheet.py` refuses the primitive `palette.black`, so the scrim binds
  `color.surface.sunken` (= palette.black in dark) and `scrim()` refuses a light frame: every D04 dialog board is dark.
  `modal()` uses it; `storyboard()` (M5) keeps e42kit's identical binding.
- **G-44** `ROWS` (AL-2's page 1, board 02's rows with the two named high rows `security.key_policy_violation`
  critical and `backup.downloaded` error, §1 L114-117, record 1,204,118 at row 05, AD-1 L313), `PAGE_ROWS` = 200,
  `CALLED_OUT` = 4, `page_rows(px, cols=None, entries=ROWS, *, n=200, **kw)`, `ROWS_AFTER_BREAK` (the 14:06:02 pages of
  AL-13, AL-14, AD-5: the failed run's Started and critical Failure records above ROWS, §1 L111-114). `entry_rows()`
  and `audit_page()` default to ROWS (not ENTRIES, which keeps §1's list with the failed run first, for the boards
  that index it); `audit_page()` keeps row 200 under the fold unless that would push rows 01-04 out of frame, when the
  fold ends the grid (board 02's 1280 frame; `called_out=`).
- **G-45** `count_text(name, chars, *, typo, color, w, note)`: a count in `type.num.base` beside its words (D02:120,
  :154); used by `count_line()` (FF-8's `dlg.positions`), `maint_on_dialog()`, `flag_scope()` ("+ 1 user override") and
  `flag_dialog()`'s body ("1 user override stays").
- **G-46** `ff2_state(f, *, reload=False)`: the live row "Deployment: ON" (FF-2 L500, D03 OV-2); [Reload now] /
  "Requires reload" only when asked (board 39, its twin 53, sheet 68: `reload=True`); `flag_actions()` keeps [History] on
  every row (the live row: Change… T2 → Security centre → History; `maintenance.mode`: → Maintenance → History); every
  fold marker says "elided" (`fold()`, `flag_groups()`, `flags_page()`, `audit_page()`).
- **G-47** `export_line(px, "limited" | "download_failed", ...)` keeps AL-22's ready flow (export.ready with [Copy] and
  [Download], every unknown fill a bar), the code's line under it (export.limited with Download T2 admin.rate_limited;
  export.download_failed with Download enabled, the "Try again" target) and export.trust last (AL-23 L258).
- **G-48** housekeeping: re-pin (above); the `rbac.view_as` shadow (dropped from INHERITED: e42kit's D09 copy serves
  it); `skeleton(shape, count, w, h, name)` instances CMP-015 with Shape and Count only (the live set; e42kit's adds
  State); `export_control()` returns "CMP-093 AuditActionTrigger (composition) · Signed export…" with CMP-093's marker
  under the control in every state (`fixups()` names its PageHeader slot "primary action · CMP-093 AuditActionTrigger
  (composition)"); `filter_field()` justifies an empty well `end` ("UTC" / the chevron at the right) and takes a node
  value (a bar); `flag_dialog(overrides=None)` draws {n} as a bar; `maint_on_dialog(count=None)` busy, not T2, with a
  D04 skeleton; `why_field()` is "CMP-040 FormField (composition) · Why?" over "CMP-007 TextInput (composition) · two
  lines", its focused well 8 px narrower so the ring keeps the column, `kept=True` a kept reason as a bar;
  `maint_status(..., w=640)` fits its words beside the glyph and the control; `shell(meta=…)` (and `audit_frame()`,
  `audit_page()`, `flags_frame()`) takes a string or a node (board 38's CMP-015), `meta_line(asof)` gives meta.asof or
  "All times UTC" alone (`asof=""`); `audit_cols()` keeps Role ≥ 96 px or its "not recorded" min-content at 2560
  (1,392 px docked: Role 96, Target −13).

### DEVIATION-OK (G-49..G-54): recorded, nothing changed

Bars for values §1 does not give (G-49), compositions and library limits (G-50), shell and chrome placeholders (G-51;
the band's grace line is now drawable, `grace_line()`), token stand-ins and Penpot limits (G-52), frame conventions
(G-53; folds now say "elided"), live-draw and PR evidence checks (G-54) stay as the sheets record them.

### What the folds changed in the kit's data and defaults (re-read pins, G-1..G-39)

- **COPY** regenerated from §14 L675-682 and L684 (`repin/tools/gencopy_new.py`; the self-test re-proves every string):
  192 keys, 153 unchanged, 15 re-worded (`audit.end` and `admin.oldest` are now the unfiltered "No older entries.",
  the filtered form `.filtered`; `audit.limited`; `tamper.failed.safe`, `dlg.engage.order_entry.list`,
  `dlg.release.order_entry`, `dlg.maint_off.body` name FREEZE…; `dlg.release.ingestion`; `export.refused.range`
  ({days}) and `.rate`; `flags.scope` is "Deployment", its other forms `flags.scope.plus_n` / `.plus_one` / `.ignored`;
  `flags.store_down` (G-34); `maint.unreadable` (G-36); both maintenance banners end "Native stops on the exchange are
  unaffected."), 24 new (`audit.count(.one)`, `tamper.page_partial_own`, `export.running.no_pct`, `export.not_sent`,
  `diff.head_started`, `diff.unchanged_n.one`, `flags.scope_account`, `flags.search`, `flags.count(.one)`,
  `flags.fail_closed_value`, `maint.list_lead`, `maint.window_field`, `maint.message_field`,
  `dlg.positions(.unavailable)`, `dlg.conflict_first`, `maintenance` and the `.filtered` forms), 2 gone
  (`admin.export_running`, `admin.conflict_first`).
- **LABELS** re-pinned by content (42 by the map, 74 re-read; `flags.meta` is now "All times UTC · as of 14:02:09", D03's
  meta.asof); new `meta.utc_only`, `maint.marker_off`, `grace.flags` / `grace.audit` (`OTHER_LABELS["grace.flags"]` is
  gone). §14 L683 now keys the anatomy strings (`labels.*`, G-29): `LABEL_KEYS` (82) maps them, and `label()` records the
  copy key (e.g. `labels.col.time`, `labels.act.run_tamper_check`; "—" has no snake-case form and is recorded as
  `labels.word.* '—'`) instead of a copy gap; `action_cell()` records `labels.action.*`.
- **Registry and gaps:** §0 L73-74 now give board 65's slug and board 66's four 1000 × 1728 frames (size "1000×1728");
  the parse skips §4's new tamper-line table (L199-207); 7 of the 8 old SPEC_GAPS are closed by the folds (only
  SCR-006's copy gap stays). ACTIONS: `maintenance.disabled` "Maintenance off" (L540). AUDIT_COLS: G-7's ten columns.
- **Defaults that follow the folded text:** `flags_frame()` meta.asof (G-14); `flag_search()` shows flags.search;
  `flag_scope(f, overrides, *, fail_closed=False)` and `flag_row()` (no "Changed … by …" under fail_closed, FF-12);
  `flag_values()` flags.fail_closed_value; `flag_dialog()` states `store_down` (an unknown outcome: the re-read busy,
  G-34) and `not_saved` (D29); `engage_dialog("ingestion")` no count and no wait; `release_dialog()` and
  `maint_off_dialog()` put "This always needs a fresh code." in its own slot and the marker after it (§11);
  `maint_content()`: the lead-in before maint.list, MM-8 names its state in the list's place (G-2), MM-10/MM-11 keep the
  lead-in, lists and window section (G-35), the marker by control direction (`maint_marker("on"|"off"|"repair")`, G-8);
  `window_section()` keyed fields; `export_line(..., pct_served=False)` (G-17 f); `export_dialog(state="not_sent")`;
  `tamper_footer(state="none"|"page_partial_own")` (G-12); `audit_page(pager_state="none")` (G-13);
  `diff_value()` a long value's first 120 characters then diff.full, `diff_full(unchanged=1)` the singular,
  `diff_full(shape="result", started=True)` (G-11); `rung(..., after=[...])` and its `"busy"` / `"validity:<key>"`
  states; `motion_frame(65)` finds §13's S-rules and flash bullets by content (L652-659, L663-666).

### What every generator must re-check before it re-runs (all 74 re-run after the folds, G-48)

1. **Read the boards branch's spec** and re-pin every local `L`-number, `at(...)` anchor and kit-text guard (`_repin()`,
   `KIT_PAGER`, `PAGER_KIDS`, …): every kit L-number moved, and guards that match kit notes or node names will stop.
2. **Static check** (`repin/tools/static_gen_check.py`, log `repin/static-gen-check.log`): 70 of 74 bind cleanly; gen_22
   L1098 `d.raw('admin.export_running')` (G-1: busy, no key), gen_47 L1149, L1345 `d.raw('admin.conflict_first')` (G-4:
   `dlg.conflict_first`, the validity form), gen_62 L85 `d.OTHER_LABELS["grace.flags"]` (G-33: `LABELS["grace.flags"]`
   "flag changes"), gen_36 L331, L974 `d.LABELS['f.user_agent']` (a key the kit never had: keep it local or drop it).
3. **Drop the local fixes the kit now makes:** Role in bar rows (02, 05, 11, 16, 18, 20, 22, 33, 35; 14, 21), pager
   fixes (06, 07, 17, 18, 28, 36), the page text's tertiary (06, 08), `ready_with()` (23), the meta skeleton (38:
   `shell(meta=d.skeleton(...))`), `why_fit()` (48), status-word fitting (54, 57, 60-62, 73), the window fields' names
   (54, 57, 60-62, 71-73), empty wells, the CMP-093 export trigger (02, 06, 08, …), counts in type.num.base (45, 55,
   74), local skeletons (01, 38, 63, 64, 71), local page rows (02, 03, 08, 10-13, 16-24, 28-31, 34, 35, 37, 69: use
   `d.ROWS` / `d.page_rows()`, and `d.ROWS_AFTER_BREAK` on 13, 14, 34).
4. **Dialogs:** replace `k.modal(...)` with `d.modal(...)` on every dialog board (18, 19, 24, 42, 43, 45-48, 50, 55,
   56, 59, 60, 63, 64, 73, 74) so the ENV badges sit above the scrim (G-31); 28 and 52 size their insets' dialogs to the
   area between the bars (`fill=True`, or `env_badges_above(top=, status=, w=, h=)` for an inset geometry).
5. **Grids:** ten columns now (the expander first; Actor 144, Action 128, Target 144, Environment 80, IP 104): any
   board that indexes columns by position re-checks; the selected-row boards (30-37, 69) pass `selected=` (G-38).
6. **Copy and annotations:** copy keys and gaps change on every board (labels.* keys, the re-worded and new keys above);
   AL-9 picks `audit.end` or `audit.end.filtered`; boards drawing `flags.scope` switch to its `.plus_*` / `.ignored` keys.
7. **Not absorbed (outside G-40..G-48; keep the boards' local forms):** `busy()` puts its in-flight label after the
   confirm (56 and 73 lead the actions row with it); `record_drawer()` draws an unknown session, IP or request_id as a
   bar, not §5's "none" for a stored null (L305-306); AD-6's subject pivot only for a non-null subject_id (35).

## SPEC CAPPED (board cap, 2026-10-24) — hcl-worker-2 (binding from here on; adds to "SPEC MOVED")

**The spec is the folded and capped text:** `docs/design/E42/E42-D04.md` at HEAD
`1ef40f20b` on `design/e42-d04-boards` (local, not pushed): after the fold `8a3bc3f2d`, `9ccf2790c` caps §0 at ten
boards under the orchestrator's lever-4 ruling (2026-10-24 03:11Z) and `1ef40f20b` restates the text outside §0 (the
selection and pass-2 record: `cap/E42-D04-selection.md`). **md5 `29360883820664eba06edd3d25dff0d9`,
1,018 lines.** Both commits edit in place: no line is inserted or deleted, so **every L-number in the kit and in the
sheets holds**. 119 lines differ from `8a3bc3f2d`: 69 by text (L4-5, 32, 62, 69-74, 76-81, 88-89, 159, 184, 193, 251,
253, 260, 500, 504, 506-507, 552, 555, 669, 756-757, 761-788 but 763, 765, 770 and 772, 806, 808, 821-822, 888, 902,
914, 916-918, 923, 927), 50 by Prettier padding only (L67-68, L546-559, L858-894).

- **Drawn: ten boards** (§0 L69-74; L79's PROPOSED deviation): 02 `scr135-populated` ★ · 13 `scr135-tamper-failed`
  ★ S · 14 `tamper-elsewhere` ★ S (1280, three frames) · 32 `scr136-secret` ★ S · 34 `scr136-after-break` S · 41
  `scr145-live-blocked` ★ S · 55 `scr148-turn-on` · 66 `status-sheet` ★ (four 1000 × 1728 frames) · 67 `diff-sheet` ★
  (1280) · 69 `redlines` (both sizes). 22 frames, 7 ★ boards → 14 renders, 24 PNGs (§0 L76-79); build order (L88-89):
  66, 67 → 02, 13, 14 → 32, 34 → 41 → 55 → 69 → exports and renders → PR embeds. No light twin is drawn (L80-81).
- **Not drawn: the other 64**, "not drawn — the text is binding; drawn on request": 01, 03–12, 15–31, 33, 35–40,
  42–54, 56–65, 68, 70–74. Their generators and sheets stay on disk as they are (not re-run under the cap); a board
  drawn on request re-runs its generator against this kit once §0 moves it into a "drawn" list.
- **The kit** (`e42d04kit.py`; backup `e42d04kit.py.pre-cap`):
  - `SPEC_MD5 = "29360883…"` (1ef40f20b, the board-cap restatement, in place; L-numbers unchanged); new
    `SPEC_MD5_FOLD = "818bd877…"` (the fold, where every kit L-number was read: repin/linemap-carries.json's "new"
    side); `SPEC_MD5_MERGED` unchanged.
  - §0's parse reads the cap form: `_cap_lists()` splits a row into "drawn <boards>" and "not drawn — the text is
    binding; drawn on request: <boards>" (or either list alone: L73 has the not-drawn list only); `_RANGE_ITEM`
    reads the unmarked runs (`05–09`, `15–20`, `24–26`, `38–40`, `42–48`, `59–61`, `71–73`); a board listed twice, a
    backward or marked run, an unreadable item or a row with neither list raises. New: `Bd.drawn` (last field,
    default False), `DRAWN` = `CAP_BOARDS` = (2, 13, 14, 32, 34, 41, 55, 66, 67, 69), `S0_LISTED` (each §0 row's
    ids), `FOLD_MARKS` (the fold's 18 ★, 6 S, 4 light). Every other `Bd` field equals the fold's parse on all 74 boards
    (checked against the pre-cap kit run on `8a3bc3f2d`'s text, `_work/capcheck/`) but board 39's ★, below.
  - **Spec gap (new, in `SPEC_GAPS`, closes itself):** §0 L71's not-drawn run `38–40` drops board 39's ★ (`39 ★` at
    the fold's L71; every other ★ is kept, the not-drawn 03, 04, 10, 11, 21–23, 49, 57 and 58 included), so
    `BOARDS[39].star` reads False. Board 39 is not drawn, so no frame, render or PNG count changes; L71 reading
    `38 · 39 ★ · 40` restores it and the kit drops the gap by itself. `00-selftest.json` differs from the fold's only
    by this line in notes.spec_gaps.
  - Self-test re-quotes (same lines, by content): L76 "**Count.** 74 board ids" and "ten are drawn"; L78 "Renders for
    the 7 drawn ★ boards: 14 PNGs, so **24 PNGs**" (was L78's "18" ★); L76-77 "SCR-135 2 × 2 + 3 = 7; SCR-136 2 × 2 =
    4; SCR-145 2; SCR-148 2; motion 0; proofs 4 + 1 + 2 = 7; **22 frames**" (was "144 frames"); L79 "boards 02, 13, 14,
    32, 34, 41, 55, 66, 67 and 69 are drawn; the other 64 are not drawn — the text is binding; drawn on request.";
    L821-822 "Boards 13, 14, 32, 34 and 41, and AL-4's text (board 04 not drawn — the text binds), go to the security
    reviewer". Added: §0's six rows list each id of their Boards cell once, drawn or not; every board keeps the fold's
    marks (6 S, 4 light, ★ within the fold's 18, missing at most 39's). The fold's 18 ★ and 144 frames stay the 74 ids'
    plan (drawn on request), no longer quoted from §0.
  - Every other line check passed unchanged: the cited words on the re-worded lines still stand (AL-16 L251, AL-25
    L260's verbs, FF-2 L500 "Deployment: ON" and "every other row its registry default", FF-8 L506 "Open positions: 2",
    FF-9 L507 "This always needs a fresh code.", MM-5 L552, D24 L159 "board 39 alone draws it"); no kit note quotes a
    changed word.
- **Self-test** (`python3 -I -B e42d04kit.py selftest`): PASS spec 29360883; **67 PASS, 0 FAIL** (64 before: + the
  row, drawn and fold-marks checks); `00-selftest.json` validator 0 errors, 195 warnings (Tier-1
  `size.control.comfortable` / `size.icon.sm`), 115 sections, 496,299 bytes, the largest section 13,449 B; BOARDS 74.
- **What the ten generators must re-check before they re-run** (read, not run here):
  1. md5 guards: gen_13 L75-76 and gen_34 L79-80 pin the literal 818bd877, and their `repin_report()` (gen_13 L340,
     gen_34 L396) wants linemap-carries.json's new_md5 to be today's; gen_14 L101-103, gen_41 L245-247 and gen_55 L726
     compare that new_md5 (818bd877) with `d.SPEC_MD5`. Each refuses until it compares the map with
     `d.SPEC_MD5_FOLD` and today's text with `d.SPEC_MD5`. gen_02 L291, gen_41 L73 and gen_55 L597 compare today's
     text with `d.SPEC_MD5` and pass; gen_32, 66, 67 and 69 have no md5 guard on the kit.
  2. Re-read by content any citation on the 69 re-worded lines above: the L-numbers hold, the words do not (each state
     row the cap touched gains "not drawn — the text binds"; §17 L761-788 re-points its boards to the ten).
  3. An annotation that names another board as the place a thing is drawn names a drawn one, or says the text binds.
  4. `d._spec_checks()` / `d._kit_checks()` (run by gen_02, 13, 14, 32, 34, 55) pass on this tree: 52 checks, 0 failing.

## Live fixes not yet in the generators (SHEET-FIX, live check 2026-10-29)

The live check fixed these on the boards; the committed sheets predate them, and the next regeneration fixes them in
the kit or `cap10.py`.

- SHEET-FIX: 01, AL-18 overlay 'CMP-044 rung-1 dialog · export' (640×369), y 228→216 (centred).
- SHEET-FIX: 01/06, overlay 'CMP-075 EnvBadgeLocal', x 1233→1232 (on the StatusBar badge).
- SHEET-FIX: 06, MM-2 'rung-2 dialog' (640×452), y −4; MM-6 'rung-4 dialog' (640×326), y −2.
- SHEET-FIX: 02, AD-5 'CMP-046 Drawer', y 456→463, h 296→289; 'body (scrolls)' h 187→179; 'drawer body content' y
  166→165.
- SHEET-FIX: 03, AD-3 1280 'CMP-046 Drawer', y 374→377, h 378→375; 'body (scrolls)' clipped to the foot.
- SHEET-FIX: 04, AD-1 1280 drawer y 374→377, h 375; AD-7 drawer y 381→385, h 371→367.
- SHEET-FIX: 09, CMP-173 inline/Full value wrap widths −1..−6 px (ON 134→128, false 228→225, the rest −1/−2).
- SHEET-FIX: roots, h = annotations foot + 80. New heights: 01 9536, 02 5255, 03 3537, 04 3982, 05 3731, 06 7544,
  07 3830, 08 2159, 09 1970, 10 5195.

The live check also notes a kit metric: the two-line 2560 Action label + code box is 33 px against a 32 px row (19 + 14
px); the kit should tighten it.

The CMP-014 Spinner is drawn as the e42kit `SPINNER` fallback (the registry glyph `refresh` at `size.icon.sm`): the
per-set file holds tokens and local icons only, no catalogue components (`gen10/BUILD.md`, Fix pass 4).
