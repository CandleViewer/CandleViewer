# HANDOFF to the executor: #988 E33-D04 (DS contributions and motion) boards, r2, in the per-set Penpot file "E33-D04 boards"

From the design lane. Offline notes only: nothing here was run against Penpot. Set directory: `this folder` (brief: `brief-board.md`, section R2).
Ticket issue #988; boards branch `design/e33-d04-boards` (a checkout of that branch). The r1 hand-off (the appendix below) still holds for everything not restated here.

**r2 = r1 + your r1 draw review** (details: `brief-board.md`, section R2):

1. **Board 06 `motion/focused-row-flash`, the value-change overlay:** must come out TRANSLUCENT (`color.text.primary` at `flash.peak-opacity` 0.25: the Progress cell, its figures and bar visible through it). In r1 the colour-token bind wrote the opaque value over the fill opacity. r2 never binds a translucent fill, reads every one back after the bindings, re-asserts it and reports it in the new result field `translucent`.
2. **The pause icon (01, 02, 04, 05, 06, 07, 08, 10):** two primitive bars (`state-glyph-pause-bar`) in the glyph slot, never the U+2016 text glyph (Inter drew it as one bar). Captions and notes read "pause (two bars)". New gate `no-u2016`. 07 and 10 were not in your list but are the twins of 06 and 05 and carried the same glyph.
3. **⚠ on 03 / 05 / 06: not added, by the spec.** The §9.2 register gives `alert-triangle` to the orphan family only (01 / 04 / 08 rows; 02 shows every board-01 glyph). 03, 05 and 06 draw no orphan state. Nothing to check there.
4. **Typography tokens are not bound (by design in r2):** text is set by value (Inter / JetBrains Mono, size, weight, line height from packages/ui/tokens). Expect `tokens.boards[].reasons` to count texts as "typography by value (r2: not bound; informational)" and `typeGuard` to list each type token's verdict. Not a defect.

**What to do in Penpot (file "E33-D04 boards", page "E33-D04 DS contributions and motion", page id `282ddccc-0450-80b0-8008-d9d894a15d72`):**

- **Redraw 01, 02, 04, 05, 06, 07, 08 and 10 only**, over their r1 boards in the same page. `PART=null` (and board 02's `PART=1`) first removes this ticket's own same-name, TAG-ed board, so the r1 copy goes with it; then board 02's `PART=2`, relayout, export.
- **Keep 03 and 09 as drawn (r1):** no call, no relayout, no re-export. The r2 script differs for them only in the eyebrow / footer version text, so they stay `hpe1ver = r1` on the page; listexp shows `ver r1` for them and that is expected.
- **Dedupe step (after the last board):** `e33-d04-dedupe.js` with `DRY_RUN=true`: expect `kept 10`, `removed 0`, every copy count 1. If an r1 copy of a redrawn board is still listed (an interrupted or renamed leftover), dedupe keeps the copy with the most descendants, then the highest `hpe1ver`: the r2 copy wins for every redrawn board (each grew: 01 / 08 +4, 02 +12, 06 / 07 +2, 04 / 05 / 10 +1) as long as the r2 board is complete. Check with listexp first, then run `DRY_RUN=false`, or delete the stale r1 copy by hand after a read-only list.
- This round: **9 plugin calls**, 1,852 descendants (01 171, 02 440, 04 247, 05 166, 06 247, 07 244, 08 171, 10 166). One tab session is enough (under ~1,500 is the reload threshold: reload once after board 05 to be safe).

## (a) Files and sha256 (source files on disk, before any override)

| File                                                                                                               | sha256                                                             |
| ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `e33-d04-board.js` (2,221 lines, **r2**; assembled from `js/src/*.js` by `js/src/assemble.sh`, do not re-assemble) | `85f1368bed4cd12a9c19ed6781dbef512b4fe029c37e5b3a157a85f9b699a9de` |
| `e33-d04-relayout.js` (unchanged since r1)                                                                         | `0f98768466445a792c4428779b392345a948077899878c48b13091505d871eb3` |
| `e33-d04-dedupe.js` (unchanged since r1)                                                                           | `51a9aadf3a75d5caec303b75c379445f671fe0bee8015eba3cd23d843dba9a04` |
| `probe.js` (unchanged since r1)                                                                                    | `5f2b37587b6fdafc792eab517c32b3195eedab4f48cc64ff21f6a0f6662219d6` |

Other files: `conf` (VER `r2`), `expect.txt`, `brief-board.md`, `tools/` (offline mock + generators + `dumpdiff.py`: ignore), `work/` (`work/mock-r2.txt` / `mock-r2v.txt` are the last mock: 10 boards, failures 0, guards OK 5/5, page row OK, dedupe dry run kept 10, 11 calls, max 248 shapes per call, 0 path segments, 0 HTML-comment tokens; `work/preview-r2/` holds offline previews of the eight boards; `work/r2v-proof/` the negative tests).
Companions in `docs/design/_tools/sheets/common/`: `listexp.js`, `openpage.js`, `pull/export_to_storage.js`, `pull/read_chunk.js`.

**Committed form.** Each script is committed with a `.txt` suffix (`e33-d04-board.js.txt`, `e33-d04-relayout.js.txt`, `e33-d04-dedupe.js.txt`, `probe.js.txt`), byte-identical to what was run: they are plugin function bodies with a top-level `return`, which the repo's ESLint cannot parse as modules. The sha256 values above are of these bytes. Strip `.txt` to run one. The board script is r2, the one that drew 01, 02, 04, 05, 06, 07, 08 and 10; 03 and 09 are r1's drawings (r1 sha256 in the appendix), which r2 changes only in the eyebrow and footer version text. The helpers in `sheets/common/` are shared with the E12 sets.

## (b) Globals

As in the r1 hand-off (b): `WRITER` (probe.js stamp, re-probe after every reload), `FILE_ID` (the "E33-D04 boards" file's id), `PAGE_ID` = `"282ddccc-0450-80b0-8008-d9d894a15d72"`, `ONLY=[n]` (one board per call), `PART`, `PASS`, `DRY_RUN`. Do NOT override `VERSION`, `TAG`, `TICKET`, `PAGE_NAME`, `EXPORT_DIR`.
Guards: `e33-d04-board.js` line 98 (writer stamp) and line 105 (`FILE_ID` id comparison; no file-name comparison); relayout line 28 and dedupe line 22 the same id comparison. A wrong id returns `{abort:"file"}` and touches nothing. Page: found by `PAGE_ID` or name, used only if it holds nothing but `E33-D04 /` frames.

## (c) Library / components / tokens

Primitives only, no components, no shared library; the only `penpot.library` use is `penpot.library.local.tokens` (read-only, line 420). Colour tokens bind under the value guard when the file's local catalog has an active set with an identical value and the matching theme; with an empty catalog nothing fails.
**r2:** translucent fills are never colour-bound (board 06's overlay is the set's only one). The result's `translucent` field reads it back after the bindings: on board 06 expect `{ shapes: 1, ok: 1, off: 0 }` and `fills[0]` = `value-change-overlay`, `intended 0.25`, `read 0.25` (`reasserted: true` is fine: it means the bind overwrote it and the script put it back). A `translucent:` warning is a defect to report. Every other board: `shapes: 0`.
Typography: by value, not bound (item 4 above).

## (d) Call sequence per board

`PART=0` prints the live plan; run it first. Every call is at most 250 shapes (this round max 248), 0 path segments.

| Board | r2 action                                                        | Calls           | Shapes per call (frame counted) |
| ----- | ---------------------------------------------------------------- | --------------- | ------------------------------- |
| 01    | redraw over r1 (pause bars)                                      | 1 (`PART=null`) | 172                             |
| 02    | redraw over r1 (pause bars, "(two bars)" in the table and notes) | 2 (`PART=1,2`)  | 221 + 220                       |
| 03    | keep r1 as drawn                                                 | (1)             | (125; not run)                  |
| 04    | redraw over r1 (pause bars)                                      | 1               | 248                             |
| 05    | redraw over r1 (pause bars)                                      | 1               | 167                             |
| 06    | redraw over r1 (translucent overlay, pause bars)                 | 1               | 248                             |
| 07    | redraw over r1 (pause bars)                                      | 1               | 245                             |
| 08    | redraw over r1 (pause bars)                                      | 1               | 172                             |
| 09    | keep r1 as drawn                                                 | (1)             | (125; not run)                  |
| 10    | redraw over r1 (pause bars)                                      | 1               | 167                             |

Per board (as r1 (d); `draw_any.sh` / `draw_parts.sh` semantics):

1. Build: `board.js` with `WRITER, FILE_ID, PAGE_ID, ONLY=[n]` (+ `PART=1` then `PART=2` for board 02; never re-send PART 1 once PART 2 exists). Success = `abort: None`, `retry: None`, `warnings: []`; `{retry:true}` = re-send the same call (up to 3 times, 6 s apart). A timed-out call keeps running: probe and list before anything else.
2. Wait until `listexp.js` (`TAG="cv:e33-d04"`, `PAGE_ID`) shows the board at `ver == "r2"` with a stable descendant count over two reads (20 s apart).
3. Relayout (`e33-d04-relayout.js`, `ONLY=[n]`, `PAGE_ID`): `PASS="measure"` until `unmeasured` = 0, `PASS="restack"` until `moved` = 0 (at least twice); wait 10 s; measure + restack once more.
4. Shape-count gate: listexp `kids` must equal `expect.txt` (e). Otherwise do NOT export; re-list ~2 min, then investigate.
5. Export 1x PNG (`openpage.js` first) to `WT/<exportAs>`, `WT` = a checkout of the boards branch, the SAME names as r1 (table (f)), overwriting the r1 PNGs of the eight redrawn boards only. The 03 / 09 PNGs and the E33-D02 / D03 PNGs stay untouched. Append `n id exportAs` to `boards.txt`.
6. Inspect each PNG, by eye:
   - **One translucent fill:** board 06, frame `motion/focused-row-flash`, frame 0: the Progress cell of the focused row shows a light veil with "6 of 10 slices · 60 %" and the blue bar clearly visible through it (offline preview: `work/preview-r2/crop-06-overlay.png`). An opaque white or near-white cell = defect.
   - **One pause icon:** board 01, frame `CMP-246/waiting-for-bybit` (or `paused-by-you`): the label's glyph slot shows two separate amber bars before the word (preview: `crop-01-pause.png`; light twin 08: two dark-amber bars, `crop-08-pause.png`). A single bar, an "I" or a "‖" glyph = defect.
   - Plus r1's checks: no re-wrapped pill, Inter + JetBrains Mono only, no tofu (`▸ ✗ ⊘ ↻ ✓ ⚠ ⓘ →`), board 02's simulated strips.

My driver: `draw_mixed_batches.sh <TD> "1 2:2 4 5" "6 7 8 10"` (its window checks are local to the design lane: ignore). The commit side: I commit and push the PNGs (conf `SCOPE="oms-execution"`, `ISSUE="988"`, `VER="r2"`); unless told otherwise the executor only lands the PNGs in the worktree and tells me which.

## (e) Expected descendants (`expect.txt`)

`01 171 · 02 440 · 03 124 · 04 247 · 05 166 · 06 247 · 07 244 · 08 171 · 09 124 · 10 166` (r1 to r2: 01 / 08 167 -> 171, 02 428 -> 440, 04 246 -> 247, 05 / 10 165 -> 166, 06 245 -> 247, 07 242 -> 244; 03 / 09 keep their r1 drawings, whose counts are the same).

## (f) Board list (unchanged names, slugs and exports)

| n   | Slug                       | Export (relative to WT)                                       | Width / mock height | Theme            | r2               |
| --- | -------------------------- | ------------------------------------------------------------- | ------------------- | ---------------- | ---------------- |
| 01  | state-label-specimen       | docs/design/E33/img/E33-D04-01-state-label-specimen.png       | 2220 / 1835         | dark             | redraw           |
| 02  | state-label-cvd            | docs/design/E33/img/E33-D04-02-state-label-cvd.png            | 3200 / 956          | dark             | redraw (2 parts) |
| 03  | progress-card-by-kind      | docs/design/E33/img/E33-D04-03-progress-card-by-kind.png      | 2720 / 983          | dark             | keep r1          |
| 04  | progress-row-in-host       | docs/design/E33/img/E33-D04-04-progress-row-in-host.png       | 1860 / 1835         | dark             | redraw           |
| 05  | builder-shell-spec-sheet   | docs/design/E33/img/E33-D04-05-builder-shell-spec-sheet.png   | 2640 / 1779         | dark             | redraw           |
| 06  | motion-storyboard          | docs/design/E33/img/E33-D04-06-motion-storyboard.png          | 2760 / 1519         | dark             | redraw           |
| 07  | motion-reduced-twins       | docs/design/E33/img/E33-D04-07-motion-reduced-twins.png       | 2760 / 1507         | dark             | redraw           |
| 08  | state-label-specimen-light | docs/design/E33/img/E33-D04-08-state-label-specimen-light.png | 2220 / 1835         | light twin of 01 | redraw           |
| 09  | progress-card-light        | docs/design/E33/img/E33-D04-09-progress-card-light.png        | 2720 / 983          | light twin of 03 | keep r1          |
| 10  | builder-shell-light        | docs/design/E33/img/E33-D04-10-builder-shell-light.png        | 2640 / 1779         | light twin of 05 | redraw           |

## (g) File and page

File **"E33-D04 boards"**, page **`E33-D04 DS contributions and motion`**, id `282ddccc-0450-80b0-8008-d9d894a15d72`.

## (h) Pitfalls

All of the r1 hand-off's (h) still apply (120 s bridge timeout: never re-send, probe and list; PART 1 / `PART=null` deletes and rebuilds its own board; heartbeat; reload ~every 1,500 shapes and re-probe `WRITER`; Penpot re-spaces frame names; stale export after parts; late growth; export timeouts via `pull/`; fonts by `fontId`; Inter re-wrap; duplicates and strays; per-call budgets; no secrets, hosts, links or file ids anywhere). r2 additions:

- A `warnings` entry from `translucent`, `no-u2016`, `regCheck`, `menu-clear` or `fixtures` means a script defect: stop and report that board to the design lane.
- Never run an r2 call against board 03 or 09; if one is run by mistake it simply redraws that board at r2 (harmless, but then re-export it and tell me).

## Appendix: the r1 hand-off (still holds for everything r2 does not restate)

### HANDOFF to the executor: draw #988 E33-D04 (design-system contributions and motion: CMP-246, CMP-118, CMP-245 and the motion storyboard) boards, r1, into a NEW per-set Penpot file

From the design lane. Offline notes only: nothing here was run against Penpot. Set directory: `this folder` (brief: `brief-board.md`).
Ticket issue #988, spec text merged as #4528; the boards PR is on branch `design/e33-d04-boards`. **OWED: all ten boards (r1, carries synced 2026-10-26).** No separate `cvd_sim.py` step: board 02's greyscale and deuteranopia strips are DRAWN INSIDE the board with simulated fills (by value, never bound; captions say so).

#### (a) Files and sha256 (source files on disk, before any override)

| File                                                                                                           | sha256                                                             |
| -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `e33-d04-board.js` (2,164 lines, r1; assembled from `js/src/*.js` by `js/src/assemble.sh`, do not re-assemble) | `0bd310a5ba0c2288b72f75a6ffd29c6ff18198dce1a646c6c1cafe2b2e4f5d9f` |
| `e33-d04-relayout.js`                                                                                          | `0f98768466445a792c4428779b392345a948077899878c48b13091505d871eb3` |
| `e33-d04-dedupe.js`                                                                                            | `51a9aadf3a75d5caec303b75c379445f671fe0bee8015eba3cd23d843dba9a04` |
| `probe.js`                                                                                                     | `5f2b37587b6fdafc792eab517c32b3195eedab4f48cc64ff21f6a0f6662219d6` |

Other files: `conf` (TICKET, SLUGF, VER, WT, EXPDIR, TAG, SCOPE, ISSUE), `expect.txt`, `brief-board.md`, `tools/` (offline mock `penpot_mock988.js`, generators: ignore; the mock is a local copy, never run in Penpot), `work/` (audit, mock logs; `work/mock-r2c.txt` is the last mock: 10 boards, failures 0, 11 calls, max 247 shapes per call).
No `boards.txt`, no `page_id` yet. Companions in `docs/design/_tools/sheets/common/`: `listexp.js`, `openpage.js`, `pull/export_to_storage.js`, `pull/read_chunk.js`.

#### (b) Globals

Globals (a runner overrides each with a regex on its own single `const NAME = ...;` line; the runner does exactly that
on a temp copy and never edits the source file, so keep those lines single-line if the executor's runner does the same):

| Global                                                | Scripts                 | Pass in the NEW per-set file                                                                                                                                                                                                                                                                                                                |
| ----------------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `WRITER`                                              | board, relayout, dedupe | the `storage.hpe1inst` stamp that `js/probe.js` returns for the executor's own plugin instance. Run probe.js (read-only) once per fresh tab, then pass that string as a quoted JS literal. The default `"SET-ME"` makes every write script return `{skip: ...}` and do nothing. The stamp changes after a tab reload: re-probe and re-pass. |
| `FILE_ID`                                             | board, relayout, dedupe | **set FILE_ID to the new file's id** (a quoted string). See (b-guard).                                                                                                                                                                                                                                                                      |
| `PAGE_ID`                                             | board, relayout, dedupe | leave `null` for the very first call (the page does not exist yet), then pass the page id that call returns. This set has no `page_id` file yet: create it from that first answer.                                                                                                                                                          |
| `ONLY`                                                | board, relayout         | `[n]`, exactly one board number of the BOARDS table per call (two numbers, `null`, `[]` or `"SET-ME"` abort `{abort:"only"}` before any write). Relayout: `[n]`, one board found on the page.                                                                                                                                               |
| `PART`                                                | board                   | see (d): `null` = whole board in one call; `0` = print the parts plan and touch nothing; `k` = part k of K.                                                                                                                                                                                                                                 |
| `PASS`                                                | relayout                | `"measure"` or `"restack"` (see (d)).                                                                                                                                                                                                                                                                                                       |
| `DRY_RUN`                                             | dedupe                  | `true` first; dedupe is only needed once, at the end of the set.                                                                                                                                                                                                                                                                            |
| `VERSION`, `TAG`, `TICKET`, `PAGE_NAME`, `EXPORT_DIR` | all                     | do NOT override: they are the `hpe1ver` stamp the checks match, the plugin-data key, ticket prefix, page name and export folder given below.                                                                                                                                                                                                |

**(b-guard) File guard.** `e33-d04-board.js` line 100: `if (FILE_ID === "SET-ME" || !penpot.currentFile || penpot.currentFile.id !== FILE_ID) return { abort: "file", ... }` (writer stamp check: line 93).
Relayout line 28 and dedupe line 22: same id comparison. **No file-NAME comparison, no "New File 1", no hard-coded old id** (grep: 0 hits). So: **set FILE_ID to the new file's id**; nothing to edit or skip.
A wrong id returns `{abort:"file", current:{name}}` (name only) and touches nothing.

**Page guard / creation.** `PAGE_NAME = "E33-D04 DS contributions and motion"` (g). Found by name or `PAGE_ID`, created when missing, used only if it holds nothing but `E33-D04 /` frames (else an `abort` "...foreign-content", nothing touched).
**`ONLY=[]` does not bootstrap the page** (aborts `"only"`), so draw_any.sh's page step does not work: the page is created by the FIRST real call: board 01 (one call, `PART=null`). If it answers `{retry:true, pageId, createdPage:true}` re-send the same call (nothing drawn).
Store the returned `pageId` in a new `page_id` file and pass it as `PAGE_ID` afterwards. `PART > 1` with no page aborts `{abort:"part"}`.

#### (c) Library / components / tokens

**Primitives-only: no component instances, no shared library.** The only `penpot.library` use is line 415, `penpot.library.local.tokens`, read-only (0 `instance`/`createComponent`). The CMP-246 / CMP-118 / CMP-245 surfaces are DRAWN from primitives
(no real components): the boards are specimens. Token binding is OPTIONAL: colours and type styles are token NAMES resolved to literals at build time and bound by name after the build to the file's LOCAL token catalog when it has an ACTIVE set holding an identical value (all 8 hex digits) and the active theme equals the shape's theme.
With an empty catalog nothing fails (literal fills, fonts set directly; the result's `tokens.catalog.note` says "empty token catalog"). My LANE-NOTES (09:02Z) record that this script "uses only local tokens (no library)": for token-bound boards the new file's local catalog must first be loaded with the repo token sets (the #4584 helper "penpot_token_sets.py"; not in this set: ask the design lane or the orchestrator), dark theme active for boards 01-07, light theme for twins 08-10.
Board 02's strip fills are simulated colours by value (never bound, by design); the motion tokens it quotes are text, not bindings.

#### (d) Call sequence per board

`PART=0` prints the live plan: run it first. **11 plugin calls** for the set (max 247 shapes per call, 0 path segments): nine boards are ONE call (`PART=null`), board 02 is TWO parts.

| Board | Calls           | Shapes per call (frame counted) |
| ----- | --------------- | ------------------------------- |
| 01    | 1 (`PART=null`) | 168                             |
| 02    | 2 (`PART=1,2`)  | 215 + 214                       |
| 03    | 1               | 125                             |
| 04    | 1               | 247                             |
| 05    | 1               | 166                             |
| 06    | 1               | 246                             |
| 07    | 1               | 243                             |
| 08    | 1               | 168                             |
| 09    | 1               | 125                             |
| 10    | 1               | 166                             |

Per board (the sequence `draw_any.sh` / `draw_parts.sh` runs; the executor's tooling must do the same):

1. Build: `board.js` with `WRITER, FILE_ID, PAGE_ID, ONLY=[n]` (+ `PART=k` for board 02, in order 1 then 2; a part that times out keeps running: wait, probe and list before part 2). Success = `abort: None`, `retry: None`; `{retry:true}` = page not current yet: re-send the same call (up to 3 times).
2. Wait until `listexp.js` (`TAG="cv:e33-d04"`, `PAGE_ID`) shows the board at `ver == "r1"` with a stable descendant count over two reads (20 s apart).
3. Relayout, each its own call with `e33-d04-relayout.js`, `ONLY=[n]`, `PAGE_ID`: `PASS="measure"` (until `unmeasured` = 0), `PASS="restack"` twice (until `moved` = 0); wait 10 s; measure + restack once more (only after the last part).
4. Shape-count gate: listexp `kids` must equal `expect.txt` (e). Otherwise do NOT export (re-list ~2 min, then investigate).
5. Export 1x PNG (page current: `openpage.js`) to `WT/<exportAs>`, **`WT` = a checkout of the boards branch** (branch `design/e33-d04-boards`), folder `docs/design/E33/img/` (conf `EXPDIR`). `exportAs` is in the board's plugin data and in the result's `exportCommands` (`python3 docs/design/_tools/penpot_export.py <id> <exportAs>`).
   The merged E33-D02 / D03 PNGs in that folder stay untouched. Append `n id exportAs` to a NEW `boards.txt`.
6. Inspect each PNG: no re-wrapped pill, Inter + JetBrains Mono, and **glyph tofu**: the placeholders `▸ ‖ ✗ ⊘ ↻ ✓ ⚠ ⓘ →` (brief OPEN item 2: Inter coverage of `↻ ⊘ ⓘ` is the doubtful one); the ⚠ must be the one-colour outline glyph, never a colour emoji. Board 02: the two strips must show simulated colours (not token colours); the forced-colours strip draws no fills (glyph and word in CanvasText).
   The script's own gates (`regCheck`, `menu-clear`, `fixtures`) report as `warnings`: any warning is a defect to report to the design lane before the next board.

Total 2,073 descendants over the set: two tab sessions of one reload at about the midpoint (boards 01-05 = 1,130; boards 06-10 = 943). The commit side: I commit and push PNGs per board (conf `SCOPE="oms-execution"`, `ISSUE="988"`, `VER="r1"`); unless told otherwise the executor only lands the PNGs in the worktree and tells me which.
My driver: `draw_mixed_batches.sh <TD> "1 2:2 3 4 5" "6 7 8 9 10"` (its window checks are local to the design lane: ignore).

#### (e) Expected descendants (`expect.txt`)

`01 167 · 02 428 · 03 124 · 04 246 · 05 165 · 06 245 · 07 242 · 08 167 · 09 124 · 10 165`

#### (f) Board list (names `E33-D04 / NN <slug>`, x = sum of widths before + (n-1) x 160, y = 0: one row; each frame is a child board named as the spec §9.2 register's Frame cell)

| n   | Slug                       | Export (relative to WT)                                       | Width / mock height | Theme            | Calls |
| --- | -------------------------- | ------------------------------------------------------------- | ------------------- | ---------------- | ----- |
| 01  | state-label-specimen       | docs/design/E33/img/E33-D04-01-state-label-specimen.png       | 2220 / 1835         | dark             | 1     |
| 02  | state-label-cvd            | docs/design/E33/img/E33-D04-02-state-label-cvd.png            | 3200 / 956          | dark             | 2     |
| 03  | progress-card-by-kind      | docs/design/E33/img/E33-D04-03-progress-card-by-kind.png      | 2720 / 983          | dark             | 1     |
| 04  | progress-row-in-host       | docs/design/E33/img/E33-D04-04-progress-row-in-host.png       | 1860 / 1835         | dark             | 1     |
| 05  | builder-shell-spec-sheet   | docs/design/E33/img/E33-D04-05-builder-shell-spec-sheet.png   | 2640 / 1779         | dark             | 1     |
| 06  | motion-storyboard          | docs/design/E33/img/E33-D04-06-motion-storyboard.png          | 2760 / 1519         | dark             | 1     |
| 07  | motion-reduced-twins       | docs/design/E33/img/E33-D04-07-motion-reduced-twins.png       | 2760 / 1507         | dark             | 1     |
| 08  | state-label-specimen-light | docs/design/E33/img/E33-D04-08-state-label-specimen-light.png | 2220 / 1835         | light twin of 01 | 1     |
| 09  | progress-card-light        | docs/design/E33/img/E33-D04-09-progress-card-light.png        | 2720 / 983          | light twin of 03 | 1     |
| 10  | builder-shell-light        | docs/design/E33/img/E33-D04-10-builder-shell-light.png        | 2640 / 1779         | light twin of 05 | 1     |

(Heights are the offline mock's; the real page can differ by a few px, the export rounds a fractional height up.)

#### (g) Page to create in the new file

`E33-D04 DS contributions and motion` (exactly).

#### (h) Pitfalls

- **120 s bridge task timeout.** A call that runs past it answers "timed out" at the bridge but KEEPS RUNNING in the plugin. Never re-send on a timeout or on a "tab suspended" answer
  (a suspended call can still run later, and a re-send then duplicates): probe read-only (`js/probe.js`), list the board (`listexp.js`) and compare its descendants with the parts table first.
  My driver, on a timed-out part: wait 30 s, poll the probe every 30 s for up to ~8 min until the plugin answers, then continue with the next part. Parts run in order, one finished before the next starts.
  An answer of `failed (re-send the whole file)` means the upload never ran: wait for the heartbeat, then re-send.
- **A part that is re-sent.** PART 1 deletes and rebuilds its own board (never re-send it once later parts exist; if you must, run 2..K again). PART k > 1 replaces only its own shapes (idempotent).
- **Heartbeat.** The plugin heartbeat drops for a background or minimised tab (about 4-9 min): keep the drawing tab in front, in its own browser profile, and probe before retrying a write.
- **Reload the tab about every 1,500 built shapes** (a 10k-shape tab session crashed with "Out of Memory"). Wait ~25 s before a reload so the last build is saved; `storage` resets on reload, so re-probe and re-pass `WRITER`.
- **Penpot re-spaces frame names.** A board named `X / NN slug` can read back as `X/NN slug` (and the reverse): the scripts compare NORMALISED names (`\s*/\s*` becomes `/`) plus the plugin-data `TAG` key, and the lister reads plugin data, not names. Never match, rename or delete by raw name.
- **Stale export after parts.** A board can be exported while its last part is still rendering (empty frame, missing footer) although page size and shape count look right. Gate on `expect.txt` (e), re-list until stable, and look at every PNG; if wrong: `openpage.js`, wait, re-export.
- **Late growth and fractional sizes.** Auto-height texts are measured only while their page is active; a board can grow ~8 px after export (run measure + restack again after a 10 s settle, then compare the page size with the PNG). The export rounds a fractional height UP (1980.4 gives 1981): that is not a mismatch. A page that is not active cannot be modified, and the export needs the board's page current in that tab.
- **Export call timeouts.** If the MCP export call times out, export inside the plugin (`shape.export({type:"png",scale:1})` into `storage`) and read the bytes back in 45,000-byte base64 chunks (`pull/export_to_storage.js` + `pull/read_chunk.js`; the pull wrapper), then check the PNG header and the size.
- **Fonts.** `penpot.fonts.findByName("Inter")` and `findById('gfont-inter')` prefix-match Inter Tight. The scripts use `fonts.all.find(f => f.fontId === "gfont-inter")` (and `gfont-jetbrains-mono`); valid variant ids are `regular`, `500`, `600`, `700`. A wrong id shows as serif fallback, re-wrapped lines and ~120 s exports. After the first call read the result's `fonts` histogram (expect only `gfont-inter` and `gfont-jetbrains-mono`) and one text's `fontId` / `fontVariantId`. Never set `fontVariantId` on a token-bound text (it drops the typography binding); the scripts already avoid that.
- **Inter re-wrap pitfall.** Pill and segmented labels sized at 0.62 em per character can wrap (`○ DEMO`, `✓ UTC`). Inspect every PNG's pills and segments; a re-wrapped label is a script defect for the design lane to fix (rN+1), not something to patch by hand in Penpot.
- **Duplicates and strays.** A second copy of a board (same name, same `ver`) or a same-name page with foreign content aborts or is reported (`duplicatePages`); the scripts never delete foreign frames or pages. Delete a duplicate page only manually in the UI, after a read-only probe shows it holds only this ticket's frames. At the end of a set run the dedupe script with `DRY_RUN=true` (expect `removed 0`, every copy count 1) and list the page to confirm one copy per board. The files read for this hand-off (LANE-NOTES, the Penpot memory note) contain no written note on the "E14-D05 stray sweep": ask me or the orchestrator if you meet stray shapes, and do not sweep unknown shapes.
- **Per-call budgets (orchestrator ruling 2026-10-23):** <= 400 shapes and <= 5,000 path segments per call, <= 20,000 segments per page. These scripts draw 0 path segments; the pre-run guard throws before touching anything when a call is over budget.
- **No secrets or addresses anywhere.** Never put a token, MCP key, host, file link or file id in a result you paste, a hand-off, a commit or a PR body (the repo is public). Only the owner signs in; never log in, switch accounts or regenerate a key.
- **E33-D04-specific.** Draw order does not matter (no board reads another). Board 02 is the widest (3200) and the only parted board: do not re-send PART 1 after PART 2 exists.
  The status words are word-first (the accessible-name order) with the glyph slot leading visually: this is intentional (brief OPEN item 3), not a defect. A `warnings` entry from `regCheck`, `menu-clear` or `fixtures` means a script defect: stop and report that board to the design lane.
  Note (2026-10-26): the assembled script was rebuilt only to remove a literal HTML-comment token from a code comment on line 42, which Penpot's SES sandbox rejects. Nothing drawn changes.
