"""The OMS's command port, B1's `CommandPort` (E29-T04 #913; 24-internal-schemas.md Sec.8.3,
Sec.8.4, Sec.8.6, Sec.8.8).

`place` builds the create from the stored order only and sends it through the account's own port
(C-2.11, C-2.10), answering B1 what its guards read: an accepted create's id in the shape the OMS
keeps (#4020 Lows 1-2), a refusal's codes and never the exchange's text (SR-E29-09), a duplicate
with what the lookup found and no top-level id (#4020 Low 3), adopted only on the full match and
audited ahead (C-2.9), another order under the id handed over first (S2-Q3), and a refused rate
token as `RATE_BUDGET_EXCEEDED`. 24 Sec.8.6's branch runs before any answer. A resumed create is
looked up first whatever the switches say, then asks them (C-2.21), and is re-sent only within the
history window (rule 6) and, on live, `LIVE_RESEND_MAX_AGE_S`, past which it ends unsent, audited
and alerted ([LANE-26]). `lookup` raises rather than answer empty after a failed hand-over.
`attach_stop` skips a stop the position shows, audited (Q-E), and otherwise gates, records and
audits the request ahead, sends both sides, settles and reads back; a Partial stop is refused (Q-F).
No stop or take-profit that is no price above zero is sent (#2877 ruling 2); the venue's outage is
raised, never a refusal, and never repeated (#2863); a registered order's records carry its
request's correlation id ([AUDIT-REQUEST-ID]). `cancel` (S4-B1) sends one cancel of the stored
order in the `critical` lane, ungated, its refusal and its raise as a create's, by one deadline
inside B1's own bound on it; a recorded stop's row is never a KILL's to cancel, nor a user's while
a read does not show its position flat (C-2.6, Q9); `expect_exit` gets an exit service B1's answer.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
from collections.abc import Awaitable, Mapping
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.errors import (
    AmbiguousResultError,
    AuthError,
    ClockDriftError,
    DuplicateClientIdError,
    ExchangeError,
    NotFoundError,
    OmsErrorCode,
    RateBudgetExceededError,
    ServiceUnavailableError,
    TransportError,
)
from candleviewer.exchange.base.fakes import FakeReject, LandedThenAmbiguous
from candleviewer.exchange.base.models import (
    CancelOrderRequest,
    OrderAck,
    PlaceOrderRequest,
    TradingStopRequest,
)
from candleviewer.exchange.bybit.trading import CRITICAL_WAIT_S
from candleviewer.observability.context import bind_context
from candleviewer.oms.commands import (
    ACCOUNT_UNAVAILABLE,
    ALREADY_SET,
    ATTACH_GATE_WAIT_S,
    EXPIRED_UNSENT_REASON,
    LIVE_HISTORY_SPAN_S,
    LIVE_RESEND_MAX_AGE_S,
    NEVER_SENT_ALERT,
    PARTIAL_STOP_UNSUPPORTED,
    PORT_TIMEOUT_S,
    RECORDED_STOP_READ_S,
    RESEND_REFUSED,
    STORE_UNAVAILABLE,
    STORE_UNAVAILABLE_RETRY_AFTER_S,
    SUBMIT_TIMEOUT_S,
    OmsCommandPort,
    found_view,
    order_id_kept,
    place_request,
)
from candleviewer.oms.errors import (
    AccountScopeDenied,
    AckWithoutOrderId,
    ClockDriftBlocked,
    HandoverUnavailable,
    OmsNotReady,
    OrderEntryRefused,
    Problem,
    ResendRefused,
    StopRequestInFlight,
    StopRequestPending,
    StoreUnavailable,
    TradingDisabled,
    problem_for,
)
from candleviewer.oms.fakes import FakeClockHealth
from candleviewer.oms.order_machine import OrderAuditRecord, _data_refusal
from candleviewer.oms.ports import (
    STOP_GATE_READ_TIMEOUT_S,
    KeyedRecord,
    NoHandoverStore,
    PositionKey,
)
from candleviewer.oms.stop_gate import ResolvingStopGate
from candleviewer.oms_wiring import NO_ACTIVE_KEY, STOP_REQUEST_BOUND_S, ClockHealthBinding
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.config import (
    CV_COMMAND_TIMEOUT,
    CV_KILL_CANCEL_TIMEOUT,
    CV_PERSIST_TIMEOUT,
)
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.orders import NewOrder, OrderRow
from tests.unit.oms.command_rig import (
    ACCOUNT,
    DAY_US,
    EPOCH,
    HOUR_US,
    LIVE_ACCOUNT,
    STOP,
    SYMBOL,
    T0_US,
    UIDS,
    Handovers,
    Rig,
    build_rig,
    command,
    exchange_order,
    new_order,
    outage,
    position,
    ref,
)
from tests.unit.oms.command_rig import (
    earlier_request as _earlier_request,
)

_DUP = OmsErrorCode.DUPLICATE_CLIENT_ID.value


def _ack(exchange_order_id: object, *, ok: bool = True) -> OrderAck:
    return OrderAck.model_construct(
        ok=ok,
        order_link_id=None,
        exchange_order_id=exchange_order_id,
        error_code=None,
        exchange_ret_code=None,
        exchange_ret_msg=None,
        retryable=False,
        latency_ms=0,
        transport="rest",
        record=None,
    )


# --- the request: built from the stored order only ---------------------------------------------


def test_the_request_is_the_stored_order_in_the_ports_vocabulary() -> None:
    """C-2.10, C-2.6: the same id, terms and native stop on every send; 21's column vocabulary
    becomes 24 Sec.14.4's (`Buy` -> `buy`, `PostOnly` -> `post_only`, `MarkPrice` -> `mark`, `1` ->
    `rise`, `Partial` -> `partial`)."""
    order = new_order(
        side="Sell",
        order_type="Market",
        price=None,
        time_in_force="PostOnly",
        trigger_price=Decimal("59000"),
        trigger_by="MarkPrice",
        trigger_direction=1,
        stop_loss=Decimal("61000"),
        take_profit=Decimal("55000"),
        tpsl_mode="Partial",
        position_idx=2,
        close_on_trigger=True,
    )
    request = place_request(order, ref())
    assert request == PlaceOrderRequest(
        account=ref(),
        symbol=SYMBOL,
        side="sell",
        order_type="market",
        qty=Decimal("0.010"),
        price=None,
        time_in_force="post_only",
        order_link_id=order.order_link_id,
        reduce_only=False,
        close_on_trigger=True,
        position_idx=2,
        trigger_price=Decimal("59000"),
        trigger_by="mark",
        trigger_direction="rise",
        take_profit=Decimal("55000"),
        stop_loss=Decimal("61000"),
        tpsl_mode="partial",
        lane="entry",
    )


@pytest.mark.parametrize(
    ("reduce_only", "intent", "lane"),
    [
        (False, "entry", "entry"),
        (False, "scale_in", "entry"),
        (True, "entry", "entry"),  # a reduce-only order classified an entry (SR-E29-01)
        (True, "stop_loss", "critical"),
        (True, "take_profit", "critical"),
        (True, "scale_out", "critical"),
        (True, "flatten", "critical"),
        (False, "flatten", "entry"),  # never the exits' reserve without reduce-only (C-12.7)
    ],
)
def test_only_a_reduce_only_order_that_reduces_takes_the_critical_lane(
    reduce_only: bool, intent: Any, lane: str
) -> None:
    order = new_order(reduce_only=reduce_only, intent=intent)
    assert place_request(order, ref()).lane == lane


async def test_a_registered_order_is_sent_once_with_its_id_stop_and_take_profit() -> None:
    rig = build_rig()
    order = new_order()
    watch = rig.port.expect(order)
    answer = await rig.port.place(command("place", order))
    assert answer == {"ok": True, "exchange_order_id": "fake-000000000001"}
    (call,) = rig.demo.calls
    assert (call.method, call.account_id, call.lane) == ("place_order", ACCOUNT, "entry")
    assert isinstance(call.request, PlaceOrderRequest)
    sent = (call.request.order_link_id, call.request.stop_loss, call.request.take_profit)
    assert sent == (order.order_link_id, STOP, Decimal("64000"))
    assert call.request.account == ref()
    assert await watch.answer() == answer
    assert rig.live.calls == []


async def test_c_2_11_a_live_accounts_create_goes_on_the_live_port_with_its_own_key() -> None:
    rig = build_rig()
    order = new_order(LIVE_ACCOUNT, "live")
    rig.port.expect(order)
    answer = await rig.port.place(command("place", order))
    assert answer["ok"] is True
    (call,) = rig.live.calls
    assert isinstance(call.request, PlaceOrderRequest)
    assert call.request.account == ref(LIVE_ACCOUNT, "live")
    assert rig.demo.calls == []


async def test_a_command_naming_another_order_than_the_registered_one_sends_nothing() -> None:
    rig = build_rig()
    order = new_order()
    rig.port.expect(order)
    with pytest.raises(ValueError, match="another order"):
        await rig.port.place(command("place", order, order_link_id=new_order(seq=1).order_link_id))
    assert rig.demo.calls == []


@pytest.mark.parametrize(
    ("unnamed", "refused"),
    [("order_id", "does not name its order"), ("order_link_id", "names no order_link_id")],
)
async def test_a_command_that_does_not_name_its_order_sends_nothing(
    unnamed: str, refused: str
) -> None:
    """A command with no order id, or a resumed one with no `order_link_id`, is refused before
    any read or send (`ValueError`: B1's `unknown`)."""
    rig = build_rig()
    order = new_order()
    await rig.stored(order)
    with pytest.raises(ValueError, match=refused):
        await rig.port.place(command("place", order, **{unnamed: None}))
    assert rig.demo.calls == [] and rig.accounts.asked == []


async def test_a_trading_account_resolved_to_another_account_sends_nothing() -> None:
    """SR-E27-21, C-2.11: a resolver that answers another account's ref is refused before any
    send, so no request is signed with another account's key."""
    rig = build_rig()
    order = new_order()
    rig.accounts.seed(ref(LIVE_ACCOUNT, "live"), as_id=ACCOUNT)
    rig.port.expect(order)
    with pytest.raises(ValueError, match="another account's"):
        await rig.port.place(command("place", order))
    assert rig.demo.calls == [] and rig.live.calls == []


# --- the answer of an accepted or refused create (#4020 Lows 1-3) -------------------------------


@pytest.mark.parametrize(
    "exchange_order_id",
    ["x" * 64, "fake-000000000001", "b3c0e6e2-1d4f-4f53-9f7a-2a3c4d5e6f70"],
    ids=["sixty_four", "fake", "uuid"],
)
async def test_an_accepted_create_answers_the_order_id_it_names(
    exchange_order_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = build_rig()
    order = new_order()

    async def accepted(_request: PlaceOrderRequest) -> OrderAck:
        return _ack(exchange_order_id)

    monkeypatch.setattr(rig.demo, "place_order", accepted)
    rig.port.expect(order)
    answer = await rig.port.place(command("place", order))
    assert answer == {"ok": True, "exchange_order_id": exchange_order_id}


_UNKEPT = [None, "", 1, "x" * 65, "x1\n", "x\x00y", " ", "x 1", "x\u00a0y", "\u2028"]


@pytest.mark.parametrize(
    "exchange_order_id",
    _UNKEPT,
    ids=[
        "none",
        "empty",
        "not_text",
        "sixty_five",
        "newline",
        "nul",
        "space",
        "inner_space",
        "nbsp",
        "line_separator",
    ],
)
async def test_an_accepted_create_naming_no_order_id_the_oms_keeps_is_ambiguous(
    exchange_order_id: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 3 on #3972 and #4020 Lows 1-2: B1 lands the order in `unknown` (S1)."""
    rig = build_rig()
    order = new_order()

    async def accepted(_request: PlaceOrderRequest) -> OrderAck:
        return _ack(exchange_order_id)

    monkeypatch.setattr(rig.demo, "place_order", accepted)
    watch = rig.port.expect(order)
    with capture_logs() as logs, pytest.raises(AckWithoutOrderId):
        await rig.port.place(command("place", order))
    assert await watch.answer() is None
    assert [log["event"] for log in logs] == ["oms_ack_without_order_id"]


def test_the_id_the_oms_keeps_is_b1s_text_id_printable_and_without_whitespace() -> None:
    assert order_id_kept("x" * 64) == "x" * 64
    assert all(order_id_kept(raw) is None for raw in _UNKEPT)
    assert all(b01.text_id(raw) is not None for raw in (" ", "x 1", "x\u00a0y", "\u2028"))


async def test_a_refused_create_answers_its_codes_and_never_the_exchanges_text() -> None:
    """SR-E29-09, 24 Sec.8.6 code-only rule: B1 records the code; the message never leaves."""
    rig = build_rig()
    order = new_order()
    reject = FakeReject(OmsErrorCode.INSUFFICIENT_MARGIN, 110007, "do not show this text")
    rig.demo.script("place_order", reject)
    rig.port.expect(order)
    answer = await rig.port.place(command("place", order))
    assert answer == {"ok": False, "error_code": "INSUFFICIENT_MARGIN", "exchange_ret_code": 110007}
    assert "do not show" not in repr(answer)


# --- an order found under the id: adopted, handed over, or unresolved (SR-E29-03, S2-Q3) ----


async def test_a_duplicate_whose_order_matches_is_answered_found_and_audited_ahead() -> None:
    """24 Sec.8.3 rule 3: the lookup's order, no top-level id (#4020 Low 3), and the adoption's
    record written before the answer (C-2.9)."""
    handovers = Handovers()
    rig = build_rig(handovers=handovers)
    order = new_order()
    rig.demo.seed_order(exchange_order(order), uid=UIDS["demo"])
    rig.port.expect(order)
    answer = await rig.port.place(command("place", order))
    found = found_view(exchange_order(order))
    assert answer == {"ok": False, "error_code": _DUP, "lookup": found}
    assert "exchange_order_id" not in answer
    assert rig.calls() == ["place_order", "open_orders"]
    ((record, sent_before),) = rig.audits.written
    assert isinstance(record, OrderAuditRecord)
    assert (record.action, record.outcome, record.reason) == (
        "orders.submit",
        "success",
        "adopted_after_lookup",
    )
    assert (record.order_id, record.account_id, sent_before) == (order.id, ACCOUNT, 2)
    assert record.detail["exchange_order_id"] == found["exchange_order_id"]
    assert record.detail["source"] == "realtime"
    assert handovers.handed == []
    assert b01.full_match(command("place", order).order, answer["lookup"])


async def test_a_duplicate_whose_order_does_not_match_is_handed_over_before_the_answer() -> None:
    handovers = Handovers()
    rig = build_rig(handovers=handovers)
    order = new_order()
    squatter = exchange_order(order, qty=Decimal("0.020"))
    rig.demo.seed_order(squatter, uid=UIDS["demo"])
    rig.port.expect(order)
    with capture_logs() as logs:
        answer = await rig.port.place(command("place", order))
    assert answer == {"ok": False, "error_code": _DUP, "lookup": found_view(squatter)}
    assert handovers.handed == [(ACCOUNT, squatter.exchange_order_id)]
    assert rig.audits.written == []  # nothing adopted
    assert "oms_link_id_held_by_another_order" in [log["event"] for log in logs]
    assert not b01.full_match(command("place", order).order, answer["lookup"])


@pytest.mark.parametrize("handovers", [Handovers(refuse=True), NoHandoverStore()])
async def test_a_hand_over_that_fails_answers_an_empty_lookup(handovers: Any) -> None:
    """S2-Q3: nothing handed over, so nothing is held on it: B1's `unknown` arm."""
    rig = build_rig(handovers=handovers)
    order = new_order()
    rig.demo.seed_order(exchange_order(order, price=Decimal("61000")), uid=UIDS["demo"])
    rig.port.expect(order)
    with capture_logs() as logs:
        answer = await rig.port.place(command("place", order))
    assert answer == {"ok": False, "error_code": _DUP, "lookup": {}}
    assert "oms_handover_failed" in [log["event"] for log in logs]


async def test_a_found_order_whose_money_b1_cannot_read_is_handed_over_never_adopted() -> None:
    """CR-2B1-02 (c): `full_match` raises on money that is not C6 text, which B1's guards deny
    too, so the port reads it as a mismatch: handed over (S2-Q3), never adopted or audited as one,
    even where the figure is the row's (`1e-2`)."""
    handovers = Handovers()
    rig = build_rig(handovers=handovers)
    order = new_order()
    held = exchange_order(order)
    rig.demo.seed_order(held, uid=UIDS["demo"])
    rig.port.expect(order)
    with capture_logs() as logs:
        answer = await rig.port.place(command("place", order, qty="1e-2"))
    assert answer == {"ok": False, "error_code": _DUP, "lookup": found_view(held)}
    assert handovers.handed == [(ACCOUNT, held.exchange_order_id)] and rig.audits.written == []
    assert "oms_link_id_held_by_another_order" in [log["event"] for log in logs]


@pytest.mark.parametrize("lookup_fails", [False, True], ids=["not_found", "lookup_failed"])
async def test_a_duplicate_no_lookup_settles_answers_an_empty_lookup(lookup_fails: bool) -> None:
    rig = build_rig()
    order = new_order()
    rig.demo.script("place_order", DuplicateClientIdError("the id was already accepted"))
    if lookup_fails:
        rig.demo.script("open_orders", TransportError("the read failed"))
    rig.port.expect(order)
    answer = await rig.port.place(command("place", order))
    assert answer == {"ok": False, "error_code": _DUP, "lookup": {}}
    assert rig.audits.written == []


async def test_an_ambiguous_create_is_raised_after_one_send() -> None:
    """SR-E29-15: `unknown`, never a resend (S1)."""
    rig = build_rig()
    order = new_order()
    rig.demo.script("place_order", LandedThenAmbiguous())
    watch = rig.port.expect(order)
    with pytest.raises(AmbiguousResultError):
        await rig.port.place(command("place", order))
    assert rig.calls() == ["place_order"]
    assert await watch.answer() is None


@pytest.mark.parametrize(("wait_s", "retry_after_s"), [(None, 1), (0.2, 1), (2.2, 3), (900.0, 60)])
async def test_a_refused_rate_token_is_rate_budget_exceeded_with_its_retry(
    wait_s: float | None, retry_after_s: int
) -> None:
    """24 Sec.8.7: nothing left, so B1's `rejected`, never `unknown`; the watch keeps the delay."""
    rig = build_rig()
    order = new_order()
    rig.demo.script("place_order", RateBudgetExceededError("no token", retry_after_s=wait_s))
    watch = rig.port.expect(order)
    answer = await rig.port.place(command("place", order))
    assert answer == {
        "ok": False,
        "error_code": "RATE_BUDGET_EXCEEDED",
        "retry_after_s": retry_after_s,
    }
    assert await watch.answer() == answer


async def test_a_create_that_does_not_answer_in_time_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = build_rig(submit_timeout_s=0.01)
    order = new_order()

    async def hangs(_request: PlaceOrderRequest) -> OrderAck:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(rig.demo, "place_order", hangs)
    watch = rig.port.expect(order)
    with pytest.raises(TimeoutError):
        await rig.port.place(command("place", order))
    assert await watch.answer() is None


async def _hangs(*_args: object, **_kwargs: object) -> Any:
    await asyncio.Event().wait()


async def _within(call: Awaitable[Any], seconds: float) -> asyncio.Task[Any]:
    """`call` as a task that its own deadline must have ended within `seconds`; else the test
    fails, the task cancelled."""
    task = asyncio.ensure_future(call)
    await asyncio.wait([task], timeout=seconds)
    if not task.done():
        task.cancel()
        await asyncio.wait([task])
        pytest.fail(f"the call outlasted {seconds} s")
    return task


@pytest.mark.parametrize("hung", ["account", "adoption_record", "hand_over", "credential_report"])
async def test_one_deadline_ends_all_of_a_registered_place(
    hung: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-2B1-04: `SUBMIT_TIMEOUT_S` bounds all of `place`, its answer's calls too, so an entry's
    stop request is answered within this and its three persists ([LANE-25], Q4). A call the
    deadline ends is raised when the answer needs it (the account; the adoption's record, C-2.9:
    B1's `unknown`) and logged when it is best-effort, its answer standing (a hand-over: an empty
    lookup, S2-Q3; a credential report: the refusal), as on its own, longer, timeout."""
    rig = build_rig(submit_timeout_s=0.05, port_timeout_s=60.0)
    order = new_order()
    if hung == "account":
        monkeypatch.setattr(rig.accounts, "trading_account", _hangs)
    elif hung == "adoption_record":
        rig.demo.seed_order(exchange_order(order), uid=UIDS["demo"])
        monkeypatch.setattr(rig.audits, "write", _hangs)
    elif hung == "hand_over":
        rig.demo.seed_order(exchange_order(order, qty=Decimal("0.020")), uid=UIDS["demo"])
        monkeypatch.setattr(rig.handovers, "hand_over_order", _hangs)
    else:
        rig.demo.script("place_order", FakeReject(OmsErrorCode.AUTH_ERROR, 10003))
        monkeypatch.setattr(rig.credentials, "refused", _hangs)
    watch = rig.port.expect(order)
    with capture_logs() as logs:
        task = await _within(rig.port.place(command("place", order)), 5.0)
    lost = [(log["event"], log["failure"]) for log in logs if "failure" in log]
    if hung in ("account", "adoption_record"):
        with pytest.raises(TimeoutError):
            task.result()
        assert await watch.answer() is None
        return
    if hung == "hand_over":
        assert task.result() == {"ok": False, "error_code": _DUP, "lookup": {}}
        assert lost == [("oms_handover_failed", "TimeoutError")]
        return
    refused = {"ok": False, "error_code": "AUTH_ERROR", "exchange_ret_code": 10003}
    assert task.result() == refused and lost == [("oms_auth_rejection_lost", "TimeoutError")]


@pytest.mark.parametrize("hung", ["stored_row", "never_sent_record", "alert"])
async def test_one_deadline_ends_all_of_a_resumed_place(
    hung: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-2B1-04, a create a restart resumes: its stored row's read and its end unsent's record
    are raised at the deadline (C-2.9: nothing answered unrecorded, so B1's `unknown`, nobody
    alerted); the alert, best-effort, is logged CRITICAL and the order still ends unsent."""
    rig = build_rig(submit_timeout_s=0.05, port_timeout_s=60.0)
    order = new_order(LIVE_ACCOUNT, "live")
    await rig.stored(order)
    rig.now.us = T0_US + 121 * SECOND_US
    if hung == "stored_row":
        monkeypatch.setattr(rig.orders, "get_by_link_id", _hangs)
    elif hung == "never_sent_record":
        monkeypatch.setattr(rig.audits, "write", _hangs)
    else:
        monkeypatch.setattr(rig.notices, "notify", _hangs)
    with capture_logs() as logs:
        task = await _within(rig.port.place(command("place", order)), 5.0)
    if hung != "alert":
        with pytest.raises(TimeoutError):
            task.result()
        assert rig.notices.got == []
        return
    assert task.result() == {"ok": False, "error_code": b01.EXPIRED_UNSENT}
    lost = [(log["log_level"], log["failure"]) for log in logs if "failure" in log]
    assert lost == [("critical", "TimeoutError")]


# --- 24 Sec.8.6, before any answer ---------------------------------------------------------------


@pytest.mark.parametrize("ret_code", [10003, 10004, 10005, 10010, 33004])
async def test_an_auth_refusal_passes_its_codes_on_before_the_answer(ret_code: int) -> None:
    """The orchestrator's Q-I ruling: the code and the exchange's return code, as they came."""
    rig = build_rig()
    order = new_order()
    rig.demo.script("place_order", FakeReject(OmsErrorCode.AUTH_ERROR, ret_code))
    rig.port.expect(order)
    answer = await rig.port.place(command("place", order))
    assert rig.credentials.calls == [(ACCOUNT, "AUTH_ERROR", ret_code)]
    assert answer == {"ok": False, "error_code": "AUTH_ERROR", "exchange_ret_code": ret_code}


async def test_an_auth_error_with_no_return_code_is_not_passed_on() -> None:
    """A local refusal (the key vault's, M2's): no exchange code, no verdict on the key."""
    rig = build_rig()
    order = new_order()
    rig.demo.script("place_order", FakeReject(OmsErrorCode.AUTH_ERROR))
    rig.port.expect(order)
    await rig.port.place(command("place", order))
    assert rig.credentials.calls == []


async def test_a_raised_auth_error_with_its_code_is_passed_on_and_raised() -> None:
    """A lookup's read raises on every failure (24 Sec.14.4): the branch runs all the same."""
    rig = build_rig()
    order = new_order()
    rig.demo.script("place_order", DuplicateClientIdError("held"))
    rig.demo.script("open_orders", AuthError("refused", exchange_ret_code=10003))
    rig.port.expect(order)
    with pytest.raises(AuthError):
        await rig.port.place(command("place", order))
    assert rig.credentials.calls == [(ACCOUNT, "AUTH_ERROR", 10003)]


async def test_a_credential_report_that_fails_never_changes_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = build_rig()
    order = new_order()

    async def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("the store is down")

    monkeypatch.setattr(rig.credentials, "refused", broken)
    rig.demo.script("place_order", FakeReject(OmsErrorCode.AUTH_ERROR, 10004))
    rig.port.expect(order)
    with capture_logs() as logs:
        answer = await rig.port.place(command("place", order))
    assert answer["error_code"] == "AUTH_ERROR"
    assert ("oms_auth_rejection_lost", "critical") in [
        (log["event"], log["log_level"]) for log in logs
    ]


async def test_clock_drift_trips_the_halt_and_runs_one_resync_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 Sec.8.6 `10002`: order entry halts until a measurement taken after the trip clears it,
    and a second refusal while the resync runs starts no other."""
    rig = build_rig()
    measured, reasons = asyncio.Event(), []

    async def resync(*, reason: str) -> int:
        reasons.append(reason)
        await measured.wait()
        rig.health.measure()
        return 0

    monkeypatch.setattr(rig.health, "resync_after_signature_failure", resync)
    rig.demo.script(
        "place_order",
        FakeReject(OmsErrorCode.CLOCK_DRIFT, 10002),
        FakeReject(OmsErrorCode.CLOCK_DRIFT, 10002),
    )
    for order in (new_order(), new_order(seq=1)):
        rig.port.expect(order)
        answer = await rig.port.place(command("place", order))
        assert answer == {"ok": False, "error_code": "CLOCK_DRIFT", "exchange_ret_code": 10002}
    assert isinstance(rig.halt.refusal(), ClockDriftBlocked)
    task = rig.port.resync_task
    assert task is not None and reasons == ["order_10002"]
    rig.monotonic.s += 1  # the resync measures after the trip
    measured.set()
    await task
    assert reasons == ["order_10002"]
    assert rig.halt.refusal() is None


async def test_aclose_cancels_a_running_resync_and_none_starts_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-2B1-09 (every task owned, C-2.18): at shutdown the resync a `CLOCK_DRIFT` started is
    cancelled and awaited, a second `aclose` does nothing more, and a `CLOCK_DRIFT` after it still
    trips the halt, and counts, but starts no resync."""
    rig = build_rig()
    started = asyncio.Event()

    async def resync(*, reason: str) -> int:
        started.set()
        await asyncio.Event().wait()
        return 0

    monkeypatch.setattr(rig.health, "resync_after_signature_failure", resync)
    drift = FakeReject(OmsErrorCode.CLOCK_DRIFT, 10002)
    rig.demo.script("place_order", drift, drift)
    first, second = new_order(), new_order(seq=1)
    rig.port.expect(first)
    await rig.port.place(command("place", first))
    task = rig.port.resync_task
    assert task is not None
    await started.wait()
    await rig.port.aclose()
    assert task.cancelled()
    await rig.port.aclose()
    rig.port.expect(second)
    await rig.port.place(command("place", second))
    assert rig.port.resync_task is task and isinstance(rig.halt.refusal(), ClockDriftBlocked)
    trips = rig.metrics.registry.get_sample_value("oms_clock_halt_trips_total", {"env": "demo"})
    assert trips == 2.0


async def test_a_raised_clock_drift_trips_the_halt_too() -> None:
    rig = build_rig()
    order = new_order()
    rig.demo.script("place_order", ClockDriftError("recv_window"))
    rig.port.expect(order)
    with pytest.raises(ClockDriftError):
        await rig.port.place(command("place", order))
    assert isinstance(rig.halt.refusal(), ClockDriftBlocked)
    assert rig.port.resync_task is not None
    await rig.port.resync_task


# --- a create a restart resumes (SR-E29-15, C-2.21, 24 Sec.8.3 rule 6, [LANE-26]) ---------------

_LOOKUP = ["open_orders", "order_history"]
SECOND_US = 1_000_000


async def _resumed(rig: Rig, order: NewOrder, *, age_us: int) -> Mapping[str, Any]:
    """`order` stored as a restart finds it, `age_us` old when its `place` resumes."""
    await rig.stored(order)
    rig.now.us = T0_US + age_us
    return await rig.port.place(command("place", order))


def test_the_live_resend_bound_is_at_most_two_minutes_and_only_ever_tightened() -> None:
    """[LANE-26]: 120 s, which a change may lower and never raise; the port refuses a larger
    bound, and a bound that is no figure."""
    assert 0 <= LIVE_RESEND_MAX_AGE_S <= 120
    for bound in (120.000001, 3_600.0, float("inf"), float("nan"), -1.0):
        with pytest.raises(ValueError, match="tightened"):
            build_rig(live_resend_max_age_s=bound)
    for tighter in (0.0, 60.0):
        build_rig(live_resend_max_age_s=tighter)


async def test_a_registered_create_is_not_asked_again() -> None:
    """The pipeline asks the switches itself, at step 6, just before the persist."""
    rig = build_rig()
    order = new_order()
    rig.switches.refusals[ACCOUNT] = TradingDisabled()
    rig.port.expect(order)
    assert (await rig.port.place(command("place", order)))["ok"] is True
    assert rig.switches.asked == []


@pytest.mark.parametrize("refused", [False, True], ids=["switches_on", "switches_refuse"])
async def test_a_resumed_create_is_looked_up_first_and_one_found_is_adopted_unsent(
    refused: bool,
) -> None:
    """[LANE-26] step 1 (C-2.10): reading is never an order, so the lookup runs whatever the
    switches say, and an order the venue holds is adopted with nothing sent, past the bound too."""
    rig = build_rig()
    order = new_order(LIVE_ACCOUNT, "live")
    if refused:
        rig.switches.refusals[LIVE_ACCOUNT] = TradingDisabled()
    held = exchange_order(order, state="filled")
    rig.live.seed_order(held, uid=UIDS["live"])
    answer = await _resumed(rig, order, age_us=2 * DAY_US)
    assert answer == {"ok": False, "error_code": _DUP, "lookup": found_view(held)}
    assert rig.calls(rig.live) == _LOOKUP and rig.switches.asked == []
    assert rig.audits.actions() == [("orders.submit", "adopted_after_lookup")]
    assert rig.notices.got == []


@pytest.mark.parametrize("age_us", [SECOND_US, 2 * DAY_US], ids=["young", "past_the_bound"])
async def test_the_switches_refuse_a_resumed_create_after_its_lookup_and_before_any_send(
    age_us: int,
) -> None:
    """[LANE-26] step 2 (C-2.21): a refusal sends nothing (`ResendRefused`: B1 lands the order in
    `unknown`), and comes before the bound is read, so nothing ends unsent while they refuse."""
    rig = build_rig()
    order = new_order(LIVE_ACCOUNT, "live")
    rig.switches.refusals[LIVE_ACCOUNT] = TradingDisabled()
    with pytest.raises(ResendRefused) as refused:
        await _resumed(rig, order, age_us=age_us)
    assert isinstance(refused.value.refusal, TradingDisabled)
    assert rig.switches.asked == [(LIVE_ACCOUNT, "live")]
    assert rig.calls(rig.live) == _LOOKUP
    assert rig.audits.written == [] and rig.notices.got == []


@pytest.mark.parametrize("live", [False, True], ids=["demo_in_window", "live_past_the_bound"])
async def test_a_tripped_clock_halt_refuses_a_resumed_create_after_the_switches(live: bool) -> None:
    """SEC-2B1-01 (24 Sec.8.6 `10002`, C-2.21): while the halt stands, a resumed create no lookup
    found is `ResendRefused` with the halt's own refusal, so B1 lands it in `unknown` to wait for
    the resync: never re-sent under the drifted clock, whose `10002` would end it `rejected`, and
    never ended unsent while the halt refuses. The switches are asked first."""
    rig = build_rig()
    order, venue = (new_order(LIVE_ACCOUNT, "live"), rig.live) if live else (new_order(), rig.demo)
    rig.halt.trip()
    with pytest.raises(ResendRefused) as refused:
        await _resumed(rig, order, age_us=121 * SECOND_US if live else 60 * SECOND_US)
    assert isinstance(refused.value.refusal, ClockDriftBlocked)
    assert rig.switches.asked == [(order.exchange_account_id, "live" if live else "demo")]
    assert rig.calls(venue) == _LOOKUP
    assert rig.audits.written == [] and rig.notices.got == []


@pytest.mark.parametrize("age_us", [SECOND_US, 2 * DAY_US], ids=["young", "past_the_bound"])
async def test_an_unmeasured_clock_leaves_a_resumed_create_unsent_as_not_ready(age_us: int) -> None:
    """Ruling Q8 (CR-S3B2-02): the binding answers a clock no measurement has answered for with
    `OmsNotReady`, which `ClockHalt.refusal` lets through, after the switches, before the bound
    is read. The port logs it `oms_resend_refused` with its code, as a refusal is, and raises it as
    it is, so B1 lands the order in `unknown`: nothing sent, no record, no alert."""
    rig = build_rig(clock=ClockHealthBinding(FakeClockHealth(lambda: 0.0)))  # never measured
    order = new_order(LIVE_ACCOUNT, "live")
    with capture_logs() as logs, pytest.raises(OmsNotReady) as refused:
        await _resumed(rig, order, age_us=age_us)
    assert problem_for(refused.value).code == "oms_not_ready"
    assert rig.switches.asked == [(LIVE_ACCOUNT, "live")]
    assert rig.calls(rig.live) == _LOOKUP
    assert rig.audits.written == [] and rig.notices.got == []
    [line] = [log for log in logs if log["event"] == "oms_resend_refused"]
    assert (line["refusal"], line["code"]) == ("OmsNotReady", "oms_not_ready")
    assert line["order_link_id"] == order.order_link_id and line["log_level"] == "warning"


@pytest.mark.parametrize(
    ("age_us", "resent"),
    [
        (119 * SECOND_US, True),
        (120 * SECOND_US, True),
        (120 * SECOND_US + 1, False),
        (121 * SECOND_US, False),
    ],
    ids=["119s", "exactly_120s", "120s_and_1us", "121s"],
)
async def test_live_resends_up_to_the_bound_and_never_past_it(age_us: int, resent: bool) -> None:
    """[LANE-26] steps 3 and 4: a live create no lookup found is re-sent while its age is at most
    `LIVE_RESEND_MAX_AGE_S`, so at exactly 120 s it still is (the port reads `age > bound` as too
    old), under the same id and stop, after `adopt_or_resend`'s own lookup; a microsecond past the
    bound it never is, and ends unsent (within the venue's history span: the next test)."""
    rig = build_rig()
    order = new_order(LIVE_ACCOUNT, "live")
    answer = await _resumed(rig, order, age_us=age_us)
    calls = rig.calls(rig.live)
    if resent:
        assert calls == [*_LOOKUP, *_LOOKUP, "place_order"]
        request = rig.live.calls[-1].request
        assert isinstance(request, PlaceOrderRequest)
        assert (request.order_link_id, request.stop_loss) == (order.order_link_id, STOP)
        assert answer["ok"] is True and rig.notices.got == []
        return
    assert calls == _LOOKUP
    assert answer == {"ok": False, "error_code": b01.EXPIRED_UNSENT}
    assert rig.audits.actions() == [(RESEND_REFUSED, EXPIRED_UNSENT_REASON)]
    assert len(rig.notices.got) == 1


async def test_a_live_create_past_the_bound_ends_unsent_with_its_record_and_alert() -> None:
    """[LANE-26] step 4: the record (`oms.resend_refused`, its age and the bound) is written ahead,
    then the user is alerted through the OMS's notice route; the answer takes `submitting`'s last
    arm, `rejected` with `EXPIRED_UNSENT` (B1's contract test drives it)."""
    rig = build_rig()
    order = new_order(LIVE_ACCOUNT, "live")
    answer = await _resumed(rig, order, age_us=121 * SECOND_US)
    assert answer == {"ok": False, "error_code": "EXPIRED_UNSENT"}
    ((record, sent_before),) = rig.audits.written
    assert isinstance(record, OrderAuditRecord)
    assert (record.action, record.outcome, record.severity, record.reason) == (
        "oms.resend_refused",
        "denied",
        "warning",
        "expired_unsent",
    )
    assert (record.order_id, record.account_id, record.request_id) == (order.id, LIVE_ACCOUNT, None)
    detail = {"order_link_id": order.order_link_id, "age_s": "121", "bound_s": "120"}
    assert record.detail == detail and sent_before == 2  # the lookup's two reads, no create
    (notice,) = rig.notices.got
    assert (notice.kind, notice.order_id, notice.account_id, notice.order_link_id) == (
        "alert",
        order.id,
        LIVE_ACCOUNT,
        order.order_link_id,
    )
    assert notice.detail == {
        "alert": NEVER_SENT_ALERT,
        "created_at": "2026-10-21T12:00:00+00:00",
        "message": (
            "an order from 2026-10-21 12:00:00 UTC was not found within the venue's 24 h history "
            "and was not placed; re-enter it if still wanted"
        ),
    }


@pytest.mark.parametrize(
    ("age_us", "ended"),
    [
        (121 * SECOND_US, True),
        (DAY_US - 1, True),
        (DAY_US, False),
        (DAY_US + 1, False),
        (30 * DAY_US, False),
    ],
    ids=["121s", "a_microsecond_inside_the_span", "exactly_the_span", "past_the_span", "a_month"],
)
async def test_a_live_miss_ends_unsent_only_within_the_venues_history_span(
    age_us: int, ended: bool
) -> None:
    """SEC-2B1-02 (the orchestrator's ruling), both arms. Within the venue's 24 h history
    (`LIVE_HISTORY_SPAN_S`) a miss in open orders and history means the create never landed, so
    it ends unsent, recorded and alerted ([LANE-26]). At or past it a miss proves nothing (24
    Sec.14.1): the answer is an empty lookup, B1's `unknown`, for reconciliation, with nothing
    sent, recorded or alerted, so its entry's attach rows wait instead of being voided blind."""
    assert LIVE_HISTORY_SPAN_S * SECOND_US == DAY_US
    rig = build_rig()
    with capture_logs() as logs:
        answer = await _resumed(rig, new_order(LIVE_ACCOUNT, "live"), age_us=age_us)
    assert rig.calls(rig.live) == _LOOKUP
    past = [log["log_level"] for log in logs if log["event"] == "oms_resend_past_history"]
    if ended:
        assert answer == {"ok": False, "error_code": b01.EXPIRED_UNSENT} and past == []
        assert rig.audits.actions() == [(RESEND_REFUSED, EXPIRED_UNSENT_REASON)]
        assert [notice.kind for notice in rig.notices.got] == ["alert"]
        return
    assert answer == {"ok": False, "error_code": _DUP, "lookup": {}} and past == ["warning"]
    assert rig.audits.written == [] and rig.notices.got == []


async def test_an_end_unsent_whose_record_does_not_land_raises_and_alerts_nothing() -> None:
    """C-2.9: nothing is answered unrecorded, so B1 lands the order in `unknown` instead."""
    rig = build_rig()
    rig.audits.refuse = RuntimeError("the audit lane refused")
    with pytest.raises(RuntimeError, match="audit lane"):
        await _resumed(rig, new_order(LIVE_ACCOUNT, "live"), age_us=121 * SECOND_US)
    assert rig.notices.got == [] and rig.calls(rig.live) == _LOOKUP


async def test_a_never_sent_alert_that_does_not_land_is_logged_and_the_order_still_ends() -> None:
    """Never dropped silently: the lost alert is logged CRITICAL, and the record stands."""
    rig = build_rig()
    rig.notices.refuse = True
    with capture_logs() as logs:
        answer = await _resumed(rig, new_order(LIVE_ACCOUNT, "live"), age_us=121 * SECOND_US)
    assert answer == {"ok": False, "error_code": "EXPIRED_UNSENT"}
    lost = [log["log_level"] for log in logs if log["event"] == "oms_never_sent_alert_lost"]
    assert lost == ["critical"]
    assert rig.audits.actions() == [(RESEND_REFUSED, EXPIRED_UNSENT_REASON)]


@pytest.mark.parametrize(
    "met",
    [
        DuplicateClientIdError("the order_link_id was already accepted"),
        FakeReject(OmsErrorCode.DUPLICATE_CLIENT_ID, 110072),
        LandedThenAmbiguous(),
        RateBudgetExceededError("no token", retry_after_s=1.0),
    ],
    ids=["duplicate_raised", "duplicate_answered", "landed_then_ambiguous", "refused_token"],
)
async def test_a_resend_the_venue_may_hold_is_looked_up_by_b1_never_renamed(met: Any) -> None:
    """[LANE-26] step 3, the race after a missed lookup: the venue took the earlier create once
    the lookups had missed it, so the one re-send meets a duplicate, "already accepted" (or its
    outcome stays open). One create, the same id and stop, and a duplicate answer with no lookup,
    so B1 looks the id up at once (24 Sec.8.3 rule 3) and binds what it finds only on its full
    match; nothing is ever sent under a new id."""
    rig = build_rig()
    order = new_order(LIVE_ACCOUNT, "live")
    rig.live.script("place_order", met)
    answer = await _resumed(rig, order, age_us=30 * SECOND_US)
    assert answer == {"ok": False, "error_code": _DUP}
    creates = [call.request for call in rig.live.calls if call.method == "place_order"]
    assert len(creates) == 1 and isinstance(creates[0], PlaceOrderRequest)
    assert (creates[0].order_link_id, creates[0].stop_loss) == (order.order_link_id, STOP)


@pytest.mark.parametrize(
    ("age_us", "resent"),
    [(121 * SECOND_US, True), (HOUR_US, True), (6 * DAY_US, True), (6 * DAY_US + 1, False)],
    ids=["121s", "an_hour", "six_days", "past"],
)
async def test_demo_keeps_its_six_day_bound(age_us: int, resent: bool) -> None:
    """Rule 6, which [LANE-26] leaves alone: demo keeps 7 days of history, so it re-sends for 6
    days, and an id older than that is unresolvable by history (`unknown`), never ended unsent."""
    rig = build_rig()
    answer = await _resumed(rig, new_order(), age_us=age_us)
    assert ("place_order" in rig.calls()) is resent
    assert answer["ok"] is resent
    if not resent:
        assert answer == {"ok": False, "error_code": _DUP, "lookup": {}}
    assert rig.audits.written == [] and rig.notices.got == []


@pytest.mark.parametrize("live", [False, True], ids=["demo_in_window", "live_past_the_bound"])
async def test_a_resumed_lookup_that_fails_never_resends(live: bool) -> None:
    rig = build_rig()
    order = new_order(LIVE_ACCOUNT, "live") if live else new_order()
    await rig.stored(order)
    port = rig.live if live else rig.demo
    port.script("order_history", TransportError("the read failed"))
    rig.now.us = T0_US + (2 * DAY_US if live else 60 * SECOND_US)
    answer = await rig.port.place(command("place", order))
    assert answer == {"ok": False, "error_code": _DUP, "lookup": {}}
    assert rig.calls(port) == _LOOKUP and rig.notices.got == []


@pytest.mark.parametrize("gate", ["auth", "clock"])
async def test_a_resumed_lookup_that_meets_a_trading_gate_is_raised_and_sends_nothing(
    gate: str,
) -> None:
    """24 Sec.8.6 before any answer: an `AuthError` or a `ClockDriftError` from the first lookup
    gates trading, so its branch runs and it is raised (B1: `unknown`), with nothing sent."""
    rig = build_rig()
    order = new_order(LIVE_ACCOUNT, "live")
    raised = (
        AuthError("the key expired", exchange_ret_code=33004)
        if gate == "auth"
        else ClockDriftError("recv_window", exchange_ret_code=10002)
    )
    rig.live.script("open_orders", raised)
    with pytest.raises(type(raised)):
        await _resumed(rig, order, age_us=SECOND_US)
    assert rig.calls(rig.live) == ["open_orders"] and rig.switches.asked == []
    if gate == "auth":
        assert rig.credentials.calls == [(LIVE_ACCOUNT, "AUTH_ERROR", 33004)]
        return
    assert isinstance(rig.halt.refusal(), ClockDriftBlocked)
    assert rig.port.resync_task is not None
    await rig.port.resync_task


async def test_a_resumed_create_with_no_stored_row_sends_nothing() -> None:
    rig = build_rig()
    with pytest.raises(ValueError, match="no stored order"):
        await rig.port.place(command("place", new_order()))
    assert rig.demo.calls == []


# --- lookup: before a create this process did not begin (SR-E29-15) ------------------------------


async def test_lookup_answers_nothing_when_no_order_holds_the_id() -> None:
    rig = build_rig()
    order = new_order()
    await rig.stored(order)
    assert await rig.port.lookup(command("lookup", order)) == {}
    assert rig.calls() == ["open_orders", "order_history"]


async def test_lookup_answers_the_matching_order_audited_ahead() -> None:
    rig = build_rig()
    order = new_order()
    await rig.stored(order)
    rig.demo.seed_order(exchange_order(order), uid=UIDS["demo"])
    found = await rig.port.lookup(command("lookup", order))
    assert found == found_view(exchange_order(order))
    assert rig.audits.actions() == [("orders.submit", "adopted_after_lookup")]


async def test_lookup_hands_another_order_over_before_answering_it() -> None:
    handovers = Handovers()
    rig = build_rig(handovers=handovers)
    order = new_order()
    await rig.stored(order)
    squatter = exchange_order(order, side="sell")
    rig.demo.seed_order(squatter, uid=UIDS["demo"])
    assert await rig.port.lookup(command("lookup", order)) == found_view(squatter)
    assert handovers.handed == [(ACCOUNT, squatter.exchange_order_id)]


async def test_lookup_raises_when_the_hand_over_fails() -> None:
    """S2-Q3 as corrected: an empty answer here would make B1 send the order."""
    rig = build_rig(handovers=NoHandoverStore())
    order = new_order()
    await rig.stored(order)
    rig.demo.seed_order(exchange_order(order, side="sell"), uid=UIDS["demo"])
    with pytest.raises(HandoverUnavailable):
        await rig.port.lookup(command("lookup", order))


async def test_lookup_raises_when_a_read_fails() -> None:
    rig = build_rig()
    order = new_order()
    await rig.stored(order)
    rig.demo.script("open_orders", TransportError("the read failed"))
    with pytest.raises(TransportError):
        await rig.port.lookup(command("lookup", order))


async def test_lookup_of_a_registered_order_reads_the_registration_and_keeps_it() -> None:
    """A resync can make B1 look before its first send: the registration stays for `place`."""
    rig = build_rig()
    order = new_order()
    watch = rig.port.expect(order)
    assert await rig.port.lookup(command("lookup", order)) == {}
    assert not watch.answered
    assert (await rig.port.place(command("place", order)))["ok"] is True
    assert (await watch.answer() or {}).get("ok") is True


# --- attach_stop (24 Sec.8.8 rules 2 and 6; 21 Sec.3.3.11) ----------------------------------------


def _attach(order: Any, stop: str = "58000") -> b01.Command:
    return command("attach_stop", order, {"stop_loss": stop})


async def _filled(rig: Any, order: Any = None) -> Any:
    """An entry whose first fill started its stop: stored, as B1's `sl_pending` finds it."""
    order = order if order is not None else new_order()
    await rig.stored(order, lifecycle="submitted")
    return order


def _rows(rig: Any) -> list[Any]:
    """Every recorded stop the in-memory store holds (its own table, read directly)."""
    return list(rig.store._stops.values())


async def test_attach_skips_the_call_when_the_position_shows_the_stop_but_still_audits_it() -> None:
    """Q-E: the saving is the `critical` call, never the trail (C-2.9)."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position(stop_loss=STOP, updated_at=T0_US + 5_000))
    answer = await rig.port.attach_stop(_attach(order))
    reading = {"updated_time": (T0_US + 5_000) // 1_000, "stop_loss": "58000", "size": "0.01"}
    assert answer == {"ok": True, "position": reading}
    assert rig.calls() == ["positions"]
    ((record, _),) = rig.audits.written
    assert isinstance(record, OrderAuditRecord)
    assert (record.action, record.outcome, record.reason) == ("sl.attached", "success", ALREADY_SET)
    assert (record.order_id, record.account_id) == (order.id, ACCOUNT)
    assert _rows(rig) == []


async def test_attach_records_and_audits_its_request_before_the_send() -> None:
    """21 Sec.3.3.11: the row is written ahead, its `sl.attached` record in the insert's
    transaction and named by the row (`audit_record_id`), then the call, then the answer."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    rig.now.us = T0_US + 7_000_000
    answer = await rig.port.attach_stop(_attach(order))
    assert rig.calls() == ["positions", "set_trading_stop", "positions"]
    ((record, sent_before),) = rig.audits.written
    assert isinstance(record, KeyedRecord)
    assert (record.action, record.reason, record.object_kind) == (
        "sl.attached",
        "first_fill_attach",
        "recorded_stop",
    )
    assert (record.actor_user_id, record.outcome, sent_before) == (None, "success", 1)
    (row,) = _rows(rig)
    assert (row.source, row.kind, row.status, row.tpsl_mode) == (
        "trading_stop",
        "stop_loss",
        "pending",
        "Full",
    )
    assert (row.trigger_price, row.size, row.order_id, row.position_marker) == (
        STOP,
        None,
        None,
        None,
    )
    assert (row.position_side, row.position_idx, row.actor_user_id) == ("Buy", 0, None)
    assert record.object_id == row.id and record.name == str(row.id)
    assert row.audit_record_id == rig.audits.record_id("sl.attached", str(row.id))
    assert row.answered_at == EPOCH + timedelta(microseconds=T0_US + 7_000_000)
    assert answer["ok"] is True and answer["position"]["stop_loss"] == "58000"


async def test_attach_sends_both_sides_the_take_profit_as_the_position_shows_it() -> None:
    """24 Sec.8.9: one call writes both sides, so the take-profit the position shows goes too."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position(take_profit=Decimal("64000")))
    await rig.port.attach_stop(_attach(order))
    call = rig.demo.calls[1]
    assert (call.method, call.lane) == ("set_trading_stop", "critical")
    assert call.request == TradingStopRequest(
        account=ref(), symbol=SYMBOL, stop_loss=STOP, take_profit=Decimal("64000")
    )


async def test_a_refused_attach_voids_its_row_audited_ahead() -> None:
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    reject = FakeReject(OmsErrorCode.INSTRUMENT_FILTER, 110003, "do not show this text")
    rig.demo.script("set_trading_stop", reject)
    answer = await rig.port.attach_stop(_attach(order))
    assert {key: answer[key] for key in ("ok", "error_code", "exchange_ret_code")} == {
        "ok": False,
        "error_code": "INSTRUMENT_FILTER",
        "exchange_ret_code": 110003,
    }
    assert answer["position"]["stop_loss"] is None and "do not show" not in repr(answer)
    (row,) = _rows(rig)
    assert row.status == "void"
    assert rig.audits.actions() == [
        ("sl.attached", "first_fill_attach"),
        ("sl.modified", "trading_stop_refused"),
    ]
    void = rig.audits.written[1][0]
    assert isinstance(void, KeyedRecord) and void.object_id == row.id
    assert void.detail["error_code"] == "INSTRUMENT_FILTER"


async def test_an_attach_whose_send_raises_leaves_its_row_in_flight() -> None:
    """Only the complete read resolves a request with no answer (21 Sec.3.3.11)."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    rig.demo.script("set_trading_stop", TransportError("cut off"))
    with pytest.raises(TransportError):
        await rig.port.attach_stop(_attach(order))
    (row,) = _rows(rig)
    assert (row.status, row.answered_at) == ("pending", None)
    assert rig.calls() == ["positions", "set_trading_stop"]


@pytest.mark.parametrize("accepted", [True, False], ids=["answered", "refused"])
async def test_an_attach_whose_settle_fails_answers_the_exchange_and_leaves_its_row_in_flight(
    accepted: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-2B1-02 (b), 21 Sec.3.3.11: the exchange's answer stands, and the row, which only the
    complete read now ends, stays in flight; the failure is logged, and a void it did not write
    is not audited either."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    if not accepted:
        rig.demo.script("set_trading_stop", FakeReject(OmsErrorCode.INSTRUMENT_FILTER, 110003))

    async def broken(*_args: object, **_kwargs: object) -> Any:
        raise OSError("the store is down")

    monkeypatch.setattr(rig.stops, "settle", broken)
    with capture_logs() as logs:
        answer = await rig.port.attach_stop(_attach(order))
    assert answer["ok"] is accepted
    (row,) = _rows(rig)
    assert (row.status, row.answered_at) == ("pending", None)
    failed = [log for log in logs if log["event"] == "oms_stop_settle_failed"]
    assert [(log["log_level"], log["answered"], log["failure"]) for log in failed] == [
        ("error", accepted, "OSError")
    ]
    assert rig.audits.actions() == [("sl.attached", "first_fill_attach")]


async def test_a_stop_gate_that_does_not_answer_is_bounded_and_nothing_is_recorded() -> None:
    """CR-2B1-03 (C-2.18): the gate's call is bounded as any other, whatever the gate bounds
    itself, so a gate that never answers ends the attach with `TimeoutError` (B1's
    `sl_missing`), with nothing recorded or sent."""

    class _Stuck:
        async def clear(
            self, key: PositionKey, *, wait_s: float = 0.0, protective: bool = False
        ) -> None:
            await asyncio.Event().wait()

    rig = build_rig(gate=_Stuck(), port_timeout_s=0.05)
    order = await _filled(rig)
    rig.demo.seed_position(position())
    task = await _within(rig.port.attach_stop(_attach(order)), 5.0)
    with pytest.raises(TimeoutError):
        task.result()
    assert rig.calls() == ["positions"] and _rows(rig) == [] and rig.audits.written == []


async def test_an_attach_sends_while_the_switches_refuse_and_the_clock_halt_stands() -> None:
    """CR-2B1-05 (24 Sec.8.10's carve-out, C-2.6, C-4.14): attaching a missing native stop is a
    protective write that no synchronous refusal gates, the switches' (the kill switch, live
    enablement, the order-entry gate) and the clock halt's alike, so it is recorded, sent and
    read back as on any day, and the switches are never asked."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    rig.switches.refusals[ACCOUNT] = TradingDisabled()
    rig.halt.trip()
    assert isinstance(rig.halt.refusal(), ClockDriftBlocked)
    answer = await rig.port.attach_stop(_attach(order))
    assert answer["ok"] is True and answer["position"]["stop_loss"] == "58000"
    assert rig.calls() == ["positions", "set_trading_stop", "positions"]
    assert rig.switches.asked == [] and [row.status for row in _rows(rig)] == ["pending"]


async def test_a_row_waiting_for_the_complete_read_holds_the_attach_until_its_read_ends() -> None:
    """24 Sec.8.4: the attach waits for the complete read it starts, which voids the earlier request
    its position does not show (`in_flight_resolved`, audited ahead); then it sends its own."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    await _earlier_request(rig)
    rig.now.us = T0_US + round(STOP_REQUEST_BOUND_S * 1_000_000)  # at the bound: it waits
    answer = await rig.port.attach_stop(_attach(order))
    assert answer["ok"] is True
    assert rig.calls() == ["positions", "positions", "set_trading_stop", "positions"]
    assert [row.status for row in _rows(rig)] == ["void", "pending"]
    assert rig.audits.actions()[:2] == [
        ("sl.modified", "in_flight_resolved"), ("sl.attached", "first_fill_attach"),
    ]  # fmt: skip


async def test_an_attach_whose_key_stays_held_is_refused_as_an_entry_is() -> None:
    """Q-A and Q-D: a key its read cannot clear (a `restore` row, E29-T06's) is 409
    `stop_request_in_flight`, `Retry-After: 5`, nothing recorded or sent: B1's `sl_missing`."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    await _earlier_request(rig, "restore")
    rig.now.us = T0_US + round(STOP_REQUEST_BOUND_S * 1_000_000)
    with pytest.raises(StopRequestPending) as refused:
        await rig.port.attach_stop(_attach(order))
    assert refused.value.retry_after_s == 5
    assert problem_for(refused.value) == Problem(409, "stop_request_in_flight", retry_after=True)
    assert rig.calls() == ["positions"] and len(_rows(rig)) == 1


async def test_a_request_in_flight_inside_its_bound_refuses_the_insert() -> None:
    """Q2: inside its bound the row is not waiting; the second request meets it at the insert."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    await _earlier_request(rig)
    rig.now.us = T0_US + 1_000_000
    with pytest.raises(StopRequestInFlight):
        await rig.port.attach_stop(_attach(order))
    assert rig.calls() == ["positions"] and len(_rows(rig)) == 1


async def test_a_partial_mode_stop_is_refused_before_anything_is_sent() -> None:
    """Q-F: no stop size can be sent yet (24 Sec.8.9), so B1 goes to `sl_missing` and B8."""
    rig = build_rig()
    order = await _filled(rig, new_order(tpsl_mode="Partial"))
    answer = await rig.port.attach_stop(_attach(order))
    assert answer == {"ok": False, "error_code": PARTIAL_STOP_UNSUPPORTED}
    assert rig.demo.calls == [] and _rows(rig) == []
    ((record, _),) = rig.audits.written
    assert isinstance(record, OrderAuditRecord)
    assert (record.action, record.outcome, record.reason) == (
        "sl.attached",
        "denied",
        "partial_mode",
    )


async def test_an_attach_whose_audit_does_not_land_records_and_sends_nothing() -> None:
    """C-2.9: the hook fails the insert, so no row is written and nothing is sent."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    rig.audits.refuse = RuntimeError("the audit lane refused")
    with pytest.raises(RuntimeError, match="audit lane"):
        await rig.port.attach_stop(_attach(order))
    assert rig.calls() == ["positions"] and _rows(rig) == []


async def test_an_attach_reads_and_sends_on_its_own_environments_port() -> None:
    rig = build_rig()
    order = await _filled(rig, new_order(LIVE_ACCOUNT, "live"))
    rig.live.seed_position(position(LIVE_ACCOUNT))
    answer = await rig.port.attach_stop(_attach(order))
    assert answer["ok"] is True
    assert rig.calls(rig.live) == ["positions", "set_trading_stop", "positions"]
    assert rig.demo.calls == []


_NO_STOP: list[dict[str, Any]] = [
    {},
    {"stop_loss": None},
    {"stop_loss": "0"},
    {"stop_loss": "-0"},
    {"stop_loss": "-1"},
    {"stop_loss": "NaN"},
    {"stop_loss": "sNaN"},
    {"stop_loss": "Infinity"},
    {"stop_loss": "-Infinity"},
    {"stop_loss": "x"},
]


@pytest.mark.parametrize("terms", _NO_STOP)
async def test_an_attach_without_a_usable_stop_sends_nothing(terms: dict[str, Any]) -> None:
    rig = build_rig()
    order = await _filled(rig)
    with pytest.raises(ValueError, match="stop"):
        await rig.port.attach_stop(command("attach_stop", order, terms))
    assert rig.demo.calls == []


async def test_an_attach_for_no_stored_order_sends_nothing() -> None:
    rig = build_rig()
    with pytest.raises(ValueError, match="no stored order"):
        await rig.port.attach_stop(_attach(new_order()))
    assert rig.demo.calls == []


async def test_the_attach_answer_is_a_reading_b1s_guard_takes() -> None:
    """B1.5: `sl_attach_ok` confirms the requested stop on the open position the read-back shows."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    answer = await rig.port.attach_stop(_attach(order))
    assert b01.sl_attach_ok({"stop_loss": "58000"}, SimpleNamespace(data=answer))
    assert not b01.sl_attach_ok({"stop_loss": "57000"}, SimpleNamespace(data=answer))


# --- no stop or take-profit that is no price above zero is sent (#2877 ruling 2, C-2.6) ---------

#: Prices a registered `NewOrder` can carry (2a's `check_fields` refuses a non-finite figure, and
#: the store's CHECK refuses these at the insert).
_NOT_ABOVE_ZERO = ["0", "-0", "-1"]


@pytest.mark.parametrize("value", _NOT_ABOVE_ZERO)
@pytest.mark.parametrize("side", ["stop_loss", "take_profit"])
async def test_a_registered_create_whose_side_is_no_price_above_zero_sends_nothing(
    side: str, value: str
) -> None:
    """Refused before anything is sent, whatever the exchange port checks (G-8b's guard is not
    relied on): B1 lands the order in `unknown`, never with a protection removed by implication."""
    rig = build_rig()
    order = new_order()
    figure = Decimal(value)  # the same id, with a side that is no price above zero
    rig.port.expect(
        new_order(stop_loss=figure) if side == "stop_loss" else new_order(take_profit=figure)
    )
    with capture_logs() as logs, pytest.raises(ValueError, match=side):
        await rig.port.place(command("place", order))
    assert rig.demo.calls == []
    refused = [log for log in logs if log["event"] == "oms_create_price_refused"]
    assert [(log["log_level"], log["side"]) for log in refused] == [("critical", side)]


@pytest.mark.parametrize(
    ("value", "looked_up"),
    [("0", True), ("-0", True), ("-1", True), ("NaN", False), ("Infinity", False)],
)
async def test_a_resumed_row_whose_stop_is_no_price_above_zero_is_never_resent(
    value: str, looked_up: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Postgres's `numeric` holds `NaN` and `Infinity`, which pass `stop_loss > 0`. A row read
    back with a stop at or below zero is still looked up (reading is never an order) and refused
    before the re-send; a non-finite one forms no request at all, so nothing is read or sent."""
    rig = build_rig()
    order = new_order()
    malformed = dataclasses.replace(await rig.stored(order), stop_loss=Decimal(value))

    async def stored(_account_id: Any, _link: str) -> Any:
        return malformed

    monkeypatch.setattr(rig.orders, "get_by_link_id", stored)
    rig.now.us = T0_US + 60 * SECOND_US
    with pytest.raises(ValueError, match="stop_loss"):
        await rig.port.place(command("place", order))
    assert rig.calls() == (_LOOKUP if looked_up else [])


@pytest.mark.parametrize("resumed", [False, True], ids=["registered", "resumed"])
async def test_an_order_that_is_not_reduce_only_and_has_no_stop_is_never_sent(
    resumed: bool,
) -> None:
    """SEC-2B1-04 (C-2.6): `FirstPersist.check` and B1's gate refuse it upstream, and the port
    refuses it too, before anything is sent (a resumed one after its lookup, as reading is never
    an order), logged CRITICAL, so B1 lands the order in `unknown`."""
    rig = build_rig()
    order = new_order()
    bare = dataclasses.replace(order, stop_loss=None)
    if resumed:
        await rig.stored(bare)
        rig.now.us = T0_US + 60 * SECOND_US
    else:
        rig.port.expect(bare)
    with capture_logs() as logs, pytest.raises(ValueError, match="native stop"):
        await rig.port.place(command("place", order))
    assert rig.calls() == (_LOOKUP if resumed else [])
    missing = [log["log_level"] for log in logs if log["event"] == "oms_create_stop_missing"]
    assert missing == ["critical"]


async def test_a_reduce_only_order_with_no_stop_of_its_own_is_sent() -> None:
    """C-2.6 binds an order that may open a position; a reduce-only order records no stop of its
    own (`FirstPersist.check`), so the port sends it without one, in the `critical` lane."""
    rig = build_rig()
    order = new_order(
        side="Sell", intent="flatten", reduce_only=True, stop_loss=None, take_profit=None
    )
    rig.port.expect(order)
    assert (await rig.port.place(command("place", order)))["ok"] is True
    (call,) = rig.demo.calls
    assert isinstance(call.request, PlaceOrderRequest)
    assert (call.request.stop_loss, call.lane) == (None, "critical")


@pytest.mark.parametrize("shown", ["0", "-1"])
async def test_an_attach_leaves_out_a_take_profit_the_reading_shows_as_no_price(shown: str) -> None:
    """The side the reading cannot vouch for is not sent, so the venue keeps its take-profit: a
    zero there would remove it by implication (a reading cannot hold a non-finite one)."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position(take_profit=Decimal(shown)))
    await rig.port.attach_stop(_attach(order))
    call = rig.demo.calls[1]
    assert call.request == TradingStopRequest(
        account=ref(), symbol=SYMBOL, stop_loss=STOP, take_profit=None
    )


async def test_forget_drops_an_unspent_registration_and_answers_its_watch_none() -> None:
    """S2-Q5: a `SEND` that did not commit sends nothing, so the pipeline drops the order's
    registration; a later `place` of it is a resumed create, never a first send."""
    rig = build_rig()
    order = new_order()
    watch = rig.port.expect(order)
    rig.port.forget(order.id)
    assert watch.answered and await watch.answer() is None
    rig.port.forget(order.id)  # nothing registered: nothing to drop
    assert rig.calls() == []


# --- the venue's outage (#4092, #2863): raised, never a refusal, never repeated ------------------


async def test_a_create_the_outage_answers_is_raised_after_one_send() -> None:
    """Never mapped to a refusal: raised, so B1 lands the order in `unknown` (its contract test),
    and never repeated, though the outage says `retryable`, as #4092 raises it (SEC-4092-02)."""
    rig = build_rig()
    order = new_order()
    rig.port.expect(order)
    raised = outage(10016)
    assert raised.retryable is True and raised.code is OmsErrorCode.SERVICE_UNAVAILABLE
    rig.demo.script("place_order", raised)
    with pytest.raises(ServiceUnavailableError):
        await rig.port.place(command("place", order))
    assert rig.calls() == ["place_order"]


async def test_an_attach_the_outage_answers_is_raised_after_one_call() -> None:
    """Whether the venue applied the stop is open: raised, so B1's stop goes `sl_missing`, and the
    row stays in flight for the complete read; nothing is sent again."""
    rig = build_rig()
    order = await _filled(rig)
    rig.demo.seed_position(position())
    rig.demo.script("set_trading_stop", outage())
    with pytest.raises(ServiceUnavailableError):
        await rig.port.attach_stop(_attach(order))
    assert rig.calls() == ["positions", "set_trading_stop"]
    (row,) = _rows(rig)
    assert (row.status, row.answered_at) == ("pending", None)


async def test_a_lookup_the_outage_fails_is_raised_after_one_read() -> None:
    rig = build_rig()
    order = new_order()
    await rig.stored(order)
    rig.demo.script("open_orders", outage())
    with pytest.raises(ServiceUnavailableError):
        await rig.port.lookup(command("lookup", order))
    assert rig.calls() == ["open_orders"]


@pytest.mark.parametrize("resumed", [False, True], ids=["after_a_duplicate", "resumed"])
async def test_a_creates_lookup_the_outage_fails_settles_nothing_and_sends_nothing(
    resumed: bool,
) -> None:
    """An empty lookup (`unknown`), never a refusal B1 would record, and no call repeated."""
    rig = build_rig()
    order = new_order()
    if resumed:
        await rig.stored(order)
        rig.demo.script("order_history", outage())
    else:
        rig.demo.seed_order(exchange_order(order), uid=UIDS["demo"])  # the create is a duplicate
        rig.demo.script("open_orders", outage())
        rig.port.expect(order)
    answer = await rig.port.place(command("place", order))
    assert answer == {"ok": False, "error_code": _DUP, "lookup": {}}
    assert rig.calls() == (_LOOKUP if resumed else ["place_order", "open_orders"])


# --- the request's correlation id ([AUDIT-REQUEST-ID], #3990; 21 Sec.3.10.1) --------------------

_REQUEST = UUID("6f1d2c3b-4a59-4e68-8f7a-9b0c1d2e3f40")
#: A correlation id bound where B1's call runs, which no record of the port may take.
_STALE = UUID("0a1b2c3d-4e5f-4a6b-8c7d-8e9fa0b1c2d3")


@pytest.mark.parametrize("call", ["place", "lookup"])
async def test_a_registered_orders_record_carries_its_requests_id_never_the_contexts(
    call: str,
) -> None:
    """B1's calls run in its own task, so the id rides on the registration (`expect`), and one
    bound where the call runs, stale or not, is never taken."""
    rig = build_rig()
    order = new_order()
    rig.demo.seed_order(exchange_order(order), uid=UIDS["demo"])
    rig.port.expect(order, request_id=_REQUEST)
    with bind_context(request_id=str(_STALE)):
        if call == "place":
            await rig.port.place(command("place", order))
        else:
            await rig.port.lookup(command("lookup", order))
    ((record, _),) = rig.audits.written
    assert isinstance(record, OrderAuditRecord) and record.request_id == _REQUEST


async def test_a_second_registration_carries_its_own_requests_id() -> None:
    rig = build_rig()
    order = new_order()
    rig.demo.seed_order(exchange_order(order), uid=UIDS["demo"])
    rig.port.expect(order, request_id=_STALE)
    rig.port.expect(order, request_id=_REQUEST)
    await rig.port.place(command("place", order))
    assert [record.request_id for record, _ in rig.audits.written] == [_REQUEST]


async def test_records_of_a_resume_and_an_attach_carry_no_request_id() -> None:
    """A restart's resume and a fill-driven attach are no request's, whatever their task's
    context: an adoption, an end unsent, a stop's request and its void all carry None."""
    rig = build_rig()
    adopted = new_order(seq=1)
    rig.demo.seed_order(exchange_order(adopted), uid=UIDS["demo"])
    filled = await _filled(rig)
    rig.demo.seed_position(position())
    rig.demo.script("set_trading_stop", FakeReject(OmsErrorCode.INSTRUMENT_FILTER, 110003))
    with bind_context(request_id=str(_STALE)):
        await _resumed(rig, adopted, age_us=SECOND_US)
        await _resumed(rig, new_order(LIVE_ACCOUNT, "live"), age_us=121 * SECOND_US)
        await rig.port.attach_stop(_attach(filled))
    assert [(record.action, record.request_id) for record, _ in rig.audits.written] == [
        ("orders.submit", None),
        (RESEND_REFUSED, None),
        ("sl.attached", None),
        ("sl.modified", None),
    ]


def test_every_action_the_port_writes_is_registered() -> None:
    """24 Sec.15.5's closed set: the writer refuses an action it does not list."""
    assert {"orders.submit", "sl.attached", "sl.modified", RESEND_REFUSED} <= AUDIT_ACTIONS


# --- the pipeline's watch, cancel and amend ------------------------------------------------------


async def test_watches_are_bounded_and_one_dropped_is_answered_none() -> None:
    """C-2.18: the oldest registration goes first, its waiter answered rather than left waiting."""
    rig = build_rig(max_watches=2)
    watches = [rig.port.expect(new_order(seq=n)) for n in range(3)]
    assert await watches[0].answer() is None
    assert not watches[1].answered and not watches[2].answered


async def test_a_second_registration_of_an_order_replaces_the_first() -> None:
    rig = build_rig()
    order = new_order()
    first, second = rig.port.expect(order), rig.port.expect(order)
    assert await first.answer() is None
    answer = await rig.port.place(command("place", order))
    assert await second.answer() == answer


async def test_a_cancelled_place_answers_its_watch_none_and_stays_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-2B1-02 (d): B1's attempt cancelled mid-send (its own bound, a step that cancels it)
    answers the registration None, so the pipeline's waiter never hangs, and the cancellation
    is re-raised, never swallowed."""
    rig = build_rig()
    order = new_order()
    sending = asyncio.Event()

    async def hangs(_request: PlaceOrderRequest) -> OrderAck:
        sending.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(rig.demo, "place_order", hangs)
    watch = rig.port.expect(order)
    task = asyncio.ensure_future(rig.port.place(command("place", order)))
    await sending.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled() and await watch.answer() is None


async def test_a_cancelled_waiter_never_cancels_the_answer() -> None:
    """CR-2B1-02 (d): `PlaceWatch.answer()` shields the answer, so a waiter's own cancellation
    leaves it pending for `place`, and a later waiter gets it."""
    rig = build_rig()
    order = new_order()
    watch = rig.port.expect(order)
    waiter = asyncio.ensure_future(watch.answer())
    await asyncio.sleep(0)  # one turn of the loop: the waiter is now awaiting the answer
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not watch.answered
    answer = await rig.port.place(command("place", order))
    assert answer["ok"] is True and await watch.answer() == answer


def test_the_port_holds_at_least_one_registration() -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_rig(max_watches=0)


def test_no_cancel_or_amend_service_is_injected() -> None:
    """The port's own cancel and amend (S4-B2: `test_commands_amend.py`) replace both services."""
    params = inspect.signature(OmsCommandPort).parameters
    assert {"cancels", "amends"}.isdisjoint(params)


# --- cancel and a KILL's cancel (24 Sec.8.8 rule 6; INV-B1-h, INV-B1-j; S4 rulings Q8, Q9, Q11) --

_STOP_ID = "x-sl-0005"
#: A recorded stop's two rows over a long's position (24 Sec.8.8 rule 6), each with its trigger.
_RECORDED = [("stop_loss", STOP), ("take_profit", new_order().take_profit)]
_KEPT = {"ok": False, "error_code": b01.NATIVE_STOP_REQUIRED}


async def _live(rig: Rig, order: NewOrder | None = None, **venue: Any) -> OrderRow:
    """`order` resting at the venue, stored `submitted` and bound to the venue's id for it."""
    order = order if order is not None else new_order()
    resting = exchange_order(order, **venue)
    rig.demo.seed_order(resting, uid=UIDS["demo"])
    bound = dataclasses.replace(order, exchange_order_id=resting.exchange_order_id)
    return await rig.stored(bound, lifecycle="submitted")


async def _recorded_stop(
    rig: Rig, intent: str = "stop_loss", trigger: Decimal | None = STOP
) -> OrderRow:
    """A recorded stop's row (24 Sec.8.3 rule 7): the stop-loss or take-profit order of a long's
    position, Sell, reduce-only and close-on-trigger, resting at the venue under the `ext-` key of
    its id, materialised `submitted` and bound."""
    stop = new_order(
        seq=5, order_link_id=ext_key(_STOP_ID), side="Sell", intent=intent,
        order_type="Market", price=None, trigger_price=trigger, stop_loss=None, take_profit=None,
        reduce_only=True, close_on_trigger=True, tpsl_mode="Partial", provenance="recorded_stop",
    )  # fmt: skip
    return await _live(rig, stop, exchange_order_id=_STOP_ID)


@pytest.mark.parametrize(("kind", "bound"), [("cancel", True), ("kill_cancel", False)])
async def test_a_cancel_names_the_stored_order_once_in_the_critical_lane(
    kind: b01.CommandKind, bound: bool
) -> None:
    """By its exchange order id once bound (an `ext-` key never goes on the wire, 24 Sec.14.2
    rule 11), else by its own id, as a KILL out of `unknown` sends it (Q8): the stored row's,
    the same id every time (C-2.10), drawn from the `critical` lane's reserve (C-12.7)."""
    rig = build_rig()
    order = new_order()
    if bound:
        row = await _live(rig, order)
    else:
        rig.demo.seed_order(exchange_order(order), uid=UIDS["demo"])
        row = await rig.stored(order, lifecycle="unknown")
    answer = await rig.port.cancel(command(kind, row))
    (call,) = rig.demo.calls
    assert (call.method, call.lane) == ("cancel_order", "critical")
    assert call.request == CancelOrderRequest(
        account=ref(), symbol=SYMBOL, order_link_id=row.order_link_id,
        exchange_order_id=row.exchange_order_id,
    )  # fmt: skip
    assert answer == {"ok": True, "exchange_order_id": exchange_order(order).exchange_order_id}
    assert rig.audits.written == [] and rig.switches.asked == []


@pytest.mark.parametrize(
    ("kind", "code", "ret_code", "reported", "halted", "logged"),
    [("kill_cancel", "INSTRUMENT_FILTER", 110017, [], False, ["INSTRUMENT_FILTER"]),
     ("cancel", "AUTH_ERROR", 10003, [(ACCOUNT, "AUTH_ERROR", 10003)], False, []),
     ("cancel", "CLOCK_DRIFT", 10002, [], True, [])],
)  # fmt: skip
async def test_a_refused_cancel_answers_its_codes_after_the_10003_and_10002_reactions(
    kind: b01.CommandKind, code: str, ret_code: int, reported: list[Any], halted: bool, logged: Any
) -> None:
    """INV-B1-j: B1 takes the order back live on the refusal, which carries its codes and never
    the exchange's text (SR-E29-09); 24 Sec.8.6 runs first, as for a create: `10003` goes to the
    credential report, `10002` trips the clock halt and one resync. A KILL's refused cancel is
    logged at ERROR: B18 and reconciliation settle the venue (INV-B1-h)."""
    rig = build_rig()
    row = await _live(rig)
    rig.demo.script("cancel_order", FakeReject(OmsErrorCode(code), ret_code, "do not show"))
    with capture_logs() as logs:
        answer = await rig.port.cancel(command(kind, row))
    assert answer == {"ok": False, "error_code": code, "exchange_ret_code": ret_code}
    assert rig.calls() == ["cancel_order"] and rig.credentials.calls == reported
    assert isinstance(rig.halt.refusal(), ClockDriftBlocked) is halted
    assert (rig.port.resync_task is not None) is halted
    await rig.port.aclose()  # the resync, where one began, ends with the port
    assert [e["error_code"] for e in logs if e["event"] == "oms_kill_cancel_refused"] == logged


_PARKED = {"ok": False, "unknown": "already_terminal", "exchange_ret_code": 110001}


@pytest.mark.parametrize(
    ("venue", "raised", "ret_code", "watched"),
    [(outage(), ServiceUnavailableError, 10019, None),
     (FakeReject(OmsErrorCode.ORDER_NOT_FOUND, 110001), NotFoundError, 110001, _PARKED)],
    ids=["outage", "already_terminal"],
)  # fmt: skip
async def test_a_cancel_the_venue_leaves_open_is_raised_after_one_call_its_watch_says_why_or_none(
    venue: Any, raised: type[ExchangeError], ret_code: int, watched: Any
) -> None:
    """Q11, S1: raised, so B1 lands the order in `unknown` and never sends it again, though the
    outage says `retryable`; so is the venue's 110001 (the S4-B1 ruling), as `NotFoundError` with
    its code: the venue does not hold the order, which says nothing of how it ended. Neither is a
    data refusal a step could mean. The exit service's watch answers None for a fault, never a
    refusal; for the 110001 it says why the order parks, with the code, so S4-C tells it apart."""
    rig = build_rig()
    row = await _live(rig)
    watch = rig.port.expect_exit(row.id, "cancel", request_id=_REQUEST)
    rig.demo.script("cancel_order", venue)
    with pytest.raises(raised) as error:
        await rig.port.cancel(command("cancel", row))
    assert error.value.exchange_ret_code == ret_code and not _data_refusal(error.value)
    assert rig.calls() == ["cancel_order"] and watch.answered and await watch.answer() == watched


async def test_a_cancel_refused_a_rate_token_answers_its_retry_with_nothing_sent() -> None:
    """24 Sec.8.7: the `critical` lane gave no token within its wait, so nothing left: B1 takes
    the order back live, and the exit service answers 429 with the retry."""
    rig = build_rig()
    row = await _live(rig)
    rig.demo.script("cancel_order", RateBudgetExceededError("no token", retry_after_s=2.2))
    answer = await rig.port.cancel(command("cancel", row))
    assert answer == {"ok": False, "error_code": "RATE_BUDGET_EXCEEDED", "retry_after_s": 3}


async def test_a_kills_cancel_goes_out_while_the_switches_refuse_and_the_clock_halt_stands() -> (
    None
):
    """24 Sec.8.10's carve-out (C-2.6, C-4.14): an exit is never gated, so the kill switch, live
    enablement, the order-entry gate and the clock halt never stop a KILL's own cancel, and the
    switches are never asked."""
    rig = build_rig()
    row = await _live(rig)
    rig.switches.refusals[ACCOUNT] = TradingDisabled()
    rig.halt.trip()
    answer = await rig.port.cancel(command("kill_cancel", row))
    assert answer["ok"] is True and rig.calls() == ["cancel_order"] and rig.switches.asked == []


_UNREAD = {"ok": False, "error_code": STORE_UNAVAILABLE, "retry_after_s": 1}


@pytest.mark.parametrize(
    ("kind", "bound", "hung", "outcome"),
    [("kill_cancel", {"kill_cancel_timeout_s": 0.05}, ("orders", "get_by_link_id"), _UNREAD),
     ("kill_cancel", {"kill_cancel_timeout_s": 0.05}, ("accounts", "trading_account"), _UNREAD),
     ("kill_cancel", {"kill_cancel_timeout_s": 0.05}, ("demo", "cancel_order"), TimeoutError),
     ("cancel", {"cancel_timeout_s": 0.05}, ("demo", "cancel_order"), TimeoutError)],
)  # fmt: skip
async def test_one_deadline_ends_all_of_a_cancel_by_its_kinds_own_bound(
    kind: b01.CommandKind, bound: Any, hung: Any, outcome: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All of a cancel, its reads and its call, ends by one deadline of its own kind's bound: a
    read cut off answers `STORE_UNAVAILABLE`, nothing sent; a call cut off is raised (B1's
    `kill_cancel_timeout`, or `unknown`). The other kind's bound, or none, would outlast 3 s."""
    rig = build_rig(port_timeout_s=60.0, **bound)
    row = await _live(rig)
    monkeypatch.setattr(getattr(rig, hung[0]), hung[1], _hangs)
    task = await _within(rig.port.cancel(command(kind, row)), 3.0)
    assert (type(error) if (error := task.exception()) else task.result()) == outcome


async def test_a_cancel_naming_another_order_is_a_defect_raised_never_an_unread_store() -> None:
    """The reads' carve-out: a command whose ids disagree with the stored row is a defect,
    raised (B1 lands it in `unknown`), never answered `STORE_UNAVAILABLE`; nothing is sent."""
    rig = build_rig()
    row = await _live(rig)
    with pytest.raises(ValueError, match="another order"):
        await rig.port.cancel(command("cancel", row, order_id=str(uuid5(NAMESPACE_URL, "x"))))
    assert rig.calls() == []


_UNAVAILABLE = {"ok": False, "error_code": ACCOUNT_UNAVAILABLE}  # no `retry_after_s`: none helps


@pytest.mark.parametrize("kind", ["cancel", "kill_cancel"])
@pytest.mark.parametrize(
    ("refusal", "answer"),
    [(AccountScopeDenied(), _UNAVAILABLE), (OrderEntryRefused(NO_ACTIVE_KEY), _UNAVAILABLE),
     (StoreUnavailable(), _UNREAD)],
    ids=["scope_denied", "no_key", "outage"],
)  # fmt: skip
async def test_a_cancel_the_account_refuses_is_account_unavailable_never_an_outage(
    kind: b01.CommandKind, refusal: Exception, answer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The S4-B1 ruling (B): an account out of scope or with no active key, as the wiring's binding
    refuses it (and pages CRITICAL), is no outage: `ACCOUNT_UNAVAILABLE`, no retry advised, nothing
    sent. A read that is down (`StoreUnavailable`, its sibling) stays `STORE_UNAVAILABLE`."""
    rig = build_rig()
    row = await _live(rig)
    monkeypatch.setattr(rig.accounts, "trading_account", AsyncMock(side_effect=refusal))
    assert await rig.port.cancel(command(kind, row)) == answer and rig.calls() == []


@pytest.mark.parametrize(
    ("error", "unexpected"),
    [(TypeError("defect"), True), (StorageQueryFailed("22P02"), True),
     (StoreUnavailable(), False), (TimeoutError(), False), (StorageQueryFailed("57014"), False)],
    ids=["defect", "data_refusal", "store_unavailable", "timeout", "outage"],
)  # fmt: skip
async def test_a_failed_read_is_still_unavailable_but_one_no_outage_raises_is_logged_at_error(
    error: Exception, unexpected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 10:29Z ruling stands literally, whatever the read raised (`ValueError` aside): nothing
    sent, `STORE_UNAVAILABLE` with its retry. A class outside what an outage raises (a timeout,
    `StoreUnavailable`, a storage failure that is no data refusal) is a defect that reads as an
    outage, so it is logged at ERROR, by class (the S4-B1 re-check, Finding 4)."""
    rig = build_rig()
    row = await _live(rig)
    monkeypatch.setattr(rig.accounts, "trading_account", AsyncMock(side_effect=error))
    with capture_logs() as logs:
        assert await rig.port.cancel(command("cancel", row)) == _UNREAD and rig.calls() == []
    flagged = [
        (e["log_level"], e["failure"]) for e in logs if e["event"] == "oms_cancel_unread_unexpected"
    ]
    assert flagged == ([("error", type(error).__name__)] if unexpected else [])


async def test_the_unread_retry_is_the_one_constant_the_amend_shares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The S4-B1 ruling: `STORE_UNAVAILABLE` advises one wait, 1 s, for the cancel and the amend
    alike (S4-B2 imports it). The answer reads it, so a figure moved there moves it here."""
    assert STORE_UNAVAILABLE_RETRY_AFTER_S == 1.0
    monkeypatch.setattr("candleviewer.oms.commands.STORE_UNAVAILABLE_RETRY_AFTER_S", 7.0)
    rig = build_rig()
    row = await _live(rig)
    monkeypatch.setattr(rig.accounts, "trading_account", AsyncMock(side_effect=StoreUnavailable()))
    assert await rig.port.cancel(command("cancel", row)) == _UNREAD | {"retry_after_s": 7}


def test_the_cancel_bounds_sit_inside_b1s_own_and_a_users_outlasts_the_critical_lane() -> None:
    """A KILL's cancel ends inside B1's `CV_KILL_CANCEL_TIMEOUT`; a user's inside its
    `CV_COMMAND_TIMEOUT` and past the adapter's `critical` lane wait, so, while the store reads
    answer promptly, a token that does not come is a refusal (429, the order live), not `unknown`
    (Q8). Each is only ever tightened."""
    params = inspect.signature(OmsCommandPort).parameters
    kill, user = (params[name].default for name in ("kill_cancel_timeout_s", "cancel_timeout_s"))
    assert 0 < kill < CV_KILL_CANCEL_TIMEOUT and CRITICAL_WAIT_S < user < CV_COMMAND_TIMEOUT
    assert RECORDED_STOP_READ_S + CRITICAL_WAIT_S < user  # the call keeps the lane's wait (Q9)
    outside = (float("inf"), float("nan"), 0.0, -1.0)
    for wider in (kill + 0.001, *outside):
        with pytest.raises(ValueError, match="tightened"):
            build_rig(kill_cancel_timeout_s=wider)
    for wider in (user + 0.001, *outside):
        with pytest.raises(ValueError, match="tightened"):
            build_rig(cancel_timeout_s=wider)


async def test_a_recorded_stops_position_read_ends_by_its_own_bound_and_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q9 inside the cancel's bound: a read that does not answer ends by `RECORDED_STOP_READ_S`,
    not the whole cancel's, so the call would keep the `critical` lane's wait; it refuses, as an
    unread position does, nothing sent (C-2.6)."""
    monkeypatch.setattr("candleviewer.oms.commands.RECORDED_STOP_READ_S", 0.05)
    rig = build_rig(port_timeout_s=60.0)
    row = await _recorded_stop(rig)
    monkeypatch.setattr(rig.demo, "positions", _hangs)
    task = await _within(rig.port.cancel(command("cancel", row)), 3.0)
    assert task.result() == _KEPT and rig.calls() == []


# --- the native stop (C-2.6): a recorded stop's row is never a KILL's, nor an open position's ----


@pytest.mark.parametrize(("intent", "trigger"), _RECORDED)
async def test_native_sl_a_kill_never_cancels_a_recorded_stops_row_nothing_read_or_sent(
    intent: str, trigger: Decimal | None
) -> None:
    """INV-B1-p, C-2.6: B1's guarded arm consumes a KILL of the row, its stop-loss or its
    take-profit; should one reach the port all the same, it is refused at once, CRITICAL, nothing
    asked of the venue, even over a flat position, where a user's cancel of it would go out."""
    rig = build_rig()
    row = await _recorded_stop(rig, intent, trigger)
    rig.demo.seed_position(position(side=None, qty="0"))
    with capture_logs() as logs:
        answer = await rig.port.cancel(command("kill_cancel", row))
    assert answer == _KEPT and rig.calls() == []
    spared = [log["log_level"] for log in logs if log["event"] == "oms_kill_spared_recorded_stop"]
    assert spared == ["critical"]


@pytest.mark.parametrize(("intent", "trigger"), _RECORDED)
async def test_native_sl_a_kill_that_cannot_read_the_row_sends_nothing(
    intent: str, trigger: Decimal | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed (C-2.6, the 10:29Z condition): a KILL whose row read fails cannot tell a
    recorded stop from a plain order, so nothing is sent: `STORE_UNAVAILABLE`, the stop kept."""
    rig = build_rig(port_timeout_s=60.0, kill_cancel_timeout_s=0.05)
    row = await _recorded_stop(rig, intent, trigger)
    monkeypatch.setattr(rig.orders, "get_by_link_id", _hangs)
    task = await _within(rig.port.cancel(command("kill_cancel", row)), 3.0)
    assert task.result() == _UNREAD and rig.calls() == []


_READ, _SENT = [("positions", "poll")], [("positions", "poll"), ("cancel_order", "critical")]
_LET = {"ok": True, "exchange_order_id": _STOP_ID}


@pytest.mark.parametrize(("intent", "trigger"), _RECORDED)
@pytest.mark.parametrize(
    ("seed", "answer", "calls", "released"),
    [(lambda rig: rig.demo.seed_position(position(qty="0.010")), _KEPT, _READ, []),
     (lambda rig: rig.demo.seed_position(position(qty="-0.010")), _KEPT, _READ, []),
     (lambda rig: rig.demo.script("positions", TransportError("cut off")), _KEPT, _READ, []),
     (lambda rig: rig.demo.seed_position(position(side=None, qty="0")), _LET, _SENT, []),
     (lambda rig: None, _LET, _SENT, ["none"])],
    ids=["open", "negative", "unread", "flat", "none"],
)  # fmt: skip
async def test_native_sl_the_cancel_port_refuses_a_recorded_stops_row_unless_it_reads_flat(
    seed: Any, answer: Any, calls: Any, released: list[str], intent: str, trigger: Decimal | None
) -> None:
    """Q9, fail closed: a user's cancel of either row goes out only once a `poll`-lane read shows
    its position flat (or none, which is logged apart); a position of any size, or a read that
    fails, keeps the stop, nothing sent (24 Sec.8.8 rule 6). The call names the row by its
    exchange id, which alone goes on the wire, never its `ext-` key (24 Sec.14.2 rule 11)."""
    rig = build_rig()
    row = await _recorded_stop(rig, intent, trigger)
    seed(rig)
    with capture_logs() as logs:
        assert await rig.port.cancel(command("cancel", row)) == answer
    assert [(call.method, call.lane) for call in rig.demo.calls] == calls
    assert {getattr(c.request, "exchange_order_id", _STOP_ID) for c in rig.demo.calls} <= {_STOP_ID}
    assert [e["position"] for e in logs if e["event"] == "oms_recorded_stop_released"] == released


# --- the exit services' watch (`expect_exit`), as the pipeline's (`expect`) -----------------------


async def test_an_exit_watch_answers_b1s_cancel_and_a_kills_cancel_spends_none() -> None:
    rig = build_rig()
    row = await _live(rig)
    watch = rig.port.expect_exit(row.id, "cancel", request_id=_REQUEST)
    assert (watch.order_id, watch.kind, watch.request_id, watch.actor) == (
        row.id, "cancel", _REQUEST, None,
    )  # fmt: skip
    rig.demo.script("cancel_order", FakeReject(OmsErrorCode.INSTRUMENT_FILTER))
    await rig.port.cancel(command("kill_cancel", row))  # refused: a KILL's spends no watch
    assert not watch.answered
    answer = await rig.port.cancel(command("cancel", row))
    assert answer["ok"] is True and watch.answered and await watch.answer() == answer


async def test_exit_watches_are_bounded_replaced_and_forgotten_each_answered_none() -> None:
    """C-2.18 and S2-Q5, as the pipeline's: a second registration replaces the first, the oldest
    goes past the bound, and an exit whose command was refused is forgotten, each answered None."""
    rig = build_rig(max_watches=2)
    first = rig.port.expect_exit(UUID(int=1), "cancel")
    second = rig.port.expect_exit(UUID(int=1), "cancel")
    third, fourth = (rig.port.expect_exit(UUID(int=n), "cancel") for n in (2, 3))
    assert [w.answered for w in (first, second, third, fourth)] == [True, True, False, False]
    assert await first.answer() is None and await second.answer() is None
    rig.port.forget_exit(UUID(int=3), "cancel")
    rig.port.forget_exit(UUID(int=3), "cancel")  # nothing registered: nothing to drop
    assert fourth.answered and await fourth.answer() is None and not third.answered


@pytest.mark.parametrize(("kind", "spent"), [("cancel", True), ("kill_cancel", False)])
async def test_a_cancelled_cancel_answers_its_watch_none_and_stays_cancelled(
    kind: b01.CommandKind, spent: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As a cancelled `place` (CR-2B1-02 (d)): B1's cancel cut off mid-send answers the exit's
    watch None, never leaving it pending, and re-raises the cancellation; a KILL's spends none."""
    rig = build_rig()
    row = await _live(rig)
    monkeypatch.setattr(rig.demo, "cancel_order", _hangs)
    watch = rig.port.expect_exit(row.id, "cancel")
    task = asyncio.ensure_future(rig.port.cancel(command(kind, row)))
    for _ in range(64):  # into the venue's call, which never answers
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert watch.answered is spent and (not spent or await watch.answer() is None)


async def test_a_cancelled_exit_waiter_never_cancels_the_answer() -> None:
    """As `PlaceWatch`'s: `ExitWatch.answer()` shields the answer, so a waiter's own cancellation
    leaves it pending for B1's cancel, and a later waiter gets it."""
    rig = build_rig()
    row = await _live(rig)
    watch = rig.port.expect_exit(row.id, "cancel")
    waiter = asyncio.ensure_future(watch.answer())
    await asyncio.sleep(0)  # one turn of the loop: the waiter is now awaiting the answer
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not watch.answered
    answer = await rig.port.cancel(command("cancel", row))
    assert answer["ok"] is True and watch.answered and await watch.answer() == answer


def test_the_stop_request_bound_exceeds_an_entrys_answer_path() -> None:
    """[LANE-25], Q4: an entry's stop request is answered within its first persist (which stamps
    the row's `created_at`), its `submitting` step's write, all of `place` (one deadline for its
    reads, calls and answer, CR-2B1-04, which `test_one_deadline_ends_all_of_a_registered_place`
    pins), and the result step's write, each read from the constant that bounds it, so a change
    to any of them that the bound no longer covers fails here."""
    defaults = inspect.signature(OmsCommandPort).parameters
    assert defaults["submit_timeout_s"].default == SUBMIT_TIMEOUT_S
    first, send, result = CV_PERSIST_TIMEOUT, CV_PERSIST_TIMEOUT, CV_PERSIST_TIMEOUT
    assert STOP_REQUEST_BOUND_S > first + send + SUBMIT_TIMEOUT_S + result
    bound = inspect.signature(ResolvingStopGate).parameters["bound_s"]
    assert bound.default is inspect.Parameter.empty  # given: `OmsBounds.stop_request_s`


def test_the_attachs_wait_for_its_read_fits_its_bound_and_b1s_attempt() -> None:
    """24 Sec.8.4 (Q2): the gate's two reads around the 2 s wait fit `PORT_TIMEOUT_S`, which bounds
    the call; with the `trading-stop` call's deadline, B1's attempt (`CV_COMMAND_TIMEOUT`)."""
    gate = 2 * STOP_GATE_READ_TIMEOUT_S + ATTACH_GATE_WAIT_S
    assert ATTACH_GATE_WAIT_S == 2.0 and gate < PORT_TIMEOUT_S
    assert gate + SUBMIT_TIMEOUT_S < CV_COMMAND_TIMEOUT
