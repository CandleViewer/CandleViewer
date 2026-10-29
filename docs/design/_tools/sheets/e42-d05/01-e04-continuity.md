# E42-D05 / 01 e04-continuity · 1280×800 · dark

File `E42-D05 boards`, page `E42-D05`; export `docs/design/E42/img/E42-D05-01-e04-continuity.png`; sheet `01-e04-continuity.json` (validated); theme dark.

Board 01 of the confirmed ten (plan e42d05-plan.md, main-orchestrator 18:44Z, #960 comment 6477583631). Grid (0, 0); 6000 x 5632 px; 8 frames; footer "page E42-D05 · board 01 · r1".

## Frames

- `HL-2 · 1280×800 [01]` — 1280 x 800 at (80, 80), row 1
- `HL-5 · 1280×800 [01]` — 1280 x 800 at (1440, 80), row 1
- `HL-14 · 1280×800 [01]` — 1280 x 800 at (2800, 80), row 1
- `IL-2 · 1280×800 [01]` — 1280 x 800 at (4160, 80), row 1
- `slot · E04 scr-143-all-green · 1280×800 (empty)` — 1280 x 800 at (80, 960), row 2
- `slot · E04 scr-143-degraded-outage · 1280×800 (empty)` — 1280 x 800 at (1440, 960), row 2
- `slot · E04 scr-143-unreachable-backend · 1280×800 (empty)` — 1280 x 800 at (2800, 960), row 2
- `slot · E04 scr-144-incident-log · 1280×800 (empty)` — 1280 x 800 at (4160, 960), row 2

## Sources

- spec `spec/E42-D05@72ee4fb32.md` (md5 caa2ca66de34951efc989eac875def0a), kit `e42d05kit.py`, plan `spec/e42d05-plan.md`
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
- copy health.label.bars_writer: E42-D05 L707

## Renders

- none (the plan renders boards 02, 03, 04 and 06)

## Validator and size

- `01-e04-continuity.json: 0 errors, 13 warnings, 48 sections, 246842 bytes` (exit 0)
- 48 sections, 1370 nodes (0 instances), largest section 13953 bytes

## E04 twins (row 2) — live step pending

Row 2's four `slot · E04 …` boards are empty, labelled placeholders, not D05 frames: the live Penpot step duplicates E04-D01's scr-143-all-green, scr-143-degraded-outage, scr-143-unreachable-backend and scr-144-incident-log into them, under HL-2, HL-5, HL-14 and IL-2. AC-6's pairwise comparison is not complete until then; the deferral needs the orchestrator's acceptance.
