"""incidents + backups + backup_kind + backup_status (E42-T05 #966)

Revision ID: 0028_incidents_backups
Revises: 0027_feature_flags
Create Date: 2026-10-16

Purely additive (C-5.1). `incidents` is `docs/plan/21-database-schema.md` Sec.3.10.2a verbatim
(the incident read model behind `GET /admin/incidents`, new with E42-T05) and `backups` is
Sec.3.10.3 verbatim (the register's `0012_governance` row). `backup_kind` and `backup_status`
(Sec.1.2) had no earlier owner, so they are created here; `severity` comes from 0003.

* `backups.encryption_ref` is class S (Sec.12, C-5.9) and carries the `SECRET:` column comment
  the model mirrors verbatim. No seed, trigger or GRANT (`pg_bootstrap.sql` default privileges).
* `SET LOCAL lock_timeout = '5s'` brackets both directions (0019/0022/0025 pattern, C-5.6): the
  FKs lock `users` on the way in and the drops on the way out, so each wait is bounded.
* Downgrade locks both tables, refuses while either holds rows, then drops tables and types.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028_incidents_backups"
down_revision: str | None = "0027_feature_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_ENUM_SQL)
    op.execute(_INCIDENTS_SQL)
    op.execute(_BACKUPS_SQL)
    op.execute(_COMMENT_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.1.2 (`backup_kind`, `backup_status`), verbatim.
_ENUM_SQL = """
CREATE TYPE backup_kind         AS ENUM ('pg_basebackup','pg_dump','questdb_snapshot','parquet_sync','config_bundle');
CREATE TYPE backup_status       AS ENUM ('running','ok','failed','verified','restored');
"""

# 21-database-schema.md Sec.3.10.2a, verbatim.
_INCIDENTS_SQL = """
CREATE TABLE incidents (
  id              uuid PRIMARY KEY,
  component       text NOT NULL,
  signature       text NOT NULL,
  severity        severity NOT NULL,
  status          text NOT NULL DEFAULT 'open',   -- open | acknowledged | resolved
  title           text NOT NULL,
  detail          text,
  occurrences     integer NOT NULL DEFAULT 1,
  first_seen_at   timestamptz NOT NULL,
  last_seen_at    timestamptz NOT NULL,
  acknowledged_by uuid REFERENCES users(id) ON DELETE SET NULL,
  acknowledged_at timestamptz,
  resolved_at     timestamptz,
  runbook_ref     text,
  CONSTRAINT inc_signature CHECK (signature ~ '^[0-9a-f]{16}$'),
  CONSTRAINT inc_severity  CHECK (severity IN ('error','critical')),
  CONSTRAINT inc_status    CHECK (status IN ('open','acknowledged','resolved')),
  CONSTRAINT inc_count     CHECK (occurrences >= 1),
  CONSTRAINT inc_seen      CHECK (last_seen_at >= first_seen_at),
  CONSTRAINT inc_ack       CHECK (status <> 'acknowledged' OR acknowledged_at IS NOT NULL),
  CONSTRAINT inc_resolved  CHECK (status <> 'resolved' OR resolved_at IS NOT NULL)
);
CREATE UNIQUE INDEX ux_incidents_group ON incidents (component, signature);
CREATE INDEX ix_incidents_seen        ON incidents (last_seen_at DESC);
CREATE INDEX ix_incidents_status_seen ON incidents (status, last_seen_at DESC);
"""

# 21-database-schema.md Sec.3.10.3, verbatim.
_BACKUPS_SQL = """
CREATE TABLE backups (
  id             uuid PRIMARY KEY,
  kind           backup_kind NOT NULL,
  status         backup_status NOT NULL DEFAULT 'running',
  target_path    text NOT NULL,
  size_bytes     bigint,
  checksum_sha256 sha256_hex,
  encrypted      boolean NOT NULL DEFAULT true,
  encryption_ref text,
  covers_from    timestamptz,
  covers_to      timestamptz,
  wal_start_lsn  text,
  wal_end_lsn    text,
  duration_ms    integer,
  verified_at    timestamptz,
  verify_method  text,             -- 'restore_smoke' | 'checksum' | 'pg_verifybackup'
  restored_at    timestamptz,
  error_message  text,
  triggered_by   text NOT NULL DEFAULT 'schedule',  -- schedule | manual | pre_migration | pre_release
  triggered_by_user uuid REFERENCES users(id) ON DELETE SET NULL,
  started_at     timestamptz NOT NULL DEFAULT now(),
  finished_at    timestamptz,
  CONSTRAINT bk_trigger CHECK (triggered_by IN ('schedule','manual','pre_migration','pre_release','pre_restore')),
  CONSTRAINT bk_verify  CHECK (verify_method IS NULL OR verify_method IN ('restore_smoke','checksum','pg_verifybackup','duckdb_scan'))
);
CREATE INDEX ix_backups_kind_time ON backups (kind, started_at DESC);
CREATE INDEX ix_backups_failed    ON backups (started_at DESC) WHERE status = 'failed';
"""

# C-5.9 / Sec.12: the classification declaration. Keep byte-identical to `models.backups`.
_COMMENT_SQL = """
COMMENT ON COLUMN backups.encryption_ref IS 'SECRET: keyring handle of the backup encryption key (21 Sec.12); never returned by any API, never logged';
"""

_DOWNGRADE_SQL = """
LOCK TABLE incidents, backups IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM incidents) OR EXISTS (SELECT 1 FROM backups) THEN
    RAISE EXCEPTION '0028_incidents_backups downgrade refused: incidents or backups hold data';
  END IF;
END $BODY$;
DROP TABLE backups;
DROP TABLE incidents;
DROP TYPE backup_status;
DROP TYPE backup_kind;
"""
