# HANDOFF to the drawing agent: draw #176 E08-D08 (SCR-104 scanner panel) boards, r2, into a NEW per-set Penpot file "E08-D08 boards"

From the design lane. Offline notes only: nothing here was run against Penpot. Set directory: `this folder` (brief: `brief-board.md`; build report: `brief-done.md`, section "R1 review folds + resync (r2, 2026-10-28)"; review: `review-r1.md`).
Ticket issue #176, spec text merged on main as #4825 (merge commit 43c5ebdd86, approved head 779a70fe). Spec §0 is the frame register and board table. **OWED: all ten boards, 01-10.** None is skipped.

**r2 = r1 + the review folds + the resync to the merged text:** H1 filter-consistent rows (every drawn row passes every active filter; new d8Checks rule 8 `filters`); H2/M3 the filter-bar notes take their real height, the link sits on its own line under the sentence where it does not fit beside it (W-3 Regime), and rule 1b (no text past the pane's right edge); L6 the save dialog's Name field holds "Funding and 24 h change"; the cites re-pointed to base `2cf551f4af`; wording of board 01's pane note and board 02's Names stamp. **M4 (orchestrator ruling): board 01 shows 16 of 24 rows (15 of 24 in the row-menu-viewer frame), with the caption line "N of 24 rows are visible at the 1280 x 800 reference; the rest scroll ...". The visible subset plus the caption is the ruling; do not try to fit a 17th row.** Boards 01 and 08 carry that caption. No Penpot copy exists yet: everything is a first draw.

## (a) Files and sha256 (source files on disk, before any override)

| File                                                                                                               | sha256                                                             |
| ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `e08-d08-board.js` (3,080 lines, **r2**; assembled from `js/src/*.js` by `js/src/assemble.sh`, do not re-assemble) | `8c36e3331b2244364caab27d0b91130dab292364ed5ee0cc275a227b1fa364c1` |
| `e08-d08-relayout.js` (156 lines)                                                                                  | `12fdcb00030d82b18f8ae6cbfb858fb0b218dbd9cc1aab6b946505a68a1e149b` |
| `e08-d08-dedupe.js` (62 lines)                                                                                     | `cf0d561d400806cb5d1875e32f33b205ec06dfe245c422a60b72e057fe71dcd1` |
| `probe.js` (31 lines)                                                                                              | `5f2b37587b6fdafc792eab517c32b3195eedab4f48cc64ff21f6a0f6662219d6` |

Other files: `conf` (SLUGF `e08-d08`, VER `r2`, WT (a checkout of main), TAG, SCOPE `ingestion`, ISSUE `176`), `expect.txt`, briefs, `tools/` (offline mock and generators: ignore; never run in Penpot), `work/` (`work/mock-all.txt` is the last mock: 10 boards, failures 0, guards OK 5/5, dedupe dry run kept 10, 107 calls, max 246 shapes per call, 0 path segments; `work/preview/` holds offline previews of the ten boards).
No `boards.txt`, no `page_id` yet. Companions in `docs/design/_tools/sheets/common/`: `listexp.js` (set its `TAG` = `cv:e08-d08` and `PAGE_ID`), `openpage.js`, `pull/export_to_storage.js`, `pull/read_chunk.js`.

**Committed form.** Each script is committed with a `.txt` suffix (`e08-d08-board.js.txt`, `e08-d08-relayout.js.txt`, `e08-d08-dedupe.js.txt`, `probe.js.txt`), byte-identical to what was run: they are plugin function bodies with a top-level `return`, which the repo's ESLint cannot parse as modules. The sha256 values above are of these bytes. Strip `.txt` to run one. The helpers in `sheets/common/` are shared with the other sets. The offline `tools/`, `work/` and `js/src/` folders named above are not committed.

## (b) Globals

A runner overrides each with a regex on its own single `const NAME = ...;` line (the runner does this on a temp copy and never edits the source); keep those lines single-line.

| Global                                                | Scripts                 | Pass in the NEW per-set file                                                                                                                                                                                                                        |
| ----------------------------------------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `WRITER`                                              | board, relayout, dedupe | the `storage.hpe1inst` stamp that `js/probe.js` returns for your own plugin instance (read-only; once per fresh tab; re-probe and re-pass after a tab reload). The default `"SET-ME"` makes every write script return `{skip: ...}` and do nothing. |
| `FILE_ID`                                             | board, relayout, dedupe | **the id of the new file "E08-D08 boards"** (quoted string). See (b-guard).                                                                                                                                                                         |
| `PAGE_ID`                                             | board, relayout, dedupe | leave `null` for the very first call (the page does not exist yet), then pass the page id that call returns; keep it in a new `page_id` file.                                                                                                       |
| `ONLY`                                                | board, relayout         | `[n]`, exactly one board number per call, n in 1-10 (two numbers, `null`, `[]`, `"SET-ME"` abort `{abort:"only"}` before any write).                                                                                                                |
| `PART`                                                | board                   | `0` = print the parts plan, touch nothing; `k` = part k of K. **Every board is over `SHAPE_BUDGET` 400, so all ten are parted: `PART=null` throws on all of them.**                                                                                 |
| `PASS`                                                | relayout                | `"measure"` or `"restack"` (see (d)).                                                                                                                                                                                                               |
| `DRY_RUN`                                             | dedupe                  | `true` first; dedupe is only needed once, at the end of the set.                                                                                                                                                                                    |
| `VERSION`, `TAG`, `TICKET`, `PAGE_NAME`, `EXPORT_DIR` | all                     | do NOT override: `VERSION "r2"`, `TAG "cv:e08-d08"`, `TICKET "E08-D08"`, `PAGE_NAME "E08-D08 SCR-104 Scanner"`, `EXPORT_DIR "docs/design/E08/img"`.                                                                                                 |

**(b-guard) Guards (line numbers verified in the r2 files).**

- `e08-d08-board.js` line 91: writer-stamp check (`storage.hpe1inst !== WRITER` returns `{skip}`); **line 98: file guard** `if (FILE_ID === "SET-ME" || !penpot.currentFile || penpot.currentFile.id !== FILE_ID) return { abort: "file", ... current: {name} }`; line 101: the `ONLY` check (`abort "only"`).
- `e08-d08-relayout.js`: writer line 28, **file guard line 29**, ONLY check line 30. `e08-d08-dedupe.js`: writer line 21, **file guard line 22**.
- No file-NAME comparison, no "New File 1", no hard-coded id (grep: 0 hits in all four files). So: create the file "E08-D08 boards", set FILE_ID to its id; nothing to edit or skip. A wrong id returns `{abort:"file", current:{name}}` (name only) and touches nothing.

**Page guard / creation.** `PAGE_NAME = "E08-D08 SCR-104 Scanner"` (spec §0: per-set file `E08-D08 boards`, page `E08-D08 SCR-104 Scanner`, cited by name and page id only, never a host or file link), in the file **"E08-D08 boards"**. Found by name or `PAGE_ID`, **created by name on the first call** when missing (board.js lines 2870-2875), used only if it holds nothing but `E08-D08 /` frames (else `abort` "...foreign-content", lines 2856/2860, nothing touched).
`ONLY=[]` does not bootstrap the page: the page is created by the FIRST real call, board 01 `PART=1`. If it answers `{retry:true, pageId, createdPage:true}` (line 2886) re-send the same call (nothing drawn). Store the returned `pageId` in `page_id` and pass it as `PAGE_ID` from then on. `PART > 1` with no page aborts `{abort:"part"}` (line 2871).

## (c) Library / components / tokens

**Primitives-only: no component instances, no shared library.** Token binding is OPTIONAL: colours and type styles are token NAMES resolved to literals at build time and bound by name after the build to the file's LOCAL token catalog when it has an ACTIVE set holding an identical value and the active theme equals the shape's theme. With an empty catalog nothing fails (literal fills).
**Themes are baked (the twins), per spec §0:** boards 01-07 are dark compact; **08 is the light twin of 01, 09 the light twin of 06 (stale), 10 the high-contrast twin of 02 (criteria menu)**. (Not a comfortable-density twin: this set has none; comfortable density and the 200 % card reflow are "specified, drawn on request".) **Export the light boards (08, 09) and the hc board (10) each in its own theme as drawn:** if you load the repo token sets, activate light before building 08 and 09 and high-contrast before 10 (otherwise they are drawn unbound, by design, with the right colours). Never export them after re-binding to dark. Expect 08 and 09 on a light canvas (near-white pane and workspace) and 10 with the hc text colours.
**Scrim: only under board 07's two dialogs** (CMP-043 save dialog, CMP-044 delete confirm), set by value at `opacity.scrim` = 0.6, below the TopBar to above the StatusBar, re-asserted after the bind (80-parts; the result's `scrims` reads `{off: 0, opacity: [0.6]}`). Every other board has NO scrim: the SCR-104 pane is docked in a live workspace shown at full strength. If any board other than 07's two dialog frames comes out dimmed, STOP and report to the design lane.

## (d) Call sequence per board

`PART=0` prints the live plan: run it first for each board. `PART_SHAPES = 250`: **every call is at most 250 shapes** (max 246) and 0 path segments; **107 calls** for the set (parts plan from `work/mock-all.txt`; frame counted in part 1).

| Board               | K   | Shapes per call (mock) | Final shapes (gate) | Reload the tab after part                 |
| ------------------- | --- | ---------------------- | ------------------- | ----------------------------------------- |
| 01 populated        | 8   | 246 x 6, 245 x 2       | 1965                | 6                                         |
| 02 criteria-menu    | 9   | 236, 235 x 8           | 2115                | 6                                         |
| 03 range-editor     | 10  | 232 x 2, 231 x 8       | 2311                | 6                                         |
| 04 capped           | 5   | 220, 219 x 4           | 1095                | none (fits one session)                   |
| 05 result-states    | 7   | 222, 221 x 6           | 1547                | none, or after 6 if the tab has been used |
| 06 stale            | 14  | 245 x 14               | 3429                | 6 and 12                                  |
| 07 presets          | 23  | 242 x 10, 241 x 13     | 5552                | 6, 12 and 18                              |
| 08 populated-light  | 8   | 246 x 6, 245 x 2       | 1965                | 6                                         |
| 09 stale-light      | 14  | 245 x 14               | 3429                | 6 and 12                                  |
| 10 criteria-menu-hc | 9   | 236, 235 x 8           | 2115                | 6                                         |

(The mock's per-call count includes the call's bookkeeping; the final-shapes column is the gate. Total 25,523 shapes. Reload roughly every 1,500 built shapes; only between parts, after the listing is stable.)

Per board:

1. Parts 1..K: `board.js` with `WRITER, FILE_ID, PAGE_ID, ONLY=[n], PART=k`, in order. Success = `abort: None`, `retry: None`, `warnings: []`; `{retry:true}` = page not current yet: re-send the same call (up to 3 times, 6 s apart). A part that times out at the bridge keeps running: wait, probe, and list before the next part. `next`/`missing` name the next part; the relayout is named only once nothing is missing. Any `warnings` entry (the d8Checks: `annot-clear` incl. rule 1b, `view-as`, `no-path`, `t2`, `advice`, `estimated`, `words`, `filters`; also `stamp`, `sheet`, `scrim`) is a script defect: stop and report that board to the design lane.
2. **SCRIM CHECK BY EYE.** After **board 01 PART 1** export or screenshot the first frame: the pane docked in the workspace, undimmed (like `work/preview/` board 01). Re-check on **board 08 PART 1** (light: no grey wash). Board 07 is the only board with a scrim, under its two dialog frames.
3. Wait until `listexp.js` (`TAG="cv:e08-d08"`, `PAGE_ID`) shows the board at `ver == "r2"` with a stable descendant count over two reads (20 s apart).
4. Relayout, each its own call with `e08-d08-relayout.js`, `ONLY=[n]`, `PAGE_ID`: `PASS="measure"` (until `unmeasured` = 0), `PASS="restack"` until `moved` = 0 (at least twice); wait 10 s; measure + restack once more. Only after the last part.
5. **Expect gate:** listexp `kids` must equal `expect.txt` (e). Otherwise do NOT export; re-list after ~2 min, then investigate.
6. Export 1x PNG (the page must be current: `openpage.js`) to `WT/<exportAs>` = `docs/design/E08/img/E08-D08-NN-<slug>.png` (table (f)); WT per conf is a checkout of main; the design lane names the boards branch before the commit. `exportAs` is in the board's plugin data and the result's `exportCommands`. Append `n id exportAs` to a NEW `boards.txt`. **Export the light boards (08, 09) and the hc board (10) with their theme** (see (c)).
7. Inspect each PNG: Inter + JetBrains Mono only; no re-wrapped pill, chip or button label; captions under the frames; PROPOSED stamps and margin notes where the mock puts them; 08/09 on the light canvas, 10 with the hc colours. Specifically:
   - **Text decoration (the mock cannot see it): check by eye** (a) the **struck-through removed chip** (board 07, the "a removed criterion" frame: the removed filter's chip text is struck through, not just greyed), and (b) the **link underline** on the filter-bar note links (board 01 note, board 02 derivation note, board 02 frame 2 W-3/W-4) and wherever a link is drawn. Report any missing decoration with board and frame; do not hand-fix.
   - **Derivation note link (H2/M3), after the relayout:** on board 02 (and hc twin 10) criteria/derivation-note, and board 01's note, the W-3 (Regime) note sentence wraps at the content width and its **link sits on its own line under the sentence at the sentence's x**; W-4's sentence and link stay on one line. Nothing overlaps the next item; no text ends past the pane's right edge. Mock numbers: board 01 note x 141..878 (one line) with the link at x 141 on the next line; board 02 frame 2 W-4 + link 1474..2155 against the pane's right edge 2238. Re-check after the relayout restack, which can move things.
   - **Board 01 shows 16 of 24 rows (populated) and 15 of 24 (row-menu-viewer), with the caption line "16 of 24 rows are visible at the 1280 x 800 reference; the rest scroll ..." (orchestrator ruling: the visible subset plus the caption).** Same on 08. Do not count it a defect that rows 17-24 are not drawn.
   - Rows are filter-consistent (H1): on board 02's frames every drawn row satisfies every active chip's bound; tape speed z-scores of recorded rows are >= 2.00; live-only rows show "—" in the recorded-history cells.
   - **Glyphs:** check that Inter renders the symbols the boards use (⊘ ↺ ● ○ ⟳ › Δ and the sparkline/estimated markers). Report any tofu with board and frame; do not hand-fix.
   - 07 save dialog: Name field "Funding and 24 h change", marked illustrative in the caption; the scrim only under the CMP-043 and CMP-044 dialogs.
   - Known, accepted in the mock (L7, L8): the cross-block caption/header samples ("Turnover 24 h" x "Instruments where Funding % is at most 0" etc.) and board 05's two-row bar are unchanged from r1; look at them in the PNGs and report only if they are visibly colliding.

## (e) Expected descendants (`expect.txt`)

`01 1965 · 02 2115 · 03 2311 · 04 1095 · 05 1547 · 06 3429 · 07 5552 · 08 1965 · 09 3429 · 10 2115` (equal to the mock's final shape counts in `work/mock-all.txt`).

## (f) Board list (names `E08-D08 / NN <slug>`, one row at y = 0, 160 px apart; each frame is a child board, a 1280 x 800 window holding the pane at its 784 px reference width, compact)

| n   | Slug             | Export (relative to WT)                             | Width / mock height | Theme                             | Frames | Calls |
| --- | ---------------- | --------------------------------------------------- | ------------------- | --------------------------------- | ------ | ----- |
| 01  | populated        | docs/design/E08/img/E08-D08-01-populated.png        | 2720 / 1336         | dark                              | 2      | 8     |
| 02  | criteria-menu    | docs/design/E08/img/E08-D08-02-criteria-menu.png    | 2720 / 1219         | dark                              | 2      | 9     |
| 03  | range-editor     | docs/design/E08/img/E08-D08-03-range-editor.png     | 2720 / 1193         | dark                              | 2      | 10    |
| 04  | capped           | docs/design/E08/img/E08-D08-04-capped.png           | 1360 / 1286         | dark                              | 1      | 5     |
| 05  | result-states    | docs/design/E08/img/E08-D08-05-result-states.png    | 4080 / 1194         | dark                              | 3      | 7     |
| 06  | stale            | docs/design/E08/img/E08-D08-06-stale.png            | 4080 / 1194         | dark                              | 3      | 14    |
| 07  | presets          | docs/design/E08/img/E08-D08-07-presets.png          | 6800 / 1244         | dark, scrim under the two dialogs | 5      | 23    |
| 08  | populated-light  | docs/design/E08/img/E08-D08-08-populated-light.png  | 2720 / 1336         | light twin of 01                  | 2      | 8     |
| 09  | stale-light      | docs/design/E08/img/E08-D08-09-stale-light.png      | 4080 / 1181         | light twin of 06                  | 3      | 14    |
| 10  | criteria-menu-hc | docs/design/E08/img/E08-D08-10-criteria-menu-hc.png | 2720 / 1219         | high-contrast twin of 02          | 2      | 9     |

(Heights are the offline mock's after relayout; the real page can differ by a few px, the export rounds a fractional height up. Board x positions in the mock: 0, 2880, 5760, 8640, 10160, 14400, 18640, 25600, 28480, 32720.)

## (g) File and page to create

File **"E08-D08 boards"** (new, per set); page **`E08-D08 SCR-104 Scanner`** (exactly, spec §0), created by name by the first call (board 01 PART 1).

## (h) Pitfalls

- **120 s bridge task timeout.** A call past it answers "timed out" at the bridge but KEEPS RUNNING in the plugin. Never re-send on a timeout or a "tab suspended" answer: probe read-only (`js/probe.js`), list the board (`listexp.js`) and compare descendants with the parts table first. Parts run in order, one finished before the next starts.
- **A part that is re-sent.** PART 1 deletes and rebuilds its own board (never re-send it once later parts exist; if you must, run 2..K again). PART k > 1 replaces only its own shapes (idempotent).
- **Heartbeat.** The plugin heartbeat drops for a background or minimised tab (about 4-9 min): keep the drawing tab in front and probe before retrying a write.
- **Reload the tab about every 1,500 built shapes** (a 10k-shape tab session crashed with "Out of Memory"). Wait ~25 s before a reload so the last build is saved; `storage` resets on reload, so re-probe and re-pass `WRITER`.
- **Penpot re-spaces frame names** (`X / NN slug` can read back as `X/NN slug`): the scripts compare normalised names plus the plugin-data `TAG`; never match, rename or delete by raw name.
- **Stale export after parts.** Gate on `expect.txt`, re-list until stable, and look at every PNG; if wrong: `openpage.js`, wait, re-export.
- **Export call timeouts.** If the MCP export times out, export inside the plugin into `storage` and read it back in 45,000-byte base64 chunks (`pull/export_to_storage.js` + `pull/read_chunk.js`), then check the PNG header and size. Board 07 (6800 wide) is the likeliest.
- **Fonts.** The scripts use `gfont-inter` and `gfont-jetbrains-mono`; after the first call read the result's `fonts` histogram (expect only those two).
- **Dedupe (after the last board):** `e08-d08-dedupe.js` with `DRY_RUN=true`: expect `kept 10`, `removed 0`, every copy count 1.
- **Per-call budgets (orchestrator ruling 2026-10-23):** <= 400 shapes and <= 5,000 path segments per call; these scripts stay <= 250 shapes and draw 0 path segments.
- **No secrets or addresses anywhere.** Never put a token, MCP key, host, file link or file id in a result you paste, a hand-off, a commit or a PR body (the repo is public).
- **E08-D08-specific.** Board 07 is the longest (23 calls, three reloads). Words that look like placeholders are intended (the register captions print spec cells beside the filled frame words). PROPOSED stamps and margin notes are design annotations, not UI. Every board with market numbers carries the footer "illustrative values, not a market capture".
