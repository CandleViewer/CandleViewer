"""Behavioural contract of the order-submission stores (E29-T04 #913): the first persist
(`SubmissionStore`, 21 Sec.3.3.10 "Writes", 24 Sec.8.4 step 5), the replay anchor
(`IdempotencyAnchorStore`) and the recorded stops (`RecordedStopStore`, 21 Sec.3.3.11), with an
order step's settle of its entry's stops. A first persist writes its rows together or none of them,
whatever refuses it: a held key, a taken id, a stop request in flight, a refusing or late hook, the
share-locked re-check. Each refusal carries the name Postgres gives it, so the fake takes only what
Postgres takes (C-13.3). `test_submission_fake.py` runs it on the in-memory stores,
`tests/integration/storage/test_order_submission_contract_pg.py` on Postgres; subclasses supply
`h`. Every case works in accounts of its own, so a shared database never mixes them."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

import pytest

from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories.executions import (
    ExecutionStore,
    FillTotals,
    NewExecution,
    OrderFill,
)
from candleviewer.storage.repositories.idempotency_anchors import (
    UX_IA_PRINCIPAL_REF,
    AnchorOutcome,
    IdempotencyAnchorStore,
    NewAnchor,
)
from candleviewer.storage.repositories.orders import (
    ORDER_STATE_OF,
    UX_ORDERS_LINK,
    LifecycleState,
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderEventStore,
    OrderStore,
    OrderTransition,
)
from candleviewer.storage.repositories.recorded_stops import (
    UX_RS_IN_FLIGHT,
    NewRecordedStop,
    RecordedStopRow,
    RecordedStopStore,
    StaleRecordedStop,
    SweptStop,
)
from candleviewer.storage.repositories.submissions import (
    UX_TG_CREATOR_REF,
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
    FirstPersistWriteAhead,
    SubmissionRefusal,
    SubmissionStore,
)
from candleviewer.storage.repositories.trade_groups import (
    ACCOUNT_NOT_LIVE,
    PROFILE_CHANGED,
    JsonObject,
    NewTradeGroup,
    NewTradeGroupLeg,
    TradeGroupStoreRefusedError,
)

T0: Final = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
SHA: Final = "ab" * 32
EVENT: Final = NewOrderEvent(kind="local_create", source="local", event_ts=T0)
QTY, PX, SL, TP = Decimal("0.010"), Decimal("63000"), Decimal("62000"), Decimal("65000")
NOTHING: Final = (0, 0, 0, 0, 0)
#: A stop request's bound in the cases (`waiting_for_key`); a `now` past it for every row a case
#: writes, on either clock (the fake's `T0`, the database's); and the clock's finest step.
BOUND_S: Final = 5.0
BOUND: Final = timedelta(seconds=BOUND_S)
LATE: Final = datetime(2100, 1, 1, tzinfo=UTC)
TICK: Final = timedelta(microseconds=1)
#: Bounds `waiting_for_key` cannot use, each failing closed: every unanswered row waits.
UNUSABLE: Final[dict[str, object]] = {
    "missing": None,
    "not_a_number": float("nan"),
    "infinite": float("inf"),
    "negative": -1.0,
    "past_any_timestamp": 1e300,
    "a_bool": True,
    "text": "5",
}


class Orders(OrderStore, OrderEventStore, Protocol):
    """The order and order-event stores, one class on either side."""


@dataclass(frozen=True)
class Bounded:
    """Stores over the harness's tables whose write-ahead hooks are bounded at a test's bound."""

    submissions: SubmissionStore
    stops: RecordedStopStore


@dataclass(frozen=True)
class Harness:
    """`new_account` makes a demo account with its live profile at version 1; `refuse` makes the
    share-locked re-check refuse it from now on (SR-E28-15); `held` counts a persist's anchor,
    group, leg, order and recorded-stop rows as stored; `move_stop` makes a lifecycle move no store
    writes yet (`in_force`, `replaced` or `ended`), as `trg_rs_guard` and `rs_times` admit it;
    `bind_stop` an exchange order id no store binds yet, as `trg_rs_guard` admits the one bind;
    `twin_stop` a row of a stop's request values and age (`created_at`) under another id, which one
    request per transaction never writes; `tick` makes the next row younger, as Postgres's `now()`
    does and the fake's standing clock does not.
    The exit routes' scope (E29-T04 slice 4): `grant` gives a user a viewing grant on an account,
    trading when `trade`, frozen when `frozen`; `owner` a live owner role; `elsewhere` a live
    account, of another environment than `new_account`'s."""

    submissions: SubmissionStore
    anchors: IdempotencyAnchorStore
    stops: RecordedStopStore
    orders: Orders
    executions: ExecutionStore
    new_user: Callable[[], UUID]
    new_account: Callable[[], tuple[UUID, UUID]]
    refuse: Callable[[UUID, SubmissionRefusal], None]
    bounded: Callable[[float], Bounded]
    held: Callable[[FirstPersist, NewOrder], tuple[int, ...]]
    move_stop: Callable[[UUID, str], None]
    bind_stop: Callable[[UUID, str], None]
    twin_stop: Callable[[UUID, UUID], None]
    tick: Callable[[], None]
    grant: Callable[[UUID, UUID, bool, bool], None]
    owner: Callable[[UUID], None]
    elsewhere: Callable[[], tuple[UUID, UUID]]


def link() -> str:
    """A fresh `order_link_id` of the OMS's own shape (24 Sec.8.3)."""
    return f"cvd-0{uuid4().hex[:21]}-d0hb-00en"


def entry(
    user: UUID,
    account: UUID,
    profile: UUID,
    *,
    ref: str | None = None,
    link_id: str | None = None,
    take_profit: Decimal | None = None,
    group: dict[str, Any] | None = None,
    leg: dict[str, Any] | None = None,
    write_ahead: FirstPersistWriteAhead | None = None,
) -> tuple[FirstPersist, NewOrder]:
    """An entry's first persist on BTCUSDT, position 0: its one-leg group, the order, its stop-loss
    (and take-profit) and its anchor; `group` and `leg` change their rows."""
    key, group_id, leg_id, order_id = ref or str(uuid4()), uuid4(), uuid4(), uuid4()
    group_values: dict[str, Any] = {
        "id": group_id, "client_group_ref": key, "client_body_sha256": SHA, "created_by": user,
        "env": "demo", "symbol": "BTCUSDT", "side": "Buy", "status": "submitting",
        "leg_failure_policy": "best_effort", "algo": "none", "algo_params": None,
        "intent_note": None, "origin": "manual", "origin_rule_id": None,
        "origin_rule_run_id": None, "definition_id": None, "requested_qty_mode": "fixed_qty",
        "requested_qty_value": QTY, "entry_type": "Market", "entry_price": None,
        "trigger_price": None, "trigger_by": None, "sl_price_hint": SL,
        "tp_price_hint": take_profit, "is_paper": False,
    }  # fmt: skip
    new_group = NewTradeGroup(**(group_values | (group or {})))
    snapshot: JsonObject = {"account_id": str(account), "profile_id": str(profile), "version": 1}
    leg_values: dict[str, Any] = {
        "id": leg_id, "exchange_account_id": account, "account_profile_id": profile,
        "profile_version": 1, "profile_snapshot": snapshot, "status": "pending",
        "sequence_no": 0, "target_qty": QTY, "resolved_leverage": Decimal(5),
        "resolved_sl_price": SL, "resolved_tp_price": take_profit, "risk_usd": None,
        "rejection_code": None, "rejection_message": None,
    }  # fmt: skip
    new_leg = NewTradeGroupLeg(**(leg_values | (leg or {})))
    order = NewOrder(
        id=order_id, exchange_account_id=account, order_link_id=link_id or link(),
        symbol="BTCUSDT", side="Buy", intent="entry", order_type="Market", qty=QTY,
        stop_loss=SL, take_profit=take_profit, state="pending_submit",
        lifecycle_state="validated", trade_group_leg_id=leg_id,
    )  # fmt: skip
    sides = {"stop_loss": SL, "take_profit": take_profit}
    attach = {"source": "entry_attach", "order_id": order_id, "actor_user_id": user}
    stops = tuple(
        trading_stop(account, kind=kind, trigger_price=price, position_marker=None, **attach)
        for kind, price in sides.items()
        if price is not None
    )
    anchor = NewAnchor(
        id=uuid4(), created_by=user, operation="placeOrder", client_ref=key,
        request_sha256=SHA, trade_group_id=group_id,
    )  # fmt: skip
    first = FirstPersist(
        anchor=anchor, group=new_group, legs=(new_leg,), recorded_stops=stops,
        write_ahead=write_ahead,
    )  # fmt: skip
    return first, order


def reduce_only(
    user: UUID, account: UUID, *, ref: str | None = None
) -> tuple[FirstPersist, NewOrder]:
    """A reduce-only order's first persist: the order and its anchor, no group and no stop."""
    order = NewOrder(
        id=uuid4(), exchange_account_id=account, order_link_id=link(), symbol="BTCUSDT",
        side="Sell", intent="flatten", order_type="Market", qty=QTY, reduce_only=True,
        state="pending_submit", lifecycle_state="validated",
    )  # fmt: skip
    anchor = NewAnchor(
        id=uuid4(), created_by=user, operation="placeOrder", client_ref=ref or str(uuid4()),
        request_sha256=SHA, order_id=order.id,
    )  # fmt: skip
    return FirstPersist(anchor=anchor), order


def trading_stop(account: UUID, **over: Any) -> NewRecordedStop:
    """A system writer's trading-stop request for BTCUSDT's position 0, its stop-loss side."""
    values: dict[str, Any] = {
        "id": uuid4(), "exchange_account_id": account, "symbol": "BTCUSDT", "position_idx": 0,
        "position_side": "Buy", "kind": "stop_loss", "source": "trading_stop", "order_id": None,
        "tpsl_mode": "Full", "trigger_price": Decimal(62500), "size": None,
        "audit_record_id": uuid4(), "actor_user_id": None, "position_marker": "m1",
    }  # fmt: skip
    return NewRecordedStop(**(values | over))


async def waiting(
    h: Harness,
    account: UUID,
    symbol: str = "BTCUSDT",
    position_idx: int = 0,
    *,
    now: datetime = LATE,
    bound_s: Any = BOUND_S,
) -> tuple[RecordedStopRow, ...]:
    """The key's rows waiting for the complete read at `now`: by default past every row's bound,
    where an unanswered row waits, as one found at startup does."""
    return await h.stops.waiting_for_key(account, symbol, position_idx, now=now, bound_s=bound_s)


Move = Callable[[Harness, NewOrder], Awaitable[object]]


def to(frm: LifecycleState, dest: LifecycleState, **over: Any) -> Move:
    """An order step from `frm` to `dest` as B1's writer writes it, a local event with the chart
    state beside the stored one; `entry_stops` only when given (a step that bypasses it, as a
    writer that crashed would, is how a case reaches a row it must find)."""

    kind = over.pop("kind", "ack")

    async def move(h: Harness, order: NewOrder) -> object:
        event = NewOrderEvent(kind=kind, source="local", event_ts=T0)
        step = OrderTransition(
            account_id=order.exchange_account_id, order_id=order.id,
            from_state=ORDER_STATE_OF[frm], to_state=ORDER_STATE_OF[dest], event=event,
            lifecycle_state=dest, **over,
        )  # fmt: skip
        return await h.orders.transition(step)

    return move


SEND: Final = to("validated", "submitting", kind="submit_attempt", bump_submit_attempts=True,
                 idempotency_state="in_flight")  # fmt: skip
ACK: Final = to("submitting", "submitted", idempotency_state="acked", entry_stops="answered")
REFUSED: Final = to("submitting", "rejected", kind="reject", idempotency_state="failed",
                    entry_stops="void")  # fmt: skip


async def partial(h: Harness, order: NewOrder) -> object:
    """A fill of 0.004 of the accepted entry, with its execution."""
    size = Decimal("0.004")
    execution = NewExecution(
        exchange_account_id=order.exchange_account_id, order_id=order.id, exec_id="E1",
        order_link_id=order.order_link_id, symbol=order.symbol, side=order.side, exec_qty=size,
        exec_price=PX, exec_value=size * PX, exec_type="Trade", is_maker=False, exec_ts=T0,
    )  # fmt: skip
    totals = FillTotals(
        cum_exec_qty=size, cum_exec_value=size * PX, avg_price=PX, fee_paid=Decimal(0)
    )
    step = OrderTransition(
        account_id=order.exchange_account_id, order_id=order.id, from_state="accepted",
        to_state="partially_filled", lifecycle_state="partially_filled",
        event=NewOrderEvent(kind="partial_fill", source="local", event_ts=T0),
    )  # fmt: skip
    return await h.executions.commit_fill(OrderFill(step=step, execution=execution, totals=totals))


async def audited(_: object) -> None:
    """A write-ahead hook whose record lands."""


async def refuses(_: object) -> None:
    raise RuntimeError("the audit trail refused the record")


async def hangs(_: object) -> None:
    await asyncio.Event().wait()


async def unreachable(_: object) -> None:
    raise ConnectionRefusedError("the audit lane is down")


#: A write-ahead hook that fails, and what the write raises, nothing written: its own error; past
#: the bound, `WriteAheadTimeout`; an `OSError`, as the store's unit of work maps one.
HOOKS: Final[dict[str, tuple[Callable[[object], Awaitable[None]], type[Exception]]]] = {
    "refuses": (refuses, RuntimeError),
    "hangs": (hangs, WriteAheadTimeout),
    "unreachable": (unreachable, StorageTierUnavailable),
}
#: An entry's moves, and whether its attach rows then wait for the complete read (21 Sec.3.3.11's
#: table, the orchestrator's Q2 ruling) inside their request's bound, and past it. Unanswered, they
#: wait only past it (inside it, a second request meets them at the insert); on an end the
#: exchange did not confirm, answered or not, they wait at once; answered on a live order, voided,
#: or its order's position's stop since it filled, they never do.
WAITING: Final[dict[str, tuple[tuple[Move, ...], bool, bool]]] = {
    "in_flight": ((), False, True),
    "sent": ((SEND,), False, True),
    "unknown": ((SEND, to("submitting", "unknown")), False, True),
    "killed_in_flight": ((SEND, to("submitting", "killed")), True, True),
    "live": ((SEND, ACK), False, False),
    "cancelled_by_its_answer": ((SEND, ACK, to("submitted", "cancelled")), True, True),
    "killed_after_its_send": ((SEND, ACK, to("submitted", "killed")), True, True),
    "expired_with_no_count": ((SEND, ACK, to("submitted", "expired")), True, True),
    "held": ((SEND, ACK, to("submitted", "held")), True, True),
    "rejected_by_reconciliation": (
        (SEND, ACK, to("submitted", "rejected", kind="reject")),
        True,
        True,
    ),
    "refused_by_its_create": ((SEND, REFUSED), False, False),
    "confirmed_unfilled": (
        (SEND, ACK, to("submitted", "cancelled", entry_stops="void")),
        False,
        False,
    ),
    "filled_then_cancelled": (
        (SEND, ACK, partial, to("partially_filled", "cancelled")),
        False,
        False,
    ),
}
#: An entry's moves, and whether the startup sweep voids its rows (R10): never placed, it does.
SWEPT: Final[dict[str, tuple[tuple[Move, ...], bool]]] = {
    "never_sent": ((), True),
    "killed_before_its_send": ((to("validated", "killed"),), True),
    "refused_by_its_create": ((SEND, to("submitting", "rejected", kind="reject")), True),
    "live": ((SEND, ACK), False),
    "killed_after_its_send": ((SEND, to("submitting", "killed")), False),
}


class SubmissionContract:
    # -- the first persist ----------------------------------------------------------------------

    async def test_an_entry_persists_its_rows_together_audited_before_its_commit(
        self, h: Harness
    ) -> None:
        """21 Sec.3.3.10: the group with its leg, the order's `validated` row, its stops in flight
        and the anchor, together; the hook runs before the commit, so a read sees none yet."""
        user, (account, profile) = h.new_user(), h.new_account()
        seen: list[tuple[FirstPersisted, object]] = []

        async def audit(persisted: FirstPersisted) -> None:
            seen.append((persisted, await h.orders.get(account, persisted.order.id)))

        first, order = entry(user, account, profile, take_profit=TP, write_ahead=audit)
        persisted = await h.submissions.create_first(first, order, EVENT)
        assert seen == [(persisted, None)] and h.held(first, order) == (1, 1, 1, 1, 2)
        assert persisted.group is not None and persisted.anchor_id == first.anchor.id
        assert (persisted.group.group.status, [leg.id for leg in persisted.group.legs]) == (
            "submitting",
            [first.legs[0].id],
        )
        row = persisted.order
        assert (row.state, row.lifecycle_state, row.provenance) == (
            "pending_submit",
            "validated",
            "placed",
        )
        assert await h.orders.get(account, order.id) == row
        stops = persisted.recorded_stops
        assert [(s.kind, s.status, s.answered_at) for s in stops] == [
            ("stop_loss", "pending", None),
            ("take_profit", "pending", None),
        ]
        assert set(await h.stops.for_order(account, order.id)) == set(stops)
        found = await h.anchors.find(user, "placeOrder", first.anchor.client_ref, SHA)
        assert found is not None and (found.id, found.trade_group_id) == (
            first.anchor.id,
            first.anchor.trade_group_id,
        )
        assert found.body_matches and (found.outcome_status, found.decided_at) == (None, None)

    async def test_a_reduce_only_order_persists_its_order_and_anchor_alone(
        self, h: Harness
    ) -> None:
        user, (account, _) = h.new_user(), h.new_account()
        first, order = reduce_only(user, account)
        persisted = await h.submissions.create_first(first, order, EVENT)
        assert (persisted.group, persisted.recorded_stops) == (None, ())
        assert h.held(first, order) == (1, 0, 0, 1, 0)
        found = await h.anchors.find(user, "placeOrder", first.anchor.client_ref, SHA)
        assert found is not None and (found.trade_group_id, found.order_id) == (None, order.id)

    async def test_an_entry_without_its_native_stop_is_refused_before_any_statement(
        self, h: Harness
    ) -> None:
        """C-2.6 (`FirstPersist.check`): an entry records its stop-loss, or nothing is written."""
        user, (account, profile) = h.new_user(), h.new_account()
        first, order = entry(user, account, profile)
        bare = replace(first, recorded_stops=())
        with pytest.raises(ValueError, match="stop-loss"):
            await h.submissions.create_first(bare, order, EVENT)
        assert h.held(first, order) == NOTHING

    @pytest.mark.parametrize(
        ("earlier", "later", "constraint"),
        [
            ("entry", "entry", UX_TG_CREATOR_REF),
            ("reduce_only", "reduce_only", UX_IA_PRINCIPAL_REF),
            ("entry", "reduce_only", UX_IA_PRINCIPAL_REF),
            ("reduce_only", "entry", UX_IA_PRINCIPAL_REF),
        ],
    )
    async def test_a_key_the_principal_holds_refuses_the_next_persist_with_nothing_written(
        self, h: Harness, earlier: str, later: str, constraint: str
    ) -> None:
        """21 Sec.3.3.10: whatever the key's first request was, a later one writes nothing and is
        answered as a repeat; an entry meets the group's twin of the key first, unless the key's
        request was reduce-only and wrote no group."""
        user, (account, profile) = h.new_user(), h.new_account()
        ref = str(uuid4())
        made: dict[str, Callable[[], tuple[FirstPersist, NewOrder]]] = {
            "entry": lambda: entry(user, account, profile, ref=ref),
            "reduce_only": lambda: reduce_only(user, account, ref=ref),
        }
        await h.submissions.create_first(*made[earlier](), EVENT)
        first, order = made[later]()
        with pytest.raises(AnchorTakenError) as err:
            await h.submissions.create_first(first, order, EVENT)
        assert err.value.constraint == constraint and h.held(first, order) == NOTHING

    async def test_of_two_concurrent_persists_of_one_key_one_is_stored(self, h: Harness) -> None:
        user, (account, _) = h.new_user(), h.new_account()
        ref = str(uuid4())
        persists = [reduce_only(user, account, ref=ref) for _ in "ab"]
        results = await asyncio.gather(
            *(h.submissions.create_first(*persist, EVENT) for persist in persists),
            return_exceptions=True,
        )
        lost = [r for r in results if isinstance(r, AnchorTakenError)]
        assert len(lost) == 1 and lost[0].constraint == UX_IA_PRINCIPAL_REF
        assert sorted(h.held(*persist) for persist in persists) == [NOTHING, (1, 0, 0, 1, 0)]

    async def test_another_principals_key_is_its_own(self, h: Harness) -> None:
        """SR-E29-07: the key is scoped to its principal and its operation."""
        (account, _), ref = h.new_account(), str(uuid4())
        users = h.new_user(), h.new_user()
        persists = [reduce_only(user, account, ref=ref) for user in users]
        for persist in persists:
            await h.submissions.create_first(*persist, EVENT)
        found = [await h.anchors.find(user, "placeOrder", ref, SHA) for user in users]
        assert [f and f.id for f in found] == [first.anchor.id for first, _ in persists]
        assert await h.anchors.find(users[0], "closePosition", ref, SHA) is None
        assert await h.anchors.find(h.new_user(), "placeOrder", ref, SHA) is None

    async def test_a_taken_order_link_id_refuses_the_persist_with_nothing_written(
        self, h: Harness
    ) -> None:
        user, (account, profile) = h.new_user(), h.new_account()
        stored = await h.submissions.create_first(*reduce_only(user, account), EVENT)
        first, order = entry(user, account, profile, link_id=stored.order.order_link_id)
        with pytest.raises(OrderConstraintError) as err:
            await h.submissions.create_first(first, order, EVENT)
        assert err.value.constraint == UX_ORDERS_LINK and h.held(first, order) == NOTHING

    async def test_one_stop_request_is_in_flight_per_position(self, h: Harness) -> None:
        """`ux_rs_in_flight`: an entry's attach, or a trading-stop request, for a position whose
        stop request is in flight writes nothing; once that one is answered, the same rows go."""
        user, (account, profile) = h.new_user(), h.new_account()
        earlier = await h.submissions.create_first(*entry(user, account, profile), EVENT)
        later = entry(user, account, profile)
        attempts: list[Callable[[], Awaitable[object]]] = [
            lambda: h.submissions.create_first(*later, EVENT),
            lambda: h.stops.insert([trading_stop(account)]),
        ]
        for attempt in attempts:
            with pytest.raises(OrderConstraintError) as err:
                await attempt()
            assert err.value.constraint == UX_RS_IN_FLIGHT
        assert h.held(*later) == NOTHING
        await h.stops.settle(account, [earlier.recorded_stops[0].id], "answered", at=T0)
        assert (await h.submissions.create_first(*later, EVENT)).order.id == later[1].id

    @pytest.mark.parametrize("hook", sorted(HOOKS))
    async def test_a_hook_that_fails_leaves_nothing_written(self, h: Harness, hook: str) -> None:
        """C-2.9: the write-ahead audit is part of the persist; the key and the position stay
        free after it fails."""
        user, (account, profile) = h.new_user(), h.new_account()
        audit, raised = HOOKS[hook]
        first, order = entry(user, account, profile, write_ahead=audit)
        with pytest.raises(raised):
            await h.bounded(0.05).submissions.create_first(first, order, EVENT)
        assert h.held(first, order) == NOTHING
        await h.submissions.create_first(replace(first, write_ahead=None), order, EVENT)
        assert h.held(first, order) == (1, 1, 1, 1, 1)

    @pytest.mark.parametrize(
        ("reason", "kind", "refused"),
        [
            ("account_not_live", "entry", ACCOUNT_NOT_LIVE),
            ("account_not_live", "reduce_only", ACCOUNT_NOT_LIVE),
            ("profile_changed", "entry", PROFILE_CHANGED),
            ("profile_changed", "reduce_only", None),  # a reduce-only order locks no profile
        ],
    )
    async def test_the_share_locked_recheck_refuses_with_nothing_written(
        self, h: Harness, reason: SubmissionRefusal, kind: str, refused: str | None
    ) -> None:
        """SR-E28-15: the account, then the leg's profile at its version, locked and live."""
        user, (account, profile) = h.new_user(), h.new_account()
        h.refuse(account, reason)
        first, order = (
            entry(user, account, profile) if kind == "entry" else reduce_only(user, account)
        )
        if refused is None:
            await h.submissions.create_first(first, order, EVENT)
            assert h.held(first, order) == (1, 0, 0, 1, 0)
            return
        with pytest.raises(TradeGroupStoreRefusedError) as err:
            await h.submissions.create_first(first, order, EVENT)
        assert err.value.reason == refused and h.held(first, order) == NOTHING

    @pytest.mark.parametrize(
        ("group", "leg", "constraint"),
        [
            ({"entry_type": "Limit"}, {}, "tg_limit_px"),
            ({"entry_type": "Conditional", "trigger_price": SL}, {}, "tg_cond_px"),
            ({}, {"target_qty": Decimal(-1)}, "tgl_filled_rng"),  # met before `tgl_qty_pos`
            ({}, {"target_qty": Decimal(0)}, "tgl_qty_pos"),
            ({}, {"resolved_leverage": Decimal(0)}, "tgl_lev"),
            ({}, {"sequence_no": 101}, "tgl_seq"),
        ],
    )
    async def test_a_group_or_leg_postgres_refuses_is_refused_by_name(
        self, h: Harness, group: dict[str, Any], leg: dict[str, Any], constraint: str
    ) -> None:
        user, (account, profile) = h.new_user(), h.new_account()
        first, order = entry(user, account, profile, group=group, leg=leg)
        with pytest.raises(OrderConstraintError) as err:
            await h.submissions.create_first(first, order, EVENT)
        assert err.value.constraint == constraint and h.held(first, order) == NOTHING

    async def test_a_leg_outside_its_groups_environment_is_refused_by_name(
        self, h: Harness
    ) -> None:
        """C-2.11 (`trg_tgl_env`, SEC-2B1-03): a demo account's leg in a live group writes
        nothing, refused by the name Postgres gives it, so the fake is no laxer than Postgres."""
        user, (account, profile) = h.new_user(), h.new_account()
        first, order = entry(user, account, profile, group={"env": "live"})
        with pytest.raises(OrderConstraintError) as err:
            await h.submissions.create_first(first, order, EVENT)
        assert err.value.constraint == "trg_tgl_env" and h.held(first, order) == NOTHING

    @pytest.mark.parametrize(
        ("held", "constraint"),
        [
            ("group", "trade_groups_pkey"),
            ("leg", "trade_group_legs_pkey"),
            ("order", "orders_pkey"),
            ("anchor", "idempotency_anchors_pkey"),
        ],
    )
    async def test_an_id_its_table_holds_refuses_the_persist_by_name_with_nothing_written(
        self, h: Harness, held: str, constraint: str
    ) -> None:
        """Each row's primary key, met by the name Postgres gives it: a later persist, on another
        account under a key of its own, that names a group, leg, order or anchor id a stored row
        holds writes nothing (the later order and its anchor read as missing)."""
        user, (account, profile) = h.new_user(), h.new_account()
        other, other_profile = h.new_account()
        if held in ("group", "leg"):
            first, order = entry(user, account, profile)
            later, later_order = entry(user, other, other_profile)
            assert first.group is not None and later.group is not None
            if held == "group":
                group = replace(later.group, id=first.group.id)
                anchor = replace(later.anchor, trade_group_id=first.group.id)
                later = replace(later, group=group, anchor=anchor)
            else:
                leg_id = first.legs[0].id
                later = replace(later, legs=(replace(later.legs[0], id=leg_id),))
                later_order = replace(later_order, trade_group_leg_id=leg_id)
        else:
            first, order = reduce_only(user, account)
            later, later_order = reduce_only(user, other)
            if held == "order":
                later_order = replace(later_order, id=order.id)
                later = replace(later, anchor=replace(later.anchor, order_id=order.id))
            else:
                later = replace(later, anchor=replace(later.anchor, id=first.anchor.id))
        await h.submissions.create_first(first, order, EVENT)
        with pytest.raises(OrderConstraintError) as err:
            await h.submissions.create_first(later, later_order, EVENT)
        assert err.value.constraint == constraint
        assert await h.orders.get(other, later_order.id) is None
        assert await h.anchors.find(user, "placeOrder", later.anchor.client_ref, SHA) is None

    async def test_text_holding_nul_is_refused_whole_with_nothing_written(self, h: Harness) -> None:
        """OM-T04: Postgres refuses a statement whose bound text holds NUL (22021)."""
        user, (account, profile) = h.new_user(), h.new_account()
        first, order = entry(user, account, profile, group={"intent_note": "a\x00b"})
        with pytest.raises(StorageQueryFailed):
            await h.submissions.create_first(first, order, EVENT)
        assert h.held(first, order) == NOTHING
        with pytest.raises(StorageQueryFailed):
            await h.stops.insert([trading_stop(account, position_marker="m\x00")])
        assert await waiting(h, account) == ()

    # -- the replay anchor ----------------------------------------------------------------------

    async def test_an_outcome_is_recorded_once(self, h: Harness) -> None:
        """`ia_decided`: the first answer, by compare-and-set from none; of two at once, one."""
        user, (account, _) = h.new_user(), h.new_account()
        first, order = reduce_only(user, account)
        await h.submissions.create_first(first, order, EVENT)
        rejected = AnchorOutcome(status=502, code="exchange_error", ret_code=110007, decided_at=T0)
        accepted = AnchorOutcome(status=202, decided_at=T0)
        decided = await asyncio.gather(
            h.anchors.record_outcome(first.anchor.id, rejected),
            h.anchors.record_outcome(first.anchor.id, accepted),
        )
        assert sorted(decided) == [False, True]
        assert await h.anchors.record_outcome(uuid4(), accepted) is False
        found = await h.anchors.find(user, "placeOrder", first.anchor.client_ref, SHA)
        assert found is not None
        outcome = (found.outcome_status, found.outcome_code, found.outcome_ret_code)
        assert outcome == ((502, "exchange_error", 110007) if decided[0] else (202, None, None))
        assert found.decided_at == T0

    async def test_an_anchor_compares_the_fingerprint_and_never_returns_it(
        self, h: Harness
    ) -> None:
        user, (account, _) = h.new_user(), h.new_account()
        first, order = reduce_only(user, account)
        await h.submissions.create_first(first, order, EVENT)
        ref = first.anchor.client_ref
        same = await h.anchors.find(user, "placeOrder", ref, SHA)
        other = await h.anchors.find(user, "placeOrder", ref, "cd" * 32)
        assert same is not None and other is not None and same.id == other.id
        assert (same.body_matches, other.body_matches) == (True, False)
        assert SHA not in repr(same) and ref not in repr(same)

    @pytest.mark.parametrize(
        ("ref", "sha"),
        [
            ("9B2F7C1E-4D3A-4F6B-8A0C-5E1D2C3B4A59", SHA),
            ("{9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59}", SHA),
            ("9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59", "AB" * 32),
            ("9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59", "ab"),
        ],
    )
    async def test_a_key_or_fingerprint_the_table_cannot_hold_is_refused(
        self, h: Harness, ref: str, sha: str
    ) -> None:
        """`ia_ref_fmt` and `sha256_hex`, before any statement, naming no value."""
        with pytest.raises(ValueError) as err:
            await h.anchors.find(h.new_user(), "placeOrder", ref, sha)
        assert ref not in str(err.value) and sha not in str(err.value)

    # -- the recorded stops ---------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("outcome", "status", "answered", "closed"),
        [
            ("answered", "pending", True, False),
            ("refused", "void", True, True),
            ("not_shown", "void", False, True),
        ],
    )
    async def test_a_stop_request_is_settled_once_and_only_in_its_account(
        self, h: Harness, outcome: Any, status: str, answered: bool, closed: bool
    ) -> None:
        """A void passes its write-ahead hook, as every void must (C-2.9)."""
        account, _ = h.new_account()
        [recorded] = await h.stops.insert([trading_stop(account)])
        hook = None if outcome == "answered" else audited
        with pytest.raises(StaleRecordedStop):
            await h.stops.settle(uuid4(), [recorded.id], outcome, at=T0, write_ahead=hook)
        [settled] = await h.stops.settle(account, [recorded.id], outcome, at=T0, write_ahead=hook)
        times = (settled.answered_at is not None, settled.closed_at is not None)
        assert (settled.status, *times) == (status, answered, closed)
        with pytest.raises(StaleRecordedStop):
            await h.stops.settle(account, [recorded.id], "answered", at=T0)

    @pytest.mark.parametrize("outcome", ["refused", "not_shown"])
    async def test_a_void_without_its_hook_is_refused_before_anything(
        self, h: Harness, outcome: Any
    ) -> None:
        """SEC-4057-F-01 (21 Sec.3.3.11 "Audit"): the store takes no void without its write-ahead
        hook, `ValueError` before any statement, so the row is still in flight after it."""
        account, _ = h.new_account()
        [recorded] = await h.stops.insert([trading_stop(account)])
        with pytest.raises(ValueError, match="audited write-ahead"):
            await h.stops.settle(account, [recorded.id], outcome, at=T0)
        assert await waiting(h, account) == (recorded,)

    @pytest.mark.parametrize("named", ["none", "twice"])
    async def test_a_settle_names_each_row_of_its_request_once(
        self, h: Harness, named: str
    ) -> None:
        """`ValueError` before any statement for a settle that names no row, or a row twice; the
        row stays in flight."""
        account, _ = h.new_account()
        [recorded] = await h.stops.insert([trading_stop(account)])
        ids = [] if named == "none" else [recorded.id, recorded.id]
        with pytest.raises(ValueError, match="names each row of the request once"):
            await h.stops.settle(account, ids, "answered", at=T0)
        assert await waiting(h, account) == (recorded,)

    async def test_a_row_id_the_table_holds_refuses_the_insert_by_name(self, h: Harness) -> None:
        """`recorded_stops_pkey`: a request that names a stored row's id writes nothing, its
        position left free (the first request answered, so no request is in flight for it)."""
        account, _ = h.new_account()
        [recorded] = await h.stops.insert([trading_stop(account)])
        await h.stops.settle(account, [recorded.id], "answered", at=T0)
        with pytest.raises(OrderConstraintError) as err:
            await h.stops.insert([trading_stop(account, id=recorded.id)])
        assert err.value.constraint == "recorded_stops_pkey"
        assert await waiting(h, account) == ()

    async def test_a_settle_is_audited_before_its_commit_or_settles_nothing(
        self, h: Harness
    ) -> None:
        """SEC-2A-05: inside the hook the row is still in flight for every other reader."""
        account, _ = h.new_account()
        [recorded] = await h.stops.insert([trading_stop(account)])
        seen: list[tuple[tuple[RecordedStopRow, ...], tuple[RecordedStopRow, ...]]] = []

        async def audit(rows: tuple[RecordedStopRow, ...]) -> None:
            seen.append((rows, await waiting(h, account)))

        with pytest.raises(RuntimeError):
            await h.stops.settle(account, [recorded.id], "refused", at=T0, write_ahead=refuses)
        [voided] = await h.stops.settle(account, [recorded.id], "refused", at=T0, write_ahead=audit)
        assert seen == [((voided,), (recorded,))]

    async def test_an_insert_is_audited_before_its_commit(self, h: Harness) -> None:
        """21 Sec.3.3.11 "Audit": the request's record is written with its rows (`sl.attached`)."""
        account, _ = h.new_account()
        stop = trading_stop(account)
        seen: list[tuple[tuple[RecordedStopRow, ...], tuple[RecordedStopRow, ...]]] = []

        async def audit(rows: tuple[RecordedStopRow, ...]) -> None:
            seen.append((rows, await waiting(h, account)))

        rows = await h.stops.insert([stop], write_ahead=audit)
        assert seen == [(rows, ())]
        assert [(r.id, r.status, r.answered_at) for r in rows] == [(stop.id, "pending", None)]

    @pytest.mark.parametrize("hook", sorted(HOOKS))
    async def test_an_insert_whose_audit_fails_writes_nothing(self, h: Harness, hook: str) -> None:
        account, _ = h.new_account()
        stop = trading_stop(account)
        audit, raised = HOOKS[hook]
        with pytest.raises(raised):
            await h.bounded(0.05).stops.insert([stop], write_ahead=audit)
        assert await waiting(h, account) == ()
        assert [row.id for row in await h.stops.insert([stop])] == [stop.id]

    @pytest.mark.parametrize("case", sorted(WAITING))
    async def test_the_rows_that_wait_for_the_complete_read(self, h: Harness, case: str) -> None:
        """While any is listed, no other stop request for the key may leave (21 Sec.3.3.11):
        inside their request's bound, the rows of an entry that ended with no confirmed count;
        from the bound on, its unanswered rows too (the orchestrator's Q2 ruling)."""
        user, (account, profile) = h.new_user(), h.new_account()
        first, order = entry(user, account, profile, take_profit=TP)
        persisted = await h.submissions.create_first(first, order, EVENT)
        born = persisted.recorded_stops[0].created_at
        moves, inside, past = WAITING[case]
        for move in moves:
            await move(h, order)
        ids = {stop.id for stop in first.recorded_stops}
        for now, waits in ((born + BOUND - TICK, inside), (born + BOUND, past)):
            listed = await waiting(h, account, now=now)
            assert {row.id for row in listed} == (ids if waits else set())
            assert [row.created_at for row in listed] == sorted(row.created_at for row in listed)
        for elsewhere in (
            (uuid4(), "BTCUSDT", 0),
            (account, "ETHUSDT", 0),
            (account, "BTCUSDT", 1),
        ):
            assert await waiting(h, *elsewhere) == ()

    async def test_an_unanswered_row_waits_from_its_requests_bound_on(self, h: Harness) -> None:
        """The orchestrator's Q2 ruling: in flight inside its bound, a row is not listed, as a
        second request meets it at the insert (`ux_rs_in_flight`) and retries (Q4); as old as its
        bound or older, it waits for the complete read; answered, it does not."""
        account, _ = h.new_account()
        [row] = await h.stops.insert([trading_stop(account)])
        born = row.created_at
        assert await waiting(h, account, now=born) == ()
        assert await waiting(h, account, now=born + BOUND - TICK) == ()
        with pytest.raises(OrderConstraintError) as err:
            await h.stops.insert([trading_stop(account)])
        assert err.value.constraint == UX_RS_IN_FLIGHT
        assert await waiting(h, account, now=born + BOUND) == (row,)
        assert await waiting(h, account, now=born + 2 * BOUND) == (row,)
        await h.stops.settle(account, [row.id], "answered", at=T0)
        assert await waiting(h, account, now=born + 2 * BOUND) == ()

    @pytest.mark.parametrize("bound", sorted(UNUSABLE))
    async def test_a_missing_or_unusable_bound_fails_closed(self, h: Harness, bound: str) -> None:
        """The orchestrator's Q2 ruling: with no bound the read can use, every unanswered row
        waits, even one written at `now`; an answered one still does not."""
        account, _ = h.new_account()
        [row] = await h.stops.insert([trading_stop(account)])
        unusable = UNUSABLE[bound]
        assert await waiting(h, account, now=row.created_at, bound_s=unusable) == (row,)
        await h.stops.settle(account, [row.id], "answered", at=T0)
        assert await waiting(h, account, now=row.created_at, bound_s=unusable) == ()

    async def test_a_naive_now_is_refused_before_the_read(self, h: Harness) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            await waiting(h, h.new_account()[0], now=LATE.replace(tzinfo=None))

    async def test_the_orders_step_settles_its_entrys_stops_with_it(self, h: Harness) -> None:
        """21 Sec.3.3.11's table: the acceptance answers the rows; an end the exchange confirmed
        unfilled voids them, unless the order holds a fill (SEC-2A-01)."""
        user = h.new_user()
        cases: dict[str, tuple[Move, ...]] = {
            "accepted": (SEND, ACK),
            "refused": (SEND, REFUSED),
            "filled": (SEND, ACK, partial, to("partially_filled", "cancelled", entry_stops="void")),
        }
        settled: dict[str, list[tuple[str, object, object]]] = {}
        for name, moves in cases.items():
            first, order = entry(user, *h.new_account())
            await h.submissions.create_first(first, order, EVENT)
            for move in moves:
                await move(h, order)
            rows = await h.stops.for_order(order.exchange_account_id, order.id)
            settled[name] = [(row.status, row.answered_at, row.closed_at) for row in rows]
        assert settled == {
            "accepted": [("pending", T0, None)],
            "refused": [("void", None, T0)],
            "filled": [("pending", T0, None)],
        }

    @pytest.mark.parametrize("case", sorted(SWEPT))
    async def test_the_startup_sweep_voids_only_an_unplaced_entrys_rows(
        self, h: Harness, case: str
    ) -> None:
        """R10: never sent, killed before its send, or refused by its create's own answer; each
        voided row audited before the commit, and a refused audit voids nothing."""
        user, (account, profile) = h.new_user(), h.new_account()
        first, order = entry(user, account, profile)
        await h.submissions.create_first(first, order, EVENT)
        moves, unplaced = SWEPT[case]
        for move in moves:
            await move(h, order)
        if unplaced:
            with pytest.raises(RuntimeError):
                await h.stops.void_orphans(account, at=T0, write_ahead=refuses)
        audited: list[SweptStop] = []

        async def audit(swept: tuple[SweptStop, ...]) -> None:
            audited.extend(swept)

        swept = await h.stops.void_orphans(account, at=T0, write_ahead=audit)
        ids = [stop.id for stop in first.recorded_stops] if unplaced else []
        assert [stop.id for stop in swept] == ids and list(swept) == audited
        rows = await h.stops.for_order(account, order.id)
        assert [row.status for row in rows] == ["void" if unplaced else "pending"]

    async def test_one_accounts_sweep_leaves_other_accounts_and_other_requests_alone(
        self, h: Harness
    ) -> None:
        """R10's scope: a sweep of one account voids its unplaced entry's rows only, never another
        account's, and never a request that is not an entry's attach (a trading stop)."""
        user, (account, profile) = h.new_user(), h.new_account()
        other, other_profile = h.new_account()
        mine, mine_order = entry(user, account, profile)
        theirs, their_order = entry(user, other, other_profile)
        for first, order in ((mine, mine_order), (theirs, their_order)):
            await h.submissions.create_first(first, order, EVENT)
        [stop] = await h.stops.insert([trading_stop(account, symbol="ETHUSDT")])
        swept = await h.stops.void_orphans(account, at=T0, write_ahead=audited)
        assert [row.id for row in swept] == [row.id for row in mine.recorded_stops]
        rows = await h.stops.for_order(other, their_order.id)
        assert [row.status for row in rows] == ["pending"]
        assert await waiting(h, account, "ETHUSDT") == (stop,)
