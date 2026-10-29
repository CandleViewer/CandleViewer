# E42-D05 / 03 scr143-144-populated · 1280×800+2560×1440 · dark

File `E42-D05 boards`, page `E42-D05`; export `docs/design/E42/img/E42-D05-03-scr143-144-populated.png`; sheet `03-scr143-144-populated.json` (validated); theme dark.

Board 03 of the confirmed ten (plan e42d05-plan.md, main-orchestrator 18:44Z, #960 comment 6477583631). Grid (12000, 0); 5920 x 4528 px; 6 frames; footer "page E42-D05 · board 03 · r1".

## Frames

- `HL-2 · 1280×800 [06]` — 1280 x 800 at (80, 80), row 1
- `HL-2 · 2560×1440 [06]` — 2560 x 1440 at (1440, 80), row 1
- `HL-5 · 1280×800 [09]` — 1280 x 800 at (4080, 80), row 1
- `HL-6 · 1280×800 [10]` — 1280 x 800 at (80, 1600), row 2
- `IL-2 · 1280×800 [24]` — 1280 x 800 at (1440, 1600), row 2
- `IL-2 · 2560×1440 [24]` — 2560 x 1440 at (2800, 1600), row 2

## Sources

- spec `spec/E42-D05@72ee4fb32.md` (md5 caa2ca66de34951efc989eac875def0a), kit `e42d05kit.py`, plan `spec/e42d05-plan.md`
- copy health.client_none: E42-D05 L707
- HL-2 all healthy: E42-D05 L304
- SCR-143 anatomy: E42-D05 §5 L249-261
- spec §15 L626-680 (tokens, contrast, colour vision)
- spec §14 L604-624 (copy deck)
- copy health.reread: E42-D05 L707
- copy health.overall: E42-D05 L707
- copy health.incidents: E42-D05 L707
- copy health.label.bybit_public_ws: E42-D05 L707
- copy health.probe: E42-D05 L707
- copy tile.asof: E42-D03 §14 (inherited, §15 L715)
- copy health.label.bybit_private_ws: E42-D05 L707
- copy health.label.bybit_rest: E42-D05 L707
- copy health.label.recorder: E42-D05 L707
- copy health.label.postgres: E42-D05 L707
- copy health.label.questdb: E42-D05 L707
- copy health.label.parquet_store: E42-D05 L707
- copy health.label.hot_tier_write_behind: E42-D05 L707
- copy health.label.rule_engine: E42-D05 L707
- copy health.label.oms: E42-D05 L707
- copy health.label.ingestion: E42-D05 L707
- copy health.label.disk: E42-D05 L707
- copy health.label.secrets: E42-D05 L707
- copy health.label.bars: E42-D05 L707

## Renders

- ★ `E42-D05-03-scr143-144-populated-greyscale.png` and `E42-D05-03-scr143-144-populated-deuteranopia.png`

## Validator and size

- `03-scr143-144-populated.json: 0 errors, 19 warnings, 63 sections, 315391 bytes` (exit 0)
- 63 sections, 1822 nodes (0 instances), largest section 13976 bytes

## Review fixes (r2, board-local)

- IL-2 1280 + 2560: the break_glass and recorder rows draw Severity as word + octagon (DJ: §1 L86-88 names none; SCR-144 lists error and critical only, `incident.scope` §15 L709): break_glass critical (a safety row, D03 OV-10), recorder error.
- IL-2: the break_glass row's Subsystem is drawn as text `break_glass` (its row identity).
- HL-6 (and every degraded tile on this board): triangle + the plain word "degraded" on the status line, the worked-example detail on its own line beneath (HL-3 row L305); `tile.degraded` "Degraded — {detail}" split across the two lines. Other boards' degraded tiles still draw the joined string (kit unchanged).
