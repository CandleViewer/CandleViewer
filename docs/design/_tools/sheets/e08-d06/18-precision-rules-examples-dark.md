# E08-D06 / 18 SCR-103∕precision-rules-examples

File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; export `docs/design/E08/img/scr-103-precision-rules-examples-dark.png`; sheet `18-precision-rules-examples-dark.json` (validated); theme dark.

Board 18D (§15 L631: §5; minimal vs as delivered; one stacked 14-char qty; after CR-8 / CR-11). Grid (6000, 7200); 1840 x 1298 px; footer "page E08-D06 SCR-103 Symbol info · board 18 · r3".

## Frames

- `SCR-103 · Precision rules · F1-F10 examples · dark · compact` (1200 x 1100; no §6 state)
- Left: minimal vs as delivered, after CR-8 / CR-11, Stacked; right: tick cases, rule examples, F1-F10

## Validator and size

- `18-precision-rules-examples-dark.json: 0 errors, 0 warnings, 9 sections, 47548 bytes` (exit 0)
- 9 sections, 47548 bytes

## Live checks (6)

- frame 18: the taller column needs about 1029 of 1100 px; read back that F10 ends inside
- the Stacked value 50,000,000,000 reads whole (14 characters), end-aligned under its label
- root 'E08-D06 / 18 SCR-103∕precision-rules-examples' at (6000, 7200): read back the name exactly after the first section call; size 1840 x 1298
- after touchTexts + relayout: the annotation column (estimated 786 px) ends inside the root (h 1298); raise the root's h to its end + 80 if not
- frame 'SCR-103 · Precision rules · F1-F10 examples · dark · compact': read back 1200 x 1100 at (80, 80); clip on, no child spills; its caption sits 28 px above it
- export docs/design/E08/img/scr-103-precision-rules-examples-dark.png: record the board id and the PNG size (1840 x 1298 at 1x)

## Derivations (4)

- minimal = F3 rule_value() of instruments_after.json's BTCUSDT strings; as delivered = those strings (tick 0.10, max qty 100.000, leverage 100.00)
- after CR-8 / CR-11: high 82,850.0 / low 80,611.7 = F4 at_precision of the recorded highPrice24h / lowPrice24h at tick 0.10; 2026-09-01 00:00 UTC is 22's recording_started_at example
- tick cases: shown = the nearest multiple of the tick at the tick's decimals, grouped; Characters = len(shown); BTCUSDT / SOLUSDT / LUNAUSDT ticks from instruments_after.json, the others as §5 gives them
- F4 82,751.2 / 82,782.37, F5 57,911.602, F6 ▲ +1.23 %, F7 812 GB: the kit's formatters on the recorded snapshot and 22's disk example equal r2's F examples

## Spec gaps (0)

## Deviations (0)

## Copy gaps (0)

## Fallbacks (1)

- kit choice: r2's numbered markers are not drawn on the frames; each marker is an annotation block naming its part ('at: ...') so no marker shifts the drawer's layout

## Spec cites (4)

- L244: digits are never cut or ellipsised (board 18)
- L277: the last two rows say so on the board
- L245: F9 One formatter.
- L213: (CR-2)

## Sources (1)

- spec E08-D06.md md5 af8763f0 (§15 L631); hand-off E08-D06-handoff.md md5 50667e8f; r2 data block sha256 298c156f

## Tokens (20)

- type.ui.label
- color.text.secondary
- space.inset.sm
- color.border.default
- type.ui.body
- type.num.base
- color.text.primary
- type.ui.caption
- color.text.tertiary
- color.border.subtle
- type.ui.heading-sm
- space.stack.sm
- space.inset.xs
- color.surface.overlay
- space.stack.lg
- space.stack.xs
- type.ui.body-strong
- color.surface.app
- space.inset.lg
- color.surface.canvas
