"""E40-T04 inbox RBAC: every route's permission (403 before any lookup), 401 without a session,
fail-closed 501 when no resolver is wired, 503 without a store, and SR-026's declared-query
allow-list on the list."""

from __future__ import annotations

from typing import Any

import pytest
from _deliveries_env import Env

from candleviewer.api.alert_deliveries import LIST_DELIVERIES_QUERY

_OUTCOME = {"outcome": "shown", "permission": "granted"}
ROUTES: list[tuple[str, str, Any, str]] = [
    ("GET", "/alerts/deliveries", None, "alerts:read"),
    ("POST", "/alerts/deliveries/{id}/ack", None, "alerts:write"),
    ("POST", "/alerts/deliveries/ack-all", None, "alerts:write"),
    ("POST", "/alerts/deliveries/{id}/desktop-outcome", _OUTCOME, "alerts:write"),
]


@pytest.fixture
def env() -> Env:
    return Env()


@pytest.mark.parametrize(("method", "path", "body", "perm"), ROUTES)
def test_every_route_is_403_without_its_permission_and_changes_nothing(
    env: Env, method: str, path: str, body: Any, perm: str
) -> None:
    d = env.store.add(channel="desktop", status="queued")
    sent = env.store.add()
    env.perms = frozenset({"alerts:read", "alerts:write"} - {perm})
    r = env.c.request(method, path.format(id=d.id), json=body)
    assert r.status_code == 403 and r.json()["required_permissions"] == [perm]
    assert env.store.rows[d.id] == d and env.store.rows[sent.id] == sent
    assert env.audit.calls == []


@pytest.mark.parametrize(("method", "path", "body", "perm"), ROUTES)
def test_a_foreign_id_is_403_not_404_without_the_permission(
    env: Env, method: str, path: str, body: Any, perm: str
) -> None:
    """The permission check runs before ownership, so a 403 never says whether it exists."""
    other = env.store.add(user="00000000-0000-4000-8000-00000000000b", channel="desktop")
    env.perms = frozenset()
    assert env.c.request(method, path.format(id=other.id), json=body).status_code == 403
    assert env.denials() == []


@pytest.mark.parametrize(("method", "path", "body", "perm"), ROUTES)
def test_every_route_is_401_without_a_session(
    env: Env, method: str, path: str, body: Any, perm: str
) -> None:
    env.user = None
    r = env.c.request(method, path.format(id=1), json=body)
    assert r.status_code == 401 and r.headers["content-type"] == "application/problem+json"
    assert r.json()["code"] == "unauthenticated"


@pytest.mark.parametrize(("method", "path", "body", "perm"), ROUTES)
def test_every_route_fails_closed_501_without_a_resolver(
    method: str, path: str, body: Any, perm: str
) -> None:
    assert Env(wired=False).c.request(method, path.format(id=1), json=body).status_code == 501


@pytest.mark.parametrize(("method", "path", "body", "perm"), ROUTES)
def test_every_route_is_503_without_a_store(
    env: Env, method: str, path: str, body: Any, perm: str
) -> None:
    env.store_up = False
    r = env.c.request(method, path.format(id=1), json=body)
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"


@pytest.mark.parametrize("key", ["user_id", "userId", "owner", "channel"])
def test_list_refuses_an_undeclared_query_parameter(env: Env, key: str) -> None:
    env.store.add()
    r = env.c.get("/alerts/deliveries", params={key: "x"})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"


def test_list_declares_exactly_the_contract_parameters() -> None:
    """Read from the spec (SR-026), as `tests/unit/api/test_query_allowlist.py` does; that table
    also requires a declared 422, which this operation's status list lacks until #1131."""
    from candleviewer.api.contract_conformance import load_openapi_spec
    from tests.unit.api.test_query_allowlist import _declared_query

    assert _declared_query(load_openapi_spec(), "/alerts/deliveries", "get") == (
        LIST_DELIVERIES_QUERY
    )
