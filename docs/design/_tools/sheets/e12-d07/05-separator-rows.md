# E12-D07 / 05 separator-rows

File `E12-D07 boards`, page `E12-D07 SCR-045 data table`; export `docs/design/E12/img/E12-D07-05-separator-rows.png`; sheet `05-separator-rows.json` (validated); theme dark.

Board 05 of ten (§0 L79: every separator row of §7.1; the rebuild and cache-loading captions). Grid (24000, 0); 4640 x 2676 px; footer "page E12-D07 SCR-045 data table · board 05 · r1".

## Frames

- `SCR-045∕separators∕non-time · dark`
- `SCR-045∕separators∕time-axis · dark`
- `SCR-045∕captions∕rebuild-and-cache · dark`
- SCR-045∕separators∕non-time · dark: 1280 x 800
- SCR-045∕separators∕time-axis · dark: 1280 x 800
- SCR-045∕captions∕rebuild-and-cache · dark: 1280 x 800
- SCR-045∕separators∕non-time · dark caption: BTCUSDT Vol 50 BTC — 17 bars visible on the chart (2026-10-19 16:40–09:21 UTC) of 171 loaded · open 63,995.9 · close 63,989.2 (−0.01 %) · high 63,995.9 · low 63,982.7 · volume 850.742 · delta +15.250 · prices in USDT, volume in BTC · Bar order · not time · each bar closes at 50 BTC of volume · durations as h:mm:ss
- SCR-045∕separators∕time-axis · dark caption: top “BTCUSDT 1 m — 4 bars visible on the chart (2026-10-19 16:37–16:40 UTC) of 1,266 loaded · open 64,001.5 · close 63,992.8 (−0.01 %) · high 64,002.3 · low 63,992.7 · volume 122.802 · delta +6.480 · prices in USDT, volume in BTC”; bottom “BTCUSDT 1 m — 5 bars visible on the chart (2026-10-19 16:59–17:03 UTC) of 1,266 loaded · open 63,987.2 · close 63,989.3 (+0.00 %) · high 63,990.4 · low 63,986.2 · volume 111.320 · delta +8.530 · prices in USDT, volume in BTC”
- SCR-045∕captions∕rebuild-and-cache · dark caption: top “BTCUSDT Vol 50 BTC — 4 bars visible on the chart (2026-10-19 16:40–16:45 UTC) of 171 loaded · open 63,995.9 · close 63,988.6 (−0.01 %) · high 63,995.9 · low 63,988.5 · volume 200.177 · delta +49.655 · prices in USDT, volume in BTC · Bar order · not time · each bar closes at 50 BTC of volume · durations as h:mm:ss · Showing Volume 50 until ready”; bottom “BTCUSDT 1 m — 4 bars visible on the chart (2026-10-19 17:00–09:16 UTC) of 330 loaded · open 63,989.3 · close 63,987.3 (−0.00 %) · high 63,992.9 · low 63,986.9 · volume 110.696 · delta −6.026 · prices in USDT, volume in BTC · Loading 5m, showing 1m until it arrives”
- sources: spec §7.1 L256–264 (nine kinds), L266 (order where two meet), §7.2 L270, §7.3 L272–275, §7.4 L277, §13 W-1…W-12, W-18; E11-D04 §10 L325–326 (bands); hand-off §H, §E

## Validator and size

- `05-separator-rows.json: 0 errors, 90 warnings, 53 sections, 190410 bytes` (exit 0)
- 53 sections, 190410 bytes

## Live checks (10)

- root 'E12-D07 / 05 separator-rows' at (24000, 0): read back the name exactly after the first section call (a mismatch makes a duplicate root); size 4640 x 2676
- after touchTexts + relayout: the annotation column (estimated 2836 px) ends inside the root (h 2676); raise the root's h if not
- frame 'SCR-045∕separators∕non-time · dark': read back 1280 x 800 at (80, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕separators∕time-axis · dark': read back 1280 x 800 at (1440, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕captions∕rebuild-and-cache · dark': read back 1280 x 800 at (2800, 80) after relayout; no child overflows it (clip on)
- export docs/design/E12/img/E12-D07-05-separator-rows.png: the PNG's frames are each 1280 x 800 device px; record the board id and the PNG size
- focus ring: read back 2 px color.focus.ring on 'separator · gap-non-time · focused' (frame non-time) and 'separator · partial-history · focused' (frame time-axis)
- every 'separator · *' row reads 24 px tall, fill color.surface.hover, text color.text.secondary, text on one line (no wrap)
- the gap row text reads exactly “Recording gap 17:02–09:14 UTC · Series restarted 09:15 UTC”
- two-panel frames: read back panel heights 318 and 318 with a 4 px gutter; each table's last row ends above its footer

## Spec gaps (5)

- W-5 / W-6 <ts> has no format in §13: drawn as “16:40 UTC” (hh:mm UTC, as W-1 / W-2 write their times)
- the caption's visible-range clause names one date (A-11); on the non-time frame it spans the gap, so it reads 2026-10-19 16:40–09:xx UTC with the next day's 09:xx
- W-7 “the last 30 days” and E11-D04's “History starts 2026-09-01 08:00 UTC” are kept verbatim; the seeded series starts 2026-10-19 (placeholders, as A-3 / A-5)
- §7.3 W-8 names only the held Volume 50; the new setting being built is not named, so the toolbar keeps the held Vol 50 BTC; likewise the bottom panel's toolbar keeps 1m while 5m loads
- separators∕time-axis: generation 1 has 22 one-minute bars between the partial-history row and the W-3 row and one panel holds 20 rows, so the frame stacks two panels of the same 1m series scrolled to each row

## Deviations (2)

- separators∕time-axis (boards 05 and 10): two panels of the same 1m series stacked in the dock (CMP-081 4 px gutter), the top scrolled to the partial-history row and the bottom to the W-3 row; 22 one-minute bars lie between them and one panel holds 20 rows
- board 05 captions∕rebuild-and-cache: two chart panels stacked in the dock (CMP-081 4 px gutter), because W-8 and W-9 caption two different series (A-4); every other board 05 frame but separators∕time-axis holds one panel

## Copy keys (14)

- W-7 (§13 L351, verbatim)
- W-6 (§13 L350, verbatim)
- W-2 (§13 L346, verbatim)
- W-1 (§13 L345, verbatim)
- W-10 (§13 L354, verbatim)
- W-12 (§13 L356, PROPOSED, the registry's unit)
- loading-older: E11-D04's band (D04E11:325), unchanged
- W-5 (§13 L349, verbatim)
- W-3 (§13 L347, verbatim)
- W-18 (§13 L362, PROPOSED)
- before-history: E11-D04's band (D04E11:326), unchanged
- W-8 (§13 L352, verbatim, the rebuild copy's last sentence)
- W-4 (§13 L348, verbatim)
- W-9 (§13 L353, verbatim)

## Copy gaps (0)

## Fallbacks (2)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the expander, check and sort glyphs
- fallback: color.text.buy / color.text.sell (E11-D04 CR-D04-2 = E11-D02 CR-5, unregistered) drawn as color.buy.default / color.sell.default; the sign (+ / −) is the carrier (D04E11 §5.4)

## Sources (1)

- spec E12-D07.md md5 d8bbf958 (§0 L79); hand-off §H; E11-D04 §2, §5, §6, §10 (md5 02f3ff69); E12-D04 board kit (chrome geometry)

## Tokens (32)

- color.text.tertiary
- size.icon.sm
- type.ui.label
- color.surface.raised
- color.border.default
- border.hairline
- radius.control
- space.inset.sm
- space.inset.xs
- type.ui.caption
- color.text.secondary
- color.text.primary
- color.surface.hover
- type.num.sm
- color.buy.default
- color.surface.canvas
- color.sell.default
- color.focus.ring
- border.focus
- space.stack.xs
- color.surface.selected
- size.icon
- color.env.demo
- radius.badge
- radius.card
- type.ui.heading-sm
- space.inset.lg
- space.inset.md
- color.surface.app
- color.surface.sunken
- type.ui.body
- space.stack.sm
