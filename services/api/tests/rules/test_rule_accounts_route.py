"""#2291 (E35-S04 AC2, BQ-8): `GET /rules/accounts` and the scope checks read the scope resolver
per request, so the one the composition root wires after it builds the router serves them.

The app builds `make_rules_router` before it wires the scope (`create_app`), as the RBAC pack does;
the router therefore takes a provider (`lambda: ctx.rules.scope_resolver`), read on each request.
The answer is the caller's own view grants that are not frozen, sorted; any other account is absent.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.rules import make_rules_router
from candleviewer.rules.service import RulesService
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_validator_endpoints import PRICE, _cmp, _doc

U1, U2 = uuid.UUID(int=1), uuid.UUID(int=2)
A, B, C = (uuid.UUID(int=n) for n in (10, 11, 12))
#: user -> (account, can_view, frozen) rows, as `user_account_access` holds them.
Grants = dict[uuid.UUID, list[tuple[uuid.UUID, bool, bool]]]


class _Source:
    """`ScopeSource` over fixed grant rows, logging which users' grants were read."""

    def __init__(self, grants: Grants) -> None:
        self.grants = grants
        self.loaded: list[uuid.UUID] = []

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        self.loaded.append(owner)
        return list(self.grants.get(owner, []))

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        return frozenset({"rules:read"})


class _Principal:
    def __init__(self, user_id: uuid.UUID, perms: frozenset[str]) -> None:
        self.user_id, self._perms = user_id, perms

    def has(self, permission: str) -> bool:
        return permission in self._perms


class _Resolver:
    """The caller named by the `x-user` header, holding `rules:read` unless `x-perms` is empty."""

    def resolve(self, request: Request) -> _Principal:
        perms = request.headers.get("x-perms", "rules:read")
        user = uuid.UUID(request.headers["x-user"])
        return _Principal(user, frozenset(p for p in perms.split(",") if p))


def _app(grants: Grants) -> tuple[TestClient, RulesService, _Source]:
    """The router as `create_app` mounts it: built first, the scope wired afterwards."""
    svc, source = RulesService(), _Source(grants)
    app = FastAPI()
    app.include_router(
        make_rules_router(
            default_registry,
            principal_resolver=_Resolver(),
            scope_resolver=lambda: svc.scope_resolver,
            scope_refresh=svc.refresh_scope,
        )
    )
    return TestClient(app), svc, source


async def _audit(_event: str, _data: dict[str, str]) -> None:
    return None


def _accounts(client: TestClient, user: uuid.UUID, **headers: str) -> Any:
    return client.get("/rules/accounts", headers={"x-user": str(user), **headers})


def test_rule_accounts_reads_a_resolver_wired_after_the_router_is_built() -> None:
    client, svc, source = _app({U1: [(B, True, False), (A, True, False)]})
    unwired = _accounts(client, U1)
    assert unwired.status_code == 501  # fail closed while no scope is wired
    svc.wire_scope(source, "demo", _audit)
    wired = _accounts(client, U1)
    assert wired.status_code == 200, wired.text
    assert wired.json() == {"accounts": [str(A), str(B)]}


def test_validate_reads_a_resolver_wired_after_the_router_is_built() -> None:
    client, svc, source = _app({U1: [(A, True, False)]})

    def validate(account: uuid.UUID) -> int:
        rule = _doc(
            _cmp(PRICE, {"const": 1}), scope={"level": "account", "account_ids": [str(account)]}
        )
        body = {"ir": rule.model_dump(mode="json")}
        resp = client.post("/rules/validate", json=body, headers={"x-user": str(U1)})
        return int(resp.status_code)

    assert validate(A) == 501
    svc.wire_scope(source, "demo", _audit)
    assert (validate(A), validate(C)) == (200, 403)


def test_rule_accounts_lists_only_view_grants_that_are_not_frozen() -> None:
    client, svc, source = _app({U1: [(A, True, False), (B, True, True), (C, False, False)]})
    svc.wire_scope(source, "demo", _audit)
    assert _accounts(client, U1).json() == {"accounts": [str(A)]}


def test_rule_accounts_without_rules_read_is_403_before_any_grant_read() -> None:
    client, svc, source = _app({U1: [(A, True, False)]})
    svc.wire_scope(source, "demo", _audit)
    resp = _accounts(client, U1, **{"x-perms": "rules:write"})
    assert resp.status_code == 403
    assert source.loaded == []


def test_rule_accounts_never_lists_an_account_of_another_user() -> None:
    client, svc, source = _app({U1: [(A, True, False)], U2: [(B, True, False), (C, True, False)]})
    svc.wire_scope(source, "demo", _audit)
    assert _accounts(client, U1).json() == {"accounts": [str(A)]}
    assert _accounts(client, U2).json() == {"accounts": [str(B), str(C)]}
    assert _accounts(client, uuid.UUID(int=3)).json() == {"accounts": []}
