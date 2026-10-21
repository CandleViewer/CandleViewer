"""Unit tests for the first persist's port and Postgres adapter (E29-T04 #913): `FirstPersist.check`
and `create_first` against a recording fake unit of work, in statement order, with the hook, the
two anchor conflicts, the share-locked refusals and the error mapping. Real SQL and the races:
tests/integration/storage/test_order_submission_pg.py (CI only)."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import TextClause

from candleviewer.storage.errors import StorageTierUnavailable, WriteAheadTimeout
from candleviewer.storage.repositories import submissions_sqlalchemy as mod
from candleviewer.storage.repositories.idempotency_anchors import NewAnchor
from candleviewer.storage.repositories.orders import (
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderRow,
)
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop, RecordedStopRow
from candleviewer.storage.repositories.submissions import (
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
)
from candleviewer.storage.repositories.trade_groups import (
    NewTradeGroup,
    NewTradeGroupLeg,
    TradeGroupStoreRefusedError,
)

_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()
_T = datetime(2026, 10, 21, 9, tzinfo=UTC)
_USER, _ACCOUNT, _PROFILE = uuid.UUID(int=0x1001), uuid.UUID(int=0x4001), uuid.UUID(int=0x5001)
_GROUP, _LEG, _ORDER, _ANCHOR = (uuid.UUID(int=n) for n in (0x2001, 0x3001, 0x6001, 0x7001))
_SL, _TP = uuid.UUID(int=0x8001), uuid.UUID(int=0x8002)
_REF = "9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59"
_SHA = hashlib.sha256(b'{"symbol":"BTCUSDT","side":"Buy","qty":"0.010"}').hexdigest()
_LINK = "cvd-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"
_EVENT = NewOrderEvent(kind="local_create", source="local", event_ts=_T)


def _sql(stmt: Any) -> str:
    text = str(stmt.compile(dialect=_ASYNCPG, compile_kwargs={"render_postcompile": True}))
    return " ".join(text.split())


def _order(**over: Any) -> NewOrder:
    values: dict[str, Any] = {
        "id": _ORDER, "exchange_account_id": _ACCOUNT, "order_link_id": _LINK, "symbol": "BTCUSDT",
        "side": "Buy", "intent": "entry", "order_type": "Market", "qty": Decimal("0.010"),
        "stop_loss": Decimal("62000"), "take_profit": Decimal("65000"), "state": "pending_submit",
        "lifecycle_state": "validated", "trade_group_leg_id": _LEG,
    }  # fmt: skip
    return NewOrder(**(values | over))


def _reduce_only(**over: Any) -> NewOrder:
    base = {"side": "Sell", "intent": "flatten", "reduce_only": True, "stop_loss": None}
    return _order(**{"take_profit": None, "trade_group_leg_id": None, **base, **over})


def _group(**over: Any) -> NewTradeGroup:
    values: dict[str, Any] = {
        "id": _GROUP, "client_group_ref": _REF, "client_body_sha256": _SHA, "created_by": _USER,
        "env": "demo", "symbol": "BTCUSDT", "side": "Buy", "status": "submitting",
        "leg_failure_policy": "best_effort", "algo": "none", "algo_params": None,
        "intent_note": None, "origin": "manual", "origin_rule_id": None,
        "origin_rule_run_id": None, "definition_id": None, "requested_qty_mode": "fixed_qty",
        "requested_qty_value": Decimal("0.010"), "entry_type": "Market", "entry_price": None,
        "trigger_price": None, "trigger_by": None, "sl_price_hint": Decimal("62000"),
        "tp_price_hint": Decimal("65000"), "is_paper": False,
    }  # fmt: skip
    return NewTradeGroup(**(values | over))


def _leg(**over: Any) -> NewTradeGroupLeg:
    snapshot = {"account_id": str(_ACCOUNT), "profile_id": str(_PROFILE), "version": 3}
    values: dict[str, Any] = {
        "id": _LEG, "exchange_account_id": _ACCOUNT, "account_profile_id": _PROFILE,
        "profile_version": 3, "profile_snapshot": snapshot, "status": "pending", "sequence_no": 0,
        "target_qty": Decimal("0.010"), "resolved_leverage": Decimal("5"),
        "resolved_sl_price": Decimal("62000"), "resolved_tp_price": Decimal("65000"),
        "risk_usd": None, "rejection_code": None, "rejection_message": None,
    }  # fmt: skip
    return NewTradeGroupLeg(**(values | over))


def _stop(record_id: uuid.UUID = _SL, **over: Any) -> NewRecordedStop:
    values: dict[str, Any] = {
        "id": record_id, "exchange_account_id": _ACCOUNT, "symbol": "BTCUSDT", "position_idx": 0,
        "position_side": "Buy", "kind": "stop_loss", "source": "entry_attach",
        "order_id": _ORDER, "tpsl_mode": "Full", "trigger_price": Decimal("62000"),
        "size": None, "audit_record_id": uuid.UUID(int=0x9001), "actor_user_id": _USER,
    }  # fmt: skip
    return NewRecordedStop(**(values | over))


_STOPS = (_stop(), _stop(_TP, kind="take_profit", trigger_price=Decimal("65000")))


def _entry(**over: Any) -> FirstPersist:
    anchor = NewAnchor(
        id=_ANCHOR, created_by=_USER, operation="placeOrder", client_ref=_REF,
        request_sha256=_SHA, trade_group_id=_GROUP,
    )  # fmt: skip
    values: dict[str, Any] = {
        "anchor": anchor,
        "group": _group(),
        "legs": (_leg(),),
        "recorded_stops": _STOPS,
    }
    return FirstPersist(**(values | over))


def _groupless(**over: Any) -> FirstPersist:
    anchor = NewAnchor(
        id=_ANCHOR, created_by=_USER, operation="placeOrder", client_ref=_REF,
        request_sha256=_SHA, order_id=_ORDER,
    )  # fmt: skip
    return FirstPersist(**({"anchor": anchor} | over))


def test_an_entry_and_a_reduce_only_order_that_belong_together_pass() -> None:
    _entry().check(_order())
    _entry(recorded_stops=(_stop(),)).check(_order(take_profit=None))
    _groupless().check(_reduce_only())


@pytest.mark.parametrize(
    ("first", "order", "rule"),
    [
        (_entry(), _order(lifecycle_state=None), "validated row"),
        (_entry(), _order(provenance="reconciliation"), "validated row"),
        (_entry(), _reduce_only(), "one-leg group"),
        (_groupless(), _order(), "one-leg group"),
        (_groupless(legs=(_leg(),)), _reduce_only(), "writes no leg"),
        (_groupless(), _reduce_only(trade_group_leg_id=_LEG), "writes no leg"),
        (_groupless(recorded_stops=(_stop(),)), _reduce_only(), "records no stop"),
        (_entry(), _order(id=uuid.UUID(int=0x6002)), "rs_entry"),
        (_entry(group=_group(id=uuid.UUID(int=0x2002))), _order(), "names its group"),
        (_entry(group=_group(client_group_ref=str(uuid.UUID(int=0xAB)))), _order(), "principal"),
        (_entry(group=_group(client_body_sha256="0" * 64)), _order(), "fingerprint"),
        (_entry(group=_group(created_by=uuid.UUID(int=0x1002))), _order(), "principal"),
        (_entry(group=_group(side="Sell")), _order(), "symbol and side"),
        (_entry(legs=(_leg(), _leg(id=uuid.UUID(int=0x3002)))), _order(), "exactly one leg"),
        (_entry(legs=()), _order(), "exactly one leg"),
        (_entry(), _order(trade_group_leg_id=uuid.UUID(int=0x3002)), "group's leg"),
        (_entry(legs=(_leg(resolved_sl_price=Decimal(61000)),)), _order(), "C-2.6"),
        (_entry(recorded_stops=(_stop(),)), _order(), "take-profit when it has one"),
        (_entry(recorded_stops=_STOPS[1:]), _order(), "stop-loss"),
        (_entry(recorded_stops=(_stop(trigger_price=Decimal(61000)), _STOPS[1])), _order(),
         "attached price"),
        (_entry(recorded_stops=(_stop(position_idx=1), _STOPS[1])), _order(), "position"),
        (_entry(recorded_stops=(_stop(position_side="Sell"), _STOPS[1])), _order(), "position"),
        (_entry(recorded_stops=(_stop(actor_user_id=None), _STOPS[1])), _order(), "actor"),
        (_entry(recorded_stops=(_stop(tpsl_mode="Partial", size=Decimal(1)), _STOPS[1])),
         _order(), "mode"),
    ],
)  # fmt: skip
def test_parts_that_do_not_belong_together_are_refused_before_any_statement(
    first: FirstPersist, order: NewOrder, rule: str
) -> None:
    with pytest.raises(ValueError, match=rule) as exc:
        first.check(order)
    assert "62000" not in str(exc.value) and _REF not in str(exc.value)


def test_an_entry_without_its_stop_is_refused_whatever_its_rows_say() -> None:
    """C-2.6, belt and braces: B1 refuses it at `VALIDATE`, and the persist does again."""
    with pytest.raises(ValueError, match=r"C-2\.6"):
        _entry(legs=(_leg(resolved_sl_price=None, status="rejected"),), recorded_stops=()).check(
            _order(stop_loss=None, take_profit=None)
        )


class _Rel:
    """A scripted unit of work: the cap is answered apart; each other statement takes the next
    result (a list of mappings) or raises it; commits and rollbacks are counted."""

    def __init__(self, *script: list[dict[str, Any]] | BaseException) -> None:
        self.script = list(script)
        self.statements: list[Any] = []
        self.commits = self.rollbacks = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: Any = None) -> Any:
            if isinstance(stmt, TextClause):
                return None
            self.statements.append(stmt)
            item = self.script.pop(0)
            if isinstance(item, BaseException):
                raise item
            rows = _Rows(item)
            return SimpleNamespace(mappings=lambda: rows, first=rows.first)

        async def commit() -> None:
            self.commits += 1

        try:
            yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)
        except BaseException:
            self.rollbacks += 1
            raise


class _Rows(list[dict[str, Any]]):
    def first(self) -> dict[str, Any] | None:
        return self[0] if self else None

    def one(self) -> dict[str, Any]:
        assert len(self) == 1
        return self[0]


def _store(rel: _Rel, **kwargs: Any) -> mod.SqlAlchemySubmissionStore:
    return mod.SqlAlchemySubmissionStore(cast(Any, rel), **kwargs)  # structural fake


def _row_of(dataclass: Any, values: dict[str, Any]) -> dict[str, Any]:
    return {f.name: values.get(f.name) for f in dataclasses.fields(dataclass)}


_GROUP_ROW = {
    **{f.name: getattr(_group(), f.name) for f in dataclasses.fields(NewTradeGroup)},
    "submitted_at": None, "opened_at": None, "closed_at": None, "created_at": _T,
    "updated_at": _T,
}  # fmt: skip
_LEG_ROW = {
    **{f.name: getattr(_leg(), f.name) for f in dataclasses.fields(NewTradeGroupLeg)},
    "trade_group_id": _GROUP, "filled_qty": Decimal(0), "avg_entry_price": None,
    "avg_exit_price": None, "native_sl_confirmed": False, "native_sl_confirmed_at": None,
    "realised_pnl": Decimal(0), "fees_paid": Decimal(0), "submitted_at": None, "closed_at": None,
    "created_at": _T, "updated_at": _T,
}  # fmt: skip
_ORDER_ROW = _row_of(OrderRow, {**dataclasses.asdict(_order()), "created_ts": _T})


def _stop_row(stop: NewRecordedStop) -> dict[str, Any]:
    return _row_of(RecordedStopRow, {**dataclasses.asdict(stop), "status": "pending"})


_LIVE: list[list[dict[str, Any]]] = [
    [{"id": _ACCOUNT}],
    [{"id": _PROFILE, "exchange_account_id": _ACCOUNT, "version": 3}],
]


class _Hook:
    def __init__(self, rel: _Rel, error: BaseException | None = None) -> None:
        self.rel, self.error = rel, error
        self.seen: list[tuple[FirstPersisted, int]] = []

    async def __call__(self, persisted: FirstPersisted) -> None:
        self.seen.append((persisted, self.rel.commits))
        if self.error is not None:
            raise self.error


async def test_an_entry_writes_its_rows_in_order_and_the_hook_runs_before_the_commit() -> None:
    rel = _Rel(
        [_GROUP_ROW], *_LIVE, [_LEG_ROW], [_ORDER_ROW], [_stop_row(s) for s in _STOPS[::-1]],
        [{"id": _ANCHOR}],
    )  # fmt: skip
    hook = _Hook(rel)
    persisted = await _store(rel).create_first(_entry(write_ahead=hook), _order(), _EVENT)
    statements = [_sql(stmt) for stmt in rel.statements]
    assert [s.split(" ", 3)[:3] for s in statements] == [
        ["INSERT", "INTO", "trade_groups"], ["SELECT", "exchange_accounts.id", "FROM"],
        ["SELECT", "account_profiles.id,", "account_profiles.exchange_account_id,"],
        ["INSERT", "INTO", "trade_group_legs"], ["WITH", "inserted_order", "AS"],
        ["INSERT", "INTO", "recorded_stops"], ["INSERT", "INTO", "idempotency_anchors"],
    ]  # fmt: skip
    assert "FOR SHARE" in statements[1] and "FOR SHARE" in statements[2]
    assert rel.commits == 1 and hook.seen == [(persisted, 0)]
    assert persisted.anchor_id == _ANCHOR and persisted.order.id == _ORDER
    assert persisted.group is not None and [leg.id for leg in persisted.group.legs] == [_LEG]
    assert [stop.id for stop in persisted.recorded_stops] == [_SL, _TP]  # the order given


async def test_a_reduce_only_order_locks_its_account_and_writes_no_group_or_stop() -> None:
    row = _row_of(OrderRow, {**dataclasses.asdict(_reduce_only()), "created_ts": _T})
    rel = _Rel([{"id": _ACCOUNT}], [row], [{"id": _ANCHOR}])
    persisted = await _store(rel).create_first(_groupless(), _reduce_only(), _EVENT)
    statements = [_sql(stmt) for stmt in rel.statements]
    assert "FROM exchange_accounts" in statements[0] and "FOR SHARE" in statements[0]
    assert statements[1].startswith("WITH inserted_order AS")
    assert statements[2].startswith("INSERT INTO idempotency_anchors")
    assert persisted.group is None and persisted.recorded_stops == () and rel.commits == 1


async def test_a_reduce_only_order_on_an_account_that_is_not_live_writes_nothing() -> None:
    rel = _Rel([])
    with pytest.raises(TradeGroupStoreRefusedError) as exc:
        await _store(rel).create_first(_groupless(), _reduce_only(), _EVENT)
    assert exc.value.reason == "account_not_live"
    assert len(rel.statements) == 1 and rel.commits == 0 and rel.rollbacks == 1


async def test_a_held_group_key_is_an_anchor_taken_and_nothing_follows_it() -> None:
    rel = _Rel([])
    hook = _Hook(rel)
    with pytest.raises(AnchorTakenError) as exc:
        await _store(rel).create_first(_entry(write_ahead=hook), _order(), _EVENT)
    assert exc.value.constraint == "ux_tg_creator_ref"
    assert len(rel.statements) == 1 and hook.seen == [] and rel.commits == 0


async def test_a_held_anchor_rolls_the_whole_persist_back_before_the_hook() -> None:
    rel = _Rel([_GROUP_ROW], *_LIVE, [_LEG_ROW], [_ORDER_ROW], [_stop_row(_STOPS[0])], [])
    hook = _Hook(rel)
    first = _entry(write_ahead=hook, recorded_stops=_STOPS[:1])
    with pytest.raises(AnchorTakenError) as exc:
        await _store(rel).create_first(first, _order(take_profit=None), _EVENT)
    assert exc.value.constraint == "ux_ia_principal_ref"
    assert hook.seen == [] and rel.commits == 0 and rel.rollbacks == 1


async def test_a_profile_past_the_legs_version_is_refused_under_its_share_lock() -> None:
    moved = [{"id": _PROFILE, "exchange_account_id": _ACCOUNT, "version": 4}]
    rel = _Rel([_GROUP_ROW], [{"id": _ACCOUNT}], moved)
    with pytest.raises(TradeGroupStoreRefusedError) as exc:
        await _store(rel).create_first(_entry(), _order(), _EVENT)
    assert exc.value.reason == "profile_changed" and rel.commits == 0


async def test_a_refused_row_leaves_as_its_constraint_name_with_no_value() -> None:
    orig = SimpleNamespace(sqlstate="23505", constraint_name="ux_rs_in_flight")
    error = IntegrityError("INSERT ... 62000", {"p": "62000"}, cast(Any, orig))
    rel = _Rel([_GROUP_ROW], *_LIVE, [_LEG_ROW], [_ORDER_ROW], error)
    with pytest.raises(OrderConstraintError) as exc:
        await _store(rel).create_first(_entry(), _order(), _EVENT)
    assert exc.value.constraint == "ux_rs_in_flight" and "62000" not in str(exc.value)
    assert exc.value.__cause__ is None and rel.commits == 0


async def test_a_hook_past_its_bound_is_write_ahead_timeout_never_tier_unavailable() -> None:
    """`WriteAheadTimeout` is a `TimeoutError`, so an `OSError`: the order store's mapping lets it
    pass first, as the unit of work rolled back and no outcome is in doubt."""
    rel = _Rel([{"id": _ACCOUNT}], [_ORDER_ROW], [{"id": _ANCHOR}])

    async def hangs(persisted: FirstPersisted) -> None:
        await asyncio.Event().wait()

    store = _store(rel, audit_timeout_s=0.01)
    with pytest.raises(WriteAheadTimeout) as exc:
        await store.create_first(_groupless(write_ahead=hangs), _reduce_only(), _EVENT)
    assert not isinstance(exc.value, StorageTierUnavailable) and rel.commits == 0


async def test_a_raw_os_error_from_the_hook_reads_as_the_database_unreachable() -> None:
    rel = _Rel([{"id": _ACCOUNT}], [_ORDER_ROW], [{"id": _ANCHOR}])
    hook = _Hook(rel, ConnectionError("audit disk"))
    with pytest.raises(StorageTierUnavailable):
        await _store(rel).create_first(_groupless(write_ahead=hook), _reduce_only(), _EVENT)
    assert rel.commits == 0


async def test_a_persist_that_does_not_belong_together_runs_no_statement() -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match="one-leg group"):
        await _store(rel).create_first(_groupless(), _order(), _EVENT)
    assert rel.statements == []


@pytest.mark.parametrize("bound", [0, -1.0, float("nan"), float("inf"), True])
def test_the_hook_bound_is_a_finite_number_of_seconds_above_zero(bound: Any) -> None:
    with pytest.raises(ValueError, match="audit_timeout_s"):
        _store(_Rel(), audit_timeout_s=bound)


def test_the_default_hook_bound_leaves_b1_room_to_commit() -> None:
    from candleviewer.statechart.config import CV_PERSIST_TIMEOUT

    assert mod.SUBMISSION_AUDIT_TIMEOUT_S < CV_PERSIST_TIMEOUT
