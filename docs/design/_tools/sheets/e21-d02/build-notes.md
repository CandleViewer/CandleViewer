# E21-D02 board kit — build notes

Ticket #440 (E21-D02), the boards PR (it carries the closing keyword; the text merged as #5488, `Refs #440`). Offline:
no Penpot, no network. Every string comes from the spec through `k.W` (the §12 copy deck, slots filled and checked),
`k.Wf` (a copy-deck row whose illustrative figures are replaced by the world's, the form kept) or `k.S` (a spec string,
matched verbatim with code ticks and bold removed); labels the spec does not write are `k.ui(...)` and listed under
each sheet's `notes.copy_gaps`. Every number comes from the seeded world.

## Sources and pins

- Spec `docs/design/E21/E21-D02.md`, md5 `4d99a14edaaa38680621310731662f6d` as the boards PR leaves it (the text merged as #5488 at
  `b4fdf44c9`; the boards PR edits §0 and the pins in place and appends §17 As built); no hand-off file (BQ-2). Ruling of record: comment 6576656158 (BQ-0 … BQ-15 RULED).
- `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` md5 `edd9dd2a060c51bd4bd1450307728ddf`: the
  BTCUSDT tick 0.10 and qty step 0.001 only.
- Tools from the checkout, read-only: `docs/design/_tools/sheets/tools/` (`validate_sheet.py`,
  `components.offline.json`, `token-sync.json`, `compact.py` = the packer, `mkcall4.py`).

The kit reads the spec by repo-relative path from a checkout: in the repo at `docs/design/_tools/sheets/e21-d02/`
(REPO four levels up; raw sheets to `build/`, packed to `v4/`), or from anywhere with `CV_CHECKOUT=<checkout>` (raw
sheets to `../E21-D02-cap/`, packed to `../E21-D02-v4/`).

## Rebuild

From this folder in a checkout (`BUILD.md` has the full recipe):

```sh
python3 -X utf8 -I -B e21d02kit.py selftest          # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                   # builds twice (byte-identical), scans, "OK: 0 failures"
```

The QA preview the authors used (a headless-Chromium render of a raw sheet) is not part of the committed kit.

After the text changes, re-pin: put the new md5 and where it was read in `DOCS` / `HEAD`, run the self-test, fix any
`LookupError` (it names the string that moved or was reworded), then `check_all.py`. The parsers read §0's board
table, §4's states, §12's copy deck, §2.1, §2.3, §2.4, §3.1, §5.1, §5.2, §7.3 (both tables), §7.4 and §9.2 by heading.

## Pipeline

`gen/gen_NN.py` builds the board's frames with `gen/ui.py` (the SCR-050 panel: header, the one notice, the tier and
shed notices, the column header, the pane and the ladder, the footer, the detector strip; the ⋯ menu, the depth
listbox, the row menu, the reveal, the expanded aggregate, the Table view) and calls `ui.run` → `k.build`: the raw
sheet (kit lint, banned scan, validator exit 0), the `.md` sidecar (line 3 is the render line; twins carry the
light-export line), the packed sheet (`compact.py`; `compactOf` = the raw sheet's path and sha256; mkcall4 count =
sections; every packed section ≤ 9216 B). Panel rows are grouped three to a band so a panel packs into ~20 sections.

## The seeded world (seed 440)

Mark 64,012.5 (§2.2's "mark 64,012.5"), best bid 64,012.4, best ask 64,012.6. 500 non-empty levels a side, gaps of
2 + Exp(4.8) ticks, lognormal sizes, a seeded walk over 60 one-second trail columns to 00:12:19 UTC. Rows at a
10 USDT zoom (bids floor, asks ceil), so 25 compact rows show 63,890–64,130 and every one of them holds a level of
the 200 tier. Planted, so the copy deck's figures are the world's: the iceberg at 63,970 (W-14, its prints 2.6), the
stop-run zone 63,900 (W-15), an 18.0 bid wall at 63,960 pulled at column 45 with no print ("pulled 18.0
(estimated)"), the DEMO session's orders (Acct A buy 0.5, Acct B buy 0.4 and 0.3 at 63,980 = W-23 "3 orders · buy
1.2 BTC"; Acct A buy 0.5 at 63,950 = W-22; Acct B sell 0.5 at 64,100), the long 0.30 at 64,020 (W-25; §15 item 1)
and the queue ahead 12.4 (W-24 = the level less the own 1.2 and 0.8 behind). Stops: the 10/35/60/80/95 % quantiles
of the window's cells at the tier (adaptive); legend anchors 0, the middle stop and the window's largest cell.

## Readings (ambiguities settled)

1. Light twins (01, 05, 07): themes are file-wide, so a twin is the same token-bound board exported again under the
   light theme as `E21-D02-NN-<slug>-light.png`; `.md` line 3 stays `theme dark.`; no duplicate frames are drawn.
2. Frame ids: §4's thirteen states on their §0 boards; a variant §0's Draws cell names is `<state> · <variant>` (the
   tier and density strips, the sentence form, ≥ T2, rebuilt, the expanded aggregate, the reveal, the CVD twin set,
   the focus order, the Table view); board-marker frames for the redlines, the legs, the ARMED inset, the legend, the
   exports and the keys. The free-scroll inset is a full 1280 × 800 window.
3. Illustrative figures: drawn verbatim wherever the world can carry them. W-5 / W-6 on the T1 frame read "Stale 7s" /
   "Last update 7 s ago" (the world's age is 7 s; that 7 s is ≥ T2 = 6 s is recorded as a spec gap on board 05); the
   ≥ T2 frame draws W-26 "Stale 15s" and W-27 and no W-6 line (§4 names W-6 for T1). W-24 is one string, "ahead 12.4
   (estimated)", inside the CMP-227 inline badge (no separate chip). W-2 keeps its form with the drawn rows
   (63,910–64,130): its example 63,950–64,120 is 18 rows at 10 USDT (§3.1's comfortable count), no zoom on the 0.1
   tick fits the compact frame's 23 rows to it, and 500 × comfortable is not drawn (§0) — a spec gap on board 02.
   W-7, W-14, W-15, W-21 … W-26 match the world verbatim. §9.2's focused-row readings are derived in the same form.
4. At 1280 px the header holds title · the LOCKED echo · depth · env badge · view switch · follow state · ⋯ (§2.1;
   the follow slot never overflows, §9.4); scale, trail, cell and ARM are drawn inside ⋯ (redlines, arm-locked).
5. The footer is `14`:1211's (qty 0.10 ▾, presets 0.25 / 0.50 / 1.0, BUY MKT, SELL MKT, FLAT, CXL); W-13's {size}
   is the selected 0.10. The ARMED inset, named `inset · ARMED (E30-D04)` for its owner (§0), cites E30-D04's frame without drawing a
   pill (§0's not-drawn list); its words keep §5.3's "labelled E31".
6. LIVE: the synthetic LIVE session holds no order, so no account appears under both environments (C-2.11); the
   Owner has live allowed, so W-20 leads; the rbac.* legs are drawn as notice specimens on the legs frame.
7. Tritanopia: `cvd_sim.py` writes greyscale, deuteranopia and protanopia only; §7.3's computed tritanopia ΔE stands
   (spec gap). The exports are named on board 09 and made at export, never drawn colours.
8. The reveal's heading and column words, the cell chip's "auto · 1 s", the "Detectors" and "Heatmap · time →"
   labels and `14`:1211's footer words are copy gaps (`k.ui`), listed per sheet.
9. No review nit was carried to this PR: the design reads of the text (record, lenses) were folded into the merged
   text; their open NITs are text-only.

## Kit choices (also in each sheet's `notes.fallbacks`)

The env badge's icon as an 8 px dot (outlined DEMO, filled LIVE); CMP-227's glyph and CMP-134's as the local `info`;
the pulled hatch as 2 × 2 steps; the resync scrim color.surface.overlay at opacity.scrim (validator WARN: Tier-1),
as are size.icon.sm (the lock, chevrons) and radius.pill (the chips); menus as color.surface.overlay cards. Icons
used: locked, chevron-down, chevron-right, more-horizontal, info, warning, refresh, check; the shared seed
`../run/local-icons.js` holds only locked of these, so `local-icons.js` here seeds all eight (each glyph the
`packages/ui` Lucide source, path data unchanged).

## Packed sheets and the validator

`validate_sheet.py` checks cvsheet v1 sections; a packed (v4.1) sheet's `styles`, `s` refs and `clone` nodes fail it by
design (the committed E08-D10 v4 sheets fail it the same way). `check_all.py` therefore expands every packed section
with the packer's own `expand_styles` + `materialize` and requires it equal to the raw section, so the raw sheet's
validator verdict (exit 0) covers the packed one.

## Live checks: centring

Only a node a live check names is centred, on the axis it names (the EmptyState card on board 04: horizontally in the
frame and vertically in the panel body; the scrim label on board 06: horizontally, its top fixed a quarter down). Menus,
the listbox, the reveal and the board markers are anchored at named x / y; every other node keeps its sheet position.

## Live-check fold (the drawing lane's fix lines, 2026-11-03)

Every geometry fix line of the live check is folded in, so a rebuild reproduces the drawn sheets node for node (the
sheets' `notes` differ only in the spec pin):

- Root heights: `ROOT_H`, the live max(annotation end, footer end) + 80 (01 2139, 02 1947, 03–06 1026, 07 2126,
  08 1026, 09 1787, 10 1667). The annotation column's live end is not the kit's estimate, so the drawn value is kept;
  the guard allows one caption line of footer-estimate slack (board 07: estimated 2058, live 2046).
- Board 02: the depth listbox popup at the depth control's live left edge, x 273 (`LIVE_DEPTH_X`; the estimate is
  262); the tier-500 band `rows 22-24` keeps whole rows (h 72, not 64) where the clipped band would cut a row's text.
- Board 04: the sentence form's ring is w − 8 and its heading w − 24 (544 and 536 in the 560 px card), the heading's
  box one live line (h 17; the width estimate would wrap it).
- Board 10: the focus-order marker 05 clamps to x 0 inside its frame.
- Kept as drawn: board 04's card top 326 and board 06's scrim label x 560 (the centres are 326.5 and 560.5; the kit
  floors them, the sidecars say so, and the drawing kept the sidecar values).
- The packed sheets in `v4/` keep the bare raw-sheet name in `compactOf.file` (the packer writes the absolute path;
  the kit counts the sections with `mkcall4.py` first, then makes the name bare), and every Python child the kit
  spawns runs with `-X utf8`.
