# E12-D07 (#242) — PR 2 board sheets: build notes (binding for the five board authors)

Spec (binding; every string comes from it): `docs/design/E12/E12-D07.md` (§0 the ten boards; §2 row header; §3 the
column sets; §4 chart-type cells; §5 widths; §6 `state` words; §7 separator rows and captions; §9 sync; §13 the copy
deck W-1..W-22; §14 tokens) and `docs/design/E12/E12-D07-handoff.md` (§H the frames; §E the owner walkthrough), read
from this checkout by repo-relative path, as this PR commits them (md5 pins in the kit's `SPEC_MD5`: spec `299bc3f6`,
hand-off `5f7f9099`, E11-D04 `02f3ff69`, E12-D06 `b9a9bc57`; the kit refuses to run on drifted bytes, so every
`L<n>` cite, looked up by `k.L` / `k.HL`, holds against the committed text). The SCR-045 shell is E11-D04's
(`docs/design/E11/E11-D04.md` §2 anatomy, §5 columns/200 %, §6 rows, §7 banner, §10 table states): consume it, never
redraw it differently. The window chrome and panel geometry follow the committed E12-D04 board kit
(`docs/design/_tools/sheets/e12-d04/`): TopBar 80, NavRail 64, RightRail strip 48 (240 open), StatusBar 48, tab strip
32, compact controls and rows 24.

## 1. Pipeline (offline; nothing here touches Penpot)

1. A generator per board, `gen/gen_NN.py` (helpers `gen/pairN_helpers.py`), imports the kit
   (`sys.path.insert(0, <kit dir>)`, `import e12d07kit as k`) and builds the board's frames + its annotation
   blocks.
2. `k.write_sheet(nn, frames, ann)` → `build/NN-<slug>.json` (untracked): assembles the board (grid x/y, plain root hugging
   frames + annotation column + 80), splits sections (≤ 9,000 raw bytes each), runs the kit lint (no inst, icon set,
   wrap strings, explicit h, no "/" in names, no banned strings) and `tools/validate_sheet.py --components
tools/components.offline.json`; raises `RuntimeError` unless exit 0.
3. `k.write_md(nn, sheet_path, summary=..., frames_info=[...])` → `NN-<slug>.md` in the kit folder. Line 1 `# <board name>`,
   line 3 exactly: File `E12-D07 boards`, page `E12-D07 SCR-045 data table`; export
   `docs/design/E12/img/E12-D07-NN-<slug>.png`; sheet `NN-<slug>.json` (validated); theme dark. (`theme light.` on 09,
   10). Then frames, validator line, notes (live checks first).
4. `k.pack_sheet(sheet_path)` → `v4/NN-<slug>.json` (`tools/compact.py`; `compactOf.file` = the bare source file name,
   its sha256 the raw sheet's, checked; every packed section ≤ 9,216 B compact, checked).
5. LIVE (later, a Penpot lane): cvsheet v4.2, one section per call, touchTexts + relayout, lint, export.

Self-test: `python3 -I e12d07kit.py selftest` → 19 PASS, `00-selftest.json` validator exit 0, packed
`00-selftest.packed.json` (both in `build/selftest/`; never rendered).

## 2. Penpot file, page, boards, frames

- File **`E12-D07 boards`** (per-set file: NO library components → no `inst` nodes; every component is a composition
  of primitives named `CMP-nnn <Name> (composition)`), page **`E12-D07 SCR-045 data table`**.
- Board names exactly §0's: `E12-D07 / NN <slug>`; exports `docs/design/E12/img/E12-D07-NN-<slug>.png`.
- Frame names = the hand-off §H ids prefixed `SCR-045/`, e.g. `SCR-045/time/default · dark`. The renderer's section
  paths split on "/", so the kit draws each "/" as U+2215 "∕" (`k.frame_name(fid)`; the layer reads the same). A live
  check may rename the layers to the ASCII form AFTER the last section call of the board.
- Every frame is a 1280 × 800 window (`k.window`) holding one chart panel with the table open in place (D04E11 D2),
  compact density; the two exceptions are recorded below (board 08 at 200 %; board 05's captions frame, §6 A-4).

| NN  | Board name                          | slug                   | Theme | Frames (§H; frame size)                                                                                 |
| --- | ----------------------------------- | ---------------------- | ----- | ------------------------------------------------------------------------------------------------------- |
| 01  | `E12-D07 / 01 time-bars`            | `time-bars`            | dark  | `time/default · dark`, `time/forming-last · dark`, `time/sorted-delta · dark` (1280 × 800 each)         |
| 02  | `E12-D07 / 02 tick-volume-delta`    | `tick-volume-delta`    | dark  | `tick/default · dark`, `tick/wide-auto · dark`, `volume/default · dark`, `delta/default · dark` (2 × 2) |
| 03  | `E12-D07 / 03 range-renko`          | `range-renko`          | dark  | `range/default · dark`, `renko/default · dark`, `renko/seam · dark`                                     |
| 04  | `E12-D07 / 04 row-states`           | `row-states`           | dark  | `states/all-words · dark`, `states/stale-caption · dark`                                                |
| 05  | `E12-D07 / 05 separator-rows`       | `separator-rows`       | dark  | `separators/non-time · dark`, `separators/time-axis · dark`, `captions/rebuild-and-cache · dark`        |
| 06  | `E12-D07 / 06 chart-type-cells`     | `chart-type-cells`     | dark  | `chart-type/baseline · dark`, `chart-type/delta-volume · dark`, `chart-type/equi-volume · dark`         |
| 07  | `E12-D07 / 07 sync-and-edge`        | `sync-and-edge`        | dark  | `sync/before-loaded · dark`, `sync/stale-banner-non-time · dark`                                        |
| 08  | `E12-D07 / 08 reflow-200`           | `reflow-200`           | dark  | `reflow/tick-200 · dark` (640 × 400 CSS px = 1280 × 800 at 200 %; export at 2x)                         |
| 09  | `E12-D07 / 09 row-states-light`     | `row-states-light`     | light | `states/all-words · light` (light twin of 04)                                                           |
| 10  | `E12-D07 / 10 separator-rows-light` | `separator-rows-light` | light | `separators/non-time · light`, `separators/time-axis · light` (light twin of 05)                        |

Light twins (09, 10) are the SAME construction as their base frames (same tokens, same data; the generator reuses the
base board's frame builders with the light fid); the theme switch happens at export (md line 3 `theme light.`; the kit
adds the live check "activate the light token set before exporting").

## 3. Grid and board layout

- Board NN at x = ((NN − 1) mod 5) × 6000, y = floor((NN − 1) / 5) × 3200 (`k.grid_xy`). Every board fits its pitch
  (largest: 3-frame boards 4,640 px wide; board 02 as 2 × 2 is 3,280 × ~1,840); `k.board` raises if a board would come
  within 200 px of its neighbour — then widen the pitch HERE for every board, never per board.
- Root: a plain (non-flex) board, fill `color.surface.app`, clip on; frames 1:1 at x/y with an 80 px margin and 80 px
  gutters (no 80 px spacing token: positions, not a flex gap); at most 3 frames a row (4 frames: 2 × 2); the ONE 400 px
  annotation column (fill `color.surface.canvas`, padding `space.inset.lg`) at the right of the frames + 80; root =
  frames + column + 80 (`k.board`, `k.layout`).

## 4. The annotation column (one per board, outside the frames)

`k.annotations(nn, blocks, board_lines=[...])`: title = the board name; a **Board** block (§0 line and its Draws cell,
theme and twin, export path); then ONE block per frame from `k.frame_block(fid, ...)`, in frame order; footer
`page E12-D07 SCR-045 data table · board NN · r1`. Each frame block carries, in this order:

1. **Frame** — `k.frame_name(fid)`.
2. **State** — the frame's state id (§H id) and what it shows, with its spec section (e.g. "tick/default (§2.2, §3.1
   tick set; auto columns hidden: the panel is narrower than 1,004.4 CSS px)").
3. **Mode / chart type** — `<mode> (<D09 short label>) · chart type: <type>`.
4. **Columns** — `k.columns_line(cols, mode)`: every visible column with its tier and mark `[P field: <REST> / <WS>]`
   or `[A derived: <formula or source>]`; then one line per "—" cell the frame shows, with its reason (R-6: "no delta:
   bar from exchange klines" W-18, "trade count not sent" W-19, "close time not sent" W-20, "delta not sent" W-21, or
   "forming: not closed yet").
5. **Row header** — the drawn form and the focused row's accessible name (`k.row_header`, `k.row_name`: §2.1 time
   `hh:mm`, name `2026-10-20 13:42:00 UTC`; §2.2 non-time `10:22:11.412 bar 3 of 5`, name "bar 3 of 5, opened … UTC,
   closed … UTC after …").
6. **Keyboard and focus** — the path that reaches the frame and where focus sits (E11-D04's grid keys, unchanged:
   `Alt+T` toggles Chart │ Table, focus lands on the cursor bar's row; `↑`/`↓` move with origin `table` and stop on
   separator rows (§7.2); `Home`/`End`, `Ctrl+Home` raises one history page (D04E11:263); `Shift+R` Refresh to current
   (D04E11 §7); `Esc` or `Alt+T` back to the chart). The focused row carries the 2 px `color.focus.ring` (aria-current).
7. **Announcement** — the polite-region string(s) the frame's step produces (E11-D04's "Data table, row k of N",
   "Sorted by delta, descending", §9.1's W-16 "First loaded bar; Loading older bars" once, the banner's
   "Table is on bar …, which is no longer in view on the chart."); separator rows are NOT announced on arrival (§7.2).
8. **Copy** — every W-n the frame draws, keyed and quoted (the kit's `k.copy()` records them in notes too).
9. **Tokens** — `k.frame_tokens(frame)` (every token the frame binds) + the fallback line (buy/sell).

Per frame (what to draw; data from the kit's seeded series, §5 below):

| Frame                                                            | Mode · chart · panel                                                                                                                                                                                       | Rows and states                                                                                                                                                                                                               | Copy                           | Focus / announcement                                          |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------- |
| 01 `time/default`                                                | time 1m · Candle · rail strip (1,168)                                                                                                                                                                      | ~18 closed 1m rows of gen 2 before the forming bar; `state` "—" on all; caption with units                                                                                                                                    | caption units (D04E11:256)     | cursor row mid-table, ring; "Data table, row k of N"          |
| 01 `time/forming-last`                                           | time · Candle · strip                                                                                                                                                                                      | the last rows to 13:42, the forming row LAST: values `color.text.secondary`, `forming` primary, `aria-describedby` "forming bar, values change until close"                                                                   | —                              | forming row focused; its name                                 |
| 01 `time/sorted-delta`                                           | time · Candle · strip                                                                                                                                                                                      | rows sorted by delta ↓ (header arrow, aria-sort), the forming row pinned last; chip "Sorted by delta ↓ — not in time order · separators hidden while sorted" + Reset (the loaded time series holds separator rows)            | W-17                           | "Sorted by delta, descending"                                 |
| 02 `tick/default`                                                | tick · Candle · RightRail OPEN (dock 976): P set only (833.8 fits, 1,004.4 does not)                                                                                                                       | rows around the sweep: 10:22:11.412 bar 1..5 of 5                                                                                                                                                                             | W-10, W-11                     | bar 3 of 5 focused; its name incl. the close clause (T AC2)   |
| 02 `tick/wide-auto`                                              | tick · strip (1,168): `close time` + `duration` join                                                                                                                                                       | same rows; caption + "durations as h:mm:ss"                                                                                                                                                                                   | W-10, W-11                     | same                                                          |
| 02 `volume/default`                                              | volume · strip: P + A                                                                                                                                                                                      | rows around the sweep (several bars share one open time: bar k of 8)                                                                                                                                                          | W-10, W-12                     | —                                                             |
| 02 `delta/default`                                               | delta · strip: P + A (`buy`, `sell`, close time, duration)                                                                                                                                                 | rows incl. the sweep run; `buy` = (v + delta) ÷ 2, `sell` = (v − delta) ÷ 2                                                                                                                                                   | W-10, W-14                     | —                                                             |
| 03 `range/default`                                               | range · strip: P + A                                                                                                                                                                                       | `range` in whole ticks (≥ 40)                                                                                                                                                                                                 | W-10, W-13                     | —                                                             |
| 03 `renko/default`                                               | renko · strip                                                                                                                                                                                              | `brick` up/down words; high/low kept as cells                                                                                                                                                                                 | W-10, W-15                     | —                                                             |
| 03 `renko/seam`                                                  | renko · strip                                                                                                                                                                                              | gen 2 bricks, the seam row (W-1) at the 11:30 cold start, gen 3 bricks; "bar k of n" restarts                                                                                                                                 | W-1, W-10, W-15                | seam row focused: name = its text                             |
| 04 `states/all-words`                                            | time 1m · **Equi-volume** (state 12 chars) · strip                                                                                                                                                         | 13:24–13:42: one row per word — `POC`, `Est.`, `Est.·POC`, `width capped`, `corrected`, `no range` (13:33, the flat bar), `stale`, `forming` last — the others "—"                                                            | —                              | each word's accessible-name addition (§6 table) in the column |
| 04 `states/stale-caption`                                        | time · Candle · strip; status row feed chip "Stale 7s · last 13:42:05"                                                                                                                                     | the stale snapshot's rows `stale`; forming row `forming`; caption ends "values as of 13:42:05"                                                                                                                                | —                              | —                                                             |
| 05 `separators/non-time`                                         | volume (Vol 50 BTC) · strip                                                                                                                                                                                | lookback row (W-7 text + Load more) → built range start (W-6 + Build earlier bars) → gen 1 rows → gap row with the seam appended ("Recording gap 17:02–09:14 UTC · Series restarted 09:15 UTC") → gen 2 rows (bar k restarts) | W-1, W-2, W-6, W-7, W-10, W-12 | a separator row focused (grid row)                            |
| 05 `separators/time-axis`                                        | time 1m · strip                                                                                                                                                                                            | loading-older band (top) → kline rows 16:2x (delta "—", W-18) → partial-history row (W-5, ts 16:40) → gen 1 rows → W-3 row above 17:02 → kline rows inside the gap                                                            | W-3, W-5, W-18                 | —                                                             |
| 05 `captions/rebuild-and-cache`                                  | TWO stacked panels (`k.split_h(2)`; A-4): top Vol 50 BTC rebuilding (caption W-8), bottom 1m loading 5m (caption W-9) with the before-history band and a kline-hole row (W-4, `series("time", hole=True)`) | ~6 rows each                                                                                                                                                                                                                  | W-4, W-8, W-9                  | —                                                             |
| 06 `chart-type/baseline`                                         | time · Baseline · strip: + `vs base` (A) = c − B, B = the base price stated in the column                                                                                                                  | name "above 64,000.0 by 1.2" form (D06:353)                                                                                                                                                                                   | —                              | —                                                             |
| 06 `chart-type/delta-volume`                                     | volume · Delta-volume · strip: + `buy`, `sell`                                                                                                                                                             | —                                                                                                                                                                                                                             | W-10, W-12                     | —                                                             |
| 06 `chart-type/equi-volume`                                      | time · Equi-volume · strip: `state` 12 chars                                                                                                                                                               | one row `width capped`, name "width capped (3.2 × median)"                                                                                                                                                                    | —                              | —                                                             |
| 07 `sync/before-loaded`                                          | tick · strip; the cursor moved before the first loaded bar                                                                                                                                                 | lookback (or loading-older) boundary row, then the first loaded row FOCUSED under it                                                                                                                                          | W-16                           | "First loaded bar; Loading older bars" once                   |
| 07 `sync/stale-banner-non-time`                                  | tick · strip; focused bar left the chart's view                                                                                                                                                            | banner (`k.stale_banner_text(mode="tick")` = W-22 + E11-D04's tail, Shift+R Kbd, Refresh to current)                                                                                                                          | W-22                           | banner announced once, polite                                 |
| 08 `reflow/tick-200`                                             | tick, maximised panel at 640 × 400 CSS px                                                                                                                                                                  | stacked blocks (`k.stacked_block`): heading = row header + `state`; OHLC 2 × 2; close time + duration; volume, delta, trades                                                                                                  | W-10, W-11                     | a block focused                                               |
| 09 `states/all-words · light`                                    | = 04 `states/all-words`                                                                                                                                                                                    | same                                                                                                                                                                                                                          | —                              | same                                                          |
| 10 `separators/non-time · light`, `separators/time-axis · light` | = 05's two frames                                                                                                                                                                                          | same                                                                                                                                                                                                                          | same                           | same                                                          |

## 5. Data (fixed, seeded; `k.series(mode)`)

One trade stream, `random.Random(242)`, BTCUSDT tick 0.1 / qty step 0.001 (the fixture instrument file): generation 1
records 2026-10-19 16:40–17:02 UTC; the recording gap 17:02–09:14 (W-2's times); generation 2 restarts 09:15 (W-1's
time) and runs to the last good time 13:42:05 (§6.2); a buy sweep of 4,600 prints at 2026-10-20 10:22:11.412 (§2.2's
example time) so tick bars 1–5 of 5 share that open time (W-22's "bar 3 of 5" exists); a builder cold start at 11:30
(non-time generation 3: a seam with no gap); one print in minute 13:33 (a flat 1m bar → `no range`). Time-axis kline
rows (`kline=True`, delta/trades "—"): 16:00–16:39 (before order flow, W-5) and 17:02–09:14 (`hole=True` drops them,
W-4's case). Sizes: Tick 1,000 · Vol 50 BTC · Range 40 · Delta 25 BTC · Renko 30 (D09 defaults = W-11..W-15). Every
mode's last row is forming. `k.tag(bar, "stale", "corrected", "width capped", "Est.", "POC")` makes the row-state
specimens (forming and `no range` are derived, never tagged). `k.at(mode, "10:22:11.412")` finds a row.

## 6. Spec ambiguities and the readings this kit takes (state each in the sheet's notes.spec_gaps / deviations)

- **A-1 (§H 02 `tick/default` vs `tick/wide-auto`).** At a 1280 px window the one chart panel is 1,168 CSS px wide
  and every mode's set with its auto columns fits (largest: delta 1,079.8, §5), so "default" and "wide-auto" would
  be the same picture. Reading: `tick/default` opens the RightRail (240 px → dock 976: the primary 833.8 fits, the
  auto 1,004.4 does not, so `close time` / `duration` live only in the row's name and the stacked block); every other
  frame keeps the 48 px strip.
- **A-2 (§2.2's example).** "bar 3 of 5 … closed 10:22:14.020 after 0:02.6" cannot hold: bars sharing one open time
  are consecutive, so bars 1–4 of 5 close at that same millisecond and only bar 5 closes later. The data keeps the
  rule (bars 1–4 close at 10:22:11.412, duration 0:00.0; bar 5 closes ~50 s later); the example string is not drawn.
- **A-3 (§7.1 seam vs W-1/W-2 times).** W-2's gap ends 09:14 and W-1's restart is 09:15, so they meet at one place
  and §7.1 shows the gap row only, the seam appended after "·". A seam with no gap (board 03 `renko/seam`) is the
  11:30 cold start in the data; its row is W-1 verbatim, whose "09:15" is then a copy-deck placeholder (kept verbatim,
  as E12-D06's ruling 7 kept its placeholder times).
- **A-4 (§H 05 `captions/rebuild-and-cache`).** One frame must show two captions (W-8 rebuild, W-9 cache-loading) that
  belong to two different series; one panel has one caption. Reading: this frame's dock holds two chart panels stacked
  (`k.split_h(2)`, CMP-081's 4 px gutter), each with its own toolbar, caption and a few rows. Recorded as a deviation
  from "one chart panel per frame".
- **A-5 (W-6 "Volume 75 BTC" vs D09's Vol 50).** The non-time separator frame draws the Vol 50 BTC series (toolbar,
  W-12) and keeps W-6 verbatim (placeholder, as A-3).
- **A-6 (board 08 at 200 %).** No token scales type ×2, so the frame is drawn in CSS px at 640 × 400 (maximised panel,
  D04E11 §5.2) and exported at 2× to be the 1280 × 800 window (`k.window_maximised`; live check + deviation).
- **A-7 (board 07 `sync/before-loaded`).** The chart is hidden while the table is open in place, so "the chart's cursor
  goes before the loaded window" is not visible in one panel. Reading: draw the table state only (first loaded row
  focused under its boundary row, W-16 announced once) and state the trigger in the annotation; `k.candles` exists if
  the author draws the chart beside it in a second panel ("Open table in a new panel", D04E11 D2) — then record it.
- **A-8 (§H "the recorded fixture paths E12-D06 used").** `packages/fixtures/bybit/2026-10-05/` holds 1m klines
  (2023-11-15, ~62,900, no delta, no trade count) and 542 prints 30 s apart: they cannot close one 1,000-trade bar or
  carry delta. The kit's series are seeded synthetic data (§5), honest bar builds; only the instrument's tick size and
  qty step come from the fixture.
- **A-9 (`vs base` width).** §3.1/§5 give no width for the §4 chart-type cells; the kit reserves 9 characters, the cell
  shows the signed c − B ("+1.2"), the name the D06:353 form ("above 64,000.0 by 1.2").
- **A-10 (frame names).** §H names frames `SCR-045/<id>`; the renderer splits section paths on "/", so the layers
  carry U+2215 "∕" (§2).
- **A-11 (caption date).** D04E11:179 puts the date "in the caption" but its caption example has none; the kit writes
  it inside the visible-range clause "(2026-10-20 10:09–10:39 UTC)".
- **A-12 (buy/sell text colour).** `color.text.buy` / `color.text.sell` are unregistered (E11-D04 CR-D04-2); drawn as
  `color.buy.default` / `color.sell.default` (fallback line), the sign is the carrier.
- **A-13 (`brick` width).** §3.1 and §5 count `brick` at 4 characters, from its values; the header word is 5,
  so the kit sizes every column to fit its header too (`Column.width`), and only `brick` grows (49 px; §0, D07-C17).

## 7. Pairs for the five board authors (a light twin goes with its base board)

| Author | Boards                                          | Why together                                                          |
| ------ | ----------------------------------------------- | --------------------------------------------------------------------- |
| P1     | 01 `time-bars` + 06 `chart-type-cells`          | time-mode rows and the chart-type cells on the time / volume sets     |
| P2     | 02 `tick-volume-delta` + 08 `reflow-200`        | the tick set at 100 % and stacked at 200 %                            |
| P3     | 03 `range-renko` + 07 `sync-and-edge`           | non-time rows (range, renko, the seam) and the non-time edge / banner |
| P4     | 04 `row-states` + 09 `row-states-light`         | base + light twin                                                     |
| P5     | 05 `separator-rows` + 10 `separator-rows-light` | base + light twin                                                     |

## 8. The kit (`e12d07kit.py`) — public functions

Registry: `BOARDS`, `LIGHT_TWINS`, `PAIRS`, `COPY` (W-n), `COLUMNS` (§3.1), `SEPARATORS`, `STATE_ORDER`;
`grid_xy(nn)`, `frame_name(fid)`, `copy(key, ts=)`, `state_word(words)`, `set_width(mode, tiers, equi=)`,
`shown_columns(mode, auto=, extended=, chart=)`, `col_px(name, mode, equi=)`, `row_width(cols, mode, equi=)`.
Data: `series(mode, hole=False)`, `trades()`, `tag(bar, *words)`, `at(mode, "hh:mm[:ss.mmm]", day=)`,
`cell(name, bar, mode, base=, cvd=)`, `cvd_of(rows, bar)`, `row_header(bar, mode)`, `row_name(bar, mode)`,
`f_price/f_qty/f_signed/f_duration/hhmm/hms_ms`.
Chrome: `window(fid, panel|[panels], rail="strip"|"open")`, `window_maximised(fid, panel)`, `dock_w(rail)`,
`split_h(n)`, `panel(mode, table, w=, h=, chart=, chips=)`, `toolbar(mode, chart=, w=)`, `status_row(w=, chips=)`,
`stale_chip()`, `control(...)`, `badge(...)`.
Table: `table(rows, w=, h=, caption_chars=, header=, chips=, banner=, footer=, hint=)` (raises on overflow),
`table_room(h)`, `max_rows(h=, caption_lines=, chips=, banner=, footer=)`, `caption_text(rows, mode, loaded=,
durations=, feed_stale=, aggregation=, rebuild="W-8"|"W-9")`, `caption_lines(chars, w)`, `chip_row(w, sort=,
separators_hidden=)`, `stale_banner_text(bar, mode)`, `stale_banner(chars, w)`, `header_row(cols, mode, sort=,
equi=)`, `bar_row(bar, cols, mode, i, focused=, selected=, stale=, base=, cvd=, equi=)`, `sep_row(kind, cols, mode,
ts=, seam_too=, focused=, action_disabled=)`, `footer_row(w, older=, new_bars=)`, `stacked_block(bar, mode, i, w=,
focused=)`, `candles(bars, w=, h=, cursor=)`.
Sheet: `frame_block(fid, state=, mode=, cols=, row_header_form=, keyboard=, announcement=, copy_keys=, chart=,
tokens=, extra=)`, `columns_line(cols, mode)`, `frame_tokens(frame)`, `annotations(nn, blocks, board_lines=)`,
`board(nn, frames, ann)`, `write_sheet(nn, frames, ann, notes=)`, `write_md(nn, path, summary=, frames_info=)`,
`pack_sheet(path)`, `live(line)`, `spec_gap(line)`, `deviate(line)`, `lint(nodes)`, `selftest()`.

## 9. Rules every author keeps

- Every string from the spec / hand-off / E11-D04 (or the data); never invent copy. Quote W-n through `k.copy()`.
- No `inst` nodes; icons only from the local set (the kit refuses others); `o.wrap` only "wrap" / "nowrap"; every
  flex child without text has an explicit h; no "/" in node names.
- No local path, host, `wt/<digit>`, worker or agent name in any text, note or shape name (the kit's BANNED check).
- Every sheet's notes carry measurable live checks (the kit adds root name, sizes, annotation fit, export size, theme
  for light twins, 2× export for 08); add the board's own (e.g. "read back row 09's ring: 2 px color.focus.ring").
- Keep each packed section ≤ ~9 KB (the kit checks); write files in chunks; offline only.

## Live-check fold (2026-10-29; the live-check report's SHEET-FIX lines)

- `annotations()`: text `data-line` right after `title` (type.ui.caption, color.text.tertiary, w ANN_W − 32 = 368),
  string `k.DATA_LINE`; Board block (block-01) ends with `value-cvd` (type.ui.body, color.text.primary, w 368), string
  `k.CVD_LINE`; both on every board, exactly as drawn live (live/addlib.js).
- gen_03 / gen_07: the board line "Data: seeded synthetic BTCUSDT stream …" (block-01 value-6) dropped, superseded.
- Root h: `k.MEASURED_H` (annotation end + 80, measured live after touchTexts + relayout; `text_h` over-estimates the
  column): 01 2574, 02 2644, 03 2587, 04 2414, 05 2676, 06 2520, 07 2148, 08 1253, 09 1609, 10 1981. `board()` uses it
  for strict boards and raises if it would not clear the frames + 80.
- Regenerated all ten (gen/gen_NN.py), validator exit 0 x10, re-packed (sha256 = raw). Identity
  vs the sheets before the fold: per board only `annotations/data-line` and `annotations/block-01/value-cvd` added,
  `annotations/block-01/value-6` removed on 03 and 07, `board.h` changed; no other node changed; notes differ only in
  the two live-check lines carrying the root size / h. Section counts 05 46→47, 10 33→35 (re-split only).
  Scans: 0 inst, 0 non-string wrap, 0 local-path / worker strings (packed: only compactOf.file, as required).
- Not folded (optional SHEET-FIX): 06 f1 vs-base zero cells "0.0" (spec §4 rules none) — left as is.
