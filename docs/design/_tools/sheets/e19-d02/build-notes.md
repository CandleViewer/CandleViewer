# E19-D02 (#416) board kit: build notes

Offline cvsheet v4 sheets for the ten §0 boards of `docs/design/E19/E19-D02.md` (file `E19-D02 boards`, page
`E19-D02`): greyscale desktop wireframes of SCR-038 (docked and overlay) and SCR-039. No Penpot, no network. In a
checkout the kit sits at `docs/design/_tools/sheets/e19-d02/` (raw sheets and their `.md` to `build/`, packed sheets
to `v4/`, each `.md` also beside the kit); outside one it needs `CV_REPO` naming a checkout and writes to sibling
`E19-D02-cap/` and `E19-D02-v4/` folders. `BUILD.md` is the rebuild recipe.

## Sources (md5-pinned in `DOCS`; the kit refuses drifted bytes)

- The spec by repo-relative path, md5 `40b8a21b`: the boards PR's text (§0 drawn, §18 As built). The boards were
  drawn from the text PR's pin, md5 `1299df3b` at `3619e95c5` (PR #5487's merge commit); the boards PR edits §0 and
  a few status lines in place and appends §18, so every cited line keeps its number and the re-pinned kit rebuilds
  the drawn sheets. §0's board table, its not-drawn line, the window size, the board / twin
  counts and §12's copy deck are parsed, never typed; every drawn word passes `k.S` (verbatim in the spec), is a
  `k.W(n)` copy-deck string filled from the world, or is a `copy_gap` note naming its source.
- No hand-off file (BQ-2: E19-D07 is the pack).
- The recorded instrument fixture (`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`): BTCUSDT's tick
  size 0.10 and qty step 0.001, nothing else.
- Tools: the checkout's `docs/design/_tools/sheets/tools/` (validator with `components.offline.json` and the default
  `token-sync.json`, `compact.py` as the packer, `mkcall4.py`). No local tokens.

## Build

```sh
python3 -X utf8 -I -B e19d02kit.py selftest                  # OK: 0 failures
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                           # OK: 0 findings
```

A rebuild is byte-identical (seed 416, one clock; checked: all 30 raw sheets, `.md` and packed sheets hash equal
across two runs). When the spec moves, re-pin its md5 in `DOCS`, rebuild, re-run the self-test and `check_all.py`.

## Layout

| File              | What                                                                                               |
| ----------------- | -------------------------------------------------------------------------------------------------- |
| `e19d02kit.py`    | sources, §0 parse, wire tokens, node builders + lint, metrics, the copy deck, the world, sheet I/O |
| `gen/frames.py`   | chart, docked and overlay hosts, the plot, the states, edge cases, table, SCR-039, menus, flows    |
| `gen/registry.py` | frame id -> builder; `build_board(nn)`                                                             |
| `gen/gen_NN.py`   | one generator per board                                                                            |
| `check_all.py`    | the scan (validator, mkcall4 count, sha256, node rules, wire tokens, icons, captions, cells, pins) |

## Fidelity: greyscale wire tokens only (§2 "Wire tokens")

Frames bind only `color.surface.canvas / .raised / .overlay`, `color.border.default`, `color.text.primary /
.secondary / .tertiary` and `type.ui.label`, `type.ui.caption`, `type.num.sm` (the root's backdrop is
`color.surface.app`, outside every frame). `node()` refuses any other colour or type token and `check_all.py` scans for
them. Value-area bars `.secondary`, other bars `.tertiary`, the POC rail, VAH / VAL ticks and level words `.primary`,
the bracket `.secondary`; a primary button is drawn inverted (`.primary` fill, `.canvas` label). Theme dark; 0 light
twins (§0). Hi-fi is E19-D03's.

## The synthetic world (declared on every board; seed 416)

The E19-D03 kit's world model, re-seeded with 416: BTCUSDT 30-minute bars from 10 Oct 00:00 to 31 Oct 14:30 UTC (the
clock), trend and balance days, recorded trades from 12 Oct 09:00 UTC (bars only before: approximated), no data 13 Oct
04:00–06:00, one stop-run print cluster per session; profiles per `24` §4.5 / §5.2 (POC tie-break chain, single-step
VA at 70 %, HVN / LVN). Row size 100 ticks unless a frame says otherwise. Every number on a board is derived.

## Kit readings (the ambiguities settled; each a `readings` note or an annotation line)

- **Inputs on boards 01 / 02.** §15 places "volume, delta and TPO modes drawn" on boards 01 and 02, while R-3 wants the
  densities comparable: board 01 draws Volume at all three densities (the R-3 comparison); board 02 draws compact
  Volume (Visible range), dense Delta, comfortable TPO (Session, so the IB exists), with the same controls and words.
- **Status slot and CMP-227.** CMP-227 sits in the status slot (§3.1's order: partial chip, CMP-227, degraded tag),
  right after the title row, which §6's "after the title" also reads as; the degraded tag is the slot's last item.
- **Developing bracket.** The open end is the value-area edge on the last price's side.
- **Estimated slot.** D02-C10: no hatch token; each bar's bars-only part is an outlined segment after its recorded part.
- **Glyphs.** HVN / LVN are the §3.1 legend's '>' / '<' characters; shapes are E19-D03's.
- **Overlay '⚙'.** Drawn as the 'Settings' button word (no gear in the icon set); '⋯' is `more-horizontal`.
- **Board 05 condition.** The three no-history frames share a synthetic "never recorded" condition so W-11 holds
  (the rows of §6 name W-11 for the sentence and view-as variants); W-10's filled form is named on the owner frame.
- **Mid-fit.** §4.3's "two stacked frames" are laid out side by side (two 640 × 800 windows) so each keeps the full
  height; both aligned, each with its own priceLow / priceHigh.
- **Aligned scale.** The chart's auto-fit holds its bars and the profile's rows; the panel's rows go through that
  frame's price -> y (linear) or `26`:221's log mapping (aligned-log: a 21-session composite at 2 000-tick rows, so the
  top / bottom heights differ measurably; the ratio is annotated).
- **Edge 5 000 rows.** The longest bar suffix within 5 000 rows at row size 1 (4 487 rows); merged to fit the drawn
  plot (not §7's PROPOSED 620 px; annotated).
- **Two-level.** A synthetic two-level BTCUSDT profile (80 % / 20 %, the second at zero delta), drawn in Delta.
- **Partial / composite.** Requests that start before the world (8–14 Oct; 1–30 Oct) yield the partial chip, W-7's
  gap ranges and CMP-227 for the bars-only part together (PD-5 order).
- **Table.** The docked table keeps `05`'s five columns, Price sticky, the rest scrolling (§11 R1); MEMO A-6's columns
  are a board marker (proposed, not built).
- **Copy gaps.** Interval words (30m, 2h, 4h), the date / duration / start-end forms, the view-as name "Sam", the
  user's preset names, board-marker titles, the Period radios' one-line descriptions (a grey placeholder line).

## T2 (§1.4; E09-D09 §2.1)

Board 09 draws the three T2 controls: the SCR-038 header's `Save preset…` (2a inline in the menu, W-15 its second
line), SCR-039 `Save` and the footer menu's `Save preset…` (both described by the one dialog-header notice). Each has
the CMP-019 lock leading, its full label in `color.text.tertiary`, the raised fill with the default hairline,
`aria-disabled` (never `disabled`, never `color.text.disabled` / `opacity.disabled`: refused by `node()`). Board 05's
no-history CTA for non-owners and under view-as is the sentence form: no control, no glyph.

## Icons

The repo's `run/local-icons.js` carries `locked`, `arrow-up`, `arrow-down` (used). The kit also uses `chevron-down`,
`check`, `info`, `warning`, `danger`, `pending` and `more-horizontal`, which this folder's `local-icons.js` adds (each
its `packages/ui` Lucide SVG, path data unchanged); each sheet's `icons` notes name them; run that seed in place of
the shared one.

## Check findings settled (offline check of the boards kit)

- W-8's methodology line "approximated from bars" is drawn verbatim in a board marker on `SCR-038/approximated`
  (board 04; SCR-058's drawer is not this spec's).
- W-35: both forms ("Showing table", "Showing histogram") are drawn in board 07's "announced on the swap" marker.
- Announcement-only strings are declared in each md's "Not drawn" section (`k.not_drawn_w`), verbatim, with the
  spec line and "the text is binding": W-33 on every board carrying the "Levels (derived)" annotation; W-34 on 07;
  W-36, W-37, W-39 on 08; W-38 on 08 and 09 (named in the annotation notes only, on no frame).
- Live checks name centring precisely: the SCR-039 dialog is "centred horizontally and vertically" with its sums;
  every board marker is "anchored top-left at (x, y)", never re-centred; one board-level line says nothing else is
  centred. `check_all.py` asserts the drawn and declared W-strings per board (`DRAWN_W`, `NOT_DRAWN_W`).
- W-17 and W-18 (`SCR-038/load-failed`, `SCR-038/stale`) are declared not drawn in board 04's md: outside the
  10-board cap, as §0's not-drawn line says.

## Live-check fold (render 2026-11-03, dark)

The drawing lane's live check returned three SHEET-FIX lines, made on the boards and folded here (no sheet was
hand-edited; the rebuilt raw sheets differ from the rendered ones only in these values and their notes):

- Legend keys: every `key …` row 12 → 14 px (the caption's line height; 12 cut 1 px top and bottom), the HVN / LVN
  `mark` 14 px with its `glyph` at the mark's top (y −1 → 0). The legend keeps its drawn height: `legend()` sizes it
  from the 12 px rows, and `check_all.py` lets the rows take the legend's bottom inset, nothing else.
- Board 02, `SCR-038/overlay-comfortable`: the `IB label` sat 6 px above the plot top (cut); where that happens it now
  sits beside the IB bar, x = bar x − 14 − 4 (its laid-out width read back), y = the bar's top.
- Root heights: `LIVE_ROOT_H`, the read-back max(annotation end, footer end) + 80: 1878 (01–03, 05, 06, 08–10),
  2758 (04), 1011 (07), checked under the kit's own estimate.
