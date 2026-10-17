"""`SqlAlchemyIdentityProvider` with a fake unit of work (QA #1658)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.storage.repositories import accounts_sqlalchemy
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider

_NOW = datetime(2026, 10, 1, tzinfo=UTC)
#: Columns `accounts()` must never select (SECRET-classified or key metadata: C-3.2, SR-051).
#: Matched on word boundaries so a qualified (`ea.exchange_uid`) or comma-terminated column is
#: caught as well as a bare one.
_SECRET_COLUMN = re.compile(
    r"\b(api_keys|exchange_uid|password_hash|equity\w*|key_id_enc|secret_enc)\b"
)


class _Rel:
    def __init__(self, results: list[list[Any]]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any]) -> Any:
            self.calls.append((str(stmt), params))
            rows = self.results.pop(0)
            return SimpleNamespace(first=lambda: rows[0] if rows else None, all=lambda: rows)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


def _provider(rel: _Rel) -> SqlAlchemyIdentityProvider:
    return SqlAlchemyIdentityProvider(rel)  # type: ignore[arg-type]  # structural fake


async def test_user_maps_openapi_user_without_secret_columns() -> None:
    row = SimpleNamespace(
        _mapping={
            "id": "u1",
            "username": "alice",
            "email": "a@x.invalid",
            "display_name": None,
            "status": "active",
            "mfa_required": True,
            "mfa_enabled": True,
            "roles": ["owner"],
            "last_login_at": None,
            "created_at": _NOW,
            "updated_at": _NOW,
        }
    )
    rel = _Rel([[row]])
    user = await _provider(rel).user("u1")
    assert user["roles"] == ["owner"] and user["mfa_enabled"] is True
    assert user["created_at"] == _NOW.isoformat() and user["last_login_at"] is None
    sql, params = rel.calls[0]
    assert "password_hash" not in sql and params == {"id": "u1"}


async def test_user_unknown_raises_lookup_error() -> None:
    with pytest.raises(LookupError):
        await _provider(_Rel([[]])).user("nope")


async def test_session_info_lists_permissions_and_scope() -> None:
    rel = _Rel([[("orders:submit",), ("users:write",)], [("acc-1",)]])
    info = await _provider(rel).session_info("u1")
    assert info == {"permissions": ["orders:submit", "users:write"], "account_scope": ["acc-1"]}


def _account_row(account_id: str, mode: str, label: str = "main") -> Any:
    return SimpleNamespace(
        _mapping={
            "exchange_account_id": account_id,
            "label": label,
            "environment": "demo",
            "mode": mode,
        }
    )


async def test_accounts_maps_each_reachable_account_with_its_label_environment_and_mode() -> None:
    rel = _Rel([[_account_row("a-1", "trade", "main"), _account_row("a-2", "read", "sub")]])
    accounts = await _provider(rel).accounts("u1")
    assert accounts == [
        {"exchange_account_id": "a-1", "label": "main", "environment": "demo", "mode": "trade"},
        {"exchange_account_id": "a-2", "label": "sub", "environment": "demo", "mode": "read"},
    ]


async def test_accounts_for_a_user_who_reaches_none_is_empty() -> None:
    assert await _provider(_Rel([[]])).accounts("u1") == []


async def test_accounts_is_scoped_in_sql_to_the_caller_and_selects_no_secret_column() -> None:
    rel = _Rel([[]])
    await _provider(rel).accounts("u1")
    sql, params = rel.calls[0]
    assert params == {"id": "u1"}, "the only bind is the caller; no client-supplied scope"
    # Scope at construction (SR-051): live accounts, and for a non-owner only live, unfrozen
    # view grants of this user, decided in the statement and never filtered after the fetch.
    assert "ea.deleted_at IS NULL" in sql and "uaa.can_view AND NOT uaa.frozen" in sql
    assert sql.count("CAST(:id AS uuid)") == 2, "the owner check and the grant join"
    assert _SECRET_COLUMN.search(sql) is None


@pytest.mark.parametrize(
    "select",
    [
        "SELECT ea.id, ea.exchange_uid, ea.label FROM exchange_accounts ea",
        "SELECT ea.id, ea.equity_cached_usd FROM exchange_accounts ea",
        "SELECT u.id, u.password_hash FROM users u",
        "SELECT k.key_id_enc, k.secret_enc FROM api_keys k",
    ],
)
def test_the_secret_column_guard_catches_qualified_and_comma_terminated_columns(
    select: str,
) -> None:
    assert _SECRET_COLUMN.search(select) is not None


async def test_accounts_owner_branch_matches_the_account_stores_owner_predicate() -> None:
    rel = _Rel([[]])
    await _provider(rel).accounts("u1")
    sql = " ".join(rel.calls[0][0].split())
    # The owner conjuncts of `accounts_sqlalchemy._OWNER_PRED` (SR-051): the two copies of the
    # predicate cannot drift apart unnoticed.
    for conjunct in (
        "u.deleted_at IS NULL AND u.status = 'active'",
        "(ur.expires_at IS NULL OR ur.expires_at > now())",
    ):
        assert conjunct in accounts_sqlalchemy._OWNER_PRED
        assert conjunct in sql
