# E21-D03 board kit — build notes

Ticket #503 (E21-D03), the boards PR (it carries the closing keyword once E21-D02 #440 is done; the text is PR #5518,
`Refs #503`). Offline: no Penpot, no network. The boards are drawn: E21-D03 §0 holds each board's id, PNGs and gates,
§20 the as-built record. Every string comes from the spec through `k.W` (the §15 copy deck, slots filled and checked) or
`k.S` (a spec string, matched verbatim with code ticks and bold removed); the few labels the spec does not write are
`k.ui(...)` and listed under each sheet's `notes.copy_gaps`. Every number comes from the seeded world.

## Sources and pins

- Spec `docs/design/E21/E21-D03.md`, md5 `b22ff82ca51787f3bbecc5f8d34fd6bf`, the as-built text (the boards PR; the
  cites were read at the text PR head `c7b0d2087` and every cited line stays in place); no hand-off file (BQ-2). Ruling of record: comment 6580396430 (the BQ list 6579618328 ruled; plan APPROVED).
- `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` md5 `edd9dd2a060c51bd4bd1450307728ddf`: the
  BTCUSDT tick 0.10 and qty step 0.001 only.
- Tools from the checkout, read-only: `docs/design/_tools/sheets/tools/` (`validate_sheet.py`,
  `components.offline.json`, `token-sync.json`, `compact.py` = the packer, `mkcall4.py`).

The kit reads the spec by repo-relative path from a checkout: in the repo at `docs/design/_tools/sheets/e21-d03/`
(REPO four levels up; raw sheets to `build/`, packed to `v4/`), or from anywhere with `CV_CHECKOUT=<checkout>` (raw
sheets to `../E21-D03-cap/`, packed to `../E21-D03-v4/`).

## Rebuild

```sh
python3 -X utf8 -I -B e21d03kit.py selftest          # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                   # builds twice (byte-identical), scans, "OK: 0 failures"
```

`BUILD.md` has the full recipe.

After the text PR changes (the orchestrator's design read), re-pin: put the new md5 and head in `DOCS` / `HEAD`, run
the self-test, fix any `LookupError` (it names the string that moved or was reworded), then `check_all.py`. The parsers
read §0's board table, §10's states, §15's copy deck, §2.2, §2.4, §9.1, §12.1, §12.2, §13.1 and §13.4 by heading.

## Pipeline

`gen/gen_NN.py` builds the board's frames with `gen/ui.py` (widgets, the dialog, SCR-050 behind, the SCR-153 window)
and calls `ui.run` → `k.build`: the raw sheet (kit lint, banned scan, validator exit 0), the `.md` sidecar (line 3 is
the render line; twins carry the light-export line; a copy beside the kit is committed), the packed sheet (`compact.py`;
`compactOf` = the raw sheet's bare name and sha256; mkcall4 count = sections; every packed section ≤ 9216 B). The SCR-050 rows are grouped into 8-row bands so
a full panel packs into a few sections.

## The seeded world (seed 503)

Mark 64,560.2 (best bid 64,560.2, best ask 64,560.3); 500 levels a side, a lognormal base with three walls a side and a
seeded walk over 17 columns. The tile: 17 columns × 5 bands a side, a band = the sum of tier ÷ 5 levels; the stops
(`anchors`) are the 10/35/60/80/95 % quantiles of the tile's band sizes at the tier (adaptive, log): at 200 they are
65.079, 75.468, 90.195, 122.695, 166.134 BTC. SCR-050 behind the dialog draws one level per 24 px row from the same
book. Cost (W-7) and the clamp (W-13) are a kit model, labelled "illustrative, PROPOSED, not a budget" on the board:
p95 of 600 seeded frames of 2.4 + 0.011 ms × levels, inbound = 10 s of 20 Hz updates at p 0.04 a level (50: 3.2 ms ·
81/s; 200: 5.6 ms · 326/s; 500 unmeasured on board 01); clamp = 600,000 cells ÷ (2 × tier × 1 column/s) → 600 s at 500.

## Readings (ambiguities settled)

1. Light twins (01, 05, 09): themes are file-wide, so a twin is the same token-bound board exported a second time
   under the light theme as `E21-D03-NN-<slug>-light.png`; `.md` line 3 stays `theme dark.` (the render theme) and the
   sidecar's line 7 names the light export. No duplicate frames are drawn.
2. Board-marker frames for what §0's Draws cells name without a state id: board 01's redlines (§2.4 verbatim + target
   specimens), board 02's D02 tier-notice inset (W-5, W-36 filled for Columns 1 s → 500 ms), board 10's 200 % reflow
   (drawn in CSS px: 640 × 400; the tablist drawn on two rows as §13.3 says). Two specimen frames show copy a state row
   names but its frame cannot show at once: W-11 / W-12 (board 07) and the W-33 leg (board 08).
3. The dialog geometry is the kit's (§2.1 gives none): CMP-043 lg 960 × 720, centred; the left tabpanel 560 px, the
   tile 320 × 200 (§2.3's PROPOSED size); fields at 32 px (size.control.comfortable), labels in a 208 px column.
4. The footer status node is drawn as visible caption text (W-29, W-38); every announcement is also drawn as a board
   marker ("announced: …") in the window's foot strip.
5. The cvd-preview frame draws the CVD-safe set's tokens; the simulated appearance is cvd_sim.py's render at export
   (a filter, never a drawn colour). Boards 03 and 09 add the greyscale export.
6. SCR-153: no E15-D12 rows in this session, so the shed row is alone in the banner slot; W-35's earlier steps are not
   drawn (their values are G-5's); the pinned row shows W-26 alone, focused; W-22 / W-26 / W-27 are announced through
   the banner's region.
7. The viewing-as user is "Manager 01" (synthetic); the presets label "Quantity presets (BTC)", the Detectors group
   label and the E21-D02 panel labels are copy gaps (`k.ui`).

8. W-37 (both reset forms) is drawn on board 10 as a second foot-strip announcement marker beside W-29's (not the
   frame's state; every R-5 announcement has a board). The keys are named beside W-9 (`book.rebuild_refused`, 02) and
   W-32 (`rbac.view_as`, 08).
9. Carried Minors (design approval at `c7b0d2087`): board 10 adds the `Enter` row for a T2 option as an annotation
   only while §13.1 lacks it (it drops out once the parsed table carries it); board 09's pinned frame says the W-25
   pin is session-only in a view-as or no-`workspaces:write` session (C-12; E17-D03 G3).

## Kit choices (also in each sheet's `notes.fallbacks`)

Radios / checkboxes as 16 px marks with the color.text.tertiary rest stroke; the env pill's glyph as an 8 px dot
(outlined DEMO, filled LIVE); the spinner as a static ring; the backdrop scrim color.surface.app at opacity.scrim
(validator WARN: Tier-1 primitive, as is size.icon.sm for the CMP-019 lock); nodes wholly under the opaque card are not
drawn.

## Live-check fold (the drawing lane's fix lines, 2026-11-03)

Every fix line of the live check is folded in, so a rebuild reproduces the drawn sheets node for node; the only
differences from the sheets as handed over are these (and the sheets' `notes`, which carry the spec pin):

- Root heights: `MEASURED_H`, the checked max(annotation end, footer end) + 80 (01 1026, 02 2322, 03 1934, 04 1039,
  05 1947, 06 1039, 07 1422, 08 1334, 09 1934, 10 1166). Every root came out 5 to 362 px shorter than the kit's
  estimate (board 10 the furthest): the annotation and footer texts wrap fewer lines live, and the estimate carried
  15 % slack and a round-up to 8 px. The root estimate now takes Inter's advance as 0.48 em (`INTER_EM["root"]`) with
  whole-pixel text boxes and no slack (`est_root_height`; the nodes' own sizes keep 0.56, so no drawn geometry moves),
  which puts the ten estimates within 0 … +13 px of the drawn heights, and `board()` refuses a checked height more than
  `MEASURED_SLACK` (48 px) from its estimate: past that the text has changed since the measure, so measure again.
- The 1-2 px raises: `est_drawn_height` rounds each text box up to a whole pixel, as Penpot draws it. `ui.group()`
  takes it (the depth-tier group: 02 and 07, 94 -> 95 and 86 -> 87), the Colour tab's scale-and-gamma row hugs its
  tallest child (46 -> 47, so the tabpanel 385 -> 386 and 393 -> 394) and the shed row's message takes it (09, 53 ->
  55); the row keeps its 77 px with an 8 px bottom inset (the live fix used 10 px, which is not a token), so the SCR-050
  header under it does not move.
- Board 02: the SCR-050 header in the `inset · D02 tier notice` frame spans the frame's content width, 1232 px (the
  frame less 24 px a side), not the window's 1280.
- Board 07: the "illustrative" marker beside the dialog wraps to the 136 px left before the frame's edge (words 120 px
  wide, three lines, 56 px); one line ran 47 px past the frame.
- Board 10: focus marker 03 is placed from the checked Depth tier option (the group's one Tab stop), with the live
  check's offset `LIVE_DX` (-16 px: the options before it are narrower live than estimated).
- The foot-strip announcement markers sat 16 px over the dialog's lower edge (02, 05, 07, 08, 10; W-37's by 20 px):
  in a dialog frame they are now 40 px tall with 4 px top and bottom insets, placed in the 40 px strip under the
  dialog (`ui.foot_strip_y`, which refuses a marker that does not fit); the SCR-153 frames (no dialog) keep theirs.
  E21-D03 §20 records the drawn overlap as a drawn deviation.
- Backticks: 17 drawn texts carried cite backticks (02: 3, 03: 1, 05: 2, 07: 3, 09: 4, 10: 4); the drawing lane
  removed them live with the words kept. `text()` now strips every backtick from drawn text, and `check_all.py` fails
  on one.
- Every Python child the kit spawns (the validator, the packer, `mkcall4.py`, the generators and the self-test under
  `check_all.py`) runs with `-X utf8`, so the build also runs on a cp1252 Windows host; the packed sheets keep the
  bare raw-sheet name (`check_all.py` runs `mkcall4.py` in `build/`).
- Seeding the token sets, Penpot refused the four `motion.duration.*` primitives; no sheet binds a motion token.
