-- QuestDB hot-tier DDL, batch 6 (E26-T03, #626).
-- A replay re-emits a recorded book event field-identical (24-internal-schemas Sec.13.7), so the
-- two event fields the 0001 book tables lack are recorded from now on rather than derived:
--   prev_update_id  LONG       orderbook_deltas: BookDelta.prev_update_id, the update id the
--                              delta follows
--   ts_match        TIMESTAMP  orderbook_deltas and orderbook_snapshots: Bybit `cts`, the
--                              matching-engine time, in us
-- Additive and nullable (C-5.1): a row written before this file reads NULL in both, and the
-- replay derives the value for it as Sec.13.7 tables. No DEDUP key changes. Plain `ADD COLUMN`
-- (the 0003/0005 form): the `IF NOT EXISTS` variant failed on the CI QuestDB 8.1.1 with "invalid
-- type". The runner's _cv_migrations record makes this file run once. The cold exporter widens
-- the registered Parquet column sets for exactly these columns (storage/cold/exporter.py
-- ALLOWED_ADDITIONS, 21-database-schema.md Sec.5.2). Do not hand-edit a column without updating
-- 21-database-schema.md Sec.4.2/4.3 in the same PR.
-- Inverse, for an operator (QuestDB batches have no down step), once the code writing these
-- columns is rolled back:
--   ALTER TABLE orderbook_deltas DROP COLUMN prev_update_id;
--   ALTER TABLE orderbook_deltas DROP COLUMN ts_match;
--   ALTER TABLE orderbook_snapshots DROP COLUMN ts_match;

ALTER TABLE orderbook_deltas ADD COLUMN prev_update_id LONG;
ALTER TABLE orderbook_deltas ADD COLUMN ts_match TIMESTAMP;
ALTER TABLE orderbook_snapshots ADD COLUMN ts_match TIMESTAMP;
