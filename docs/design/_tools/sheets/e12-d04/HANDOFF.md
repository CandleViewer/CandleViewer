# HANDOFF to the executor: draw #240 E12-D04 (SCR-041 interval / bar-mode half and the hotkey ladder) boards, r2, into a NEW per-set Penpot file "E12-D04 boards"

From the design lane. Offline notes only: nothing here was run against Penpot. Set directory: `this folder` (brief: `brief-board.md`; build report: `brief-done.md`, sections "R1 review folds" and "R2 (rulings)"; review: `review-r1.md`).
Ticket issue #240, spec text merged on main as #4682 (the worktree `a checkout of main` sits at the PR head 004ca099c9, same spec content). **OWED: all ten boards, 01–10.** None is skipped (`NOT_DRAWN = []`).

**r1 = the ten boards + review-r1's twelve folds.** **r2 = r1 + the orchestrator's five rulings:** board 01's strip keeps slot 7 "Renko 30" ⊘ and an empty slot 8, and C-26 is drawn as slot 7's accessible description in a labelled margin note ("accessible description of slot 7 (aria-describedby): C-26 … (D03:211)"), not as strip copy; ETHFIUSDT's "—" cells are named a fixture gap in the board notes (02, 07, 09: only the 24 h turnover is "—" by D-8), and the ETHUSDT stand-in bars on 03 stay labelled, with no price labels; idle/preview draws the recorded case with no margin note (the board treats that register row's Copy cell as the recorded preview copy through one commented override in `tools/gen_register.py`; PR 2 fixes the spec row); Record appears only with the not-recorded disclosure (unchanged); board 05's keyboard storyboard stays a sheet of 1:1 popover crops, and its note and caption name the 1280 × 800 window the crops come from. The Kill switch stays enabled in view-as, the announcements stay notes, the user is "alex" and the turnover is "—". No Penpot copy exists yet: everything is a first draw.

## (a) Files and sha256 (source files on disk, before any override)

| File                                                                                                               | sha256                                                             |
| ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `e12-d04-board.js` (3,236 lines, **r2**; assembled from `js/src/*.js` by `js/src/assemble.sh`, do not re-assemble) | `811c1c914d555ef169708442d3948979bae864df76f6f3b916b28b5a8326ca1f` |
| `e12-d04-relayout.js`                                                                                              | `46a999008f0dee64094313bb614f06ef91a0ad898c98a0d28a7f99ecc3910e50` |
| `e12-d04-dedupe.js`                                                                                                | `e469c3d397dc2d42c7c4f1bab2bd40114b8832b7b0d4a9d1406d8c6566bbcb94` |
| `probe.js`                                                                                                         | `5f2b37587b6fdafc792eab517c32b3195eedab4f48cc64ff21f6a0f6662219d6` |

Other files: `conf` (SLUGF `e12-d04`, VER `r2`, WT, TAG, SCOPE, ISSUE), `expect.txt`, briefs, `tools/` (offline mock + generators: ignore; never run in Penpot), `work/` (audit, mock logs, previews; `work/mock-all.txt` is the last mock: 10 boards, failures 0, guards OK 5/5, dedupe dry run kept 10, 55 calls, max 249 shapes per call, 0 path segments, 0 HTML-comment tokens; `work/preview/` holds offline previews of the ten boards).
Companions in `docs/design/_tools/sheets/common/`: `listexp.js`, `openpage.js`, `pull/export_to_storage.js`, `pull/read_chunk.js`.

**Committed form.** Each script is committed with a `.txt` suffix (`e12-d04-board.js.txt`, and so on, including the four helpers in `common/`), byte-identical to what was run: they are plugin function bodies with a top-level `return`, which the repo's ESLint cannot parse as modules. The sha256 values above are of these bytes. Strip `.txt` to run one.

## (b) Globals

Globals (a runner overrides each with a regex on its own single `const NAME = ...;` line; `the runner` does exactly that on a temp copy and never edits the source file, so keep those lines single-line if hcl-2's runner does the same):

| Global                                                | Scripts                 | Pass in the NEW per-set file                                                                                                                                                                                                                                                                                                         |
| ----------------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `WRITER`                                              | board, relayout, dedupe | the `storage.hpe1inst` stamp that `js/probe.js` returns for hcl-2's own plugin instance. Run probe.js (read-only) once per fresh tab, then pass that string as a quoted JS literal. The default `"SET-ME"` makes every write script return `{skip: ...}` and do nothing. The stamp changes after a tab reload: re-probe and re-pass. |
| `FILE_ID`                                             | board, relayout, dedupe | **set FILE_ID to the id of the new file "E12-D04 boards"** (a quoted string). See (b-guard).                                                                                                                                                                                                                                         |
| `PAGE_ID`                                             | board, relayout, dedupe | leave `null` for the very first call (the page does not exist yet), then pass the page id that call returns. Create a `page_id` file from that first answer.                                                                                                                                                                         |
| `ONLY`                                                | board, relayout         | `[n]`, exactly one board number per call, n in 1–10 (two numbers, `null`, `[]`, `"SET-ME"` abort `{abort:"only"}` before any write). Relayout: `[n]`, one board found on the page.                                                                                                                                                   |
| `PART`                                                | board                   | see (d): `0` = print the parts plan and touch nothing; `k` = part k of K. **Every board in this set is over `SHAPE_BUDGET` 400, so every board is parted: `PART=null` throws on all ten.**                                                                                                                                           |
| `PASS`                                                | relayout                | `"measure"` or `"restack"` (see (d)).                                                                                                                                                                                                                                                                                                |
| `DRY_RUN`                                             | dedupe                  | `true` first; dedupe is only needed once, at the end of the set.                                                                                                                                                                                                                                                                     |
| `VERSION`, `TAG`, `TICKET`, `PAGE_NAME`, `EXPORT_DIR` | all                     | do NOT override: `VERSION "r2"` (the `hpe1ver` stamp), `TAG "cv:e12-d04"`, `TICKET "E12-D04"`, `PAGE_NAME "E12-D04 SCR-041 bar modes"`, `EXPORT_DIR "docs/design/E12/img"`.                                                                                                                                                          |

**(b-guard) File guard.** `e12-d04-board.js` line 96: `if (FILE_ID === "SET-ME" || !penpot.currentFile || penpot.currentFile.id !== FILE_ID) return { abort: "file", ... }` (writer stamp check: line 89). Relayout line 29 and dedupe line 22 are the same id comparison. **No file-NAME comparison, no "New File 1", no hard-coded id** (grep: 0 hits in all four files). So: create the file "E12-D04 boards", **set FILE_ID to its id**; nothing to edit or skip. A wrong id returns `{abort:"file", current:{name}}` (name only) and touches nothing.

**Page guard / creation.** `PAGE_NAME = "E12-D04 SCR-041 bar modes"` (spec §0: "one file per design set, `E12-D04 boards`, page `E12-D04 SCR-041 bar modes`, created by name at the boards step and cited by name + id only"), in the file **"E12-D04 boards"**. Found by name or `PAGE_ID`, **created by name on the first call** when missing, used only if it holds nothing but `E12-D04 /` frames (else an `abort` "...foreign-content", nothing touched).
**`ONLY=[]` does not bootstrap the page** (aborts `"only"`): the page is created by the FIRST real call, board 01 `PART=1`. If it answers `{retry:true, pageId, createdPage:true}` re-send the same call (nothing drawn). Store the returned `pageId` in the new `page_id` file and pass it as `PAGE_ID` from then on. `PART > 1` with no page aborts `{abort:"part"}`.

## (c) Library / components / tokens

**Primitives-only: no component instances, no shared library.** The only `penpot.library` use is line 796, `penpot.library.local.tokens`, read-only (0 `createComponent`). Token binding is OPTIONAL: colours and type styles are token NAMES resolved to literals at build time and bound by name after the build to the file's LOCAL token catalog when it has an ACTIVE set holding an identical value and the active theme equals the shape's theme. With an empty catalog nothing fails (literal fills; `tokens.catalog.note` says why).
**Themes are baked (the twins):** 10-tokens holds every value for dark, light and high contrast. **Board 08 is dark at the comfortable density (the density twin of 01), board 09 is drawn with the light values (the light twin of 02's typing/unavailable), board 10 with the high-contrast values (the hc twin of 01, plus a 1:1 crop of the T2 and checked strip states);** 01–07 are dark compact, whatever theme is active. **Export each twin in its own theme as drawn:** if you load the repo token sets for binding, activate light before building 09 and high-contrast before 10 (otherwise they are drawn unbound, by design, with the right colours). Never export 09/10 after re-binding them to dark. Expect 09 on a light canvas (near-white popover and workspace) and 10 with the hc text colours.
**No scrim.** SCR-041 is CMP-017's **non-modal** popover (§10.2): no scrim is drawn on any board. The workspace (TopBar, NavRail, chart, StatusBar) shows at full strength around the popover. The pp/361 scrim helper is kept in the script unused; the mock's re-assert reports 0 scrim shapes. If any board comes out dimmed behind the popover, STOP and report to hcl-1.

## (d) Call sequence per board

`PART=0` prints the live plan: run it first for each board. `PART_SHAPES = 250`: **every call is at most 250 shapes** (max 249) and 0 path segments; **55 calls** for the set. No rotated shapes, no paths.

| Board                      | K   | Shapes per call (frame counted in part 1) | Descendants |
| -------------------------- | --- | ----------------------------------------- | ----------- |
| 01 open-idle-strip         | 6   | 227 × 6                                   | 1361        |
| 02 typing-unrecorded       | 8   | 223 × 3 + 222 × 5                         | 1778        |
| 03 committed-fallback      | 5   | 232 × 4 + 231                             | 1158        |
| 04 switch-storyboard       | 8   | 236 + 235 × 7                             | 1880        |
| 05 keyboard-storyboard     | 3   | 219 + 218 × 2                             | 654         |
| 06 more-in-place           | 6   | 239 + 238 × 5                             | 1428        |
| 07 roles-and-states        | 13  | 249 × 5 + 248 × 8                         | 3228        |
| 08 open-idle-comfortable   | 2   | 229 + 228                                 | 456         |
| 09 typing-unrecorded-light | 2   | 228 × 2                                   | 455         |
| 10 open-idle-hc            | 2   | 234 + 233                                 | 466         |

(The mock's per-call count includes the call's bookkeeping; the descendants column is the gate.)

Per board:

1. Parts 1..K: `board.js` with `WRITER, FILE_ID, PAGE_ID, ONLY=[n], PART=k`, in order. Success = `abort: None`, `retry: None`, `warnings: []`; `{retry:true}` = page not current yet: re-send the same call (up to 3 times, 6 s apart). A part that times out at the bridge keeps running: wait, probe, and list before the next part. The result's `next`/`missing` name the next part; the relayout is named only once nothing is missing. Any `warnings` entry (the d4Checks: `annot-clear`, `view-as`, `no-path`, `t2`, `words`; also `stamp`, `sheet`) is a script defect: stop and report that board to hcl-1.
2. **NO-SCRIM CHECK BY EYE.** After **board 01 PART 1** (the first window frame), export or screenshot that frame: the popover sits below the chart's symbol button over an undimmed workspace, like `work/preview/E12-D04_01_open-idle-strip.png`. Re-check on **board 09 PART 1** (light: no grey wash).
3. Wait until `listexp.js` (`TAG="cv:e12-d04"`, `PAGE_ID`) shows the board at `ver == "r2"` with a stable descendant count over two reads (20 s apart).
4. Relayout, each its own call with `e12-d04-relayout.js`, `ONLY=[n]`, `PAGE_ID`: `PASS="measure"` (until `unmeasured` = 0), `PASS="restack"` until `moved` = 0 (at least twice); wait 10 s; measure + restack once more. Only after the last part.
5. **Expect gate:** listexp `kids` must equal `expect.txt` (e). Otherwise do NOT export; re-list after ~2 min, then investigate.
6. Export 1x PNG (the page must be current: `openpage.js`) to `WT/<exportAs>` = `docs/design/E12/img/E12-D04-NN-<slug>.png` (table (f)); WT per conf is `a checkout of main`; hcl-1 names the boards branch/worktree before the commit. `exportAs` is in the board's plugin data and the result's `exportCommands`. Append `n id exportAs` to a NEW `boards.txt`.
7. Inspect each PNG: Inter + JetBrains Mono only; no re-wrapped pill, chip or button label; captions under the frames, never over the popover; PROPOSED stamps and margin notes on their chips right of the popover; 09 on the light canvas, 10 with the high-contrast colours. Specifically:
   - **Glyphs: check that Inter renders ⊘ ↺ ● ○ ⟳ › (the ⊘ on slot 7 in 01/08/10, ↺ on the Recent rows, ● / ○ in the Recording / Not recorded chips, ⟳ on the busy and loading states of 03, 04 and 07, › in board 06 (SCR-042 in place)). Report any tofu (an empty box or a fallback glyph) with the board and frame; do not hand-fix.**
   - 01 idle/strip: slot 7 reads "⊘ 7 Renko 30" with NO "Not available yet" line under it; the margin note "accessible description of slot 7 (aria-describedby): C-26 "Not available yet" (D03:211); not visible strip copy" sits right of the popover. Same on 08 and 10.
   - 01 idle/preview: ETHUSDT active with its "● Recording" chip, the cells line, no sentence and **no margin note** beside the popover.
   - 03 retained / strip-notice / shell: the ETHFIUSDT plot is the labelled ETHUSDT stand-in, with no price labels.
   - 05 keyboard/storyboard: a sheet of four 1:1 popover crops and the Enter step; the note names the 1280 × 800 window they come from.
   - 07 view-as: the "Kill switch…" button in the StatusBar stays enabled (confirmed); Record is T2 with its reason.
   - 03 shell (R1 F-10): the second stamp chip ("…the lot size." (S-27)) must not spill under the next chip.

Shapes: 12,864 in all. **Reload the tab between boards** and inside the big ones (at the latest every ~1,500 shapes): 07 (3,228) needs a reload after parts 6 and 12; 04 (1,880) and 02 (1,778) each need one after part 6; 01 (1,361), 06 (1,428) and 03 (1,158) each fit one tab session. Reload only between parts, after the listing is stable. The commit side: I commit and push the PNGs (conf `SCOPE="charting-ui"`, `ISSUE="240"`, `VER="r2"`); unless told otherwise hcl-2 only lands the PNGs in the worktree and tells me which.

## (e) Expected descendants (`expect.txt`)

`01 1361 · 02 1778 · 03 1158 · 04 1880 · 05 654 · 06 1428 · 07 3228 · 08 456 · 09 455 · 10 466` (equal to the mock's final shape counts in `work/mock-all.txt`).

## (f) Board list (names `E12-D04 / NN <slug>`, one row at y = 0, 160 px apart; each frame is a child board named as the spec §18.1 register's Frame cell, a 1280 × 800 window (§0); board 05's storyboard frame is a 1280 × 800 sheet of 1:1 crops)

| n   | Slug                    | Export (relative to WT)                                    | Width / mock height | Theme                                  | Frames | Calls |
| --- | ----------------------- | ---------------------------------------------------------- | ------------------- | -------------------------------------- | ------ | ----- |
| 01  | open-idle-strip         | docs/design/E12/img/E12-D04-01-open-idle-strip.png         | 4080 / 1295         | dark, compact                          | 3      | 6     |
| 02  | typing-unrecorded       | docs/design/E12/img/E12-D04-02-typing-unrecorded.png       | 5440 / 1219         | dark, compact                          | 4      | 8     |
| 03  | committed-fallback      | docs/design/E12/img/E12-D04-03-committed-fallback.png      | 4080 / 1219         | dark, compact                          | 3      | 5     |
| 04  | switch-storyboard       | docs/design/E12/img/E12-D04-04-switch-storyboard.png       | 6800 / 1231         | dark, compact                          | 5      | 8     |
| 05  | keyboard-storyboard     | docs/design/E12/img/E12-D04-05-keyboard-storyboard.png     | 2720 / 1219         | dark, compact                          | 2      | 3     |
| 06  | more-in-place           | docs/design/E12/img/E12-D04-06-more-in-place.png           | 4080 / 1168         | dark, compact                          | 3      | 6     |
| 07  | roles-and-states        | docs/design/E12/img/E12-D04-07-roles-and-states.png        | 9520 / 1244         | dark, compact                          | 7      | 13    |
| 08  | open-idle-comfortable   | docs/design/E12/img/E12-D04-08-open-idle-comfortable.png   | 1360 / 1376         | dark, comfortable (density twin of 01) | 1      | 2     |
| 09  | typing-unrecorded-light | docs/design/E12/img/E12-D04-09-typing-unrecorded-light.png | 1360 / 1324         | light twin of 02                       | 1      | 2     |
| 10  | open-idle-hc            | docs/design/E12/img/E12-D04-10-open-idle-hc.png            | 1360 / 1390         | high-contrast twin of 01               | 1      | 2     |

(Heights are the offline mock's after relayout; the real page can differ by a few px, the export rounds a fractional height up.)

## (g) File and page to create

File **"E12-D04 boards"** (new, per set); page **`E12-D04 SCR-041 bar modes`** (exactly, spec §0), created by name by the first call (board 01 PART 1).

## (h) Pitfalls

- **120 s bridge task timeout.** A call that runs past it answers "timed out" at the bridge but KEEPS RUNNING in the plugin. Never re-send on a timeout or a "tab suspended" answer: probe read-only (`js/probe.js`), list the board (`listexp.js`) and compare its descendants with the parts table first. Parts run in order, one finished before the next starts.
- **A part that is re-sent.** PART 1 deletes and rebuilds its own board (never re-send it once later parts exist; if you must, run 2..K again). PART k > 1 replaces only its own shapes (idempotent).
- **Heartbeat.** The plugin heartbeat drops for a background or minimised tab (about 4–9 min): keep the drawing tab in front and probe before retrying a write.
- **Reload the tab about every 1,500 built shapes** (a 10k-shape tab session crashed with "Out of Memory"). Wait ~25 s before a reload so the last build is saved; `storage` resets on reload, so re-probe and re-pass `WRITER`.
- **Penpot re-spaces frame names** (`X / NN slug` can read back as `X/NN slug`): the scripts compare normalised names plus the plugin-data `TAG`; never match, rename or delete by raw name.
- **Stale export after parts.** Gate on `expect.txt` (e), re-list until stable, and look at every PNG; if wrong: `openpage.js`, wait, re-export.
- **Export call timeouts.** If the MCP export times out, export inside the plugin into `storage` and read it back in 45,000-byte base64 chunks (`pull/export_to_storage.js` + `pull/read_chunk.js`), then check the PNG header and size. Board 07 (9520 wide) is the likeliest to need this.
- **Fonts.** The scripts use `fonts.all.find(f => f.fontId === "gfont-inter")` and `gfont-jetbrains-mono`; after the first call read the result's `fonts` histogram (expect only those two).
- **Dedupe (after the last board):** `e12-d04-dedupe.js` with `DRY_RUN=true`: expect `kept 10`, `removed 0`, every copy count 1.
- **Per-call budgets (orchestrator ruling 2026-10-23):** ≤ 400 shapes and ≤ 5,000 path segments per call; these scripts stay ≤ 250 shapes and draw 0 path segments.
- **No secrets or addresses anywhere.** Never put a token, MCP key, host, file link or file id in a result you paste, a hand-off, a commit or a PR body (the repo is public).
- **E12-D04-specific.** Board 07 is the long one (13 calls, two reloads). The workspace around the popover is E15-D03's compact chrome (pp/361's parts, byte-identical), with no scrim. Words that look like placeholders are intended: the register captions print the spec's §18.1 cells verbatim beside the filled frame words ({user} is "alex", the session user "robin · Owner"). idle/preview's caption prints the overridden Copy cell ("Recording (E08-D05 D-7, …)") by ruling 3, not the spec's "S-10"; that is expected until PR 2 fixes the spec row. The PROPOSED stamps and the plain margin notes (including slot 7's accessible-description note) are design annotations, not UI. The chart bars are recorded data (BTCUSDT klines, ETHUSDT prints); ETHFIUSDT's plot is a labelled ETHUSDT stand-in.
