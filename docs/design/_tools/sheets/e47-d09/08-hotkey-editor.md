# E47-D09 / 08 hotkey-editor

File `E47-D09 boards`, page `E47-D09`; export `docs/design/E47/img/E47-D09-08-hotkey-editor.png`; sheet `08-hotkey-editor.json` (validated); theme dark.

Board 08 of ten (§0 L75: SCR-113 redlines RL-1 … RL-5 over the as-built editor (§10)). Grid (12000, 3200); 4640 x 1878 px; "page E47-D09 · board 08 · r1".

## Frames

- `hotkeys∕conflict-at-capture · dark`
- `hotkeys∕reserved · dark`
- `hotkeys∕reset-all · dark`
- `hotkeys∕capture · dark`
- `hotkeys∕safety-group · dark`

## Validator and size

- `08-hotkey-editor.json: 0 errors, 6 warnings, 65 sections, 213594 bytes` (exit 0)
- 65 sections, 213594 bytes

## Live checks (8)

- root 'E47-D09 / 08 hotkey-editor' at (12000, 3200): read back the name exactly after the first section call; size 4640 x 1878
- after touchTexts + relayout: the root's h 1878 is the measured max(column end, footer end) + 80 (annotation column estimated 1100 px); read it back
- frame 'hotkeys∕conflict-at-capture · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'hotkeys∕reserved · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'hotkeys∕reset-all · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'hotkeys∕capture · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'hotkeys∕safety-group · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E47/img/E47-D09-08-hotkey-editor.png: every frame is 1280 x 800; record the board id and the PNG size

## Readings (2)

- every SCR-113 frame works on positions.close_all (§9's AC4 command, in the Safety group); the conflict key Ctrl+Shift+A is Global's account picker, the reserved key Ctrl+Shift+I a RES entry
- RL-1's held Save is drawn as an ordinary secondary button (form validity, never T2: no lock, no raised fill); the key field shows aria-invalid as a 2 px color.status.danger.strong edge plus the message's words

## G rows (0)

## C rows (1)

- D09-C16 (§19.1 L409): RL-1

## Spec gaps (0)

## Deviations (0)

## Copy keys (5)

- W-13 (§16 L318, PROPOSED)
- W-12 (§16 L317, PROPOSED)
- W-17 (§16 L322, PROPOSED)
- W-14 (§16 L319, verbatim)
- W-24 (§16 L329, PROPOSED)

## Copy gaps (3)

- SCR-113 words "Hotkeys", "Safety", "Save", "Reset", "Unbind", "Swap", "Reset all", "Import", "Export", "Require a modifier for destructive commands" and the group titles: `14` SCR-113's wireframe and as-built line (`14`:2414-2436), not this spec's
- RL-5's caution note: §10 asks for it in text, not colour; no W-row gives its words, so it is drawn as a warning glyph and placeholder lines (`14` SCR-113's checklist: "trading actions are visually grouped and carry a caution note")
- "Press keys…" in the capturing field: the field's placeholder while it listens (RL-4 gives the spoken W-24 only)

## Fallbacks (3)

- kit choice: numbered stop markers, tags, outlines, arrows and callouts are annotation overlays in color.status.info.default (callouts on color.surface.overlay), never product UI; a callout quotes what is spoken (polite) or what a key does
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items, list rows of SCR-093) drawn as neutral placeholders; only what this spec names is drawn with words

## Sources (1)

- spec docs/design/E47/E47-D09.md md5 690029fa (§0 L75); hand-off docs/design/E47/E47-D09-handoff.md md5 d50c31f7 (§H L105); registry at 4c662fd5b apps/web/src/keymap/keymap.json md5 eb409e85 and apps/web/src/keymap/reserved-keys.json md5 5683c37f; tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (48)

- type.num.xs
- color.text.primary
- space.inset.sm
- color.surface.canvas
- radius.control
- color.status.danger.strong
- border.thick
- border.hairline
- color.focus.ring
- border.focus
- type.ui.body-strong
- space.inset.xs
- space.button.paddingX
- color.action.secondary.default
- color.text.secondary
- type.ui.body
- type.ui.caption
- space.inset.md
- color.status.warning.strong
- size.icon
- color.surface.sunken
- type.ui.label
- space.stack.xs
- color.surface.overlay
- color.status.info.default
- type.ui.heading-lg
- color.border.default
- color.border.strong
- color.surface.raised
- color.text.on-action
- size.icon.sm
- color.action.primary.default
- color.surface.hover
- type.ui.heading-sm
- space.stack.md
- space.inset.xl
- color.text.link
- color.border.selected
- color.border.subtle
- color.surface.app
- color.surface.selected
- color.env.live
- color.status.danger.subtle
- space.inset.lg
- color.status.success.strong
- color.status.info.strong
- color.text.tertiary
- space.stack.sm
