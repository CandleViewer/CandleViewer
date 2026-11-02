-- infra/scripts/pg_bootstrap.sql — E07-T02
--
-- Idempotent cluster/role bootstrap for the Postgres relational tier
-- (`docs/plan/21-database-schema.md` Sec.1.1). Creates the three roles the
-- rest of the schema assumes exist (and the backup sidecar's two, below) — `cv_owner` (DDL, runs migrations),
-- `cv_app` (DML only, no DDL — the runtime role every request handler
-- connects as), `cv_ro` (read-only, the only role the DuckDB `postgres`
-- attachment in Sec.5.5 may use) — plus the default-privilege grants that
-- make every *future* table automatically visible to `cv_app`/`cv_ro`
-- without a per-migration grant statement.
--
-- Run as a Postgres superuser (`psql -v ON_ERROR_STOP=1 -f
-- infra/scripts/pg_bootstrap.sql`), with passwords supplied as `-v`
-- overrides: `-v owner_pw='...' -v app_pw='...' -v ro_pw='...'`, and
-- optionally `-v backup_pw='...' -v restore_pw='...'` for the backup roles
-- (C-12.2/SR-120..124 — never a value committed to this file). The `\if
-- :{?owner_pw}` guards below are pure psql variable-existence checks (no
-- backticks, no shell command substitution), so this parses and runs the
-- same whether invoked interactively or non-interactively via `psql -f`
-- (bug #1556 CI failure: backtick `\set var `echo ...`` substitution does
-- not reliably reach the server the same way across invocation modes, and
-- unconditionally overwrote any `-v`-supplied value). This script **fails
-- closed** (C-12.2): if a caller omits an override, there is no weak
-- fallback password — the block below forces a SQL error, which aborts the
-- run under the required `-v ON_ERROR_STOP=1` invocation instead of silently
-- creating `cv_owner`/`cv_app`/`cv_ro` with a guessable password. Production
-- values are injected by the deploy pipeline's secret store as `-v`
-- overrides; local/dev callers must pass their own `-v owner_pw=...` (see
-- `infra/compose/.env.example` for the dev-only values to use, never
-- committed here).
--
-- Safe to re-run: every statement below is guarded so a second invocation
-- against an already-bootstrapped cluster is a no-op, not an error.

\if :{?owner_pw}
\else
  \warn 'pg_bootstrap.sql: owner_pw not supplied via -v — refusing to bootstrap with a default password (C-12.2)'
  SELECT 1 / 0;
\endif
\if :{?app_pw}
\else
  \warn 'pg_bootstrap.sql: app_pw not supplied via -v — refusing to bootstrap with a default password (C-12.2)'
  SELECT 1 / 0;
\endif
\if :{?ro_pw}
\else
  \warn 'pg_bootstrap.sql: ro_pw not supplied via -v — refusing to bootstrap with a default password (C-12.2)'
  SELECT 1 / 0;
\endif

-- NOTE: role creation is expressed as three `SELECT ... \gexec` statements
-- rather than a single `DO $$ ... $$` block. psql's `:'var'` interpolation
-- is a client-side lexer pass that does not descend into dollar-quoted
-- string bodies, so `PASSWORD :'owner_pw'` inside `DO $$ ... $$` is sent to
-- the server byte-for-byte (including the literal colon), which the server
-- then rejects with `syntax error at or near ":"` (bug #1556 CI failure).
-- `\gexec` statements are plain top-level SQL, not dollar-quoted, so the
-- substitution happens as intended before the generated `CREATE ROLE` text
-- is sent back to the server for execution.
SELECT format('CREATE ROLE cv_owner LOGIN PASSWORD %L', :'owner_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_owner')
\gexec

SELECT format('CREATE ROLE cv_app LOGIN PASSWORD %L', :'app_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app')
\gexec

SELECT format('CREATE ROLE cv_ro LOGIN PASSWORD %L', :'ro_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_ro')
\gexec

-- The backup sidecar's two roles (ADR-0041 section 1, `21-database-schema.md`
-- Sec.1.1 "Backup roles"); the API never logs in as either. Their grants are
-- revision `0066_backup_role_grants`'s, which needs both to exist: a
-- migration runs as `cv_owner`, which can neither create a role nor make
-- one a member of itself.
--   * `cv_backup` runs `pg_dump`, read-only. It is created `LOGIN` with the
--     password `-v backup_pw=...` supplies; without one it is created
--     `NOLOGIN` with no password, so it exists for the grants and nothing can
--     log in as it (fail closed, C-12.2: no default password).
--   * `cv_restore` runs restore jobs only, with the owner's rights through
--     its membership in `cv_owner`. It is always created `NOLOGIN`, with the
--     password `-v restore_pw=...` supplies, if any; the Owner's host-side
--     step for one restore job enables its login `VALID UNTIL` the job's
--     deadline, and the runbook's closing step sets it `NOLOGIN` again.
-- An existing role is left as it is, password and login included.
\if :{?backup_pw}
SELECT format('CREATE ROLE cv_backup LOGIN PASSWORD %L', :'backup_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_backup')
\gexec
\else
SELECT 'CREATE ROLE cv_backup NOLOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_backup')
\gexec
\endif

\if :{?restore_pw}
SELECT format('CREATE ROLE cv_restore NOLOGIN PASSWORD %L', :'restore_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_restore')
\gexec
\else
SELECT 'CREATE ROLE cv_restore NOLOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_restore')
\gexec
\endif

GRANT cv_owner TO cv_restore;

SELECT 'CREATE DATABASE candleviewer OWNER cv_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'candleviewer')
\gexec

-- If `candleviewer` already existed (e.g. created by the CI service
-- container's own POSTGRES_DB bootstrap, owned by that container's
-- superuser) the CREATE DATABASE above is a no-op, so re-assert
-- ownership here unconditionally — cv_owner must own the database it
-- migrates, or the REVOKE/GRANT block below leaves it without CREATE
-- on schema public (bug #1556 CI follow-up).
ALTER DATABASE candleviewer OWNER TO cv_owner;

\connect candleviewer

-- Re-assert schema ownership too, for the same already-existed case.
ALTER SCHEMA public OWNER TO cv_owner;

-- `cv_app` never receives CREATE/ALTER/DROP on this database (§9.1: "the app
-- role cv_app has no DDL privileges") — no GRANT of schema-level CREATE is
-- issued to it anywhere in this script, and it is asserted by
-- `services/api/tests/integration/*` (role privilege matrix, ticket AC 3).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO cv_app, cv_ro;

ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cv_app;
ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public
  GRANT SELECT ON TABLES TO cv_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO cv_app;

-- Audit tables get no UPDATE/DELETE grant for cv_app (C-5.7). The default
-- privileges above are fail-open for any future audit-classified table, so
-- this script re-asserts the append-only invariant defensively for every
-- table already named `audit_log` (or ending in `_audit_log`) at the time it
-- runs — a no-op today since that table does not exist until `0012_governance`
-- (E09/E42), and a real REVOKE the moment it does, without depending on that
-- later revision remembering to repeat it. `0012_governance` still owns the
-- authoritative REVOKE for `audit_log` (`docs/plan/21-database-schema.md`
-- Sec.1.1) — this is a defence-in-depth backstop, not a substitute.
DO $$
DECLARE
  audit_table regclass;
BEGIN
  FOR audit_table IN
    SELECT c.oid::regclass
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND (c.relname = 'audit_log' OR c.relname LIKE '%\_audit\_log')
  LOOP
    EXECUTE format('REVOKE UPDATE, DELETE ON %s FROM cv_app, cv_ro', audit_table);
  END LOOP;
END
$$;
