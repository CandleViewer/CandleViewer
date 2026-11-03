# E41-D01 board kit — build notes

Ticket #1017 (E41-D01): the research board and the SCR-093..096 lo-fi wireframes, ten boards (dark only, no twins;
memo §0, BQ-15) for the per-set Penpot file `E41-D01 boards`, page `E41-D01` (memo Deviation 2). Offline: no Penpot,
no network. WIREFRAMES: greyscale — node() refuses every colour token outside `GREY` (surfaces, text, borders,
neutral, grid, axis); check_all re-scans every sheet for it.

## BUILD

`BUILD.md` beside this file: the kit sits at `docs/design/_tools/sheets/e41-d01/` (outputs in `build/`, not committed,
and `v4/`, with each `.md` sidecar beside the kit), or runs from anywhere with `CV_CHECKOUT=<checkout>` (outputs in the
sibling `E41-D01-cap/` and `E41-D01-v4/` folders).

Sources (md5-pinned in `DOCS`, read by repo-relative path; the kit refuses drifted bytes; the memo is pinned as the
boards PR leaves it, with §0's rows drawn and §12 As built, every line a board cites in place; `14` and `21` are read
with `git show` at the memo's base `46e6acd2d`, because both moved on main after it): the memo `docs/design/research/e41-journal-review.md` (§0 boards, §2 RQs, §4 walkthroughs, §5 F, §6 WD, §7
frames, §7.1 deck — parsed, never typed), the session protocol, `17` §1.6 (journey + abandonment rows, parsed), `14`
SCR-093..096 (state words, filter labels), `21` §3.7.2 (tag categories, `tag.neutral`) and the recorded instrument
fixture (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step 0.001).

Layout: `e41d01kit.py` (registries, greyscale tokens, node primitives, the world, frame / board / sections / lint /
validate / write / md / pack, self-test); `gen/wf.py` (wireframe parts and lo-fi charts); `gen/s093.py`, `s094.py`,
`s095.py`, `s096.py` (per-screen parts); `gen/gen_01..10.py`.

## The world (seed 1017; every number derived)

42 LIVE trades on Account A / B / C and 12 DEMO trades on Demo 1, closes 1–30 Oct 2026, BTCUSDT and ETHUSDT. Prices
synthetic on the fixture ticks; qty = 50 USDT risk ÷ stop distance, floored to the step; R = (exit − entry) ÷ (entry −
SL); net = gross − fees (0.055 % a side, synthetic) + funding (0.01 % per 8 h, synthetic, longs pay). Group G-1 =
yesterday's loser (30 Oct 14:32:05, BTCUSDT long, stopped at −1R) on all three accounts: three list rows, no
aggregate row, siblings on SCR-094. Context classes: opened before 8 Oct = not recorded; before 16 Oct = ticks pruned
(bar replay); one trade spans the 22 Oct 10:00–10:40 tick gap = bar-only. Tags: `21`'s five categories, `us-open` the
auto tag (13:00–15:59 UTC); `news` and `moved-stop` hold 3 trades (WD-4's low bucket); tag `range-retest` holds 12
(the protocol's 12-trade view). Bars on SCR-094 are a seeded 5-minute path through entry, MAE, MFE and exit; inside
the trade no bar passes the MAE or MFE.

## Readings taken (ambiguities settled)

1. Board plan: memo §0's ten boards; frames placed from §7 (44 frames). Board 08 and 10 frames carry a variant after
   " · " (e.g. `SCR-095/default · DEMO toggle on`): §7 lists no ids for them.
2. `SCR-093/viewer-write-disabled` is DRAWN on board 03 (the orchestrator's board plan asks for WD-13's T2 frame)
   although memo §0 L79 said "not drawn — the text is binding"; the boards PR updated that line (export-failed is the
   only not-drawn frame). WD-13's owner cell "(not drawn)" stays as drawn verbatim on board 01 (memo §12).
   `SCR-093/export-failed` stays text-only.
3. File name `E41-D01 boards` (BQ-0; the memo names only the page).
4. Every UI label the memo does not write ("Next page", "Apply tag", error titles, confirm sentences, ...) is drawn and
   listed under each sheet's copy gaps as a kit label (PROPOSED; E41-D02 / D03 write the copy). §7.1 strings, `14`
   state words and WD-13's reason are verbatim.
5. Insufficient sample uses a LIVE tag filter of 12 trades (protocol §3 item 4) on board 07; the DEMO toggle frame
   (board 08, 12 DEMO trades) shows the same caveat because its n < 20.
6. Viewer grant: Account A and B; Manager (P2b) grant: Account B and C (synthetic).
7. Focus ring, primary action, scope label: greyscale stand-ins (fallback notes) — `color.focus.ring` and
   `color.env.*` are hues; hi-fi binds them.
8. 200 % reflow is drawn as a 640 CSS px viewport (a 1280 px window at 200 %), type at its normal size.
9. `14` checklist columns not on the lo-fi row (open time, fees, environment, rating) are named in board 02's notes;
   `14`'s tag description column does not exist in `21` and is not drawn (board 09 notes).
10. Packed sheets keep compact.py's absolute pack-source path in `compactOf.file` outside a checkout; in a checkout the
    committed `v4/` copy carries the bare raw-sheet name (the sha256 beside it unchanged; BUILD.md).

## Change 2 (review of #1017: findings 1, 2, nit 3)

11. T2 on SCR-094 and the bulk bar (WD-13): board 04's frame carries an inset `inset · viewer-write-disabled` with the
    note field and the tag editor as T2 (visible, CMP-019 lock, the CMP-079 reason "Your role can't write in the
    journal.", Add tag disabled); board 03's viewer frame draws the bulk-tag bar disabled the same way. No frame or
    board added (ten boards, same frame list).
12. One disabled look for every T2 control (button, checkbox, tag chip, text field, bulk bar): a `dashed · ` name (the
    post-step dashes it) and `color.border.default` where enabled controls are solid `color.border.strong`, plus the
    lock and secondary text. The state survives forced colours without the glyph (fallback `t2stroke`).
13. Board 07 insufficient-sample states in a line of its own that the cohort is a LIVE subset (LIVE trades tagged
    'range-retest', 12 trades, not the DEMO set of board 08).

## Live-check fold (render 2026-11-03, ten boards, dark)

The ten boards were drawn from these sheets on page `E41-D01` of the per-set file `E41-D01 boards`, with the local icon
seed `local-icons.js` (the shared five plus check, chevron-down, chevron-right, info, more-horizontal, warning, danger,
pending, refresh and search, each from its `packages/ui` Lucide SVG). Four SHEET-FIX lines came back; each was made on
the board and is folded here, so a rebuild reproduces the drawn boards:

14. Board 05, SCR-094/pruned: the short trade's SL lay above the bars, outside the CMP-181 pane's price range; the
    rule and label sat 12 px above the pane. Live moved both down 12 px; the kit (`gen/wf.py` context_chart) now spans
    the price scale over the SL, entry and exit, so that pane's bars rescale slightly (the other panes are unchanged:
    their SL, entry and exit already lie inside the bars' range).
15. Board 06, the table view's breakdown card: the select value "session hour (UTC)" wrapped in a 92 px text. Live:
    value 124 px, select 168 px. The kit (`gen/s095.py` select_w) sizes the select from its value: the measured 124 px
    for this value (the text estimate over-reads it), the estimate otherwise, 136 px at least.
16. Board 10, both focus-return frames: step 3 ended at 1151 px inside a 1120 px sequence; the sequence is 1152 px wide
    (live and kit).
17. Every root's height is the live read-back, max(annotation end, footer end) + 80: `LIVE_ROOT_H` in the kit, which
    checks it under the kit's own estimate and over the frames' end.

Drawn deviation, recorded in memo §12 and not redrawn: board 05's bar-only band label overlaps the first candle of the
gap (board 10's legend strips, which grazed their text, are padded since the redraw below). The `.md`
"N shapes" lines count the sheet's nodes; the board's node count adds the icon instances' children.

## Design-read fold (orchestrator's read of #5567, 2026-11-03; boards 03, 04 and 10 to be redrawn)

- T2 rendering 2a (E09-D09 §2.2): `gen/wf.py` draws the CMP-019 lock first in every T2 button, chip, field and row
  checkbox, as the E47-D04 and E08-D09 kits do. The SCR-093 bulk bar's tag select is T2 (`select(..., t2=True)`: lock
  first, the value in the T2 label colour, described by the page's CMP-079 reason); its orphan lock is gone.
- The focus ring is a 2 px inner stroke (`RING_ALIGN`), with INSET_XS added to a node that has no inset, so a clip-on
  parent never cuts it. Board 09 keeps the outer ring it was drawn with (not in this redraw).
- Board 10: keyboard row 5 names the row model (CMP-049 grid, the APG grid pattern: one roving tab stop, Up / Down
  arrows); the viewport notes, step captions and forced-colours lines take `padY` INSET_XS so their dashes clear the
  words. That moves the frames' bottom 2792 to 2864, so `LIVE_ROOT_H[10]` is 2995, predicted here and read back by the
  redraw.
- Memo L44 (BQ-2) names memo §0, §6, §7 and §12 as the wireframe spec; the memo md5 is re-pinned, so every sidecar's
  sources line and every sheet's `compactOf.sha256` moved; sheets 01, 02 and 05 to 09 differ only in that md5.

## Redraw fold (boards 03, 04 and 10 redrawn, 2026-11-03)

Boards 03, 04 and 10 were deleted and drawn again from the regenerated sheets (new board ids in memo §12). Every board's
node count is its shapes plus the root, every frame clip-on with no spill, lint and the cut check clean, and the roots
read back at 2827, 1356 and 2995 (board 10's predicted height confirmed). Two SHEET-FIX folds, live and kit:

18. Board 04, the T2 inset: `notes_tags(t2=True)` was COL_W (548 px) inside a 548 px inset with INSET_SM padding, so the
    note field's right edge was cut 8 px; `gen_04.py` passes `w - 16` (532 px; the value text 488 px).
19. Board 10, both focus-return frames: the focused dialog heading's title kept the heading's full width inside the
    ring's INSET_XS `padX` (4 px past it); `wf.dialog()` narrows the title by 2 × INSET_XS (297 -> 289 px).
