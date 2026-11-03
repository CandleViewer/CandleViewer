# E47-D09 / 09 inert

File `E47-D09 boards`, page `E47-D09`; export `docs/design/E47/img/E47-D09-09-inert.png`; sheet `09-inert.json` (validated); theme dark.

Board 09 of ten (§0 L76: the inert message from the journal, non-modal, the polite region marked, and the 200 % inset (§11)). Grid (18000, 3200); 3280 x 998 px; "page E47-D09 · board 09 · r1".

## Frames

- `inert∕journal · dark`
- `inert∕journal-200 · dark`

## Validator and size

- `09-inert.json: 0 errors, 0 warnings, 17 sections, 44670 bytes` (exit 0)
- 17 sections, 44670 bytes

## Live checks (5)

- root 'E47-D09 / 09 inert' at (18000, 3200): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the root's h 998 is the measured max(column end, footer end) + 80 (annotation column estimated 782 px); read it back
- frame 'inert∕journal · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'inert∕journal-200 · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D09-09-inert.png: every frame is 1280 x 800; record the board id and the PNG size

## Readings (2)

- AC5's case is ticket.submit (Ctrl+Enter) pressed in the journal (§11: "the journal case of AC5"); W-6's {contexts} is its registry context "Ticket"
- the toast's tone word "Info" is E10-D03 §7's "glyph + severity word + text" for the info tone (copy gap: no W-row)

## G rows (1)

- D09-G2 (§19.2 L418): the journal and other non-registry views have no keymap context, so the inert message cannot name them (owner E47-S08, the registry rows)

## C rows (1)

- D09-C12 (§19.1 L405): the exceptions stand; every modified binding explains itself

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- W-6 (§16 L311, PROPOSED (BQ-11's {view} reads "this view" until D09-G2))

## Copy gaps (2)

- "Journal": SCR-093's title (`14`:2152); the list and its filters are placeholders
- "Info" and "Dismiss notification": E10-D03 §7 (D03E10:84, :289), not this spec's

## Fallbacks (5)

- kit choice: numbered stop markers, tags, outlines, arrows and callouts are annotation overlays in color.status.info.default (callouts on color.surface.overlay), never product UI; a callout quotes what is spoken (polite) or what a key does
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items, list rows of SCR-093) drawn as neutral placeholders; only what this spec names is drawn with words
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); SCR-012's rows 32 px (E10-D03 §6.1, D03E10:281: 32 compact, 40 comfortable); the shell bars keep E10's 48 px TopBar
- kit choice (E47-D03 board 05's): at 200 % the 1280 x 800 window is a 640 x 400 CSS px viewport; the inset draws the 640 CSS px layout at 1:1 in a 640 px strip with the 400 px viewport outlined; the device shows it at 2 x
- fallback (E47-D03's FALLBACKS type-150): no type token at a 150 % text scale: each role is drawn with the token nearest 1.5 x its size (caption 11 -> heading-md 16, label 12 / body 13 -> heading-lg 20, heading-sm 14 / heading-md 16 -> display 24, num.xs 11 -> heading-md 16)

## Sources (1)

- spec docs/design/E47/E47-D09.md md5 26cc703c (§0 L76); hand-off docs/design/E47/E47-D09-handoff.md md5 bbb18e25 (§H L105); registry at 4c662fd5b apps/web/src/keymap/keymap.json md5 eb409e85 and apps/web/src/keymap/reserved-keys.json md5 5683c37f; tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (40)

- color.status.info.strong
- size.icon
- type.ui.body-strong
- space.inset.xs
- color.text.secondary
- radius.control
- type.ui.body
- color.text.primary
- space.stack.xs
- space.inset.md
- color.surface.overlay
- radius.card
- color.border.default
- border.hairline
- color.status.info.default
- border.thick
- type.ui.caption
- color.text.inverse
- type.ui.label
- space.inset.sm
- color.surface.hover
- space.inset.lg
- color.surface.canvas
- color.surface.raised
- color.focus.ring
- border.focus
- type.ui.heading-lg
- space.stack.md
- space.inset.xl
- color.surface.app
- color.surface.selected
- color.border.subtle
- color.env.live
- space.button.paddingX
- color.status.danger.subtle
- color.status.danger.strong
- type.ui.display
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
