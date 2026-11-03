# E47-D06 / 07 parity-oracle

File `E47-D06 boards`, page `E47-D06 — Canvas accessibility`; export `docs/design/E47/img/E47-D06-07-parity-oracle.png`; sheet `07-parity-oracle.json` (validated); theme dark.

Board 07 of 8 (§0 L73: §9 as a sheet: AC2's footprint bar traced from the canvas to the mirror label, the table row and the oracle row). Grid (7000, 4200); 1920 x 998 px; "page E47-D06 — Canvas accessibility · board 07 · r1".

## Frames

- `parity∕footprint-bar · dark` (§I: `parity/footprint-bar · dark`)

## Validator and size

- `07-parity-oracle.json: 0 errors, 1 warnings, 12 sections, 38714 bytes` (exit 0)
- 12 sections, 38714 bytes

## Live checks (4)

- root 'E47-D06 / 07 parity-oracle' at (7000, 4200): read back the name exactly after the first section call; size 1920 x 998
- after touchTexts + relayout: the root's h 998 is the measured max(column end, footer end) + 80 (annotation column estimated 371 px); read it back
- frame 'parity∕footprint-bar · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- export docs/design/E47/img/E47-D06-07-parity-oracle.png; record the board id and the PNG size in §0

## Ambiguities (2)

- the estimated level's reason is CMP-227's display name "Iceberg" (`iceberg`, a `05`:169 token; R-5); the values slot names each value ("bid …, ask …, delta …")
- the imbalance flag reads ask ≥ 3 × bid at one level (`05`'s 300 % example); the diagonal comparison is E18's

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (2)

- kit choice: the canvas surfaces are drawn as simplified synthetic plots (bodies, wicks, bars, bubbles) from the seeded stream; their own visual design is their tickets', not this spec's
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)

## Sources (1)

- spec docs/design/E47/E47-D06.md md5 fdde6ab4, hand-off docs/design/E47/E47-D06-handoff.md md5 c6ebe77c (§0 L73; hand-off §I L111); T2 reason templates docs/design/E09/E09-D09.md md5 20c5d5f4; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (33)

- type.ui.heading-sm
- color.text.primary
- type.num.sm
- color.axis.text
- color.footprint.bid
- color.text.tertiary
- color.footprint.ask
- space.inset.xs
- space.inset.sm
- color.footprint.imbalance
- border.thick
- type.ui.caption
- radius.badge
- color.text.secondary
- border.hairline
- type.ui.label
- space.stack.xs
- color.surface.sunken
- type.ui.body-strong
- space.stack.sm
- color.surface.raised
- size.icon.sm
- type.num.base
- color.sell.default
- type.ui.body
- color.buy.default
- color.surface.selected
- color.surface.canvas
- color.focus.ring
- border.focus
- space.inset.lg
- color.border.subtle
- space.stack.md
