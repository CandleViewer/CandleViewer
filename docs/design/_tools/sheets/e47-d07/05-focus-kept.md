# E47-D07 / 05 focus-kept

File `E47-D07 boards`, page `E47-D07 announcements`; export `docs/design/E47/img/E47-D07-05-focus-kept.png`; sheet `05-focus-kept.json` (validated); theme dark.

Board 05 of 10 (§0 L70: §9: focus and the typed price kept on a reject; the auto-flatten alertdialog exception). Grid (28000, 0); 3280 x 998 px; "page E47-D07 announcements · board 05 · r1".

## Frames

- `focus∕reject-kept · dark` (§H: `focus/reject-kept · dark`)
- `focus∕alertdialog · dark` (§H: `focus/alertdialog · dark`)

## Validator and size

- `05-focus-kept.json: 0 errors, 1 warnings, 12 sections, 28921 bytes` (exit 0)
- 12 sections, 28921 bytes

## Live checks (6)

- modal: re-centre 'CMP-044 alertdialog · auto-flatten' after relayout (estimated 440 x 172 px)
- root 'E47-D07 / 05 focus-kept' at (28000, 0): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the root's h 998 is the measured max(column end, footer end) + 80 (annotation column estimated 581 px); read it back
- frame 'focus∕reject-kept · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'focus∕alertdialog · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D07-05-focus-kept.png; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (1)

- dialog width 440 px: a kit choice (no source gives the dialog's width; the E47-D05 kit's)

## Copy keys (3)

- W-41 (§7.2 L318, no source; PROPOSED): View position
- W-41 (§7.2 L318, no source; PROPOSED): Dismiss
- W-40 (§7.2 L317, no source; PROPOSED): Position auto-flattened

## Copy gaps (1)

- "Order ticket" and "Price": the ticket's heading and its price field's label (§9 names "the order ticket's price field"; the ticket is E11's, its other controls are placeholders here)

## Fallbacks (4)

- kit choice: the shell chrome (TopBar, NavRail, StatusBar), the other CMP-086 entries and the other SCR-117 sections drawn as neutral placeholders; only this spec's parts are drawn
- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light
- kit choice: numbered stop markers, tags, arrows and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim

## Sources (1)

- spec docs/design/E47/E47-D07.md md5 ab7bad64, hand-off docs/design/E47/E47-D07-handoff.md md5 5b74ef6e (§0 L70; hand-off §H L107); scripts docs/design/E47/E47-D07-transcripts.json md5 6bf5c553 replayed through docs/design/_tools/e47_d07_announcement_audit.py md5 8ab6f248; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1 there)

## Tokens (40)

- color.status.danger.strong
- size.icon
- type.ui.body
- color.text.primary
- space.inset.sm
- color.surface.overlay
- radius.card
- color.border.default
- border.hairline
- radius.control
- color.surface.hover
- type.ui.heading-sm
- type.num.base
- space.stack.xs
- color.surface.canvas
- color.border.strong
- color.focus.ring
- border.focus
- type.ui.label
- space.stack.md
- space.inset.lg
- color.surface.raised
- type.ui.caption
- color.text.inverse
- space.inset.xs
- color.status.info.default
- color.surface.app
- color.border.subtle
- space.inset.md
- type.ui.body-strong
- space.button.paddingX
- color.action.secondary.default
- type.ui.heading-md
- radius.dialog
- space.dialog.padding
- opacity.scrim
- color.surface.sunken
- color.text.secondary
- color.text.tertiary
- space.stack.sm
