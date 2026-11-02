# E47-D08 / 08 override-vs-os

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-08-override-vs-os.png`; sheet `08-override-vs-os.json` (validated); theme dark.

Board 08 of 10 (§0 L78: §9: OS reduce with the override off; the W-2 announcement and SCR-117's Effective line). Grid (14000, 4200); 1920 x 1000 px; "page E47-D08 — Motion · board 08 · r1".

## Frames

- `override∕os-reduce-off · dark` (§H: `override/os-reduce-off · dark`)

## Validator and size

- `08-override-vs-os.json: 0 errors, 0 warnings, 6 sections, 18422 bytes` (exit 0)
- 6 sections, 18422 bytes

## Live checks (4)

- root 'E47-D08 / 08 override-vs-os' at (14000, 4200): read back the name exactly after the first section call; size 1920 x 1000
- after touchTexts + relayout: the annotation column (estimated 453 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'override∕os-reduce-off · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-08-override-vs-os.png under the dark set; record the board id and the PNG size in §0

## Ambiguities (1)

- A-2: §0 L78 asks for SCR-117's Effective line with the override off; §15's W-3 is the On fill; the board draws the Off fill of the same E47-D05 template ("Effective: Off, your choice")

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- W-2 (§15 L323, verbatim (RULED; BQ-9)): Reduced motion off
- W-3 (§15 L324, verbatim (D05 W-13; SCR-117)): Effective: On, your choice

## Copy gaps (0)

## Fallbacks (2)

- kit choice: numbered markers, tags, window shading, outlines and callouts are annotation overlays in color.status.info.default (or its subtle tint) with color.text.inverse words, never product UI
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and panels outside the board's subject are neutral placeholders; only the surfaces a board draws are drawn

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 6c50afbb, hand-off docs/design/E47/E47-D08-handoff.md md5 dc1307c8 (§0 L78; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 1ff5d8cb9 (§7.1); SCR-117 strings E47-D05 at 3987edc89

## Tokens (30)

- type.ui.heading-lg
- color.text.primary
- type.ui.heading-sm
- color.surface.canvas
- color.border.strong
- border.hairline
- type.ui.body
- space.inset.sm
- color.action.primary.default
- space.inset.lg
- type.ui.body-strong
- type.ui.caption
- color.text.secondary
- space.stack.xs
- color.surface.hover
- radius.badge
- space.stack.lg
- space.inset.xl
- color.text.inverse
- space.inset.xs
- radius.control
- color.status.info.default
- type.ui.label
- color.surface.overlay
- border.thick
- color.surface.app
- color.border.subtle
- space.inset.md
- color.text.tertiary
- space.stack.sm
