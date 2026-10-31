# E08-D06 / 06 SCR-103∕not-trading-closed-owner

File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; export `docs/design/E08/img/scr-103-not-trading-closed-owner-dark.png`; sheet `06-not-trading-closed-owner-dark.json` (validated); theme dark.

Board 6D (§15 L619: LUNAUSDT Closed, `status_reason` (AC 3)). Grid (0, 2400); 1120 x 1260 px; footer "page E08-D06 SCR-103 Symbol info · board 06 · r3".

## Frames

- `SCR-103 · Not trading · Closed · Owner · LUNAUSDT · dark · compact` (480 x 1100; Not trading)

## Validator and size

- `06-not-trading-closed-owner-dark.json: 0 errors, 0 warnings, 13 sections, 34791 bytes` (exit 0)
- 13 sections, 34791 bytes

## Live checks (6)

- root 'E08-D06 / 06 SCR-103∕not-trading-closed-owner' at (0, 2400): read back the name exactly after the first section call; size 1120 x 1260
- after touchTexts + relayout: the annotation column (estimated 1132 px) ends inside the root (h 1260); raise the root's h to its end + 80 if not
- frame 'SCR-103 · Not trading · Closed · Owner · LUNAUSDT · dark · compact': read back 480 x 1100 at (80, 80); clip on, no child spills; its caption sits 28 px above it
- export docs/design/E08/img/scr-103-not-trading-closed-owner-dark.png: record the board id and the PNG size (1120 x 1260 at 1x)
- board 6D: the footer holds one button (Open in new chart); no Open DOM ladder
- board 6D: the danger notice sits under the identity line inside the sticky header

## Derivations (2)

- SCR-103 · Not trading · Closed · Owner · LUNAUSDT · dark · compact: sticky header 181 = the measured header 180 + the 1 px header rule (live-check fold)
- LUNAUSDT rules by the §5 F3 formatter on instruments_after.json: status Closed, tick 0.0001, step 0.001, minQty 0.001, maxQty 100, minNotional 5, maxLev 100×, levStep 0.01, funding 8 h, identity LUNA / USDT · USDT perpetual · settled in USDT · listed 2020-04-01

## Spec gaps (0)

## Deviations (0)

## Copy gaps (0)

## Fallbacks (3)

- kit choice (Q7): the drawer is 480 px wide; no size.drawer token exists (§2 D-14)
- the state glyphs (● ○ ◐ ▲ ▼ ✕) are text characters of the value string (§10.3 'Colour'), not icons
- kit choice: r2's numbered markers are not drawn on the frames; each marker is an annotation block naming its part ('at: ...') so no marker shifts the drawer's layout

## Spec cites (9)

- L293: notice under the title: "BTCUSDT is not trading on Bybit."
- L42: then status_reason verbatim (server text written for screen readers, #
- L42: CMP-239 delisted only when delisted
- L42: delisted is derived and true only for Delivering and Closed
- L42: The contract band stays fully legible
- L42: the live band is replaced by one sentence, the countdown is suppressed
- L293: "Recorded coverage isn't available for symbols that aren't trading." w
- L42: Open in new chart is the only action
- L293: a flip while open is announced once

## Sources (2)

- Seed data: the r2 board script's DATA block, sha256 298c156f…e1a7, posted 2026-10-23 on #174 (values re-derived by the §5 formatters)
- spec E08-D06.md md5 af8763f0 (§15 L619); hand-off E08-D06-handoff.md md5 50667e8f; r2 data block sha256 298c156f

## Tokens (34)

- type.ui.caption
- color.data-confidence.delisted.text
- space.inset.xs
- radius.badge
- color.data-confidence.delisted.indicator
- border.hairline
- color.status.danger.strong
- size.icon
- type.ui.body-strong
- color.text.primary
- type.ui.body
- space.inset.md
- space.stack.sm
- radius.card
- color.status.danger.subtle
- type.ui.heading-md
- space.inset.sm
- color.text.secondary
- radius.control
- space.dialog.padding
- color.border.default
- type.num.base
- color.text.tertiary
- space.inset.lg
- type.ui.heading-sm
- space.stack.xs
- color.text.link
- space.button.paddingX
- color.action.secondary.default
- space.stack.lg
- color.surface.overlay
- elevation.dialog
- type.ui.label
- color.surface.canvas
