# E36-D02 boards: drawing hand-off (#873)

Board script for E36-D02 (SCR-081 rule editor, form mode; SCR-083 templates gallery). The spec is `docs/design/E36/E36-D02.md` (merged in #4148) and the source of every word and number on the boards.

- **Script:** `e36-d02-board.js` r7. It is the r7 posted on #4148 (issuecomment-6378143051 and its parts), with one changed sentence in the version comment, so its sha256 differs.
- **Post-passes:** `e36-d02-relayout.js` (PASS "measure", then "restack" until `moved = 0`), then `e36-d02-dedupe.js`.
- **Page:** `E36-D02 Rule form editor and templates`, in a per-set file "E36-D02 boards". The page is created by name on the first run; pin `PAGE_ID` after it.
- **Globals to set per call:**
  - `WRITER`: the tab's single-writer stamp;
  - `FILE_ID`: the per-set file, set at load time and never committed;
  - `PAGE_ID`: `null` on the first call;
  - `ONLY`: the board numbers;
  - `PART`: `0` returns the part plan and self-check and draws nothing.
- **Fonts:** Inter and JetBrains Mono only.
- **Cap of ten boards:** draw `ONLY = [1, 2, 4, 5, 6, 7, 9, 10, 12, 13]`. Boards 03 (round-trip indicator), 08 (validation copy) and 11 (long content at 200 %) are not drawn; their text in the spec is binding, and §0 records them as not drawn.
- **Parts:** 02 and 12 are two parts each (`PART = 1`, then `2`); every other board is one call (`PART = null`). A failed part k > 1 is redone from `PART = 1`.
- **Export:** each board at scale 1, as `docs/design/E36/img/E36-D02-NN-<slug>.png`. Boards 01–10 and 13 use the dark theme; board 12 is the themes board.
- **Eyeball checks:**
  - every pill and button label is on one line (the script's pre-export self-check throws otherwise);
  - the validity-disabled buttons keep their own fill at `opacity.disabled`, with the reason beside them;
  - the T2 rows carry the lock, the tertiary label and the reason;
  - each read-only frame has one notice.
