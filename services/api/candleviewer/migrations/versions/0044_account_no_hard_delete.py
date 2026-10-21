"""exchange_accounts: cv_app loses DELETE, the last item of #2758's write-once guarantee

Revision ID: 0044_account_no_hard_delete
Revises: 0042_sessions_view_as
Create Date: 2026-10-21

`REVOKE DELETE ON exchange_accounts FROM cv_app`, the residual that 0024 (`api_keys`) and 0041
(`env`) both named. Both guards are BEFORE UPDATE triggers: neither fires on a DELETE or an INSERT.
`infra/scripts/pg_bootstrap.sql` grants `cv_app` DELETE by default on every table the owner
creates, so the runtime role could delete an account that nothing RESTRICTs (no sub-account,
order, execution, leg, membership, risk row or key rotation), its keys, profiles, positions and
grants cascading with it, and insert the id again: in another environment, which steps around
`trg_ea_env_write_once` (C-2.11, KV-T04), or with an older key row, which steps around
`trg_api_keys_write_once` (SR-003, KV-T02).

* The application never hard-deletes an account: the store soft-deletes (`deleted_at`), and no
  statement under `candleviewer/` or `cvdev/` deletes from or truncates the table (a unit test
  pins it). Referential actions run as the table owner, so a purge by `cv_owner` still cascades to
  keys, profiles, positions, position snapshots and grants. No foreign key cascades into the table:
  `created_by` and `updated_by` are ON DELETE SET NULL (to `users`), `parent_account_id` RESTRICT.
* TRUNCATE needs no REVOKE. The bootstrap's default privileges give `cv_app` SELECT, INSERT, UPDATE
  and DELETE and `cv_ro` SELECT, and no revision grants this table anything else, so `cv_app` never
  held TRUNCATE (a separate privilege), REFERENCES or TRIGGER, and `cv_ro` holds no DELETE. After
  this revision `cv_app` holds INSERT, SELECT and UPDATE (the integration tests pin the set); the
  downgrade's GRANT restores DELETE alone, so a round trip leaves the ACL as it was.
* An UPDATE of `id` is the other way to free an id, and no trigger guards that column. It stays
  refused through the children: every foreign key into the table is ON UPDATE NO ACTION, every
  account has its Default profile (`trg_ea_default_profile`), and `cv_app` can neither re-point a
  profile or a key (the write-once guards, SQLSTATE 23514) nor delete one (0037, 0024: no DELETE),
  so the UPDATE fails with SQLSTATE 23503 (the integration tests pin it). Only a way to detach or
  remove the profile row would re-open it (a cascading key with the profile's write-once guard gone,
  or a DELETE path on `account_profiles`); a write-once guard on `id` would close it directly.
* Guarded like 0024 and 0032: each statement runs only where `pg_bootstrap.sql` created `cv_app`
  (a migration-only test cluster has none). The upgrade narrows one grant and widens none.
* Residuals: the owner (`cv_owner`: migrations, and the alert purge when `CV_PG_OWNER_DSN` is set)
  and superusers can still delete accounts, grant DELETE again, and disable or drop either guard.

No table, column or row changes (C-5.1), so an empty or a seeded database round-trips (C-5.5).
Reversible (C-5.2): `downgrade()` grants DELETE back (the `pg_bootstrap.sql` default), which
re-opens the hole, so it is a rollback-only path. `lock_timeout` (5 s) brackets both directions
(C-5.6); a GRANT or REVOKE rewrites the table's privilege list and nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0044_account_no_hard_delete"
down_revision: str | None = "0042_sessions_view_as"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_REVOKE_DELETE)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_GRANT_DELETE)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# Each runs only where `pg_bootstrap.sql` created `cv_app` (0024/0032 pattern). Static literals:
# SQL built from strings at runtime trips bandit B608 in the `sast` gate.
_REVOKE_DELETE = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'REVOKE DELETE ON exchange_accounts FROM cv_app'; END IF; END $BODY$;"
)
_GRANT_DELETE = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'GRANT DELETE ON exchange_accounts TO cv_app'; END IF; END $BODY$;"
)
