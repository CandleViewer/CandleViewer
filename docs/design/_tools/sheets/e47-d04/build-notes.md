# E47-D04 board kit: build notes

Ten cvsheet v4.2 sheets for #1303 E47-D04 (the focus model), built offline from the spec. No Penpot, no network.

## Pipeline

- Spec: `docs/design/E47/E47-D04.md` and `E47-D04-handoff.md`, read from this checkout by repo-relative path. The
  boards were drawn from the text after the rulings of record (`136bab54c`); the pins now hold the as-built text, whose
  §0, §C and §H rows were edited in place, so every `L<n>` and §H cite on the boards still reads the same line.
  md5-pinned with the recorded fixture `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` (tick size
  only) in `SPEC_MD5`; the kit refuses to import on drift.
- `e47d04kit.py`: parses §0 (BOARDS, the page name), §H (FRAME_PLAN), §4 (ARCH: the archetype table, cited per cell),
  §7.1 (GEOMETRY), §7.6 (BACKGROUNDS: 12 rows x 6 ratios as `CONTRAST:` keys), every `<!--=CONTRAST:...-->` and
  `<!--=COUNT:...-->` figure, §15 (COPY, `w()` fills slots), §18.2 (GROWS), §1.4 (RULES). Builders: CMP-039 rings
  (normal, inset, thick) from nested stroke-only boards; markers, tags, outlines, callouts (annotation overlays); the
  SCR-010 shell and SCR-020's four-panel workspace with frame coordinates in `GEO`; the full page; specimen frames;
  CMP-044 dialog + scrim; the seeded ladder and position set; the ONE annotation column; `board()`; the E08 kit's
  section packer, lint, validator call, `write_sheet`, `pack_sheet` (copied); `write_md`; `build_all`; `selftest`.
- `gen/gen_NN.py` per board (`gen/common.py`: panel bodies, marker spots). 09 and 10 call 08's `build(theme)`; 10's
  first frame is `gen_10.frame_thick`.
- `scan.py`: 0 inst, icons in the local set, no boolean wrap, no banned strings, no "/" below the root name, cell
  padX 8, a "state:" caption per frame, 1280 x 800 frames, root = frames + 80 + 400 + 80, packed `compactOf` = the
  raw sheet's bare name + sha256, md5 pin.

Rebuild: `BUILD.md`. Output: the raw sheets in `build/` (untracked), each `.md` beside the kit and in `build/`, the
packed sheets in `v4/` (`compactOf.file` the bare raw-sheet name).

## Live-check fold

One live round on the rendered page found and fixed, and the kit now writes, the following (a rebuild reproduces the
boards as drawn):

- Root heights: max(annotation end, footer end) + 80 as measured (`MEASURED_H`): 01, 02, 05, 08–10 998; 03 1036;
  04 1878; 06 1101; 07 1042 (after the boards lens fold below).
- Board 07 `form∕admin-t2-t3`: the TopBar's T2 FLATTEN ALL and its ruled reason ("Only the owner can flatten every
  account.", E39-D03 S4) as a column clipped the reason 8 px in the 48 px TopBar: laid out as a row (centred, gap
  `space.inset.sm`), the reason hugging; the `seq 02` marker moves 104 px left with the group.
- Board 10: the preference card's title wraps at the card's 256 px content width.
- Board 01: the wrap line and its two heads move 2 px in, inside the frame's right edge.
- Board 06: the cheatsheet's restore callout moves 24 px left, inside the frame.

## Boards lens fold

The boards lens on the exported PNGs found the annotation layer at fault in places; the kit now writes the fixes and
boards 01, 02, 03, 04, 07, 08, 09 and 10 were redrawn from it (deleted by root name, rendered again, live-checked):

- `frame_block`: the "Waits on D04-Gn (...)" summaries quote the full §18.2 title (they were cut at 70 characters,
  mid-word, on boards 01, 04 and 08–10).
- Board 04 `retention∕not-obscured`: the ticket's tag sits on the ticket, under its submit button, off the focused row.
- Board 07 `form∕admin-t2-t3`: the T3 tag moves under Keyboard-only mode, clear of W-8's help text; the Drawn line
  counts the rail (six entries, the owner frame's seven) and names what is not drawn (the sticky footer row, the
  radio groups). Its column grew, so its root is 1042 high.
- Board 01 `shell∕landmarks`: the `navigation` tag moves up, off the `main` tag, and is the frame's last overlay so
  the main outline does not cross it (a z-order fix on the page); the four `region · h2` tags sit in the header bars.
- Board 02 `workspace∕roving-zones`: the RG-07 tag is a four-line tag in the rail under the tree's outline
  (`tag_stack`); the RG-08 tag sits in the DOM header bar; the R-2 callout is 344 wide, so "(R-2)" stays whole.
- Board 03 `grid∕esc-layers`: an alphabetic marker (`Esc`) is a 28 × 20 pill.

## Penpot file, page, names

- File `E47-D04 boards`, page `E47-D04 — Focus model` (§0). Roots `E47-D04 / NN <slug>` exactly as §0; grid
  x = ((NN-1) mod 5) x 6000, y = floor((NN-1)/5) x 3200.
- Frames: §H's `<archetype>/<state> · <theme>` with U+2215 for the slash (`shell∕landmarks · dark`): a "/" in a
  node name splits section paths. Captions `state: shell∕landmarks` 28 px above each frame.
- Exports `docs/design/E47/img/E47-D04-NN-<slug>.png`. Themes: 01-08 dark, 09 light, 10 hc; twins token-bound
  (the theme is switched at export).

| Board              | Frames | Root w x h  | Theme |
| ------------------ | ------ | ----------- | ----- |
| 01 landmarks-ring  | 2      | 3280 x 998  | dark  |
| 02 workspace-order | 2      | 3280 x 998  | dark  |
| 03 grid-escape     | 3      | 4640 x 1036 | dark  |
| 04 retention       | 4      | 3280 x 1878 | dark  |
| 05 dialog-flatten  | 2      | 3280 x 998  | dark  |
| 06 overlay-palette | 3      | 4640 x 1101 | dark  |
| 07 full-page-form  | 2      | 3280 x 1042 | dark  |
| 08 ring-spec       | 2      | 3280 x 998  | dark  |
| 09 ring-spec-light | 2      | 3280 x 998  | light |
| 10 ring-hc-thick   | 2      | 3280 x 998  | hc    |

Root heights are the live-measured ends (`MEASURED_H`, above); without a measurement the kit's estimate (`text_h`
over-estimates the column) is the floor, and the live drawer sets h = max(column end, footer end) + 80 after
touchTexts + relayout (a live_checks line on every sheet).

## The window and the world

- Compact density (§0): 24 px controls and rows. Shell: TopBar 48, NavRail 56, main 984, RightRail 240, StatusBar
  24; workspace: tab strip 32, panels 490 x 332 (2 x 2, 4 px splitters), tray 28. Panel names by E15-D15's rule
  (D15:262): "Chart, BTCUSDT 1 minute, Live", "DOM, BTCUSDT, Live", "Positions, all symbols, Live", "Tape, BTCUSDT".
- Panel focus is CMP-080's inset frame + header bar in `color.focus.ring` (§7.4, `16`:88; `border.panel.focus` is
  not in the token file: a `border.focus` stroke + a 3 px rect); CMP-039 sits on the control only.
- Synthetic data, declared on every board's face and annotation: seeded (1303) book around best bid 67,420.00
  on the fixture's BTCUSDT tick 0.10; positions on the fixture's ETHUSDT / SOLUSDT ticks too. Every price derives from
  the anchor +/- k ticks; board 04's nearest level (`nearest_survivor`, ties toward the touch) and its 2.4.11
  geometry (overlap, scroll-padding, scroll) are computed, never typed.
- Every ratio on 08-10 is the spec tool's output; the self-test re-derives min edge / min ring from the rows and the
  §7.5 extents (6 / 9 px) from the band widths.

## Annotation column

One 400 px column per board: the §0 Draws cell with its line, theme / twin, the §H frames, export, the synthetic
declaration; then per frame: what it draws with `§n L<line>` cites (looked up, never typed), the §4 cell it
illustrates, the W-string with its §15 line and status, the keyboard path, the G-rows it waits on; footer
`page E47-D04 — Focus model · board NN · r1`.

## Kit readings (ambiguities; recorded in each sheet's notes)

1. §H frame names contain "/": drawn with U+2215.
2. Board 05's dialog title: E47-D04 names only "the flatten-all ConfirmDialog"; drawn with E39-D03 §10 S1 "Flatten
   all positions — all accounts" (copy gap); body copy as placeholders (E39-D01 owns it); Confirm labelled "Confirm"
   (§9.1's word).
3. Board 07 frame 2: §0 says SCR-121 with "a T2 control in the order, a T3 item absent"; the walkthrough (§E) reads
   "an admin item a manager cannot reach is not there at all". Drawn as a Manager session on SCR-110/117: Admin rail
   entry and section-nav link absent (T3; SCR-121 unreachable), the TopBar's global FLATTEN ALL as T2 with E39-D03 S4
   "Only the owner can flatten every account." The TopBar placement follows §9.2 (`14`:302) although E39-D03 C6
   moves the panic buttons to the RightRail.
4. The 3 px thick ring (D04-G5, no token) is two adjacent ring-colour strokes (border.focus + border.hairline).
5. Board 06: palette rows are SCR-012's wireframe; the cheatsheet's words are `14` SCR-013 / `14`:302 and §3 / §6
   (bindings are E47-D09's); menu items are placeholders.
6. h1 on Settings drawn "Settings" with h2 "Accessibility"; non-W-7 option descriptions are placeholders.

## Not drawn (§0 L82, the text is binding)

The focus-trace overlay (§13); the 159-id map (§5); retention rows beyond the ladder and positions grid (§8); the
CVD-theme rings (pending E47-D03); the light and hc cells of boards 01-07; comfortable and cosy densities.

## Pairs for parallel renders

(1, 2), (3, 4), (5, 6), (7, 8), (9, 10): 09 and 10 are 08's twins and share its generator, so 08-10 can be rendered
together if preferred.
