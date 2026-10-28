"""Unit tests for `SqlAlchemyAccountsStore` against a recording fake unit of work (E27-T01).

Real-SQL behaviour is covered by tests/integration/storage/test_accounts_store_pg.py (CI only).
"""

from __future__ import annotations

import dataclasses
import re
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.repositories import accounts_sqlalchemy as mod
from candleviewer.storage.repositories.accounts import (
    SUB_ACCOUNT_CAP_CONFLICT,
    AccountKey,
    AccountsStoreConflictError,
    AccountsStoreRuleError,
    AccountsStoreScopeDeniedError,
    AccountsStoreStaleError,
    AccountsStoreUnchangedError,
    ApiKeyRotationRow,
    ApiKeyRow,
    ExchangeAccountPatch,
    ExchangeAccountRow,
    GranteeRow,
    GrantScope,
    NewExchangeAccount,
    NewKeyRotation,
    OwnerScope,
    RotationStep,
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


def _key(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": str(uuid4()), "exchange_account_id": str(uuid4()), "label": "k",
        "key_id_last4": "abcd", "kek_version": 1, "permission_snapshot": '{"a": 1}',
        "permission_snapshot_at": _T, "can_trade": False, "can_withdraw": False,
        "can_transfer": False, "read_only": True, "status": "active", "expires_at": None,
        "last_used_at": None, "rotation_due_at": None, "created_at": _T, "revoked_at": None,
    }  # fmt: skip
    d.update(over)
    return d


def _rot(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": str(uuid4()), "old_api_key_id": str(uuid4()), "new_api_key_id": str(uuid4()),
        "started_at": _T, "validated_at": None, "cutover_at": None, "completed_at": None,
        "failed_at": None, "failure_reason": None, "grace_seconds": 900,
    }  # fmt: skip
    d.update(over)
    return d


def _all_statements() -> set[sa.TextClause]:
    return {v for v in vars(mod).values() if isinstance(v, sa.TextClause)}


def _sql(s: sa.TextClause) -> str:
    return str(s)


def test_statement_inventory_is_fully_classified() -> None:
    allst = _all_statements()
    scoped = set(mod.OWNER_STATEMENTS) | set(mod.GRANT_STATEMENTS) | {mod._OWNER_GATE}
    assert allst == scoped | set(mod.TELEMETRY_STATEMENTS)


def test_statements_are_static_and_have_no_forbidden_shapes() -> None:
    for s in _all_statements():
        text = _sql(s)
        for bad in ("{", "%(", "SELECT *", "OFFSET", "DELETE"):
            assert bad not in text


def test_no_statement_names_an_envelope_column() -> None:
    for s in _all_statements():
        for col in _FORBIDDEN_COLS:
            assert col not in _sql(s)
    for cols in (mod._EA_COLS, mod._KEY_COLS, mod._ROT_COLS):
        for col in _FORBIDDEN_COLS:
            assert col not in cols


def test_column_allow_lists_match_row_dataclasses() -> None:
    for cols, cls in (
        (mod._EA_COLS, ExchangeAccountRow),
        (mod._KEY_COLS, ApiKeyRow),
        (mod._ROT_COLS, ApiKeyRotationRow),
    ):
        aliases = set(re.findall(r" AS (\w+)", cols))
        assert aliases == {f.name for f in dataclasses.fields(cls)}


# SQL is literal only (no concatenation), so each statement repeats its column list and its
# SR-051 / path-scope fragments verbatim. Self-discovering like the drawings tests: a statement
# added later must be classified here, and every copy is pinned to the module constant.
_STATEMENTS = {n: v for n, v in vars(mod).items() if isinstance(v, sa.TextClause)}
_COLUMN_COPIES = {
    "_EA_COLS": ("_CREATE", "_GET_OWNER", "_GET_GRANT", "_LIST_OWNER", "_LIST_GRANT", "_UPDATE"),
    "_KEY_COLS": ("_GET_KEY", "_LIST_KEYS", "_TRANSITION"),
    "_ROT_COLS": ("_GET_ROT", "_LIST_ROTS", "_STEP_VALIDATED", "_STEP_CUTOVER",
                  "_STEP_COMPLETED", "_STEP_FAILED"),
}  # fmt: skip
_NO_COLUMN_COPY = {
    "_OWNER_GATE",
    "_LOCK_PARENT",
    "_COUNT_SUBS",
    "_SOFT_DELETE",
    "_START_ROT",
    "_COUNT_ACCOUNTS",
    "_COUNT_KEYS",
    "_COUNT_PROFILES",
    "_LIST_GRANTEES",
    "_GRANTEES_TIMEOUT",
}


def test_every_statement_has_at_most_one_pinned_column_list() -> None:
    copies = [n for names in _COLUMN_COPIES.values() for n in names]
    assert len(copies) == len(set(copies))
    assert set(copies) | _NO_COLUMN_COPY == set(_STATEMENTS)


@pytest.mark.parametrize(
    ("cols", "name"), [(c, n) for c, names in _COLUMN_COPIES.items() for n in names]
)
def test_literal_column_lists_match_the_pinned_allow_list(cols: str, name: str) -> None:
    assert getattr(mod, cols) in str(_STATEMENTS[name])


def test_start_rotation_returns_exactly_the_rotation_row_fields() -> None:
    returning = str(mod._START_ROT).split(" RETURNING ")[1]
    aliases = set(re.findall(r" AS (\w+)", returning))
    assert aliases == {f.name for f in dataclasses.fields(ApiKeyRotationRow)}


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


_PATH_SCOPE = {
    "k": ("ea.id = k.exchange_account_id", "k.exchange_account_id = CAST(:account AS uuid)"),
    "o": ("ea.id = o.exchange_account_id", "o.exchange_account_id = CAST(:account AS uuid)"),
}


@pytest.mark.parametrize(
    ("name", "alias"),
    [("_GET_KEY", "k"), ("_LIST_KEYS", "k"), ("_TRANSITION", "k"), ("_START_ROT", "o"),
     ("_GET_ROT", "o"), ("_LIST_ROTS", "o"), ("_STEP_VALIDATED", "o"), ("_STEP_CUTOVER", "o"),
     ("_STEP_COMPLETED", "o"), ("_STEP_FAILED", "o")],
)  # fmt: skip
def test_key_and_rotation_statements_are_scoped_to_the_live_path_account(
    name: str, alias: str
) -> None:
    text = str(_STATEMENTS[name])
    assert "ea.deleted_at IS NULL" in text
    for fragment in _PATH_SCOPE[alias]:
        assert fragment in text


@pytest.mark.parametrize("step", sorted(mod._STEPS))
def test_rotation_steps_update_only_the_named_open_rotation(step: str) -> None:
    text = str(mod._STEPS[step])
    assert "r.id = CAST(:rot AS uuid) AND r.completed_at IS NULL AND r.failed_at IS NULL" in text


def test_telemetry_statements_are_env_bound_aggregates_without_row_identity() -> None:
    """#2314: counts for the M13 row gauges; the env is the only bound parameter (no caller, no
    id), so nothing a route could scope leaves these statements."""
    for s in mod.TELEMETRY_STATEMENTS:
        text = _sql(s)
        assert "count(*) AS n" in text and "GROUP BY" in text
        assert "ea.env::text = CAST(:env AS text)" in text
        assert set(s.compile().params) == {"env"}
        assert ".id::text" not in text and " AS id" not in text
    assert "ea.deleted_at IS NULL" in _sql(mod._COUNT_ACCOUNTS)
    assert "deleted_at" not in _sql(mod._COUNT_KEYS)  # 21 §3.2: every api_keys row counts
    profiles = _sql(mod._COUNT_PROFILES)  # #906 D1a: live profiles of live accounts, per state
    case = "CASE WHEN p.trading_enabled THEN 'trading_enabled' ELSE 'trading_disabled' END"
    assert case in profiles
    assert "p.deleted_at IS NULL" in profiles and "ea.deleted_at IS NULL" in profiles
    assert "ea.id = p.exchange_account_id" in profiles


async def test_row_counts_map_rows_and_run_no_gate_and_no_commit() -> None:
    rel = _Rel(
        _Result([{"kind": "main", "n": 2}, {"kind": "sub", "n": 1}]),
        _Result([{"status": "active", "n": 3}]),
        _Result([{"state": "trading_enabled", "n": 4}, {"state": "trading_disabled", "n": 1}]),
    )
    store = _store(rel)
    assert await store.count_accounts_by_kind("live") == {"main": 2, "sub": 1}
    assert await store.count_api_keys_by_status("live") == {"active": 3}
    assert await store.count_profiles_by_trading_state("live") == {
        "trading_enabled": 4,
        "trading_disabled": 1,
    }
    counts = [mod._COUNT_ACCOUNTS, mod._COUNT_KEYS, mod._COUNT_PROFILES]
    assert [c[0] for c in rel.calls] == counts
    assert [c[1] for c in rel.calls] == [{"env": "live"}] * 3 and rel.commits == 0


@pytest.mark.parametrize("env", ["", "prod", "LIVE"])
async def test_row_counts_refuse_an_unknown_env_before_any_sql(env: str) -> None:
    rel = _Rel()
    with pytest.raises(ValueError):
        await _store(rel).count_accounts_by_kind(env)
    with pytest.raises(ValueError):
        await _store(rel).count_api_keys_by_status(env)
    with pytest.raises(ValueError):
        await _store(rel).count_profiles_by_trading_state(env)
    assert rel.calls == []


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
    nr = NewKeyRotation(uuid4(), uuid4(), uuid4(), uuid4())
    calls: list[Callable[[SqlAlchemyAccountsStore], Awaitable[object]]] = [
        lambda s: s.create_account(_OWNER, new),
        lambda s: s.get_account(_OWNER, uuid4()),
        lambda s: s.list_accounts(_OWNER, env=None, kind=None, after=None, limit=5),
        lambda s: s.update_account(_OWNER, uuid4(), ExchangeAccountPatch(label="b"), if_match=None),
        lambda s: s.soft_delete_account(_OWNER, uuid4()),
        lambda s: s.get_key(_OWNER, uuid4(), uuid4()),
        lambda s: s.list_keys(_OWNER, uuid4()),
        lambda s: s.list_grantees(_OWNER, uuid4()),
        lambda s: s.transition_key_status(
            _OWNER, uuid4(), uuid4(), expected="pending", new="active"
        ),
        lambda s: s.start_rotation(_OWNER, nr),
        lambda s: s.get_rotation(_OWNER, uuid4(), uuid4()),
        lambda s: s.list_rotations(_OWNER, uuid4(), limit=5),
        lambda s: s.record_rotation_step(
            _OWNER, uuid4(), uuid4(), "validated", failure_reason=None
        ),
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
    with pytest.raises(AccountsStoreScopeDeniedError):
        await s.list_keys(forged, uuid4())
    with pytest.raises(AccountsStoreScopeDeniedError):
        await s.list_grantees(forged, uuid4())
    assert rel.calls == []


async def test_list_grantees_runs_the_gate_then_maps_each_grant() -> None:
    """#898 B2b: the account's grantees, behind the owner gate, under the read's 250 ms server
    cap, mapped from their rows."""
    user, acct = uuid4(), uuid4()
    row = {"user_id": str(user), "username": "ann", "can_trade": True}
    rel = _Rel(_Result(), _Result(), _Result([row]))
    got = await _store(rel).list_grantees(_OWNER, acct)
    assert got == (GranteeRow(user, "ann", True),) and rel.commits == 0
    stmts = [c[0] for c in rel.calls]
    assert stmts == [mod._OWNER_GATE, mod._GRANTEES_TIMEOUT, mod._LIST_GRANTEES]
    assert rel.calls[2][1] == {"account": str(acct)}


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
    rel = _Rel(
        _Result(), _Result([{"id": str(parent)}]), _Result([_subs(0)]),
        _Result([_ea(kind="sub", parent_account_id=str(parent))]),
    )  # fmt: skip
    new = NewExchangeAccount(uuid4(), "exch", "demo", "sub", "42", "L", parent)
    row = await _store(rel).create_account(_OWNER, new)
    params = rel.calls[3][1]
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


async def test_create_runs_its_write_ahead_on_the_inserted_row_before_the_commit() -> None:
    """C-2.9 (#895): the hook sees the row the insert returned, inside the unit of work."""
    rel, seen = _Rel(_Result(), _Result([_ea()])), list[tuple[ExchangeAccountRow, int]]()

    async def ahead(row: ExchangeAccountRow) -> None:
        seen.append((row, rel.commits))

    new = NewExchangeAccount(uuid4(), "e", "demo", "main", "1", "L")
    row = await _store(rel).create_account(_OWNER, new, write_ahead=ahead)
    assert seen == [(row, 0)] and rel.commits == 1


async def test_create_whose_write_ahead_fails_commits_nothing() -> None:
    rel = _Rel(_Result(), _Result([_ea()]))

    async def refused(_row: ExchangeAccountRow) -> None:
        raise RuntimeError("the audit writer is not started")

    new = NewExchangeAccount(uuid4(), "e", "demo", "main", "1", "L")
    with pytest.raises(RuntimeError):
        await _store(rel).create_account(_OWNER, new, write_ahead=refused)
    assert rel.commits == 0


async def test_create_refused_by_a_constraint_never_runs_its_write_ahead() -> None:
    rel, seen = _Rel(_Result(), raises=_integrity("23505", "ux_ea_uid")), list[object]()

    async def ahead(row: ExchangeAccountRow) -> None:
        seen.append(row)

    new = NewExchangeAccount(uuid4(), "e", "demo", "main", "1", "L")
    with pytest.raises(AccountsStoreConflictError):
        await _store(rel).create_account(_OWNER, new, write_ahead=ahead)
    assert (seen, rel.commits) == ([], 0)


# -- the sub-account cap (#895, 22 createExchangeAccount: "the server rejects the 6th") -----------
def _subs(used: int, *, business_kyc: bool = False) -> dict[str, Any]:
    return {"used": used, "business_kyc": business_kyc}


def _sub_rel(used: int, *, business_kyc: bool = False) -> tuple[_Rel, UUID]:
    parent = uuid4()
    return _Rel(
        _Result(), _Result([{"id": str(parent)}]),
        _Result([_subs(used, business_kyc=business_kyc)]),
        _Result([_ea(kind="sub", parent_account_id=str(parent))]),
    ), parent  # fmt: skip


async def test_create_sub_locks_the_parent_and_counts_before_the_insert() -> None:
    rel, parent = _sub_rel(0)
    await _store(rel).create_account(
        _OWNER, NewExchangeAccount(uuid4(), "e", "demo", "sub", "1", "L", parent)
    )
    stmts = [c[0] for c in rel.calls]
    assert stmts == [mod._OWNER_GATE, mod._LOCK_PARENT, mod._COUNT_SUBS, mod._CREATE]
    assert rel.calls[1][1] == {"parent": str(parent), "env": "demo"}
    assert rel.calls[2][1] == {"parent": str(parent), "env": "demo"}


async def test_create_sub_at_the_cap_is_refused_before_the_write_ahead_and_insert() -> None:
    rel, parent = _sub_rel(mod.SUB_ACCOUNT_CAPS["regular"])
    seen: list[object] = []

    async def ahead(row: ExchangeAccountRow) -> None:
        seen.append(row)

    new = NewExchangeAccount(uuid4(), "e", "demo", "sub", "1", "L", parent)
    with pytest.raises(AccountsStoreConflictError) as ei:
        await _store(rel).create_account(_OWNER, new, write_ahead=ahead)
    assert ei.value.constraint == SUB_ACCOUNT_CAP_CONFLICT == "sub_account_cap"
    assert ei.value.__cause__ is None and ei.value.__suppress_context__ is True
    assert mod._CREATE not in [c[0] for c in rel.calls]
    assert (seen, rel.commits) == ([], 0)


async def test_create_sub_below_the_cap_is_admitted() -> None:
    rel, parent = _sub_rel(mod.SUB_ACCOUNT_CAPS["regular"] - 1)
    row = await _store(rel).create_account(
        _OWNER, NewExchangeAccount(uuid4(), "e", "demo", "sub", "1", "L", parent)
    )
    assert row.parent_account_id == parent and rel.commits == 1


@pytest.mark.parametrize(("used", "refused"), [(19, False), (20, True)])
async def test_create_sub_under_a_recorded_business_kyc_tier_caps_at_twenty(
    used: int, refused: bool
) -> None:
    rel, parent = _sub_rel(used, business_kyc=True)
    new = NewExchangeAccount(uuid4(), "e", "demo", "sub", "1", "L", parent)
    if refused:
        with pytest.raises(AccountsStoreConflictError):
            await _store(rel).create_account(_OWNER, new)
    else:
        await _store(rel).create_account(_OWNER, new)
    assert rel.commits == (0 if refused else 1)


async def test_create_under_a_locked_parent_that_is_no_live_main_is_parent_unavailable() -> None:
    """Defence in depth behind the lock: if the insert's own parent predicate still finds no
    live main parent, the refusal is the same rule error."""
    rel, parent = _sub_rel(0)
    rel.results[-1] = _Result([])
    with pytest.raises(AccountsStoreRuleError) as ei:
        await _store(rel).create_account(
            _OWNER, NewExchangeAccount(uuid4(), "e", "demo", "sub", "1", "L", parent)
        )
    assert ei.value.rule == "parent_unavailable" and rel.commits == 0


async def test_create_main_takes_no_parent_lock_and_no_count() -> None:
    rel = _Rel(_Result(), _Result([_ea()]))
    new = NewExchangeAccount(uuid4(), "e", "demo", "main", "1", "L")
    await _store(rel).create_account(_OWNER, new)
    assert [c[0] for c in rel.calls] == [mod._OWNER_GATE, mod._CREATE]


def test_sub_count_is_live_same_env_children_of_the_one_parent() -> None:
    text = str(mod._COUNT_SUBS)
    for fragment in (
        "s.parent_account_id = CAST(:parent AS uuid)", "s.deleted_at IS NULL",
        "s.env::text = CAST(:env AS text)", "st.scope = 'system'",
        "st.key = 'accounts.subaccount_tier'",
    ):  # fmt: skip
        assert fragment in text
    assert set(mod._COUNT_SUBS.compile().params) == {"parent", "env"}


def test_parent_lock_is_a_no_key_row_lock_on_a_live_main_parent_of_the_env() -> None:
    """`FOR NO KEY UPDATE` serialises sub creates without blocking key / grant inserts that
    reference the parent (their `FOR KEY SHARE` does not conflict with it); an invalid parent
    is not locked, so it keeps the insert's `parent_unavailable` answer, never a cap 409."""
    text = str(mod._LOCK_PARENT)
    for fragment in (
        "p.id = CAST(:parent AS uuid)", "p.deleted_at IS NULL", "p.kind = 'main'",
        "p.env::text = CAST(:env AS text)",
    ):  # fmt: skip
        assert fragment in text
    assert text.endswith("FOR NO KEY UPDATE")
    assert set(mod._LOCK_PARENT.compile().params) == {"parent", "env"}


def test_sub_account_caps_match_the_admin_capacity_tiers() -> None:
    from candleviewer.admin.overview.capacity import TIER_CAPS

    assert dict(mod.SUB_ACCOUNT_CAPS) == dict(TIER_CAPS)


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
async def test_unknown_integrity_errors_are_typed_by_their_facts_alone(
    state: str, name: str | None
) -> None:
    rel = _Rel(_Result(), raises=_integrity(state, name))
    new = NewExchangeAccount(uuid4(), "e", "demo", "main", "1", "L")
    with pytest.raises(StorageConstraintViolated) as ei:
        await _store(rel).create_account(_OWNER, new)
    assert (ei.value.sqlstate, ei.value.constraint, ei.value.__cause__) == (state, name, None)
    assert ei.value.__suppress_context__ is True
    assert "secret-uid" not in "".join(traceback.format_exception(ei.value))


@pytest.mark.parametrize(
    ("state", "name", "refusal"),
    [("23505", "ux_api_keys_active", AccountsStoreConflictError),
     ("23514", "akr_grace", AccountsStoreRuleError),
     ("23503", "some_fk", StorageConstraintViolated)],
)  # fmt: skip
async def test_every_write_types_a_refusal_and_chains_nothing(
    state: str, name: str, refusal: type[Exception]
) -> None:
    nr = NewKeyRotation(uuid4(), uuid4(), uuid4(), uuid4())
    new = NewExchangeAccount(uuid4(), "e", "demo", "main", "1", "L")
    calls: list[Callable[[SqlAlchemyAccountsStore], Awaitable[object]]] = [
        lambda s: s.create_account(_OWNER, new),
        lambda s: s.update_account(_OWNER, uuid4(), ExchangeAccountPatch(label="b"), if_match=None),
        lambda s: s.transition_key_status(
            _OWNER, uuid4(), uuid4(), expected="pending", new="active"
        ),
        lambda s: s.start_rotation(_OWNER, nr),
    ]
    for call in calls:
        with pytest.raises(refusal) as ei:
            await call(_store(_Rel(_Result(), raises=_integrity(state, name))))
        assert ei.value.__cause__ is None and ei.value.__suppress_context__
        assert "secret-uid" not in "".join(traceback.format_exception(ei.value))
        if isinstance(ei.value, StorageConstraintViolated):
            assert (ei.value.sqlstate, ei.value.constraint) == (state, name)


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


def test_an_account_patch_carries_no_environment() -> None:
    """#2333: `exchange_accounts.env` is write-once, so the patch the store takes has no `env`."""
    assert "env" not in {f.name for f in dataclasses.fields(ExchangeAccountPatch)}


def test_an_account_patch_carries_no_identity_column() -> None:
    """#3968 (SR-E27-13): `id`, `exchange_uid` and `kind` are write-once too, so the patch carries
    none of them."""
    fields = {f.name for f in dataclasses.fields(ExchangeAccountPatch)}
    assert not {"id", "exchange_uid", "kind"} & fields


@pytest.mark.parametrize(
    "trigger",
    ["trg_ea_env_write_once", "trg_ea_env_in_use", "trg_ea_env_parent",
     "trg_ea_identity_write_once"],
)  # fmt: skip
async def test_an_account_guard_refusal_is_a_typed_rule_error(trigger: str) -> None:
    """The `env` guards refuse with SQLSTATE 23514 naming themselves as the constraint (0039,
    0041, and 0017's parent guard since 0049, #3962), and so does the `id`, `exchange_uid` and
    `kind` guard (0050, #3968), so a write that met one is the store's rule error, raised
    `from None` (the driver text carries P1 parameters), and nothing commits."""
    rel = _Rel(_Result(), raises=_integrity("23514", trigger))
    with pytest.raises(AccountsStoreRuleError) as ei:
        await _store(rel).update_account(
            _OWNER, uuid4(), ExchangeAccountPatch(label="b"), if_match=None
        )
    assert ei.value.rule == trigger and ei.value.__cause__ is None
    assert ei.value.__suppress_context__ is True and rel.commits == 0


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


async def test_key_reads_decode_snapshot_and_bind_account() -> None:
    acct = uuid4()
    rel = _Rel(
        _Result(), _Result([_key()]), _Result(), _Result([_key(permission_snapshot={"b": 2})])
    )
    s = _store(rel)
    got = await s.get_key(_OWNER, acct, uuid4())
    assert got is not None and got.permission_snapshot == {"a": 1}
    assert rel.calls[1][1]["account"] == str(acct)
    keys = await s.list_keys(_OWNER, acct)
    assert keys[0].permission_snapshot == {"b": 2}
    rel3 = _Rel(_Result(), _Result([]))
    assert await _store(rel3).get_key(_OWNER, acct, uuid4()) is None


async def test_transition_key_status_paths() -> None:
    ok = _Rel(_Result(), _Result([_key(status="active")]))
    row = await _store(ok).transition_key_status(
        _OWNER, uuid4(), uuid4(), expected="pending", new="active"
    )
    assert row is not None and ok.commits == 1
    gone = _Rel(_Result(), _Result([]), _Result([]))
    assert (
        await _store(gone).transition_key_status(
            _OWNER, uuid4(), uuid4(), expected="pending", new="active"
        )
        is None
    )
    revoked = _Rel(_Result(), _Result([]), _Result([_key(revoked_at=_T)]))
    assert (
        await _store(revoked).transition_key_status(
            _OWNER, uuid4(), uuid4(), expected="pending", new="active"
        )
        is None
    )
    stale = _Rel(_Result(), _Result([]), _Result([_key()]))
    with pytest.raises(AccountsStoreConflictError) as ei:
        await _store(stale).transition_key_status(
            _OWNER, uuid4(), uuid4(), expected="pending", new="active"
        )
    assert ei.value.constraint == "key_status"
    dup = _Rel(_Result(), raises=_integrity("23505", "ux_api_keys_active"))
    with pytest.raises(AccountsStoreConflictError):
        await _store(dup).transition_key_status(
            _OWNER, uuid4(), uuid4(), expected="pending", new="active"
        )


@pytest.mark.parametrize(
    ("expected", "new"), [("pending", "revoked"), ("pending", "pending"), ("zz", "active")]
)
async def test_transition_rejects_forbidden_statuses_before_sql(expected: str, new: str) -> None:
    rel = _Rel()
    with pytest.raises(ValueError):
        await _store(rel).transition_key_status(
            _OWNER, uuid4(), uuid4(), expected=expected, new=new
        )
    assert rel.calls == []


async def test_rotation_start_get_list() -> None:
    nr = NewKeyRotation(uuid4(), uuid4(), uuid4(), uuid4(), 60)
    rel = _Rel(
        _Result(), _Result([_rot()]), _Result(), _Result([_rot()]), _Result(), _Result([_rot()])
    )
    s = _store(rel)
    assert (await s.start_rotation(_OWNER, nr)) is not None and rel.commits == 1
    assert rel.calls[1][1]["grace"] == 60
    assert await s.get_rotation(_OWNER, nr.exchange_account_id, uuid4()) is not None
    assert len(await s.list_rotations(_OWNER, nr.exchange_account_id, limit=3)) == 1
    none = _Rel(_Result(), _Result([]))
    assert await _store(none).start_rotation(_OWNER, nr) is None
    miss = _Rel(_Result(), _Result([]))
    assert await _store(miss).get_rotation(_OWNER, uuid4(), uuid4()) is None
    dup = _Rel(_Result(), raises=_integrity("23514", "akr_distinct"))
    with pytest.raises(AccountsStoreRuleError):
        await _store(dup).start_rotation(_OWNER, nr)


@pytest.mark.parametrize("limit", [0, mod._ROTATION_LIMIT + 1])
async def test_list_rotations_rejects_bad_limit(limit: int) -> None:
    with pytest.raises(ValueError):
        await _store(_Rel()).list_rotations(_OWNER, uuid4(), limit=limit)


def test_key_and_rotation_lists_are_bounded() -> None:
    assert str(mod._LIST_KEYS).endswith(" ORDER BY k.created_at, k.id LIMIT 100")
    assert str(mod._LIST_ROTS).endswith(" ORDER BY r.started_at DESC, r.id DESC LIMIT :limit")
    assert mod._ROTATION_LIMIT == 100


async def test_rotation_steps_use_their_statement_and_conflict_when_out_of_order() -> None:
    steps: tuple[RotationStep, ...] = ("validated", "cutover", "completed")
    for step in steps:
        rel = _Rel(_Result(), _Result([_rot()]))
        await _store(rel).record_rotation_step(_OWNER, uuid4(), uuid4(), step, failure_reason=None)
        assert rel.calls[1][0] is mod._STEPS[step]
    failed = _Rel(_Result(), _Result([_rot()]))
    await _store(failed).record_rotation_step(
        _OWNER, uuid4(), uuid4(), "failed", failure_reason="why"
    )
    assert failed.calls[1][1]["reason"] == "why"
    out = _Rel(_Result(), _Result([]), _Result([_rot()]))
    with pytest.raises(AccountsStoreConflictError) as ei:
        await _store(out).record_rotation_step(
            _OWNER, uuid4(), uuid4(), "cutover", failure_reason=None
        )
    assert ei.value.constraint == "rotation_state"
    gone = _Rel(_Result(), _Result([]), _Result([]))
    assert (
        await _store(gone).record_rotation_step(
            _OWNER, uuid4(), uuid4(), "completed", failure_reason=None
        )
        is None
    )


@pytest.mark.parametrize(
    ("step", "reason"),
    [("bogus", None), ("failed", None), ("failed", ""), ("failed", "x" * 201), ("validated", "r")],
)
async def test_rotation_step_input_validation(step: str, reason: str | None) -> None:
    rel = _Rel()
    with pytest.raises(ValueError):
        await _store(rel).record_rotation_step(
            _OWNER,
            uuid4(),
            uuid4(),
            step,  # type: ignore[arg-type]  # deliberate: "bogus" must hit the runtime step guard
            failure_reason=reason,
        )
    assert rel.calls == []


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


@pytest.mark.parametrize("raw", ['{"a": 1}', {"a": 1}])
def test_decode_accepts_json_text_or_mapping(raw: object) -> None:
    assert mod._decode(raw) == {"a": 1}


@pytest.mark.parametrize("raw", ['[["a", 1]]', [("a", 1)], None, 7])
def test_decode_fails_closed_on_a_non_object_snapshot(raw: object) -> None:
    with pytest.raises(TypeError):
        mod._decode(raw)


# -- #898 B3b2: the patch's compare-and-set on `is_enabled` and its write-ahead -----------------


def test_the_update_compares_the_enabled_flag_in_its_one_conditional_write() -> None:
    sql = _sql(mod._UPDATE)
    assert "CAST(:expect_enabled AS boolean) IS NULL" in sql
    assert "ea.is_enabled = CAST(:expect_enabled AS boolean)" in sql


async def test_a_missed_enabled_flag_on_a_live_unchanged_tag_is_unchanged_not_stale() -> None:
    """Ruling 6: the second of two disables finds the account disabled, a repeat, not a 412."""
    rel = _Rel(_Result(), _Result([]), _Result([_ea(is_enabled=False, updated_at=_T)]))
    patch = ExchangeAccountPatch(is_enabled=False)
    with pytest.raises(AccountsStoreUnchangedError):
        await _store(rel).update_account(_OWNER, uuid4(), patch, if_match=None, expect_enabled=True)
    assert rel.calls[1][1]["expect_enabled"] is True and rel.commits == 0
    same = _Rel(_Result(), _Result([]), _Result([_ea(is_enabled=False, updated_at=_T)]))
    with pytest.raises(AccountsStoreUnchangedError):  # the tag still matches: a repeat
        await _store(same).update_account(_OWNER, uuid4(), patch, if_match=_T, expect_enabled=True)


async def test_a_moved_tag_is_stale_whatever_the_enabled_flag() -> None:
    later = datetime(2026, 10, 2, tzinfo=UTC)
    rel = _Rel(_Result(), _Result([]), _Result([_ea(is_enabled=False, updated_at=later)]))
    with pytest.raises(AccountsStoreStaleError):
        await _store(rel).update_account(
            _OWNER, uuid4(), ExchangeAccountPatch(is_enabled=False), if_match=_T,
            expect_enabled=True,
        )  # fmt: skip


async def test_the_write_ahead_runs_on_the_updated_row_before_the_commit() -> None:
    seen: list[tuple[str, int]] = []
    rel = _Rel(_Result(), _Result([_ea(label="b", is_enabled=False)]))

    async def ahead(row: Any) -> None:
        seen.append((row.label, rel.commits))

    await _store(rel).update_account(
        _OWNER, uuid4(), ExchangeAccountPatch(is_enabled=False), if_match=None, write_ahead=ahead
    )
    assert seen == [("b", 0)] and rel.commits == 1


async def test_a_write_ahead_that_fails_rolls_the_update_back() -> None:
    rel = _Rel(_Result(), _Result([_ea()]))

    async def refused(row: Any) -> None:
        raise RuntimeError("audit writer stopped")

    with pytest.raises(RuntimeError):
        await _store(rel).update_account(
            _OWNER, uuid4(), ExchangeAccountPatch(label="b"), if_match=None, write_ahead=refused
        )
    assert rel.commits == 0
