# E26-D02 / 05 pre-play-and-paused

File `E26-D02 boards`, page `E26-D02 SCR-097 Replay page`; export `docs/design/E26/img/E26-D02-05-pre-play-and-paused-dark.png`; sheet `05-pre-play-and-paused.json` (validated); theme dark.

Composite B5 of ten (§16 L688: 02 (with revived, not found and a Viewer's configuring), 03 and 06). Grid (24000, 0); 4560 x 2438 px; "page E26-D02 SCR-097 Replay page · board 05 (B5) · r1".

## Frames

- `02 SCR-097∕configuring · dark` (§16 frame 02, L733, 1920 x 1080)
- `03 SCR-097∕buffering · dark` (§16 frame 03, L734, 1920 x 1080)
- `06 SCR-097∕paused-stepped · dark` (§16 frame 06, L737, 1920 x 1080)

## Validator and size

- `05-pre-play-and-paused.json: 0 errors, 33 warnings, 71 sections, 168869 bytes` (exit 0)
- 71 sections, 168869 bytes

## Live checks (7)

- root 'E26-D02 / 05 pre-play-and-paused' at (24000, 0): read back the name exactly after the first section call; size 4560 x 2438
- after touchTexts + relayout: the annotation column (estimated 820 px) ends inside the root (h 2438); raise the root's h to max(annotation end, footer end) + 80 if not
- frame '02 SCR-097∕configuring · dark': read back 1920 x 1080 at (80, 80); clip on, no child spills
- frame '03 SCR-097∕buffering · dark': read back 1920 x 1080 at (2080, 80); clip on, no child spills
- frame '06 SCR-097∕paused-stepped · dark': read back 1920 x 1080 at (80, 1240); clip on, no child spills
- local token: create set 'E26-D02 local · dark' with color.replay.border = palette.purple.400 (local-tokens.json) before the first section call; every frame and chip border binds it
- export docs/design/E26/img/E26-D02-05-pre-play-and-paused-dark.png; record the board id and the PNG size

## Readings (2)

- R-170 without a session (configuring): the track row draws the bare groove only (no window, so no classes, labels, thumb or coverage line); every transport control is T2 on the one replay.no_session notice, Paper fills and Allow real-time panels included (kit reading: no session holds them)
- buffering: the panels have no frame of data yet, so each chip shows the word and the date only (D-2's narrow form keeps the word and the date) and the panels are empty; the header shows the window start

## Derivations (6)

- "Preparing 13:00–15:00 UTC · reading recorded data · 12 s": the spec's example "Preparing 13:00–15:00 UTC · reading recorded data · 4 s" (L332) with this frame's values
- "Paused at 13:39:00": the spec's example "Paused at 13:38:04" (L87) with this frame's values
- "10× on Play": the spec's example "4× on Play" (L173) with this frame's values
- chart at 13:39:00.000: slots 13:06–14:06 (60 × 1 min), 33 bars from the seeded prints, price axis 63,994.2–64,039.9 at 10 steps, virtual now at x 628
- DOM at 13:39:00: best bid 64,011.9, best ask 64,012.0 (one tick over the last print), sizes seeded 509
- world: BTCUSDT 1-minute bars and prints from one walk seeded 509 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; window 13:00–15:00 UTC on 2026-09-13 (spec L25); history start 13:04:12; gap 13:52:10–13:55:40; partial after 14:41; playhead 13:38:04.210; the walk shifted so the bar holding the playhead closes at §3's illustrative last 64,011.0

## Spec gaps (0)

## Deviations (0)

## Copy keys (3)

- replay.no_session: "Start a session first." (§5.3 L236)
- rbac.permission: "Your role can't control replay." (§5.3 L235)
- replay.step_bar_time: "Step by bar needs a time interval on this panel — step by tick instead." (§5.3 L242)

## Copy gaps (5)

- "visually hidden": the hidden-string marker label (kit form, board marker)
- panel titles "Chart BTCUSDT 1m", "DOM BTCUSDT 200", "Ticket", "Tape BTCUSDT": §3 sketch L77-L82 (capitalised; the tape names its symbol)
- "last 64,011.9" · "mark —": §3 sketch L78, D-15 L58 (last derived from the seeded prints at 13:39:00)
- "Simulated Buy / Long 0.250 BTC": §3 sketch L84 (its double space as one)
- "Buy" / "Sell" (the taker side word on tape rows): E22-D02's side words, not this spec's

## Fallbacks (10)

- kit choice (§16 readings): a state's other moments drawn at full scale in 'board marker · tray' boxes inside the frame (1 px color.border.strong outline, a caption naming the moment), never as product UI
- kit choice: a visually hidden string drawn for the board as caption text in a dashed-look outline (the words a screen reader hears; not on screen in the product)
- kit choice: the terminal's TopBar and StatusBar drawn as neutral placeholders (E10's, not this spec's); only the CMP-074 band position, the header strip, the dock and the transport are this spec's (§3)
- kit choice: icon/replay (E11-D02 CR-7) is not in the local icon set; its 16 px slot is drawn with the local 'refresh' glyph, named 'icon∕replay (stand-in)'
- kit choice: the transport's |<<, <, > and >>| glyphs (CMP-002, icon-only) are drawn as their own characters in type.num.base inside the 24 × 24 button; the icons are E26-D05's
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: CMP-001's loading spinner (no spinner icon in the local set) drawn as a 12 px ellipse outline in color.text.on-action, border.thick, centred at the label's width; static
- kit choice: the 45° hatch at a 6 px pitch drawn as 2 × 2 px color.neutral.default steps (three per stroke on the 6 px track); the chart's gap band draws the same steps in 12 px strips at its top and foot between its dashed edges (the full-height texture is E11-D05's rotated-line recipe, applied live)
- kit choice: dashed lines (virtual now, the hatch edges) drawn as 4 px dashes with 4 px gaps
- opacity.scrim is a Tier-1 primitive (validator WARN); §11 names it for the scrim and the dimmed future

## Sources (3)

- spec E26-D02.md md5 8acbcacc and hand-off md5 32dd0521 (§16 L688; §3-§13; RULED comment 6555545802)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.replay.border, PROPOSED, RULED BQ-10)

## Tokens (57)

- type.ui.body
- color.text.primary
- color.status.info.strong
- size.icon
- space.inset.sm
- color.status.info.subtle
- radius.control
- color.surface.raised
- type.ui.label
- color.text.secondary
- space.stack.sm
- space.inset.md
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.card
- type.ui.body-strong
- color.text.on-action
- color.action.primary.default
- space.button.paddingX
- type.num.base
- space.inset.xs
- color.action.secondary.default
- type.ui.caption
- color.text.tertiary
- space.stack.xs
- color.surface.sunken
- color.surface.hover
- color.env.demo
- border.thick
- color.border.subtle
- space.inset.lg
- color.surface.app
- type.ui.heading-sm
- space.4
- color.border.default
- size.icon.sm
- type.num.sm
- type.num.xs
- radius.pill
- space.inset.xl
- type.num.md
- color.surface.selected
- color.neutral.default
- color.replay.border
- radius.badge
- color.focus.ring
- border.focus
- color.surface.overlay
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.up
- color.candle.down
- opacity.scrim
- color.sell.default
- color.buy.default
