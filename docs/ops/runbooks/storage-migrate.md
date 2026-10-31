# Runbook — storage migrate step (#3897)

Owner: backend-platform. Code: `services/api/candleviewer/storage/migrate.py`. The API image ships the
QuestDB DDL (`backend/db/questdb/*.sql`) read-only at `/app/backend/db/questdb`. A deploy applies both
schemas in one explicit step before the API starts; the API never applies either at boot
(`20-architecture.md` §6.2). `python -m candleviewer.storage.migrate` runs, in order, and stops at
the first failure:

1. `alembic upgrade head`, in process, on `CV_PG_DSN`.
2. The E07-T03 runner (`run_migrations`) over the shipped DDL, on `CV_QUESTDB_PG`.
3. The drift guard (`assert_no_schema_drift`): each DDL table's live column names must equal the DDL's.

All three run under one Postgres advisory lock named `cv_migrations`, the key the boot runner (not
wired into the API) used, so two runs never overlap: a second one waits up to
`CV_MIGRATION_LOCK_TIMEOUT_S` (300 s), then exits 4. Alembic's connection has a 10 s connect timeout
and gives up on a lock another session holds after that same wait. The step sets both bounds itself:
do not put `connect_timeout` or `options` in the DSN (`CV_PG_OWNER_DSN`, which the step reads as
`CV_PG_DSN`). The lock's connection is asyncpg's, which sends both to the server as settings, not as
libpq options, and a `connect_timeout` there fails the step at the lock (exit 4). A long-running
statement is not cut. Ctrl-C releases the lock while Alembic's worker thread may still be running:
wait for the process to exit before you run the step again.

Exit 0 means all three passed or nothing was left to apply: a second run applies nothing and exits 0.

## Run it

Before the first run on an install that already holds data, read `_cv_migrations` first
(`SELECT filename FROM _cv_migrations`); if that table does not exist, nothing is recorded: no runner
has run on that QuestDB. The step applies each DDL file once, on a QuestDB that does not list it, and
`0004_bars_key_by_index.sql` drops and re-creates the six `bars_*` tables (`bars_time`, `bars_tick`,
`bars_volume`, `bars_range`, `bars_renko`, `bars_delta`). A fresh QuestDB loses nothing. If `0004` is
not listed and those tables hold bar data without `0004`'s columns and upsert keys (tables created by
ILP, for example), take a rebuild plan or a backup first: the rows in them are dropped. A table that
already has both is kept: that is a run that applied `0004` and died before its record (see "After a
crash"). The step also runs on the first `up` that includes `api`, so read `_cv_migrations` first.

Stop the API and every other ILP writer before the first run on an install that has tables: a live
writer can create a table again between a drop and its re-creation. On an install that has tables but
no `_cv_migrations` (the case #3897 came from: ILP created them on first write), drop or rebuild those
tables first. `CREATE TABLE IF NOT EXISTS` leaves the shape ILP inferred (no DEDUP keys) and the drift
guard compares column names only. A plain `ADD COLUMN` of a column that exists on a table lacking its
DDL upsert keys, as a table ILP created does, now stops the run at exit 9, as it stopped at exit 7
before #3093: for the `bars_*` tables that is at `0003`, before `0004` drops them. A keyless table
that lacks the column still reaches `0004`'s drop: the check before the run is yours.

```bash
C="docker compose -f infra/compose/docker-compose.yml"
CV_PG_OWNER_DSN='<the cv_owner DSN>' $C --profile core up -d --build api
```

The step reads `CV_PG_OWNER_DSN` (the owner role, `cv_owner`: `21-database-schema.md` §9.1). Compose
hands it to the `migrate` container as its `CV_PG_DSN`; the `api` service does not take it, and
`CV_PG_DSN` stays the app role's (`cv_app`, which has no DDL privileges). Every `up` that
includes `api` runs the step, so give the owner DSN to each such `up`, and to a `run` of the step,
as a prefix, as above, so the owner login is not left in the shell's environment or in
`infra/compose/.env` for the commands that do not need it: never `export` it and never write it to
`.env`.
The shell also keeps the line you type in its history, so never paste the literal DSN: use
`CV_PG_OWNER_DSN="$(<secret-store read>)"` as the prefix, which reads it from the operator's secret
store, or type the line with a leading space under `HISTCONTROL=ignorespace`. On the dev stack `cv` is
the owner, so `CV_PG_OWNER_DSN` is the same DSN as `CV_PG_DSN`; left unset, compose uses its
placeholder DSN, the login fails (exit 4) and `up` starts no `api`.

`--build` makes the one-shot and the API this checkout's build. Compose reuses an image that exists
(`run` and `up` build only a missing one), so a release that adds a revision or a DDL file could
otherwise run the step from an older build, apply nothing new, exit 0, and then start the new API on
the old schema. `migrate` also has `pull_policy: build`, which makes `up` and `run` rebuild it even
without the flag, and it shares no image tag with `api` (the dev override builds api's `builder`
target); `api` has no such key, so it needs the flag.

`up` starts Postgres and QuestDB if they are down, waits until they are healthy, runs the `migrate`
one-shot and starts `api` once it has exited 0: `api` has
`depends_on: {migrate: {condition: service_completed_successfully}}`, and `migrate` has the profiles
`core` and `migrate`, because compose refuses an `api` that depends on a service of an inactive
profile. The step runs on every `up` that includes `api`, a routine one of a running stack too:
compose starts the exited `migrate` container again, and a run with nothing left to apply exits 0
(the crash window between a file's DDL and its `_cv_migrations` record no longer fails a run, #3093:
see "After a crash"). A failed step stops that `up` (see "Exit status"): `api` is not started, and
an `api` that is already running is left as it is. `restart api` and `up --no-deps api` start `api`
alone and run no step, which is how to start an older image on a schema a newer one migrated: its
step cannot find the database's revision and exits 4.

To run the step alone, as a rehearsal or the first run on a new install, give it the owner DSN the
same way. `run` starts Postgres and QuestDB if they are down, waits until they are healthy and
returns the step's exit status as the shell's:

```bash
CV_PG_OWNER_DSN='<the cv_owner DSN>' $C --profile core run --rm --build migrate
```

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
`questdb_wal_not_applied` warning first. Under `up`, compose reports a failed step as
`service "migrate" didn't complete successfully: exit <n>` (Compose v5) and starts no `api`: `<n>`
is one of the statuses below, and the step's own `exit_code` is in its `storage_migrate_failed` line
in `$C --profile core logs migrate`. `run --rm migrate` returns the status as the shell's exit
status.

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
  already run. A drop in the middle of a DDL file leaves that file's earlier statements applied: the
  retry finishes the file (see "After a crash"). Keep the API and every ILP writer stopped until the
  re-run exits 0. Check `CV_QUESTDB_PG`, its login and `questdb`.
- **7 `DDL_REFUSED`** (`StorageQueryFailed`): QuestDB refused a statement (`sqlstate`). Files before
  it are recorded; statements of the failing file that ran before the refusal stay applied, and a
  re-run skips them (see "After a crash"). A table that ILP created before the first run (the #3897
  deployment) can still be refused: back up, drop those tables and re-run. Otherwise stop, keep the
  API down and escalate.
- **8 `WAL_NOT_APPLIED`** (`StorageWalNotApplied`): QuestDB's apply job did not catch up with a table
  the runner reads before it acts: `_cv_migrations`, or the table of an `ADD COLUMN` or a `DROP TABLE`
  (`table`; `reason`: `timeout` after 30 s, `suspended` or `unexpected_shape`). The statement it waited
  for was not run, and a re-run finishes the file. For `suspended`, fix the cause and run
  `ALTER TABLE <table> RESUME WAL;` (`recorder-rolloff.md`). For `timeout`, check `wal_tables()`, stop
  the API and every other ILP writer or wait for the apply to catch up, then re-run. Keep the API
  and every ILP writer stopped until the re-run exits 0.
- **9 `SCHEMA_DRIFT`** (`StorageSchemaDrift`): a live table's column names differ from its DDL's once
  QuestDB's apply settled (about 5 s); `detail` names the table and the missing and extra columns. The
  runner raises it too (`step` `questdb_ddl`) for an `ADD COLUMN` whose column exists with another
  type (`detail`: `questdb column <table>.<column> is <live type>, the DDL adds <type>`) or on a
  table lacking its DDL upsert keys (ILP's shape; see "Run it"); that file is not recorded. Do not
  start the API on it. ILP creates a table on its first write with inferred column types, the
  failure this step prevents. Escalate with `detail`.

## After a crash

QuestDB has no transactional DDL, so a step that was killed, lost its connection (exit 6) or hit the
60 s statement timeout can stop between a file's statements, or after its last one and before its
`_cv_migrations` record. Run the step again: it finishes that file and exits 0 (#3093). Before an
`ADD COLUMN`, and before a `DROP TABLE` of a table the same file re-creates (`0004`), the runner waits
for that table's WAL apply and reads the live table. A column that is there with the DDL's type is
skipped when the table has the upsert keys its first `CREATE` declares; a table without them (ILP sets
none) stops the run at exit 9, as a table ILP created stopped at exit 7 before #3093: the `bars_*`
tables stop at `0003`, before `0004` drops them. A `DROP TABLE` is
skipped when the table already has every column and upsert key of its re-creation, so the bars written
since are kept; an older table is still dropped and re-created. Each skip is one
`questdb_statement_skipped` line (`filename`, `kind`, `table`, and `column` for an `ADD COLUMN`) and a
file with a skip logs one `questdb_migration_resumed` warning: an earlier run died, find out why.
Neither carries a value. Keep the API and every ILP writer stopped until the re-run exits 0: a writer
that runs first can add a column the file was about to add, which the guard reads as the crash's own
effect.

**Incident note (#3093, P1).** The runner recorded a file only after its last statement and checked
none, so a re-run failed at a plain `ADD COLUMN` (exit 7) and a re-run of `0004` dropped the six
`bars_*` tables first. Found while fixing #3064 (#3077); filed 2026-10-17 as P2, raised to P1 that
day; reproduced on 2026-10-21 on QuestDB 8.1.1, where 10 of 11 sampled crash points failed or lost
rows. No loss is known: this step shipped on 2026-10-21 (#3982) and the rows are derived bars. Its
risk register entry is a bullet of RSK-012 in `32-risk-register.md`.
