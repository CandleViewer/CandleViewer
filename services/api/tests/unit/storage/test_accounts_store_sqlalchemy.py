"""Unit tests for `SqlAlchemyAccountsStore` against a recording fake unit of work (E27-T01).

Real-SQL behaviour is covered by tests/integration/storage/test_accounts_store_pg.py (CI only).
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories import accounts_sqlalchemy as mod
from candleviewer.storage.repositories.accounts import (
    AccountKey,
    AccountsStoreConflictError,
    AccountsStoreRuleError,
    AccountsStoreScopeDeniedError,
    AccountsStoreStaleError,
    ExchangeAccountPatch,
    ExchangeAccountRow,
    GrantScope,
    NewExchangeAccount,
    OwnerScope,
)
from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore

_T = datetime(2026, 10, 1, tzinfo=UTC)
_CALLER = uuid4()
_OWNER = OwnerScope(_CALLER)
_FORBIDDEN_COLS = ("secret_enc", "key_id_enc", "enc_nonce", "dek_ref", "enc_alg", "ip_whitelist")


class _Result:
    def __init__(self, rows: list[Any] | None = None, rowcount: int = 1, scalar: Any = True):
        self.rows = rows or []
        self.rowcount = rowcount
        self._scalar = scalar

    def mappings(self) -> _Result:
        return self

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def __iter__(self) -> Any:
        return iter(self.rows)

    def scalar_one(self) -> Any:
        return self._scalar


class _Rel:
    def __init__(self, *results: _Result, raises: Exception | None = None) -> None:
        self.results = list(results)
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self.commits = 0
        self.raises = raises

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> _Result:
            self.calls.append((stmt, params or {}))
            if self.raises is not None and len(self.calls) > 1:
                raise self.raises
            return self.results.pop(0)

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel) -> SqlAlchemyAccountsStore:
    # The adapter takes the concrete SqlAlchemyRelationalRepository (as every sibling adapter
    # does); _Rel mimics only its unit_of_work(), so the nominal type cannot match.
    return SqlAlchemyAccountsStore(rel)  # type: ignore[arg-type]  # structural fake, see above


def _ea(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": str(uuid4()), "exchange": "x", "env": "demo", "kind": "main",
        "exchange_uid": "1", "parent_account_id": None, "label": "a", "colour_token": "c",
        "is_enabled": True, "trading_enabled": False, "position_mode": "one_way",
        "margin_mode": "cross", "account_type": "UNIFIED", "quote_ccy": "USDT",
        "equity_cached_usd": None, "equity_cached_at": None, "max_sub_accounts_hint": 5,
        "last_reconciled_at": None, "created_at": _T, "updated_at": _T, "deleted_at": None,
    }  # fmt: skip
    d.update(over)
    return d


def _all_statements() -> set[sa.TextClause]:
    return {v for v in vars(mod).values() if isinstance(v, sa.TextClause)}


def _sql(s: sa.TextClause) -> str:
    return str(s)


def test_statement_inventory_is_fully_classified() -> None:
    allst = _all_statements()
    assert allst == set(mod.OWNER_STATEMENTS) | set(mod.GRANT_STATEMENTS) | {mod._OWNER_GATE}


def test_statements_are_static_and_have_no_forbidden_shapes() -> None:
    for s in _all_statements():
        text = _sql(s)
        for bad in ("{", "%(", "SELECT *", "OFFSET", "DELETE"):
            assert bad not in text


def test_no_statement_names_an_envelope_column() -> None:
    for s in _all_statements():
        for col in _FORBIDDEN_COLS:
            assert col not in _sql(s)
    for cols in (mod._EA_COLS,):
        for col in _FORBIDDEN_COLS:
            assert col not in cols


def test_column_allow_lists_match_row_dataclasses() -> None:
    for cols, cls in ((mod._EA_COLS, ExchangeAccountRow),):
        aliases = set(re.findall(r" AS (\w+)", cols))
        assert aliases == {f.name for f in dataclasses.fields(cls)}


# SQL is literal only (no concatenation), so each statement repeats its column list and its
# SR-051 / path-scope fragments verbatim. Self-discovering like the drawings tests: a statement
# added later must be classified here, and every copy is pinned to the module constant.
_STATEMENTS = {n: v for n, v in vars(mod).items() if isinstance(v, sa.TextClause)}
_COLUMN_COPIES = {
    "_EA_COLS": ("_CREATE", "_GET_OWNER", "_GET_GRANT", "_LIST_OWNER", "_LIST_GRANT", "_UPDATE"),
}
_NO_COLUMN_COPY = {"_OWNER_GATE", "_SOFT_DELETE"}


def test_every_statement_has_at_most_one_pinned_column_list() -> None:
    copies = [n for names in _COLUMN_COPIES.values() for n in names]
    assert len(copies) == len(set(copies))
    assert set(copies) | _NO_COLUMN_COPY == set(_STATEMENTS)


@pytest.mark.parametrize(
    ("cols", "name"), [(c, n) for c, names in _COLUMN_COPIES.items() for n in names]
)
def test_literal_column_lists_match_the_pinned_allow_list(cols: str, name: str) -> None:
    assert getattr(mod, cols) in str(_STATEMENTS[name])


def test_owner_gate_is_the_pinned_owner_predicate() -> None:
    head, _, predicate = mod._OWNER_GATE.text.partition(" ")
    assert (head, predicate) == ("SELECT", mod._OWNER_PRED)


@pytest.mark.parametrize(
    ("owner", "grant"), [("_GET_OWNER", "_GET_GRANT"), ("_LIST_OWNER", "_LIST_GRANT")]
)
def test_owner_and_grant_variants_differ_only_in_the_sr051_predicate(
    owner: str, grant: str
) -> None:
    o, g = str(_STATEMENTS[owner]), str(_STATEMENTS[grant])
    assert o.count(mod._OWNER_PRED) == 1 and g.count(mod._GRANT_PRED) == 1
    assert o.replace(mod._OWNER_PRED, "<scope>") == g.replace(mod._GRANT_PRED, "<scope>")


def test_grant_statements_require_snapshot_and_live_grant() -> None:
    for s in mod.GRANT_STATEMENTS:
        text = _sql(s)
        assert "ea.id = ANY(CAST(:granted AS uuid[]))" in text
        assert "uaa.user_id = CAST(:caller AS uuid)" in text
        assert "uaa.can_view AND NOT uaa.frozen" in text
        assert "ea.deleted_at IS NULL" in text


def test_owner_reads_carry_owner_gate_and_liveness() -> None:
    for s in (mod._GET_OWNER, mod._LIST_OWNER):
        text = _sql(s)
        assert "r.name = 'owner'" in text and "ea.deleted_at IS NULL" in text


def test_list_statements_order_then_single_trailing_limit() -> None:
    for s in (mod._LIST_OWNER, mod._LIST_GRANT):
        text = _sql(s)
        assert text.count("LIMIT") == 1 and text.endswith("LIMIT :limit")
        assert "ORDER BY ea.created_at, ea.id LIMIT" in text


async def test_owner_methods_with_failed_gate_run_one_statement_and_no_commit() -> None:
    new = NewExchangeAccount(uuid4(), "x", "demo", "main", "1", "a")
    calls: list[Callable[[SqlAlchemyAccountsStore], Awaitable[object]]] = [
        lambda s: s.create_account(_OWNER, new),
        lambda s: s.get_account(_OWNER, uuid4()),
        lambda s: s.list_accounts(_OWNER, env=None, kind=None, after=None, limit=5),
        lambda s: s.update_account(_OWNER, uuid4(), ExchangeAccountPatch(label="b"), if_match=None),
        lambda s: s.soft_delete_account(_OWNER, uuid4()),
    ]
    for call in calls:
        rel = _Rel(_Result(scalar=False))
        with pytest.raises(AccountsStoreScopeDeniedError):
            await call(_store(rel))
        assert len(rel.calls) == 1 and rel.calls[0][0] is mod._OWNER_GATE and rel.commits == 0


async def test_owner_methods_reject_grant_scope_without_sql() -> None:
    rel = _Rel()
    forged: Any = GrantScope(_CALLER, frozenset({uuid4()}))
    s = _store(rel)
    with pytest.raises(AccountsStoreScopeDeniedError):
        await s.soft_delete_account(forged, uuid4())
    assert rel.calls == []


async def test_empty_grant_scope_makes_no_sql_call() -> None:
    rel = _Rel()
    s = _store(rel)
    empty = GrantScope(_CALLER, frozenset())
    assert await s.get_account(empty, uuid4()) is None
    page = await s.list_accounts(empty, env=None, kind=None, after=None, limit=10)
    assert page.items == () and page.next_after is None and rel.calls == []


async def test_grant_get_binds_sorted_granted_and_caller_and_returns_row_unfiltered() -> None:
    a, b = uuid4(), uuid4()
    foreign = _ea()
    rel = _Rel(_Result([foreign]))
    got = await _store(rel).get_account(GrantScope(_CALLER, frozenset({a, b})), a)
    stmt, params = rel.calls[0]
    assert stmt is mod._GET_GRANT and len(rel.calls) == 1  # the grant arm runs no owner gate
    assert params["granted"] == sorted([str(a), str(b)]) and params["caller"] == str(_CALLER)
    assert got is not None and str(got.id) == foreign["id"]  # SQL is the only filter


async def test_owner_get_runs_gate_then_owner_statement_and_missing_is_none() -> None:
    rel = _Rel(_Result(), _Result([]))
    acct = uuid4()
    assert await _store(rel).get_account(_OWNER, acct) is None
    assert [c[0] for c in rel.calls] == [mod._OWNER_GATE, mod._GET_OWNER]
    assert rel.calls[1][1] == {"id": str(acct), "caller": str(_CALLER)}


async def test_list_fetches_limit_plus_one_and_computes_next_after() -> None:
    rows = [_ea(created_at=_T), _ea(created_at=_T), _ea(created_at=_T)]
    rel = _Rel(_Result(), _Result(rows))
    after = AccountKey(_T, uuid4())
    page = await _store(rel).list_accounts(_OWNER, env="demo", kind="main", after=after, limit=2)
    stmt, params = rel.calls[1]
    assert rel.calls[0][0] is mod._OWNER_GATE and stmt is mod._LIST_OWNER
    assert params["limit"] == 3 and params["after_id"] == str(after.id)
    assert params["caller"] == str(_CALLER) and "granted" not in params
    assert len(page.items) == 2 and page.next_after == AccountKey(_T, page.items[-1].id)
    rel2 = _Rel(_Result(), _Result(rows[:2]))
    last = await _store(rel2).list_accounts(_OWNER, env=None, kind=None, after=None, limit=2)
    assert last.next_after is None


@pytest.mark.parametrize("limit", [0, 501, -1])
async def test_list_rejects_bad_limit_before_sql(limit: int) -> None:
    rel = _Rel()
    with pytest.raises(ValueError):
        await _store(rel).list_accounts(_OWNER, env=None, kind=None, after=None, limit=limit)
    assert rel.calls == []


async def test_list_grant_scope_uses_grant_statement() -> None:
    rel = _Rel(_Result([]))
    scope = GrantScope(_CALLER, frozenset({uuid4()}))
    await _store(rel).list_accounts(scope, env=None, kind=None, after=None, limit=5)
    assert rel.calls[0][0] is mod._LIST_GRANT


@pytest.mark.parametrize(("env", "kind"), [("prod", None), (None, "x")])
async def test_list_rejects_unknown_filters(env: str | None, kind: str | None) -> None:
    with pytest.raises(ValueError):
        await _store(_Rel()).list_accounts(_OWNER, env=env, kind=kind, after=None, limit=5)


async def test_create_binds_exchange_and_commits() -> None:
    parent = uuid4()
    rel = _Rel(_Result(), _Result([_ea(kind="sub", parent_account_id=str(parent))]))
    new = NewExchangeAccount(uuid4(), "exch", "demo", "sub", "42", "L", parent)
    row = await _store(rel).create_account(_OWNER, new)
    params = rel.calls[1][1]
    assert params["exchange"] == "exch" and params["parent"] == str(parent)
    assert row.parent_account_id == parent and rel.commits == 1


async def test_create_with_missing_parent_is_parent_unavailable() -> None:
    rel = _Rel(_Result(), _Result([]))
    new = NewExchangeAccount(uuid4(), "e", "demo", "sub", "1", "L", uuid4())
    with pytest.raises(AccountsStoreRuleError) as ei:
        await _store(rel).create_account(_OWNER, new)
    assert ei.value.rule == "parent_unavailable" and rel.commits == 0


async def test_create_rejects_unknown_env_or_kind() -> None:
    with pytest.raises(ValueError):
        await _store(_Rel()).create_account(
            _OWNER, NewExchangeAccount(uuid4(), "e", "prod", "main", "1", "L")
        )


class _DriverError(Exception):
    """DBAPI-shaped error carrying only what `_sqlstate_and_constraint` reads."""

    def __init__(
        self,
        sqlstate: str | None = None,
        *,
        constraint_name: str | None = None,
        diag: object = None,
        driver_exception: BaseException | None = None,
    ) -> None:
        super().__init__("driver error")
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name
        self.diag = diag
        self.driver_exception = driver_exception


def _integrity(state: str, constraint: str | None, where: str = "orig") -> IntegrityError:
    if where == "orig":
        orig = _DriverError(state, constraint_name=constraint)
    elif where == "cause":
        orig = _DriverError(state)
        orig.__cause__ = _DriverError(constraint_name=constraint)
    elif where == "driver":
        orig = _DriverError(state, driver_exception=_DriverError(constraint_name=constraint))
    else:
        orig = _DriverError(state, diag=SimpleNamespace(constraint_name=constraint))
    return IntegrityError("stmt", {"p": "secret-uid"}, orig)


@pytest.mark.parametrize("where", ["orig", "cause", "driver", "diag"])
async def test_unique_violation_maps_to_conflict_from_every_source(where: str) -> None:
    rel = _Rel(_Result(), raises=_integrity("23505", "ux_ea_label", where))
    new = NewExchangeAccount(uuid4(), "e", "demo", "main", "1", "L")
    with pytest.raises(AccountsStoreConflictError) as ei:
        await _store(rel).create_account(_OWNER, new)
    assert ei.value.constraint == "ux_ea_label" and ei.value.__cause__ is None
    assert ei.value.__suppress_context__ is True


async def test_check_violation_maps_to_rule() -> None:
    rel = _Rel(_Result(), raises=_integrity("23514", "ea_parent_shape"))
    new = NewExchangeAccount(uuid4(), "e", "demo", "main", "1", "L")
    with pytest.raises(AccountsStoreRuleError) as ei:
        await _store(rel).create_account(_OWNER, new)
    assert ei.value.rule == "ea_parent_shape"


@pytest.mark.parametrize(
    ("state", "name"),
    [("23505", "other"), ("23514", "other"), ("23505", None), ("23503", "ux_ea_uid")],
)
async def test_unknown_integrity_errors_are_reraised(state: str, name: str | None) -> None:
    err = _integrity(state, name)
    rel = _Rel(_Result(), raises=err)
    new = NewExchangeAccount(uuid4(), "e", "demo", "main", "1", "L")
    with pytest.raises(IntegrityError):
        await _store(rel).create_account(_OWNER, new)


async def test_unmapped_integrity_error_is_reraised_unchanged_by_every_write() -> None:
    calls: list[Callable[[SqlAlchemyAccountsStore], Awaitable[object]]] = [
        lambda s: s.update_account(_OWNER, uuid4(), ExchangeAccountPatch(label="b"), if_match=None),
    ]
    for call in calls:
        err = _integrity("23503", "some_fk")
        with pytest.raises(IntegrityError) as ei:
            await call(_store(_Rel(_Result(), raises=err)))
        assert ei.value is err


async def test_update_success_bumps_via_sql_and_commits() -> None:
    rel = _Rel(_Result(), _Result([_ea(label="b")]))
    row = await _store(rel).update_account(
        _OWNER, uuid4(), ExchangeAccountPatch(label="b"), if_match=_T
    )
    stmt, params = rel.calls[1]
    assert stmt is mod._UPDATE and params["if_match"] == _T and params["caller"] == str(_CALLER)
    assert "clock_timestamp()" in _sql(mod._UPDATE) and row is not None and rel.commits == 1


async def test_update_zero_rows_live_is_stale_and_gone_is_none() -> None:
    rel = _Rel(_Result(), _Result([]), _Result([_ea()]))
    with pytest.raises(AccountsStoreStaleError):
        await _store(rel).update_account(
            _OWNER, uuid4(), ExchangeAccountPatch(is_enabled=False), if_match=_T
        )
    assert rel.calls[2][0] is mod._GET_OWNER and rel.commits == 0
    rel2 = _Rel(_Result(), _Result([]), _Result([]))
    got = await _store(rel2).update_account(
        _OWNER, uuid4(), ExchangeAccountPatch(margin_mode="isolated"), if_match=None
    )
    assert got is None


async def test_update_empty_patch_rejected_and_integrity_mapped() -> None:
    with pytest.raises(ValueError):
        await _store(_Rel()).update_account(_OWNER, uuid4(), ExchangeAccountPatch(), if_match=None)
    rel = _Rel(_Result(), raises=_integrity("23514", "ea_posmode"))
    with pytest.raises(AccountsStoreRuleError):
        await _store(rel).update_account(
            _OWNER, uuid4(), ExchangeAccountPatch(position_mode="x"), if_match=None
        )


async def test_soft_delete_reports_rowcount() -> None:
    rel = _Rel(_Result(), _Result(rowcount=1))
    assert await _store(rel).soft_delete_account(_OWNER, uuid4()) is True
    rel2 = _Rel(_Result(), _Result(rowcount=0))
    assert await _store(rel2).soft_delete_account(_OWNER, uuid4()) is False


async def test_soft_delete_result_without_rowcount_fails_loudly_not_as_not_found() -> None:
    res = _Result()
    del res.rowcount  # a wrong result object must not read as "nothing deleted"
    with pytest.raises(AttributeError):
        await _store(_Rel(_Result(), res)).soft_delete_account(_OWNER, uuid4())


class _DriverUUID(UUID):
    """Stands in for asyncpg's own `UUID` subclass."""

    __slots__ = ()


def test_uuid_helpers_normalise_to_plain_uuid() -> None:
    u = uuid4()
    for raw in (str(u), _DriverUUID(str(u))):
        got = mod._uuid(raw)
        assert got == u and type(got) is UUID
    assert mod._opt_uuid(None) is None
    opt = mod._opt_uuid(_DriverUUID(str(u)))
    assert opt == u and type(opt) is UUID
