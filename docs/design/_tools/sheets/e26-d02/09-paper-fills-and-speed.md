# E26-D02 / 09 paper-fills-and-speed

File `E26-D02 boards`, page `E26-D02 SCR-097 Replay page`; export `docs/design/E26/img/E26-D02-09-paper-fills-and-speed-dark.png`; sheet `09-paper-fills-and-speed.json` (validated); theme dark.

Composite B9 of ten (§16 L692: 10 and 09 (the Security note)). Grid (18000, 3200); 4560 x 1398 px; "page E26-D02 SCR-097 Replay page · board 09 (B9) · r1".

## Frames

- `10 SCR-097∕paper-fill-active · dark` (§16 frame 10, L741, 1920 x 1200)
- `09 SCR-097∕speed-limited · dark` (§16 frame 09, L740, 1920 x 1080)

## Validator and size

- `09-paper-fills-and-speed.json: 0 errors, 27 warnings, 89 sections, 191603 bytes` (exit 0)
- 89 sections, 191603 bytes

## Live checks (6)

- root 'E26-D02 / 09 paper-fills-and-speed' at (18000, 3200): read back the name exactly after the first section call; size 4560 x 1398
- after touchTexts + relayout: the annotation column (estimated 676 px) ends inside the root (h 1398); raise the root's h to max(annotation end, footer end) + 80 if not
- frame '10 SCR-097∕paper-fill-active · dark': read back 1920 x 1200 at (80, 80); clip on, no child spills
- frame '09 SCR-097∕speed-limited · dark': read back 1920 x 1080 at (2080, 80); clip on, no child spills
- local token: create set 'E26-D02 local · dark' with color.replay.border = palette.purple.400 (local-tokens.json) before the first section call; every frame and chip border binds it
- export docs/design/E26/img/E26-D02-09-paper-fills-and-speed-dark.png; record the board id and the PNG size

## Readings (2)

- frame 10's Paper fills switch reads 'Paper fills · Paper 1' (§16 readings): on, and T2 2a on replay.paper_working while this page's simulated order and position exist
- frame 09's Paper fills switch reads 'Paper fills · off above 25×' (§5.2, D-9; §16 readings), off and T2 2a with its reason beside it

## Derivations (5)

- the simulated position: Buy / Long 0.250 filled at the first print from 13:31:00 (13:31:01, 64,001.2); the working order: Buy 0.100 limit at last − 5.0 = 64,006.0
- chart at 13:38:04.210: slots 13:05–14:05 (60 × 1 min), 34 bars from the seeded prints, price axis 63,994.2–64,039.9 at 10 steps, virtual now at x 629
- DOM at 13:38:04: best bid 64,011.0, best ask 64,011.1 (one tick over the last print), sizes seeded 509
- "Playing at 100×": the spec's example "Playing at 4×" (L334) with this frame's values
- world: BTCUSDT 1-minute bars and prints from one walk seeded 509 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; window 13:00–15:00 UTC on 2026-09-13 (spec L25); history start 13:04:12; gap 13:52:10–13:55:40; partial after 14:41; playhead 13:38:04.210; the walk shifted so the bar holding the playhead closes at §3's illustrative last 64,011.0

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- replay.paper_working: "Cancel or close simulated orders and positions first." (§5.3 L243)
- replay.paper_above_25x: "Paper fills are off above 25× — at this speed an order placed by hand lands too far from the moment you meant." (§5.3 L244)

## Copy gaps (6)

- the private panels' column labels (Symbol, Side, Size, Entry, Price, Time) and their titles (Positions, Orders, Fills): the E38 panels' words, not this spec's; SIM, Cancel and Close are its
- "last 64,011.0" · "mark —": §3 sketch L78, D-15 L58 (last derived from the seeded prints at 13:38:04)
- "Simulated Buy / Long 0.250 BTC": §3 sketch L84 (its double space as one)
- "visually hidden": the hidden-string marker label (kit form, board marker)
- panel titles "Chart BTCUSDT 1m", "DOM BTCUSDT 200", "Ticket", "Tape BTCUSDT": §3 sketch L77-L82 (capitalised; the tape names its symbol)
- "Buy" / "Sell" (the taker side word on tape rows): E22-D02's side words, not this spec's

## Fallbacks (9)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice (§16 readings): a state's other moments drawn at full scale in 'board marker · tray' boxes inside the frame (1 px color.border.strong outline, a caption naming the moment), never as product UI
- kit choice: the terminal's TopBar and StatusBar drawn as neutral placeholders (E10's, not this spec's); only the CMP-074 band position, the header strip, the dock and the transport are this spec's (§3)
- kit choice: icon/replay (E11-D02 CR-7) is not in the local icon set; its 16 px slot is drawn with the local 'refresh' glyph, named 'icon∕replay (stand-in)'
- kit choice: the transport's |<<, <, > and >>| glyphs (CMP-002, icon-only) are drawn as their own characters in type.num.base inside the 24 × 24 button; the icons are E26-D05's
- kit choice: the 45° hatch at a 6 px pitch drawn as 2 × 2 px color.neutral.default steps (three per stroke on the 6 px track); the chart's gap band draws the same steps in 12 px strips at its top and foot between its dashed edges (the full-height texture is E11-D05's rotated-line recipe, applied live)
- kit choice: dashed lines (virtual now, the hatch edges) drawn as 4 px dashes with 4 px gaps
- opacity.scrim is a Tier-1 primitive (validator WARN); §11 names it for the scrim and the dimmed future
- kit choice: a visually hidden string drawn for the board as caption text in a dashed-look outline (the words a screen reader hears; not on screen in the product)

## Sources (3)

- spec E26-D02.md md5 d4f77108 and hand-off md5 32dd0521 (§16 L692; §3-§13; RULED comment 6555545802)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.replay.border, PROPOSED, RULED BQ-10)

## Tokens (56)

- type.ui.body-strong
- color.text.primary
- color.action.secondary.default
- space.button.paddingX
- radius.control
- type.ui.caption
- space.inset.sm
- color.border.strong
- border.hairline
- radius.badge
- color.text.secondary
- size.icon.sm
- type.ui.label
- space.stack.sm
- space.inset.md
- color.surface.canvas
- radius.card
- type.ui.body
- color.surface.hover
- color.env.demo
- border.thick
- space.inset.xs
- color.border.subtle
- space.inset.lg
- color.surface.app
- size.icon
- type.ui.heading-sm
- type.num.md
- type.num.base
- space.4
- color.border.default
- color.surface.raised
- color.text.on-action
- color.action.primary.default
- color.surface.selected
- type.num.sm
- color.text.tertiary
- color.surface.sunken
- type.num.xs
- radius.pill
- color.neutral.default
- space.inset.xl
- space.stack.xs
- color.replay.border
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- opacity.scrim
- color.sell.default
- color.buy.default
- color.status.warning.strong
- color.status.warning.subtle
- color.status.info.strong
- color.status.info.subtle
