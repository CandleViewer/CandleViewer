# E08-D06 / 10 SCR-103∕load-error-catalogue-owner

File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; export `docs/design/E08/img/scr-103-load-error-catalogue-owner-dark.png`; sheet `10-load-error-catalogue-owner-dark.json` (validated); theme dark.

Board 10D (§15 L623: AC 4; 404 and 403 strips). Grid (12000, 2400); 1120 x 994 px; footer "page E08-D06 SCR-103 Symbol info · board 10 · r3".

## Frames

- `SCR-103 · Contract load failed, Not in the instrument list, Forbidden · Owner · dark · compact` (480 x 760; Contract load failed, Not in the instrument list, Forbidden)
- Stacked: A (top), B, C; each a hugging CMP-046 drawer, no footer actions (r2 actions [])

## Validator and size

- `10-load-error-catalogue-owner-dark.json: 0 errors, 0 warnings, 5 sections, 23140 bytes` (exit 0)
- 5 sections, 23140 bytes

## Live checks (6)

- frame 10: the three stacked drawers need about 755 px of the 760 px frame; read back that C's bottom edge sits inside the frame (clip on, nothing cut)
- A: the CMP-027 block's Retry is the primary button; B: Search symbols then Retry; C: no button
- root 'E08-D06 / 10 SCR-103∕load-error-catalogue-owner' at (12000, 2400): read back the name exactly after the first section call; size 1120 x 994
- after touchTexts + relayout: the annotation column (estimated 907 px) ends inside the root (h 994); raise the root's h to its end + 80 if not
- frame 'SCR-103 · Contract load failed, Not in the instrument list, Forbidden · Owner · dark · compact': read back 480 x 760 at (80, 80); clip on, no child spills; its caption sits 28 px above it
- export docs/design/E08/img/scr-103-load-error-catalogue-owner-dark.png: record the board id and the PNG size (1120 x 994 at 1x)

## Derivations (1)

- no numbers on this board: the three strips carry the spec's sentences only (§6 rows, §8 T4)

## Spec gaps (0)

## Deviations (0)

## Copy gaps (0)

## Fallbacks (2)

- kit choice (Q7): the drawer is 480 px wide; no size.drawer token exists (§2 D-14)
- kit choice: r2's numbered markers are not drawn on the frames; each marker is an annotation block naming its part ('at: ...') so no marker shifts the drawer's layout

## Spec cites (8)

- L297: CMP-027 error, role="alert" once: "Couldn't load BTCUSDT's contract ru
- L297: the order line, gated on CR-10
- L427: CMP-027: role="alert" (contract), role="status" (coverage, live)
- L488: symbol.info_load_failed
- L307: Retry keeps focus on the button, sets aria-busy on its band and never
- L297: "Ref urn:cv:req:…" only when the problem carries instance
- L398: each control, ring color.focus.ring at border.focus
- L299: T4: "Your role can't see instruments." (E09-D09 rbac.permission)

## Sources (1)

- spec E08-D06.md md5 af8763f0 (§15 L623); hand-off E08-D06-handoff.md md5 50667e8f; r2 data block sha256 298c156f

## Tokens (33)

- type.ui.heading-md
- color.text.primary
- space.inset.sm
- color.text.secondary
- size.icon
- radius.control
- space.dialog.padding
- space.stack.sm
- color.border.default
- color.status.danger.strong
- type.ui.body-strong
- space.inset.xs
- type.ui.body
- color.text.on-action
- space.button.paddingX
- color.action.primary.default
- type.ui.caption
- color.text.tertiary
- space.inset.md
- radius.card
- color.status.danger.subtle
- border.hairline
- type.ui.heading-sm
- space.stack.xs
- space.inset.lg
- space.stack.lg
- color.surface.overlay
- elevation.dialog
- color.action.secondary.default
- color.surface.raised
- color.surface.app
- type.ui.label
- color.surface.canvas
