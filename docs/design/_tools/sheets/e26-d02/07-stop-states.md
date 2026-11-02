# E26-D02 / 07 stop-states

File `E26-D02 boards`, page `E26-D02 SCR-097 Replay page`; export `docs/design/E26/img/E26-D02-07-stop-states-dark.png`; sheet `07-stop-states.json` (validated); theme dark.

Composite B7 of ten (§16 L690: 08, 11, 12 and 13 (AC 2; the three terminal T2 keys replay.end_of_range, replay.ended, replay.error)). Grid (6000, 3200); 4560 x 2438 px; "page E26-D02 SCR-097 Replay page · board 07 (B7) · r1".

## Frames

- `08 SCR-097∕gap-encountered · dark` (§16 frame 08, L739, 1920 x 1080)
- `11 SCR-097∕end-of-range · dark` (§16 frame 11, L742, 1920 x 1080)
- `12 SCR-097∕session-expired · dark` (§16 frame 12, L743, 1920 x 1080)
- `13 SCR-097∕error · dark` (§16 frame 13, L744, 1920 x 1080)

## Validator and size

- `07-stop-states.json: 0 errors, 56 warnings, 212 sections, 402707 bytes` (exit 0)
- 212 sections, 402707 bytes

## Live checks (8)

- root 'E26-D02 / 07 stop-states' at (6000, 3200): read back the name exactly after the first section call; size 4560 x 2438
- after touchTexts + relayout: the annotation column (estimated 1021 px) ends inside the root (h 2438); raise the root's h to max(annotation end, footer end) + 80 if not
- frame '08 SCR-097∕gap-encountered · dark': read back 1920 x 1080 at (80, 80); clip on, no child spills
- frame '11 SCR-097∕end-of-range · dark': read back 1920 x 1080 at (2080, 80); clip on, no child spills
- frame '12 SCR-097∕session-expired · dark': read back 1920 x 1080 at (80, 1240); clip on, no child spills
- frame '13 SCR-097∕error · dark': read back 1920 x 1080 at (2080, 1240); clip on, no child spills
- local token: create set 'E26-D02 local · dark' with color.replay.border = palette.purple.400 (local-tokens.json) before the first section call; every frame and chip border binds it
- export docs/design/E26/img/E26-D02-07-stop-states-dark.png; record the board id and the PNG size

## Readings (4)

- the book-alone callout is D-13's 'Order book not recorded 13:52:10–13:55:40 UTC — …' with the same cause words as the no-data callout (the ellipsis stands for E11-D04's cause)
- frame 08 draws Skip gap and Stop here; Always skip gaps in this session and the notice's Stop at gaps wait for CC-2 and are not drawn (RULED BQ-8)
- end of range: the callout carries Restart from 13:00, Extend window and Results; Leave replay is the controls row's own (one Leave replay on screen)
- error: the mapped cause drawn is storage read failed (§7.1), the server's token never shown (D-23)

## Derivations (9)

- "Paused at 13:52:10": the spec's example "Paused at 13:38:04" (L87) with this frame's values
- chart at 13:52:10.000: slots 13:19–14:19 (60 × 1 min), 34 bars from the seeded prints, price axis 63,976.0–64,040.6 at 10 steps, virtual now at x 631
- DOM at 13:52:10: best bid 63,985.2, best ask 63,985.3 (one tick over the last print), sizes seeded 509
- chart at 15:00:00.000: slots 14:27–15:27 (60 × 1 min), 33 bars from the seeded prints, price axis 63,996.6–64,090.8 at 20 steps, virtual now at x 628
- DOM at 15:00:00: best bid 64,071.4, best ask 64,071.5 (one tick over the last print), sizes seeded 509
- chart at 13:52:04.000: slots 13:19–14:19 (60 × 1 min), 34 bars from the seeded prints, price axis 63,976.0–64,040.6 at 10 steps, virtual now at x 629
- DOM at 13:52:04: best bid 63,986.0, best ask 63,986.1 (one tick over the last print), sizes seeded 509
- chart at 13:52:04.120: slots 13:19–14:19 (60 × 1 min), 34 bars from the seeded prints, price axis 63,976.0–64,040.6 at 10 steps, virtual now at x 629
- world: BTCUSDT 1-minute bars and prints from one walk seeded 509 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; window 13:00–15:00 UTC on 2026-09-13 (spec L25); history start 13:04:12; gap 13:52:10–13:55:40; partial after 14:41; playhead 13:38:04.210; the walk shifted so the bar holding the playhead closes at §3's illustrative last 64,011.0

## Spec gaps (0)

## Deviations (0)

## Copy keys (3)

- replay.end_of_range: "End of range — restart or extend the window." (§5.3 L239)
- replay.ended: "This session has ended." (§5.3 L238)
- replay.error: "Retry the seek first." (§5.3 L240)

## Copy gaps (7)

- "last 63,985.2" · "mark —": §3 sketch L78, D-15 L58 (last derived from the seeded prints at 13:52:10)
- panel titles "Chart BTCUSDT 1m", "DOM BTCUSDT 200", "Ticket", "Tape BTCUSDT": §3 sketch L77-L82 (capitalised; the tape names its symbol)
- "Simulated Buy / Long 0.250 BTC": §3 sketch L84 (its double space as one)
- "Buy" / "Sell" (the taker side word on tape rows): E22-D02's side words, not this spec's
- "last 64,071.4" · "mark —": §3 sketch L78, D-15 L58 (last derived from the seeded prints at 15:00:00)
- "visually hidden": the hidden-string marker label (kit form, board marker)
- "last 63,986.0" · "mark —": §3 sketch L78, D-15 L58 (last derived from the seeded prints at 13:52:04)

## Fallbacks (9)

- kit choice (§16 readings): a state's other moments drawn at full scale in 'board marker · tray' boxes inside the frame (1 px color.border.strong outline, a caption naming the moment), never as product UI
- kit choice: the terminal's TopBar and StatusBar drawn as neutral placeholders (E10's, not this spec's); only the CMP-074 band position, the header strip, the dock and the transport are this spec's (§3)
- kit choice: icon/replay (E11-D02 CR-7) is not in the local icon set; its 16 px slot is drawn with the local 'refresh' glyph, named 'icon∕replay (stand-in)'
- kit choice: the transport's |<<, <, > and >>| glyphs (CMP-002, icon-only) are drawn as their own characters in type.num.base inside the 24 × 24 button; the icons are E26-D05's
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the 45° hatch at a 6 px pitch drawn as 2 × 2 px color.neutral.default steps (three per stroke on the 6 px track); the chart's gap band draws the same steps in 12 px strips at its top and foot between its dashed edges (the full-height texture is E11-D05's rotated-line recipe, applied live)
- kit choice: dashed lines (virtual now, the hatch edges) drawn as 4 px dashes with 4 px gaps
- opacity.scrim is a Tier-1 primitive (validator WARN); §11 names it for the scrim and the dimmed future
- kit choice: a visually hidden string drawn for the board as caption text in a dashed-look outline (the words a screen reader hears; not on screen in the product)

## Sources (3)

- spec E26-D02.md md5 e52ed805 and hand-off md5 32dd0521 (§16 L690; §3-§13; RULED comment 6555545802)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.replay.border, PROPOSED, RULED BQ-10)

## Tokens (61)

- type.ui.body-strong
- color.text.primary
- color.action.secondary.default
- space.button.paddingX
- radius.control
- type.ui.body
- color.status.warning.strong
- size.icon
- space.inset.sm
- color.status.warning.subtle
- type.ui.label
- color.text.secondary
- space.stack.sm
- space.inset.md
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.card
- color.status.info.strong
- color.status.info.subtle
- color.surface.hover
- color.env.demo
- border.thick
- space.inset.xs
- color.border.subtle
- space.inset.lg
- color.surface.app
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
- size.icon.sm
- color.surface.sunken
- type.num.xs
- color.text.tertiary
- radius.pill
- color.neutral.default
- type.ui.caption
- space.inset.xl
- space.stack.xs
- color.replay.border
- radius.badge
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.up
- color.candle.down
- opacity.scrim
- color.sell.default
- color.buy.default
- color.focus.ring
- border.focus
- color.surface.overlay
- color.status.danger.strong
- color.status.danger.subtle
