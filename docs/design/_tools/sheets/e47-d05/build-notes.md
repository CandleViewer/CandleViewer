# E47-D05 (#1304) board kit: build notes

Offline cvsheet v4 sheets for the ten §0 boards of `docs/design/E47/E47-D05.md` (file `E47-D05 boards`, page
`E47-D05 SCR-117`), frames from the hand-off's §H. No Penpot, no network. Synthetic data only (seed 1304, BTCUSDT,
tick 0.1 from the recorded fixture), declared on every board's face.

## Build

In a checkout the kit sits at `docs/design/_tools/sheets/e47-d05/` (raw sheets to `build/`, packed to `v4/`);
anywhere else set `CV_CHECKOUT` to a checkout (raw sheets + `.md` to `../E47-D05-cap/`, packed to `../E47-D05-v4/`).

```sh
python3 -X utf8 -I -B e47d05kit.py selftest         # OK: 0 failures
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                  # every sheet "ok", "OK: 0 findings"
```

A rebuild is byte-identical (raw sheets, packed sheets and `.md`). Each packed sheet's `compactOf` is the bare raw
name and the raw sheet's sha256.

## Sources (md5-pinned in `DOCS`; the kit refuses drifted bytes)

- Spec `docs/design/E47/E47-D05.md` and hand-off `E47-D05-handoff.md` as committed with the boards (the text head
  was `3987edc89`; the boards PR edits §0 in place and appends §20, every cited line where it was): §0 (boards,
  file, page, export pattern, the data line, the twins sentence), §H (frames and viewport words), §15 (copy deck),
  §3 (keys), §4 (labels, descriptions), §2 (section order, h1), §5.1 (Effective template, tri-state options), §7.2
  (classes), §7.3 (the burst), §10 (states, synonyms), §6.1 (loop length) are parsed; the COUNT anchors are checked.
- The shipped screen `AccessibilitySettingsScreen.tsx` (ASS), read with `git show` at the base the spec's "Inputs
  pinned" line names (`4c662fd5b`), as the spec cites it: the announce and verbosity radio labels ("as shipped").
- `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`: BTCUSDT's tick size only (checked = §0's 0.1).
- E47-D04 at the pin the spec's Key line names (`48c711e64`, its merge commit), read with `git show`: §7.1's normal / thick ring rows
  (2 / 1 / 2 px and 3 / 2 / 2 px), checked against the drawn bands.

## Boards

| Board                    | Frames | Kind                                                                     |
| ------------------------ | ------ | ------------------------------------------------------------------------ |
| 01 scr117-default        | 1      | the whole page at its full scroll length (1280 wide, 800 px fold marked) |
| 02 scr117-light          | 1      | 01's builder, light set at export                                        |
| 03 hc-zoom-200           | 1      | the stacked 640 CSS px page in three 640 x 800 strips, hc set at export  |
| 04 system-states         | 3      | 1280 x 800 windows at the page top                                       |
| 05 motion-table-tiles    | 3      | windows scrolled to the tile's group                                     |
| 06 focus-tile            | 3      | windows scrolled to Contrast and focus                                   |
| 07 announcement-tile     | 4      | windows scrolled to Announcements                                        |
| 08 keyboard-only-reveal  | 3      | workspace windows (no SettingsNav), a synthetic panel per host           |
| 09 modified-reset-search | 3      | windows; the dialog over a scrim                                         |
| 10 keyboard-order-150    | 1      | the page at 150 % at full scroll length, 17 numbered stops               |

## Kit choices and fallbacks (also in each sheet's notes)

- Chrome (TopBar, NavRail, StatusBar, other CMP-086 entries) as placeholders (the E47-D03 kit's SCR-116 chrome).
- Full-length frames for 01, 02 and 10 (the page outruns the 800 px viewport); strips for the 200 % frame (E47-D03).
- Section membership of the eleven rows is the kit's reading of §2 + §3 (ambiguity note on every board).
- Thick ring as border.focus + border.hairline strokes; links underlined with a 1 px rect; the scrim is
  color.surface.sunken at opacity.scrim; border.control drawn as hairline (dark, light) / thick (hc); 150 % text maps
  to the nearest type token.
- Copy gaps (listed per sheet): "Search settings", "Pause" / "Play", "Play sample", "Sample", "Reset this section",
  "Cancel", the tiles' accessible names, the candle-table headers, the reveal forms' labels, "[latest price]".
- T2 (board 04, forced colours): lock + full label in color.text.tertiary, raised fill with a color.border.default
  hairline, reason W-17 in color.text.secondary, aria-disabled, in the Tab order (drawn focused); never opacity.

## Live-check fold

The drawing lane's twelve SHEET-FIX lines are folded in, so a rebuild reproduces the boards as drawn (spec §20):

- the link underlines are the words' measured widths (`k.MEASURED_UNDERLINE`): 199 and 110 px at 100 % (01, 02,
  03; the estimates were 233 and 116), 314 and 173 px at 150 % (10; 358 and 179);
- the 800 px fold (01, 02, 10) is `dashed · fold · 800 px viewport`: no fill, a 1 px inner `color.status.info.default`
  stroke the post-step dashes (its live line names "dashed style"); board 03's viewport outline says the same;
- board 08: the order line's handle sits at the stop line's y + 5 (420, was 404), the rule edge's at y 260 (was 244);
- board 09: the section-reset dialog is centred on its measured height 178 (`DIALOG_MEASURED_H`; y 311, was 312);
- board 10: a toggle row's text column subtracts its stop marker's own width (28 px for a two-digit stop, 20 for one)
  plus the gap, so `keyboard_only` and `larger_hit_targets` narrow from 882 to 874 px.

Root heights stay at the kit's sizes (the live check kept them). The texts of boards 04, 06 and 09 that did not paint
on the first board after a tab reload were set again live; that is a drawing step, not a kit change.
