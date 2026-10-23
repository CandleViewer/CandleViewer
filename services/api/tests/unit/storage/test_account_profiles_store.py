"""Unit tests for `SqlAlchemyAccountProfileStore` (E28-T01 #905): the Core statements rendered for
asyncpg, the error mapping and every store path against a recording fake unit of work.

Real SQL runs in tests/integration/storage/test_account_profiles_store_pg.py (CI only).
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from candleviewer.db import models
from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories import account_profiles_sqlalchemy as mod
from candleviewer.storage.repositories import accounts_sqlalchemy as accounts_mod
from candleviewer.storage.repositories.account_profiles import (
    DEFAULT_MOVES_ALONE,
    PROFILE_CONFLICTS,
    PROFILE_RULES,
    AccountProfileRow,
    AccountProfileStore,
    AccountProfileStoreConflictError,
    AccountProfileStoreRuleError,
    AccountProfileStoreScopeDeniedError,
    AccountProfileStoreStaleError,
    AccountProfileValues,
    DefaultBindingRow,
    DefaultMove,
    LadderRung,
)
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope

_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()
_T = datetime(2026, 10, 20, 9, tzinfo=UTC)
_CALLER, _ACCOUNT, _PROFILE = uuid4(), uuid4(), uuid4()
_OWNER = OwnerScope(_CALLER)
_GRANT = GrantScope(_CALLER, frozenset({_ACCOUNT}))
_VALUES = AccountProfileValues(
    name="Scalp", is_default=False, enabled=True, trading_enabled=True, leverage=Decimal("5"),
    margin_mode="cross", position_mode="one_way", sizing_mode="risk_based", size_fixed_qty=None,
    size_fixed_notional_usd=None, size_pct_equity=None, risk_pct_equity=Decimal("1"),
    risk_fixed_amount_usd=None, min_leg_notional_usd=Decimal("5"), sl_offset_value=Decimal("20"),
    sl_offset_unit="ticks", sl_atr_period=14, sl_atr_multiple=Decimal("2"),
    fallback_sl_offset_pct=Decimal("2"), tp_offset_value=None, tp_offset_unit=None,
    tp_ladder=(
        LadderRung(Decimal("50"), Decimal("1")), LadderRung(Decimal("50.5"), Decimal("2.25"))
    ),
    require_native_sl=True, max_position_notional_usd=Decimal("50000"),
    max_position_pct_equity=None, max_daily_loss_usd=Decimal("1000"), max_daily_loss_pct=None,
    max_open_positions=3, max_concurrent_orders=20, max_leverage_cap=Decimal("10"),
    max_orders_per_minute=30, all_symbols=False, allowed_symbols=("BTCUSDT", "*USDT"),
    blocked_symbols=None, reduce_only_default=False, time_in_force_default="GTC",
    slippage_tolerance_bps=10,
)  # fmt: skip


def _sql(stmt: Any) -> str:
    """The statement as asyncpg receives it, whitespace collapsed."""
    text = str(stmt.compile(dialect=_ASYNCPG, compile_kwargs={"render_postcompile": True}))
    return " ".join(text.split())


def _params(stmt: Any) -> dict[str, Any]:
    return dict(stmt.compile(dialect=_ASYNCPG).params)


def _where(stmt: Any) -> str:
    """The WHERE clause alone, without the RETURNING list."""
    return _sql(stmt).split(" WHERE ", 1)[1].split(" RETURNING ", 1)[0]


def _assignments(stmt: Any) -> str:
    return _sql(stmt).split(" SET ", 1)[1].split(" WHERE ", 1)[0]


def _mapping(values: AccountProfileValues = _VALUES, **over: Any) -> dict[str, Any]:
    """A row as asyncpg returns it: `tp_ladder` as text, arrays as lists, ids as strings."""
    m: dict[str, Any] = {f.name: getattr(values, f.name) for f in dataclasses.fields(values)}
    ladder = values.tp_ladder
    m["tp_ladder"] = None if ladder is None else mod._ladder_json(ladder)
    for name in ("allowed_symbols", "blocked_symbols"):
        m[name] = None if m[name] is None else list(m[name])
    m |= {"id": str(_PROFILE), "exchange_account_id": str(_ACCOUNT), "version": 3}
    m |= {"created_by": str(_CALLER), "updated_by": None, "created_at": _T, "updated_at": _T}
    m |= {"deleted_at": None}
    return m | over


class _Result:
    def __init__(self, rows: list[Any] | None = None, scalar: Any = True) -> None:
        self.rows = rows or []
        self._scalar = scalar

    def mappings(self) -> _Result:
        return self

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def one(self) -> Any:
        assert len(self.rows) == 1
        return self.rows[0]

    def __iter__(self) -> Any:
        return iter(self.rows)

    def scalar_one(self) -> Any:
        return self._scalar


class _Rel:
    """A unit of work that answers each `execute` with the next scripted result."""

    def __init__(self, *results: _Result, raises: BaseException | None = None) -> None:
        self.results = list(results)
        self.calls: list[Any] = []
        self.commits = 0
        self.raises = raises

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> _Result:
            self.calls.append(stmt)
            if self.raises is not None and len(self.calls) > 1:
                raise self.raises
            return self.results.pop(0)

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel) -> mod.SqlAlchemyAccountProfileStore:
    # The adapter takes the concrete SqlAlchemyRelationalRepository, as its siblings do; _Rel
    # mimics only its unit_of_work(), so the nominal type cannot match.
    return mod.SqlAlchemyAccountProfileStore(rel)  # type: ignore[arg-type]  # structural fake


_GATE_OK = _Result(scalar=True)
#: The account row a move locks first, at binding version 3.
_BIND3 = _Result([{"default_binding_version": 3}])


# -- the statements -------------------------------------------------------------------------------


def test_the_read_allow_list_is_the_row_and_its_values_in_column_order() -> None:
    names = [c.name for c in mod.PROFILE_COLUMNS]
    row = [f.name for f in dataclasses.fields(AccountProfileRow) if f.name != "values"]
    assert names == row + [f.name for f in dataclasses.fields(AccountProfileValues)]
    assert sorted(names) == sorted(c.name for c in models.account_profiles.columns)


def test_the_ladder_is_read_as_text_so_its_numbers_stay_exact() -> None:
    sql = _sql(mod.get_statement(_OWNER, _ACCOUNT, _PROFILE))
    assert "CAST(account_profiles.tp_ladder AS TEXT) AS tp_ladder" in sql


@pytest.mark.parametrize(
    "stmt",
    [
        mod.list_statement(_OWNER, _ACCOUNT),
        mod.get_statement(_OWNER, _ACCOUNT, _PROFILE),
        mod.update_statement(_OWNER, _ACCOUNT, _PROFILE, _VALUES, 3),
        mod.lock_profile_statement(_OWNER, _ACCOUNT, _PROFILE),
        mod.unset_default_statement(_OWNER, _ACCOUNT),
        mod.set_default_statement(_OWNER, _ACCOUNT, _PROFILE),
        mod.delete_statement(_OWNER, _ACCOUNT, _PROFILE, 3),
        mod.revision_statement(_OWNER, _ACCOUNT, _PROFILE, 2),
        mod.lock_account_statement(_OWNER, _ACCOUNT),
        mod.default_statement(_OWNER, _ACCOUNT),
        mod.binding_lock_statement(_OWNER, _ACCOUNT),
        mod.binding_statement(_OWNER, _ACCOUNT),
    ],
    ids=[
        "list", "get", "update", "lock", "unset", "set", "delete", "revision", "account", "default",
        "binding-lock", "binding",
    ],
)  # fmt: skip
def test_every_owner_statement_carries_the_live_account_and_the_owner_predicate(stmt: Any) -> None:
    """SR-051 in the statement itself, not only in the gate before it."""
    where = _where(stmt)
    assert "exchange_accounts.deleted_at IS NULL" in where
    assert "r.name = 'owner' AND u.deleted_at IS NULL AND u.status = 'active'" in where
    assert _params(stmt)["caller"] == str(_CALLER)


@pytest.mark.parametrize(
    "stmt",
    [
        mod.get_statement(_OWNER, _ACCOUNT, _PROFILE),
        mod.get_statement(_GRANT, _ACCOUNT, _PROFILE),
        mod.update_statement(_OWNER, _ACCOUNT, _PROFILE, _VALUES, 3),
        mod.lock_profile_statement(_OWNER, _ACCOUNT, _PROFILE),
        mod.set_default_statement(_OWNER, _ACCOUNT, _PROFILE),
        mod.delete_statement(_OWNER, _ACCOUNT, _PROFILE, 3),
    ],
    ids=["get", "grant-get", "update", "lock", "set", "delete"],
)
def test_a_profile_is_matched_under_its_own_account_only(stmt: Any) -> None:
    """IDOR (C-12.4, SEC-1B-03): the path's account binds the profile row itself, so another
    account's profile id under this path matches no row; a soft-deleted profile matches none."""
    where = _where(stmt)
    assert "account_profiles.id = $" in where
    assert "account_profiles.exchange_account_id = $" in where
    assert "account_profiles.deleted_at IS NULL" in where
    params = _params(stmt)
    assert params["id_1"] == _PROFILE and params["exchange_account_id_1"] == _ACCOUNT


def test_the_default_read_locks_the_live_default_of_this_account_only() -> None:
    """The before-state a default move hands the hook: this account's live default, locked as the
    row the move then unsets is (CR-1B-R3-01)."""
    stmt = mod.default_statement(_OWNER, _ACCOUNT)
    where = _where(stmt)
    assert "account_profiles.exchange_account_id = $" in where
    assert "account_profiles.is_default IS true" in where
    assert "account_profiles.deleted_at IS NULL" in where
    assert _sql(stmt).endswith(" FOR UPDATE OF account_profiles")
    assert _params(stmt)["exchange_account_id_1"] == _ACCOUNT


def test_the_binding_lock_matches_this_accounts_row_only() -> None:
    """#906 0d: the move locks, and reads the binding's version of, the path's account and no
    other; without the predicate it would lock every live account's row and read whichever
    version came first (the owner predicate and the live account are pinned above)."""
    stmt = mod.binding_lock_statement(_OWNER, _ACCOUNT)
    assert "exchange_accounts.id = $" in _where(stmt)
    assert _ACCOUNT in _params(stmt).values()


@pytest.mark.parametrize("scope", [_OWNER, _GRANT], ids=["owner", "grant"])
def test_the_binding_read_joins_the_live_default_in_scope(scope: OwnerScope | GrantScope) -> None:
    """#906 0d: the account's live default beside its binding version, under the caller's own
    predicate (SR-051), and with no lock: a read never waits for a move."""
    stmt = mod.binding_statement(scope, _ACCOUNT)
    sql, where = _sql(stmt), _where(stmt)
    assert sql.startswith(
        "SELECT account_profiles.id, exchange_accounts.default_binding_version "
        "FROM exchange_accounts JOIN account_profiles "
        "ON account_profiles.exchange_account_id = exchange_accounts.id WHERE "
    )
    assert "account_profiles.exchange_account_id = $" in where
    assert "account_profiles.is_default IS true" in where
    assert "account_profiles.deleted_at IS NULL" in where
    owner = "r.name = 'owner' AND u.deleted_at IS NULL AND u.status = 'active'"
    assert ("uaa.can_view AND NOT uaa.frozen" if scope is _GRANT else owner) in where
    assert " FOR " not in sql


def test_a_list_reads_live_profiles_the_default_first_and_is_bounded() -> None:
    """#905: soft delete is honoured in every read; the default leads (D7), then names."""
    sql = _sql(mod.list_statement(_OWNER, _ACCOUNT))
    assert "account_profiles.deleted_at IS NULL" in _where(mod.list_statement(_OWNER, _ACCOUNT))
    assert re.search(
        r"ORDER BY account_profiles\.is_default DESC, lower\(account_profiles\.name\)", sql
    )
    assert re.search(r" LIMIT \$\d+::INTEGER$", sql)


def test_the_owner_and_grant_scopes_are_the_accounts_stores_own() -> None:
    """SR-051: one scope rule, never a drifting copy (the accounts store's tests pin it)."""
    assert mod._OWNER_PRED == accounts_mod._OWNER_PRED
    assert mod._OWNER_GATE.text == accounts_mod._OWNER_GATE.text
    assert "uaa.can_view AND NOT uaa.frozen" in mod._GRANT_PRED
    assert "uaa.can_view AND NOT uaa.frozen" in accounts_mod._GRANT_PRED


def test_a_revision_is_matched_under_the_account_it_recorded() -> None:
    """The history has no account column: the revision's own payload names its account."""
    stmt = mod.revision_statement(_OWNER, _ACCOUNT, _PROFILE, 2)
    assert "(account_profile_revisions.payload ->> $" in _where(stmt)
    params = _params(stmt)
    assert params["payload_1"] == "exchange_account_id" and params["param_1"] == str(_ACCOUNT)


def test_a_grant_read_narrows_to_granted_accounts_with_a_live_can_view_grant() -> None:
    sql = _sql(mod.get_statement(_GRANT, _ACCOUNT, _PROFILE))
    assert "exchange_accounts.id IN" in sql and "r.name = 'owner'" not in sql
    assert ("EXISTS (SELECT 1 FROM user_account_access uaa WHERE uaa.user_id = CAST($") in sql
    assert (
        "AND uaa.exchange_account_id = exchange_accounts.id AND uaa.can_view AND NOT uaa.frozen)"
        in sql
    )


def test_the_account_subquery_is_never_correlated_away() -> None:
    """`exchange_accounts` stays in the subquery's own FROM, whatever encloses it."""
    for stmt in (
        mod.get_statement(_OWNER, _ACCOUNT, _PROFILE),
        mod.effective_statement(_ACCOUNT, None),
        mod.binding_statement(_OWNER, _ACCOUNT),
    ):
        assert re.search(r"EXISTS \(SELECT \S+ AS anon_\d+\s+FROM exchange_accounts", _sql(stmt))


def test_writes_set_updated_by_and_never_version_or_updated_at() -> None:
    """`trg_ap_version` and the touch trigger own those columns (SR-E28-07), and
    `trg_ap_default_binding` the binding's version (#906 0d): no write names it."""
    for stmt in (
        mod.update_statement(_OWNER, _ACCOUNT, _PROFILE, _VALUES, None),
        mod.set_default_statement(_OWNER, _ACCOUNT, _PROFILE),
        mod.unset_default_statement(_OWNER, _ACCOUNT),
        mod.delete_statement(_OWNER, _ACCOUNT, _PROFILE, None),
    ):
        assignments = _assignments(stmt)
        assert "updated_by=" in assignments
        assert "version=" not in assignments and "updated_at=" not in assignments
        assert "default_binding_version" not in _sql(stmt)
    insert = _sql(mod.insert_statement(_OWNER, _ACCOUNT, _PROFILE, _VALUES))
    columns = insert.split("(", 1)[1].split(")", 1)[0]
    assert "version" not in columns.split(", ") and "updated_at" not in columns.split(", ")
    assert "created_by" in columns and "updated_by" in columns
    assert "default_binding_version" not in insert


def test_update_never_moves_the_default_and_checks_the_expected_version() -> None:
    stmt = mod.update_statement(_OWNER, _ACCOUNT, _PROFILE, _VALUES, 7)
    assert "is_default=" not in _assignments(stmt)
    assert "account_profiles.is_default = false" in _where(stmt)
    assert "account_profiles.version = $" in _where(stmt) and 7 in _params(stmt).values()
    unchecked = mod.update_statement(_OWNER, _ACCOUNT, _PROFILE, _VALUES, None)
    assert "account_profiles.version" not in _where(unchecked)


def test_delete_spares_the_default_and_soft_deletes() -> None:
    stmt = mod.delete_statement(_OWNER, _ACCOUNT, _PROFILE, None)
    assert sorted(_assignments(stmt).split(", ")) == ["deleted_at=now()", "updated_by=$1::UUID"]
    assert "account_profiles.is_default IS false" in _where(stmt)
    assert _sql(stmt).startswith("UPDATE account_profiles SET")


def test_the_ladder_binds_as_json_numbers_rendered_from_decimal() -> None:
    params = _params(mod.insert_statement(_OWNER, _ACCOUNT, _PROFILE, _VALUES))
    ladder = [v for v in params.values() if isinstance(v, str) and v.startswith("[")]
    assert ladder == ['[{"pct": 50, "r": 1}, {"pct": 50.5, "r": 2.25}]']
    assert json.loads(ladder[0], parse_float=Decimal)[1]["pct"] == Decimal("50.5")
    assert "tp_ladder=CAST($" in _sql(
        mod.update_statement(_OWNER, _ACCOUNT, _PROFILE, _VALUES, None)
    )


def test_no_ladder_binds_sql_null_never_json_null() -> None:
    """`ap_ladder_shape` refuses JSON `null`; a profile without a ladder writes SQL NULL."""
    none = dataclasses.replace(_VALUES, tp_ladder=None)
    assert "tp_ladder=NULL" in _assignments(
        mod.update_statement(_OWNER, _ACCOUNT, _PROFILE, none, None)
    )
    bound = _params(mod.insert_statement(_OWNER, _ACCOUNT, _PROFILE, none)).values()
    assert not [v for v in bound if isinstance(v, str) and v.startswith(("[", "null"))]


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_a_ladder_number_that_is_not_finite_is_refused_before_any_sql(value: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        mod._ladder_json((LadderRung(value, Decimal("1")),))


def test_the_symbol_lists_bind_as_text_arrays_and_null_stays_null() -> None:
    params = _params(mod.insert_statement(_OWNER, _ACCOUNT, _PROFILE, _VALUES))
    assert params["allowed_symbols"] == ["BTCUSDT", "*USDT"] and params["blocked_symbols"] is None


def test_the_effective_read_takes_no_principal_and_chooses_the_default_without_an_id() -> None:
    by_default = _sql(mod.effective_statement(_ACCOUNT, None))
    assert "account_profiles.is_default IS true" in by_default and "user_roles" not in by_default
    assert "account_profiles.id = $" in _sql(mod.effective_statement(_ACCOUNT, _PROFILE))
    assert "account_profiles.deleted_at IS NULL" in by_default


def test_the_revision_names_its_account_from_the_payload() -> None:
    sql = _sql(mod.revision_statement(_OWNER, _ACCOUNT, _PROFILE, 2))
    assert "(account_profile_revisions.payload ->> $" in sql
    assert str(_ACCOUNT) in _params(mod.revision_statement(_OWNER, _ACCOUNT, _PROFILE, 2)).values()


# -- decoding --------------------------------------------------------------------------------------


def test_a_row_decodes_to_the_stored_values_exactly() -> None:
    row = mod._row(_mapping())
    assert row.values == _VALUES and row.id == _PROFILE and row.exchange_account_id == _ACCOUNT
    assert row.created_by == _CALLER and row.updated_by is None and row.version == 3


def test_an_empty_symbol_list_stays_distinct_from_null() -> None:
    row = mod._row(_mapping(allowed_symbols=[], blocked_symbols=None))
    assert row.values.allowed_symbols == () and row.values.blocked_symbols is None


def test_a_revision_payload_decodes_to_the_row_it_recorded() -> None:
    """`to_jsonb(row)` as Postgres writes it: ids and times as strings, numerics with scale."""
    payload = {
        **{k: (str(v) if isinstance(v, UUID) else v) for k, v in _mapping().items()},
        "leverage": Decimal("5.00"), "risk_pct_equity": Decimal("1.000000"),
        "created_at": "2026-10-20T09:00:00+00:00", "updated_at": "2026-10-20T09:00:00.5+00:00",
        "tp_ladder": [{"pct": 50, "r": 1}, {"pct": Decimal("50.5"), "r": Decimal("2.25")}],
    }  # fmt: skip
    row = mod._payload_row(payload)
    assert row.values == _VALUES and row.created_at == _T
    assert row.updated_at == datetime(2026, 10, 20, 9, 0, 0, 500000, tzinfo=UTC)


# -- error mapping ---------------------------------------------------------------------------------


class _DriverError(Exception):
    def __init__(self, sqlstate: str | None, constraint_name: str | None = None) -> None:
        super().__init__("violates a constraint\nDETAIL:  Failing row contains (secret-name)")
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name


def _integrity(state: str, constraint: str | None) -> IntegrityError:
    return IntegrityError(
        "UPDATE account_profiles", {"name": "secret-name"}, _DriverError(state, constraint)
    )


@pytest.mark.parametrize("rule", sorted(PROFILE_RULES))
async def test_a_check_or_the_ladder_trigger_maps_to_its_rule(rule: str) -> None:
    rel = _Rel(_GATE_OK, raises=_integrity("23514", rule))
    with pytest.raises(AccountProfileStoreRuleError) as ei:
        await _store(rel).update_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=None)
    assert ei.value.rule == rule and ei.value.__cause__ is None and ei.value.__suppress_context__


@pytest.mark.parametrize("constraint", sorted(PROFILE_CONFLICTS - {"default_profile"}))
async def test_a_unique_index_maps_to_its_conflict(constraint: str) -> None:
    rel = _Rel(_GATE_OK, raises=_integrity("23505", constraint))
    with pytest.raises(AccountProfileStoreConflictError) as ei:
        await _store(rel).update_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=None)
    assert ei.value.constraint == constraint and ei.value.__cause__ is None


@pytest.mark.parametrize(
    ("state", "constraint"),
    [
        ("23514", "trg_ap_version"),
        ("23503", "account_profiles_exchange_account_id_fkey"),
        ("22003", None),
    ],
)
async def test_any_other_refusal_leaves_as_its_sqlstate_only(
    state: str, constraint: str | None
) -> None:
    rel = _Rel(_GATE_OK, raises=_integrity(state, constraint))
    with pytest.raises(StorageQueryFailed) as ei:
        await _store(rel).update_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=None)
    assert ei.value.__cause__ is None and "secret-name" not in str(ei.value)


@pytest.mark.parametrize("error", [OSError("refused"), sa.exc.TimeoutError("pool")])
async def test_a_connection_the_store_cannot_get_is_the_tier_unavailable(error: Exception) -> None:
    rel = _Rel(_GATE_OK, raises=error)
    with pytest.raises(StorageTierUnavailable) as ei:
        await _store(rel).update_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=None)
    assert ei.value.__cause__ is None


async def test_a_lost_connection_mid_statement_is_the_tier_unavailable() -> None:
    lost = OperationalError("SELECT", {}, _DriverError("08006"))
    rel = _Rel(_GATE_OK, raises=lost)
    with pytest.raises(StorageTierUnavailable):
        await _store(rel).get_profile(_OWNER, _ACCOUNT, _PROFILE)


def test_the_rule_and_conflict_sets_are_the_tables_names() -> None:
    checks = {
        str(c.name).removeprefix("ck_account_profiles_")
        for c in models.account_profiles.constraints
        if isinstance(c, sa.CheckConstraint)
    }
    assert PROFILE_RULES == checks | {"trg_ap_ladder_sum"}
    uniques = {str(ix.name) for ix in models.account_profiles.indexes if ix.unique}
    assert PROFILE_CONFLICTS == uniques | {"account_profiles_pkey", "default_profile"}
    assert DEFAULT_MOVES_ALONE not in PROFILE_RULES | PROFILE_CONFLICTS


# -- the store's paths -----------------------------------------------------------------------------


async def test_an_owner_call_by_anyone_else_is_denied_before_any_other_sql() -> None:
    rel = _Rel(_Result(scalar=False))
    with pytest.raises(AccountProfileStoreScopeDeniedError):
        await _store(rel).list_profiles(_OWNER, _ACCOUNT)
    assert len(rel.calls) == 1 and rel.commits == 0


async def test_a_write_takes_an_owner_scope_only() -> None:
    with pytest.raises(AccountProfileStoreScopeDeniedError):
        await _store(_Rel()).delete_profile(_GRANT, _ACCOUNT, _PROFILE, expected_version=None)  # type: ignore[arg-type]  # the refusal under test


async def test_a_default_move_takes_an_owner_scope_only_and_runs_no_sql() -> None:
    """The binding is the account's ceiling (D7), moved by an owner alone: a grant, which only
    reads (SR-051), is refused before any statement runs, so no account row is locked for it."""
    rel = _Rel()
    grant: Any = _GRANT  # the call takes an owner scope, so the type checker refuses a grant here
    with pytest.raises(AccountProfileStoreScopeDeniedError):
        await _store(rel).set_default_profile(grant, _ACCOUNT, _PROFILE, expected_binding_version=3)
    assert rel.calls == [] and rel.commits == 0


async def test_the_binding_read_is_denied_to_a_non_owner_before_any_other_sql() -> None:
    rel = _Rel(_Result(scalar=False))
    with pytest.raises(AccountProfileStoreScopeDeniedError):
        await _store(rel).get_default_binding(_OWNER, _ACCOUNT)
    assert len(rel.calls) == 1 and rel.commits == 0


async def test_a_default_move_is_denied_to_a_non_owner_before_any_other_sql() -> None:
    rel = _Rel(_Result(scalar=False))
    with pytest.raises(AccountProfileStoreScopeDeniedError):
        await _store(rel).set_default_profile(
            _OWNER, _ACCOUNT, _PROFILE, expected_binding_version=3
        )
    assert len(rel.calls) == 1 and rel.commits == 0


async def test_an_empty_grant_reads_nothing_and_runs_no_sql() -> None:
    rel = _Rel()
    empty = GrantScope(_CALLER, frozenset())
    assert await _store(rel).list_profiles(empty, _ACCOUNT) == ()
    assert await _store(rel).get_profile(empty, _ACCOUNT, _PROFILE) is None
    assert await _store(rel).get_revision(empty, _ACCOUNT, _PROFILE, 1) is None
    assert rel.calls == []


async def test_a_grant_read_runs_without_the_owner_gate() -> None:
    rel = _Rel(_Result([_mapping()]))
    rows = await _store(rel).list_profiles(_GRANT, _ACCOUNT)
    assert [r.id for r in rows] == [_PROFILE] and len(rel.calls) == 1


async def test_create_refuses_an_account_that_is_not_live() -> None:
    rel = _Rel(_GATE_OK, _Result([]))
    assert await _store(rel).create_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES) is None
    assert rel.commits == 0 and len(rel.calls) == 2


async def test_create_inserts_under_a_share_lock_of_the_account_and_commits() -> None:
    rel = _Rel(_GATE_OK, _Result([{"id": _ACCOUNT}]), _Result([_mapping(version=1)]))
    row = await _store(rel).create_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES)
    assert row is not None and row.version == 1 and rel.commits == 1
    assert "FOR SHARE" in _sql(rel.calls[1]) and _sql(rel.calls[2]).startswith(
        "INSERT INTO account_profiles"
    )


async def test_update_returns_the_new_row_and_commits() -> None:
    rel = _Rel(_GATE_OK, _Result([_mapping(version=4)]))
    row = await _store(rel).update_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=3)
    assert row is not None and row.version == 4 and rel.commits == 1


async def test_update_of_a_missing_profile_is_none() -> None:
    rel = _Rel(_GATE_OK, _Result([]), _Result([]))
    assert (
        await _store(rel).update_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=3)
        is None
    )
    assert rel.commits == 0


async def test_update_at_an_old_version_is_stale() -> None:
    rel = _Rel(_GATE_OK, _Result([]), _Result([_mapping(version=4)]))
    with pytest.raises(AccountProfileStoreStaleError):
        await _store(rel).update_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=3)


@pytest.mark.parametrize("expected", [3, None])
async def test_update_that_would_move_the_default_is_refused(expected: int | None) -> None:
    current = _mapping(version=3, is_default=True)
    rel = _Rel(_GATE_OK, _Result([]), _Result([current]))
    with pytest.raises(AccountProfileStoreRuleError) as ei:
        await _store(rel).update_profile(
            _OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=expected
        )
    assert ei.value.rule == DEFAULT_MOVES_ALONE and rel.commits == 0


async def test_update_overtaken_after_its_statement_is_stale() -> None:
    """The row matched nothing yet reads as current: another write landed in between."""
    rel = _Rel(_GATE_OK, _Result([]), _Result([_mapping(version=3)]))
    with pytest.raises(AccountProfileStoreStaleError):
        await _store(rel).update_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=3)


async def test_delete_of_the_default_is_a_conflict() -> None:
    rel = _Rel(_GATE_OK, _Result([]), _Result([_mapping(version=3, is_default=True)]))
    with pytest.raises(AccountProfileStoreConflictError) as ei:
        await _store(rel).delete_profile(_OWNER, _ACCOUNT, _PROFILE, expected_version=3)
    assert ei.value.constraint == "default_profile"


async def test_delete_at_an_old_version_is_stale_and_of_a_missing_one_none() -> None:
    stale = _Rel(_GATE_OK, _Result([]), _Result([_mapping(version=9)]))
    with pytest.raises(AccountProfileStoreStaleError):
        await _store(stale).delete_profile(_OWNER, _ACCOUNT, _PROFILE, expected_version=3)
    missing = _Rel(_GATE_OK, _Result([]), _Result([]))
    assert (
        await _store(missing).delete_profile(_OWNER, _ACCOUNT, _PROFILE, expected_version=3) is None
    )


async def test_delete_returns_the_deleted_row_and_commits() -> None:
    rel = _Rel(_GATE_OK, _Result([_mapping(version=4, deleted_at=_T)]))
    row = await _store(rel).delete_profile(_OWNER, _ACCOUNT, _PROFILE, expected_version=3)
    assert row is not None and row.deleted_at == _T and rel.commits == 1


async def test_set_default_moves_it_under_the_account_row_lock_unsetting_first() -> None:
    """#906 0d: the account row first, `FOR NO KEY UPDATE` and before any profile row (21
    Sec.3.2.4), so moves on one account run one at a time; the database bumps the binding."""
    old = _mapping(id=str(uuid4()), version=2, is_default=True)
    rel = _Rel(
        _GATE_OK,
        _BIND3,
        _Result([_mapping(version=3)]),
        _Result([old | {"version": 3, "is_default": False}]),
        _Result([_mapping(version=4, is_default=True)]),
    )
    move = await _store(rel).set_default_profile(
        _OWNER, _ACCOUNT, _PROFILE, expected_binding_version=3
    )
    assert move is not None and move.written and move.version == 4
    assert move.profile.id == _PROFILE and move.profile.values.is_default
    assert move.previous is not None and not move.previous.values.is_default and rel.commits == 1
    assert len(rel.calls) == 5
    lock, select, unset, set_ = (_sql(c) for c in rel.calls[1:5])
    assert lock.startswith(
        "SELECT exchange_accounts.default_binding_version FROM exchange_accounts"
    )
    assert lock.endswith(" FOR NO KEY UPDATE OF exchange_accounts")
    assert "FOR UPDATE OF account_profiles" in select
    assert unset.startswith("UPDATE account_profiles SET is_default=$1::BOOLEAN")
    assert set_.startswith("UPDATE account_profiles SET is_default=$1::BOOLEAN")
    assert _params(rel.calls[3])["is_default"] is False
    assert _params(rel.calls[4])["is_default"] is True


class _Ahead:
    """A write-ahead hook recording what it saw and the commits before it ran."""

    def __init__(self, rel: _Rel, raises: BaseException | None = None) -> None:
        self.rel, self.raises = rel, raises
        self.seen: list[tuple[int | None, int, int]] = []

    async def __call__(self, before: AccountProfileRow | None, after: AccountProfileRow) -> None:
        self.seen.append(
            (None if before is None else before.version, after.version, self.rel.commits)
        )
        if self.raises is not None:
            raise self.raises


async def test_a_create_hands_the_hook_the_new_row_before_it_commits() -> None:
    rel = _Rel(_GATE_OK, _Result([{"id": _ACCOUNT}]), _Result([_mapping(version=1)]))
    ahead = _Ahead(rel)
    await _store(rel).create_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, write_ahead=ahead)
    assert ahead.seen == [(None, 1, 0)] and rel.commits == 1


async def test_an_update_hands_the_hook_the_locked_before_and_the_after_row() -> None:
    rel = _Rel(_GATE_OK, _Result([_mapping(version=3)]), _Result([_mapping(version=4)]))
    ahead = _Ahead(rel)
    await _store(rel).update_profile(
        _OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=3, write_ahead=ahead
    )
    assert ahead.seen == [(3, 4, 0)] and rel.commits == 1
    assert "FOR UPDATE OF account_profiles" in _sql(rel.calls[1])


async def test_a_delete_hands_the_hook_the_locked_before_and_the_deleted_row() -> None:
    rel = _Rel(
        _GATE_OK, _Result([_mapping(version=3)]), _Result([_mapping(version=4, deleted_at=_T)])
    )
    ahead = _Ahead(rel)
    await _store(rel).delete_profile(
        _OWNER, _ACCOUNT, _PROFILE, expected_version=3, write_ahead=ahead
    )
    assert ahead.seen == [(3, 4, 0)] and rel.commits == 1


async def test_a_default_move_hands_the_hook_the_old_default_then_the_new_one() -> None:
    old = _mapping(id=str(uuid4()), version=2, is_default=True)
    rel = _Rel(
        _GATE_OK,
        _BIND3,
        _Result([_mapping(version=3)]),
        _Result([old]),
        _Result([old | {"version": 3, "is_default": False}]),
        _Result([_mapping(version=4, is_default=True)]),
    )
    ahead = _Ahead(rel)
    await _store(rel).set_default_profile(
        _OWNER, _ACCOUNT, _PROFILE, expected_binding_version=3, write_ahead=ahead
    )
    assert ahead.seen == [(2, 3, 0), (3, 4, 0)] and rel.commits == 1
    assert "FOR UPDATE OF account_profiles" in _sql(rel.calls[3])


async def test_a_default_move_without_a_previous_default_hands_the_hook_the_new_one_only() -> None:
    rel = _Rel(
        _GATE_OK,
        _BIND3,
        _Result([_mapping(version=3)]),
        _Result([]),
        _Result([]),
        _Result([_mapping(version=4, is_default=True)]),
    )
    ahead = _Ahead(rel)
    move = await _store(rel).set_default_profile(
        _OWNER, _ACCOUNT, _PROFILE, expected_binding_version=3, write_ahead=ahead
    )
    assert move is not None and move.written and move.previous is None
    assert ahead.seen == [(3, 4, 0)] and rel.commits == 1


async def _refusable(
    write: str, store: mod.SqlAlchemyAccountProfileStore, ahead: _Ahead
) -> AccountProfileRow | DefaultMove | None:
    if write == "update":
        return await store.update_profile(
            _OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=3, write_ahead=ahead
        )
    if write == "delete":
        return await store.delete_profile(
            _OWNER, _ACCOUNT, _PROFILE, expected_version=3, write_ahead=ahead
        )
    return await store.set_default_profile(
        _OWNER, _ACCOUNT, _PROFILE, expected_binding_version=3, write_ahead=ahead
    )


_V4 = _Result([_mapping(version=4)])
_DEFAULT = _Result([_mapping(version=3, is_default=True)])


@pytest.mark.parametrize(
    ("write", "results", "refusal"),
    [
        ("update", [_V4, _Result([]), _V4], AccountProfileStoreStaleError),
        ("update", [_Result([]), _Result([]), _Result([])], None),
        ("update", [_DEFAULT, _Result([]), _DEFAULT], AccountProfileStoreRuleError),
        ("delete", [_V4, _Result([]), _V4], AccountProfileStoreStaleError),
        ("delete", [_DEFAULT, _Result([]), _DEFAULT], AccountProfileStoreConflictError),
        ("delete", [_Result([]), _Result([]), _Result([])], None),
        ("default", [_Result([{"default_binding_version": 4}])], AccountProfileStoreStaleError),
        ("default", [_Result([])], None),
        ("default", [_BIND3, _Result([])], None),
        ("default", [_BIND3, _DEFAULT], None),
    ],
    ids=[
        "stale-update", "missing-update", "default-moves-alone", "stale-delete",
        "delete-the-default", "missing-delete", "stale-move", "missing-account-move",
        "missing-move", "already-default",
    ],
)  # fmt: skip
async def test_a_write_that_changes_no_row_never_calls_the_hook(
    write: str, results: list[_Result], refusal: type[Exception] | None
) -> None:
    """Once per row it changed, so never for a refused, missing or no-op write (CR-1B-R3-02)."""
    rel = _Rel(_GATE_OK, *results)
    ahead = _Ahead(rel)
    if refusal is None:
        outcome = await _refusable(write, _store(rel), ahead)
        assert outcome is None or (isinstance(outcome, DefaultMove) and not outcome.written)
    else:
        with pytest.raises(refusal):
            await _refusable(write, _store(rel), ahead)
    assert ahead.seen == [] and rel.commits == 0


async def test_a_raw_os_error_from_the_hook_reads_as_the_database_unreachable() -> None:
    """Why the hook raises its own typed refusal (the `ProfileWriteAhead` contract): the store
    maps an `OSError` it cannot tell from the driver's as the tier's (CR-1B-R3-07)."""
    rel = _Rel(_GATE_OK, _Result([_mapping(version=3)]), _Result([_mapping(version=4)]))
    with pytest.raises(StorageTierUnavailable):
        await _store(rel).update_profile(
            _OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=3,
            write_ahead=_Ahead(rel, ConnectionError("audit disk")),
        )  # fmt: skip
    assert rel.commits == 0


async def test_a_hook_that_raises_leaves_the_write_uncommitted() -> None:
    rel = _Rel(_GATE_OK, _Result([_mapping(version=3)]), _Result([_mapping(version=4)]))
    with pytest.raises(RuntimeError, match="audit store down"):
        await _store(rel).update_profile(
            _OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=3,
            write_ahead=_Ahead(rel, RuntimeError("audit store down")),
        )  # fmt: skip
    assert rel.commits == 0


async def test_a_hook_past_the_audit_timeout_leaves_the_write_uncommitted() -> None:
    rel = _Rel(_GATE_OK, _Result([{"id": _ACCOUNT}]), _Result([_mapping(version=1)]))

    async def hangs(before: AccountProfileRow | None, after: AccountProfileRow) -> None:
        await asyncio.Event().wait()

    store = mod.SqlAlchemyAccountProfileStore(rel, audit_timeout_s=0.01)  # type: ignore[arg-type]  # structural fake
    with pytest.raises(WriteAheadTimeout):
        await store.create_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, write_ahead=hangs)
    assert rel.commits == 0


async def test_without_a_hook_a_write_reads_nothing_first() -> None:
    rel = _Rel(_GATE_OK, _Result([_mapping(version=4)]))
    await _store(rel).update_profile(_OWNER, _ACCOUNT, _PROFILE, _VALUES, expected_version=3)
    assert len(rel.calls) == 2 and _sql(rel.calls[1]).startswith("UPDATE account_profiles")


async def test_a_move_at_an_old_binding_version_is_stale_before_the_profile_is_read() -> None:
    """No last-write-wins on the binding (#906 0d): a stale version is refused under the account
    row lock, before the profile the move names is read, so it tells nothing about that profile.
    Nothing but the exact version is accepted, ahead or behind: a tag the binding has not reached
    is as stale as one it has passed."""
    for bound in (4, 2):  # the tag, 3, is behind the binding, then ahead of it
        stale = _Rel(_GATE_OK, _Result([{"default_binding_version": bound}]))
        with pytest.raises(AccountProfileStoreStaleError):
            await _store(stale).set_default_profile(
                _OWNER, _ACCOUNT, _PROFILE, expected_binding_version=3
            )
        assert len(stale.calls) == 2 and stale.commits == 0
    for script in ([_Result([])], [_BIND3, _Result([])]):  # no live account, then no profile
        missing = _Rel(_GATE_OK, *script)
        moved = await _store(missing).set_default_profile(
            _OWNER, _ACCOUNT, _PROFILE, expected_binding_version=3
        )
        assert moved is None and missing.commits == 0 and len(missing.calls) == 1 + len(script)
    current = _Rel(_GATE_OK, _BIND3, _Result([_mapping(version=3, is_default=True)]))
    again = await _store(current).set_default_profile(
        _OWNER, _ACCOUNT, _PROFILE, expected_binding_version=3
    )
    assert again is not None and not again.written and again.version == 3
    assert again.previous is None and current.commits == 0 and len(current.calls) == 3


@pytest.mark.parametrize(
    "move",
    [
        AccountProfileStore.set_default_profile,
        mod.SqlAlchemyAccountProfileStore.set_default_profile,
    ],
    ids=["port", "adapter"],
)
def test_a_move_requires_the_binding_version_in_the_port_and_the_adapter(
    move: Callable[..., Any],
) -> None:
    """No default, so no caller can leave the tag out and fall back to last-write-wins: a later
    `int | None = None` that skipped the check would pass every test that sends the keyword."""
    parameter = inspect.signature(move).parameters["expected_binding_version"]
    assert parameter.default is inspect.Parameter.empty


async def test_get_default_binding_answers_the_row_or_none_and_an_empty_grant_runs_no_sql() -> None:
    found = _Rel(_GATE_OK, _Result([{"id": str(_PROFILE), "default_binding_version": 7}]))
    binding = await _store(found).get_default_binding(_OWNER, _ACCOUNT)
    assert binding == DefaultBindingRow(account_id=_ACCOUNT, profile_id=_PROFILE, version=7)
    assert len(found.calls) == 2 and found.commits == 0
    assert _sql(found.calls[1]) == _sql(mod.binding_statement(_OWNER, _ACCOUNT))
    hidden = _Rel(_Result([]))  # a grant read runs without the owner gate
    assert await _store(hidden).get_default_binding(_GRANT, _ACCOUNT) is None
    assert len(hidden.calls) == 1
    empty = _Rel()
    assert (
        await _store(empty).get_default_binding(GrantScope(_CALLER, frozenset()), _ACCOUNT) is None
    )
    assert empty.calls == []


async def test_a_revision_reads_back_the_profile_it_recorded() -> None:
    ladder = json.loads(mod._ladder_json(_VALUES.tp_ladder or ()))
    payload = json.dumps({**_mapping(), "tp_ladder": ladder}, default=str)
    found = {
        "id": 7,
        "version": 3,
        "payload": payload,
        "changed_by": str(_CALLER),
        "changed_at": _T,
    }
    revision = await _store(_Rel(_GATE_OK, _Result([found]))).get_revision(
        _OWNER, _ACCOUNT, _PROFILE, 3
    )
    assert revision is not None and revision.version == 3 and revision.changed_by == _CALLER
    assert revision.profile.values == _VALUES


async def test_the_effective_read_runs_without_any_gate() -> None:
    rel = _Rel(_Result([_mapping()]))
    row = await _store(rel).effective_profile(_ACCOUNT, None)
    assert row is not None and len(rel.calls) == 1 and rel.commits == 0


async def test_cancellation_passes_through_unchanged() -> None:
    import asyncio

    rel = _Rel(_GATE_OK, raises=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await _store(rel).get_profile(_OWNER, _ACCOUNT, _PROFILE)


def test_a_dbapi_error_never_leaves_with_its_parameters() -> None:
    err: DBAPIError = _integrity("23514", "ap_trading_caps")
    with pytest.raises(AccountProfileStoreRuleError) as ei, mod._constraints():
        raise err
    assert "secret-name" not in repr(ei.value) and ei.value.__context__ is err
    assert ei.value.__suppress_context__
