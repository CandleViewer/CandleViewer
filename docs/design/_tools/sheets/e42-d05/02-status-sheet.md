# E42-D05 / 02 status-sheet · 1280×800 · dark

File `E42-D05 boards`, page `E42-D05`; export `docs/design/E42/img/E42-D05-02-status-sheet.png`; sheet `02-status-sheet.json` (validated); theme dark.

Board 02 of the confirmed ten (plan e42d05-plan.md, main-orchestrator 18:44Z, #960 comment 6477583631). Grid (6000, 0); 6000 x 4320 px; 4 frames; footer "page E42-D05 · board 02 · r1".

## Frames

- `status sheet · dark · 1280×800 [02]` — 1280 x 800 at (80, 80), row 1
- `status sheet · light · 1280×800 [02]` — 1280 x 800 at (1440, 80), row 1
- `status sheet · hc · 1280×800 [02]` — 1280 x 800 at (2800, 80), row 1
- `status sheet · forced colours · 1280×800 [04]` — 1280 x 800 at (4160, 80), row 1

## Sources

- spec `spec/E42-D05@72ee4fb32.md` (md5 caa2ca66de34951efc989eac875def0a), kit `e42d05kit.py`, plan `spec/e42d05-plan.md`
- status sheet: E42-D05 §16 L720-751; D2 L115
- copy health.not_deployed: E42-D05 L707
- copy tile.stale: E42-D03 §14 (inherited, §15 L715)
- copy backup.status.verified: E42-D05 L710
- copy backup.status.ok: E42-D05 L710
- copy backup.status.failed: E42-D05 L710
- copy backup.error.checksum_mismatch: E42-D05 L710
- copy backup.status.running: E42-D05 L710
- copy backup.running: E42-D05 L710
- copy backup.status.restored: E42-D05 L710
- copy backup.status.deleted: E42-D05 L710
- copy backup.status.not_encrypted: E42-D05 L710
- copy machine.current: E42-D05 L713
- copy machine.latched: E42-D05 L713
- copy backup.run.title: E42-D05 L710
- T2: E42-D05 §4.1 L182-212
- copy admin.backup_running: E42-D05 L714
- copy admin.backup_not_usable: E42-D05 L714
- forced colours: E42-D05 §4.3 L224-231
- copy health.label.bybit_public_ws: E42-D05 L707
- copy health.probe: E42-D05 L707
- copy tile.asof: E42-D03 §14 (inherited, §15 L715)
- copy health.label.bybit_private_ws: E42-D05 L707
- copy tile.degraded: E42-D03 §14 (inherited, §15 L715)

## Renders

- ★ `E42-D05-02-status-sheet-greyscale.png` and `E42-D05-02-status-sheet-deuteranopia.png`

## Validator and size

- `02-status-sheet.json: 0 errors, 7 warnings, 14 sections, 111412 bytes` (exit 0)
- 14 sections, 685 nodes (0 instances), largest section 12582 bytes

## Ambiguities

- §4.3 L230 puts the forced-colours inset on board 04; the confirmed plan moves it to board 02's fourth column.
- Forced colours have no cvsheet token theme: Canvas / CanvasText / LinkText / Highlight / HighlightText are stand-ins (FALLBACKS['FC']); light and hc themes switch at export, so the three columns share one construction.
- The 3 px current-state border is border.thick + border.hairline nested; incident statuses beyond §1 (chain break open, break-glass acknowledged) are kit judgements.
- The status sheet has no state row: roles, keyboard, announcement and events read 'none / see the state boards'.
- Light and hc groups: copy keys and tokens are the dark frame's (same construction), stated as such.
- Board labels (deliberate, not spec copy): the crop labels 'HL-6 · forced-colors: active', 'RW-3 · …', 'WZ-5 · …'. The old visible 'Theme column: …' line is gone; each column's theme is in the frame name and note.
- Forced-colours crops are generator-local (fc_column in this file replaces K.fc_column; the kit is unchanged) and sized to their estimated content (no clipped text): HL-6 crop = the frame's first tile row (bybit_public_ws healthy, bybit_private_ws degraded, bybit_rest down); the HL-6 'warning' (disk) and 'Not built yet' (bars_writer) tiles and the healthy tiles below are omitted (drawn on board 03, HL-6 at 1280).
- RW-3 crop: the 6-step stepper plus the step-2 h2; the §8.2 impact lines and scope picker are omitted (board 06). Step 1 reads 'Done 2026-10-22': §8 names no restore step dates, so the worked example's date is used.
- WZ-5 crop: stepper steps 1-6 of 8 (7 Limits, 8 Invite: Not started, omitted). Step 3 is the one aria-current step (status 'Blocked until 2026-10-24 09:15 UTC'); step 4 reads 'Not started' (the spec leaves step 4's status open; D27 allows one current step). At the 352 px crop body width the exact time sits on its own line under the reason.
