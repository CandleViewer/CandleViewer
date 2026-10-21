"""Unit tests for `SqlAlchemyTradeGroupStore` (E28-T01 #905): the Core statements rendered for
asyncpg, the error mapping and every store path against a recording fake unit of work, and a row
the store cannot decode as the M13 facade answers it.

The codec, the port dataclasses and the name pins are test_trade_groups_port.py's. Real SQL runs
in tests/integration/storage/test_trade_groups_store_pg.py (CI only).
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
import structlog
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from candleviewer.accounts.errors import AccountsError
from candleviewer.accounts.trade_group_repository import TradeGroupRepository
from candleviewer.db import models
from candleviewer.domain.primitives import GroupId
from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories import accounts_sqlalchemy as accounts_mod
from candleviewer.storage.repositories import trade_groups_sqlalchemy as mod
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.storage.repositories.exchange_payload import MAX_CODE_CHARS, redact_exchange_text
from candleviewer.storage.repositories.orders_sqlalchemy import OMS_STATEMENT_TIMEOUT_MS
from candleviewer.storage.repositories.trade_groups import (
    ACCOUNT_NOT_LIVE,
    CREATE_ONLY_GROUP_COLUMNS,
    DEFINITION_NOT_LIVE,
    GROUP_PATCH_COLUMNS,
    LEG_PATCH_COLUMNS,
    OPEN_GROUP_STATUSES,
    PROFILE_CHANGED,
    TRADE_GROUP_CONFLICTS,
    TRADE_GROUP_RULES,
    UNPROTECTED_LEG_STATUSES,
    WRITE_ONCE_GROUP_COLUMNS,
    WRITE_ONCE_LEG_COLUMNS,
    GroupAnchor,
    GroupCreated,
    GroupExists,
    GroupPatch,
    JsonObject,
    LegPatch,
    NewTradeGroup,
    NewTradeGroupLeg,
    TradeGroupRecord,
    TradeGroupStoreConflictError,
    TradeGroupStoreRefusedError,
    TradeGroupStoreRuleError,
    TradeGroupStoreScopeDeniedError,
    TradeGroupStoreStaleError,
    render_json,
)

_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()
_T = datetime(2026, 10, 20, 9, tzinfo=UTC)
_CALLER = UUID(int=0x1001)
_GROUP = UUID(int=0x2001)
_DEFINITION = UUID(int=0x3001)
_ACCOUNT_A, _ACCOUNT_B = UUID(int=0x4002), UUID(int=0x4001)  # B sorts first
_PROFILE_A, _PROFILE_B = UUID(int=0x5002), UUID(int=0x5001)
_LEG_A, _LEG_B = UUID(int=0x6001), UUID(int=0x6002)
_REF = str(UUID(int=0x7001))
_BODY = hashlib.sha256(b'{"symbol":"BTCUSDT","side":"Buy"}').hexdigest()
_OWNER = OwnerScope(_CALLER)
_GRANT = GrantScope(_CALLER, frozenset({_ACCOUNT_A, _ACCOUNT_B}))
#: Synthetic, built at run time (SR-145): shaped like an API key (18+ letters and digits), so the
#: string rule replaces it, and a run of 18+ letters alone, which only the message rule replaces.
_CODE_KEY_SHAPED = "Q3w9" * 5
_MESSAGE_LETTER_RUN = "error sign! origin_string[" + "Qwerty" * 4 + "]"


def _snapshot(account: UUID, profile: UUID, version: int = 3) -> JsonObject:
    return {"profile_id": str(profile), "account_id": str(account), "version": version,
            "name": "Scalp", "leverage": "5"}  # fmt: skip


def _new_group(**over: Any) -> NewTradeGroup:
    values: dict[str, Any] = {
        "id": _GROUP, "client_group_ref": _REF, "client_body_sha256": _BODY, "created_by": _CALLER,
        "env": "demo", "symbol": "BTCUSDT", "side": "Buy", "status": "submitting",
        "leg_failure_policy": "all_or_none", "algo": "oco",
        "algo_params": {"legs": 2, "tp": "65000.5"}, "intent_note": "scalp the open",
        "origin": "manual", "origin_rule_id": None, "origin_rule_run_id": None,
        "definition_id": None, "requested_qty_mode": "risk_based",
        "requested_qty_value": Decimal("1"), "entry_type": "Limit",
        "entry_price": Decimal("63000.5"), "trigger_price": None, "trigger_by": None,
        "sl_price_hint": Decimal("62000"), "tp_price_hint": None, "is_paper": False,
    }  # fmt: skip
    return NewTradeGroup(**(values | over))


def _new_leg(
    leg_id: UUID = _LEG_A,
    account: UUID = _ACCOUNT_A,
    profile: UUID = _PROFILE_A,
    *,
    seq: int = 0,
    version: int = 3,
    **over: Any,
) -> NewTradeGroupLeg:
    values: dict[str, Any] = {
        "id": leg_id, "exchange_account_id": account, "account_profile_id": profile,
        "profile_version": version, "profile_snapshot": _snapshot(account, profile, version),
        "status": "pending", "sequence_no": seq, "target_qty": Decimal("0.010"),
        "resolved_leverage": Decimal("5"), "resolved_sl_price": Decimal("62000"),
        "resolved_tp_price": None, "risk_usd": Decimal("12.5"), "rejection_code": None,
        "rejection_message": None,
    }  # fmt: skip
    return NewTradeGroupLeg(**(values | over))


_NEW_GROUP = _new_group()
_LEGS = (_new_leg(_LEG_B, _ACCOUNT_B, _PROFILE_B, seq=1), _new_leg())


def _group_mapping(group: NewTradeGroup = _NEW_GROUP, **over: Any) -> dict[str, Any]:
    """A group row as asyncpg returns it: ids as strings here, `algo_params` as `jsonb` text."""
    m: dict[str, Any] = {
        f.name: getattr(group, f.name)
        for f in dataclasses.fields(group)
        if f.name != "client_body_sha256"
    }
    params = group.algo_params
    m["algo_params"] = None if params is None else json.dumps(params)  # jsonb re-spaces its text
    m |= {"id": str(group.id), "created_by": str(group.created_by), "submitted_at": None}
    m |= {"opened_at": None, "closed_at": None, "created_at": _T, "updated_at": _T}
    return m | over


def _leg_mapping(leg: NewTradeGroupLeg = _LEGS[1], **over: Any) -> dict[str, Any]:
    m: dict[str, Any] = {
        f.name: getattr(leg, f.name)
        for f in dataclasses.fields(leg)
        if f.name != "profile_snapshot"
    }
    m |= {"id": str(leg.id), "trade_group_id": str(_GROUP), "filled_qty": Decimal("0")}
    m |= {"avg_entry_price": None, "avg_exit_price": None, "native_sl_confirmed": False}
    m |= {"native_sl_confirmed_at": None, "realised_pnl": Decimal("0"), "fees_paid": Decimal("0")}
    m |= {"submitted_at": None, "closed_at": None, "created_at": _T, "updated_at": _T}
    return m | over


def _sql(stmt: Any) -> str:
    """The statement as asyncpg receives it, whitespace collapsed."""
    text = str(stmt.compile(dialect=_ASYNCPG, compile_kwargs={"render_postcompile": True}))
    return " ".join(text.split())


def _params(stmt: Any) -> dict[str, Any]:
    return dict(stmt.compile(dialect=_ASYNCPG).params)


def _binds_as_markers(sql: str) -> str:
    """Every asyncpg placeholder (`$3::TEXT[]`) and every named bind (`:caller`) as `:b`."""
    return re.sub(r"\$\d+(::[A-Z]+(\[\])?)?|:[a-z_]+\b", ":b", sql)


def _assignments(stmt: Any) -> list[str]:
    """The columns an UPDATE sets, in order."""
    clause = _sql(stmt).split(" SET ", 1)[1].split(" WHERE ", 1)[0]
    return re.findall(r"(?:^|, )([a-z_]+)=", clause)


def _wheres(sql: str) -> list[str]:
    """Each WHERE clause of the statement (subqueries' included), up to what ends it."""
    return [re.split(r" ORDER BY | RETURNING | FOR ", part)[0] for part in sql.split(" WHERE ")[1:]]


_FULL_LEG_PATCH = LegPatch(
    status="filled", filled_qty=Decimal("0.010"), avg_entry_price=Decimal("63000.5"),
    avg_exit_price=Decimal("64000"), native_sl_confirmed=True, native_sl_confirmed_at=_T,
    realised_pnl=Decimal("-1.25"), fees_paid=Decimal("0.03"), rejection_code=_CODE_KEY_SHAPED,
    rejection_message=_MESSAGE_LETTER_RUN, submitted_at=_T, closed_at=_T,
)  # fmt: skip
_FULL_GROUP_PATCH = GroupPatch(status="closed", submitted_at=_T, opened_at=_T, closed_at=_T)

#: Every builder, built: the scoped ones under a grant scope (the owner variant is tested apart).
_STATEMENTS: dict[str, Any] = {
    "anchor_statement": mod.anchor_statement(_CALLER, _REF, _BODY),
    "insert_group_statement": mod.insert_group_statement(_NEW_GROUP),
    "lock_definition_statement": mod.lock_definition_statement(_DEFINITION),
    "lock_accounts_statement": mod.lock_accounts_statement([_ACCOUNT_A, _ACCOUNT_B, _ACCOUNT_A]),
    "lock_profiles_statement": mod.lock_profiles_statement([_PROFILE_A, _PROFILE_B]),
    "insert_legs_statement": mod.insert_legs_statement(_GROUP, _LEGS),
    "lock_leg_statement": mod.lock_leg_statement(_GROUP, _LEG_A),
    "update_leg_statement": mod.update_leg_statement(_GROUP, _LEG_A, _FULL_LEG_PATCH),
    "lock_group_statement": mod.lock_group_statement(_GROUP),
    "update_group_statement": mod.update_group_statement(_GROUP, _FULL_GROUP_PATCH),
    "group_statement": mod.group_statement(_GROUP),
    "legs_statement": mod.legs_statement([_GROUP, UUID(int=0x2000)]),
    "leg_statement": mod.leg_statement(_LEG_A),
    "open_groups_statement": mod.open_groups_statement(),
    "unprotected_legs_statement": mod.unprotected_legs_statement(),
    "scoped_group_statement": mod.scoped_group_statement(_GRANT, _GROUP),
    "scoped_legs_statement": mod.scoped_legs_statement(_GRANT, _GROUP),
}


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None, scalar: Any = True) -> None:
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
    """A unit of work that answers the statement cap itself and every other `execute` with the
    next scripted item, a `_Result` or an exception to raise; it counts commits and rollbacks."""

    def __init__(self, *script: _Result | BaseException) -> None:
        self.script = list(script)
        self.calls: list[Any] = []
        self.caps: list[dict[str, Any]] = []
        self.commits = 0
        self.rollbacks = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        before = len(self.calls)

        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> _Result:
            if stmt is mod._SET_TIMEOUT:
                assert len(self.calls) == before, "the cap is a unit of work's first statement"
                self.caps.append(dict(params or {}))
                return _Result()
            self.calls.append(stmt)
            item = self.script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        async def commit() -> None:
            self.commits += 1

        try:
            yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)
        except BaseException:
            self.rollbacks += 1
            raise


def _store(rel: _Rel, **kwargs: Any) -> mod.SqlAlchemyTradeGroupStore:
    # The adapter takes the concrete SqlAlchemyRelationalRepository, as its siblings do; _Rel
    # mimics only its unit_of_work(), so the nominal type cannot match.
    return mod.SqlAlchemyTradeGroupStore(rel, **kwargs)  # type: ignore[arg-type]  # structural fake


_GATE_OK = _Result(scalar=True)
_INSERTED = _Result([_group_mapping()])
_ACCOUNTS_LIVE = _Result([{"id": str(_ACCOUNT_B)}, {"id": str(_ACCOUNT_A)}])
_PROFILES_LIVE = _Result(
    [
        {"id": str(_PROFILE_B), "exchange_account_id": str(_ACCOUNT_B), "version": 3},
        {"id": str(_PROFILE_A), "exchange_account_id": str(_ACCOUNT_A), "version": 3},
    ]
)


def _legs_inserted() -> _Result:
    """RETURNING in another order than the legs were given: the record sorts them."""
    return _Result([_leg_mapping(_LEGS[0]), _leg_mapping(_LEGS[1])])


# -- the statements -------------------------------------------------------------------------------


def test_every_statement_builder_is_scoped_or_system() -> None:
    # Self-discovering, so a builder added later cannot dodge the scope pins below.
    builders = {n for n in vars(mod) if n.endswith("_statement")}
    assert builders == mod.SCOPED_STATEMENTS | mod.SYSTEM_STATEMENTS == set(_STATEMENTS)
    assert not mod.SCOPED_STATEMENTS & mod.SYSTEM_STATEMENTS
    assert mod.SCOPED_STATEMENTS == {"scoped_group_statement", "scoped_legs_statement"}


@pytest.mark.parametrize("name", sorted(_STATEMENTS))
def test_only_the_scoped_statements_read_a_scope(name: str) -> None:
    sql = _sql(_STATEMENTS[name])
    scoped = "user_account_access" in sql or "user_roles" in sql
    assert scoped is (name in mod.SCOPED_STATEMENTS)


@pytest.mark.parametrize("name", sorted(mod.SCOPED_STATEMENTS))
def test_scoped_statements_carry_the_grant_predicate_and_bind_the_caller(name: str) -> None:
    stmt = _STATEMENTS[name]
    assert _binds_as_markers(mod._GRANT_VISIBLE) in _binds_as_markers(_sql(stmt))
    assert "uaa.can_view AND NOT uaa.frozen" in _sql(stmt)
    params = _params(stmt)
    assert params["caller"] == str(_CALLER)
    assert params["granted"] == sorted([str(_ACCOUNT_A), str(_ACCOUNT_B)])
    assert "ANY(CAST($" in _sql(stmt) and "::TEXT[] AS uuid[])" in _sql(stmt)


@pytest.mark.parametrize("build", [mod.scoped_group_statement, mod.scoped_legs_statement])
def test_scoped_statements_carry_the_owner_predicate_for_an_owner(build: Any) -> None:
    stmt = build(_OWNER, _GROUP)
    sql = _sql(stmt)
    assert _binds_as_markers(mod._OWNER_PRED) in _binds_as_markers(sql)
    assert "user_account_access" not in sql and _params(stmt)["caller"] == str(_CALLER)


def test_owner_gate_and_predicate_equal_the_accounts_store() -> None:
    assert mod._OWNER_GATE.text == accounts_mod._OWNER_GATE.text
    assert mod._OWNER_PRED == accounts_mod._OWNER_PRED
    assert mod._OWNER_GATE.text == f"SELECT {mod._OWNER_PRED}"
    assert "uaa.can_view AND NOT uaa.frozen" in accounts_mod._GRANT_PRED
    assert "uaa.can_view AND NOT uaa.frozen" in mod._GRANT_VISIBLE


#: The SR-E28-21 predicate as the PR-2b design states it; the store parenthesises it.
_SR_E28_21 = """
EXISTS (SELECT 1 FROM trade_group_legs vl WHERE vl.trade_group_id = trade_groups.id)
AND NOT EXISTS (SELECT 1 FROM trade_group_legs vl WHERE vl.trade_group_id = trade_groups.id
  AND NOT (vl.exchange_account_id = ANY(CAST(:granted AS uuid[]))
    AND EXISTS (SELECT 1 FROM exchange_accounts vea WHERE vea.id = vl.exchange_account_id
      AND vea.deleted_at IS NULL)
    AND EXISTS (SELECT 1 FROM user_account_access uaa WHERE uaa.user_id = CAST(:caller AS uuid)
      AND uaa.exchange_account_id = vl.exchange_account_id AND uaa.can_view AND NOT uaa.frozen)))
"""


def test_the_grant_predicate_is_sr_e28_21_verbatim() -> None:
    assert mod._GRANT_VISIBLE == "(" + " ".join(_SR_E28_21.split()) + ")"


def test_the_anchor_is_read_only_with_its_creator() -> None:
    naming = [
        (name, where)
        for name, stmt in _STATEMENTS.items()
        for where in _wheres(_sql(stmt))
        if "client_group_ref" in where
    ]
    assert [name for name, _ in naming] == ["anchor_statement"]  # the test is not vacuous
    assert all("created_by = $" in where for _, where in naming)
    assert _params(_STATEMENTS["anchor_statement"])["created_by_1"] == _CALLER


@pytest.mark.parametrize("name", sorted(_STATEMENTS))
def test_no_statement_returns_the_body_fingerprint(name: str) -> None:
    returned = set(_STATEMENTS[name].exported_columns.keys())
    assert "client_body_sha256" not in returned
    assert ("profile_snapshot" in returned) is (name == "leg_statement")


def test_the_anchor_answers_whether_the_fingerprint_matches_without_returning_it() -> None:
    sql = _sql(_STATEMENTS["anchor_statement"])
    assert sql.startswith(
        "SELECT trade_groups.id, trade_groups.client_body_sha256 = $1::VARCHAR AS body_matches "
        "FROM trade_groups WHERE trade_groups.created_by = $2::UUID "
        "AND trade_groups.client_group_ref = $3::VARCHAR"
    )


def test_the_group_insert_does_nothing_on_the_creator_ref_conflict() -> None:
    sql = _sql(_STATEMENTS["insert_group_statement"])
    assert sql.startswith("INSERT INTO trade_groups (")
    assert (
        " ON CONFLICT (created_by, client_group_ref) DO NOTHING RETURNING trade_groups.id, " in sql
    )
    assert "client_body_sha256" in sql.split(" VALUES ", 1)[0]  # written, never returned
    bound = _params(_STATEMENTS["insert_group_statement"])
    assert bound["client_body_sha256"] == _BODY and bound["created_by"] == _CALLER


def test_lock_statements_take_live_rows_for_share_in_id_order() -> None:
    definition = _sql(_STATEMENTS["lock_definition_statement"])
    assert definition.endswith(
        "WHERE trade_group_definitions.id = $1::UUID "
        "AND trade_group_definitions.deleted_at IS NULL FOR SHARE"
    )
    accounts = _STATEMENTS["lock_accounts_statement"]
    assert _sql(accounts).endswith(
        "WHERE exchange_accounts.id IN ($1::UUID, $2::UUID) AND exchange_accounts.deleted_at "
        "IS NULL ORDER BY exchange_accounts.id FOR SHARE"
    )
    assert _params(accounts)["id_1"] == [_ACCOUNT_B, _ACCOUNT_A]  # distinct, in id order
    profiles = _STATEMENTS["lock_profiles_statement"]
    assert _sql(profiles).startswith(
        "SELECT account_profiles.id, account_profiles.exchange_account_id, "
        "account_profiles.version FROM account_profiles WHERE account_profiles.id IN ("
    )
    assert _sql(profiles).endswith(
        "AND account_profiles.deleted_at IS NULL ORDER BY account_profiles.id FOR SHARE"
    )
    assert _params(profiles)["id_1"] == [_PROFILE_B, _PROFILE_A]


def test_row_locks_for_updates_are_no_key_and_scoped_to_the_group() -> None:
    leg = _sql(_STATEMENTS["lock_leg_statement"])
    assert leg == (
        "SELECT trade_group_legs.status FROM trade_group_legs WHERE "
        "trade_group_legs.trade_group_id = $1::UUID AND trade_group_legs.id = $2::UUID "
        "FOR NO KEY UPDATE"
    )
    group = _sql(_STATEMENTS["lock_group_statement"])
    assert group.endswith("WHERE trade_groups.id = $1::UUID FOR NO KEY UPDATE")
    update = _sql(_STATEMENTS["update_leg_statement"])
    assert "WHERE trade_group_legs.trade_group_id = $" in update


_RESOLVED_LEG_COLUMNS = frozenset(
    {"resolved_leverage", "resolved_sl_price", "resolved_tp_price", "target_qty", "risk_usd",
     "sequence_no"}
)  # fmt: skip


def test_updates_never_set_a_write_once_create_only_or_resolved_column() -> None:
    leg = _assignments(_STATEMENTS["update_leg_statement"])
    assert leg == list(LEG_PATCH_COLUMNS)  # every patch field, in table order, and nothing else
    assert not set(leg) & (WRITE_ONCE_LEG_COLUMNS | _RESOLVED_LEG_COLUMNS | {"updated_at"})
    group = _assignments(_STATEMENTS["update_group_statement"])
    assert (
        group == list(GROUP_PATCH_COLUMNS) == ["status", "submitted_at", "opened_at", "closed_at"]
    )
    assert not set(group) & (WRITE_ONCE_GROUP_COLUMNS | CREATE_ONLY_GROUP_COLUMNS | {"updated_at"})


def test_an_update_sets_only_the_columns_its_patch_names() -> None:
    stmt = mod.update_leg_statement(_GROUP, _LEG_A, LegPatch(fees_paid=Decimal("0.01")))
    assert _assignments(stmt) == ["fees_paid"]
    assert _assignments(mod.update_group_statement(_GROUP, GroupPatch(status="open"))) == ["status"]


_GROUP_READS = (
    "insert_group_statement", "update_group_statement", "group_statement", "open_groups_statement",
    "scoped_group_statement",
)  # fmt: skip


def test_the_failure_policy_is_inserted_as_named_returned_and_never_updated() -> None:
    """The writer's policy is bound, never the column default, every group read returns it, and
    no UPDATE sets it (`trg_tg_write_once`): B2, the unwind and a restart read it from the row."""
    assert _params(_STATEMENTS["insert_group_statement"])["leg_failure_policy"] == "all_or_none"
    for name in _GROUP_READS:
        assert "leg_failure_policy" in _STATEMENTS[name].exported_columns.keys(), name
    assert "leg_failure_policy" in WRITE_ONCE_GROUP_COLUMNS
    assert "leg_failure_policy" not in GROUP_PATCH_COLUMNS
    assert "leg_failure_policy" not in _assignments(_STATEMENTS["update_group_statement"])


def test_set_once_columns_use_coalesce() -> None:
    leg = _sql(_STATEMENTS["update_leg_statement"])
    assert "submitted_at=coalesce(trade_group_legs.submitted_at, $" in leg
    assert re.search(r"closed_at=\$\d+::TIMESTAMP WITH TIME ZONE", leg)
    group = _sql(_STATEMENTS["update_group_statement"])
    assert "submitted_at=coalesce(trade_groups.submitted_at, $" in group
    assert "opened_at=coalesce(trade_groups.opened_at, $" in group
    assert re.search(r"closed_at=\$\d+::TIMESTAMP WITH TIME ZONE", group)
    assert "coalesce" not in group.split("closed_at=", 1)[1].split(" WHERE ", 1)[0]
    assert mod.SET_ONCE_LEG_COLUMNS == {"submitted_at"}
    assert mod.SET_ONCE_GROUP_COLUMNS == {"submitted_at", "opened_at"}


def _index_statuses(table: sa.Table, index: str) -> set[str]:
    where = next(
        str(ix.dialect_options["postgresql"]["where"]) for ix in table.indexes if ix.name == index
    )
    return set(re.findall(r"'([a-z_]+)'", where.split(" IN ", 1)[1].split(")", 1)[0]))


def test_the_open_and_unprotected_reads_render_the_index_predicates_as_literals() -> None:
    opened = _sql(_STATEMENTS["open_groups_statement"])
    assert opened.endswith(
        "FROM trade_groups WHERE trade_groups.status IN ('closing', 'open', 'partially_open', "
        "'submitting') ORDER BY trade_groups.created_at, trade_groups.id"
    )
    assert "$" not in opened  # no bound array: a generic plan could not match the partial index
    assert _index_statuses(models.trade_groups, "ix_tg_open") == OPEN_GROUP_STATUSES
    unprotected = _sql(_STATEMENTS["unprotected_legs_statement"])
    assert unprotected.endswith(
        "FROM trade_group_legs JOIN trade_groups ON trade_groups.id = "
        "trade_group_legs.trade_group_id WHERE trade_group_legs.status IN ('filled', 'open', "
        "'partially_filled') AND NOT trade_group_legs.native_sl_confirmed "
        "ORDER BY trade_group_legs.trade_group_id, trade_group_legs.sequence_no, "
        "trade_group_legs.id"
    )
    assert "$" not in unprotected and "deleted_at" not in opened + unprotected
    assert _index_statuses(models.trade_group_legs, "ix_tgl_no_sl") == UNPROTECTED_LEG_STATUSES
    no_sl = next(ix for ix in models.trade_group_legs.indexes if ix.name == "ix_tgl_no_sl")
    assert "native_sl_confirmed = false" in str(no_sl.dialect_options["postgresql"]["where"])


@pytest.mark.parametrize("name", sorted(_STATEMENTS))
def test_no_statement_tests_a_flag_with_is_true_or_false(name: str) -> None:
    assert not re.search(r"\bIS (NOT )?(TRUE|FALSE)\b", _sql(_STATEMENTS[name]), re.IGNORECASE)


def test_rejection_text_is_redacted_before_it_is_bound() -> None:
    code = redact_exchange_text(_CODE_KEY_SHAPED, max_chars=MAX_CODE_CHARS)
    message = redact_exchange_text(_MESSAGE_LETTER_RUN, message=True)
    assert code != _CODE_KEY_SHAPED and message != _MESSAGE_LETTER_RUN
    assert redact_exchange_text(_MESSAGE_LETTER_RUN) == _MESSAGE_LETTER_RUN  # only the message rule
    rejected = _new_leg(
        status="rejected", resolved_sl_price=None, rejection_code=_CODE_KEY_SHAPED,
        rejection_message=_MESSAGE_LETTER_RUN,
    )  # fmt: skip
    inserted = _params(mod.insert_legs_statement(_GROUP, [rejected]))
    assert inserted["rejection_code_m0"] == code
    assert inserted["rejection_message_m0"] == message
    updated = _params(_STATEMENTS["update_leg_statement"])
    assert updated["rejection_code"] == code and updated["rejection_message"] == message
    for stmt in (
        mod.insert_legs_statement(_GROUP, [rejected]),
        _STATEMENTS["update_leg_statement"],
    ):
        assert not {_CODE_KEY_SHAPED, _MESSAGE_LETTER_RUN} & set(map(str, _params(stmt).values()))


def test_an_oversize_code_is_bound_as_the_oversize_marker() -> None:
    long_code = "E" * (MAX_CODE_CHARS + 1)
    bound = _params(mod.update_leg_statement(_GROUP, _LEG_A, LegPatch(rejection_code=long_code)))
    assert bound["rejection_code"] == redact_exchange_text(long_code, max_chars=MAX_CODE_CHARS)
    assert bound["rejection_code"] != long_code


def test_json_columns_bind_text_and_none_binds_sql_null() -> None:
    group = _STATEMENTS["insert_group_statement"]
    assert "CAST($" in _sql(group) and "::VARCHAR AS JSONB)" in _sql(group)
    assert render_json({"legs": 2, "tp": "65000.5"}) in _params(group).values()
    plain = mod.insert_group_statement(_new_group(algo="none", algo_params=None))
    values = _sql(plain).split(" VALUES (", 1)[1].split(") ON CONFLICT", 1)[0]
    assert re.findall(r"\bNULL\b", values) == ["NULL"]  # SQL NULL: every other None is a bind
    assert "JSONB" not in _sql(plain)  # never JSON `null`, which a cast of 'null' would be
    assert "algo_params" not in _params(plain) and "null" not in _params(plain).values()
    legs = _params(_STATEMENTS["insert_legs_statement"])
    for leg in _LEGS:
        assert render_json(leg.profile_snapshot) in legs.values()
    assert _sql(_STATEMENTS["insert_legs_statement"]).count("::VARCHAR AS JSONB)") == len(_LEGS)


def test_json_columns_are_read_as_text_so_integers_stay_exact() -> None:
    assert "CAST(trade_groups.algo_params AS TEXT) AS algo_params" in _sql(
        _STATEMENTS["group_statement"]
    )
    assert "CAST(trade_group_legs.profile_snapshot AS TEXT) AS profile_snapshot" in _sql(
        _STATEMENTS["leg_statement"]
    )


def test_the_read_lists_are_every_column_but_the_two_exceptions_in_table_order() -> None:
    groups = [c.name for c in models.trade_groups.columns if c.name != "client_body_sha256"]
    legs = [c.name for c in models.trade_group_legs.columns if c.name != "profile_snapshot"]
    assert [c.key for c in mod.GROUP_COLUMNS] == list(mod.GROUP_FIELDS) == groups
    assert [c.key for c in mod.LEG_COLUMNS] == list(mod.LEG_FIELDS) == legs


def test_the_legs_read_takes_the_group_ids_as_one_uuid_array() -> None:
    stmt = _STATEMENTS["legs_statement"]
    assert _sql(stmt).endswith(
        "WHERE trade_group_legs.trade_group_id = ANY (CAST($1::TEXT[] AS UUID[])) ORDER BY "
        "trade_group_legs.trade_group_id, trade_group_legs.sequence_no, trade_group_legs.id"
    )
    assert _params(stmt)["group_ids"] == sorted([str(UUID(int=0x2000)), str(_GROUP)])


def test_the_legs_insert_writes_every_leg_in_one_statement_with_its_group() -> None:
    stmt = _STATEMENTS["insert_legs_statement"]
    sql = _sql(stmt)
    assert sql.startswith("INSERT INTO trade_group_legs (") and sql.count("INSERT") == 1
    assert sql.split(" VALUES ", 1)[1].count("), (") == len(_LEGS) - 1
    bound = _params(stmt)
    assert bound["trade_group_id_m0"] == bound["trade_group_id_m1"] == _GROUP
    with pytest.raises(ValueError, match="at least one leg"):
        mod.insert_legs_statement(_GROUP, [])


# -- the error mapping -----------------------------------------------------------------------------


class _DriverError(Exception):
    def __init__(
        self, sqlstate: str | None, constraint_name: str | None = None, *, diag: bool = False
    ) -> None:
        super().__init__("violates a constraint\nDETAIL:  Failing row contains (secret-name)")
        self.sqlstate = sqlstate
        if diag:  # psycopg's spelling: the name only on `.diag`
            self.diag = SimpleNamespace(constraint_name=constraint_name)
        else:
            self.constraint_name = constraint_name


def _integrity(state: str, constraint: str | None, *, diag: bool = False) -> IntegrityError:
    return IntegrityError(
        "UPDATE trade_group_legs", {"rejection_message": "secret-name"},
        _DriverError(state, constraint, diag=diag),
    )  # fmt: skip


async def _update_raising(error: BaseException) -> None:
    rel = _Rel(_Result([{"status": "pending"}]), error)
    try:
        await _store(rel).update_leg(_GROUP, _LEG_A, LegPatch(status="submitted"))
    finally:
        assert rel.commits == 0 and rel.rollbacks == 1


def _assert_unchained(err: BaseException) -> None:
    assert err.__cause__ is None and err.__suppress_context__
    assert "secret-name" not in str(err) and "secret-name" not in repr(err)


@pytest.mark.parametrize("rule", sorted(TRADE_GROUP_RULES))
async def test_errors_map_by_constraint_name_and_carry_no_value(rule: str) -> None:
    state = "23503" if rule.endswith(("_fkey", "_revision")) else "23514"
    with pytest.raises(TradeGroupStoreRuleError) as ei:
        await _update_raising(_integrity(state, rule))
    assert ei.value.rule == rule and str(ei.value) == rule
    _assert_unchained(ei.value)


@pytest.mark.parametrize("constraint", sorted(TRADE_GROUP_CONFLICTS))
async def test_a_unique_violation_maps_to_its_conflict(constraint: str) -> None:
    with pytest.raises(TradeGroupStoreConflictError) as ei:
        await _update_raising(_integrity("23505", constraint))
    assert ei.value.constraint == constraint and str(ei.value) == constraint
    _assert_unchained(ei.value)


async def test_a_name_only_on_diag_is_found() -> None:
    with pytest.raises(TradeGroupStoreRuleError) as ei:
        await _update_raising(_integrity("23514", "tgl_sl_conf", diag=True))
    assert ei.value.rule == "tgl_sl_conf"


@pytest.mark.parametrize(
    ("state", "constraint"),
    [
        ("23514", "tgd_name"),  # another table's rule
        ("23505", "ux_tgd_name"),
        ("23514", None),
        ("22003", None),  # numeric overflow: no constraint
        ("57014", None),  # the statement cap
        ("40P01", None),
    ],
)
async def test_any_other_refusal_leaves_as_its_sqlstate_only(
    state: str, constraint: str | None
) -> None:
    with pytest.raises(StorageQueryFailed) as ei:
        await _update_raising(_integrity(state, constraint))
    _assert_unchained(ei.value)


@pytest.mark.parametrize(
    "error",
    [
        OSError("refused"),
        sa.exc.TimeoutError("pool"),
        OperationalError("SELECT", {}, _DriverError("08006")),
        OperationalError("SELECT", {}, _DriverError("57P01")),
        OperationalError("SELECT", {}, _DriverError("53300")),
    ],
    ids=["os-error", "pool-timeout", "lost-08006", "shutdown-57P01", "full-53300"],
)
async def test_a_connection_the_store_cannot_get_or_loses_is_the_tier_unavailable(
    error: Exception,
) -> None:
    with pytest.raises(StorageTierUnavailable) as ei:
        await _update_raising(error)
    assert ei.value.__cause__ is None


def test_a_dbapi_error_never_leaves_with_its_parameters() -> None:
    err: DBAPIError = _integrity("23514", "tgl_filled_rng")
    with pytest.raises(TradeGroupStoreRuleError) as ei, mod._constraints():
        raise err
    assert "secret-name" not in repr(ei.value) and ei.value.__context__ is err
    assert ei.value.__suppress_context__


async def test_cancellation_passes_through_unchanged() -> None:
    with pytest.raises(asyncio.CancelledError):
        await _update_raising(asyncio.CancelledError())


# -- the store's paths -----------------------------------------------------------------------------


@pytest.mark.parametrize("timeout", [0, -1, True, 2.5, "2000"])
def test_the_statement_cap_is_an_int_of_at_least_one(timeout: Any) -> None:
    with pytest.raises(ValueError, match="statement_timeout_ms"):
        _store(_Rel(), statement_timeout_ms=timeout)


async def test_every_unit_of_work_caps_its_statements_first() -> None:
    rel = _Rel(_Result([]), _Result([]))
    await _store(rel).find_anchor(_CALLER, _REF, _BODY)
    await _store(rel, statement_timeout_ms=750).load_group(_GROUP)
    assert rel.caps == [{"timeout": "2000"}, {"timeout": "750"}]
    assert OMS_STATEMENT_TIMEOUT_MS == 2000


async def test_empty_grant_scope_runs_no_sql() -> None:
    rel = _Rel()
    empty = GrantScope(_CALLER, frozenset())
    assert await _store(rel).get_group(empty, _GROUP) is None
    assert rel.calls == [] and rel.caps == []


async def test_owner_scope_runs_the_gate_first_and_a_non_owner_is_refused() -> None:
    denied = _Rel(_Result(scalar=False))
    with pytest.raises(TradeGroupStoreScopeDeniedError):
        await _store(denied).get_group(_OWNER, _GROUP)
    assert len(denied.calls) == 1 and denied.calls[0] is mod._OWNER_GATE
    assert denied.rollbacks == 1
    rel = _Rel(_GATE_OK, _Result([_group_mapping()]), _Result([_leg_mapping()]))
    record = await _store(rel).get_group(_OWNER, _GROUP)
    assert record is not None and [leg.id for leg in record.legs] == [_LEG_A]
    assert rel.calls[0] is mod._OWNER_GATE and len(rel.calls) == 3
    assert "user_roles" in _sql(rel.calls[1]) and "user_roles" in _sql(rel.calls[2])


async def test_a_grant_read_runs_without_the_gate_and_an_invisible_group_reads_as_missing() -> None:
    rel = _Rel(_Result([]))
    assert await _store(rel).get_group(_GRANT, _GROUP) is None
    assert len(rel.calls) == 1 and "user_account_access" in _sql(rel.calls[0])
    assert rel.commits == 0


async def test_a_grant_read_is_all_or_nothing_across_its_two_statements() -> None:
    """SR-E28-21: a grant frozen or revoked, or a leg account soft-deleted, between the group
    read and the legs read leaves no leg to read; a grant scope then reads the group as missing,
    never as a group without legs, while an owner, who may see a leg-less group, keeps it."""
    shown = _Rel(_Result([_group_mapping()]), _Result([_leg_mapping()]))
    record = await _store(shown).get_group(_GRANT, _GROUP)
    assert record is not None and [leg.id for leg in record.legs] == [_LEG_A]
    vanished = _Rel(_Result([_group_mapping()]), _Result([]))
    assert await _store(vanished).get_group(_GRANT, _GROUP) is None
    assert len(vanished.calls) == 2 and vanished.commits == 0
    owner = _Rel(_GATE_OK, _Result([_group_mapping()]), _Result([]))
    kept = await _store(owner).get_group(_OWNER, _GROUP)
    assert kept is not None and kept.group.id == _GROUP and kept.legs == ()


async def test_find_anchor_answers_the_group_and_whether_the_body_matches() -> None:
    rel = _Rel(_Result([{"id": str(_GROUP), "body_matches": False}]), _Result([]))
    assert await _store(rel).find_anchor(_CALLER, _REF, _BODY) == GroupAnchor(_GROUP, False)
    assert await _store(rel).find_anchor(_CALLER, _REF, _BODY) is None
    assert rel.commits == 0 and all(
        _sql(c) == _sql(_STATEMENTS["anchor_statement"]) for c in rel.calls
    )


async def test_create_refuses_no_legs_before_any_sql() -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match="at least one leg"):
        await _store(rel).create_group(_NEW_GROUP, [])
    assert rel.calls == [] and rel.caps == []


class _Hook:
    """A write-ahead hook recording the records it saw and the commits before it ran."""

    def __init__(self, rel: _Rel, raises: BaseException | None = None) -> None:
        self.rel, self.raises = rel, raises
        self.seen: list[tuple[TradeGroupRecord, int]] = []

    async def __call__(self, record: TradeGroupRecord) -> None:
        self.seen.append((record, self.rel.commits))
        if self.raises is not None:
            raise self.raises


async def test_create_returns_exists_and_never_calls_the_hook_on_a_conflict() -> None:
    rel = _Rel(_Result([]), _Result([{"id": str(_GROUP), "body_matches": True}]))
    hook = _Hook(rel)
    outcome = await _store(rel).create_group(_NEW_GROUP, _LEGS, write_ahead=hook)
    assert outcome == GroupExists(GroupAnchor(_GROUP, True))
    assert hook.seen == [] and rel.commits == 0 and len(rel.calls) == 2
    assert _sql(rel.calls[1]) == _sql(_STATEMENTS["anchor_statement"])  # with its creator


async def test_create_reads_a_vanished_anchor_as_its_conflict() -> None:
    rel = _Rel(_Result([]), _Result([]))
    with pytest.raises(TradeGroupStoreConflictError) as ei:
        await _store(rel).create_group(_NEW_GROUP, _LEGS)
    assert ei.value.constraint == "ux_tg_creator_ref" and rel.commits == 0


_PROFILE_STALE = _Result(
    [
        {"id": str(_PROFILE_B), "exchange_account_id": str(_ACCOUNT_B), "version": 3},
        {"id": str(_PROFILE_A), "exchange_account_id": str(_ACCOUNT_A), "version": 4},
    ]
)
_PROFILE_MISSING = _Result(
    [{"id": str(_PROFILE_B), "exchange_account_id": str(_ACCOUNT_B), "version": 3}]
)
_PROFILE_MOVED = _Result(
    [
        {"id": str(_PROFILE_B), "exchange_account_id": str(_ACCOUNT_B), "version": 3},
        {"id": str(_PROFILE_A), "exchange_account_id": str(_ACCOUNT_B), "version": 3},
    ]
)


@pytest.mark.parametrize(
    ("group", "script", "reason"),
    [
        (_new_group(definition_id=_DEFINITION), [_Result([])], DEFINITION_NOT_LIVE),
        (_NEW_GROUP, [_Result([{"id": str(_ACCOUNT_A)}])], ACCOUNT_NOT_LIVE),
        (_NEW_GROUP, [_ACCOUNTS_LIVE, _PROFILE_STALE], PROFILE_CHANGED),
        (_NEW_GROUP, [_ACCOUNTS_LIVE, _PROFILE_MISSING], PROFILE_CHANGED),
        (_NEW_GROUP, [_ACCOUNTS_LIVE, _PROFILE_MOVED], PROFILE_CHANGED),
    ],
    ids=["definition", "account", "profile-version", "profile-missing", "profile-account"],
)
async def test_create_refuses_before_inserting_legs(
    group: NewTradeGroup, script: list[_Result], reason: str
) -> None:
    rel = _Rel(_INSERTED, *script)
    hook = _Hook(rel)
    with pytest.raises(TradeGroupStoreRefusedError) as ei:
        await _store(rel).create_group(group, _LEGS, write_ahead=hook)
    assert ei.value.reason == reason and str(ei.value) == reason
    assert not any(_sql(c).startswith("INSERT INTO trade_group_legs") for c in rel.calls)
    assert hook.seen == [] and rel.commits == 0 and rel.rollbacks == 1  # the group rolls back


async def test_create_locks_definition_accounts_and_profiles_in_order_then_inserts_legs() -> None:
    rel = _Rel(_INSERTED, _Result([{"id": str(_DEFINITION)}]), _ACCOUNTS_LIVE, _PROFILES_LIVE,
               _legs_inserted())  # fmt: skip
    group = _new_group(definition_id=_DEFINITION)
    outcome = await _store(rel).create_group(group, _LEGS)
    assert isinstance(outcome, GroupCreated) and rel.commits == 1
    sqls = [_sql(c) for c in rel.calls]
    assert sqls[0].startswith("INSERT INTO trade_groups")
    assert sqls[1:4] == [
        _sql(mod.lock_definition_statement(_DEFINITION)),
        _sql(mod.lock_accounts_statement([_ACCOUNT_A, _ACCOUNT_B])),
        _sql(mod.lock_profiles_statement([_PROFILE_A, _PROFILE_B])),
    ]
    assert sqls[4] == _sql(mod.insert_legs_statement(_GROUP, _LEGS))


async def test_create_without_a_definition_locks_no_definition() -> None:
    rel = _Rel(_INSERTED, _ACCOUNTS_LIVE, _PROFILES_LIVE, _legs_inserted())
    outcome = await _store(rel).create_group(_NEW_GROUP, _LEGS)
    assert isinstance(outcome, GroupCreated) and len(rel.calls) == 4
    assert not any("trade_group_definitions" in _sql(c) for c in rel.calls)


async def test_create_awaits_the_hook_before_the_commit() -> None:
    rel = _Rel(_INSERTED, _ACCOUNTS_LIVE, _PROFILES_LIVE, _legs_inserted())
    hook = _Hook(rel)
    outcome = await _store(rel).create_group(_NEW_GROUP, _LEGS, write_ahead=hook)
    assert isinstance(outcome, GroupCreated) and rel.commits == 1
    assert hook.seen == [(outcome.record, 0)]  # once, with the stored rows, before the commit
    record = outcome.record
    assert record.group.id == _GROUP and record.group.created_by == _CALLER
    assert record.group.algo_params == {"legs": 2, "tp": "65000.5"}
    assert record.group.leg_failure_policy == "all_or_none"
    assert [(leg.sequence_no, leg.id) for leg in record.legs] == [(0, _LEG_A), (1, _LEG_B)]
    assert all(isinstance(leg.trade_group_id, UUID) for leg in record.legs)


async def test_a_raising_hook_commits_nothing_and_its_error_passes() -> None:
    rel = _Rel(_INSERTED, _ACCOUNTS_LIVE, _PROFILES_LIVE, _legs_inserted())
    hook = _Hook(rel, RuntimeError("audit store down"))
    with pytest.raises(RuntimeError, match="audit store down"):
        await _store(rel).create_group(_NEW_GROUP, _LEGS, write_ahead=hook)
    assert len(hook.seen) == 1 and rel.commits == 0 and rel.rollbacks == 1


async def test_a_raw_os_error_from_the_hook_reads_as_the_database_unreachable() -> None:
    """Why the hook raises its own typed refusal (the `GroupWriteAhead` contract)."""
    rel = _Rel(_INSERTED, _ACCOUNTS_LIVE, _PROFILES_LIVE, _legs_inserted())
    with pytest.raises(StorageTierUnavailable):
        await _store(rel).create_group(
            _NEW_GROUP, _LEGS, write_ahead=_Hook(rel, ConnectionError("audit disk"))
        )
    assert rel.commits == 0


async def test_a_hook_timeout_is_write_ahead_timeout_not_tier_unavailable() -> None:
    assert issubclass(WriteAheadTimeout, OSError)  # a TimeoutError: why the clause order matters
    rel = _Rel(_INSERTED, _ACCOUNTS_LIVE, _PROFILES_LIVE, _legs_inserted())

    async def hangs(record: TradeGroupRecord) -> None:
        await asyncio.Event().wait()

    store = _store(rel, audit_timeout_s=0.01)
    with pytest.raises(WriteAheadTimeout) as ei:
        await store.create_group(_NEW_GROUP, _LEGS, write_ahead=hangs)
    assert not isinstance(ei.value, StorageTierUnavailable)
    assert rel.commits == 0 and rel.rollbacks == 1


async def test_a_refused_leg_insert_rolls_the_group_back() -> None:
    rel = _Rel(
        _INSERTED, _ACCOUNTS_LIVE, _PROFILES_LIVE, _integrity("23505", "ux_tgl_group_account")
    )
    hook = _Hook(rel)
    with pytest.raises(TradeGroupStoreConflictError):
        await _store(rel).create_group(_NEW_GROUP, _LEGS, write_ahead=hook)
    assert hook.seen == [] and rel.commits == 0 and rel.rollbacks == 1


async def test_update_missing_returns_none_and_stale_raises_without_update() -> None:
    missing = _Rel(_Result([]))
    assert await _store(missing).update_leg(_GROUP, _LEG_A, LegPatch(status="open")) is None
    assert len(missing.calls) == 1 and missing.commits == 0
    stale = _Rel(_Result([{"status": "pending"}]))
    with pytest.raises(TradeGroupStoreStaleError):
        await _store(stale).update_leg(
            _GROUP, _LEG_A, LegPatch(status="open"), expected_status="submitted"
        )
    assert len(stale.calls) == 1 and stale.commits == 0 and stale.rollbacks == 1
    gone = _Rel(_Result([]))
    assert await _store(gone).update_group(_GROUP, GroupPatch(status="open")) is None
    assert len(gone.calls) == 1 and gone.commits == 0
    moved = _Rel(_Result([{"status": "open"}]))
    with pytest.raises(TradeGroupStoreStaleError):
        await _store(moved).update_group(
            _GROUP, GroupPatch(status="closing"), expected_status="partially_open"
        )
    assert len(moved.calls) == 1 and moved.commits == 0


async def test_update_leg_writes_under_the_row_lock_and_returns_the_stored_row() -> None:
    stored = _leg_mapping(status="submitted", submitted_at=_T)
    rel = _Rel(_Result([{"status": "pending"}]), _Result([stored]))
    patch = LegPatch(status="submitted", submitted_at=_T)
    row = await _store(rel).update_leg(_GROUP, _LEG_A, patch, expected_status="pending")
    assert row is not None and row.status == "submitted" and row.submitted_at == _T
    assert row.id == _LEG_A and row.trade_group_id == _GROUP and rel.commits == 1
    assert _sql(rel.calls[0]).endswith("FOR NO KEY UPDATE")
    assert _sql(rel.calls[1]) == _sql(mod.update_leg_statement(_GROUP, _LEG_A, patch))


async def test_update_group_writes_under_the_row_lock_and_returns_the_stored_row() -> None:
    rel = _Rel(_Result([{"status": "submitting"}]), _Result([_group_mapping(status="open")]))
    patch = GroupPatch(status="open", opened_at=_T)
    row = await _store(rel).update_group(_GROUP, patch, expected_status="submitting")
    assert row is not None and row.status == "open" and row.id == _GROUP and rel.commits == 1
    assert _sql(rel.calls[1]) == _sql(mod.update_group_statement(_GROUP, patch))


async def test_load_group_reads_the_group_then_its_legs_in_order() -> None:
    rel = _Rel(_Result([_group_mapping()]), _legs_inserted())
    record = await _store(rel).load_group(_GROUP)
    assert record is not None and rel.commits == 0
    assert [leg.id for leg in record.legs] == [_LEG_A, _LEG_B]
    assert _params(rel.calls[1])["group_ids"] == [str(_GROUP)]
    missing = _Rel(_Result([]))
    assert await _store(missing).load_group(_GROUP) is None and len(missing.calls) == 1


async def test_load_leg_decodes_the_snapshot_exactly() -> None:
    snapshot = json.dumps({**_snapshot(_ACCOUNT_A, _PROFILE_A), "big": 10**20})
    rel = _Rel(_Result([_leg_mapping(profile_snapshot=snapshot)]), _Result([]))
    found = await _store(rel).load_leg(_LEG_A)
    assert found is not None and found.leg.id == _LEG_A
    assert found.profile_snapshot["big"] == 10**20 and found.profile_snapshot["leverage"] == "5"
    assert await _store(rel).load_leg(_LEG_A) is None


async def test_a_stored_float_is_refused_on_read() -> None:
    rel = _Rel(_Result([_group_mapping(algo_params='{"tp": 1.5}')]), _Result([]))
    with pytest.raises(ValueError, match="fraction"):
        await _store(rel).load_group(_GROUP)


@pytest.mark.parametrize(
    ("script", "read"),
    [
        (
            [_Result([_group_mapping(algo_params='{"tp": 1.5}')]), _Result([])],
            lambda repo: repo.get(GroupId(_GROUP)),
        ),
        (
            [_Result([_leg_mapping(profile_snapshot='{"leverage": 1.5}')])],
            lambda repo: repo.leg_with_profile(_LEG_A),
        ),
    ],
    ids=["algo-params", "profile-snapshot"],
)
async def test_the_facade_fails_a_float_the_store_refuses_closed(
    script: list[_Result], read: Any
) -> None:
    """The refusal above reaches a caller of the M13 facade as its fail-closed `AccountsError`,
    logged with the error class only, never as a bare `ValueError`."""
    repo = TradeGroupRepository(_store(_Rel(*script)))
    with structlog.testing.capture_logs() as logs, pytest.raises(AccountsError) as ei:
        await read(repo)
    assert str(ei.value) == "stored trade group unreadable" and ei.value.__cause__ is None
    assert [(log["event"], log["error"]) for log in logs] == [
        ("trade_group.read_failed_closed", "ValueError")
    ]


async def test_list_open_groups_reads_legs_once_for_every_group() -> None:
    other = UUID(int=0x2000)
    rel = _Rel(
        _Result([_group_mapping(), _group_mapping(id=str(other))]),
        _Result([_leg_mapping(), _leg_mapping(_LEGS[0], trade_group_id=str(other))]),
    )
    records = await _store(rel).list_open_groups()
    assert [r.group.id for r in records] == [_GROUP, other]
    assert [[leg.id for leg in r.legs] for r in records] == [[_LEG_A], [_LEG_B]]
    assert len(rel.calls) == 2 and _params(rel.calls[1])["group_ids"] == sorted(
        [str(_GROUP), str(other)]
    )
    none = _Rel(_Result([]))
    assert await _store(none).list_open_groups() == () and len(none.calls) == 1


async def test_list_unprotected_legs_carries_what_the_alarm_needs() -> None:
    m = _leg_mapping(status="filled") | {"symbol": "BTCUSDT", "side": "Buy", "env": "live"}
    rel = _Rel(_Result([m | {"is_paper": False}]))
    (row,) = await _store(rel).list_unprotected_legs()
    assert (row.symbol, row.side, row.env, row.is_paper) == ("BTCUSDT", "Buy", "live", False)
    assert row.leg.status == "filled" and not row.leg.native_sl_confirmed
    assert rel.commits == 0 and _sql(rel.calls[0]) == _sql(mod.unprotected_legs_statement())
