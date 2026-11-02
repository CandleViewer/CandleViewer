-- QuestDB hot-tier DDL, batch 8 (E12, #5396; contract first, C-6.1).
-- Two bar flags for the bars_* family (21-database-schema Sec.4.8, 24-internal-schemas Sec.3.1),
-- the stored twins of 22 `Bar.gap_before` / `Bar.partial` and the 23 Sec.14.3 bar item's:
--   gap_before  BOOLEAN  a gap precedes the bar (tape gap before its first print, 24 Sec.3.3)
--   partial     BOOLEAN  the bar is not built from a complete tape window (24 Sec.3.1)
-- Additive (C-5.1). QuestDB has no NULL BOOLEAN: a row written before this file reads `false` in
-- both, which is the documented default for a bar that predates them. No DEDUP key changes.
-- Plain `ADD COLUMN` (the 0003/0005/0006/0007 form): the `IF NOT EXISTS` variant failed on the
-- CI QuestDB 8.1.1 with "invalid type". The runner's _cv_migrations record makes this file run
-- once. The bars_* tables are not in the cold exporter's table map today; when they join it,
-- these two columns join the bars dataset's registered column set (storage/cold/exporter.py
-- ALLOWED_ADDITIONS, 21-database-schema.md Sec.5.2). Do not hand-edit a column without
-- updating 21-database-schema.md Sec.4.8 in the same PR.
-- Inverse, for an operator (QuestDB batches have no down step), once the code writing these
-- columns is rolled back:
--   ALTER TABLE bars_<family> DROP COLUMN gap_before;
--   ALTER TABLE bars_<family> DROP COLUMN partial;
-- for each family in time, tick, volume, range, renko, delta.

ALTER TABLE bars_time ADD COLUMN gap_before BOOLEAN;
ALTER TABLE bars_time ADD COLUMN partial BOOLEAN;
ALTER TABLE bars_tick ADD COLUMN gap_before BOOLEAN;
ALTER TABLE bars_tick ADD COLUMN partial BOOLEAN;
ALTER TABLE bars_volume ADD COLUMN gap_before BOOLEAN;
ALTER TABLE bars_volume ADD COLUMN partial BOOLEAN;
ALTER TABLE bars_range ADD COLUMN gap_before BOOLEAN;
ALTER TABLE bars_range ADD COLUMN partial BOOLEAN;
ALTER TABLE bars_renko ADD COLUMN gap_before BOOLEAN;
ALTER TABLE bars_renko ADD COLUMN partial BOOLEAN;
ALTER TABLE bars_delta ADD COLUMN gap_before BOOLEAN;
ALTER TABLE bars_delta ADD COLUMN partial BOOLEAN;
