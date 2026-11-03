# E19-D05 / 10 flash-announcements

File `E19-D05 boards`, page `E19-D05`; export `docs/design/E19/img/E19-D05-10-flash-announcements.png`; sheet `10-flash-announcements.json` (validated); theme dark.

Board 10 of ten (§0 L115: SCR-038/flash-audit-dark, SCR-038/announcement-timeline-dark: §8). Grid (30400, 5600); 3280 x 918 px; "page E19-D05 · board 10 · r1".

## Frames

- `SCR-038∕flash-audit-dark` (dark, 1188 x 720)
- `SCR-038∕announcement-timeline-dark` (dark, 1372 x 592)

## Validator and size

- `10-flash-announcements.json: 0 errors, 0 warnings, 11 sections, 43089 bytes` (exit 0)
- 11 sections, 43089 bytes

## Live checks (5)

- root 'E19-D05 / 10 flash-announcements' at (30400, 5600): read back the name exactly after the first section call; size 3280 x 918
- after touchTexts + relayout: the annotation column (estimated 581 px) ends inside the root (h 918, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕flash-audit-dark': read back 1188 x 720 at (80, 80); clip on, no child spills
- frame 'SCR-038∕announcement-timeline-dark': read back 1372 x 592 at (1348, 80); clip on, no child spills
- export docs/design/E19/img/E19-D05-10-flash-announcements.png; record the board id and the PNG size

## Readings (2)

- Not drawn — the text is binding (§8.3 L418): D05 W-1b's down form "POC moved down {n} rows"; the timeline's jump run moves the POC up, so the appended words show the up form only; the down forms are the same strings with the glyph and verb swapped and "up" / "down" as hidden text
- R-K1 (export path): §0 names none; the kit takes the merged motion specs' form docs/design/E19/img/E19-D05-NN-<slug>.png (E08-D11 §0)

## Derivations (3)

- combined area: 8 × 256 + 4 × 256 + 4 × 256 = 4096 px² ≤ 21824 px² (HS-1b)
- "Period: Fixed range": the example "Period: {mode}" (spec L78) with this frame's values
- world: BTCUSDT 30-minute bars 11 Oct 00:00 – 31 Oct 14:30 UTC (the bar in progress), one upward walk seeded 500 (the issue number, §9's prototype seed), prices at the fixture's tick 0.10, sizes at its qty step 0.001, volume on a 10-tick grain; live updates from 14:41:00 UTC at the 1000 ms default throttle; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (3)

- D02 W-38: "Profile settings applied." (D02 L387)
- D02 W-33: "POC {price}, VAH {price}, VAL {price}" (D02 L382) filled from the world
- W-1b: "POC moved up {n} rows" (spec L419) filled from the world

## Copy gaps (2)

- "re-derived" / "equal": the kit's check column (token-sync.json + contrast_check.relative_luminance)
- "visually hidden": the kit's marker label for a string a screen reader hears (board marker)

## Fallbacks (3)

- kit stand-in: the renderer binds opacity only to a token and no token carries a key frame's computed opacity (R-3 adds none), so a shape between 0 and 1 is drawn as its outline (1 px border.hairline in its ink, no fill) and its opacity, computed from PRIM's easing at that time, is written in the key frame's caption; 1 is drawn solid and 0 is not drawn
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a timeline or a measurement, never product UI
- kit choice: a string a screen reader hears (a polite announcement) is drawn for the board as caption text in a bordered 'visually hidden' box (not on screen in the product)

## Sources (5)

- spec E19-D05.md md5 6cf5556d in this checkout (§0 L115; BQ-13 RULED: ACCEPT; no hand-off file, BQ-1)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; re-pinned when its PR merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via checkout; re-pinned when its PR merges)
- PRIM packages/ui/tokens/primitives.tokens.json md5 b5e47569 (motion durations and easings only)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)

## Tokens (23)

- type.ui.caption
- color.text.primary
- space.inset.sm
- space.inset.xs
- color.surface.canvas
- color.surface.raised
- color.text.tertiary
- color.profile.valuearea
- border.hairline
- color.profile.poc
- color.border.strong
- color.text.secondary
- type.ui.heading-sm
- color.surface.app
- type.ui.label
- type.num.xs
- color.focus.ring
- space.stack.xs
- radius.control
- color.surface.sunken
- radius.card
- space.stack.sm
- space.inset.lg
