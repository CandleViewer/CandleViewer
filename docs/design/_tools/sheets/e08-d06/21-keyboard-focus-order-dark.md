# E08-D06 / 21 SCR-103∕keyboard-focus-order

File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; export `docs/design/E08/img/scr-103-keyboard-focus-order-dark.png`; sheet `21-keyboard-focus-order-dark.json` (validated); theme dark.

Board 21D (§15 L634: §10.1). Grid (0, 9600); 1640 x 1560 px; footer "page E08-D06 SCR-103 Symbol info · board 21 · r3".

## Frames

- `SCR-103 · Keyboard focus order · §10.1 · dark · compact` (1000 x 1400; no §6 state)
- Left: d01 with the ring on Close; right: §10.1 keys table + the Tab order

## Validator and size

- `21-keyboard-focus-order-dark.json: 0 errors, 0 warnings, 21 sections, 59177 bytes` (exit 0)
- 21 sections, 59177 bytes

## Live checks (6)

- frame 21: the right column needs about 1022 of 1400 px; the drawer is 1360 tall at y 16
- the focus ring sits on Close only
- root 'E08-D06 / 21 SCR-103∕keyboard-focus-order' at (0, 9600): read back the name exactly after the first section call; size 1640 x 1560
- after touchTexts + relayout: the annotation column (estimated 664 px) ends inside the root (h 1560); raise the root's h to its end + 80 if not
- frame 'SCR-103 · Keyboard focus order · §10.1 · dark · compact': read back 1000 x 1400 at (80, 80); clip on, no child spills; its caption sits 28 px above it
- export docs/design/E08/img/scr-103-keyboard-focus-order-dark.png: record the board id and the PNG size (1640 x 1560 at 1x)

## Derivations (2)

- CMP-046 drawer: sticky header 103 = the measured header 102 + the 1 px header rule (live-check fold)
- Tab stops in this state: 4 controls (r2's _order) then the trap back to Close

## Spec gaps (0)

## Deviations (0)

## Copy gaps (0)

## Fallbacks (3)

- kit choice (Q7): the drawer is 480 px wide; no size.drawer token exists (§2 D-14)
- the state glyphs (● ○ ◐ ▲ ▼ ✕) are text characters of the value string (§10.3 'Colour'), not icons
- kit choice: r2's numbered markers are not drawn on the frames; each marker is an annotation block naming its part ('at: ...') so no marker shifts the drawer's layout

## Spec cites (5)

- L397: the title (tabindex="-1"); for section: "coverage", the CandleViewer b
- L397: the title (tabindex="-1")
- L398: Close → band actions (Retry, Try again) → "Show all N tiers" → the tie
- L398: Tab, Shift+Tab
- L398: each control, ring color.focus.ring at border.focus

## Sources (1)

- spec E08-D06.md md5 af8763f0 (§15 L634); hand-off E08-D06-handoff.md md5 50667e8f; r2 data block sha256 298c156f

## Tokens (29)

- type.ui.heading-md
- color.text.primary
- space.inset.sm
- color.text.secondary
- size.icon
- radius.control
- space.inset.xs
- color.focus.ring
- border.focus
- type.ui.caption
- space.dialog.padding
- space.stack.sm
- color.border.default
- type.ui.body
- type.num.base
- color.text.tertiary
- space.inset.lg
- type.ui.heading-sm
- space.stack.xs
- color.text.link
- type.ui.body-strong
- space.button.paddingX
- color.action.secondary.default
- space.stack.lg
- color.surface.overlay
- elevation.dialog
- type.ui.label
- color.surface.app
- color.surface.canvas
