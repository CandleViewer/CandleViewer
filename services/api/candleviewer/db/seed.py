"""`candleviewer.db.seed` — idempotent seed loader (E07-T02).

Applies `candleviewer/auth/rbac_seed.json` (the single-source RBAC vocabulary,
`docs/plan/21-database-schema.md` Sec.10.1) via `INSERT ... ON CONFLICT DO
NOTHING` keyed on each table's natural key (`roles.name`, `permissions.code`,
the `role_permissions` composite PK) — §9.3 rule 5's idempotency requirement,
exercised by `services/api/tests/unit/storage/test_seed_idempotency.py`
against a `testcontainers` Postgres. `0001_identity_rbac_sessions_mfa`'s own
unconditional `INSERT` seeds a fresh database; this module is what a
redeploy (`python -m candleviewer.db.seed`, run after every `alembic upgrade
head` per Sec.10) re-runs safely against an already-seeded one.

Not run automatically by any migration — Sec.9.3 rule 5 explicitly separates
schema migrations from data loading ("No data migrations inside schema
migrations beyond seed/lookup rows... bulk backfills are idempotent, resumable
batch jobs"); this loader is that job for the RBAC seed specifically.

`upsert_builtin_indicator_presets` (E13-T03) re-runs the Sec.10.5 built-in
indicator presets that `0040_indicator_presets` seeds, with the same rows and
the same `ON CONFLICT DO NOTHING`, so a re-run is a no-op.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from candleviewer.db.builtin_indicator_presets import BUILTIN_PRESETS

_RBAC_SEED_PATH = Path(__file__).resolve().parents[1] / "auth" / "rbac_seed.json"


class _RoleSeed(TypedDict):
    name: str
    description: str


class _PermissionSeed(TypedDict):
    code: str
    domain: str
    dangerous: bool


class _RbacSeed(TypedDict):
    roles: list[_RoleSeed]
    permissions: list[_PermissionSeed]
    role_permissions: dict[str, list[str]]


def _load_rbac_seed() -> _RbacSeed:
    with _RBAC_SEED_PATH.open(encoding="utf-8") as fh:
        raw: Any = json.load(fh)
    return {
        "roles": raw["roles"],
        "permissions": raw["permissions"],
        "role_permissions": raw["role_permissions"],
    }


async def upsert_roles_and_permissions(conn: AsyncConnection) -> None:
    """Idempotently upsert `roles`, `permissions`, and every owner/manager/
    viewer `role_permissions` grant from `rbac_seed.json`. Safe to call on an
    empty database (first deploy) or a fully-seeded one (every later deploy).
    """
    seed = _load_rbac_seed()

    for role in seed["roles"]:
        await conn.execute(
            sa.text(
                "INSERT INTO roles (id, name, description, is_system) "
                "VALUES (gen_random_uuid(), :name, :description, true) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": role["name"], "description": role["description"]},
        )

    for perm in seed["permissions"]:
        await conn.execute(
            sa.text(
                "INSERT INTO permissions (id, code, domain, description, is_dangerous) "
                "VALUES (gen_random_uuid(), :code, :domain, '', :dangerous) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": perm["code"], "domain": perm["domain"], "dangerous": perm["dangerous"]},
        )

    # role_permissions grants mirror 0001_identity_rbac_sessions_mfa.py's own
    # seed exactly (owner: all; manager/viewer: the named subsets) so a
    # re-seed of an already-migrated database is a true no-op.
    role_permissions = seed["role_permissions"]
    for role_name, codes in role_permissions.items():
        if codes == ["*"]:
            await conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM roles r, permissions p WHERE r.name = :role_name "
                    "ON CONFLICT DO NOTHING"
                ),
                {"role_name": role_name},
            )
        else:
            await conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM roles r, permissions p "
                    "WHERE r.name = :role_name AND p.code = ANY(:codes) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"role_name": role_name, "codes": list(codes)},
            )


#: Revision `0040_indicator_presets`'s seed statement for one row (21 Sec.10.5).
_BUILTIN_PRESET_INSERT = sa.text(
    "INSERT INTO indicator_presets (id, owner_user_id, indicator_code, name, params, style, "
    "pane_target, is_builtin, is_favourite) VALUES (CAST(:id AS uuid), NULL, :indicator_code, "
    ":name, CAST(:params AS jsonb), '{}'::jsonb, :pane_target, true, false) "
    "ON CONFLICT DO NOTHING"
)


async def upsert_builtin_indicator_presets(conn: AsyncConnection) -> None:
    """Idempotently insert the 18 built-in indicator presets (E13-T03), exactly as revision
    `0040_indicator_presets` seeds them: a row already there, or one whose name a live preset
    of the built-in namespace holds, is left as it is (`ON CONFLICT DO NOTHING`), so a re-run
    inserts nothing and changes no `updated_at`."""
    for preset in BUILTIN_PRESETS:
        await conn.execute(
            _BUILTIN_PRESET_INSERT,
            {
                "id": preset.id,
                "indicator_code": preset.indicator_code,
                "name": preset.name,
                "params": json.dumps(dict(preset.params)),
                "pane_target": preset.pane_target,
            },
        )
