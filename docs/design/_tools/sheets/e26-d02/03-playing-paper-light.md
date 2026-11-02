# E26-D02 / 03 playing-paper-light

File `E26-D02 boards`, page `E26-D02 SCR-097 Replay page`; export `docs/design/E26/img/E26-D02-03-playing-paper-light.png`; sheet `03-playing-paper-light.json` (validated); theme light.

Composite B3 of ten (§16 L686: 04, light twin of B2: the REPLAY frame and the DEMO badge are the light-critical pairs (§12.2)). Grid (12000, 0); 2560 x 1278 px; "page E26-D02 SCR-097 Replay page · board 03 (B3) · r1".

## Frames

- `04 SCR-097∕playing-paper · light` (§16 frame 04, L735, 1920 x 1080)

## Validator and size

- `03-playing-paper-light.json: 0 errors, 11 warnings, 48 sections, 94020 bytes` (exit 0)
- 48 sections, 94020 bytes

## Live checks (6)

- root 'E26-D02 / 03 playing-paper-light' at (12000, 0): read back the name exactly after the first section call; size 2560 x 1278
- after touchTexts + relayout: the annotation column (estimated 563 px) ends inside the root (h 1278); raise the root's h to max(annotation end, footer end) + 80 if not
- frame '04 SCR-097∕playing-paper · light': read back 1920 x 1080 at (80, 80); clip on, no child spills
- theme: activate the light token set (and 'E26-D02 local · light') before exporting board 03; read back one bound fill (color.surface.raised) as the light value
- local token: create set 'E26-D02 local · light' with color.replay.border = palette.purple.600 (local-tokens.json) before the first section call; every frame and chip border binds it
- export docs/design/E26/img/E26-D02-03-playing-paper-light.png; record the board id and the PNG size

## Readings (0)

## Derivations (3)

- chart at 13:38:04.210: slots 13:05–14:05 (60 × 1 min), 34 bars from the seeded prints, price axis 63,994.2–64,039.9 at 10 steps, virtual now at x 629
- DOM at 13:38:04: best bid 64,011.0, best ask 64,011.1 (one tick over the last print), sizes seeded 509
- world: BTCUSDT 1-minute bars and prints from one walk seeded 509 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; window 13:00–15:00 UTC on 2026-09-13 (spec L25); history start 13:04:12; gap 13:52:10–13:55:40; partial after 14:41; playhead 13:38:04.210; the walk shifted so the bar holding the playhead closes at §3's illustrative last 64,011.0

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (5)

- "exit glyph, for comparison (D-6)": board 17's comparison (spec L49, §16); a board marker
- "last 64,011.0" · "mark —": §3 sketch L78, D-15 L58 (last derived from the seeded prints at 13:38:04)
- panel titles "Chart BTCUSDT 1m", "DOM BTCUSDT 200", "Ticket", "Tape BTCUSDT": §3 sketch L77-L82 (capitalised; the tape names its symbol)
- "Simulated Buy / Long 0.250 BTC": §3 sketch L84 (its double space as one)
- "Buy" / "Sell" (the taker side word on tape rows): E22-D02's side words, not this spec's

## Fallbacks (8)

- kit choice: the terminal's TopBar and StatusBar drawn as neutral placeholders (E10's, not this spec's); only the CMP-074 band position, the header strip, the dock and the transport are this spec's (§3)
- kit choice: icon/replay (E11-D02 CR-7) is not in the local icon set; its 16 px slot is drawn with the local 'refresh' glyph, named 'icon∕replay (stand-in)'
- kit choice: the transport's |<<, <, > and >>| glyphs (CMP-002, icon-only) are drawn as their own characters in type.num.base inside the 24 × 24 button; the icons are E26-D05's
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: board 17's exit glyph for comparison beside >>| drawn as a 12 × 14 door outline with the local chevron-right (no exit icon in the local set), in a board marker box
- kit choice: the 45° hatch at a 6 px pitch drawn as 2 × 2 px color.neutral.default steps (three per stroke on the 6 px track); the chart's gap band draws the same steps in 12 px strips at its top and foot between its dashed edges (the full-height texture is E11-D05's rotated-line recipe, applied live)
- kit choice: dashed lines (virtual now, the hatch edges) drawn as 4 px dashes with 4 px gaps
- opacity.scrim is a Tier-1 primitive (validator WARN); §11 names it for the scrim and the dimmed future

## Sources (3)

- spec E26-D02.md md5 8acbcacc and hand-off md5 32dd0521 (§16 L686; §3-§13; RULED comment 6555545802)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.replay.border, PROPOSED, RULED BQ-10)

## Tokens (51)

- radius.control
- color.surface.hover
- color.env.demo
- border.thick
- type.ui.label
- color.text.primary
- space.inset.xs
- space.inset.sm
- space.inset.md
- color.border.subtle
- space.inset.lg
- color.surface.app
- size.icon
- type.ui.heading-sm
- type.ui.body-strong
- type.num.md
- type.num.base
- color.action.secondary.default
- space.button.paddingX
- space.4
- color.border.default
- color.surface.raised
- color.text.on-action
- color.action.primary.default
- color.border.strong
- border.hairline
- color.surface.selected
- type.ui.body
- type.num.sm
- size.icon.sm
- color.text.secondary
- color.surface.sunken
- type.ui.caption
- type.num.xs
- color.text.tertiary
- radius.pill
- color.neutral.default
- space.inset.xl
- space.stack.xs
- color.replay.border
- radius.badge
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- opacity.scrim
- color.surface.canvas
- color.sell.default
- color.buy.default
- space.stack.sm
