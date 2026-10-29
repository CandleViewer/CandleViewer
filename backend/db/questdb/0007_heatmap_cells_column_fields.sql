-- QuestDB hot-tier DDL, batch 7 (E21-T02, #605).
-- The heatmap engine's native column (21-database-schema Sec.4.12, 24-internal-schemas Sec.6.1)
-- carries four column-level fields the 0002 `heatmap_cells` table lacks; every row of a column
-- repeats them:
--   estimated           BOOLEAN  the column was built while the book was resyncing
--   samples             INT      the native deadlines the engine met with a book (0 = none)
--   off_window_bid_qty  DOUBLE   resting bid size outside the column's price window
--   off_window_ask_qty  DOUBLE   the same for asks
-- Additive and nullable (C-5.1): a row written before this file reads NULL in each, taken as
-- `estimated = false` with `samples` and the off-window totals unknown. No DEDUP key changes.
-- Plain `ADD COLUMN` (the 0003/0005/0006 form): the `IF NOT EXISTS` variant failed on the CI
-- QuestDB 8.1.1 with "invalid type". The runner's _cv_migrations record makes this file run once.
-- The cold exporter widens the registered Parquet column set for exactly these columns
-- (storage/cold/exporter.py ALLOWED_ADDITIONS, 21-database-schema.md Sec.5.2). Do not hand-edit
-- a column without updating 21-database-schema.md Sec.4.12 in the same PR.
-- Inverse, for an operator (QuestDB batches have no down step), once the code writing these
-- columns is rolled back:
--   ALTER TABLE heatmap_cells DROP COLUMN estimated;
--   ALTER TABLE heatmap_cells DROP COLUMN samples;
--   ALTER TABLE heatmap_cells DROP COLUMN off_window_bid_qty;
--   ALTER TABLE heatmap_cells DROP COLUMN off_window_ask_qty;

ALTER TABLE heatmap_cells ADD COLUMN estimated BOOLEAN;
ALTER TABLE heatmap_cells ADD COLUMN samples INT;
ALTER TABLE heatmap_cells ADD COLUMN off_window_bid_qty DOUBLE;
ALTER TABLE heatmap_cells ADD COLUMN off_window_ask_qty DOUBLE;
