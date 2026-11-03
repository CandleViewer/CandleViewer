# E47-D13 / 08 entry-insets

File `E47-D13 boards`, page `E47-D13 — Conformance statement`; export `docs/design/E47/img/E47-D13-08-entry-insets.png`; sheet `08-entry-insets.json` (validated); theme dark.

Board 08 of ten (§0 L79: the entry links on SCR-117 and SCR-119 as insets (with E47-D05 #1304's SCR-117 frame) (§7.1)). Grid (12000, 3200); 3280 x 998 px; "page E47-D13 — Conformance statement · board 08 · r1".

## Frames

- `entry∕scr-117 · dark`
- `entry∕scr-119 · dark`

## Validator and size

- `08-entry-insets.json: 0 errors, 0 warnings, 18 sections, 38473 bytes` (exit 0)
- 18 sections, 38473 bytes

## Live checks (5)

- root 'E47-D13 / 08 entry-insets' at (12000, 3200): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the root's h 998 is the measured max(column end, footer end) + 80 (annotation column estimated 741 px); read it back
- frame 'entry∕scr-117 · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'entry∕scr-119 · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D13-08-entry-insets.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- W-1 (§11 L284, verbatim (the shipped link))
- W-3 (§11 L286, verbatim (the shipped link))

## Copy gaps (3)

- h1 "Accessibility": the settings nav entry of `14` SCR-110 L2379 (SCR-117's page title is E47-D05's)
- h1 "Help & about": `14` SCR-119's title (L2495)
- SCR-119's statement link reuses W-1's words (`14` names the link, not its text)

## Fallbacks (5)

- kit choice: the shell chrome around SettingsLayout (wordmark, pickers, health chip, rail glyphs, StatusBar items) and every SCR-117 / SCR-119 item this spec does not word are neutral placeholders; only what E47-D13 names is drawn with words
- fallback: a text node has no underline; the link underline (`15`:258 block, §7.6) is a 1 px color.text.link rule under the link text
- CMP-039 focus ring per E47-D04's model (PR #5387, pinned in the spec's Start line): 2 px color.focus.ring between 1 px color.surface.canvas halos, 2 px offset (outer extent 6 px)
- kit choice: numbered stops, tags, outlines, redlines and callouts in color.status.info.default on color.text.inverse are annotation, never product UI
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact)

## Sources (1)

- E47-D13.md md5 0cbd55df; E47-D13-handoff.md md5 1da094e2; 47-conformance-report.md md5 807dc1d0; 47-limitations.json md5 f609cce7; 14-screens-catalogue.md md5 1ca28890 at 4c662fd5b (§0 L79; §H L99)

## Tokens (31)

- radius.control
- color.surface.hover
- space.stack.xs
- space.inset.md
- type.ui.body
- color.text.link
- color.surface.canvas
- border.hairline
- color.focus.ring
- border.focus
- color.text.secondary
- space.inset.sm
- type.ui.heading-lg
- color.text.primary
- space.stack.lg
- color.surface.app
- type.ui.label
- color.text.inverse
- color.status.info.default
- radius.badge
- border.thick
- type.ui.caption
- space.inset.xs
- color.border.subtle
- type.ui.body-strong
- color.surface.selected
- color.surface.raised
- space.inset.lg
- space.stack.sm
- type.ui.heading-sm
- color.text.tertiary
