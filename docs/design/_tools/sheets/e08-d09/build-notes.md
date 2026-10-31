# E08-D09 board kit: build notes (#177 PR 3, the ten boards)

Kit `e08d09kit.py` (this folder). Spec, binding, every string from it: `docs/design/E08/E08-D09.md` and
`E08-D09-handoff.md`, read from this checkout by repo-relative path (md5 pinned in `SPEC_MD5`: spec `9146d4d4…`,
hand-off `3dc8240e…`, the texts as PR 3 commits them; the kit refuses drifted bytes). Every `L<n>` cite is looked up
with `k.L()`, never typed. The boards were drawn at spec `30646600…` and hand-off `e6bb50a9…`, before §0's as-built
record and the hand-off's ticks, which PR 3 made in place (no line added or removed, so every cite holds); §0's board
table gained its As built column, which the kit's row pattern skips. A rebuild differs from the drawn sheets in the
two md5s of `notes.sources` only (checked node by node).

## Pipeline

1. Board author writes `gen/gen_NN.py` (one per board; a twin's generator imports its base's `build(theme)`):
   `frames = [k.window(fid, theme, sections, scroll=…, overlays=…) for each FRAME_PLAN entry, in order]`,
   `ann = k.annotations(nn, [k.frame_block(fid, …) …])`.
2. `p = k.write_sheet(nn, frames, ann)` → `build/NN-<slug>.json` (untracked); validator
   (`../tools/validate_sheet.py --components ../tools/components.offline.json --tokens ../tools/token-sync.json`)
   must exit 0, kit lint and the banned-string scan clean, `notes.live_checks` non-empty, else `RuntimeError`.
3. `k.write_md(nn, p)` → `NN-<slug>.md` in this folder and in `build/`; line 3 is the render script's line:
   ``File `E08-D09 boards`, page `E08-D09 SCR-147 Connectivity`; export `docs/design/E08/img/E08-D09-NN-<slug>.png`;
sheet `NN-<slug>.json` (validated); theme dark.`` (`theme light.` for 08, 09; `theme hc.` for 10).
4. `k.pack_sheet(p)` → `v4/NN-<slug>.json` (`../tools/compact.py`): `../tools/mkcall4.py <packed> count` equals the
   section count, then `compactOf.file` is made the bare raw-sheet name, its sha256 the raw sheet's (checked); every
   packed section ≤ 9 216 B.
5. Live (not this kit): the per-set file `E08-D09 boards` with tokens, icons and the dark theme, each packed sheet
   rendered with the shared drivers (`../README.md`, `../run/`), the live checks from the md, the export with the
   theme cycle (board 10 under the high-contrast set, `../run/theme-hc.js`).

Self-test: `python3 -I -B e08d09kit.py selftest` (writes `build/selftest/00-selftest.{json,md,packed.json}`).

## File, page, grid

- Penpot file `E08-D09 boards`; page `E08-D09 SCR-147 Connectivity` (§0, RULED BQ-25; the page id and the board ids are in spec §0 as built).
- Root per board: name exactly §0's, fill `color.surface.app`, clip; at x = ((NN−1) mod 5) × 6000,
  y = floor((NN−1)/5) × 3200; hugs its frames + ONE 400 px annotation column + 80 px margin.
- Frames 1:1, 1280 × 800 each (§0: "Every frame is a 1280 × 800 window"), 80 px gutters; 2 frames → 1 row of 2;
  4 → 2 × 2; otherwise rows of 3. A `state: <fid>` caption (caption, tertiary) sits 28 px above each frame; the W-01
  footer "illustrative values, not a market capture" sits 24 px under the last frame row (§0: every board with
  numbers carries it; all ten do).
- Frame name: `SCR-147 · <fid> · <theme>` (no "/").

| #   | Board (§0, exact)                    | Theme | Twin of | Frames | Grid (x, y)   | Root (est.)  | Export                                                     |
| --- | ------------------------------------ | ----- | ------- | ------ | ------------- | ------------ | ---------------------------------------------------------- |
| 01  | `E08-D09 / 01 healthy`               | dark  | —       | 9      | (0, 0)        | ~4640 × 2720 | `docs/design/E08/img/E08-D09-01-healthy.png`               |
| 02  | `E08-D09 / 02 approaching-throttled` | dark  | —       | 2      | (6000, 0)     | ~3280 × 960+ | `docs/design/E08/img/E08-D09-02-approaching-throttled.png` |
| 03  | `E08-D09 / 03 held-banned`           | dark  | —       | 2      | (12000, 0)    | ~3280 × 960+ | `docs/design/E08/img/E08-D09-03-held-banned.png`           |
| 04  | `E08-D09 / 04 ws-states`             | dark  | —       | 5      | (18000, 0)    | ~4640 × 1840 | `docs/design/E08/img/E08-D09-04-ws-states.png`             |
| 05  | `E08-D09 / 05 clock`                 | dark  | —       | 6      | (24000, 0)    | ~4640 × 1840 | `docs/design/E08/img/E08-D09-05-clock.png`                 |
| 06  | `E08-D09 / 06 simulator-budget`      | dark  | —       | 5      | (0, 3200)     | ~4640 × 1840 | `docs/design/E08/img/E08-D09-06-simulator-budget.png`      |
| 07  | `E08-D09 / 07 inspector-history`     | dark  | —       | 7      | (6000, 3200)  | ~4640 × 2720 | `docs/design/E08/img/E08-D09-07-inspector-history.png`     |
| 08  | `E08-D09 / 08 healthy-light`         | light | 01      | 9      | (12000, 3200) | ~4640 × 2720 | `docs/design/E08/img/E08-D09-08-healthy-light.png`         |
| 09  | `E08-D09 / 09 clock-light`           | light | 05      | 6      | (18000, 3200) | ~4640 × 1840 | `docs/design/E08/img/E08-D09-09-clock-light.png`           |
| 10  | `E08-D09 / 10 throttled-hc`          | hc    | 02      | 2      | (24000, 3200) | ~3280 × 960+ | `docs/design/E08/img/E08-D09-10-throttled-hc.png`          |

Sheet file `NN-<slug>.json`. Heights grow with the annotation column (`board()` raises past 5800 × 3000).

## Frames (`k.FRAME_PLAN`; ids are §5.2's state ids + its State words, or §0's own words)

Twins draw their base board's frames, same values, in their theme (`theme` suffix in the name).

- 01: `S-01 healthy · top` · `S-01 healthy · middle` · `S-01 healthy · bottom` (the whole page in three scroll
  positions) · `S-13 loading` · `S-15 stale` · `S-16 degraded` · `S-17 error: our counters not reporting` ·
  `S-18 unavailable: the read itself failed` · `S-19 not connected yet`
- 02: `S-02 approaching limit` · `S-03 throttled`
- 03: `S-04 held by IP` · `S-05 banned`
- 04: `S-06 WS disconnected` · `S-07 reconnecting` · `S-08 resubscribe storm` · `S-20 our queue dropping updates` ·
  `Force reconnect dialog`
- 05: `S-09 clock warning` · `S-10 clock alarm: order entry halted` · `S-11 10002 seen` ·
  `S-12 clock not measured yet` · `re-measure busy` · `re-measure cooldown`
- 06: `S-19 not connected yet · simulator` · `simulator result` · `Change budget dialog` · `Change budget refusal` ·
  `T2 view-as forms`
- 07: `inspector · 36 topic rows` · `inspector · 120 topic rows` · `inspector · 480 topic rows` · `S-14 empty` ·
  `history sparkline and table` · `history empty` · `S-19 not connected yet · inspector and history`

Every S-01 … S-20 is on a frame (§18 R4; the self-test checks it and §5.2's Board column).

## Themes

01–07 dark; 08, 09 light (twins of 01, 05); 10 hc (twin of 02). Sheets are theme-free (token binds only); the
theme is set on the file before export. §16: no new token; rate and clock states bind `color.status.*.strong` /
`color.neutral.default`; connection rows and old values bind `color.data-confidence.{disconnected,reconnecting,
stale}.*`; meters `color.action.primary.default` / `color.status.warning.strong` / `color.status.danger.default` on a
`color.surface.hover` track; every state keeps its word and glyph (R-5; DS-CR-1).

## The window (SCR-147 anatomy, §2.1–§2.2, in CMP-087 at comfortable density)

`k.window(fid, theme, sections, scroll=0, overlays=())`: TopBar 48 · NavRail 64 | main 976 (944 inside) | RightRail
240 · StatusBar 48 (E42 admin-kit geometry; the E10 chrome drawn as neutral placeholders, a recorded kit choice).
The page inside main, in §2.2's Tab order: CMP-087 band "Admin area" (56) → 4 px rule → CMP-088 PageHeader (h1
W-02, meta W-03 "All times UTC · as of {AS_OF}") → summary strip (five CMP-178 tiles: REST budget, Public market
data, Private streams, Clock, IP hold) → Rate budgets (per-class table §3 + reserve band §7) → Fan-out simulator (§8)
→ Subscription inspector (disclosure W-44, closed by default, §9) → Clock (§10, a dl of CMP-036 rows) → Actions
(Reconnect market data, §11) → Usage history (disclosure W-70, closed, §14). The page scrolls inside main: `scroll`
moves it up (the 672 px view); dialogs come in `overlays=k.modal(dialog)`.

## Annotation column (ONE, 400 px, right of the frames; `k.annotations`)

- Title: the board name. Block "Board": §0 line + Draws cell, theme (+ twin), export path, the W-01 footer line.
- One block per frame, `k.frame_block(fid, …)`, auto-filled from the spec for each S-id of the frame: the register
  row (§5.2: word + W-id, origin, glyph, tone token, trigger, exit, announcement, max rate), its SR rows and strings
  (§17.4), the origin's operator action line (W-12); then the author's: `waits=` G-rows (§21.2, gap text),
  `suppressed=` states hidden by §5.2's precedence, `recovery=True` (SR-9 on exit), `keyboard=` (§17.3 KB/PP ids),
  `lines=` (derivations such as "Retry at 14:02:53 = as of 14:02:11 + 42 s", T2 rows §17.5, copy-gap notes).
- Footer: `page E08-D09 SCR-147 Connectivity · board NN · r1`.

## The illustrative world (one clock, derived values)

`AS_OF = 14:02:11` (W-03's own example); every other time is `k.at(±s)`, every duration `k.dur(s)`, ages `k.ago(s)`.
Limits from `k.LIM` (§3.2 documented defaults: order.create 10/s, reads 50/s, IP 600 per 5 s; Public WS 500 new per
5 min, 1000 concurrent; planner 10 topics / 21 000 characters per request, 500 topics per socket; clock warn 500 ms,
halt 2 000 ms, every 300 s, stale 900 s; S-02 at 80 %, S-15 at 5 s, virtualise past 60 rows). Accounts
`k.ACCOUNTS`: "Main" is the spec's slot; Swing, Scalp, Hedge, Desk are kit choices (record via `k.deviate`). Copy
only through `k.w(key, piece, *values)`: slots are filled from the frame's own data (a missing value raises;
`sample=True` keeps the spec's slot and records it). Never type a number that contradicts another on the frame.

## Per-board content (from §0 and the sections it cites)

- 01 (§2–§14): S-01 top/middle/bottom = the whole page served and healthy (every figure with its unit, W-13; inspector
  and history closed). Sub-frames: the budgets section in S-13 (CMP-015 skeleton, aria-busy), S-15 (W-04 "as of" +
  "Stale {4s}", data-confidence.stale), S-16 (W-24, one slice error beside one ok), S-17 (W-25, last good), S-18
  (W-26 + Retry), S-19 (W-05 in Used now, Headroom and the meter's place; meter not drawn; per-minute fallback W-10
  per §3.3) — each G-section in S-19 beside its served form, marked with its G-row.
- 02: S-02 (W-14, ≥ 80 % of the spendable budget, one account's order row); S-03 (W-15: account, class, limit,
  retry time absolute + relative, code 10006; W-31 condition; W-34 what not to do).
- 03: S-04 (W-16, all accounts, our hold's time left, W-33, W-32, W-34; Reconnect T2 with W-36) and S-05 (W-17,
  "Time left: not received", contract-first D09-G13), side by side; each prints only its own condition sentence.
- 04: S-06 (W-18, assertive SR-5), S-07 (W-19 attempt n), S-08 (W-20), S-20 (W-28); Force reconnect dialog (§11:
  W-50 title/confirm, W-51 five consequences + W-56, W-52 blast radius, W-54, W-55 marker, Cancel focused;
  contract-first D09-G7).
- 05: S-09 (W-21, W-38 size + direction in words, W-37, W-39), S-10 (W-22 both pieces), S-11 (+ W-27), S-12 (W-23,
  no number, never "In sync"); re-measure busy (W-35 "Measuring…", aria-busy) and cooldown (T2-3, W-36b).
- 06: simulator S-19 (inputs live, output W-05, D09-G10); result (W-40, per-account Served now / Deferred W-42, the
  IP bucket line, W-41 "Stop-loss: always counted"); Change budget dialog (§12: W-60…W-64, the four invariants, rung
  1, D09-G8); refusal (CMP-027 under the field, value kept, T2-4); T2 view-as forms of both actions (W-74, §17.5
  T2-1, T2-2, lock leading the full label).
- 07: inspector at 36 / 120 / 480 topic rows over 3 connections (W-44…W-48; grid + aria-rowcount past 60; "Binding:"
  W-47); S-14 (W-30); history open (W-70, W-71, sparkline + its table, trend label W-72); history empty (W-73);
  S-19 for both (D09-G3, D09-G4, D09-G9).
- 08, 09, 10: the base board's frames and values in light / light / hc.

## Pairs (five parallel authors; each twin with its base)

| Pair | Boards                                     | Frames | Note                                     |
| ---- | ------------------------------------------ | ------ | ---------------------------------------- |
| A    | 01 healthy + 08 healthy-light              | 9 + 9  | 08 = 01's `build("light")`               |
| B    | 05 clock + 09 clock-light                  | 6 + 6  | 09 = 05's `build("light")`               |
| C    | 02 approaching-throttled + 10 throttled-hc | 2 + 2  | 10 = 02's `build("hc")`                  |
| D    | 03 held-banned + 07 inspector-history      | 2 + 7  |                                          |
| E    | 04 ws-states + 06 simulator-budget         | 5 + 5  | both dialogs: share one `dialog()` style |

## Kit API (`import e08d09kit as k`)

- Registry: `BOARDS[nn]` (name, slug, draws, theme, line, twin, states, export, sheet, base), `TWINS`, `PAIRS`,
  `FRAME_PLAN`, `frames_of(nn)`, `frame_name(fid, theme)`, `grid_xy(nn)`.
- Spec data: `REGISTER[sid]` (§5.2 row), `PRECEDENCE`, `COPY[key]`, `SR`, `SR_FOR[sid]`, `T2_ROWS`, `GROWS`, `L()`,
  `HL()`.
- Copy: `w(key, piece, *values, sample=False)`, `state_word(sid)`, `origin_label(sid)`, `origin_action(sid)`, `g(gid)`.
- World: `AS_OF`, `at(s)`, `dur(s)`, `ago(s)`, `pct(u, l)`, `LIM`, `ACCOUNTS`, `ORDER_CLASSES`, `QUERY_CLASSES`.
- Window: `window(fid, theme, sections, scroll=, overlays=)`, `band()`, `rule()`, `page_header(as_of)`; geometry
  `INNER_W 944`, `VIEW_H 672`.
- Sections: `section(h2, kids, waits=)`, `summary_strip(tiles)`, `tile(heading, sid, number, w_=, gid=, status=)`,
  `TILE_HEADINGS`, `tile_widths()`, `clock_ok_status(ms, dir)`, `state_line(sid, figures, w_=)`, `glyph(kind, colour)`,
  `tone_color(sid)`, `not_connected(name, gid)`, `g_tag(gid)`.
- Tables: `Col`, `cell()`, `header_row(cols)`, `table_row(cols, cells, name, i, h=None)` (auto height, raises on
  overflow), `table(name, caption, header, rows)`, `BUDGET_COLS` (= 944), `budget_header()`, `row_action()`,
  `meter(used, limit, tone=, valuetext=)`, `reserve_band([(alias, n|None)])`, `kv_row()`.
- Controls: `button()`, `busy_button()`, `t2_button(chars, reason)`, `ring()`, `inline_error()`, `skeleton()`,
  `disclosure()`, `checkbox()`, `number_field()`, `segmented()`, `sparkline(values)`, `dialog(title, kids,
actions)`, `lines_block()`, `modal(dialog)`.
- Notes: `live()`, `deviate()`, `spec_gap()`, `copy_gap()`, `fallback(key)`; output: `frame_block()`,
  `annotations()`, `write_sheet()`, `write_md()`, `pack_sheet()`, `validate()`; `selftest()`.

## Rules (hard checks in the kit)

No `inst` node; icons only from the 18-name local set (CMP-178's ring = ellipse outline, clock = `pending`,
triangle = `warning`, octagon = `danger`, all recorded as fallbacks); `o.wrap` only "wrap"/"nowrap"; every flex
child with no text has an explicit h; table cells padX 8 px a side (lint); no "/" in names; no local path, host or
agent name anywhere in a sheet or md; packed sections ≤ 9 KB; every frame 1280 × 800; frame names must equal
FRAME_PLAN in the board's theme (`write_sheet(strict=True)`); every sheet has `notes.live_checks`.

## Spec ambiguities (the kit's reading; raise with the orchestrator if it matters)

1. Board 01 "the whole page" vs "every frame a 1280 × 800 window": drawn as three scroll positions of S-01.
2. 01's "sub-frames" S-13 … S-19: drawn as full windows (§0), each with the budgets section in that state; §0 does
   not name the section.
3. 07 "3 connections at 36, 120 and 480 topic rows (the last past the threshold)": the virtualisation threshold is
   60 rows (§9), so 120 is past it too; read as three scale frames; W-44 / W-52's sample "{120} topics" is a slot.
4. 05's "re-measure button busy and in cooldown" and 06's / 07's views have no S-id: frames named by §0's words.
5. S-19 is listed for boards 01, 06, 07 in §5.2 but not in §0's 06 / 07 Draws cells: added from §0's "drawn in its
   'Not connected yet' state … and in its served form beside it".
6. Only "Main" is a spec alias; the simulator needs five accounts: four kit aliases.
7. No string for the G-row mark ("Waits on D09-Gn", kit), the section h2s (§2.2's anatomy names), the Meter / State
   / action headings (W-08 lists six), the dialog width (560, kit), the band text ("Admin area", §2.1).
8. Served-form Headroom subtracts the reserve (R-4) but the reserve is never served (D09-G14): a "served" frame must
   assume D09-G14 served or show S-19 in Headroom; authors annotate which.
9. The E10 chrome is not this spec's: placeholders, E42 admin geometry (RightRail kept).
10. Export of board 10 needs the hc theme in the export loop (resolved: exported under the hc set).

## Live-check fold (2026-10-31; the live-check report's SHEET-FIX lines)

The live check fixed these by moving or resizing the drawn shapes; each is folded into the kit so a rebuild reproduces
the drawn boards (a `.pre-livefix` copy of every edited file was kept outside the repository):

- Root h: `k.MEASURED_H` (the live-measured max(annotation end, footer end) + 80; `text_h` over-estimates the column;
  on 07 the footer ends below the annotations): 01 2758, 02 1926, 03 1455, 04 2506, 05 2270, 06 1878, 07 2758,
  08 2758, 09 2244, 10 1957 (the sheets said 2960 / 2088 / 1592 / 2760 / 2576 / 1912 / 2824 / 2888 / 2552 / 2088).
  `board()` uses it for strict boards and raises if it would not clear the frames + 80.
- 01 / 08 S-01 bottom: the page measures 1868 px (estimated 1860), so the bottom view scrolls 1196 px
  (`gen_01.MEASURED_PAGE_H − k.VIEW_H`; page y −1172 → −1180). The annotation keeps the estimate it was drawn with.
- 01 / 08 S-16 … S-19 budgets columns (`pair1_helpers.S_COLS`): Account 80 → 76, Window 56 → 60 (the header
  "Window" is 43 px, past a 56 px column's 40 inner).
- 03 S-05: the REST budget and IP hold tiles' state word wraps at the tile's inner width, 147 px
  (`k.tile(wrap_word=True)`; W-17 "Banned by the exchange" is 154 px and was clipped by 7 px, the one ruled-string
  fix), and the frame scrolls 30 px further than S-04 (`gen_03.SCROLL_OF`, page y −164 → −194) so three account rows
  show as on S-04.
- 04 / 06 dialogs: centred on their drawn heights (`k.modal(dlg, measured_h=…)`): 04 380 (estimated 389,
  y 205 → 210), 06 490 and 521 (estimated 482 and 512, y 159 → 155 and 144 → 140).
- 06 reserve band (`k.reserve_band(label_w=288)` in `pair5_helpers.budgets`): label 280 → 288, value 664 → 656 (the
  "· Hedge" label sat 2 px into the padding).

Regenerated all ten; validator exit 0 ×10. Node by node against the sheets before the fold, only the fix targets
changed: 01 and 08 the root h, the bottom frame's page y and the notes of its frame and main column (3 nodes) and
the Account and Window cells of the S-16 … S-19 headers and rows (38 nodes); 02, 05, 07, 09, 10 the root h only;
03 the root h, S-05's page y and main-column note and the two tiles' word widths (4 nodes); 04 the root h and the
dialog's y (1 node); 06 the root h, the reserve band's label and value widths on all five frames (50 nodes) and the
two dialogs' y (2 nodes). Every sheet's notes differ only in the live-check lines that carry the sizes.
