"""E40-X01 /alerts writes: every account an alert names must be granted to the caller.

A create or update by anyone but the Owner needs a grant on the top-level `exchange_account_id`
and on each account the compiled condition names: a metric operand's `account_id`, or an
account-named key in its `params`. A refusal is a 403 that changes nothing, and it is audited
first as `alert.scope_refused` (C-2.9).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from _alert_api_env import PRICE_CROSS, USER_A, Env
from fastapi.testclient import TestClient

from candleviewer.audit.writer import AuditUnavailable

ACCT_A = "00000000-0000-4000-8000-0000000000aa"
ACCT_B = "00000000-0000-4000-8000-0000000000bb"
NEW_ID = UUID("00000000-0000-4000-8000-00000000a1e7")
DETAIL = "no grant on an account in the condition"


def _on(left: dict[str, Any]) -> dict[str, Any]:
    """An alert body whose condition compares *left* (an account metric) with a constant."""
    ir = {
        "ir_version": 1,
        "trigger": {"type": "on_price_update", "debounce_ms": 250},
        "conditions": {"node_id": "c1", "op": "lt", "left": left, "right": {"const": 1000}},
    }
    return PRICE_CROSS | {"name": "equity floor", "condition_ir": ir}


def _equity(account: str) -> dict[str, Any]:
    return _on({"metric": "account_equity", "account_id": account})


def _target(env: Env, op: str) -> tuple[str, str]:
    """(method, path) of a *op* write: POST /alerts, or a PUT over an alert created first."""
    return ("POST", "/alerts") if op == "create" else ("PUT", f"/alerts/{env.create()['id']}")


def _refusals(env: Env) -> list[dict[str, Any]]:
    return [kw for action, kw in env.audit.calls if action == "alert.scope_refused"]


@pytest.fixture
def env() -> Env:
    """A caller without the Owner role, granted account A only."""
    e = Env()
    e.granted = frozenset({ACCT_A})
    return e


# The permission comes first. `test_every_route_forbidden_without_its_permission` checks only the
# row count after a refused PUT; this checks the stored row itself, and that nothing is recorded.
@pytest.mark.parametrize("op", ["create", "update"])
def test_write_without_alerts_write_403_nothing_stored(env: Env, op: str) -> None:
    method, path = _target(env, op)
    before, seen = dict(env.repo.rows), len(env.audit.calls)
    env.perms = frozenset({"alerts:read"})
    r = env.c.request(method, path, json=_equity(ACCT_B) | {"name": "renamed"})
    assert r.status_code == 403 and r.json()["required_permissions"] == ["alerts:write"]
    assert env.repo.rows == before and env.audit.calls[seen:] == []


# IDOR: a metric operand names an account outside the caller's grants (create, then update).
def test_create_operand_on_ungranted_account_403_nothing_stored_refusal_audited(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("candleviewer.api.alerts.uuid4", lambda: NEW_ID)
    r = env.c.post("/alerts", json=_equity(ACCT_B) | {"exchange_account_id": ACCT_A})
    assert r.status_code == 403 and r.json()["detail"] == DETAIL
    assert env.repo.rows == {} and env.audit.actions() == ["alert.scope_refused"]
    (record,) = _refusals(env)
    assert record["outcome"].value == "denied" and record["reason"] == "account_not_granted"
    assert record["after_state"] == {"op": "create"} and record["actor_user_id"] == USER_A
    assert (record["object_kind"], record["object_id"]) == ("alert", str(NEW_ID))


def test_update_operand_on_ungranted_account_403_row_unchanged_refusal_audited(env: Env) -> None:
    alert_id = env.create()["id"]
    before = env.repo.rows[alert_id]
    r = env.c.put(f"/alerts/{alert_id}", json=_equity(ACCT_B))
    assert r.status_code == 403 and r.json()["detail"] == DETAIL
    assert env.repo.rows[alert_id] == before
    assert env.audit.actions() == ["alert.created", "alert.scope_refused"]
    (record,) = _refusals(env)
    assert record["outcome"].value == "denied" and record["reason"] == "account_not_granted"
    assert record["after_state"] == {"op": "update"} and record["object_id"] == alert_id


def test_create_owner_names_ungranted_accounts_201(env: Env) -> None:
    env.owner, env.granted = True, frozenset()
    r = env.c.post("/alerts", json=_equity(ACCT_B) | {"exchange_account_id": ACCT_B})
    assert r.status_code == 201, r.text
    assert env.audit.actions() == ["alert.created"]


# With no top-level account, the accounts the condition names are still checked.
@pytest.mark.parametrize("account", [ACCT_A, ACCT_A.upper()])
def test_create_null_scope_operand_on_granted_account_201(env: Env, account: str) -> None:
    """The compiled condition holds the canonical id, so either spelling of a granted id passes."""
    r = env.c.post("/alerts", json=_equity(account))
    assert r.status_code == 201, r.text
    assert r.json()["condition_ir"]["conditions"]["left"]["account_id"] == ACCT_A
    assert r.json()["exchange_account_id"] is None and _refusals(env) == []


def test_create_null_scope_operand_on_ungranted_account_403_audited(env: Env) -> None:
    r = env.c.post("/alerts", json=_equity(ACCT_B))
    assert r.status_code == 403 and r.json()["detail"] == DETAIL and env.repo.rows == {}
    refused = [(kw["reason"], kw["after_state"]) for kw in _refusals(env)]
    assert refused == [("account_not_granted", {"op": "create"})]


# An account-named key inside a metric operand's `params` counts too (fails closed).
@pytest.mark.parametrize("key", ["account_id", "hedge_account_id"])
def test_create_account_key_in_metric_params_not_granted_403_audited(env: Env, key: str) -> None:
    r = env.c.post("/alerts", json=_on({"metric": "account_equity", "params": {key: ACCT_B}}))
    assert r.status_code == 403 and r.json()["detail"] == DETAIL and env.repo.rows == {}
    assert [kw["reason"] for kw in _refusals(env)] == ["account_not_granted"]


# The top-level check keeps its place (before the compile) and its detail, and is now audited.
@pytest.mark.parametrize("op", ["create", "update"])
def test_write_top_level_account_not_granted_same_403_now_audited(env: Env, op: str) -> None:
    method, path = _target(env, op)
    before, compiled = dict(env.repo.rows), len(env.compiles)
    r = env.c.request(method, path, json=PRICE_CROSS | {"exchange_account_id": ACCT_B})
    assert r.status_code == 403 and r.json()["detail"] == "no grant on that account"
    assert env.repo.rows == before and len(env.compiles) == compiled
    (record,) = _refusals(env)
    assert record["outcome"].value == "denied" and record["reason"] == "account_not_granted"
    assert record["after_state"] == {"op": op}


def _fail_refusal_records(env: Env, fault: Exception) -> None:
    """`alert.scope_refused` raises *fault*; every other record is kept as before."""
    keep = env.audit.emit

    async def emit(action: str, **kw: Any) -> None:
        if action == "alert.scope_refused":
            raise fault
        await keep(action, **kw)

    env.audit.emit = emit  # type: ignore[method-assign]  # fault injection


# Write-ahead (C-2.9): a refusal whose record cannot be written does not stand. As on the rules
# path, the request fails as the declared `503 audit_unavailable`, and nothing changes.
@pytest.mark.parametrize("op", ["create", "update"])
def test_write_refusal_whose_record_is_refused_503_nothing_stored(env: Env, op: str) -> None:
    method, path = _target(env, op)
    before = dict(env.repo.rows)
    _fail_refusal_records(env, AuditUnavailable("WAL full"))
    r = env.c.request(method, path, json=_equity(ACCT_B))
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    assert env.repo.rows == before


@pytest.mark.parametrize("op", ["create", "update"])
def test_write_refusal_whose_record_errors_500_nothing_stored(env: Env, op: str) -> None:
    method, path = _target(env, op)
    before = dict(env.repo.rows)
    _fail_refusal_records(env, RuntimeError("audit down"))
    client = TestClient(env.c.app, raise_server_exceptions=False)
    assert client.request(method, path, json=_equity(ACCT_B)).status_code == 500
    assert env.repo.rows == before
