"""E29-T04 (#913) slice 3C, the adapters: `oms_wiring.OmsAudit` (the OMS's `SubmitAudit` and
`OrderAudit`), `OrderNoticesRouter`, the machine-state member `OrderStateFeed`, and
`order_machine.CompositePublisher`, which holds the members."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.admin import wiring as admin_wiring
from candleviewer.audit.writer import AuditUnavailable, AuditWriter, keyed_record_id
from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.oms.commands import NEVER_SENT_ALERT
from candleviewer.oms.order_machine import (
    CompositePublisher,
    MachinePublisher,
    OrderAudit,
    OrderAuditRecord,
    OrderNotice,
    OrderNotices,
)
from candleviewer.oms.ports import KeyedRecord, RequestRecord, SubmitActor, SubmitAudit
from candleviewer.oms_wiring import (
    ORDER_ALERTS,
    AuditWriterPort,
    OmsAudit,
    OrderNoticesRouter,
    OrderStateFeed,
)
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.plugins.state_feed import FeedBinding
from candleviewer.statechart.registry import DEFAULT_MACHINES_DIR

ACCOUNT, ORDER, STOP, USER, SESSION, REQUEST = (uuid.UUID(int=n) for n in range(1, 7))
ACTOR = SubmitActor(user_id=USER, role="manager", session_id=SESSION, ip="100.64.0.7")
DETAIL = {"order_id": str(ORDER), "state": "submitting"}
BY_USER = {
    "actor_label": "user:manager", "actor_user_id": USER, "actor_ip": "100.64.0.7",
    "session_id": SESSION, "request_id": REQUEST,
}  # fmt: skip
BY_SYSTEM = {"actor_label": "system:oms", "actor_user_id": None, "request_id": None}
STOP_OBJECT = {"object_kind": "recorded_stop", "object_id": str(STOP)}
ORDER_OBJECT = {"object_kind": "order", "object_id": str(ORDER)}


class _Writer:
    """Records each append once the real writer's `build` has checked its columns and values."""

    def __init__(self, tmp_path: Path, error: Exception | None = None) -> None:
        self.real = AuditWriter(cast(Any, object()), str(tmp_path / "audit.wal"))
        self.error, self.calls = error, list[tuple[str, tuple[str, ...], dict[str, Any]]]()

    async def emit(self, action: str, **fields: Any) -> None:
        self._append("emit", (action,), fields)

    async def emit_keyed(self, action: str, name: str, **fields: Any) -> None:
        self._append("emit_keyed", (action, name), fields)

    def _append(self, call: str, args: tuple[str, ...], fields: dict[str, Any]) -> None:
        self.real.build(args[0], **fields)
        if self.error is not None:
            raise self.error
        self.calls.append((call, args, fields))


def _keyed(actor: SubmitActor | None) -> KeyedRecord:
    by_user = actor is not None
    return KeyedRecord(
        "sl.attached", str(STOP), ACCOUNT, "recorded_stop", STOP, "success", "info",
        "entry_attach", USER if by_user else None, DETAIL, REQUEST if by_user else None, actor,
    )  # fmt: skip


REQUEST_RECORD = RequestRecord(
    "orders.submit", ACCOUNT, "order", ORDER, "denied", "warning", "risk_limit_breached", ACTOR,
    DETAIL, REQUEST,
)  # fmt: skip
ORDER_RECORD = OrderAuditRecord("orders.cancel", ORDER, ACCOUNT, "success", "warning", "k", DETAIL)


@pytest.mark.parametrize(
    ("record", "call", "columns"),
    [
        (_keyed(ACTOR), ("emit_keyed", ("sl.attached", str(STOP))), BY_USER | STOP_OBJECT),
        (_keyed(None), ("emit_keyed", ("sl.attached", str(STOP))), BY_SYSTEM | STOP_OBJECT),
        (REQUEST_RECORD, ("emit", ("orders.submit",)), BY_USER | ORDER_OBJECT),
        (ORDER_RECORD, ("emit", ("orders.cancel",)), BY_SYSTEM | ORDER_OBJECT),
    ],
    ids=["keyed-by-a-user", "keyed-by-the-system", "request", "order-machine"],
)
async def test_each_record_goes_to_its_append_naming_its_actor_object_and_account(
    tmp_path: Path, record: Any, call: tuple[str, tuple[str, ...]], columns: dict[str, Any]
) -> None:
    writer = _Writer(tmp_path)
    await OmsAudit(writer, environment="demo").write(record)
    after = DETAIL | {"account_id": str(ACCOUNT)}
    common = {"outcome": record.outcome, "severity": record.severity, "reason": record.reason}
    assert writer.calls == [(*call, common | columns | {"after_state": after, "env": "demo"})]


async def test_the_keyed_id_is_the_writers_and_a_refused_record_is_raised(tmp_path: Path) -> None:
    audit = OmsAudit(_Writer(tmp_path, AuditUnavailable("full")), environment="demo")
    assert admin_wiring.keyed_record_id is keyed_record_id  # the root reaches it through admin
    assert audit.record_id("sl.attached", str(STOP)) == keyed_record_id("sl.attached", str(STOP))
    with pytest.raises(AuditUnavailable):  # C-2.9: the caller refuses what it cannot record
        await audit.write(_keyed(None))


async def test_a_record_that_names_a_user_but_no_actor_is_refused_and_not_written(
    tmp_path: Path,
) -> None:
    """The actor is the only source of a role, so a user with none would be labelled without one
    (C-2.9): the write raises before any append, and a site that drops the actor fails here, not
    in the audit trail (SEC-S3C2-02)."""
    writer = _Writer(tmp_path)
    roleless = replace(_keyed(None), actor_user_id=USER)
    with pytest.raises(ValueError, match="no role"):
        await OmsAudit(writer, environment="demo").write(roleless)
    assert writer.calls == []


class _Pager:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.alerts = error, list[tuple[str, str, str]]()

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.alerts.append((severity, summary, machine_kind))
        if self.error is not None:
            raise self.error


def _notice(kind: str, **detail: Any) -> OrderNotice:
    return OrderNotice(kind, ORDER, ACCOUNT, "cvd-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en", detail)


#: What a notice's detail could carry and no log line may (C-12.6).
_VALUES = {"price": "63099.8", "qty": "0.5", "api_key": "DUMMYKEY_" + "Q3w9" * 5}


@pytest.mark.parametrize(
    ("notice", "level", "alert"),
    [
        (
            _notice("alert", alert="SL_ATTACH_FAILED"),
            "error",
            ("page", "order alert SL_ATTACH_FAILED"),
        ),
        (
            _notice("alert", alert="order_never_sent"),
            "error",
            ("alert", "order alert order_never_sent"),
        ),
        (
            _notice("request_reconciliation"),
            "error",
            ("page", "order notice request_reconciliation has no owner until E29-T06"),
        ),
        (
            _notice("request_fallback_sl"),
            "error",
            ("page", "order notice request_fallback_sl has no owner until E32"),
        ),
        (_notice("amend_rejected", error_code="RATE_LIMITED"), "warning", None),
        (_notice("surprise"), "error", ("page", "order notice of an unknown kind")),
    ],
    ids=["alert", "never-sent", "reconciliation", "fallback-sl", "amend-rejected", "unknown"],
)
async def test_each_notice_goes_where_its_kind_says_and_logs_ids_and_names_only(
    notice: OrderNotice, level: str, alert: tuple[str, str] | None
) -> None:
    pager = _Pager()
    with capture_logs() as logs:
        await OrderNoticesRouter(pager).notify(replace(notice, detail={**notice.detail, **_VALUES}))
    assert [(entry["log_level"], entry["order_id"]) for entry in logs] == [(level, str(ORDER))]
    assert pager.alerts == ([] if alert is None else [(*alert, "order")])
    assert not any(value in str(logs) for value in _VALUES.values())


async def test_each_name_of_the_closed_sets_is_logged_and_paged_as_it_is() -> None:
    """The pin renames nothing and drops no name that B1, the resume or the taxonomy raises."""
    pager = _Pager()
    router = OrderNoticesRouter(pager)
    with capture_logs() as logs:
        for alert in sorted(ORDER_ALERTS):
            await router.notify(_notice("alert", alert=alert))
        for code in OmsErrorCode:
            await router.notify(_notice("amend_rejected", error_code=code.value))
    alerts = [entry["alert"] for entry in logs if entry["event"] == "oms_order_alert"]
    codes = [entry["error_code"] for entry in logs if entry["event"] == "oms_amend_rejected"]
    assert (alerts, codes) == (sorted(ORDER_ALERTS), [code.value for code in OmsErrorCode])
    assert [summary for _, summary, _ in pager.alerts] == [f"order alert {a}" for a in alerts]


@pytest.mark.parametrize(
    ("kind", "field", "page"),
    [
        pytest.param("alert", "alert", "order alert unnamed", id="alert"),
        pytest.param("amend_rejected", "error_code", None, id="error_code"),
    ],
)
async def test_a_value_outside_a_closed_name_set_is_unnamed_in_the_log_and_the_page(
    kind: str, field: str, page: str | None
) -> None:
    """A key-shaped value is a plain name by its shape (`_NAME`), so each source is held to the
    names it can raise: no alert or code from anywhere else reaches a log line or the pager's text,
    a key among them (SEC-S3C2-01, C-12.6)."""
    key, pager = _VALUES["api_key"], _Pager()
    with capture_logs() as logs:
        await OrderNoticesRouter(pager).notify(_notice(kind, **{field: key}))
    assert [entry[field] for entry in logs] == ["unnamed"]
    assert pager.alerts == ([] if page is None else [("page", page, "order")])
    assert key not in str(logs) and key not in str(pager.alerts)


_RAISERS = ("raise_unknown_alert", "raise_critical_alert", "raise_naked_position_alert")


def _alerting_states(node: dict[str, Any], path: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Each (state path, action) of B1's chart whose entry runs an alert-raising action."""
    found: list[tuple[str, str]] = []
    for name, state in node.get("states", {}).items():
        entry = state.get("entry", [])
        for action in [entry] if isinstance(entry, str) else entry:
            if action in _RAISERS:
                found.append((".".join((*path, name)), action))
        found += _alerting_states(state, (*path, name))
    return found


def _b1_alerting_states() -> list[tuple[str, str]]:
    text = (DEFAULT_MACHINES_DIR / "B01.order.machine.json").read_text()
    found = _alerting_states(json.loads(text))
    # An alert raised from a transition would be no state's: every mention is an entry's.
    assert len(found) == sum(text.count(f'"{action}"') for action in _RAISERS)
    return found


class _At:
    """An interpreter at one state, as the contract tests of B1 stand one up."""

    def __init__(self, state: str) -> None:
        self.current_state_ids = {f"order.{state}"}


async def test_the_closed_alert_set_is_what_the_order_machine_and_the_resume_raise() -> None:
    """Run each alerting state's entry action of the chart: the names B1 posts, and the one
    `oms.commands` raises, are `ORDER_ALERTS`, no more and no fewer (an alert named outside it
    would page as `unnamed`, and one nothing raises is stale)."""
    raised = set[str]()
    for state, action in _b1_alerting_states():
        context: dict[str, Any] = {}
        await b01.ACTIONS[action](_At(state), context, None, None)
        raised |= {entry["alert"] for entry in context["outbox"] if entry["kind"] == "alert"}
    assert raised | {NEVER_SENT_ALERT} == ORDER_ALERTS


async def test_the_router_never_raises_with_a_failing_pager_or_a_broken_notice() -> None:
    broken = OrderNotice("alert", ORDER, ACCOUNT, None, cast(Any, None))  # no detail to read
    with capture_logs() as logs:
        await OrderNoticesRouter(_Pager(RuntimeError("down"))).notify(_notice("alert"))
        await OrderNoticesRouter(_Pager()).notify(broken)
    critical = [entry["event"] for entry in logs if entry["log_level"] == "critical"]
    assert critical == ["oms_pager_failed", "oms_notice_unrouted"]
    failed = next(entry for entry in logs if entry["event"] == "oms_pager_failed")
    assert (failed["failure"], "error" in failed) == ("RuntimeError", False)  # B2's field name


@pytest.mark.parametrize("error", [None, RuntimeError("down")], ids=["pager-up", "pager-down"])
async def test_a_malformed_sl_attach_failed_notice_is_logged_then_paged_and_never_raised(
    error: Exception | None,
) -> None:
    pager = _Pager(error)
    malformed = OrderNotice("alert", ORDER, ACCOUNT, None, cast(Any, ["SL_ATTACH_FAILED"]))
    with capture_logs() as logs:
        await OrderNoticesRouter(pager).notify(malformed)  # the detail is no mapping
    critical = [entry["event"] for entry in logs if entry["log_level"] == "critical"]
    assert critical == ["oms_notice_unrouted"] + ([] if error is None else ["oms_pager_failed"])
    assert pager.alerts == [("page", "order notice alert not routed: AttributeError", "order")]


class _Feed:
    """A `MachineStatePort` recording each binding and each handle's payloads."""

    environment = "demo"

    def __init__(self) -> None:
        self.bound, self.published = list[FeedBinding](), list[tuple[int, Any, bool]]()

    def now_ms(self) -> int:
        return 0

    def bind(self, binding: FeedBinding) -> Any:
        self.bound.append(binding)
        return _Handle(self, len(self.bound))


class _Handle:
    def __init__(self, feed: _Feed, number: int) -> None:
        self.feed, self.number = feed, number

    def publish(self, payload: Any, *, last: bool) -> None:
        self.feed.published.append((self.number, payload["state"], last))

    def remove(self) -> None:
        raise AssertionError("the feed never removes a slot")


def test_the_feed_binds_an_order_once_scoped_to_its_account_and_drops_it_on_its_last_step() -> None:
    feed = _Feed()
    states = OrderStateFeed(feed)
    for state, last in (("submitting", False), ("submitted", False), ("filled", True)):
        states.publish(ORDER, ACCOUNT, {"state": state}, last=last)
    states.publish(ORDER, ACCOUNT, {"state": "filled"}, last=True)  # the handle went: a new one
    assert feed.bound == [FeedBinding("order", str(ORDER), frozenset({ACCOUNT}))] * 2
    assert feed.published == [
        (1, "submitting", False), (1, "submitted", False), (1, "filled", True), (2, "filled", True)
    ]  # fmt: skip


def test_the_feed_holds_at_most_max_orders_slots_dropping_the_least_recent() -> None:
    feed = _Feed()
    states = OrderStateFeed(feed, max_orders=2)
    a, b, c = (uuid.UUID(int=n) for n in (11, 12, 13))
    for order in (a, b, a, c, b):  # c drops b, published before a's second step; b binds again
        states.publish(order, ACCOUNT, {"state": "submitted"}, last=False)
    assert [binding.entity_id for binding in feed.bound] == [str(a), str(b), str(c), str(b)]


def test_a_feed_refuses_fewer_than_one_slot_and_serves_with_one() -> None:
    for max_orders in (0, -1):
        with pytest.raises(ValueError, match="max_orders"):
            OrderStateFeed(_Feed(), max_orders=max_orders)
    feed = _Feed()
    OrderStateFeed(feed, max_orders=1).publish(ORDER, ACCOUNT, {"state": "held"}, last=False)
    assert feed.published == [(1, "held", False)]


class _Member:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.got = error, list[tuple[Any, ...]]()

    def publish(
        self, order_id: uuid.UUID, account_id: uuid.UUID, payload: Any, *, last: bool
    ) -> None:
        self.got.append((order_id, account_id, payload, last))
        if self.error is not None:
            raise self.error


def test_a_member_that_raises_is_logged_and_stops_neither_the_others_nor_the_step() -> None:
    first, broken, after = _Member(), _Member(RuntimeError("x")), _Member()
    with capture_logs() as logs:
        CompositePublisher(first, broken, after).publish(ORDER, ACCOUNT, {"s": 1}, last=True)
    assert first.got == broken.got == after.got == [(ORDER, ACCOUNT, {"s": 1}, True)]
    failed = [(entry["event"], entry["member"], entry["error"]) for entry in logs]
    assert failed == [("oms_publish_member_failed", "_Member", "RuntimeError")]


def test_each_adapter_fills_its_oms_port_and_the_writer_fills_its_own(tmp_path: Path) -> None:
    """`mypy --strict` checks these assignments; the members publish through the composite."""
    writer: AuditWriterPort = _Writer(tmp_path).real  # the real writer, which E29-T04 wires
    audit = OmsAudit(writer, environment="demo")
    ports: tuple[SubmitAudit, OrderAudit, OrderNotices] = (
        audit,
        audit,
        OrderNoticesRouter(_Pager()),
    )
    feed = _Feed()
    publisher: MachinePublisher = CompositePublisher(OrderStateFeed(feed), _Member())
    publisher.publish(ORDER, ACCOUNT, {"state": "held"}, last=False)
    assert len(ports) == 3 and feed.published == [(1, "held", False)]
