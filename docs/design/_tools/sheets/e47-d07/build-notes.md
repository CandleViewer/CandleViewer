# E47-D07 (#1306) board kit: build notes

Offline cvsheet v4 sheets for the ten §0 boards of `docs/design/E47/E47-D07.md` (file `E47-D07 boards`, page
`E47-D07 announcements`), frames from the hand-off's §H. No Penpot, no network. Synthetic data only (the §10 scripts:
seed 1306, BTCUSDT, tick 0.1 from the recorded fixture), declared on every board's face and inside every frame.

## Build

In a checkout the kit sits at `docs/design/_tools/sheets/e47-d07/` (raw sheets to `build/`, packed to `v4/`);
anywhere else set `CV_CHECKOUT` to a checkout (raw sheets + `.md` to `../E47-D07-cap/`, packed to `../E47-D07-v4/`).

```sh
python3 -X utf8 -I -B e47d07kit.py selftest                 # OK: 0 failures
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                          # every sheet "ok", "OK: 0 findings"
```

A rebuild is byte-identical (raw sheets, packed sheets and `.md`). Each packed sheet's `compactOf` is the bare raw
name and the raw sheet's sha256. `check_all.py` re-runs the validator, `mkcall4.py count`, the sha256 pairing, and
scans for inst nodes, icons outside the local set, boolean wrap, forbidden strings, a backtick in drawn text, a sized
callout or tag past its frame, table-cell padding, a caption per frame, md line 3 and the md5 pins.

## Sources (md5-pinned in `DOCS`, as this checkout commits them; the kit refuses drifted bytes)

- Spec `E47-D07.md`, hand-off `E47-D07-handoff.md`, scripts `E47-D07-transcripts.json`: §0 (boards, file, page,
  export pattern, data line, twins sentence, frame rule, the not-drawn list), §H (frames), §3.1 / §3.2, §4, §5.1
  (ranks), §6.4 (matrix), §7.1 (slots), §7.2 (copy deck), §7.3 (reasons), §8.1 (panel classes, the toggle's words)
  are parsed; every `COUNT` / `SIM` anchor the kit uses is checked against what it drew.
- The audit tool `docs/design/_tools/e47_d07_announcement_audit.py`, loaded as a library: `expand`, `replay`,
  `estimate`, `CELLS`. At import the kit asserts the replay of each script equals its expected lines; boards 03, 04,
  08, 09 and 10 draw from that replay (bars, estimates, spacings, counts, filled sentences).
- `docs/design/E09/E09-D09.md`: the `rbac.view_as` reason words (D09E09:95).
- `git show` at the spec's Start-line pins: E47-D04 `48c711e64` (§7.1 ring geometry), E47-D05 `5e4065a44` (the
  SettingsNav label and the tile's button label), the merge commits (the PR heads first read, `1ff5d8cb9` and
  `3987edc89`, carry the same texts).
- `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`: BTCUSDT's tick size only.

## Boards

| Board                 | Frames | Kind                                                                                                     |
| --------------------- | ------ | -------------------------------------------------------------------------------------------------------- |
| 01 taxonomy-map       | 1      | specimen: five class cards, the ranks, 17 panel-class cards + local + silent (55 T-rows once each)       |
| 02 shell-pair-writers | 2      | specimens: writers -> the pair in the DOM; the local reply and §2's four local kinds                     |
| 03 polite-timeline    | 1      | specimen: the fast script's lanes (10 Hz band, cadence, speech, share wait, assertive), the composites   |
| 04 incident-timeline  | 1      | specimen: events, focus / assertive / polite lanes, the ranked queue, CMP-060 rows, the persistent toast |
| 05 focus-kept         | 2      | workspace windows: the reject with "6400" kept; the auto-flatten alertdialog over the scrim              |
| 06 scr117-panel       | 2      | SCR-117 windows: default (T2 safety row focused) and view-as (every control T2)                          |
| 07 scr117-panel-light | 1      | 06's default frame builder, light set at export                                                          |
| 08 verbosity-matrix   | 1      | specimen: §6.4's table with the replay counts re-derived per cell; the assertive lines identical         |
| 09 transcript-preview | 3      | SCR-117 windows: E47-D05's tile carrying each script's expected lines (D05's rows as placeholders)       |
| 10 copy-anatomy       | 1      | specimen: W-1 / W-3 / W-5 split into class word, fact, qualifiers, filled; the account; W-36; the slots  |

## Kit choices and fallbacks (also in each sheet's notes)

- Diagram boards are 1280 x 800 specimen frames ("windows" read as the frame size; no board names a timeline strip).
- Chrome, the ticket's other controls, E47-D05's rows and other SCR-117 sections are neutral placeholders.
- Class tones: a stripe + subtle fill per class; the class word always written (1.4.1). Board 10 reuses them per part.
- T2 (boards 06 / 07): lock glyph + full label in color.text.tertiary, raised fill with a border.default hairline,
  W-39 under the control in color.text.secondary, every radio aria-disabled, the group in the Tab order (drawn
  focused); never opacity.disabled or color.text.disabled.
- The scrim is color.surface.sunken at opacity.scrim (validator WARN: Tier-1 primitive). Board 06's sheet is over
  the validator's size advisory (WARN); it is split into 42 sections, each under 9 KB packed.
- Copy gaps: "Order ticket", "Price" (§9 names the field), board 03's table headings. Synthetic: the viewed user
  `user_02`; the account "Main" is W-43's own example.

## Live-check fold (after the render, 2026-11-03)

The drawing lane drew the ten boards from this kit and returned 20 fix lines and six calls. Folded here, so a rebuild
reproduces the drawn geometry:

- Root heights are the checked `want` (footer end 918 + 80): 998 on all ten (`MEASURED_H`).
- A card's `content` stack takes `measured_stack_h` when taller: each text box at ceil(size x line-height x lines)
  (13 px x 1.4 measures 19 px live, not 18.2), so the class, group and queue cards and the part chips whose last line
  sat in the bottom padding grow 1-2 px (01 ten, 02 five, 04 three, 10 25); the card and its stripe keep the estimate,
  so nothing moves. Board 01 names the ten group cards it grew (`GROWN`): its other cards wrapped shorter live.
- Board 05's auto-flatten dialog: 173 px tall live (`MEASURED_DIALOG_H`), so y 313, 0.5 px above centre.
- The synthetic-data tag sits at `SHELL_TAG_X` 224 in every shell window (05, 06, 07, 09), clear of the StatusBar
  placeholders (x 16-136, 152-208) that x 16 covered.
- Board 05's focus tag in `focus∕reject-kept` sits 8 px lower (it covered the ticket card's bottom 6 px).
- Board 03 draws a share-wait block only before a next composite (§6.1); the first render drew one after the flush.
- Drawn text carries no backtick: `text()` strips them (the first render kept the `05` and `15` cite marks on 01, 02
  and 05); `check_all.py` fails one. The PNGs are not redrawn for these (spec §17, drawn deviations).

Recorded, not folded: board 06's `SCR-117∕announcements-default` texts re-set after a tab reload (a drawing step);
board 04's 1.000 s drop marker crossing the T-30 T-31 bar label (no free space on the lane; the marker is the event's
time); board 02's W-27 reply "Not sent. order entry is paused." is the spec's template filled as written (§7.2 W-27
and §7.3's lower-case words): a fix row to W-27's copy (spec §17); the kit follows the spec when it changes.
