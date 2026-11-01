# E47-D03 (#1302) board kit: build notes

Offline cvsheet v4 sheets for the ten §0 boards of `docs/design/E47/E47-D03.md` (file `E47-D03 boards`, page
`E47-D03 themes and SCR-116`). No Penpot, no network. Raw sheets go to `build/NN-<slug>.json` with their `.md` (the
render drivers' set; untracked), the `.md` also beside the kit, packed sheets to `v4/NN-<slug>.json` (`compactOf.file`
the bare raw-sheet name, its sha256 the raw sheet's). `BUILD.md` says how to rebuild them.

## Sources (md5-pinned; the kit refuses drifted bytes)

- Spec and hand-off read from this checkout by repo-relative path, `docs/design/E47/E47-D03.md` and
  `E47-D03-handoff.md`, md5-pinned in `SPEC_MD5`. §0's board table (names, Draws, themes, twins), §G's frame plan,
  §13's copy deck, §8.1 controls, §8.2 presets, §8.3 variants, §5 encodings, §7.2 / §7.3 rows and the hand-off's §C.2
  diff are parsed. Every figure is an anchored tool value (`value<!--=KIND:key-->`, written by
  `e47_d03_theme_audit.py --fill`; `--check` reads `FAIL 0` at the pin). §0's as-built record was written in place,
  line for line, so every `L<n>` cite on the boards holds; the pins were then moved to the final bytes.
- Tools: the shared copies in `../tools/` (`validate_sheet.py` with `token-sync.json` and `--components
components.offline.json`, `compact.py`, `mkcall4.py count`).

## Build

```sh
cd docs/design/_tools/sheets/e47-d03
python3 -I -B e47d03kit.py selftest                 # OK: 0 failures
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -I -B gen/gen_$n.py; done
python3 -I -B check_all.py                          # every sheet "ok", "OK: 0 findings"
```

Generation is deterministic (seed 1302): a rebuild gives byte-identical sheets.

## Live-check fold

The live check's SHEET-FIX lines are folded in, so a rebuild reproduces the boards as drawn:

- the root heights of boards 01, 06 and 07 are the measured annotation end + 80 (`k.MEASURED_H`): 01 1039 (the
  estimate was 1136), 06 1901 (2112), 07 1448 (1568);
- the seeded bubble 04 coincided with bubble 03, hiding its ▲ (§5's sign): bubble 04 and its glyph sit 24 px higher
  (`k.BUBBLE_LIFT`), on board 06's bubbles frame, board 07's three frames and board 08's cvd-safe frame.

The accent swatch fixes (Purple → `palette.purple.400` on 01, 03, 05; Cyan → `palette.cyan.700` and Amber →
`palette.light.amber.700` on 02, 04; board 02's positions-row border → `palette.light.amber.700`) are the sheets' own
live rebind steps (the validator refuses primitive colour binds), done live as the notes say; the sheets are unchanged
by them. Against the sheets that were rendered, the rebuilt raw sheets differ only in the folded values and in their
notes (the sources line's md5 pins and the live-check lines that quote the root size).

## Boards-lens fold

Boards 05, 09 and 10 were redrawn from the kit after the boards lens: `swatch()` and `accent_picker()` take the frame's
`Scale`, so board 05's 150 % frame draws the four accent names at 150 % like every other label (V-5); board 05's
200 % viewport outline is a `dashed · …` rectangle (the post-step dashes it), so its bottom edge no longer strikes
through the heading under the fold; board 09 drops the ratio under default heatmap ask 2, §4.2's stale pair that
D03-A11 removes (`gen_09.STALE`, checked against the spec row); board 10's CVD stops 2 and 4 print "no anchored ratio
(§3.3 anchors stops 1 and 5)" where a Python `None` leaked before. The live check needed no further fix.

## Layout

| File               | What                                                                                    |
| ------------------ | --------------------------------------------------------------------------------------- |
| `e47d03kit.py`     | parsing, tokens, world, chrome, SCR-116 controls and PreviewTile, ink panels, sheet I/O |
| `gen/scr116.py`    | boards 01-05 shared frame and annotation builders                                       |
| `gen/inkboards.py` | boards 06-08 shared surfaces, §5 rows and §7.2 lines                                    |
| `gen/gen_NN.py`    | one generator per board (04 reuses 01's helpers; 10 reuses 09's `build_frame`)          |
| `check_all.py`     | the scan: validator, pack, count, inst, icons, wrap, forbidden, cell padding, captions  |

## Rules applied

- Frames are 1280 x 800; names are §G's ids with "/" drawn as U+2215; a `state: <id>` caption above each frame;
  root = frames + one 400 px annotation column + 80; the data line under the frames.
- No inst nodes; local icons only; no boolean wrap; flex children without text carry h; table cells padX 8.
- Light / hc boards are token-bound and switch at export (md line 3); board 08 is mixed (renders under dark, live
  check re-exports each frame under its own set).

## Kit choices and fallbacks (also in each sheet's notes)

- Chrome (TopBar, NavRail, StatusBar, CMP-086 list) as placeholders; "Appearance" (h1, current entry) from §0 / §8.4.
- `border.control` (D03-D5 / D6, PROPOSED) drawn as border.hairline (dark, light) / border.thick (hc).
- Accent swatches bind a semantic alias resolving to §8.2's primitive; none exists for Purple (dark/hc) or Cyan and
  Amber (light): same-hue stand-ins with live rebind steps.
- Greyscale / dichromacy frames bind true tokens; the projection is applied at export (E15-D04 precedent); §7.4's
  expected hexes are listed per frame.
- 150 % text: nearest type token to 1.5 x; 200 %: the 640 CSS px page at 1:1 in two strips.
- Hatch as 1 px stripes; CVD line as 4 px marks; env glyphs as ellipses; ▲ / ▼ as text; LIVE / DEMO weight as
  body-strong (no 13 px bold token).
- Footprint imbalance threshold 3.0 x (illustrative); PreviewTile and panel column headers are copy gaps (listed).
- Board 10's CVD heatmap stops bind today's holder of each D03-D7 … D03-D14 primitive (rebind after E47-D10).
