# E47-D06 (#1305): render return

- File: `E47-D06 boards` (file id withheld)
- Page: `{"name": "E47-D06 — Canvas accessibility", "id": "f530cfa4-3f66-80e0-8008-e329ce4f23bb"}`
- Drawn under the dark theme. 08 was exported under light; the rest under dark. The theme was set back to dark after the twin (probe on 05: `canvas.fill` #11151a). Before the light export, 08's probe read `canvas.fill` #f6f7f9 (`palette.light.neutral.50`).
- Every board meets these:
  - `lc.count` = `lintd.shapes` + 1;
  - lint `unmeasured` 0 and `unbound` 0;
  - `lc3.cutN` 0;
  - every frame at its md size (1280 x 800) and position, `clip` true, `spill` 0;
  - `lc.h` = `lc.want`. The kit's root heights were estimates; each root was set to the checked `want` (footer end + 80). See the SHEET-FIX lines.
- Each md's Live checks hold. On 02 that includes the dashed surrogate squares, which needed a live fix (see SHEET-FIX).
- Remaining lint findings, each checked live and kept:
  - `overlap`, all by design. On 03-08 these are the CMP-039 inset focus rings over their own focused row's cells. 05 has 7, 06 has 17 (three focused rows), and 03, 04 and 08 have 12-14 each. On 02 there are 35: the hollow plot-stop ring's bounds over the in-plot axis labels, surrogates and tags, plus the surrogate pair that §3.3's overlap rule draws on purpose (13:34:27 / 13:34:38, 13:48:02 / 13:48:55).
  - `lc3.scrollEdge` 4 on 05: texts at the edge of a scrolling grid (its virtualised rows). Not cuts.
- Link underlines: the only link on the page is 05's 'Learn more'. Its underline now takes the label's measured width (73 -> 71 px).
- Boards 05 and 06 (2 101 and 2 704 shapes; the brief estimated about 1 700 and 2 300) did not render in one pass. The tab was reloaded before each of them.
  - **05:** the driver's single `relayout` call ran past the bridge's 120 s, and its queued retries froze the tab (no answer for about 20 minutes). After a reload, touch and relayout ran once per top-level child of the root, in `cv.relayout`'s own bottom-up order. Each child took 2-8 s.
  - **06:** the first pass (05:37-06:40) drew 114 sections, but none of it reached the server, so a reload lost the whole board. Board 06 was drawn again from the start, one section per call (mkcall4), clearing the selection at the end of each call: each new component instance had been left selected, which kept the layer tree expanded. That pass held. Touch and relayout ran split per child, as on 05.
  - Text measurement only happened with the Penpot window in the foreground. In the background, touched texts stayed 1 x 1. With the window raised (`penpot-focus-hpe2.sh`), 06's 38 unmeasured texts measured at once.
- Text that did not paint, or drew at the wrong size:
  - **02:** the frame 'grammar∕cursor-window · dark' was re-set, because 'axis 1' (the first JetBrains Mono text) drew in a fallback serif.
  - **05:** after its reload, the stale frame and the annotation column were re-set, and four top-level texts were re-drawn from their sections (118-121).
  - Every PNG was looked at in full at 1x, and zoomed where needed. No other blank, fallback or wrongly sized text was found.
- Kept as drawn, for the kit owner:
  - Kit-wide: cite marks still carry backticks in the drawn text: `` `05`:100 `` (02), `` `14`:1108 `` / `` `14`:1009 `` (03, 05, 06, 08), `` `05` `` (01, 04, 07). 01's md says cite marks were stripped of backticks.
  - 02: the md asks for dashed surrogate squares, but the shapes are named 'surrogate HH:MM:SS', not 'dashed · …', so `post.tmpl.js` does not dash them. They were dashed live (SHEET-FIX). Renaming them, or teaching the post-step the name, would remove the live step.
  - 05: 'callout · W-1 (§6.5)' is 380 px wide at x 932, so it ran past its frame. It was moved live (SHEET-FIX). A narrower callout, or a sheet x of 898 or less, would fix it in the sheet.
  - 07: oracle rows P-4 and P-5 name an "imbalance outline + hatch" and an "estimated hatch + badge" on the canvas cell. The sheet draws only the outline and the '(estimated)' badge: it has no hatch shape (post-step `rotated` 0).
  - 05 / 06: real sizes are 2 101 and 2 704 shapes, against the brief's estimates of about 1 700 and 2 300. A board this big needs the split touch and relayout described above.

| NN  | Board id                             | Nodes | Lint (overflow / outside / unmeasured / overlap / unbound) | PNG                                                     | Size      | Bytes  | Gate                                                                    |
| --- | ------------------------------------ | ----- | ---------------------------------------------------------- | ------------------------------------------------------- | --------- | ------ | ----------------------------------------------------------------------- |
| 01  | f530cfa4-3f66-80e0-8008-e329ce56cc4e | 294   | 0 / 0 / 0 / 0 / 0                                          | docs/design/E47/img/E47-D06-01-four-layer-inventory.png | 1920x998  | 229251 | PASS E47-D06-01-four-layer-inventory.png theme=dark own=2426 other=19   |
| 02  | f530cfa4-3f66-80e0-8008-e32a78db2eb0 | 555   | 0 / 0 / 0 / 35 / 0                                         | docs/design/E47/img/E47-D06-02-surrogate-grammar.png    | 4640x998  | 324968 | PASS E47-D06-02-surrogate-grammar.png theme=dark own=3471 other=44      |
| 03  | f530cfa4-3f66-80e0-8008-e32cadc90696 | 915   | 0 / 0 / 0 / 14 / 0                                         | docs/design/E47/img/E47-D06-03-profile-table.png        | 3280x998  | 393013 | PASS E47-D06-03-profile-table.png theme=dark own=5662 other=31          |
| 04  | f530cfa4-3f66-80e0-8008-e32e5672f305 | 724   | 0 / 0 / 0 / 12 / 0                                         | docs/design/E47/img/E47-D06-04-ladder-table.png         | 3280x998  | 258436 | PASS E47-D06-04-ladder-table.png theme=dark own=3774 other=31           |
| 05  | 89daaef3-8738-8040-8008-e3301a3a951b | 2102  | 0 / 0 / 0 / 7 / 0                                          | docs/design/E47/img/E47-D06-05-table-states.png         | 4640x1878 | 758646 | PASS E47-D06-05-table-states.png theme=dark own=11539 other=77          |
| 06  | 338d0e73-2a2c-805f-8008-e34dd893d5cf | 2705  | 0 / 0 / 0 / 17 / 0                                         | docs/design/E47/img/E47-D06-06-equal-status-headers.png | 4640x1878 | 829300 | PASS E47-D06-06-equal-status-headers.png theme=dark own=11795 other=117 |
| 07  | 338d0e73-2a2c-805f-8008-e358c289ad36 | 241   | 0 / 0 / 0 / 6 / 0                                          | docs/design/E47/img/E47-D06-07-parity-oracle.png        | 1920x998  | 201074 | PASS E47-D06-07-parity-oracle.png theme=dark own=2352 other=41          |
| 08  | 338d0e73-2a2c-805f-8008-e3599cdb5148 | 916   | 0 / 0 / 0 / 14 / 0                                         | docs/design/E47/img/E47-D06-08-profile-table-light.png  | 3280x998  | 398150 | PASS E47-D06-08-profile-table-light.png theme=light own=6560 other=45   |

Nodes = `lc.count`. Lint is the post-step `lintd` of the root (`lintd.shapes` = nodes - 1).

SHEET-FIX E47-D06 01 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D06 02 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D06 02 the 36 'surrogate …' bounds (18 in each of the sparse-set and targets frames) set to dashed strokes, per the md's live check: they are not named 'dashed · …', so the post-step left them solid
SHEET-FIX E47-D06 02 frame 'grammar∕cursor-window · dark' texts re-set to their own characters (geometry and token binds unchanged), because 'axis 1' (64,096.6), the board's first JetBrains Mono text, drew in a fallback serif at 49 x 17 instead of 53 x 14 and read dark in the first export
SHEET-FIX E47-D06 03 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D06 04 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D06 05 root height 1880 -> 1878 (checked want: footer end 1798 + 80)
SHEET-FIX E47-D06 05 'callout · W-1 (§6.5)' in 'states∕stale · dark' moved from x 932 to x 898 at the same y (244): it is 380 px wide (the other callouts are 320), so it ran 32 px past the frame's right edge and its seven lines were cut by 24 px (lc3.cutN 7 -> 0, spill 1 -> 0); x 898 is the first free x right of the table (its band ends at 896)
SHEET-FIX E47-D06 05 'CMP-021 Link · Learn more' underline (and link board) 73 -> 71 px, the label's measured width
SHEET-FIX E47-D06 05 after the tab stalled in the relayout step and was reloaded: the frame 'states∕stale · dark' and the annotation column texts re-set to their own characters (geometry and token binds unchanged), because the panel header, filter toolbar and stale banner drew in a fallback serif or not at all, and the annotation lines overlapped; 'caption 04', 'caption 05', 'caption 06' and 'footer · data' (sections 118-121) re-drawn from the sheet, because they stayed unmeasured (1 x 1) after every touch; then relayout run per top-level child (cv.relayout's own bottom-up order inside each), because the driver's single relayout call exceeded the bridge's 120 s
SHEET-FIX E47-D06 06 root height 1880 -> 1878 (checked want: footer end 1798 + 80)
SHEET-FIX E47-D06 07 root height 1000 -> 998 (checked want: footer end 918 + 80)
SHEET-FIX E47-D06 08 root height 1000 -> 998 (checked want: footer end 918 + 80)
