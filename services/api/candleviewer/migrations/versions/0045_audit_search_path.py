"""Pin the audit guard functions' search_path (#4032)

Revision ID: 0045_audit_search_path
Revises: 0044_account_no_hard_delete
Create Date: 2026-10-21

0003's four guard functions (`forbid_mutation`, `audit_refuse_truncate`, `audit_chain`,
`audit_field`) name what they call (`digest`, `encode`, `length`, ...) and the table
`audit_chain` reads (`audit_log`) without a schema, so each resolved them through the
search_path of the session that fires it. This revision gives each its own:
`pg_catalog, public, pg_temp`. `pg_catalog` first, so nothing in another schema shadows a
built-in; `public`, where the tables and pgcrypto live; `pg_temp` last, so a temporary table
can never stand in for `audit_log`. The functions' bodies, and so the chain's hash input, are
unchanged.

CI-MIG-003 exempts this revision while it holds nothing but these statements
(`tools/ci/migration_lint.py`, `_SEARCH_PATH_PIN_REVISION`). The downgrade resets each
function's search_path, the state 0003 left.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0045_audit_search_path"
down_revision: str | None = "0044_account_no_hard_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER FUNCTION forbid_mutation() SET search_path = pg_catalog, public, pg_temp;"
        " ALTER FUNCTION audit_refuse_truncate()"
        " SET search_path = pg_catalog, public, pg_temp;"
        " ALTER FUNCTION audit_chain() SET search_path = pg_catalog, public, pg_temp;"
        " ALTER FUNCTION audit_field(text) SET search_path = pg_catalog, public, pg_temp"
    )


def downgrade() -> None:
    op.execute(
        "ALTER FUNCTION forbid_mutation() RESET search_path;"
        " ALTER FUNCTION audit_refuse_truncate() RESET search_path;"
        " ALTER FUNCTION audit_chain() RESET search_path;"
        " ALTER FUNCTION audit_field(text) RESET search_path"
    )
