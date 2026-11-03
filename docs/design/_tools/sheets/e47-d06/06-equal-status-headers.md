# E47-D06 / 06 equal-status-headers

File `E47-D06 boards`, page `E47-D06 — Canvas accessibility`; export `docs/design/E47/img/E47-D06-06-equal-status-headers.png`; sheet `06-equal-status-headers.json` (validated); theme dark.

Board 06 of 8 (§0 L72: §7: the View │ Table switch on each inventory panel header; §10's T2 row action, My levels only, Export CSV and the view-as notice). Grid (0, 4200); 4640 x 1878 px; "page E47-D06 — Canvas accessibility · board 06 · r1".

## Frames

- `headers∕switches · dark` (§I: `headers/switches · dark`)
- `headers∕t2-row-action · dark` (§I: `headers/t2-row-action · dark`)
- `headers∕t2-my-levels · dark` (§I: `headers/t2-my-levels · dark`)
- `headers∕t2-export · dark` (§I: `headers/t2-export · dark`)
- `ladder∕t2-trade-keys · dark` (§I: `ladder/t2-trade-keys · dark`)
- `headers∕t2-view-as-notice · dark` (§I: `headers/t2-view-as-notice · dark`)

## Validator and size

- `06-equal-status-headers.json: 0 errors, 111 warnings, 153 sections, 368617 bytes` (exit 0)
- 153 sections, 368617 bytes

## Live checks (9)

- root 'E47-D06 / 06 equal-status-headers' at (0, 4200): read back the name exactly after the first section call; size 4640 x 1878
- after touchTexts + relayout: the root's h 1878 is the measured max(column end, footer end) + 80 (annotation column estimated 790 px); read it back
- frame 'headers∕switches · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'headers∕t2-row-action · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'headers∕t2-my-levels · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'headers∕t2-export · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'ladder∕t2-trade-keys · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- frame 'headers∕t2-view-as-notice · dark': read back 1280 x 800 at (2800, 960); clip on, no child spills
- export docs/design/E47/img/E47-D06-06-equal-status-headers.png; record the board id and the PNG size in §0

## Ambiguities (2)

- the switch's first segment reads "Chart" on the chart panel (D04E11 D1 verbatim) and "View" on the others (§7's generic name); each panel's own words are its spec's (copy gap)
- the one notice sits in the panel header after the switch (§10: "the panel header carries one 2a notice"); its width is a kit choice

## Spec gaps (0)

## Deviations (1)

- the row-action reasons follow §10 (E09-D09 §3.1's rbac.permission), not D04E11:794's older "your role can't create alerts" wording

## Copy keys (3)

- table.export_deferred (PROPOSED, owner E11-D04): "Export arrives with E15", the Export CSV T2 reason
- rbac.permission (E09-D09 §3.1 template): the row-action, My levels only and trade-key reasons
- rbac.view_as (E09-D09 §3.1 template, PROPOSED use here): the view-as notice, synthetic target name

## Copy gaps (1)

- the panel titles are `14`'s screen headings, " panel" and the parenthesis dropped

## Fallbacks (5)

- kit choice: the canvas surfaces are drawn as simplified synthetic plots (bodies, wicks, bars, bubbles) from the seeded stream; their own visual design is their tickets', not this spec's
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) drawn as neutral placeholders (the E47-D03 kit's SCR-116 chrome); only the panels this spec designs carry words
- the CMP-019 Icon `lock` glyph is the local set's `locked` icon (the same glyph, the set's name)
- kit choice: numbered markers, tags, brackets and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI

## Sources (1)

- spec docs/design/E47/E47-D06.md md5 fdde6ab4, hand-off docs/design/E47/E47-D06-handoff.md md5 c6ebe77c (§0 L72; hand-off §I L111); T2 reason templates docs/design/E09/E09-D09.md md5 20c5d5f4; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (58)

- color.candle.wick
- color.candle.up
- color.candle.down
- color.surface.canvas
- type.ui.body-strong
- color.text.primary
- type.ui.label
- color.text.secondary
- size.icon.sm
- color.surface.selected
- color.border.default
- border.hairline
- radius.control
- space.inset.sm
- space.inset.xs
- color.surface.raised
- type.ui.caption
- radius.card
- color.profile.bar
- color.profile.valuearea
- color.profile.poc
- color.heatmap.ask.2
- color.heatmap.ask.1
- color.heatmap.ask.5
- color.heatmap.ask.3
- color.heatmap.ask.4
- color.heatmap.bid.5
- color.heatmap.bid.1
- color.heatmap.bid.2
- color.heatmap.bid.3
- color.heatmap.bid.4
- color.cvd.buy
- color.cvd.sell
- color.node.trigger
- color.node.action
- color.border.strong
- color.surface.app
- color.surface.hover
- color.border.subtle
- space.inset.md
- space.inset.lg
- color.text.tertiary
- type.ui.body
- space.stack.xs
- color.focus.ring
- border.focus
- color.surface.overlay
- type.num.base
- color.buy.default
- color.sell.default
- radius.badge
- color.status.info.default
- border.thick
- color.sell.subtle
- color.buy.subtle
- color.text.inverse
- type.ui.heading-sm
- space.stack.sm
