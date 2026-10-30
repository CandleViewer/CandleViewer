"""Integration (E28-T05 #909, S2d): the definition writes end to end on a Postgres 16 set up like
production, as `cv_app`, with the E28 seed (S1a's database). The RBAC pack's real `create_app()`
(`build_world`) over the real profile wiring and definition store, a real `AuditWriter` over
`audit_log`, the flag on, and only the exchange's catalogue the provider world's `Limits`. Needs
Docker and `psql`; CI `integration` runs it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

import candleviewer.app as appmod
from candleviewer.api.trade_group_definition_writes import DefinitionWrites
from candleviewer.api.trade_groups_gate import TradeGroupsGate
from candleviewer.profiles_wiring import wire_profiles
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.trade_group_definitions_sqlalchemy import (
    SqlAlchemyDefinitionStore,
)
from tests.contract._profile_writes_world import Limits
from tests.contract.rbac import rbac_harness as rbac
from tests.integration.accounts.test_profile_routes_pg import _served
from tests.integration.storage import test_trade_group_definitions_store_pg as s1a
from tests.integration.storage import test_trade_groups_store_pg as tg

pytestmark = pytest.mark.integration
bootstrapped, pg_dsn = s1a.bootstrapped, s1a.pg_dsn  # production's roles, then the E28 seed
A, B, C, PAIR = s1a.A, s1a.B, s1a.C, s1a.PAIR
_PATH = "/trade-group-definitions"
_OWNER = (
    "INSERT INTO users (id, email, username, password_hash, status) "
    "VALUES (%s, 'owner@example.test', 'rbac-owner', '$argon2id$x', 'active')"
)
_ROLE = "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE name = 'owner'"
_RECORDS = (
    "SELECT action, before_state IS NULL, after_state->'membership_change' FROM audit_log "
    "WHERE object_id = %s ORDER BY id"
)
_HELD = (
    "SELECT deleted_at IS NOT NULL, (SELECT count(*) FROM trade_group_definition_members m "
    "WHERE m.definition_id = d.id) FROM trade_group_definitions d WHERE d.id = %s"
)
Wired = tuple[rbac.World, list[SqlAlchemyRelationalRepository]]


@pytest.fixture
def world(pg_dsn: str) -> Iterator[Wired]:
    """The pack's Owner live with the owner role, as the store's gate reads it; the app's profile
    wiring and definition store on `cv_app` pools, its definition writes over them."""
    uid, app_dsn, pools = rbac.user_id_of("owner"), tg._login(pg_dsn, "cv_app"), []
    tg._sql(pg_dsn, _OWNER, uid)
    tg._sql(pg_dsn, _ROLE, uid)
    with pytest.MonkeyPatch.context() as mp:

        def wired(settings: Any, metrics: Any, bus: Any) -> Any:
            update = {"storage_backend": "real", "pg_dsn": SecretStr(app_dsn)}
            return wire_profiles(settings.model_copy(update=update), metrics, bus)

        def store(_settings: Any) -> SqlAlchemyDefinitionStore:
            pools.append(SqlAlchemyRelationalRepository(app_dsn, "group-definitions"))
            return SqlAlchemyDefinitionStore(pools[-1])

        def writes(wiring: Any, rows: Any, readiness: Any, _ctx: Any) -> DefinitionWrites:
            return DefinitionWrites(rows, readiness, wiring.accounts, wiring.effective, Limits())

        mp.setattr(appmod, "wire_profiles", wired)
        mp.setattr(appmod, "definition_store", store)
        mp.setattr(appmod, "definition_writes", writes)
        # the flag on; the root's own `preview_ready` (S3c) passed through
        mp.setattr(
            appmod, "TradeGroupsGate", lambda _flag, **built: TradeGroupsGate(lambda: True, **built)
        )
        yield rbac.build_world(mp), pools


def test_a_definition_is_created_replaced_and_deleted_through_its_routes_on_postgres(
    world: Wired, pg_dsn: str, tmp_path: Path
) -> None:
    """The Owner creates Round (A, C), replaces it at the create's `ETag` with B added (200, a new
    tag), is refused a replace at that old tag (412), and deletes it (204); then it reads as a
    missing one does. Three records written ahead, in order, with an intact chain, each with its
    membership change; the stale replace wrote nothing. A Manager, granted none of Pair's members,
    reads Pair as a missing one (SR-E28-21): the cross-account 404."""
    app, pools = world
    owner, named = rbac.bearer("owner"), [{"exchange_account_id": str(a)} for a in (A, B, C)]
    body = {"name": "Round", "environment": "demo", "members": [named[0], named[2]]}
    with _served(app, pg_dsn, tmp_path / "audit.wal") as s:
        try:
            made = s.client.post(_PATH, json=body, headers=owner)
            at, tag = f"{_PATH}/{made.json()['id']}", {"if-match": made.headers["etag"]}
            sent = [made, s.client.put(at, json=body | {"members": named}, headers=owner | tag)]
            sent.append(s.client.put(at, json=body, headers=owner | tag))  # the old tag
            sent.append(s.client.delete(at, headers=owner))
            sent += [s.client.get(path, headers=owner) for path in (at, f"{_PATH}/{uuid.uuid4()}")]
            hidden = s.client.get(f"{_PATH}/{PAIR}", headers=rbac.bearer("manager_with_grant"))
            s.portal.call(s.writer.flush, 60.0)
            chain = s.portal.call(s.verify)
        finally:
            s.portal.call(pools[0].dispose)
    assert [r.status_code for r in sent] == [201, 200, 412, 204, 404, 404] and chain.verified
    assert sent[1].headers["etag"] != made.headers["etag"]
    assert {(r.status_code, r.text) for r in (sent[4], hidden)} == {(404, sent[5].text)}
    key, (a, b, c) = made.json()["id"], (str(A), str(B), str(C))

    def change(added: list[str], removed: list[str]) -> dict[str, list[str]]:
        return {"added": added, "removed": removed, "toggled": []}

    assert tg._sql(pg_dsn, _RECORDS, key) == [
        ("trade_group_definition.created", True, change([a, c], [])),
        ("trade_group_definition.updated", False, change([b], [])),
        ("trade_group_definition.deleted", False, change([], [a, b, c])),
    ]
    assert tg._sql(pg_dsn, _HELD, key) == [(True, 3)]
