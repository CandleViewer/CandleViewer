# E26-D02 / 01 anatomy-focus-order

File `E26-D02 boards`, page `E26-D02 SCR-097 Replay page`; export `docs/design/E26/img/E26-D02-01-anatomy-focus-order-dark.png`; sheet `01-anatomy-focus-order.json` (validated); theme dark.

Composite B1 of ten (§16 L684: 01 and 19, the keyboard board: board 19's 18 focus stops over frame 01's anatomy with §11's redlines, the Replay key group and one "key on a T2 target" inset). Grid (0, 0); 4240 x 1598 px; "page E26-D02 SCR-097 Replay page · board 01 (B1) · r1".

## Frames

- `01 SCR-097∕anatomy-redlines · dark` (§16 frame 01, L732, 1920 x 1400)
- `19 SCR-097∕focus-order-overlay · dark` (§16 frame 19, L750, 1600 x 1200)

## Validator and size

- `01-anatomy-focus-order.json: 0 errors, 12 warnings, 79 sections, 147834 bytes` (exit 0)
- 79 sections, 147834 bytes

## Live checks (7)

- frame 01: after relayout the §11 redline band (seven callouts a row, estimated 312 of 320 px) ends inside the frame; if a callout is cut, report it (SHEET-FIX: shorten that tokens cell)
- root 'E26-D02 / 01 anatomy-focus-order' at (0, 0): read back the name exactly after the first section call; size 4240 x 1598
- after touchTexts + relayout: the annotation column (estimated 733 px) ends inside the root (h 1598); raise the root's h to max(annotation end, footer end) + 80 if not
- frame '01 SCR-097∕anatomy-redlines · dark': read back 1920 x 1400 at (80, 80); clip on, no child spills
- frame '19 SCR-097∕focus-order-overlay · dark': read back 1600 x 1200 at (2080, 80); clip on, no child spills
- local token: create set 'E26-D02 local · dark' with color.replay.border = palette.purple.400 (local-tokens.json) before the first section call; every frame and chip border binds it
- export docs/design/E26/img/E26-D02-01-anatomy-focus-order-dark.png; record the board id and the PNG size

## Readings (2)

- frame 01 is §3's anatomy playing, without the REAL-TIME watchlist (§3; §16 readings); B1 overlays board 19's 18 focus stops on it (§12.1 RULED BQ-14): Sessions, the chart, DOM, ticket and tape regions and the 13 transport stops |<< to Allow real-time panels; no bookmark, gap-callout or More stop
- §11's redlines are drawn as a callout band under the 1920 × 1080 anatomy inside the 1920 × 1400 frame, each callout naming its element; the tokens cell is cut at its first sentence (the rest stays §11's)

## Derivations (3)

- chart at 13:38:04.210: slots 13:05–14:05 (60 × 1 min), 34 bars from the seeded prints, price axis 63,994.2–64,039.9 at 10 steps, virtual now at x 629
- DOM at 13:38:04: best bid 64,011.0, best ask 64,011.1 (one tick over the last print), sizes seeded 509
- world: BTCUSDT 1-minute bars and prints from one walk seeded 509 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; window 13:00–15:00 UTC on 2026-09-13 (spec L25); history start 13:04:12; gap 13:52:10–13:55:40; partial after 14:41; playhead 13:38:04.210; the walk shifted so the bar holding the playhead closes at §3's illustrative last 64,011.0

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- replay.end_of_range: "End of range — restart or extend the window." (§5.3 L239)

## Copy gaps (8)

- "exit glyph, for comparison (D-6)": board 17's comparison (spec L49, §16); a board marker
- "last 64,011.0" · "mark —": §3 sketch L78, D-15 L58 (last derived from the seeded prints at 13:38:04)
- panel titles "Chart BTCUSDT 1m", "DOM BTCUSDT 200", "Ticket", "Tape BTCUSDT": §3 sketch L77-L82 (capitalised; the tape names its symbol)
- "Simulated Buy / Long 0.250 BTC": §3 sketch L84 (its double space as one)
- "Buy" / "Sell" (the taker side word on tape rows): E22-D02's side words, not this spec's
- "visually hidden": the hidden-string marker label (kit form, board marker)
- the tray captions (board markers) restate the spec's rule for the drawn moment; no product string
- "SCR-013 · Replay group, the precedence and the focus order", the table's column labels: board headings (§10's columns)

## Fallbacks (12)

- kit choice: the terminal's TopBar and StatusBar drawn as neutral placeholders (E10's, not this spec's); only the CMP-074 band position, the header strip, the dock and the transport are this spec's (§3)
- kit choice: icon/replay (E11-D02 CR-7) is not in the local icon set; its 16 px slot is drawn with the local 'refresh' glyph, named 'icon∕replay (stand-in)'
- kit choice: the transport's |<<, <, > and >>| glyphs (CMP-002, icon-only) are drawn as their own characters in type.num.base inside the 24 × 24 button; the icons are E26-D05's
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: board 17's exit glyph for comparison beside >>| drawn as a 12 × 14 door outline with the local chevron-right (no exit icon in the local set), in a board marker box
- kit choice: the 45° hatch at a 6 px pitch drawn as 2 × 2 px color.neutral.default steps (three per stroke on the 6 px track); the chart's gap band draws the same steps in 12 px strips at its top and foot between its dashed edges (the full-height texture is E11-D05's rotated-line recipe, applied live)
- kit choice: dashed lines (virtual now, the hatch edges) drawn as 4 px dashes with 4 px gaps
- opacity.scrim is a Tier-1 primitive (validator WARN); §11 names it for the scrim and the dimmed future
- kit choice: focus-order numbers drawn as 20 px numbered markers in color.focus.ring (board markers, not product UI)
- kit choice: redline callouts drawn as caption text joined to the specimen by a 1 px color.border.strong leader (board markers, not product UI)
- kit choice: a visually hidden string drawn for the board as caption text in a dashed-look outline (the words a screen reader hears; not on screen in the product)
- kit choice (§16 readings): a state's other moments drawn at full scale in 'board marker · tray' boxes inside the frame (1 px color.border.strong outline, a caption naming the moment), never as product UI

## Sources (3)

- spec E26-D02.md md5 8acbcacc and hand-off md5 32dd0521 (§16 L684; §3-§13; RULED comment 6555545802)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.replay.border, PROPOSED, RULED BQ-10)

## Tokens (57)

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
- color.focus.ring
- space.stack.sm
- border.focus
- color.surface.overlay
- radius.card
- type.ui.heading-md
- space.stack.lg
