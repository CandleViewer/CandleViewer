# E08-D06 / 03 SCR-103∕live-stale-t1-t2-owner

File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; export `docs/design/E08/img/scr-103-live-stale-t1-t2-owner-dark.png`; sheet `03-live-stale-t1-t2-owner-dark.json` (validated); theme dark.

Board 3D (§15 L616: "Stale 7s"; the T2 strip; contract band unchanged (AC 2)). Grid (6000, 0); 1640 x 1520 px; footer "page E08-D06 SCR-103 Symbol info · board 03 · r3".

## Frames

- `SCR-103 · Stale, T1 and Stale, T2 · Owner · dark · compact` (1000 x 1360; Stale, T1, Stale, T2)

## Validator and size

- `03-live-stale-t1-t2-owner-dark.json: 0 errors, 1 warnings, 36 sections, 91858 bytes` (exit 0)
- 36 sections, 91858 bytes

## Live checks (8)

- CMP-046 drawer · Stale, T2: the bands need about 1221 px for a 1181 px body: the body clips (the drawer scrolls); read back that the last band is cut at the footer, never under it
- root 'E08-D06 / 03 SCR-103∕live-stale-t1-t2-owner' at (6000, 0): read back the name exactly after the first section call; size 1640 x 1520
- after touchTexts + relayout: the annotation column (estimated 1375 px) ends inside the root (h 1520); raise the root's h to its end + 80 if not
- frame 'SCR-103 · Stale, T1 and Stale, T2 · Owner · dark · compact': read back 1000 x 1360 at (80, 80); clip on, no child spills; its caption sits 28 px above it
- export docs/design/E08/img/scr-103-live-stale-t1-t2-owner-dark.png: record the board id and the PNG size (1640 x 1520 at 1x)
- board 3D: drawers 480 x 1360 (T1) and 480 x 1341 (T2) at x 12 and 508 inside the frame; neither spills the 1000 px frame
- board 3D right drawer: the strip sits under 'Last update 06:35:46 UTC'; the T2 body (1181) ends at the top of the link row, 'Retention (owner)' is the last whole line, the sticky footer follows the body
- board 3D right drawer: a 1 px body shift needs a re-check (the cut sits on a line boundary)

## Derivations (4)

- CMP-046 drawer · Stale, T1: sticky header 103 = the measured header 102 + the 1 px header rule (live-check fold)
- CMP-046 drawer · Stale, T2: sticky header 103 = the measured header 102 + the 1 px header rule (live-check fold)
- frame 3: two 480 px drawers, gap 16 (space.stack.lg), 12 px a side (space.inset.md) = 1000; each drawer 1360 tall
- stale values kept (never live-updating): last 82,751.2, index 82,782.37, Updated 06:35:46 UTC

## Spec gaps (0)

## Deviations (2)

- board 3 right drawer (T2): the body scrolls (§6 Stale, T2) and is cut at the line boundary above the link row, so "Recorder settings" (L99) sits wholly below the cut, hidden, not clipped; the T1 drawer shows it whole
- board 3 right drawer: CMP-239 reads "Stale 15s" (the T2 age in L287's "Stale 7s" form); the spec gives no T2 chip text

## Copy gaps (0)

## Fallbacks (4)

- kit choice (Q7): the drawer is 480 px wide; no size.drawer token exists (§2 D-14)
- the state glyphs (● ○ ◐ ▲ ▼ ✕) are text characters of the value string (§10.3 'Colour'), not icons
- kit choice: the CMP-078 escalated strip binds color.status.danger.subtle with the danger icon (the words carry the state, §10.3)
- kit choice: r2's numbered markers are not drawn on the frames; each marker is an annotation block naming its part ('at: ...') so no marker shifts the drawer's layout

## Spec cites (11)

- L287: CMP-239 "Stale 7s" in the header, "Last update 06:35:46 UTC"
- L287: polite once: "Live values stale." and on exit "Live values current."
- L423: CMP-239 text in the band header, part of the band's description
- L287: band on color.data-confidence.stale.surface, values in .stale.text
- L287: values kept, never live-updating
- L40: The contract band never takes a stale treatment.
- L287: unchanged and authoritative
- L288: as T1 plus the CMP-078 escalated strip "Stale 15 s — new orders blocke
- L288: meta.stale reads "Stale (server) — since 14:02:11"
- L288: the shell's assertive T2 sentence (E17-D01 §7), never repeated here
- L41: Thresholds are E17-D01's T1 / T2 (architect ruling A2): stale at 5 s,

## Sources (2)

- Seed data: the r2 board script's DATA block, sha256 298c156f…e1a7, posted 2026-10-23 on #174 (values re-derived by the §5 formatters)
- spec E08-D06.md md5 af8763f0 (§15 L616); hand-off E08-D06-handoff.md md5 50667e8f; r2 data block sha256 298c156f

## Tokens (36)

- type.ui.heading-md
- color.text.primary
- space.inset.sm
- color.text.secondary
- size.icon
- radius.control
- type.ui.caption
- space.dialog.padding
- space.stack.sm
- color.border.default
- type.ui.body
- space.inset.xs
- type.num.base
- color.text.tertiary
- space.inset.lg
- type.ui.heading-sm
- space.stack.xs
- color.data-confidence.stale.text
- radius.badge
- color.data-confidence.stale.indicator
- border.hairline
- color.data-confidence.stale.surface
- color.text.link
- type.ui.body-strong
- space.button.paddingX
- color.action.secondary.default
- space.stack.lg
- color.surface.overlay
- elevation.dialog
- color.status.danger.strong
- radius.card
- color.status.danger.subtle
- color.surface.app
- space.inset.md
- type.ui.label
- color.surface.canvas
