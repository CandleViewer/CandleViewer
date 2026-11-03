# E47-D13 board kit: build notes

Ten cvsheet sheets for #1311 E47-D13 (the accessibility statement and the VPAT-shaped report), built offline from the
spec as merged, with the drawing lane's live check folded in (below). No Penpot, no network.

## Pipeline

- Sources, read from a checkout by repo-relative path (`14` with `git show` at the spec's base) and md5-pinned in `DOCS` (the kit refuses to import on
  drift): `docs/design/E47/E47-D13.md`, `E47-D13-handoff.md`, the generated dry run
  `docs/plan/a11y/47-conformance-report.md` (the 55 rows and their words), the register
  `docs/plan/a11y/47-limitations.json` (the statement rows, the category sentences) and `docs/plan/14-screens-catalogue.md`
  (the SCR-110 nav, SCR-116's text scales, SCR-117, SCR-119).
- `e47d13kit.py`: parses §0 (BOARDS, the page name), §H (FRAME_PLAN), §11 (COPY; `w()` fills slots, `w(key, part=i)`
  takes one of W-10's / W-14's strings), §14.2 (GROWS), §1.4 (RULES), §7.6 (PAIRS, the CONTRAST slots) and every
  COUNT slot; the report rows and the register rows; the window (the E47-D03 kit's SCR-116 shell); the statement page as
  positioned sections (`statement_page(State(...))`, every item's page y in `Page.spots`); `crop()` (a sheet carries
  only what a viewport shows); the E47-D04 kit's CMP-039 ring, markers, tags, callouts, tables, annotation column,
  board, section packer, lint, validator call, `write_sheet`, `pack_sheet`, `write_md`, `build_all`; `selftest`.
- `gen/common.py`: gutter stops, end-aligned tags, `Bands` (the whole page condensed into one main pane), the skip link.
  `gen/gen_NN.py`: one generator per board.
- `check_all.py [--twice]`: self-test, all ten generators, then the scan (0 inst, local icons, no boolean wrap, no
  banned string, no "/" below the root prefix, 1280 x 800 frames each with its "state:" caption, cell padX 8, root =
  frames + 80 + 400 + 80, validator exit 0, packed compactOf = bare name + the raw sheet's sha256, mkcall4 count exit 0
  in the raw folder, md line 3, the md5 pin); `--twice` requires a byte-identical rebuild.

## Build

```sh
cd docs/design/_tools/sheets/e47-d13             # or set CV_CHECKOUT to a checkout when the kit sits elsewhere
python3 -X utf8 -I -B e47d13kit.py selftest      # "OK: 0 failures"
python3 -X utf8 -I -B check_all.py --twice       # "rebuild byte-identical: True", "OK"
```

Outside a checkout the raw sheets and `.md` go to `../E47-D13-cap/`, the packed sheets to `../E47-D13-v4/`; inside
one, to `build/` (untracked) and `v4/`, with each `.md` copied beside the kit. Deterministic: no clock, no random.

## Penpot file, page, names

- File `E47-D13 boards`, page `E47-D13 — Conformance statement` (§0). Roots `E47-D13 / NN <slug>` exactly as §0;
  grid x = ((NN-1) mod 5) x 6000, y = floor((NN-1)/5) x 3200.
- Frames: §H's `<section>/<state> · <theme>` with U+2215 for the slash; captions `state: <section>∕<state>` 28 px
  above each frame. Exports `docs/design/E47/img/E47-D13-NN-<slug>.png`.
- Themes: 02 and 10 light, 04 high contrast (three of ten, cap one third); token-bound, the theme set at export.

## The window and the page

- Every frame a 1280 x 800 window at compact density: TopBar 48 | NavRail 64 · CMP-086 SettingsNav 208 · main
  1008 x 704 | StatusBar 48 (the E47-D03 kit's SCR-116 window); the nav's nine entries are `14` SCR-110's words,
  "Help & about" (SCR-119) selected. Shell chrome is placeholders.
- The page: a 960 px column, 24 px padding (space.inset.xl), prose at a 720 px measure (kit choice); sections 24 px
  apart, items 1-3 12 px apart; tables full width, rows zebra on color.surface.app / color.surface.raised (the two
  surfaces §7.6 measures), cells 8 px a side.
- Zoom (board 09): the page at 1:1 CSS px in strips: 200 % = two 640 px strips, 320 CSS px = four 320 px strips, each
  naming its CSS y range; the largest text scale (150 %, `14` SCR-116) maps each role to the token nearest 1.5 x.
- Heights are estimates (Inter metrics); every sheet carries live checks for the drawer to re-measure.

## Kit readings (ambiguities settled; each also in the sheets' notes)

1. Board 03 draws three frames: §0's Draws names "the offline frame (§7.3)" and §7.3 says "board 03's offline
   frame", while §H lists only `statement/stale` and `statement/version-unknown`; the spec's board table decides
   (the design read of record, R5, asked for the offline state to be drawn or listed): `statement/offline · dark`.
2. The page (about 3,500 px) is longer than a window: frames show it scrolled to the section they study; boards 01
   (`statement/anatomy`) and 10 show the whole page condensed into bands, each cut naming the px not shown.
3. Headings: one h1 in W-1's words and an h2 for items 4-8; items 1-3 sit under the h1. The h2 words for items 4, 6
   and 7 ("What is supported", "Alternatives", "All criteria") and the criteria column headers ("Criterion",
   "Level", "Conformance level") are copy gaps taken from §7.2 and §2.2's prose; W-9 and W-12 are the deck's.
4. Board 04 `limitations/generic`: no row is `internal` at the base, so the frame marks one synthetic internal row
   of category `security`, shown by the register's own category sentence after W-16.
5. Synthetic data: statement version 1.4.0 issued 2 November 2026, review by issued + 90 days, running 1.4.0
   (1.5.0 on the stale frame), the CMP-207 line; declared on every board's face and in its annotation.
6. Board 10's Tab order numbers §7.4's six page focusables; the shell's TopBar and rail stops (E47-D04's ring) are
   not numbered.
7. CMP-033 is drawn with its visible label W-13 and the copy glyph; the failed glyph `error` is not in the local
   icon set, so `danger`; the polite region's W-2 / W-17 + W-18 are drawn as visible text beside the button.
8. Board 08: SCR-117's body belongs to E47-D05 (#1304, unmerged) and is drawn as placeholders with the as-built
   link paragraph (W-1 | W-3); SCR-119's statement link reuses W-1's words.
9. No control on the page is T2 (BQ-12, §7.8): no T2 rendering is drawn; every board says so.
10. The alternatives' row words are plain readings of `05`'s keyboard-table descriptions (copy gaps); the keys are
    §7.2 item 6's.

## Live-check fold (the drawing lane, one round)

The drawing lane drew the ten boards from the transported sheets and returned 25 fix lines. Every geometry fix is
folded here, so a rebuild reproduces the drawn boards:

- `text_h` is the measured line height, `ceil(size x line-height x lines)` (13 px at 1.4: 19 px, not 18.2). It grows
  the section, pair, list, template and `actions` boards the live check grew by 1-5 px, and sets the `cut N` strip
  labels to the strip's 12 px.
- `MEASURED_H`: the checked root heights (998 on 02, 03, 05-08, 10; 1001 on 04; 1029 on 09). Board 01 keeps its
  estimate: its redraw measures the corrected annotation column.
- `MEASURED_LINK_W`: the link labels' measured widths at type.ui.body (SCR-013 187, SCR-117 194, statement 143); the
  underline and the CMP-039 ring nest around a focused link follow.
- Board 04's header tags at x 966 / 728 / 446 (`TAG_X_MEASURED`), clear of the h2; board 07's W-14 and CMP-033 tags at
  x 1024 (`TAG_X`), clear of the template box; board 08's entry outlines 379 and 171 px wide, 8 px a side; board 09's
  viewport tag at y 374, above the edge.
- Board 01: `gen_01.py` no longer cuts the §7.7 line at 400 characters (the drawn board ends "...; co"); board 01 is
  to be redrawn from this kit.

Recorded, not folded: the text re-sets of 06 and 10 after a tab reload (a drawing step); the kept findings (outside
the root by design, 08's two overlaps, 09's viewport rule over the first row) and three drawn deviations (09's 320
strip labels, 06's column tags, 10's nav tag), all in the spec's §16.
