# E41-D01 / 09 scr096-tag-manager

File `E41-D01 boards`, page `E41-D01`; export `docs/design/E41/img/E41-D01-09-scr096-tag-manager.png`; sheet `09-scr096-tag-manager.json` (validated); theme dark.

Board 09 of ten (memo §0 L74: SCR-096 default, create, rename, merge, delete, empty, error). Grid (21000, 5200); 3248 x 2418 px; "page E41-D01 · board 09 · r1".

## Frames

- `SCR-096∕default` (`SCR-096/default`)
- `SCR-096∕create` (`SCR-096/create`)
- `SCR-096∕rename` (`SCR-096/rename`)
- `SCR-096∕merge` (`SCR-096/merge`)
- `SCR-096∕delete` (`SCR-096/delete`)
- `SCR-096∕empty` (`SCR-096/empty`)
- `SCR-096∕error` (`SCR-096/error`)

## Validator and size

- `09-scr096-tag-manager.json: 0 errors, 2 warnings, 34 sections, 103204 bytes` (exit 0)
- 34 sections, 612 shapes, 103204 bytes

## Live checks (10)

- root 'E41-D01 / 09 scr096-tag-manager' at (21000, 5200): read back the name exactly after the first section call; size 3248 x 2418
- after touchTexts + relayout: the annotation column (estimated 1183 px with 15 % slack) ends inside the root (h 2418); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-096∕default': read back 816 x 640 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-096∕create': read back 816 x 712 at (976, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-096∕rename': read back 816 x 416 at (1872, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-096∕merge': read back 816 x 392 at (80, 928); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-096∕delete': read back 816 x 344 at (976, 928); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-096∕empty': read back 816 x 520 at (1872, 928); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-096∕error': read back 816 x 744 at (80, 1556); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E41/img/E41-D01-09-scr096-tag-manager.png: record the board id and the PNG size

## Derivations (6)

- usage counts: trades carrying each tag in the whole journal (LIVE and DEMO; tags are global): breakout 19, fade 21, range-retest 14, late-entry 5, moved-stop 3, fomo 9, us-open 9, news 3
- create: 'breakout-retest' is 15 characters (≤ 24, `14` SCR-096 validation); category from `21`'s enum setup, mistake, emotion, session, general
- rename: 'fomo' is on 9 trades
- merge: 'late-entry' on 5 trades, 'moved-stop' on 3, both on 0; union 8
- delete: 'news' is on 3 trades
- error: 'Breakout' clashes with 'breakout' under `21`'s unique index on lower(name)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- memo L77: ""Manage tags""
- `14` L2216: "tag names unique, ≤24 chars"

## Copy gaps (21)

- "Create tag": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Search tags": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Close": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Name": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Category": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Save": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Cancel": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Rename 'fomo'": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Renames the tag on 9 trades.": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Rename": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "New name": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Merge 'late-entry' into 'moved-stop'": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "5 trades move from 'late-entry' to 'moved-stop'; 0 of them already carry 'moved-stop'.": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "'moved-stop' will be on 8 trades.": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Merge": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Delete 'news'": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "3 trades lose the tag. The trades themselves stay.": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Delete tag": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "No tags yet": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "Tags created here, or added on a trade, are listed with their usage": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)
- "'breakout' exists; names are unique ignoring case": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the copy)

## Fallbacks (3)

- wireframe: a primary action is a color.surface.selected fill with a 2 px color.border.strong edge; no action hue
- wireframe: the focus ring is drawn as a 2 px color.text.primary outline (border.focus), not color.focus.ring (a hue); E41-D02 / D03 bind the ring token in hi-fi
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for the CMP-019 lock glyph

## Sources (6)

- spec (memo) docs/design/research/e41-journal-review.md md5 b2629298bc1879afa24b935e0d017f5b at the boards PR (§0 drawn, §12 As built) (§0 L74)
- docs/design/research/e41-d01-session-protocol.md md5 01433dd72a698bca4453a45f12250544 (the session protocol: stimuli, §4a prompts)
- docs/plan/17-ux-diagrams.md md5 0494186310c960cef92f3c614625db44 (`17` §1.6 journey)
- docs/plan/14-screens-catalogue.md at 46e6acd2d md5 1ca288905451c9e5c495a0468c062641 (`14` SCR-093..096 state words the memo cites)
- docs/plan/21-database-schema.md at 46e6acd2d md5 60a9ee1cef41b27a1f0524190b68f199 (`21` §3.7.2 tag categories)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step)

## Tokens (34)

- radius.control
- color.border.strong
- border.hairline
- color.neutral.default
- type.ui.caption
- color.text.primary
- color.text.secondary
- size.icon
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- color.border.default
- type.num.sm
- color.surface.canvas
- type.ui.body-strong
- space.button.paddingX
- border.thick
- color.surface.selected
- type.ui.body
- color.surface.sunken
- type.ui.heading-md
- space.dialog.padding
- space.stack.md
- color.surface.overlay
- radius.dialog
- space.inset.xl
- space.stack.sm
- type.ui.label
- space.stack.xs
- space.stack.lg
- type.ui.heading-sm
- size.icon.sm
- space.inset.lg
