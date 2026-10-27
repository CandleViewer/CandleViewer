# HANDOFF to the executor: draw #241 E12-D05 (SCR-031 chart settings, General tab) boards, r2, into a NEW per-set Penpot file "E12-D05 boards"

From the design lane. Offline notes only: nothing here was run against Penpot. Set directory: `this folder` (brief: `brief-board.md`; build report: `brief-done.md`, sections "R1 review folds" and "R2 (rulings)"; review: `review-r1.md`).
Ticket issue #241, spec text merged on main as #4669 (the worktree `a checkout of main` sits at the PR head cec8310a6d, same spec content). **OWED: all ten boards, 01–10.** None is skipped (`NOT_DRAWN = []`).

**r1 = the ten boards + review-r1's sixteen folds.** **r2 = r1 + the orchestrator's four rulings:** the scroll frame on 01/08/10 is labelled a specimen of CMP-043's 640 px cap (15:465–466), not a register row; 05 partial-apply accepted as drawn (3 of 4, C-25 as the margin note); the two Reset confirm bodies on 07 carry a PROPOSED stamp "PROPOSED copy row, E12-D05 copy deck (boards PR)"; 04/09 specimen 7 (Renko `atr:14`) is redrawn in D03 board 05's "Renko, atr: typed" form (✕ + C-12 in the message line, nothing sent); W-22, W-12, W-25 stay as annotations. No Penpot copy exists yet: everything is a first draw.

## (a) Files and sha256 (source files on disk, before any override)

| File | sha256 |
| --- | --- |
| `e12-d05-board.js` (3,332 lines, **r2**; assembled from `js/src/*.js` by `js/src/assemble.sh`, do not re-assemble) | `fe2c13b1febadab5f9b0bdee578c3cc45065e6eb11a0a0db650dcb8c54343501` |
| `e12-d05-relayout.js` | `0d8ae043a878334d44fb0f3f22b28c48494d086391958ad5b2a801fc99178911` |
| `e12-d05-dedupe.js` | `96f07e809b6cbd590199b2e368833e76f9c8adf1b12440c0350ba5255c652f2f` |
| `probe.js` | `5f2b37587b6fdafc792eab517c32b3195eedab4f48cc64ff21f6a0f6662219d6` |

Other files: `conf` (SLUGF `e12-d05`, VER `r2`, WT, TAG, SCOPE, ISSUE), `expect.txt`, briefs, `tools/` (offline mock + generators: ignore; never run in Penpot), `work/` (audit, mock logs, previews; `work/mock-all.txt` is the last mock: 10 boards, failures 0, guards OK 5/5, dedupe dry run kept 10, 39 calls, max 243 shapes per call, 0 path segments, 0 HTML-comment tokens; `work/preview/` holds offline previews of the ten boards).
No `boards.txt`, no `page_id` yet. Companions in `docs/design/_tools/sheets/common/`: `listexp.js`, `openpage.js`, `pull/export_to_storage.js`, `pull/read_chunk.js`.

## (b) Globals

Globals (a runner overrides each with a regex on its own single `const NAME = ...;` line; `the runner` does exactly that on a temp copy and never edits the source file, so keep those lines single-line if hcl-2's runner does the same):

| Global | Scripts | Pass in the NEW per-set file |
| --- | --- | --- |
| `WRITER` | board, relayout, dedupe | the `storage.hpe1inst` stamp that `js/probe.js` returns for hcl-2's own plugin instance. Run probe.js (read-only) once per fresh tab, then pass that string as a quoted JS literal. The default `"SET-ME"` makes every write script return `{skip: ...}` and do nothing. The stamp changes after a tab reload: re-probe and re-pass. |
| `FILE_ID` | board, relayout, dedupe | **set FILE_ID to the id of the new file "E12-D05 boards"** (a quoted string). See (b-guard). |
| `PAGE_ID` | board, relayout, dedupe | leave `null` for the very first call (the page does not exist yet), then pass the page id that call returns. Create a `page_id` file from that first answer. |
| `ONLY` | board, relayout | `[n]`, exactly one board number per call, n in 1–10 (two numbers, `null`, `[]`, `"SET-ME"` abort `{abort:"only"}` before any write). Relayout: `[n]`, one board found on the page. |
| `PART` | board | see (d): `0` = print the parts plan and touch nothing; `k` = part k of K; `null` = the whole board in ONE call (only boards 04 and 09, 135 shapes each, under `SHAPE_BUDGET` 400). |
| `PASS` | relayout | `"measure"` or `"restack"` (see (d)). |
| `DRY_RUN` | dedupe | `true` first; dedupe is only needed once, at the end of the set. |
| `VERSION`, `TAG`, `TICKET`, `PAGE_NAME`, `EXPORT_DIR` | all | do NOT override: `VERSION "r2"` (the `hpe1ver` stamp), `TAG "cv:e12-d05"`, `TICKET "E12-D05"`, `PAGE_NAME "E12-D05 SCR-031 General"`, `EXPORT_DIR "docs/design/E12/img"`. |

**(b-guard) File guard.** `e12-d05-board.js` line 99: `if (FILE_ID === "SET-ME" || !penpot.currentFile || penpot.currentFile.id !== FILE_ID) return { abort: "file", ... }` (writer stamp check: line 92). Relayout line 29 and dedupe line 22 are the same id comparison. **No file-NAME comparison, no "New File 1", no hard-coded id** (grep: 0 hits in all four files). So: create the file "E12-D05 boards", **set FILE_ID to its id**; nothing to edit or skip. A wrong id returns `{abort:"file", current:{name}}` (name only) and touches nothing.

**Page guard / creation.** `PAGE_NAME = "E12-D05 SCR-031 General"` (spec §0, which names the file `E12-D05 boards`), in the file **"E12-D05 boards"**. Found by name or `PAGE_ID`, **created by name on the first call** when missing, used only if it holds nothing but `E12-D05 /` frames (else an `abort` "...foreign-content", nothing touched).
**`ONLY=[]` does not bootstrap the page** (aborts `"only"`): the page is created by the FIRST real call, board 01 `PART=1`. If it answers `{retry:true, pageId, createdPage:true}` re-send the same call (nothing drawn). Store the returned `pageId` in the new `page_id` file and pass it as `PAGE_ID` from then on. `PART > 1` with no page aborts `{abort:"part"}`.

## (c) Library / components / tokens

**Primitives-only: no component instances, no shared library.** The only `penpot.library` use is line 703, `penpot.library.local.tokens`, read-only (0 `createComponent`). Token binding is OPTIONAL: colours and type styles are token NAMES resolved to literals at build time and bound by name after the build to the file's LOCAL token catalog when it has an ACTIVE set holding an identical value and the active theme equals the shape's theme. With an empty catalog nothing fails (literal fills; `tokens.catalog.note` says why).
**Themes are baked (the twins):** 10-tokens holds every value for dark, light and high contrast. **Boards 08 and 09 are drawn with the light values, board 10 with the high-contrast values**, whatever theme is active; 01–07 are dark. **Export each twin in its own theme as drawn:** if you load the repo token sets for binding, activate light before building 08 and 09 and high-contrast before 10 (otherwise they are drawn unbound, by design, with the right colours). Never export 08/09/10 after re-binding them to dark. Expect 08/09 on a light canvas (near-white dialog, light-grey scrimmed workspace) and 10 with the hc text colours (Save #6EA1F5 with dark text).
**Scrim:** the modal scrim is palette.black at `opacity.scrim` 0.6 set BY VALUE and re-asserted after any bind (pp/361 r3's fix); never bound to a token.

## (d) Call sequence per board

`PART=0` prints the live plan: run it first for each parted board. `PART_SHAPES = 250`: **every call is at most 250 shapes** (max 243) and 0 path segments; **39 calls** for the set. No rotated shapes, no paths.

| Board | K | Shapes per call (frame counted in part 1) | Descendants |
| --- | --- | --- | --- |
| 01 general-populated | 3 | 188 + 188 + 187 | 562 |
| 02 chart-types | 5 | 211 × 5 | 1054 |
| 03 bar-modes | 5 | 207 × 2 + 206 × 3 | 1031 |
| 04 validation | 1 (`PART=null`) | 136 | 135 |
| 05 all-panels | 3 | 227 + 227 + 226 | 679 |
| 06 preview | 6 | 239 × 4 + 238 × 2 | 1431 |
| 07 chrome-and-roles | 9 | 243 + 242 × 8 | 2178 |
| 08 general-populated-light | 3 | 188 + 188 + 187 | 562 |
| 09 validation-light | 1 (`PART=null`) | 136 | 135 |
| 10 general-populated-hc | 3 | 188 + 188 + 187 | 562 |

(The mock's per-call count includes the call's bookkeeping; the descendants column is the gate.)

Per board:
1. Parts 1..K (or the single `PART=null` call on 04/09): `board.js` with `WRITER, FILE_ID, PAGE_ID, ONLY=[n], PART=k`, in order. Success = `abort: None`, `retry: None`, `warnings: []`; `{retry:true}` = page not current yet: re-send the same call (up to 3 times, 6 s apart). A part that times out at the bridge keeps running: wait, probe, and list before the next part. The result's `next`/`missing` name the next part; the relayout is named only once nothing is missing. Any `warnings` entry (the d5Checks: `annot-clear`, `view-as`, `no-path`, `t2`, `words`; also `stamp`) is a script defect: stop and report that board to hcl-1.
2. **SCRIM CHECK BY EYE (untested in real Penpot).** After **board 01 PART 1** (the first dialog frame), export or screenshot that frame: the workspace (panel, NavRail, RightRail) must show through the scrim, dimmed but visible, and the TopBar and StatusBar must be unscrimmed, like `work/preview/E12-D05_01_general-populated.png`. If the scrim is opaque black (the token binding overrode the value), STOP and report to hcl-1; do not hand-edit. Re-check on **board 07 PART 1** (reset/general: a second scrim under the CMP-044 confirm; the dialog behind it is dimmer still, but readable) and on **board 08 PART 1** (light: a translucent grey scrim).
3. Wait until `listexp.js` (`TAG="cv:e12-d05"`, `PAGE_ID`) shows the board at `ver == "r2"` with a stable descendant count over two reads (20 s apart).
4. Relayout, each its own call with `e12-d05-relayout.js`, `ONLY=[n]`, `PAGE_ID`: `PASS="measure"` (until `unmeasured` = 0), `PASS="restack"` until `moved` = 0 (at least twice); wait 10 s; measure + restack once more. Only after the last part.
5. **Expect gate:** listexp `kids` must equal `expect.txt` (e). Otherwise do NOT export; re-list after ~2 min, then investigate.
6. Export 1x PNG (the page must be current: `openpage.js`) to `WT/<exportAs>` = `docs/design/E12/img/E12-D05-NN-<slug>.png` (table (f)); WT per conf is `a checkout of main`; hcl-1 names the boards branch/worktree before the commit. `exportAs` is in the board's plugin data and the result's `exportCommands`. Append `n id exportAs` to a NEW `boards.txt`.
7. Inspect each PNG: Inter + JetBrains Mono only; no re-wrapped pill or button label; captions under the frames, never over a dialog; PROPOSED stamps and margin notes on their chips right of the card (07's two Reset stamps sit over the second scrim and must read bright); 08/09 on the light canvas, 10 with the high-contrast colours; 04/09 specimen 7 shows "atr:14" with the caret, the invalid boundary and "✕ ATR bricks are not available yet. Enter a brick size in ticks."

Shapes: 8,329 in all. **Reload the tab between boards** and inside the big ones (at the latest every ~1,500 shapes): 07 (2,178) needs a reload after part 5; 06 (1,431) and 02 (1,054) each fit one tab session. Reload only between parts, after the listing is stable. The commit side: I commit and push the PNGs (conf `SCOPE="charting-ui"`, `ISSUE="241"`, `VER="r2"`); unless told otherwise hcl-2 only lands the PNGs in the worktree and tells me which.

## (e) Expected descendants (`expect.txt`)

`01 562 · 02 1054 · 03 1031 · 04 135 · 05 679 · 06 1431 · 07 2178 · 08 562 · 09 135 · 10 562` (equal to the mock's final shape counts in `work/mock-all.txt`).

## (f) Board list (names `E12-D05 / NN <slug>`, one row at y = 0, 160 px apart; each frame is a child board named as the spec §15.1 register's Frame cell, 1280 × 800 windows at comfortable density; 01/08/10 add the scroll specimen frame "general/populated · <theme> · scrolled to the end")

| n | Slug | Export (relative to WT) | Width / mock height | Theme | Calls |
| -- | -- | -- | -- | -- | -- |
| 01 | general-populated | docs/design/E12/img/E12-D05-01-general-populated.png | 2720 / 1232 | dark | 3 |
| 02 | chart-types | docs/design/E12/img/E12-D05-02-chart-types.png | 5440 / 1194 | dark | 5 |
| 03 | bar-modes | docs/design/E12/img/E12-D05-03-bar-modes.png | 6800 / 1207 | dark | 5 |
| 04 | validation | docs/design/E12/img/E12-D05-04-validation.png | 1360 / 1259 | dark | 1 |
| 05 | all-panels | docs/design/E12/img/E12-D05-05-all-panels.png | 4080 / 1194 | dark | 3 |
| 06 | preview | docs/design/E12/img/E12-D05-06-preview.png | 6800 / 1207 | dark | 6 |
| 07 | chrome-and-roles | docs/design/E12/img/E12-D05-07-chrome-and-roles.png | 10880 / 1207 | dark | 9 |
| 08 | general-populated-light | docs/design/E12/img/E12-D05-08-general-populated-light.png | 2720 / 1232 | light twin of 01 | 3 |
| 09 | validation-light | docs/design/E12/img/E12-D05-09-validation-light.png | 1360 / 1259 | light twin of 04 | 1 |
| 10 | general-populated-hc | docs/design/E12/img/E12-D05-10-general-populated-hc.png | 2720 / 1232 | high-contrast twin of 01 | 3 |

(Heights are the offline mock's after relayout; the real page can differ by a few px, the export rounds a fractional height up.)

## (g) File and page to create

File **"E12-D05 boards"** (new, per set); page **`E12-D05 SCR-031 General`** (exactly), created by name by the first call (board 01 PART 1).

## (h) Pitfalls

- **120 s bridge task timeout.** A call that runs past it answers "timed out" at the bridge but KEEPS RUNNING in the plugin. Never re-send on a timeout or a "tab suspended" answer: probe read-only (`js/probe.js`), list the board (`listexp.js`) and compare its descendants with the parts table first. Parts run in order, one finished before the next starts.
- **A part that is re-sent.** PART 1 deletes and rebuilds its own board (never re-send it once later parts exist; if you must, run 2..K again). PART k > 1 replaces only its own shapes (idempotent).
- **Heartbeat.** The plugin heartbeat drops for a background or minimised tab (about 4–9 min): keep the drawing tab in front and probe before retrying a write.
- **Reload the tab about every 1,500 built shapes** (a 10k-shape tab session crashed with "Out of Memory"). Wait ~25 s before a reload so the last build is saved; `storage` resets on reload, so re-probe and re-pass `WRITER`.
- **Penpot re-spaces frame names** (`X / NN slug` can read back as `X/NN slug`): the scripts compare normalised names plus the plugin-data `TAG`; never match, rename or delete by raw name.
- **Stale export after parts.** Gate on `expect.txt` (e), re-list until stable, and look at every PNG; if wrong: `openpage.js`, wait, re-export.
- **Export call timeouts.** If the MCP export times out, export inside the plugin into `storage` and read it back in 45,000-byte base64 chunks (`pull/export_to_storage.js` + `pull/read_chunk.js`), then check the PNG header and size.
- **Fonts.** The scripts use `fonts.all.find(f => f.fontId === "gfont-inter")` and `gfont-jetbrains-mono`; after the first call read the result's `fonts` histogram (expect only those two).
- **Dedupe (after the last board):** `e12-d05-dedupe.js` with `DRY_RUN=true`: expect `kept 10`, `removed 0`, every copy count 1.
- **Per-call budgets (orchestrator ruling 2026-10-23):** ≤ 400 shapes and ≤ 5,000 path segments per call; these scripts stay ≤ 250 shapes and draw 0 path segments.
- **No secrets or addresses anywhere.** Never put a token, MCP key, host, file link or file id in a result you paste, a hand-off, a commit or a PR body (the repo is public).
- **E12-D05-specific.** Board 07 is the long one (9 calls). The workspace behind the dialog is E15-D03's compact chrome (pp/361's parts, byte-identical). Words that look like placeholders are intended: the register captions print the spec's §15.1 cells verbatim beside the filled frame words ({user} is "alex", the session user "robin · Owner"). The PROPOSED stamps and the plain margin notes are design annotations, not UI.
