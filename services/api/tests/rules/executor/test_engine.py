"""E35-T09 (#5000) slice 2d: the action executor (24 §11.5, §11.9; BQ-5 to BQ-9).

`Engine` drives one `ActionExecutor` with scripted doubles: check 1's verdicts, the switches of
checks 2 and 3 (open, E35-T10) and the principal of check 5 (both users active), the routing
emitter (a scope denial's reason, or the hand-over back to the executor; a dry run to the
simulation list) and the scope re-check before a retry, one bound
`send_notification` handler whose answers a test scripts per node, the records in memory and the
alerts. Every action is `send_notification`, so the bound handler serves them all.
No sleeps: a hang is an event nobody sets, under a bound the test sets to 0.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.rules.executor import dispatch, writeahead
from candleviewer.rules.executor import engine as engine_module
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.engine import ActionExecutor, RowVerdict
from candleviewer.rules.executor.gates import Gates
from candleviewer.rules.executor.handlers import (
    HANDLERS,
    HandlerAnswer,
    HandlerSpec,
    Prepared,
    prepared,
)
from candleviewer.rules.executor.keys import client_ref, dedupe_key
from candleviewer.rules.executor.ports import ActionAuditFields, EventRow, RunRow
from candleviewer.rules.ir.models import MAX_ACTIONS, Action, RuleScope
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from tests.rules.executor.request_builders import (
    Counted,
    Principals,
    Records,
    Switches,
    action_request,
)

GUARD_S = 5.0
RULE, RUN, OWNER = str(uuid.UUID(int=7)), uuid.UUID(int=8), uuid.UUID(int=0xA1)
ACCOUNT = uuid.UUID(int=0xB1)
NOTE: dict[str, Any] = {"channel": "ui", "severity": "info", "template": "x"}
OK, DONE = HandlerAnswer("accepted", order_id=uuid.UUID(int=0xD1)), HandlerAnswer("done")
REFUSED = HandlerAnswer("refused", error_code="validation_failed")
NO_ANSWER = HandlerAnswer("no_answer", error_code="timeout")
PRE_ANCHOR = HandlerAnswer("pre_anchor", error_code="oms_not_ready")
IN_FLIGHT = HandlerAnswer("in_flight", error_code="idempotency_in_flight")
RATE = HandlerAnswer("refused", error_code="exchange_rate_limited", blocked_by="rate_limited")


class Handler:
    """A bound handler: each node's answers in order, scripted; each send logged."""

    def __init__(self, answers: Mapping[str, list[Any]]) -> None:
        self.answers = {node: list(seq) for node, seq in answers.items()}
        self.prepared: list[str] = []
        self.sent: list[tuple[str, str, str]] = []  # (node, client_ref, request_sha256)

    def prepare(
        self, req: ActionRequest, account_id: uuid.UUID | None, *, max_notional_usd: Any
    ) -> Prepared:
        self.prepared.append(req.payload.node_id)
        return prepared({"node": req.payload.node_id, "account": str(account_id)})

    async def send(self, prep: Prepared, *, client_ref: str) -> HandlerAnswer:
        node = str(prep.request["node"])
        self.sent.append((node, client_ref, prep.request_sha256))
        answer = self.answers[node].pop(0)
        if answer == "hang":
            await asyncio.Event().wait()
        if isinstance(answer, BaseException):
            raise answer
        assert isinstance(answer, HandlerAnswer)
        return answer


class FlakyRecords(Records):
    """`Records` whose `nth` call of `write` (`begin`, `append`, `fired`) fails, or hangs."""

    def __init__(self, write: str = "", nth: int = 1, *, hang: bool = False) -> None:
        super().__init__()
        self.write, self.nth, self.hang, self.calls = write, nth, hang, dict[str, int]()

    async def _gate(self, write: str) -> None:
        self.calls[write] = self.calls.get(write, 0) + 1
        if write == self.write and self.calls[write] == self.nth:
            if self.hang:
                await asyncio.Event().wait()
            raise ConnectionError("the store refused the write")

    async def begin(self, run: RunRow, first: EventRow) -> None:
        await self._gate("begin")
        await super().begin(run, first)

    async def append(self, run_id: uuid.UUID, events: Any) -> None:
        await self._gate("append")
        await super().append(run_id, events)

    async def fired(self, fields: ActionAuditFields) -> None:
        await self._gate("fired")
        await super().fired(fields)


@dataclass
class Alerts:
    raised: list[tuple[str, str, uuid.UUID, str]] = field(default_factory=list)
    settled_rules: list[str] = field(default_factory=list)

    async def partial_fire(self, rule_id: str, run_id: uuid.UUID, node_id: str) -> None:
        self.raised.append(("partial_fire", rule_id, run_id, node_id))

    async def write_ahead_failed(self, rule_id: str, run_id: uuid.UUID, node_id: str) -> None:
        self.raised.append(("write_ahead_failed", rule_id, run_id, node_id))

    def settled(self, rule_id: str) -> None:
        self.settled_rules.append(rule_id)

    def breaker_tripped(self, rule_id: str, run_id: uuid.UUID, node_id: str) -> None:
        self.raised.append(("breaker_tripped", rule_id, run_id, node_id))  # E35-T10: no order here

    async def breaker_moved(
        self, rule_id: str, run_id: uuid.UUID, node_id: str, *, moved: bool
    ) -> None:
        self.raised.append(("breaker_moved", rule_id, run_id, node_id))


@dataclass
class Engine:
    handler: Handler
    records: Records = field(default_factory=Records)
    verdicts: dict[str, list[RowVerdict]] = field(default_factory=dict)
    rechecks: dict[str, list[str | None]] = field(default_factory=dict)  # the retry's check 4
    switches: Switches = field(default_factory=Switches)
    denied: set[str] = field(default_factory=set)
    order: list[tuple[str, str]] = field(default_factory=list)
    simulated: list[str] = field(default_factory=list)
    alerts: Alerts = field(default_factory=Alerts)
    counted: Counted = field(default_factory=Counted)
    executor: ActionExecutor = field(init=False)

    def __post_init__(self) -> None:
        spec = replace(HANDLERS["send_notification"], handler=self.handler)
        table: dict[str, HandlerSpec] = {**HANDLERS, "send_notification": spec}
        self.executor = ActionExecutor(
            check_one=self.check_one, scope_check=self.scope_check,
            gates=Gates(switches=self.switches, principal=Principals()), records=self.records,
            audit=self.records,
            alerts=self.alerts, metrics=self.counted.metrics, handlers=table,
        )  # fmt: skip

    async def check_one(self, req: ActionRequest) -> RowVerdict:
        node = req.payload.node_id
        self.order.append(("check1", node))
        queue = self.verdicts.get(node)
        return queue.pop(0) if queue else "armed"

    def scope_check(self, req: ActionRequest) -> str | None:
        self.order.append(("recheck", req.payload.node_id))
        queue = self.rechecks.get(req.payload.node_id)
        return queue.pop(0) if queue else None

    async def emit(self, req: ActionRequest) -> str | None:
        """The routing emitter (`emit_checked`): the scope re-check's reason, else the sink by mode
        (`_route`)."""
        node = req.payload.node_id
        self.order.append(("scope", node))
        if node in self.denied:
            return "grant_revoked"
        if req.mode != "armed" or req.payload.dry_run_only:
            self.simulated.append(node)
        else:
            await self.executor.hand_over(req)
        return None

    async def run(self, *nodes: str, on_error: str = "abort_remaining", **kw: Any) -> None:
        await self.executor.execute(fire(self.emit, *nodes, on_error=on_error, **kw))


def request(node: str, *, on_error: str = "abort_remaining", **over: Any) -> ActionRequest:
    action = Action.model_validate(
        {"node_id": node, "type": "send_notification", "params": NOTE, "on_error": on_error}
        | over.pop("action", {})
    )
    instance = ScopeInstanceRef(f"BTCUSDT@{ACCOUNT}", "BTCUSDT", ACCOUNT)
    scope = RuleScope.model_validate({"level": "account", "account_ids": [str(ACCOUNT)]})
    base = {"action_type": "send_notification", "payload": action, "rule_id": RULE, "run_id": RUN}
    return action_request(scope, OWNER, instance, **(base | over))


def fire(emit: Any, *nodes: str, on_error: str = "abort_remaining", **over: Any) -> Fire:
    reqs = tuple(request(n, on_error=on_error, **over) for n in nodes)
    return Fire(RULE, RUN, reqs, emit, version_id=str(uuid.UUID(int=0xC0)),
                trigger_type="on_bar_close")  # fmt: skip


def key(node: str) -> str:
    """The fire key of a `send_notification` action, which names no account (24 §11.5 `targets`,
    E35-T10): its key carries none."""
    return dedupe_key(
        rule_id=RULE, version=1, scope_instance=f"BTCUSDT@{ACCOUNT}", node_id=node, run_id=RUN,
        account_id=None,
    )  # fmt: skip


def outcomes(records: Records) -> list[tuple[str, str]]:
    return [(node, outcome) for node, outcome, _ in records.results()]


async def test_actions_run_in_order_and_stop_on_failure_by_default() -> None:
    """Scenario: Actions run in order and stop on failure by default. Three actions, the second
    fails: the first's effect is recorded, the third is never attempted, nothing is rolled back,
    and a critical alert names the rule, the fire and the failed action."""
    engine = Engine(Handler({"a1": [OK], "a2": [REFUSED], "a3": [OK]}))
    await engine.run("a1", "a2", "a3")
    assert [node for node, _, _ in engine.handler.sent] == ["a1", "a2"]  # a3 never attempted
    assert outcomes(engine.records) == [("a1", "ok"), ("a2", "failed"), ("a3", "skipped")]
    assert engine.alerts.raised == [("partial_fire", RULE, RUN, "a2")]
    assert engine.records.closed[RUN][0] == "error"


@pytest.mark.parametrize("mode", ["abort_remaining", "continue", "retry_once"])
@pytest.mark.parametrize(
    ("answer", "outcome"),
    [(OK, "ok"), (REFUSED, "failed"), (RATE, "blocked"), (IN_FLIGHT, "unknown")],
)
async def test_on_error_matrix(mode: str, answer: HandlerAnswer, outcome: str) -> None:
    """24 §11.5: `abort_remaining` stops after a result other than `ok`, `simulated` or
    `skipped`; `continue` never does; `retry_once` stops as `abort_remaining` once a result stands
    (none of these four is retried: three are definite, an in-flight answer is never re-sent)."""
    engine = Engine(Handler({"a1": [answer], "a2": [OK]}))
    await engine.run("a1", "a2", on_error=mode)
    stops = outcome != "ok" and mode != "continue"
    assert outcomes(engine.records) == [("a1", outcome), ("a2", "skipped" if stops else "ok")]
    assert len(engine.handler.sent) == (1 if stops else 2)


@pytest.mark.parametrize("answer", [NO_ANSWER, PRE_ANCHOR], ids=["no_answer", "pre_anchor"])
async def test_retry_once_reuses_the_same_request_and_key(answer: HandlerAnswer) -> None:
    """Scenario: A retry reuses the same request and key (edge case): after no answer, or a
    refusal before the anchor existed (24 §11.9), one retry with the same fingerprint, dedupe key
    and `client_ref`; one `rules.fired` keyed by that key. An in-flight answer is recorded
    `unknown` and not re-sent (below)."""
    engine = Engine(Handler({"a1": [answer, OK]}))
    await engine.run("a1", on_error="retry_once")
    (first, again) = engine.handler.sent
    assert first == again == ("a1", client_ref(key("a1")), first[2])
    assert engine.handler.prepared == ["a1"]  # built once, sent twice
    assert outcomes(engine.records) == [("a1", "ok")]
    assert [f.dedupe_key for _, f in engine.records.audits] == [key("a1")] * 2  # one keyed record
    starts = [e for _, e in engine.records.events if e.kind == "action_start"]
    assert len(starts) == 2 and engine.order.count(("recheck", "a1")) == 1


async def test_retry_once_never_retries_a_definite_refusal() -> None:
    """Scenario: A definite refusal is never retried (failure case)."""
    engine = Engine(Handler({"a1": [REFUSED]}))
    await engine.run("a1", on_error="retry_once")
    assert len(engine.handler.sent) == 1 and outcomes(engine.records) == [("a1", "failed")]
    assert ("recheck", "a1") not in engine.order


async def test_in_flight_answer_is_recorded_unknown_not_resent() -> None:
    engine = Engine(Handler({"a1": [IN_FLIGHT, OK]}))
    await engine.run("a1", on_error="retry_once")
    assert len(engine.handler.sent) == 1 and outcomes(engine.records) == [("a1", "unknown")]
    (result,) = [e.payload for _, e in engine.records.events if e.kind == "action_fail"]
    assert result["error_code"] == "idempotency_in_flight"


async def test_partial_fire_alert_names_the_rule_the_fire_and_the_failed_action() -> None:
    """Any fire with an `ok` result and one that failed, was blocked or is unknown, whatever its
    `on_error`; a fire with no `ok` result is no partial fire, and closes the rule's episode."""
    engine = Engine(Handler({"a1": [OK], "a2": [IN_FLIGHT], "a3": [OK]}))
    await engine.run("a1", "a2", "a3", on_error="continue")
    assert engine.alerts.raised == [("partial_fire", RULE, RUN, "a2")]
    whole = Engine(Handler({"a1": [REFUSED]}))
    await whole.run("a1")
    assert whole.alerts.raised == [] and whole.alerts.settled_rules == [RULE]


async def test_nothing_is_rolled_back_after_a_partial_fire() -> None:
    engine = Engine(Handler({"a1": [OK], "a2": [REFUSED]}))
    await engine.run("a1", "a2")
    assert [node for node, _, _ in engine.handler.sent] == ["a1", "a2"]  # no compensating send
    assert outcomes(engine.records) == [("a1", "ok"), ("a2", "failed")]


@pytest.mark.parametrize("late", [False, True], ids=["fails", "late"])
@pytest.mark.parametrize(("write", "nth"), [("begin", 1), ("fired", 1), ("append", 2)])
async def test_the_write_ahead_comes_first(
    write: str, nth: int, late: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario: The write-ahead comes first (failure case). The run row, the audit record or the
    event write fails or does not land within its bound: that action is not sent, it is `failed`
    (`write_ahead_failed`), the rest stop whatever `on_error` says, and the alert is raised
    (AC-14). A retried write-ahead's one audit record: the retry test above, and the real writer's
    in `test_write_ahead.py`."""
    if late:
        monkeypatch.setattr(writeahead, "FIRE_RECORD_TIMEOUT_S", 0.0)
    records = FlakyRecords(write, nth, hang=late)
    engine = Engine(Handler({"a0": [OK], "a1": [OK], "a2": [OK]}), records=records)
    nodes = ("a0", "a1", "a2") if write == "append" else ("a1", "a2")  # a0 lands the run row
    async with asyncio.timeout(GUARD_S):
        await engine.run(*nodes, on_error="continue")
    sent = [node for node, _, _ in engine.handler.sent]
    assert "a1" not in sent and "a2" not in sent  # nor the rest, though `on_error` is continue
    writes = [alert for alert in engine.alerts.raised if alert[0] == "write_ahead_failed"]
    assert writes == [("write_ahead_failed", RULE, RUN, "a1")]  # once, naming the action
    assert engine.alerts.settled_rules == []  # the rule's alert episode goes on: it pages once
    failed = [e.payload for _, e in records.events if e.kind == "action_fail"]
    assert [(r["node_id"], r["outcome"], r["error_code"]) for r in failed] == [
        ("a1", "failed", "write_ahead_failed"), ("a2", "skipped", None),
    ]  # fmt: skip


async def test_retry_once_reruns_the_checks_and_a_refusal_sends_nothing() -> None:
    """Before the retry checks 1 to 8 run again (E35-T10): one that now refuses (the scope
    re-check here, check 1 below) sends nothing, and the first call's result stands (`unknown`
    after no answer)."""
    engine = Engine(Handler({"a1": [NO_ANSWER, OK]}))
    engine.rechecks["a1"] = ["grant_revoked"]
    await engine.run("a1", on_error="retry_once")
    assert len(engine.handler.sent) == 1 and outcomes(engine.records) == [("a1", "unknown")]
    pre = Engine(Handler({"a1": [PRE_ANCHOR, OK]}))
    pre.verdicts["a1"] = ["armed", "mode_changed"]  # the row is disarmed before the retry
    await pre.run("a1", on_error="retry_once")
    assert len(pre.handler.sent) == 1 and outcomes(pre.records) == [("a1", "failed")]
    assert ("recheck", "a1") not in pre.order  # check 1 refused first: check 4 was never asked


@pytest.mark.parametrize("mode", ["abort_remaining", "continue", "retry_once"])
async def test_a_failed_reread_skips_the_rest_of_the_fire_and_is_recorded(mode: str) -> None:
    """BQ-6: a check-1 read that fails or is late counts as a row no longer armed: that action
    and every later one `skipped` (`mode_changed`), each with `action_fail` and `rules.blocked`,
    nothing more read or sent, whatever `on_error` says."""
    engine = Engine(Handler({"a1": [OK], "a2": [OK], "a3": [OK]}))
    engine.verdicts["a2"] = ["unread"]
    await engine.run("a1", "a2", "a3", on_error=mode)
    assert [node for node, _, _ in engine.handler.sent] == ["a1"]
    assert ("check1", "a3") not in engine.order  # nothing more is read
    assert engine.records.results() == [
        ("a1", "ok", None), ("a2", "skipped", "mode_changed"), ("a3", "skipped", "mode_changed"),
    ]  # fmt: skip
    blocked = [
        (f.node_id, f.blocked_by) for verb, f in engine.records.audits if verb == "rules.blocked"
    ]
    assert blocked == [("a2", "mode_changed"), ("a3", "mode_changed")]


async def test_a_row_no_longer_armed_skips_the_rest_as_mode_changed_and_is_recorded() -> None:
    engine = Engine(Handler({"a1": [OK], "a2": [OK]}))
    engine.verdicts["a1"] = ["mode_changed"]
    await engine.run("a1", "a2", on_error="continue")
    assert engine.handler.sent == [] and engine.order == [("check1", "a1")]
    details = [e.payload["blocked_detail"] for _, e in engine.records.events]
    assert len(set(details)) == 1 and "disarmed" in details[0]  # its own detail, not the unread one
    assert engine.records.closed[RUN][0] == "aborted"


async def test_check_one_runs_before_the_scope_recheck() -> None:
    """24 §11.5's order: a fire both disarmed and out of scope reads `mode_changed`, never
    `scope`, and the scope gate is not consulted."""
    engine = Engine(Handler({"a1": [OK]}))
    engine.verdicts["a1"], engine.denied = ["mode_changed"], {"a1"}
    await engine.run("a1")
    assert engine.order == [("check1", "a1")]
    assert engine.records.results() == [("a1", "skipped", "mode_changed")]


async def test_a_scope_denied_action_in_a_fire_writes_rules_blocked_beside_scope_denied() -> None:
    """BQ-5: the emitter audits its own denial (`rules.scope_denied`, E35-S04); the executor
    records the action `blocked` (`scope`) with `rules.blocked` and its `action_fail`."""
    engine = Engine(Handler({"a1": [OK]}))
    engine.denied = {"a1"}
    await engine.run("a1")
    assert engine.records.results() == [("a1", "blocked", "scope")]
    assert [(verb, f.blocked_by) for verb, f in engine.records.audits] == [
        ("rules.blocked", "scope")
    ]
    assert engine.counted.blocked() == {"scope": 1} and engine.handler.sent == []


async def test_a_timed_out_action_is_unknown_and_a_raising_one_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The action's bound (`ACTION_TIMEOUT_S`, 0 s here): a timeout after the hand-over began is
    `unknown`; a raise is `failed`; each logged by its class alone."""
    monkeypatch.setattr(dispatch, "ACTION_TIMEOUT_S", 0.0)
    engine = Engine(Handler({"a1": ["hang"], "a2": [RuntimeError("boom 64123.5")]}))
    with capture_logs() as logs:
        async with asyncio.timeout(GUARD_S):
            await engine.run("a1", "a2", on_error="continue")
    assert outcomes(engine.records) == [("a1", "unknown"), ("a2", "failed")]
    failed = [
        (e["node_id"], e["reason"], e["kind"]) for e in logs if e["event"] == "rules.action_failed"
    ]
    assert failed == [("a1", "timeout", "TimeoutError"), ("a2", "error", "RuntimeError")]
    assert "64123.5" not in repr(logs)


@pytest.mark.parametrize(
    ("answers", "status"),
    [
        ([OK, DONE], "ok"),
        ([OK, REFUSED], "error"),
        ([OK, IN_FLIGHT], "error"),
        ([OK, RATE], "aborted"),
    ],
)
async def test_the_run_row_is_closed_with_the_fires_status(answers: list[Any], status: str) -> None:
    engine = Engine(Handler({"a1": [answers[0]], "a2": [answers[1]]}))
    await engine.run("a1", "a2", on_error="continue")
    assert engine.records.closed[RUN][0] == status
    (run,) = engine.records.runs.values()
    assert (run.trigger_reason, run.version_id, run.account_id) == (
        "bar_close", str(uuid.UUID(int=0xC0)), ACCOUNT,
    )  # fmt: skip


async def test_a_simulate_fire_writes_no_run_row() -> None:
    engine = Engine(Handler({}))
    await engine.executor.execute(fire(engine.emit, "a1", "a2", mode="simulate"))
    assert engine.simulated == ["a1", "a2"] and engine.records.runs == {}
    assert engine.records.events == [] and engine.counted.of("rule_actions_total") == {}


async def test_a_dry_run_only_action_is_simulated_with_no_rules_fired() -> None:
    engine = Engine(Handler({"a2": [OK]}))
    dry = request("a1", action={"dry_run_only": True})
    await engine.executor.execute(
        Fire(RULE, RUN, (dry, request("a2")), engine.emit, version_id="v", trigger_type="t")
    )
    assert engine.simulated == ["a1"] and outcomes(engine.records) == [("a1", "simulated"),
                                                                     ("a2", "ok")]  # fmt: skip
    assert [f.node_id for verb, f in engine.records.audits if verb == "rules.fired"] == ["a2"]
    (dry_event, *_) = [e for _, e in engine.records.events]
    assert (dry_event.kind, dry_event.node_ref) == ("action_ok", "a1")


async def test_a_bound_stand_in_never_serves_an_action_that_would_reach_the_oms() -> None:
    """C-2.6: a bound `action_sink` stands in for the engine-internal handlers no slice has bound
    yet; every action that would reach the OMS stays `unavailable`, `widen_stop` `native_sl`."""
    reached: list[str] = []

    async def sink(req: ActionRequest) -> None:
        reached.append(req.action_type)

    engine = Engine(Handler({}))
    records = engine.records
    # Check 5 admits the instance's account, so `widen_stop` reaches check 8 (E35-T10).
    engine.executor = ActionExecutor(
        check_one=engine.check_one, scope_check=engine.scope_check,
        gates=Gates(switches=Switches(rollout=True), principal=Principals(frozenset({ACCOUNT}))),
        records=records, audit=records, stand_in=sink,
    )  # fmt: skip
    types = (
        "place_order", "scale_out", "cancel_order", "modify_stop_loss", "move_to_breakeven",
        "halt_new_orders", "reduce_leverage", "start_twap", "widen_stop", "send_notification",
        "set_variable",
    )  # fmt: skip
    runs = (RUN, uuid.UUID(int=9))  # E35-T10: a rule holds at most `MAX_ACTIONS`, so two fires
    reqs = tuple(
        request(f"a{n}", on_error="continue", action_type=t, action={"type": t, "params": {}},
                run_id=runs[n // MAX_ACTIONS])
        for n, t in enumerate(types)
    )  # fmt: skip
    for k, run in enumerate(runs):
        part = reqs[k * MAX_ACTIONS : (k + 1) * MAX_ACTIONS]
        await engine.executor.execute(Fire(RULE, run, part, engine.emit, version_id="v"))
    assert reached == ["send_notification", "set_variable"]
    refused = {node: reason for node, outcome, reason in records.results() if outcome == "blocked"}
    assert refused == {f"a{n}": "native_sl" if t == "widen_stop" else "unavailable"
                       for n, t in enumerate(types) if t not in reached}  # fmt: skip


class FailingRecords(Records):
    """`Records` whose `nth` call of `append` or `close` raises."""

    def __init__(self, write: str, nth: int = 1) -> None:
        super().__init__()
        self.write, self.nth, self.calls = write, nth, 0

    async def append(self, run_id: uuid.UUID, events: Any) -> None:
        if self.write == "append":
            self.calls += 1
            if self.calls == self.nth:
                raise ConnectionError("the store refused the append")
        await super().append(run_id, events)

    async def close(self, run_id: uuid.UUID, status: Any, duration_ms: int) -> None:
        if self.write == "close":
            raise ConnectionError("the store refused the close")
        await super().close(run_id, status, duration_ms)


async def test_an_executor_with_no_records_bound_hands_nothing_over() -> None:
    """RE-R1: with no ports bound no write ahead can land, so no action is handed over; its
    result is counted `failed` (`write_ahead_failed`) and the write-ahead alert raised."""
    engine = Engine(Handler({"a1": [OK]}))
    engine.executor = ActionExecutor(
        check_one=engine.check_one, scope_check=engine.scope_check,
        gates=Gates(switches=engine.switches, principal=Principals()), alerts=engine.alerts,
        metrics=engine.counted.metrics, handlers=engine.executor._handlers,
    )  # fmt: skip
    with capture_logs() as logs:
        await engine.run("a1", "a2")
    assert engine.handler.sent == [] and engine.records.events == []
    assert engine.counted.of("rule_actions_total") == {
        ("failed", "send_notification"): 1, ("skipped", "send_notification"): 1,
    }  # fmt: skip
    assert [a[0] for a in engine.alerts.raised] == ["write_ahead_failed"]
    assert [e["write"] for e in logs if e["event"] == "rules.records_failed"] == ["run"]


@pytest.mark.parametrize("write", ["begin", "append", "close", "fired", "blocked"])
async def test_the_unbound_ports_refuse_every_write(write: str) -> None:
    unbound: Any = engine_module._Unbound()
    args: dict[str, tuple[Any, ...]] = {
        "begin": (None, None), "append": (RUN, ()), "close": (RUN, "ok", 0),
        "fired": (None,), "blocked": (None,),
    }  # fmt: skip
    with pytest.raises(RuntimeError, match="not bound"):
        await getattr(unbound, write)(*args[write])


async def test_a_failed_write_after_the_answer_stops_the_rest_and_alerts() -> None:
    """24 §11.5: a write after the answer that fails stops the rest the same way, the answered
    result standing; nothing more is written for the fire but its close, still tried once, as
    `error` (BQ-9), so the row never stays `running` after its fire ended."""
    records = FailingRecords("append", nth=1)  # a1's `action_ok`
    engine = Engine(Handler({"a1": [OK], "a2": [OK]}), records=records)
    with capture_logs() as logs:
        await engine.run("a1", "a2", on_error="continue")
    assert [node for node, _, _ in engine.handler.sent] == ["a1"]
    assert [a[0] for a in engine.alerts.raised] == ["write_ahead_failed"]
    assert records.closed[RUN][0] == "error" and [e.kind for _, e in records.events] == [
        "action_start"
    ]
    failed = [(e["queue"], e["write"]) for e in logs if e["event"] == "rules.records_failed"]
    assert failed == [("rule-dispatch", "event")]


async def test_a_close_that_fails_leaves_the_run_running_and_is_logged() -> None:
    records = FailingRecords("close")
    engine = Engine(Handler({"a1": [OK]}), records=records)
    with capture_logs() as logs:
        await engine.run("a1")
    assert RUN not in records.closed and outcomes(records) == [("a1", "ok")]
    closes = [(e["queue"], e["cause"]) for e in logs if e["event"] == "rules.run_close_failed"]
    assert closes == [("rule-dispatch", "ConnectionError")]


async def test_an_armed_fires_close_carries_its_duration() -> None:
    """The run row's close carries the fire's own `duration_ms`, from its start to its last
    result, on the executor's clock (24 §11.5)."""
    now = [100.0]

    class Slow(Handler):
        async def send(self, prep: Prepared, *, client_ref: str) -> HandlerAnswer:
            now[0] += 1.25  # the handler's answer takes 1.25 s
            return await super().send(prep, client_ref=client_ref)

    engine = Engine(Slow({"a1": [OK]}))
    engine.executor = ActionExecutor(
        check_one=engine.check_one, scope_check=engine.scope_check,
        gates=Gates(switches=engine.switches, principal=Principals(clock=lambda: now[0])),
        records=engine.records, audit=engine.records, handlers=engine.executor._handlers,
        clock=lambda: now[0],
    )  # fmt: skip
    await engine.run("a1")
    assert engine.records.closed[RUN] == ("ok", 1250)
    (answered,) = [e.payload for _, e in engine.records.events if e.kind == "action_ok"]
    assert answered["duration_us"] == 1_250_000


async def test_a_snapshot_no_run_row_can_hold_stops_the_fire_as_a_failed_write() -> None:
    """A metric value `input_snapshot` refuses (an over-wide decimal) leaves the fire no run row
    to write: it stops as one whose write ahead failed, nothing sent and nothing recorded, the
    alert raised once and each failed write logged by its class alone, never the value."""
    engine = Engine(Handler({"a1": [OK], "a2": [OK]}))
    wide = replace(fire(engine.emit, "a1", "a2"), metric_values={"price": Decimal("1E+100")})
    with capture_logs() as logs:
        async with asyncio.timeout(GUARD_S):
            await engine.executor.execute(wide)
    assert engine.handler.sent == [] and engine.records.runs == {}
    assert engine.records.events == [] and engine.records.audits == []
    assert engine.alerts.raised == [("write_ahead_failed", RULE, RUN, "a1")]
    assert engine.counted.of("rule_actions_total") == {
        ("failed", "send_notification"): 1, ("skipped", "send_notification"): 1,
    }  # fmt: skip
    failed = [(e["event"], e["cause"]) for e in logs if e["log_level"] == "error"]
    assert failed == [
        ("rules.records_failed", "IrValueError"), ("rules.run_close_failed", "IrValueError"),
    ]  # fmt: skip
    assert "1E+100" not in repr(logs) and "1e+100" not in repr(logs).lower()


async def test_a_snapshot_no_run_row_can_hold_stops_a_refused_fires_job_without_an_alert() -> None:
    """The same snapshot on a refused fire's record-only job: it writes nothing and raises no
    alert (its refusal was counted and paged on the tick), and each failed write, the first
    action's records and the close tried once after them, is logged on the audit queue by its
    class alone, never the value."""
    engine = Engine(Handler({}))
    refused = replace(
        fire(engine.emit, "a1", "a2"),
        kind="refused_fire",
        metric_values={"price": Decimal("1E+100")},
    )
    with capture_logs() as logs:
        async with asyncio.timeout(GUARD_S):
            await engine.executor.execute(refused)
    assert engine.records.runs == {} and engine.records.closed == {}
    assert engine.records.events == [] and engine.records.audits == []
    assert engine.alerts.raised == [] and engine.alerts.settled_rules == []
    failed = [(e["event"], e["queue"], e["cause"]) for e in logs if e["log_level"] == "error"]
    assert failed == [
        ("rules.records_failed", "rule-dispatch-audit", "IrValueError"),
        ("rules.run_close_failed", "rule-dispatch-audit", "IrValueError"),
    ]
    assert "1E+100" not in repr(logs) and "1e+100" not in repr(logs).lower()


async def test_a_retry_whose_write_ahead_fails_keeps_the_first_result() -> None:
    records = FlakyRecords("fired", nth=2)  # the retry's `rules.fired`
    engine = Engine(Handler({"a1": [NO_ANSWER, OK], "a2": [OK]}), records=records)
    await engine.run("a1", "a2", on_error="retry_once")
    assert len(engine.handler.sent) == 1  # not re-sent
    assert outcomes(records) == [("a1", "unknown"), ("a2", "skipped")]
    assert [a[0] for a in engine.alerts.raised] == ["write_ahead_failed"]


async def test_the_defensive_refusals_send_nothing() -> None:
    """An action passed by an emitter that never handed it over is `failed`; an action type
    absent from the table is `unavailable`; `hand_over` outside a fire refuses."""
    engine = Engine(Handler({"a1": [OK]}))

    async def passes_only(req: ActionRequest) -> None:
        return None  # `emit_checked`: it went on, yet nothing was handed over

    await engine.executor.execute(fire(passes_only, "a1"))
    ((node, outcome, _),) = engine.records.results()
    assert (node, outcome) == ("a1", "failed") and engine.handler.sent == []
    table = {k: v for k, v in HANDLERS.items() if k != "send_notification"}
    missing = Engine(Handler({"a1": [OK]}))
    missing.executor = ActionExecutor(
        check_one=missing.check_one, scope_check=missing.scope_check,
        gates=Gates(switches=missing.switches, principal=Principals()), records=missing.records,
        audit=missing.records, handlers=table,
    )  # fmt: skip
    await missing.run("a1")
    assert missing.records.results() == [("a1", "blocked", "unavailable")]
    with pytest.raises(RuntimeError, match="only inside its fire"):
        await missing.executor.hand_over(request("a1"))


async def test_a_simulate_fire_that_raises_stops_and_is_logged() -> None:
    engine = Engine(Handler({}))

    async def broken(req: ActionRequest) -> bool:
        raise RuntimeError("the simulation sink failed")

    with capture_logs() as logs:
        await engine.executor.execute(fire(broken, "a1", "a2", mode="simulate"))
    failed = [e for e in logs if e["event"] == "rules.action_failed"]
    assert [(e["queue"], e["node_id"], e["not_run"]) for e in failed] == [
        ("rule-dispatch", "a1", 1)
    ]
    assert engine.records.events == []


async def test_a_scope_denial_job_that_raises_is_logged_on_the_audit_queue() -> None:
    """A scope-skipped evaluation's audit-only job whose audit write raises stops there, and its
    line names the audit queue, never the fire queue (#5231's carry RC-03)."""
    engine = Engine(Handler({}))

    async def broken(req: ActionRequest) -> bool:
        raise RuntimeError("the audit write failed")

    with capture_logs() as logs:
        await engine.executor.execute(replace(fire(broken, "a1", "a2"), kind="scope_denial"))
    failed = [e for e in logs if e["event"] == "rules.action_failed"]
    assert [(e["queue"], e["node_id"], e["not_run"]) for e in failed] == [
        ("rule-dispatch-audit", "a1", 1)
    ]
    assert engine.records.events == []


@pytest.mark.parametrize(("write", "kept"), [("begin", []), ("append", ["a1"])])
async def test_a_refused_fires_records_that_fail_are_logged(write: str, kept: list[str]) -> None:
    """A refused fire's record-only job whose write fails (the row with a1's records, or a2's
    `action_fail`) is logged by its queue, the write and the class alone, and writes nothing
    more but its row's close, still tried once, as `error` (BQ-9); a job with no action writes
    nothing."""
    records = FlakyRecords(write, 1)
    engine = Engine(Handler({}), records=records)
    refused = replace(fire(engine.emit, "a1", "a2", "a3"), kind="refused_fire")
    with capture_logs() as logs:
        await engine.executor.execute(refused)
        await engine.executor.execute(replace(refused, requests=()))
    failed = [
        (e["queue"], e["write"], e["cause"]) for e in logs if e["event"] == "rules.records_failed"
    ]
    kind = "run" if write == "begin" else "event"
    assert failed == [("rule-dispatch-audit", kind, "ConnectionError")]
    assert [e.node_ref for _, e in records.events] == [f.node_id for _, f in records.audits] == kept
    assert records.closed == {RUN: ("error", 0)}
