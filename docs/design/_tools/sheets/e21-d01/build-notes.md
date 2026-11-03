# E21-D01 research-board kit — build notes

Ticket #417 (E21-D01): memo §0's eight research boards (dark only, greyscale, annotated, no visual design; BQ-13
RULED) for the per-set Penpot file `E21-D01 boards`, page `E21-D01`. This is the research-boards PR's artefact (it
carries `Closes #417`; the memo PR is `Refs #417` + `Partial:`, BQ-1). Offline: no Penpot, no network. Greyscale:
node() refuses every colour token outside `GREY`; check_all re-scans every sheet for it.

## BUILD

`BUILD.md` beside this file: the kit sits at `docs/design/_tools/sheets/e21-d01/` (outputs in `build/`, not committed,
and `v4/`, with each `.md` sidecar beside the kit), or runs from anywhere with `CV_CHECKOUT=<checkout>` (outputs in the
sibling `E21-D01-cap/` and `E21-D01-v4/` folders).

Sources (md5-pinned in `DOCS`, read by repo-relative path; the kit refuses drifted bytes; the memo is pinned as the
boards PR leaves it, with §0's rows drawn and §14 As built, every line a board cites in place): the memo `docs/design/research/e21-dom-heatmap.md` (§0 boards, §2 RQ, §3 F, §4 W, §6 defaults, §7 AD, §8 K,
§10 protocol, §12 C — parsed from its tables, never typed) and the recorded instrument fixture
`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` (BTCUSDT tick 0.10, qty step 0.001).

Layout: `e21d01kit.py` (registries, greyscale tokens, node primitives, the world, frame / board / sections / lint /
validate / write / md / pack, self-test); `gen/rb.py` (ladder, heatmap trail, pulled carrier, legend, cards,
markers); `gen/gen_01..08.py`; `check_all.py`; `local-icons.js` (the icon seed).

## The world (seed 417; every number derived)

A synthetic BTCUSDT book: mark 70,000.00 at t0, best bid = mark, best ask one tick up; 500 levels a side (gaps of one
tick for the first 30 levels, then seeded 1–3 ticks); sizes lognormal, capped at 8 BTC, on the 0.001 step; walls (≥ 10
BTC) at fixed level indices — two inside tier 50, one inside 200, one beyond 200 a side. The heatmap trail is the last
20 columns × 100 ms of the 60 s trail: at column 9 the asks at +1 and +2 trade away and the +3 ask wall is traded
through in four prints (columns 9–12; Σ prints = its size); the −5 bid wall vanishes at column 11 with no print at its
price (the pull). The centring strips use a seeded mark walk, one update per 50 ms (20 Hz), to the first update in
the edge band. Tier contents and losses (far walls, cumulative depth, heatmap rows) are computed from the book.
Kit illustrations, declared on every data board: the ramp anchors 0.4 / 2 / 10 / 50 BTC (log, ×5 a step), the
2-row edge band (OQ-3: E21-D05 #505 owns the numbers), the 5-tick zoom step, the two synthetic own orders.

## Readings taken (ambiguities settled)

1. Board plan: memo §0's eight boards, names and slugs verbatim; export path from §0 (`docs/design/research/img/
E21-D01-NN-slug.png`), not `docs/design/E21/img/`. 23 frames placed by the kit (KIT_FRAMES; §0 names no frames).
2. File name `E21-D01 boards` (README's one-file-per-set rule; the memo names only the page).
3. "Every word from the memo": tables and cards are parsed memo cells (markdown ticks and bold stripped). UI words
   the memo does not write (ladder headings, own-order cell words, notice lines, pin label, legend sentence, the
   SCR-051 setting label and centre-lock caveat) are drawn as illustrations and listed per sheet as copy gaps
   (PROPOSED; E21-D02 / D03 / D04 write the copy). Board markers (step numbers, "mark", "pointer row", read-across)
   are named `dashed · …`.
4. The own-order column heading is the kit label "own orders": C7 ("Your orders" vs "My orders") stays open.
5. Pulled carrier drawn on the heatmap only (OQ-5 open), as a hollow dashed outline with hatch rules (the post-step
   dashes `dashed · …` strokes and rotates `hatch line · …` rects 45°); consumed = print dots.
6. AD-8 is illustrated on board 02 (the SCR-051 three-option setting under the centre-lock strip) and AD-9 on board
   03 (the `trail [60s v]` header chip, the trail-length default and K5); every AD's satisfies/violates line is in
   the annotations of the board that illustrates it (AD_DRAWN; check_all verifies).
7. PROPOSED stamp on boards 02–07 (they show recommendations); boards 01 and 08 show questions and the protocol.
8. No §5 product name, imagery or logo on any board (check_all scans raw, md and packed sheets); §5 is not drawn.
9. Packed sheets keep compact.py's absolute pack-source path in `compactOf.file` outside a checkout; in a checkout the
   committed `v4/` copy carries the bare raw-sheet name (the sha256 beside it unchanged; BUILD.md).

## Live-check fold (render 2026-11-03, eight boards, dark)

The eight boards were drawn from these sheets on page `E21-D01` of the per-set file `E21-D01 boards`, with the local icon
seed `local-icons.js` (the shared five plus `info`, from its `packages/ui` Lucide SVG). Every frame read back at its
sheet size and position with clip on and no child spilling; the drawing lint's one overlap is board 03's "behind"
placement, the ladder region over the heatmap, by design. Two SHEET-FIX lines came back, made on the board and folded
here, so a rebuild reproduces the drawn boards:

10. Board 03 `axis/locked-zoom`: two 536 px zooms and the 24 px gap made 1096 px in the 1072 px row, so the second zoom
    overhung by 24 px and cut 14 ladder size texts. `ZOOM_GUTTER` in `gen/gen_03.py` is now 4 px (was 16), so each zoom
    is 524 px (524 + 24 + 524 = 1072), and the generator refuses zooms that overflow the row.
11. Every root's height is the live read-back, max(annotation end, footer end) + 80: `LIVE_ROOT_H` in the kit, which
    checks it under the kit's own estimate and over the frames' end: 2338, 2591, 2364, 2151, 1847, 1299, 1690 and 2250
    px for boards 01 to 08 (the estimate was 2344, 2592, 2368, 2168, 1848, 1312, 1696 and 2256 px).

Drawn deviation, recorded in memo §14 and not redrawn: the dashed board-marker outlines are barely taller than their
text, so the dashes graze the letters. The `.md` "N shapes" lines count the sheet's nodes; the board's node count (memo
§14) adds the icon instances' children.
