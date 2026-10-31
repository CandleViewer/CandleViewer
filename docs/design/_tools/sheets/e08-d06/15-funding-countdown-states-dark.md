# E08-D06 / 15 CMP-126∕funding-countdown-states

File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; export `docs/design/E08/img/cmp-126-funding-countdown-states-dark.png`; sheet `15-funding-countdown-states-dark.json` (validated); theme dark.

Board 15D (§15 L628: §7 states; the sign variants and no `rate`). Grid (12000, 4800); 1600 x 1098 px; footer "page E08-D06 SCR-103 Symbol info · board 15 · r3".

## Frames

- `SCR-103 · CMP-126 funding countdown · every condition · dark · compact` (960 x 900; Clock alarm)
- One table: story name | shown (CMP-126 drawn by the kit) | condition; 12 rows (r2 cmp126)

## Validator and size

- `15-funding-countdown-states-dark.json: 0 errors, 0 warnings, 12 sections, 31876 bytes` (exit 0)
- 12 sections, 31876 bytes

## Live checks (6)

- frame 15: the table needs about 450 px of 868; read back the last row (Zero) inside
- the < 5 min row leads with the warning glyph in color.status.warning.strong; the InBandState row sits on color.data-confidence.stale.surface with digits in color.data-confidence.stale.text
- root 'E08-D06 / 15 CMP-126∕funding-countdown-states' at (12000, 4800): read back the name exactly after the first section call; size 1600 x 1098
- after touchTexts + relayout: the annotation column (estimated 773 px) ends inside the root (h 1098); raise the root's h to its end + 80 if not
- frame 'SCR-103 · CMP-126 funding countdown · every condition · dark · compact': read back 960 x 900 at (80, 80); clip on, no child spills; its caption sits 28 px above it
- export docs/design/E08/img/cmp-126-funding-countdown-states-dark.png: record the board id and the PNG size (1600 x 1098 at 1x)

## Derivations (3)

- ≥ 1 h: next in 01:24:13 · 08:00 UTC = next_funding_time_ms - ts_ms floored to seconds (5053 s) from the recorded ticker; < 1 h / < 5 min use §7's {'lt1h': 3599, 'lt5m': 252} s (L321, L322)
- rates F6: fundingRate 0.0000771 -> +0.00771 %; Negative = the same with the sign flipped (−0.00771 %, illustrative); Zero -> 0.0000 % (L233)
- clock row: skew 612 ms is §7's example (L303)

## Spec gaps (0)

## Deviations (0)

## Copy gaps (0)

## Fallbacks (1)

- kit choice: r2's numbered markers are not drawn on the frames; each marker is an annotation block naming its part ('at: ...') so no marker shifts the drawer's layout

## Spec cites (8)

- H158: no rate (SCR-103)
- L424: text in aria-live="off"
- L330: The digits update at most once a second
- L322: polite once at 5 min and at 1 min: "BTCUSDT funding settles in 5 minut
- H148: the warning glyph on surface.overlay is 10.17 / 3.78 / 10.17 and carri
- L44: never negative, never a frozen 00:00:00
- L332: The two clocks are kept apart:
- H156: the sign in text (CMP-020), never colour alone

## Sources (1)

- spec E08-D06.md md5 af8763f0 (§15 L628); hand-off E08-D06-handoff.md md5 50667e8f; r2 data block sha256 298c156f

## Tokens (21)

- type.ui.label
- color.text.secondary
- space.inset.sm
- space.inset.xs
- type.num.base
- color.text.primary
- space.stack.xs
- type.ui.caption
- color.border.subtle
- color.status.warning.strong
- size.icon
- type.ui.body
- color.data-confidence.stale.text
- color.data-confidence.stale.surface
- space.inset.lg
- color.border.default
- color.surface.app
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
- color.surface.canvas
