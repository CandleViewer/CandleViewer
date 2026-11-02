# E47-D07 / 10 copy-anatomy

File `E47-D07 boards`, page `E47-D07 announcements`; export `docs/design/E47/img/E47-D07-10-copy-anatomy.png`; sheet `10-copy-anatomy.json` (validated); theme dark.

Board 10 of 10 (§0 L75: §7.1: class word, fact with symbol, qualifiers, account; the closed slots). Grid (28000, 4200); 1920 x 1000 px; "page E47-D07 announcements · board 10 · r1".

## Frames

- `copy∕anatomy · dark` (§H: `copy/anatomy · dark`)

## Validator and size

- `10-copy-anatomy.json: 0 errors, 0 warnings, 16 sections, 37118 bytes` (exit 0)
- 16 sections, 37118 bytes

## Live checks (4)

- root 'E47-D07 / 10 copy-anatomy' at (28000, 4200): read back the name exactly after the first section call; size 1920 x 1000
- after touchTexts + relayout: the annotation column (estimated 554 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'copy∕anatomy · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- export docs/design/E47/img/E47-D07-10-copy-anatomy.png; record the board id and the PNG size in §0

## Ambiguities (1)

- Board 10: §7.1 names the four parts but not where the fact ends; the kit ends it at the first qualifier after the symbol (" at {price}", ", average", " Reason:") or at its sentence's end

## Spec gaps (0)

## Deviations (0)

## Copy keys (5)

- W-43 (§7.2 L320, D17:259; verbatim (the account is the account slot)): Positions for account Main are no longer shown — access changed.
- W-1 (§7.2 L279, no source; PROPOSED): Filled. {type} {side} {qty} {symbol} at {price}.
- W-3 (§7.2 L281, no source; PROPOSED): Rejected. {type} {side} {qty} {symbol} at {price}. Reason: {reason}.
- W-5 (§7.2 L283, no source; PROPOSED): Auto-flattened. {symbol} {position_side} {qty} closed by the risk engine. Reason: {reason}.
- W-36 (§7.2 L313, no source; PROPOSED): Reason not recognised. See Notifications.

## Copy gaps (0)

## Fallbacks (4)

- kit choice: class tones (assertive danger, status info, ambient neutral, echo selected, silent sunken) are a stripe plus a subtle fill; the class word is always written, so colour is never the only signal (1.4.1)
- kit choice: numbered stop markers, tags, arrows and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: a diagram board (map, regions, timeline, matrix, anatomy) is a 1280 x 800 specimen frame on color.surface.canvas; its boxes, lanes and bars are annotation drawing, not product UI
- kit choice: board 10 reuses the four class tones as part tones (class word, fact, qualifiers, account); each chip names its part, so colour is not the only signal

## Sources (1)

- spec docs/design/E47/E47-D07.md md5 78bc33e5, hand-off docs/design/E47/E47-D07-handoff.md md5 574b8489 (§0 L75; hand-off §H L107); scripts docs/design/E47/E47-D07-transcripts.json md5 6bf5c553 replayed through docs/design/_tools/e47_d07_announcement_audit.py md5 d6f86dbc; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 1ff5d8cb9 (§7.1 there)

## Tokens (28)

- type.ui.heading-sm
- color.text.primary
- space.stack.xs
- type.ui.label
- color.text.secondary
- type.ui.body
- type.ui.caption
- space.inset.sm
- space.inset.xs
- color.status.danger.strong
- color.status.danger.subtle
- radius.control
- color.status.info.strong
- color.status.info.subtle
- color.neutral.default
- color.neutral.subtle
- color.border.selected
- color.surface.selected
- type.num.sm
- radius.badge
- color.border.default
- border.hairline
- color.text.inverse
- color.status.info.default
- color.surface.canvas
- color.text.tertiary
- space.stack.sm
- space.inset.lg
