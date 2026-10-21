# Runbook — storage migrate step (#3897)

Owner: backend-platform. Code: `services/api/candleviewer/storage/migrate.py`. The API image ships the
QuestDB DDL (`backend/db/questdb/*.sql`) read-only at `/app/backend/db/questdb`. A deploy applies both
schemas in one explicit step before the API starts; the API never applies either at boot
(`20-architecture.md` §6.2). `python -m candleviewer.storage.migrate` runs, in order, and stops at
the first failure:

1. `alembic upgrade head`, in process, on `CV_PG_DSN`.
2. The E07-T03 runner (`run_migrations`) over the shipped DDL, on `CV_QUESTDB_PG`.
3. The drift guard (`assert_no_schema_drift`): each DDL table's live column names must equal the DDL's.

All three run under one Postgres advisory lock (`cv_migrations`, the key the retired boot runner
used), so two runs never overlap: a second one waits up to `CV_MIGRATION_LOCK_TIMEOUT_S` (300 s), then
exits 4. Alembic's connection has a 10 s connect timeout and gives up on a lock another session holds
after that same wait (a `connect_timeout` or `options` parameter in the DSN wins). A long-running
statement is not cut.

Exit 0 means all three passed or nothing was left to apply: a second run applies nothing and exits 0.

## Run it

Before the first run on an install that already holds data, read `_cv_migrations` first
(`SELECT filename FROM _cv_migrations`); if that table does not exist, nothing is recorded: no runner
has run on that QuestDB. The step applies each DDL file once, on a QuestDB that does not list it, and
`0004_bars_key_by_index.sql` drops and re-creates the six `bars_*` tables (`bars_time`, `bars_tick`,
`bars_volume`, `bars_range`, `bars_renko`, `bars_delta`). A fresh QuestDB loses nothing. If `0004` is
not listed and those tables hold bar data (tables created by ILP, for example), take a rebuild plan or
a backup first: the rows in them are dropped. The step has no guard for this; the check is yours.

Stop the API and every other ILP writer before the first run on an install that has tables: a live
writer can create a table again between a drop and its re-creation. On an install that has tables but
no `_cv_migrations` (the case #3897 came from: ILP created them on first write), drop or rebuild those
tables first. `CREATE TABLE IF NOT EXISTS` leaves the shape ILP inferred (no DEDUP keys), the drift
guard compares column names only, and a plain `ADD COLUMN` fails where ILP already added the column
(exit 7).

```bash
C="docker compose -f infra/compose/docker-compose.yml"
CV_PG_OWNER_DSN='<the cv_owner DSN>' $C --profile core --profile migrate run --rm --build migrate \
  && $C --profile core up -d --build api
```

The step reads `CV_PG_OWNER_DSN` (the owner role, `cv_owner`: `21-database-schema.md` §9.1). Compose
hands it to the `migrate` container as its `CV_PG_DSN`; the `api` service does not take it, and
`CV_PG_DSN` stays the app role's (`cv_app`, which has no DDL privileges). Give the owner DSN to that
one command, as above, so the owner login is not left in the shell's environment or in
`infra/compose/.env` for the commands that follow: never `export` it and never write it to `.env`. On
the dev stack `cv` is the owner, so `CV_PG_OWNER_DSN` is the same DSN as `CV_PG_DSN`; left unset,
compose uses its placeholder DSN and the login fails (exit 4).

`--build` makes the one-shot and the API this checkout's build. Compose reuses an image that exists
(`run` and `up` build only a missing one), so a release that adds a revision or a DDL file could
otherwise run the step from an older build, apply nothing new, exit 0, and then start the new API on
the old schema. `migrate` also has `pull_policy: build`, which makes `run` rebuild it even without
the flag, and it shares no image tag with `api` (the dev override builds api's `builder` target);
`api` has no such key, so it needs the flag.

`run` starts Postgres and QuestDB if they are down, waits until they are healthy and returns the
step's exit status, so `&&` starts the API on 0 only. `migrate` is opt-in (profile `migrate`) and not
a dependency of `api`: an automated apply waits for #3093 (open), the crash window between a file's
DDL and its `_cv_migrations` record. Until then a person, or a deploy script that stops on a
non-zero exit, runs it. To automate it later, `api` gets
`depends_on: {migrate: {condition: service_completed_successfully}}` and `migrate` the profiles
`["core", "migrate"]`, together: compose refuses an `api` that depends on a service of an inactive
profile.

The step also needs `CV_QUESTDB_PG`, plus `CV_QUESTDB_PG_USER` and `CV_QUESTDB_PG_PASSWORD` if
QuestDB's login is not the default (compose passes those two to neither `migrate` nor `api` today).
From a checkout, in `services/api`, the step reads `CV_PG_DSN` itself (`CV_PG_OWNER_DSN` is the compose
name), so give it the owner DSN for that one command:
`CV_PG_DSN=<the cv_owner DSN> uv run python -m candleviewer.storage.migrate --ddl-dir ../../backend/db/questdb`

## Exit status

A failure is one JSON line, `storage_migrate_failed`: `step` (`ddl_files`, `pg_lock`, `alembic`,
`questdb_ddl` or `drift_guard`), `error` (the class in snake_case, as the log redaction replaces a run
of 18 to 36 letters as an API key), `code` (the typed error's stable code), `exit_code`, `ddl_dir` and
the typed error's own fields. It holds no DSN or driver message. Exit 8 also logs the runner's own
`questdb_wal_not_applied` warning first.

- **0 `OK`**: done; `storage_migrate_done` holds `questdb_files_applied`.
- **1 `UNEXPECTED`**: a refused setting (a traceback names it) or an error with no class here (its
  class is in `error`). Fix the cause and re-run. Exit 2 is bad arguments.
- **4 `POSTGRES_FAILED`**: the migration lock was not got in time (`migration_lock_timeout`: another
  run is in progress or hung; find it before running again), the connection failed, or
  `alembic upgrade head` failed. The alembic lines above name the revision; `error` is the driver's
  class (`operational_error`: Postgres unreachable, the login refused or a lock wait that ran out).
- **5 `DDL_NOT_FOUND`** (`StorageDdlNotFound`): `ddl_dir` holds no `.sql` file: an image built
  without `backend/db/questdb`, or a wrong `--ddl-dir`. Nothing was applied, Postgres included.
- **6 `QUESTDB_UNAVAILABLE`** (`StorageTierUnavailable`): QuestDB refused the connection or the login,
  dropped it (SQLSTATE class 08, or a connection already closed) or stopped answering. Alembic has
  already run. A drop in the middle of a DDL file leaves that file's earlier statements applied, so the
  retry can end at exit 7: then stop and escalate. Check `CV_QUESTDB_PG`, its login and `questdb`.
- **7 `DDL_REFUSED`** (`StorageQueryFailed`): QuestDB refused a statement (`sqlstate`). Files before
  it are recorded; statements of the failing file that ran before the refusal stay applied, so a
  re-run can refuse a plain `ADD COLUMN` as existing. The same follows a run killed between a file's
  DDL and its record (#3093), and a table that ILP created before the first run (the #3897
  deployment): back up, drop those tables and re-run. Otherwise stop, keep the API down and escalate.
- **8 `WAL_NOT_APPLIED`** (`StorageWalNotApplied`): QuestDB's apply job did not catch up with
  `_cv_migrations` (`reason`: `timeout` after 30 s, `suspended` or `unexpected_shape`). For
  `suspended`, fix the cause and run `ALTER TABLE _cv_migrations RESUME WAL;` (`recorder-rolloff.md`).
- **9 `SCHEMA_DRIFT`** (`StorageSchemaDrift`): a live table's column names differ from its DDL's once
  QuestDB's apply settled (about 5 s); `detail` names the table and the missing and extra columns. Do
  not start the API on it. ILP creates a table on its first write with inferred column types, the
  failure this step prevents. Escalate with `detail`.
