# E47-D09 / 05 palette

File `E47-D09 boards`, page `E47-D09`; export `docs/design/E47/img/E47-D09-05-palette.png`; sheet `05-palette.json` (validated); theme dark.

Board 05 of ten (§0 L72: SCR-012 deltas: the binding column with "unbound", an invalid-here row, a T2 row, no match (§8)). Grid (24000, 0); 3280 x 1880 px; "page E47-D09 · board 05 · r1".

## Frames

- `palette∕unbound · dark`
- `palette∕invalid-here · dark`
- `palette∕t2 · dark`
- `palette∕no-match · dark`

## Validator and size

- `05-palette.json: 0 errors, 5 warnings, 33 sections, 102379 bytes` (exit 0)
- 33 sections, 102379 bytes

## Live checks (11)

- modal: re-centre 'CMP-059 command palette' after relayout (estimated 640 x 189 px)
- modal: re-centre 'CMP-059 command palette' after relayout (estimated 640 x 269 px)
- modal: re-centre 'CMP-059 command palette' after relayout (estimated 640 x 221 px)
- modal: re-centre 'CMP-059 command palette' after relayout (estimated 640 x 163 px)
- root 'E47-D09 / 05 palette' at (24000, 0): read back the name exactly after the first section call; size 3280 x 1880
- after touchTexts + relayout: the annotation column (estimated 1480 px) ends inside the root (h 1880); set the root's h to max(column end, footer end) + 80
- frame 'palette∕unbound · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'palette∕invalid-here · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'palette∕t2 · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'palette∕no-match · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E47/img/E47-D09-05-palette.png: every frame is 1280 x 800; record the board id and the PNG size

## Readings (4)

- W-9 is drawn in PCOPY:39's shipped form with the query in curly quotes ("No command or symbol matches “flatten”"), the verbatim fragment §16 checks
- every registry command sits under E10-D03's "Action" group (the five groups Navigate · Panel · Symbol · Action · Setting; the registry carries no group field)
- valid here = the command's context is active in SCR-020's trading workspace (Global, Workspace, Chart, DOM, Ticket, Positions) and its validWhen holds; Replay rows are the invalid-here example
- the synthetic keymap profile: positions.close_all → Ctrl+Shift+F, ticket.reduce_only → Alt+R, replay.bookmark → Ctrl+B (QA-3's three remaps), dom.centre_mark unbound (no default is unbound)

## G rows (2)

- D09-G5 (§19.2 L421): CMP-059 has no per-command field for where an invalid-here command works (owner E10-S05, the palette host)
- D09-G1 (§19.2 L417): no flatten-all command is registered, though 05:64 and the TopBar name one (owner E47-S08, the registry rows)

## C rows (3)

- D09-C14 (§19.1 L407): every command listed, "unbound" shown; D09-A11, D09-A16 to E10-S05
- D09-C9 (§19.1 L402): E09-D09 governs: T2 listed, T3 absent (§12)
- D09-C2 (§19.1 L395): AC4 traced on positions.close_all; D09-G1

## Spec gaps (0)

## Deviations (0)

## Copy keys (4)

- W-7 (§16 L312, verbatim)
- W-8 (§16 L313, PROPOSED state key keymap.not_here; owner E47-S08, D09-A18)
- W-11 (§16 L316, verbatim)
- W-9 (§16 L314, verbatim)

## Copy gaps (2)

- "Your role can't change positions.": E09-D09 §3.1 rbac.permission "Your role can't {verb}." (D09E09:89) with E10-D03 §6.1's verb for the positions commands (D03E10:281); §16 has no row for it
- the no-match suggestion "Try fewer letters, or use the nav rail.": the shipped palette copy (PCOPY:40, read at 73bfdb08a); §8 says "W-9 and a suggestion" (D03E10:281) without its words

## Fallbacks (5)

- kit choice: CMP-022 Kbd drawn as a pill (color.surface.raised, color.border.default hairline, radius.control, type.num.xs in color.text.primary); a pointer chord reads as its words
- kit choice: numbered stop markers, tags, outlines, arrows and callouts are annotation overlays in color.status.info.default (callouts on color.surface.overlay), never product UI; a callout quotes what is spoken (polite) or what a key does
- fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); SCR-012's rows 32 px (E10-D03 §6.1, D03E10:281: 32 compact, 40 comfortable); the shell bars keep E10's 48 px TopBar
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items, list rows of SCR-093) drawn as neutral placeholders; only what this spec names is drawn with words

## Sources (1)

- spec docs/design/E47/E47-D09.md md5 3f1952f3 (§0 L72); hand-off docs/design/E47/E47-D09-handoff.md md5 97611aba (§H L105); registry apps/web/src/keymap/keymap.json md5 eb409e85 and apps/web/src/keymap/reserved-keys.json md5 5683c37f; tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; read at 260bb0caf

## Tokens (39)

- type.ui.body
- color.text.primary
- space.stack.xs
- color.text.secondary
- space.inset.sm
- color.surface.selected
- type.num.xs
- space.inset.xs
- radius.control
- color.surface.raised
- color.border.default
- border.hairline
- type.ui.caption
- size.icon
- color.surface.canvas
- color.focus.ring
- border.focus
- color.text.tertiary
- space.stack.sm
- space.inset.md
- color.surface.overlay
- radius.dialog
- type.ui.label
- color.status.info.default
- border.thick
- opacity.scrim
- color.surface.sunken
- type.ui.body-strong
- color.surface.hover
- color.surface.app
- color.border.subtle
- color.env.live
- space.button.paddingX
- color.status.danger.subtle
- color.status.danger.strong
- space.inset.lg
- color.status.warning.strong
- color.text.inverse
- type.ui.heading-sm
