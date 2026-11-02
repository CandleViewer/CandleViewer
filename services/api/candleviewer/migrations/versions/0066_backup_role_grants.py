"""cv_backup's read-only grants and default privileges; cv_restore held NOLOGIN (ADR-0041, #3319)

Revision ID: 0066_backup_role_grants
Revises: 0064_orders_origin
Create Date: 2026-11-02

The backup sidecar's two roles (21 Sec.1.1 "Backup roles", ADR-0041 section 1). Both are created by
`infra/scripts/pg_bootstrap.sql` as a superuser: migrations run as `cv_owner`, which has no
`CREATEROLE` and cannot make another role a member of itself, so no role is created, altered or
given a password here (passwords never appear in a migration).

* `cv_backup` runs `pg_dump`: CONNECT on this database, USAGE on schema `public`, SELECT on every
  table and sequence in it, and the default privileges that give it SELECT on every table and
  sequence `cv_owner` creates later, so no later revision repeats a grant. Nothing else: no
  INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER or DDL, and no membership.
* `cv_restore` has the rights of the objects' owner through its membership in `cv_owner`, which
  `pg_bootstrap.sql` grants. It must stay `NOLOGIN` outside a restore job, whose host-side step
  enables its login `VALID UNTIL` the job's deadline. The upgrade refuses while it can log in:
  a cluster where it can is misconfigured, or a restore job is open, and neither migrates.
* Each statement is guarded by the existence of the roles it names (0024's pattern), so on a
  cluster without them the revision changes nothing. The database is named by
  `current_database()`, never a literal, so the grant follows the database being migrated.
* No statement names the runtime role: the boot check of `storage.guarded_privileges` refuses a start in
  `live` while the API's login is a member of `cv_backup`, `cv_restore` or `cv_owner`.

Additive (C-5.1): grants only, no table or column changes. The downgrade revokes exactly what the
upgrade granted, the default privileges first (C-5.2); round trip on an empty and a seeded
database (C-5.5). `lock_timeout` (5 s) bounds the catalogue locks the grants take (C-5.6).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0066_backup_role_grants"
down_revision: str | None = "0064_orders_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_RESTORE_NOLOGIN_SQL)
    op.execute(_GRANT_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_REVOKE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


_RESTORE_NOLOGIN_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_restore' AND rolcanlogin) THEN
    RAISE EXCEPTION '0066_backup_role_grants: cv_restore can log in; it is NOLOGIN outside a restore job (ADR-0041 section 1). Set it NOLOGIN as a superuser, then migrate';
  END IF;
END $BODY$;
"""

_GRANT_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_backup') THEN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO cv_backup', current_database());
    EXECUTE 'GRANT USAGE ON SCHEMA public TO cv_backup';
    EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO cv_backup';
    EXECUTE 'GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO cv_backup';
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_owner') THEN
      EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public GRANT SELECT ON TABLES TO cv_backup';
      EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public GRANT SELECT ON SEQUENCES TO cv_backup';
    END IF;
  END IF;
END $BODY$;
"""

_REVOKE_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_backup') THEN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_owner') THEN
      EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public REVOKE SELECT ON SEQUENCES FROM cv_backup';
      EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public REVOKE SELECT ON TABLES FROM cv_backup';
    END IF;
    EXECUTE 'REVOKE SELECT ON ALL SEQUENCES IN SCHEMA public FROM cv_backup';
    EXECUTE 'REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM cv_backup';
    EXECUTE 'REVOKE USAGE ON SCHEMA public FROM cv_backup';
    EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM cv_backup', current_database());
  END IF;
END $BODY$;
"""
