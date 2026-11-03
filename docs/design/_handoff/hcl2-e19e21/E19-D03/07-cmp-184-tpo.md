# E19-D03 / 07 cmp-184-tpo

File `E19-D03 boards`, page `E19-D03`; export `docs/design/E19/img/E19-D03-07-cmp-184-tpo.png`; sheet `07-cmp-184-tpo.json` (validated); theme dark.

Board 07 of ten (§0 L80: CMP-184 ref frames; SCR-038/tpo-letters-dark, SCR-038/tpo-blocks-dark, SCR-038/tpo-ib-single-prints-dark). Grid (7600, 5600); 3280 x 2536 px; "page E19-D03 · board 07 · r1".

## Frames

- `CMP-184 · MarketProfileTpoPane — ref frame (profile)` (dark, 400 x 560)
- `CMP-184 · MarketProfileTpoPane — ref frame (blocks)` (dark, 400 x 560)
- `CMP-184 · MarketProfileTpoPane — ref frame (ib)` (dark, 400 x 560)
- `CMP-184 · MarketProfileTpoPane — ref frame (greyscale)` (dark, 400 x 560)
- `SCR-038∕tpo-letters-dark` (dark, 1280 x 800)
- `SCR-038∕tpo-blocks-dark` (dark, 1280 x 800)
- `SCR-038∕tpo-ib-single-prints-dark` (dark, 1280 x 800)

## Validator and size

- `07-cmp-184-tpo.json: 0 errors, 33 warnings, 40 sections, 194466 bytes` (exit 0)
- 40 sections, 194466 bytes

## Live checks (11)

- root 'E19-D03 / 07 cmp-184-tpo' at (7600, 5600): read back the name exactly after the first section call; size 3280 x 2536
- after touchTexts + relayout: the annotation column (estimated 980 px) ends inside the root (h 2536); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'CMP-184 · MarketProfileTpoPane — ref frame (profile)': read back 400 x 560 at (80, 80); clip on, no child spills
- frame 'CMP-184 · MarketProfileTpoPane — ref frame (blocks)': read back 400 x 560 at (560, 80); clip on, no child spills
- frame 'CMP-184 · MarketProfileTpoPane — ref frame (ib)': read back 400 x 560 at (1040, 80); clip on, no child spills
- frame 'CMP-184 · MarketProfileTpoPane — ref frame (greyscale)': read back 400 x 560 at (1520, 80); clip on, no child spills
- frame 'SCR-038∕tpo-letters-dark': read back 1280 x 800 at (80, 720); clip on, no child spills
- frame 'SCR-038∕tpo-blocks-dark': read back 1280 x 800 at (1440, 720); clip on, no child spills
- frame 'SCR-038∕tpo-ib-single-prints-dark': read back 1280 x 800 at (80, 1600); clip on, no child spills
- local tokens: create the sets of local-tokens.json ('E19-D03 local · dark', '· light', '· hc', each active only in its theme) before the first section call; color.tpo.letter and color.tpo.initialbalance bind them
- export docs/design/E19/img/E19-D03-07-cmp-184-tpo.png; record the board id and the PNG size

## Readings (0)

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 438 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (30)

- "CMP-184 · MarketProfileTpoPane — ref frame (profile)" (hand-off L82)
- "Session" (spec L263)
- "TPO" (spec L23)
- W-11: "Final" (spec L392)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- W-8: "IB {low} – {high}" (spec L389) filled from the world
- "POC" (spec L5)
- "VAH" (spec L120)
- "VAL" (spec L120)
- "CMP-184 · MarketProfileTpoPane — ref frame (blocks)" (hand-off L83)
- W-7: "TPO as blocks — letters on hover, focus and in the table" (spec L388)
- "CMP-184 · MarketProfileTpoPane — ref frame (ib)" (hand-off L84)
- "CMP-184 · MarketProfileTpoPane — ref frame (greyscale)" (hand-off L85)
- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "Period" (spec L261)
- "Input" (spec L9)
- "VA%" (D02 L135)
- "Row" (spec L253)
- "VWAP" (spec L61)
- D02 W-29: "Histogram" (D02 L378)
- D02 W-29: "Table" (D02 L378)
- "Presets" (D02 L113)
- "Settings" (D02 L100)
- "HVN" (spec L124)
- "LVN" (spec L124)
- "Single prints" (spec L200)
- W-2: "{k} hidden" (spec L383) filled from the world
- W-6: "Show tested" (spec L387)
- "BTCUSDT" (spec L62)

## Copy gaps (2)

- "forced colours (§2.4): letters, blocks, the IB bar and W-8 CanvasText; the IB band drops out": a summary of §2.4 (board label)
- "30m": the bound chart's interval word (kit world: 30-minute bars), filling D02 W-2's {interval}

## Fallbacks (3)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the chart beside the panel is a plain SCR-030 price pane (candles, grid, price axis) for alignment only
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen or a measurement, never product UI

## Sources (4)

- spec E19-D03.md md5 928db4e4 and hand-off md5 fb2077ba (§0 L80; RULED comment 6580374205)
- D02 E19-D02.md md5 1299df3b at bed73afaa (read via git show bed73afaa; re-pinned when PR #5487 merges)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.tpo.*, PROPOSED, §2.1)

## Tokens (34)

- type.ui.label
- color.text.primary
- type.ui.caption
- color.text.secondary
- size.icon.sm
- space.inset.sm
- space.inset.xs
- radius.control
- color.action.secondary.default
- color.border.default
- border.hairline
- space.stack.xs
- color.surface.raised
- type.num.xs
- color.tpo.letter
- color.tpo.initialbalance
- color.profile.poc
- color.profile.valuearea
- color.surface.canvas
- color.surface.app
- type.num.sm
- color.surface.sunken
- color.surface.selected
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- color.border.strong
- radius.card
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
- space.inset.lg
