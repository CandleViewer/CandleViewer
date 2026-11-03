# E41-D01 / 10 keyboard-and-reflow

File `E41-D01 boards`, page `E41-D01`; export `docs/design/E41/img/E41-D01-10-keyboard-and-reflow.png`; sheet `10-keyboard-and-reflow.json` (validated); theme dark.

Board 10 of ten (memo §0 L75: keyboard, reading order, 200 % reflow, forced colours, focus return (SCR-096, export)). Grid (28000, 5200); 2608 x 2995 px; "page E41-D01 · board 10 · r1".

## Frames

- `SCR-093∕default · keyboard order` (`SCR-093/default · keyboard order`)
- `SCR-096∕default · 200 % reflow` (`SCR-096/default · 200 % reflow`)
- `SCR-093∕export · 200 % reflow` (`SCR-093/export · 200 % reflow`)
- `SCR-096∕default · forced colours` (`SCR-096/default · forced colours`)
- `SCR-093∕export · forced colours` (`SCR-093/export · forced colours`)
- `SCR-096∕default · focus return` (`SCR-096/default · focus return`)
- `SCR-093∕export · focus return` (`SCR-093/export · focus return`)

## Validator and size

- `10-keyboard-and-reflow.json: 0 errors, 1 warnings, 32 sections, 117196 bytes` (exit 0)
- 32 sections, 652 shapes, 117196 bytes

## Live checks (10)

- root 'E41-D01 / 10 keyboard-and-reflow' at (28000, 5200): read back the name exactly after the first section call; size 2608 x 2995
- after touchTexts + relayout: the annotation column (estimated 1224 px with 15 % slack) ends inside the root (h 2995); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-093∕default · keyboard order': read back 1200 x 808 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-096∕default · 200 % reflow': read back 688 x 856 at (1360, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕export · 200 % reflow': read back 688 x 440 at (80, 1072); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-096∕default · forced colours': read back 816 x 736 at (848, 1072); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕export · forced colours': read back 688 x 440 at (80, 1916); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-096∕default · focus return': read back 1200 x 296 at (848, 1916); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-093∕export · focus return': read back 1200 x 400 at (80, 2464); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E41/img/E41-D01-10-keyboard-and-reflow.png: record the board id and the PNG size

## Derivations (2)

- totals (LIVE, 1 Oct 2026 – 30 Oct 2026 · all accounts): 18 of 42 net-positive → 43 %; mean R +0.30R; net +324.57 USDT (sum of the rows' gross − fees + funding; no aggregate row, WD-9)
- usage counts: trades carrying each tag in the whole journal (LIVE and DEMO; tags are global): breakout 19, fade 21, range-retest 14, late-entry 5, moved-stop 3, fomo 9, us-open 9, news 3

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (14)

- `14` L2158: "[all v]"
- memo L77: "at 200 % zoom both reflow to one column with no horizontal scroll and no clipped action"
- memo L77: "borders, the focus ring, the scope label and the CMP-019 lock glyph stay visible in system colours"
- memo L77: "focus enters the dialog on its heading, Escape or cancel closes it"
- memo L77: ""Manage tags""
- memo L77: ""Export""
- scope.live (§7.1 L160): "LIVE only — DEMO trades are not included"
- `14` L2175: "environment"
- `14` L2158: "range"
- `14` L2154: "account"
- `14` L2168: "symbol"
- `14` L2158: "tag"
- `14` L2175: "outcome"
- export.confirm (§7.1 L169): "Includes account data for {accounts} · {env} · {range} · {rows} trades"

## Copy gaps (21)

- "Tab; Enter opens SCR-096": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — keyboard line (no journal hotkeys in `14`)
- "Tab; Enter opens the confirm": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — keyboard line (no journal hotkeys in `14`)
- "Tab between; Enter / Space opens": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — keyboard line (no journal hotkeys in `14`)
- "Tab; Enter sorts": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — keyboard line (no journal hotkeys in `14`)
- "Tab to the table (one roving tab stop); Up / Down arrows move between rows; Enter opens SCR-094 (a page)": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — keyboard line (no journal hotkeys in `14`)
- "Space toggles the selection": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — keyboard line (no journal hotkeys in `14`)
- "Tab; Enter loads the next cursor page": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — keyboard line (no journal hotkeys in `14`)
- "Next page": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Search tags": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Close": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Create tag": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "format": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Cancel": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "dialog, field and table borders → CanvasText (every edge is a stroke, none is a fill alone)": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — forced-colours mapping
- "focus ring on 'Create tag' → Highlight, 2 px": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — forced-colours mapping
- "colour swatch → its token name stays as text beside it; the swatch may lose its fill": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — forced-colours mapping
- "usage counts and the auto rule are text; no state rests on fill alone": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — forced-colours mapping
- "dialog border and the format field → CanvasText": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — forced-colours mapping
- "focus ring on 'Export' → Highlight, 2 px": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — forced-colours mapping
- "the scope behind the dialog and in the confirm (LIVE) is words, not a fill": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy) — forced-colours mapping
- "(tag table)": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)

## Fallbacks (4)

- wireframe: the focus ring is drawn as a 2 px color.text.primary outline (border.focus), not color.focus.ring (a hue); E41-D02 / D03 bind the ring token in hi-fi
- wireframe: the LIVE / DEMO scope label is words in a bordered badge; color.env.* (hues) is not bound
- kit choice: board markers (focus-order numbers, reading-order arrows, zoom notes) are caption text in a 'dashed · ' outline (board markers, not product UI)
- wireframe: a primary action is a color.surface.selected fill with a 2 px color.border.strong edge; no action hue

## Sources (6)

- spec (memo) docs/design/research/e41-journal-review.md md5 f8c849aa9a46a3c9416f197d79eca321 at the boards PR (§0 drawn, §12 As built) (§0 L75)
- docs/design/research/e41-d01-session-protocol.md md5 01433dd72a698bca4453a45f12250544 (the session protocol: stimuli, §4a prompts)
- docs/plan/17-ux-diagrams.md md5 0494186310c960cef92f3c614625db44 (`17` §1.6 journey)
- docs/plan/14-screens-catalogue.md at 46e6acd2d md5 1ca288905451c9e5c495a0468c062641 (`14` SCR-093..096 state words the memo cites)
- docs/plan/21-database-schema.md at 46e6acd2d md5 60a9ee1cef41b27a1f0524190b68f199 (`21` §3.7.2 tag categories)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step)

## Tokens (35)

- color.border.strong
- border.hairline
- radius.control
- space.inset.sm
- space.inset.xs
- type.ui.caption
- color.text.tertiary
- color.surface.raised
- color.border.default
- color.text.primary
- type.num.sm
- color.surface.canvas
- type.ui.body-strong
- space.button.paddingX
- type.ui.heading-md
- space.stack.xs
- type.ui.label
- radius.badge
- border.thick
- type.ui.body
- space.stack.sm
- color.text.secondary
- size.icon
- color.surface.sunken
- space.inset.lg
- space.stack.md
- color.surface.app
- space.stack.lg
- space.inset.xl
- color.surface.selected
- space.dialog.padding
- color.surface.overlay
- radius.dialog
- color.neutral.default
- type.ui.heading-sm
