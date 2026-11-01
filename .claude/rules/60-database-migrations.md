---
description: Database and storage migration rules - Alembic additive/reversible/one-per-PR/immutable, QuestDB and Parquet layouts.
---

# Database migrations and storage layouts

Source: `CONSTITUTION.md` §5 (C-5.1 to C-5.9), §9 #17; `docs/plan/21-database-schema.md`; ADR-0003 (storage tiers).

## Alembic (Postgres)

- **Additive first (C-5.1):** add tables/columns/indexes. Destructive changes use expand -> migrate -> contract
  across separate releases; never drop/rename in the same release as the code change.
- **Reversible (C-5.2):** every revision has a tested `downgrade()`. An impossible downgrade needs an ADR note
  and an explicit `raise` with a reason.
- **One revision per PR (C-5.3).** Rebase onto `main` and re-parent (`down_revision`) if another migration landed;
  CI enforces a single head.
- **Never edit an applied migration (C-5.4).** Once merged to `main` the file is immutable; fix forward with a new
  revision. A project hook blocks edits to existing files under the migrations `versions/` directory.
- **Round-trip (C-5.5):** upgrade -> downgrade -> upgrade on empty and seeded DB (CI `migrations`). Run locally:
  `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.
- **No long locks (C-5.6):** `CREATE INDEX CONCURRENTLY`, add nullable column then backfill in batches, then constrain.
- **Audit tables (C-5.7):** no `UPDATE`/`DELETE` grants, no dropping audit history.
- **Classification (C-5.9):** columns that may hold credentials, tokens or PII are declared in the schema doc
  with their class and protection; secrets columns hold only envelope-encrypted blobs.
- Autogenerate, then **review by hand**; name: `alembic revision -m "<imperative summary>"`.
- Update `docs/plan/21-database-schema.md` in the same PR.

## QuestDB and Parquet (C-5.8)

- Time-series table definitions and Parquet partition layouts live in the storage schemas location named by
  C-5.8, versioned, with a migration note in the PR.
- QuestDB: designated timestamp = exchange event time (UTC, micro/ms), `PARTITION BY DAY`, symbols as `SYMBOL`,
  dedup keys declared for idempotent re-ingest.
- Parquet: hive-style partitions `env=/symbol=/date=`; schema changes are additive (new nullable columns);
  never rewrite historical partitions in place.
- Recorder output must stay replayable by the current code (C-2.15); a layout change ships a reader for the old layout.
- **Applied QuestDB DDL files are immutable (C-5.4).** `backend/db/questdb/NNNN_*.sql` is never edited, deleted
  or renamed once on `main`; fix forward with a new file. `backend/db/questdb/lockfile.json` pins each file's
  bytes, and CI (`migrations`, `tools/ci/verify_questdb_ddl_lock.py`) also compares the tree with the merge
  base. A new file adds its entry in the same PR: `sha256sum` the file; nothing rewrites an entry. The edit
  hook blocks an Edit or Write of an applied file; a shell edit (`sed -i`) never reaches it, so CI is the gate.
