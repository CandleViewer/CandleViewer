# E19-D01 / 09 protocol-table-alternative

File `E19-D01 boards`, page `E19-D01`; export `docs/design/research/img/E19-D01-09-protocol-table-alternative.png`; sheet `09-protocol-table-alternative.json` (validated); theme dark.

Board 09 of nine (memo §0 L43: §10 the session plan and the table-alternative columns of A-6). Grid (21000, 5200); 2080 x 2956 px; "page E19-D01 · board 09 · r1".

## Frames

- `protocol∕tasks` (`protocol/tasks`)
- `protocol∕rotation-and-rule` (`protocol/rotation-and-rule`)
- `protocol∕table-alternative` (`protocol/table-alternative`)

## Validator and size

- `09-protocol-table-alternative.json: 0 errors, 1 warnings, 54 sections, 167925 bytes` (exit 0)
- 54 sections, 1129 shapes, 167925 bytes

## Live checks (6)

- root 'E19-D01 / 09 protocol-table-alternative' at (21000, 5200): read back the name exactly after the first section call; size 2080 x 2956
- after touchTexts + relayout: the annotation column (estimated 715 px with 15 % slack) ends inside the root (h 2956); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'protocol∕tasks': read back 1440 x 648 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'protocol∕rotation-and-rule': read back 1440 x 752 at (80, 864); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'protocol∕table-alternative': read back 1440 x 1088 at (80, 1724); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E19-D01-09-protocol-table-alternative.png: record the board id and the PNG size

## Derivations (2)

- §10.3 budgets: T0..T11 sum to 38 min; + setup 3 + debrief 2 = 43 min (the memo's totals agree)
- table alternative: session 30 Oct as of 14:30 UTC; volume BTC on the 0.001 step; delta and TPO over recorded trades; % of POC floored; nodes HVN 63,205.0, LVN 63,150.0; naked POCs lie outside this session's range (that is what naked means), so the column reads — here; no approximated portion on 30 Oct, so estimated reads —

## Decisions (0)

## Spec gaps (1)

- A-6 names the six columns but not their cell words: 'single print', 'HVN' / 'LVN', the developing words and '—' are kit readings (E19-D06 owns the table)

## Deviations (0)

## Copy keys (1)

- memo L56: "Developing · as of HH:MM UTC" (placeholders filled from the world)

## Copy gaps (1)

- "Profile table, session 30 Oct, Developing · as of 14:30 UTC, 35 rows": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy) — the table's accessible caption

## Fallbacks (1)

- kit choice: a string a screen reader hears (an accessible name, the DOM mirror) is drawn as caption text in a 'dashed · ' outline

## Sources (3)

- spec (memo) docs/design/research/e19-profiles.md md5 d4e666a3f87a41724547a89a1615d062 at the boards PR (§0 drawn, §13 As built) (§0 L43)
- docs/plan/05-accessibility-standard.md at ca49e693a md5 16c60e646337d48dac83c9fb46f8a239 (`05` §6 profile table: the columns A-6 extends)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (23)

- type.ui.caption
- color.text.secondary
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- color.border.default
- color.text.primary
- color.surface.canvas
- space.stack.xs
- type.ui.body
- space.inset.md
- space.stack.sm
- radius.card
- border.hairline
- type.ui.label
- space.stack.lg
- space.inset.xl
- space.inset.lg
- color.surface.selected
- color.border.strong
- radius.control
- type.ui.heading-sm
