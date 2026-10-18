"""backups: location and digest become write-once; deleted artefacts are marked (E42-T05 #966)

Revision ID: 0032_backups_write_once
Revises: 0031_policy_disarm
Create Date: 2026-10-18

Slice BK-2 of the backups plan on #966. Deleting an artefact keeps its row (coordinator ruling Q4):
`deleted_at` and `deleted_by` are nullable with no default (no rewrite, Sec.9.3 rule 2), and
`bk_deleted` refuses a `deleted_by` without a `deleted_at`. DDL: `docs/plan/21-database-schema.md`
Sec.3.10.3, second block, verbatim. `deleted_by` is a user id, class P0 (Sec.12), so no column has
a classification comment.

* `trg_backups_write_once` (BEFORE UPDATE, per row) refuses any change to `id`, `kind`,
  `target_path`, `encryption_ref`, `started_at`, `triggered_by` or `triggered_by_user`
  (SR-E42-05). `checksum_sha256` and `deleted_at` may go from NULL to a value once, never back or
  to another value; `deleted_by` is set with the mark and then frozen. It compares with IS
  DISTINCT FROM, so writing a value over itself passes; the engine's columns stay writable.
* `triggered_by_user`, and `deleted_by` once the mark is set, may go to NULL only when their user
  row is gone: both FKs are ON DELETE SET NULL, and that referential action is an UPDATE this
  trigger sees (Postgres 16.4, tested).
* The refusal is SQLSTATE 23514 (`check_violation`), `trg_backups_write_once: backups.<column> is
  write-once (SR-E42-05)`, or `is set-once` for those three. It names the column and its rule,
  never a value: both arguments are literals of the function, and `encryption_ref` is class S.
* `ENABLE ALWAYS` keeps it firing under `session_replication_role = replica`; the function pins
  its `search_path` and names `public.users` in full. It is the only trigger on `backups`.
* No UPDATE trigger fires on DELETE or INSERT, so a delete and a re-insert under the same id would
  replace a row. `REVOKE DELETE ON backups FROM cv_app` takes that DELETE away from the runtime
  role, as 0024 and 0030 do; nothing deletes a catalogue row (kept forever, Sec.7). Guarded like
  0024: the role comes from `infra/scripts/pg_bootstrap.sql`. It narrows a grant and widens none.
  The owner role and superusers can still disable the trigger and delete rows.

Additive (C-5.1). `lock_timeout` (5 s) bounds every lock wait (C-5.6): the ALTER TABLE waits for
ACCESS EXCLUSIVE on `backups` and its FK for SHARE ROW EXCLUSIVE on `users`; the downgrade locks
`backups` in SHARE mode, then its drops wait for ACCESS EXCLUSIVE. The downgrade refuses while any
artefact is marked deleted (C-5.2): dropping `deleted_at` would show a deleted artefact as present,
and the guard keeps the mark, so the way back is a new revision. Otherwise it grants DELETE back
(the `pg_bootstrap.sql` default) and drops what it added.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032_backups_write_once"
down_revision: str | None = "0031_policy_disarm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_COLUMNS_SQL)
    op.execute(_FUNCTION_SQL)
    op.execute(_TRIGGER_SQL)
    op.execute(_REVOKE_DELETE)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_REFUSE_SQL)
    op.execute(_GRANT_DELETE)
    op.execute(_DROP_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.10.3, second block, verbatim.
_COLUMNS_SQL = """
ALTER TABLE backups
  ADD COLUMN deleted_at timestamptz,
  ADD COLUMN deleted_by uuid REFERENCES users(id) ON DELETE SET NULL,
  ADD CONSTRAINT bk_deleted CHECK (deleted_by IS NULL OR deleted_at IS NOT NULL);
"""

_FUNCTION_SQL = """
CREATE FUNCTION backups_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.kind IS DISTINCT FROM OLD.kind THEN 'kind'
    WHEN NEW.target_path IS DISTINCT FROM OLD.target_path THEN 'target_path'
    WHEN NEW.encryption_ref IS DISTINCT FROM OLD.encryption_ref THEN 'encryption_ref'
    WHEN NEW.started_at IS DISTINCT FROM OLD.started_at THEN 'started_at'
    WHEN NEW.triggered_by IS DISTINCT FROM OLD.triggered_by THEN 'triggered_by'
    WHEN NEW.triggered_by_user IS DISTINCT FROM OLD.triggered_by_user
      AND (NEW.triggered_by_user IS NOT NULL
        OR EXISTS (SELECT FROM public.users u WHERE u.id = OLD.triggered_by_user))
      THEN 'triggered_by_user'
    WHEN OLD.checksum_sha256 IS NOT NULL
      AND NEW.checksum_sha256 IS DISTINCT FROM OLD.checksum_sha256 THEN 'checksum_sha256'
    WHEN OLD.deleted_at IS NOT NULL
      AND NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN 'deleted_at'
    WHEN NEW.deleted_by IS DISTINCT FROM OLD.deleted_by AND OLD.deleted_at IS NOT NULL
      AND (NEW.deleted_by IS NOT NULL
        OR EXISTS (SELECT FROM public.users u WHERE u.id = OLD.deleted_by))
      THEN 'deleted_by'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_backups_write_once: backups.% is % (SR-E42-05)', changed,
      CASE WHEN changed IN ('checksum_sha256', 'deleted_at', 'deleted_by') THEN 'set-once'
        ELSE 'write-once' END
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $BODY$;
"""

_TRIGGER_SQL = """
CREATE TRIGGER trg_backups_write_once BEFORE UPDATE ON backups
  FOR EACH ROW EXECUTE FUNCTION backups_write_once();
ALTER TABLE backups ENABLE ALWAYS TRIGGER trg_backups_write_once;
"""

# Each runs only where `pg_bootstrap.sql` created `cv_app` (0024/0030 pattern). Static literals:
# SQL built from strings at runtime trips bandit B608 in the `sast` gate.
_REVOKE_DELETE = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'REVOKE DELETE ON backups FROM cv_app'; END IF; END $BODY$;"
)
_GRANT_DELETE = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'GRANT DELETE ON backups TO cv_app'; END IF; END $BODY$;"
)

_REFUSE_SQL = """
LOCK TABLE backups IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM backups WHERE deleted_at IS NOT NULL) THEN
    RAISE EXCEPTION '0032_backups_write_once downgrade refused: a backup artefact is marked deleted, and dropping deleted_at would show it as present again (its file is gone). Fix forward with a new revision instead (C-5.2); never clear deleted_at in SQL';
  END IF;
END $BODY$;
"""

_DROP_SQL = """
DROP TRIGGER trg_backups_write_once ON backups;
DROP FUNCTION backups_write_once();
ALTER TABLE backups
  DROP CONSTRAINT bk_deleted,
  DROP COLUMN deleted_by,
  DROP COLUMN deleted_at;
"""
