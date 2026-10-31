"""Revoke `recording:write` from `manager`: the permission is the Owner's alone (fix-forward)

Revision ID: 0060_recording_write_owner_only
Revises: 0059_alerts_disarm_reason
Create Date: 2026-10-31

E16-S01 (#484) G-04, contract first. Owner decision 4 on #323 keeps `recording:write` for the
Owner alone (E16-D02 decision 4, R-E1 of the E16 threat model, `24-internal-schemas.md` §15.2),
and `docs/plan/22-api-openapi.yaml` `x-permissions`, `candleviewer/auth/rbac_seed.json` and
`04-security-program.md` §7.2.1 and §7.2.2 rows 8, 9 and 51 now say so. A Manager loses adding,
stopping and pinning a recorded symbol, its retention, compaction and import, and
`POST /market/footprint/recompute` (not mounted yet), which needs the same permission.

`0001_identity_rbac_sessions_mfa` granted the permission to `manager` and is immutable (C-5.4), and
`db/seed.py` only ever adds (`ON CONFLICT DO NOTHING`), so this revision fixes forward with data
alone (C-5.1): it deletes the one `role_permissions` row of `manager` and `recording:write`. The
`permissions` row stays, and so do the `owner` grant (0001 gives the Owner every permission) and
`viewer`, which never held it. On a database without the grant the delete removes nothing, so the
upgrade is idempotent. The downgrade (C-5.2) restores 0001's grant, `ON CONFLICT DO NOTHING`.

Every request re-reads its caller's permissions from these tables, so the revoke takes effect at a
Manager's next request; no cache holds the old grant.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0060_recording_write_owner_only"
down_revision: str | None = "0059_alerts_disarm_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_REVOKE_SQL)


def downgrade() -> None:
    op.execute(_GRANT_SQL)


_REVOKE_SQL = """
DELETE FROM role_permissions
WHERE role_id IN (SELECT id FROM roles WHERE name = 'manager')
  AND permission_id IN (SELECT id FROM permissions WHERE code = 'recording:write');
"""

_GRANT_SQL = """
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = 'manager' AND p.code = 'recording:write'
ON CONFLICT DO NOTHING;
"""
