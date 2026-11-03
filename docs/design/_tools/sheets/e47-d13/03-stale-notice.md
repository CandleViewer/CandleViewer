# E47-D13 / 03 stale-notice

File `E47-D13 boards`, page `E47-D13 — Conformance statement`; export `docs/design/E47/img/E47-D13-03-stale-notice.png`; sheet `03-stale-notice.json` (validated); theme dark.

Board 03 of ten (§0 L74: the CMP-028 status notice above the version line, the version-unknown variant (§8.2; W-7, W-8) and the offline frame (§7.3)). Grid (12000, 0); 4640 x 998 px; "page E47-D13 — Conformance statement · board 03 · r1".

## Frames

- `statement∕stale · dark`
- `statement∕version-unknown · dark`
- `statement∕offline · dark`

## Validator and size

- `03-stale-notice.json: 0 errors, 1 warnings, 29 sections, 74768 bytes` (exit 0)
- 29 sections, 74768 bytes

## Live checks (6)

- root 'E47-D13 / 03 stale-notice' at (12000, 0): read back the name exactly after the first section call; size 4640 x 998
- after touchTexts + relayout: the root's h 998 is the measured max(column end, footer end) + 80 (annotation column estimated 826 px); read it back
- frame 'statement∕stale · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'statement∕version-unknown · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'statement∕offline · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D13-03-stale-notice.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (1)

- D13-G2 (§14.2 L386): BuildInfo.version has no ordering, so "older than" is read as "different from"

## Spec gaps (0)

## Deviations (0)

## Copy keys (14)

- W-1 (§11 L284, verbatim (the shipped link))
- W-5 (§11 L288, PROPOSED, the status (R-9))
- W-4 (§11 L287, PROPOSED, the target)
- W-7 (§11 L290, PROPOSED, the stale notice)
- W-6 (§11 L289, PROPOSED, the version line)
- W-11 (§11 L294, PROPOSED, no Supports rows)
- W-9 (§11 L292, PROPOSED, a heading)
- W-10 (§11 L293, PROPOSED, three th column headers)
- W-3 (§11 L286, verbatim (the shipped link))
- W-19 (§11 L302, PROPOSED, the verbosity link)
- W-14 (§11 L297, PROPOSED, the template: three lines, copied with line breaks)
- W-13 (§11 L296, PROPOSED, the CMP-033 label)
- W-12 (§11 L295, PROPOSED, a heading)
- W-8 (§11 L291, PROPOSED, version unknown)

## Copy gaps (14)

- h1 "Accessibility statement": W-1 (§11 L284), the shipped link's words, as the page title (§7.2 item 1 L208)
- "Scope: the web app in its desktop shell.": §7.2 item 2 L209 (no W-string)
- h2 "What is supported": the section name in §7.2 item 4 L211 (§11 has no heading string for it)
- h2 "Alternatives": the section name in §7.2 item 6 L213 (§11 has no heading string for it)
- "Show a data table in place of a chart or panel" before Alt+T: §7.2 item 6 L213 with `05`'s keyboard table (no W-string)
- "Make the text larger" before Ctrl+=: §7.2 item 6 L213 with `05`'s keyboard table (no W-string)
- "Turn reduced motion on or off" before Ctrl+Shift+M: §7.2 item 6 L213 with `05`'s keyboard table (no W-string)
- "Turn the high-contrast theme on or off" before Ctrl+Shift+H: §7.2 item 6 L213 with `05`'s keyboard table (no W-string)
- "Keyboard equivalents for every action" before its link: §7.2 item 6 L213 (no W-string)
- "How much the screen reader announces" before its link: §7.2 item 6 L213 (no W-string)
- "or the font size scale in Appearance & density settings (SCR-116)": §7.2 item 6 L213 ("beside Ctrl+= the page names the SCR-116 text-scale control"; `14` SCR-116 L2466 names it "font size scale")
- h2 "All criteria": the section name in §7.2 item 7 L214 (§11 has no heading string for it)
- column headers "Criterion", "Level", "Conformance level": §2.2 L135 and §7.2 item 7 L214 (no W-string)
- CMP-207 BuildFooter line: version, commit, environment and build time (`15` CMP-207); format and values synthetic

## Fallbacks (5)

- kit choice: the kbd chip is color.surface.raised with a border.hairline color.border.default edge, radius.control, its keys as text (§7.6: the edge is decoration, the key text identifies it)
- fallback: a text node has no underline; the link underline (`15`:258 block, §7.6) is a 1 px color.text.link rule under the link text
- kit choice: numbered stops, tags, outlines, redlines and callouts in color.status.info.default on color.text.inverse are annotation, never product UI
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact)
- kit choice: the shell chrome around SettingsLayout (wordmark, pickers, health chip, rail glyphs, StatusBar items) and every SCR-117 / SCR-119 item this spec does not word are neutral placeholders; only what E47-D13 names is drawn with words

## Sources (1)

- E47-D13.md md5 b8e1bdd1; E47-D13-handoff.md md5 b6857717; 47-conformance-report.md md5 807dc1d0; 47-limitations.json md5 f609cce7; 14-screens-catalogue.md md5 1ca28890 at 4c662fd5b (§0 L74; §H L99)

## Tokens (34)

- type.ui.heading-lg
- color.text.primary
- type.ui.body-strong
- space.stack.sm
- type.ui.body
- space.stack.xs
- color.status.info.strong
- size.icon
- space.inset.sm
- space.inset.md
- color.status.info.subtle
- type.ui.caption
- color.text.secondary
- type.ui.heading-md
- space.stack.md
- type.ui.label
- space.inset.xs
- color.surface.raised
- color.surface.app
- color.border.default
- radius.control
- border.hairline
- color.text.link
- space.button.paddingX
- color.text.inverse
- color.status.info.default
- radius.badge
- color.surface.hover
- color.border.subtle
- color.surface.selected
- space.inset.lg
- type.ui.heading-sm
- color.text.tertiary
- color.surface.canvas
