# E26-D02 / 10 panels-and-conditions

File `E26-D02 boards`, page `E26-D02 SCR-097 Replay page`; export `docs/design/E26/img/E26-D02-10-panels-and-conditions-dark.png`; sheet `10-panels-and-conditions.json` (validated); theme dark.

Composite B10 of ten (§16 L693: 15 with insets 14, 22 and 23). Grid (24000, 3200); 4560 x 2558 px; "page E26-D02 SCR-097 Replay page · board 10 (B10) · r1".

## Frames

- `15 SCR-097∕panels-under-replay · dark` (§16 frame 15, L746, 1920 x 1200)
- `14 SCR-097∕disconnected · dark` (§16 frame 14, L745, 1920 x 1080)
- `22 SCR-097∕viewing-as-read-only · dark` (§16 frame 22, L753, 1920 x 1080)
- `23 SCR-097∕on-hold-degraded · dark` (§16 frame 23, L754, 1920 x 1080)

## Validator and size

- `10-panels-and-conditions.json: 0 errors, 62 warnings, 206 sections, 399720 bytes` (exit 0)
- 206 sections, 399720 bytes

## Live checks (8)

- root 'E26-D02 / 10 panels-and-conditions' at (24000, 3200): read back the name exactly after the first section call; size 4560 x 2558
- after touchTexts + relayout: the annotation column (estimated 974 px) ends inside the root (h 2558); raise the root's h to max(annotation end, footer end) + 80 if not
- frame '15 SCR-097∕panels-under-replay · dark': read back 1920 x 1200 at (80, 80); clip on, no child spills
- frame '14 SCR-097∕disconnected · dark': read back 1920 x 1080 at (2080, 80); clip on, no child spills
- frame '22 SCR-097∕viewing-as-read-only · dark': read back 1920 x 1080 at (80, 1360); clip on, no child spills
- frame '23 SCR-097∕on-hold-degraded · dark': read back 1920 x 1080 at (2080, 1360); clip on, no child spills
- local token: create set 'E26-D02 local · dark' with color.replay.border = palette.purple.400 (local-tokens.json) before the first section call; every frame and chip border binds it
- export docs/design/E26/img/E26-D02-10-panels-and-conditions-dark.png; record the board id and the PNG size

## Readings (3)

- the REAL-TIME panel is a second-symbol chart (ETHUSDT, kit choice) with no frame or chip, the REAL-TIME word, its feed chip and chart trading T2 on replay.realtime_panel; it presumes Allow real-time panels on (D-14), so this frame's options row shows it checked (frame 01 has it off)
- disconnected: the client paused over REST at once (D-24), so the transport reads paused at the last rendered frame; SCR-152's Retry now sits on the chart's strip only
- viewing as: the session plays as it is; Pause (Play's slot) is a write, so it is T2 2a on the notice; the step unit, Paper fills and Allow real-time panels send nothing and pass the view-as leg (§5.3)

## Derivations (8)

- chart at 13:38:04.210: slots 13:05–14:05 (60 × 1 min), 34 bars from the seeded prints, price axis 63,994.2–64,039.9 at 10 steps, virtual now at x 412
- DOM at 13:38:04: best bid 64,011.0, best ask 64,011.1 (one tick over the last print), sizes seeded 509
- "Paused at 13:52:04": the spec's example "Paused at 13:38:04" (L87) with this frame's values
- chart at 13:52:04.000: slots 13:19–14:19 (60 × 1 min), 34 bars from the seeded prints, price axis 63,976.0–64,040.6 at 10 steps, virtual now at x 629
- DOM at 13:52:04: best bid 63,986.0, best ask 63,986.1 (one tick over the last print), sizes seeded 509
- "Read-only while viewing as Manager 1.": the spec's example "Read-only while viewing as {user}." (L234) with this frame's values
- chart at 13:38:04.210: slots 13:05–14:05 (60 × 1 min), 34 bars from the seeded prints, price axis 63,994.2–64,039.9 at 10 steps, virtual now at x 629
- world: BTCUSDT 1-minute bars and prints from one walk seeded 509 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; window 13:00–15:00 UTC on 2026-09-13 (spec L25); history start 13:04:12; gap 13:52:10–13:55:40; partial after 14:41; playhead 13:38:04.210; the walk shifted so the bar holding the playhead closes at §3's illustrative last 64,011.0

## Spec gaps (0)

## Deviations (0)

## Copy keys (4)

- replay.not_replayed: "Not replayed yet — CandleViewer records this data but replay does not play it back yet." (§5.3 L249)
- replay.realtime_panel: "Trading is off on a real-time panel." (§5.3 L247)
- rbac.view_as: "Read-only while viewing as {user}." (§5.3 L234)
- replay.degraded: "On hold until an operator checks this session." (§5.3 L237)

## Copy gaps (8)

- "ETHUSDT": the REAL-TIME panel's second symbol (kit choice; D-14 "a second-symbol chart", OQ-3), a second seeded walk at its fixture tick
- panel titles "CVD BTCUSDT", "Profile BTCUSDT", "Open interest", "Chart ETHUSDT" and the feed chip "Live": the panels' own words (E12, E17-D01), not this spec's
- "last 64,011.0" · "mark —": §3 sketch L78, D-15 L58 (last derived from the seeded prints at 13:38:04)
- "Buy" / "Sell" (the taker side word on tape rows): E22-D02's side words, not this spec's
- "last 63,986.0" · "mark —": §3 sketch L78, D-15 L58 (last derived from the seeded prints at 13:52:04)
- panel titles "Chart BTCUSDT 1m", "DOM BTCUSDT 200", "Ticket", "Tape BTCUSDT": §3 sketch L77-L82 (capitalised; the tape names its symbol)
- "Simulated Buy / Long 0.250 BTC": §3 sketch L84 (its double space as one)
- "Manager 1": the viewed user in rbac.view_as's {user} slot (synthetic; a P2 Manager)

## Fallbacks (8)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice (§16 readings): a state's other moments drawn at full scale in 'board marker · tray' boxes inside the frame (1 px color.border.strong outline, a caption naming the moment), never as product UI
- kit choice: the terminal's TopBar and StatusBar drawn as neutral placeholders (E10's, not this spec's); only the CMP-074 band position, the header strip, the dock and the transport are this spec's (§3)
- kit choice: icon/replay (E11-D02 CR-7) is not in the local icon set; its 16 px slot is drawn with the local 'refresh' glyph, named 'icon∕replay (stand-in)'
- kit choice: the transport's |<<, <, > and >>| glyphs (CMP-002, icon-only) are drawn as their own characters in type.num.base inside the 24 × 24 button; the icons are E26-D05's
- kit choice: the 45° hatch at a 6 px pitch drawn as 2 × 2 px color.neutral.default steps (three per stroke on the 6 px track); the chart's gap band draws the same steps in 12 px strips at its top and foot between its dashed edges (the full-height texture is E11-D05's rotated-line recipe, applied live)
- kit choice: dashed lines (virtual now, the hatch edges) drawn as 4 px dashes with 4 px gaps
- opacity.scrim is a Tier-1 primitive (validator WARN); §11 names it for the scrim and the dimmed future

## Sources (3)

- spec E26-D02.md md5 d4f77108 and hand-off md5 32dd0521 (§16 L693; §3-§13; RULED comment 6555545802)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.replay.border, PROPOSED, RULED BQ-10)

## Tokens (66)

- type.ui.body
- color.text.primary
- color.text.tertiary
- size.icon.sm
- space.inset.xs
- type.ui.caption
- color.text.secondary
- space.stack.xs
- space.stack.sm
- space.inset.sm
- color.surface.overlay
- radius.control
- color.border.default
- border.hairline
- color.status.danger.strong
- size.icon
- color.status.danger.subtle
- type.ui.label
- space.inset.md
- color.surface.canvas
- color.border.strong
- radius.card
- color.surface.hover
- color.env.demo
- border.thick
- color.border.subtle
- space.inset.lg
- color.surface.app
- type.ui.heading-sm
- type.ui.body-strong
- type.num.md
- type.num.base
- color.action.secondary.default
- space.button.paddingX
- space.4
- color.surface.raised
- color.text.on-action
- color.action.primary.default
- color.surface.selected
- type.num.sm
- color.surface.sunken
- type.num.xs
- radius.pill
- color.neutral.default
- space.inset.xl
- color.data-confidence.live.indicator
- color.data-confidence.live.text
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
- color.cvd.sell
- color.cvd.buy
- color.profile.bar
- color.profile.poc
- color.status.warning.strong
- color.status.warning.subtle
- color.status.info.strong
- color.status.info.subtle
- space.stack.md
