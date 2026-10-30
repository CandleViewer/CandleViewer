"""B19 `reconciliation`'s binding module (E29-T06 #914 PR 2a; 28 §B19.4 to §B19.6): its guards are
pure and total over context and event (A6), its event payloads closed, every action total (A1),
unwired or over a port that raises, and the re-drive plan names what a restored machine needs
(INV-B19-e). The bindings over the pass, on the library: `test_reconcile_job.py` and
`tests/xstate_contract/test_b19_reconciliation.py`."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import jsonschema
import pytest
from structlog.testing import capture_logs

from candleviewer.statechart.bindings import b19_reconciliation as b19
from candleviewer.statechart.bindings import load_binding_maps
from candleviewer.statechart.registry import Registry

SWEEP = "00000000-0000-4000-8000-0000000000a1"
ACCOUNT = "00000000-0000-0000-0000-0000000000a1"


@dataclass
class _Event:
    type: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class _Done:
    type: str
    data: Any


@dataclass
class _Error:
    type: str
    error: BaseException


class _Raising:
    """A port whose every effect raises: the actions stay total."""

    def __getattr__(self, name: str) -> Any:
        def boom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError(name)

        async def aboom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError(name)

        return aboom if name in ("fetch", "diff", "remediate", "report") else boom


@pytest.fixture
def unwired() -> Iterator[None]:
    b19.set_ports(None)
    yield
    b19.set_ports(None)


def test_the_maps_cover_every_name_the_chart_uses_and_load_as_coroutines() -> None:
    maps = load_binding_maps("reconciliation")
    chart = Registry().get("reconciliation")
    text = repr(chart)
    assert all(name in text for name in (*maps.actions, *maps.guards, *maps.services))
    assert set(maps.guards) == {
        "divergences_found_and_auto_remediate",
        "failures_exhausted",
        "unresolved_divergences",
    }


@pytest.mark.parametrize(
    ("event", "auto", "expected"),
    [
        (_Done("done.invoke.diff", {"divergences": 2}), True, True),
        (_Done("done.invoke.diff", {"divergences": 2}), False, False),
        (_Done("done.invoke.diff", {"divergences": 0}), True, False),
        (_Done("done.invoke.diff", {"divergences": True}), True, False),
        (_Done("done.invoke.diff", None), True, False),
        (_Error("error.platform.diff", RuntimeError()), True, False),
    ],
)
def test_the_remediation_guard_needs_planned_actions_and_the_capability(
    event: Any, auto: bool, expected: bool
) -> None:
    assert b19.divergences_found_and_auto_remediate({"auto_remediate": auto}, event) is expected


def test_the_stale_guard_reads_only_a_fetch_failure_and_its_window() -> None:
    spent = b19.FetchFailed("X", failing_since_us=0, failed_at_us=120, window_us=120)
    inside = b19.FetchFailed("X", failing_since_us=0, failed_at_us=119, window_us=120)
    assert b19.failures_exhausted({}, _Error("error.platform.fetch", spent))
    assert not b19.failures_exhausted({}, _Error("error.platform.fetch", inside))
    assert not b19.failures_exhausted({}, _Error("error.platform.fetch", RuntimeError()))
    assert not b19.failures_exhausted({}, _Event("RETRY_DUE"))


@pytest.mark.parametrize(
    ("value", "expected"), [(1, True), (0, False), (True, False), ("1", False)]
)
def test_the_divergent_guard_reads_the_reports_owner_items(value: object, expected: bool) -> None:
    assert b19.unresolved_divergences({"unresolved": value}, _Event("x")) is expected


@pytest.mark.parametrize(
    ("event", "payload", "valid"),
    [
        ("SWEEP_DUE", {}, True),
        ("SWEEP_DUE", {"trigger": "manual", "pass_id": SWEEP}, True),
        ("SWEEP_DUE", {"trigger": "hourly"}, False),
        ("SWEEP_DUE", {"pass_id": "p1"}, False),
        ("STARTUP", {"pass_id": SWEEP, "extra": 1}, False),
        ("OPERATOR_RESOLVED", {"decided_by": "owner", "reason": "checked"}, True),
        ("RETRY_DUE", {"pass_id": SWEEP}, False),
        ("KILL", {"reason": "x" * 65}, False),
    ],
)
def test_each_event_payload_is_closed(event: str, payload: dict[str, Any], valid: bool) -> None:
    assert jsonschema.Draft202012Validator(b19.SCHEMAS[event]).is_valid(payload) is valid
    assert set(b19.SCHEMAS) == {
        "CANCEL", "KILL", "OPERATOR_RESOLVED", "RECONNECTED", "RETRY_DUE", "STARTUP",
        "SWEEP_DUE", "UNKNOWN_ORDER",
    }  # fmt: skip


async def test_stamp_start_takes_the_input_the_trigger_and_the_pass_id() -> None:
    context: dict[str, Any] = {"input": {"account_id": ACCOUNT, "auto_remediate": False}}
    await b19.set_trigger_periodic(None, context, _Event("SWEEP_DUE", {"trigger": "manual"}), None)
    await b19.stamp_start(
        None, context, _Event("SWEEP_DUE", {"trigger": "manual", "pass_id": SWEEP}), None
    )
    assert (context["account_id"], context["auto_remediate"]) == (ACCOUNT, False)
    assert (context["trigger"], context["pass_id"]) == ("manual", SWEEP)
    await b19.stamp_start(None, context, _Event("RETRY_DUE"), None)
    assert context["pass_id"] == SWEEP  # a retry keeps its pass
    await b19.stamp_start(None, context, _Event("SWEEP_DUE"), None)
    assert context["pass_id"] != SWEEP and context["trigger"] == "periodic"  # a new pass


@pytest.mark.parametrize(
    ("action", "trigger"),
    [
        (b19.set_trigger_reconnect, "reconnect"),
        (b19.set_trigger_startup, "startup"),
        (b19.set_trigger_unknown, "unknown"),
    ],
)
async def test_each_trigger_arm_records_its_trigger(action: Any, trigger: str) -> None:
    context: dict[str, Any] = {}
    await action(None, context, _Event("x"), None)
    assert context["trigger"] == trigger


async def test_unwired_the_services_answer_nothing_and_the_actions_do_nothing(
    unwired: None,
) -> None:
    context: dict[str, Any] = {"account_id": ACCOUNT, "pass_id": SWEEP, "trigger": "periodic"}
    with capture_logs() as logs:
        for service in b19.SERVICES.values():
            assert await service(None, context, _Event("x")) == {}
        for _name, action in sorted(b19.ACTIONS.items()):
            await action(None, context, _Event("OPERATOR_RESOLVED"), None)
    assert {e["event"] for e in logs} >= {"reconcile_ports_unwired"}
    assert context["unresolved"] == 0 and context["notices"] == []


async def test_every_action_is_total_over_a_port_that_raises() -> None:
    """A1: a raising port is logged by its class, never raised, and the report's failure leaves
    nothing for the guard."""
    b19.set_ports(_Raising())  # type: ignore[arg-type]  # a port that raises on every call
    try:
        context: dict[str, Any] = {"account_id": ACCOUNT, "pass_id": SWEEP, "trigger": "periodic"}
        context["notices"] = [["oms.account_desync", "warning"]]
        with capture_logs() as logs:
            for name in sorted(b19.ACTIONS):
                if name != "stamp_start":
                    await b19.ACTIONS[name](None, context, _Event("x"), None)
        assert {e["event"] for e in logs} >= {"reconcile_effect_failed", "reconcile_report_failed"}
        assert context["unresolved"] == 0
    finally:
        b19.set_ports(None)


async def test_the_failure_actions_record_the_class_never_the_text() -> None:
    context: dict[str, Any] = {"account_id": ACCOUNT, "consecutive_failures": 1}
    secret = RuntimeError("key=abc")
    await b19.bump_failures(None, context, _Error("error.platform.fetch", secret), None)
    assert (context["consecutive_failures"], context["last_failure"]) == (2, "RuntimeError")
    await b19.record_diff_error(None, context, _Error("error.platform.diff", KeyError("x")), None)
    await b19.store_remediations(None, context, _Error("error.platform.rem", ValueError()), None)
    assert context["last_failure"] == "ValueError" and "key=abc" not in repr(context)
    await b19.record_diff_error(None, context, _Event("x"), None)
    assert context["last_failure"] == "unknown"


async def test_the_summaries_land_in_plain_context() -> None:
    context: dict[str, Any] = {}
    await b19.store_exchange_state(None, context, _Done("done.invoke.fetch", {"orders": 3}), None)
    await b19.store_divergences(
        None, context, _Done("done.invoke.diff", {"kinds": ["Miss", 4]}), None
    )
    await b19.store_remediations(
        None, context, _Done("done.invoke.rem", {"kinds": ("Miss",)}), None
    )
    assert (context["orders_checked"], context["divergences"], context["remediations"]) == (
        3, ["Miss"], ["Miss"],
    )  # fmt: skip


@dataclass
class _Reports:
    """A port whose report answers `summary`; the effects are recorded."""

    summary: Mapping[str, Any]
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def now_us(self) -> int:
        return 7

    async def report(self, account_id: str, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("report", kwargs))
        return self.summary

    def observe(self, account_id: str, *, pass_id: str) -> None:
        self.calls.append(("observe", pass_id))

    def publish(self, account_id: str, notices: Sequence[Sequence[str]]) -> None:
        self.calls.append(("publish", list(notices)))


async def test_the_report_actions_hand_on_its_notices_and_items() -> None:
    port = _Reports(
        {
            "unresolved": 2,
            "result": "divergent",
            "notices": [["oms.account_desync", "warning"], ["bad"]],
            "episode_open": True,
        }
    )
    b19.set_ports(port)  # type: ignore[arg-type]  # the three calls this test makes
    try:
        context: dict[str, Any] = {"account_id": ACCOUNT, "pass_id": SWEEP, "trigger": "manual"}
        await b19.persist_report(None, context, _Event("x"), None)
        await b19.emit_recon_metrics(None, context, _Event("x"), None)
        await b19.broadcast_recon_complete(None, context, _Event("x"), None)
        assert (context["unresolved"], context["result"], context["episode_open"]) == (
            2,
            "divergent",
            True,
        )
        assert b19.unresolved_divergences(context, _Event("x"))
        assert port.calls[-1] == ("publish", [["oms.account_desync", "warning"]])
        assert port.calls[0][1]["trigger"] == "manual"
    finally:
        b19.set_ports(None)


@pytest.mark.parametrize(
    ("trigger", "event", "payload"),
    [
        ("startup", "STARTUP", {}),
        ("reconnect", "RECONNECTED", {}),
        ("unknown", "UNKNOWN_ORDER", {}),
        ("periodic", "SWEEP_DUE", {"trigger": "periodic"}),
        ("manual", "SWEEP_DUE", {"trigger": "manual"}),
    ],
)
def test_a_machine_restored_mid_fetch_is_cancelled_then_sent_its_trigger(
    trigger: str, event: str, payload: dict[str, Any]
) -> None:
    plan = b19.redrive_after_restore("fetching", {"trigger": trigger, "pass_id": SWEEP})
    assert plan == (("CANCEL", {}), (event, payload | {"pass_id": SWEEP}))


def test_the_rest_states_and_the_unresumable_ones() -> None:
    assert b19.REST_STATES == {"idle", "backing_off", "divergent", "stale_lockout"}
    assert b19.redrive_after_restore("idle", {}) == ()
    assert b19.redrive_after_restore("diffing", {}) is None
    assert b19.redrive_after_restore("fetching", {}) == (
        ("CANCEL", {}),
        ("SWEEP_DUE", {"trigger": "periodic"}),
    )
