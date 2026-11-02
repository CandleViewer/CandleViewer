# E26-D02 / 06 scrubber-and-seeking

File `E26-D02 boards`, page `E26-D02 SCR-097 Replay page`; export `docs/design/E26/img/E26-D02-06-scrubber-and-seeking-dark.png`; sheet `06-scrubber-and-seeking.json` (validated); theme dark.

Composite B6 of ten (§16 L689: 16 and 07 (AC 3, AC 4); the bookmark markers and menu in a side inset stamped "needs CC-15 — not rendered until it lands"). Grid (0, 3200); 4240 x 1398 px; "page E26-D02 SCR-097 Replay page · board 06 (B6) · r1".

## Frames

- `16 CMP-170∕coverage-scrubber-in-context · dark` (§16 frame 16, L747, 1600 x 900)
- `07 SCR-097∕seeking · dark` (§16 frame 07, L738, 1920 x 1200)

## Validator and size

- `06-scrubber-and-seeking.json: 0 errors, 24 warnings, 68 sections, 162836 bytes` (exit 0)
- 68 sections, 162836 bytes

## Live checks (6)

- root 'E26-D02 / 06 scrubber-and-seeking' at (0, 3200): read back the name exactly after the first section call; size 4240 x 1398
- after touchTexts + relayout: the annotation column (estimated 663 px) ends inside the root (h 1398); raise the root's h to max(annotation end, footer end) + 80 if not
- frame '16 CMP-170∕coverage-scrubber-in-context · dark': read back 1600 x 900 at (80, 80); clip on, no child spills
- frame '07 SCR-097∕seeking · dark': read back 1920 x 1200 at (1760, 80); clip on, no child spills
- local token: create set 'E26-D02 local · dark' with color.replay.border = palette.purple.400 (local-tokens.json) before the first section call; every frame and chip border binds it
- export docs/design/E26/img/E26-D02-06-scrubber-and-seeking-dark.png; record the board id and the PNG size

## Readings (2)

- frame 16 draws CMP-170 in context as the 1600 px transport (playing, the thumb focused) over its specimens; the bookmark markers and menu only in the side inset stamped 'needs CC-15 — not rendered until it lands' (RULED BQ-9), never on a playing frame
- seeking: the thumb stands at the released target while the panels keep their last frame and their chips keep 13:38:04 (D-3); `Pause` reads `Cancel seek` (§6.3 rung 0.1–1 s)

## Derivations (7)

- "13:53:00 · no data": the spec's example "13:52:30 · no data" (L291) with this frame's values
- thumb specimens: rest, hover and focus at 13:20:00, drag over the gap at 13:53:00 (inside 13:52:10–13:55:40, so 'no data')
- bookmark 2 at 14:20:00: a kit-chosen second time (the sketch numbers ▲1 and ▲2, §3)
- "2 · 14:20:00 · label": the spec's example "1 · 13:41:07 · label" (L299) with this frame's values
- chart at 13:38:04.210: slots 13:05–14:05 (60 × 1 min), 34 bars from the seeded prints, price axis 63,994.2–64,039.9 at 10 steps, virtual now at x 629
- DOM at 13:38:04: best bid 64,011.0, best ask 64,011.1 (one tick over the last print), sizes seeded 509
- world: BTCUSDT 1-minute bars and prints from one walk seeded 509 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; window 13:00–15:00 UTC on 2026-09-13 (spec L25); history start 13:04:12; gap 13:52:10–13:55:40; partial after 14:41; playhead 13:38:04.210; the walk shifted so the bar holding the playhead closes at §3's illustrative last 64,011.0

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (5)

- "visually hidden": the hidden-string marker label (kit form, board marker)
- "last 64,011.0" · "mark —": §3 sketch L78, D-15 L58 (last derived from the seeded prints at 13:38:04)
- panel titles "Chart BTCUSDT 1m", "DOM BTCUSDT 200", "Ticket", "Tape BTCUSDT": §3 sketch L77-L82 (capitalised; the tape names its symbol)
- "Simulated Buy / Long 0.250 BTC": §3 sketch L84 (its double space as one)
- "Buy" / "Sell" (the taker side word on tape rows): E22-D02's side words, not this spec's

## Fallbacks (9)

- kit choice: the transport's |<<, <, > and >>| glyphs (CMP-002, icon-only) are drawn as their own characters in type.num.base inside the 24 × 24 button; the icons are E26-D05's
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the 45° hatch at a 6 px pitch drawn as 2 × 2 px color.neutral.default steps (three per stroke on the 6 px track); the chart's gap band draws the same steps in 12 px strips at its top and foot between its dashed edges (the full-height texture is E11-D05's rotated-line recipe, applied live)
- kit choice: dashed lines (virtual now, the hatch edges) drawn as 4 px dashes with 4 px gaps
- kit choice: a visually hidden string drawn for the board as caption text in a dashed-look outline (the words a screen reader hears; not on screen in the product)
- kit choice (§16 readings): a state's other moments drawn at full scale in 'board marker · tray' boxes inside the frame (1 px color.border.strong outline, a caption naming the moment), never as product UI
- kit choice: the terminal's TopBar and StatusBar drawn as neutral placeholders (E10's, not this spec's); only the CMP-074 band position, the header strip, the dock and the transport are this spec's (§3)
- kit choice: icon/replay (E11-D02 CR-7) is not in the local icon set; its 16 px slot is drawn with the local 'refresh' glyph, named 'icon∕replay (stand-in)'
- opacity.scrim is a Tier-1 primitive (validator WARN); §11 names it for the scrim and the dimmed future

## Sources (3)

- spec E26-D02.md md5 d4f77108 and hand-off md5 32dd0521 (§16 L689; §3-§13; RULED comment 6555545802)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.replay.border, PROPOSED, RULED BQ-10)

## Tokens (57)

- type.num.base
- color.text.primary
- color.action.secondary.default
- radius.control
- type.ui.body-strong
- color.text.on-action
- color.action.primary.default
- type.ui.label
- space.inset.sm
- color.border.strong
- border.hairline
- color.surface.selected
- space.inset.xs
- type.ui.body
- type.num.sm
- size.icon.sm
- color.text.secondary
- color.surface.sunken
- color.border.default
- space.button.paddingX
- space.inset.lg
- type.num.xs
- color.text.tertiary
- radius.pill
- color.neutral.default
- type.ui.caption
- color.surface.raised
- color.focus.ring
- border.focus
- space.inset.md
- space.inset.xl
- space.stack.xs
- color.surface.overlay
- space.stack.sm
- color.surface.canvas
- radius.card
- space.stack.md
- space.stack.lg
- color.surface.app
- color.surface.hover
- color.env.demo
- border.thick
- color.border.subtle
- size.icon
- type.ui.heading-sm
- type.num.md
- space.4
- color.replay.border
- radius.badge
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- opacity.scrim
- color.sell.default
- color.buy.default
