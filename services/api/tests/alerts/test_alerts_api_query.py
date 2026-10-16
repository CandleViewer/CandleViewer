"""SR-026 (#2632): the alert reads accept only the query parameters their contract operation
declares (`listAlerts`: cursor, limit, enabled, symbol; `getAlert`: none). Anything else is a 422
after authentication and the `alerts:read` check, and before the alert store is read."""

from __future__ import annotations

from typing import Any

import pytest
from _alert_api_env import USER_B, Env
from starlette.requests import Request

from candleviewer.api.query_allowlist import undeclared_query_refusal

_READS = ("/alerts", "/alerts/{id}")
#: A target user under the contract's two names, other spellings, and a wrong-case declared name.
_SPELLINGS = ("user_id", "userId", "USER_ID", "uid", "user-id", "owner_user_id", "email", "Limit")


@pytest.fixture
def env() -> Env:
    return Env()


@pytest.mark.parametrize("param", _SPELLINGS)
@pytest.mark.parametrize("route", _READS)
def test_alert_read_with_an_undeclared_query_parameter_is_422_before_the_store_is_read(
    env: Env, route: str, param: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    aid = env.create()["id"]
    audited = len(env.audit.calls)

    async def _must_not_read(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the alert store was read for a request that must be refused")

    monkeypatch.setattr(env.repo, "get", _must_not_read)
    monkeypatch.setattr(env.repo, "list_page", _must_not_read)
    r = env.c.get(route.format(id=aid), params={param: USER_B})
    assert r.status_code == 422, f"{route}?{param}=: refused, not silently ignored"
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["code"] == "validation_failed"
    rule = "target_user_not_accepted" if param in ("user_id", "userId") else "undeclared_parameter"
    assert [(e["field"], e["rule"]) for e in body["errors"]] == [(f"query.{param}", rule)]
    assert param in body["detail"] and USER_B not in r.text, "the value is never echoed"
    assert len(env.audit.calls) == audited, "a refusal audits nothing"


def test_alert_read_refusal_is_the_shared_problem_byte_for_byte(env: Env) -> None:
    r = env.c.get("/alerts", params={"user_id": "x", "uid": "y"})
    request = Request({"type": "http", "query_string": b"user_id=x&uid=y", "headers": []})
    shared = undeclared_query_refusal(request, frozenset({"cursor", "limit", "enabled", "symbol"}))
    assert shared is not None
    assert (r.status_code, r.headers["content-type"], r.content) == (
        shared.status_code,
        shared.headers["content-type"],
        shared.body,
    )


def test_alert_list_declared_parameters_are_still_accepted(env: Env) -> None:
    env.create(name="a")
    env.create(name="b", symbol="ETHUSDT")
    query = {"cursor": "c1", "limit": 5, "enabled": "true", "symbol": "BTCUSDT"}
    r = env.c.get("/alerts", params=query)
    assert r.status_code == 200
    assert [i["name"] for i in r.json()["items"]] == ["a"]


@pytest.mark.parametrize(
    ("signed_in", "perms", "status"),
    [(False, frozenset({"alerts:read"}), 401), (True, frozenset({"alerts:write"}), 403)],
)
@pytest.mark.parametrize("route", _READS)
def test_alert_read_authenticates_and_authorises_before_the_query_refusal(
    env: Env, route: str, signed_in: bool, perms: frozenset[str], status: int
) -> None:
    aid = env.create()["id"]
    env.user, env.perms = (env.user if signed_in else None), perms
    r = env.c.get(route.format(id=aid), params={"user_id": USER_B})
    assert r.status_code == status
