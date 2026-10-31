"""E35-T09 (#5000) slice 2c: the records written ahead (24 §11.5; RE-R1, AC-14 of the E35 model).

`FireRecords` keeps one armed fire's records: the run row with its first event in one write, an
`action_start` row and `rules.fired` before the hand-over, a result's `action_ok` or `action_fail`
after it, a refusal's `action_fail` and `rules.blocked`, and the run row's close. Each write has
its own bound; a write that fails or outlasts it raises `WriteAheadFailed`, and the hand-over
never runs. The stores are fakes that fail or hang on the write a test names; no sleeps: a hang
is an event nobody sets, under the bound the test sets and a guard bound that only a regression
reaches.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from candleviewer.audit.writer import AuditWriter, keyed_record_id
from candleviewer.rules.executor import writeahead
from candleviewer.rules.executor.ports import (
    ActionAuditFields,
    EventRow,
    RunRow,
    RunStatus,
    input_snapshot,
)
from candleviewer.rules.executor.results import ActionResult, Outcome, blocked_result
from candleviewer.rules.executor.writeahead import FireRecords, WriteAheadFailed
from candleviewer.rules_oms_wiring import RuleActionAudit
from tests.unit.audit.audit_fakes import FakeAuditRepository, FakeClock

GUARD_S = 5.0  # a wait's bound: only a regression (a write with no bound of its own) reaches it
PLANTED = "acct-secret-7f3a"  # in every failure a fake raises: it must never reach the error
RULE, RUN, OWNER = str(uuid.UUID(int=7)), uuid.UUID(int=8), uuid.UUID(int=0xA1)
RUN_ROW = RunRow(
    run_id=RUN, rule_id=RULE, version_id=str(uuid.UUID(int=0xC0)), mode="armed",
    trigger_reason="tick", account_id=None, symbol="BTCUSDT", matched=True,
    input_snapshot=input_snapshot({}),
)  # fmt: skip


class Store:
    """`RunRecords`: logs each write as it goes in; `fail` names the write that raises, `hang`
    the one that never answers."""

    def __init__(self, *, fail: str | None = None, hang: str | None = None) -> None:
        self.fail, self.hang = fail, hang
        self.writes: list[str] = []
        self.runs: list[RunRow] = []
        self.events: list[EventRow] = []
        self.closes: list[tuple[uuid.UUID, RunStatus, int]] = []

    async def _gate(self, write: str) -> None:
        self.writes.append(write)
        if write == self.hang:
            await asyncio.Event().wait()
        if write == self.fail:
            raise RuntimeError(f"{write} refused for {PLANTED}")

    async def begin(self, run: RunRow, first: EventRow) -> None:
        await self._gate("begin")
        self.runs.append(run)
        self.events.append(first)

    async def append(self, run_id: uuid.UUID, events: Any) -> None:
        await self._gate("append")
        self.events.extend(events)

    async def close(self, run_id: uuid.UUID, status: RunStatus, duration_ms: int) -> None:
        await self._gate("close")
        self.closes.append((run_id, status, duration_ms))


class Audit:
    """`ActionAudit`: logs `rules.fired` and `rules.blocked` as `(verb, fields)`."""

    def __init__(self, *, fail: str | None = None, hang: str | None = None) -> None:
        self.fail, self.hang = fail, hang
        self.log: list[tuple[str, ActionAuditFields]] = []

    async def _gate(self, verb: str, fields: ActionAuditFields) -> None:
        if verb == self.hang:
            await asyncio.Event().wait()
        if verb == self.fail:
            raise OSError(f"audit refused for {PLANTED}")
        self.log.append((verb, fields))

    async def fired(self, fields: ActionAuditFields) -> None:
        await self._gate("fired", fields)

    async def blocked(self, fields: ActionAuditFields) -> None:
        await self._gate("blocked", fields)


def _fields(node: str, account: uuid.UUID | None = None) -> ActionAuditFields:
    return ActionAuditFields(
        rule_id=RULE, version=1, ir_hash="0" * 64, run_id=RUN, node_id=node,
        action_type="send_notification", scope_instance="BTCUSDT@*", account_id=account,
        owner=OWNER, armed_by=str(OWNER), dedupe_key=hashlib.sha256(node.encode()).hexdigest(),
    )  # fmt: skip


def _sender(sent: list[str], node: str) -> Callable[[], Awaitable[str]]:
    async def send() -> str:
        sent.append(node)
        return f"answer-{node}"

    return send


def _result(node: str, outcome: Outcome = "ok") -> ActionResult:
    return ActionResult(
        node_id=node, action_type="send_notification", account_id=None, resolved_accounts=(),
        outcome=outcome, dedupe_key=_fields(node).dedupe_key, duration_us=40,
    )  # fmt: skip


def _refusal(node: str) -> ActionResult:
    f = _fields(node)
    return blocked_result(
        node_id=node, action_type=f.action_type, account_id=None, resolved_accounts=(),
        dedupe_key=f.dedupe_key, reason="unavailable",
    )  # fmt: skip


def _clean(failure: WriteAheadFailed) -> None:
    """It names the write and the cause's class alone (C-12.6), and chains nothing that would."""
    assert PLANTED not in f"{failure!s} {failure!r}"
    assert failure.__cause__ is None and failure.__context__ is None


@pytest.mark.parametrize("write", ["begin", "append"])
async def test_action_not_sent_when_firing_log_write_fails(write: str) -> None:
    """RE-R1, AC-14: the run row (with the first `action_start`) or a later action's event fails:
    that action is not sent, and its `rules.fired` is never written."""
    store, audit, sent = Store(fail=write), Audit(), list[str]()
    records = FireRecords(RUN_ROW, store, audit)
    if write == "append":  # the run row and the first action land; the second's event fails
        assert await records.admitted(_fields("a1"), _sender(sent, "a1")) == "answer-a1"
    with pytest.raises(WriteAheadFailed) as failed:
        await records.admitted(_fields("a2"), _sender(sent, "a2"))
    assert (failed.value.write, failed.value.cause) == (
        "run" if write == "begin" else "event", "RuntimeError",
    )  # fmt: skip
    _clean(failed.value)
    assert "a2" not in sent and [f.node_id for _, f in audit.log] == sent


async def test_action_not_sent_when_audit_write_fails() -> None:
    store, audit, sent = Store(), Audit(fail="fired"), list[str]()
    records = FireRecords(RUN_ROW, store, audit)
    with pytest.raises(WriteAheadFailed) as failed:
        await records.admitted(_fields("a1"), _sender(sent, "a1"))
    assert (failed.value.write, failed.value.cause) == ("audit", "OSError")
    _clean(failed.value)
    assert sent == [] and audit.log == [] and store.writes == ["begin"]


@pytest.mark.parametrize("write", ["begin", "append", "fired"])
async def test_action_not_sent_when_a_write_outlasts_its_bound(
    write: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each write has its own bound (`WRITE_AHEAD_TIMEOUT_S`, BQ-9): one that does not answer
    within it stops the fire as a failure does. The bound is read at each write."""
    assert writeahead.WRITE_AHEAD_TIMEOUT_S == 2.0
    monkeypatch.setattr(writeahead, "WRITE_AHEAD_TIMEOUT_S", 0.0)
    store, sent = Store(hang=write if write != "fired" else None), list[str]()
    audit = Audit(hang=write if write == "fired" else None)
    records = FireRecords(RUN_ROW, store, audit)
    if write == "append":
        await records.admitted(_fields("a1"), _sender(sent, "a1"))
    async with asyncio.timeout(GUARD_S):
        with pytest.raises(WriteAheadFailed) as failed:
            await records.admitted(_fields("a2"), _sender(sent, "a2"))
    kind = {"begin": "run", "append": "event", "fired": "audit"}[write]
    assert (failed.value.write, failed.value.cause) == (kind, "TimeoutError")
    assert "a2" not in sent


async def test_a_retried_write_ahead_writes_one_audit_record(tmp_path: Path) -> None:
    """Scenario: The write-ahead comes first (failure case), its last line: a retried write-ahead
    writes one audit record only. The audit writer keys `rules.fired` and `rules.blocked` by the
    action's `dedupe_key` (24 §15.5), so a second write of either lands on the first's row."""
    repo = FakeAuditRepository()
    writer = AuditWriter(
        repo, str(tmp_path / "audit.wal"), clock=FakeClock(), sleep=repo.retry_sleep
    )
    await writer.start()
    store, sent = Store(), list[str]()
    records = FireRecords(RUN_ROW, store, RuleActionAudit(writer))
    for _ in range(2):  # `retry_once`'s second attempt writes its write-ahead again
        await records.admitted(_fields("a1"), _sender(sent, "a1"))
        await records.refused(_refusal("a2"), _fields("a2"))
    await writer.flush(5)
    await writer.stop(1)
    assert sent == ["a1", "a1"] and [e.seq for e in store.events] == [1, 2, 3, 4]
    rows = {(row["action"], row["record_id"]) for row in repo.rows}
    assert rows == {
        ("rules.fired", str(keyed_record_id("rules.fired", _fields("a1").dedupe_key))),
        ("rules.blocked", str(keyed_record_id("rules.blocked", _fields("a2").dedupe_key))),
    }
    assert len(repo.rows) == 2


async def test_the_run_row_and_the_first_event_go_in_one_write() -> None:
    """The fire's first write is the run row with its first event, in one transaction (BQ-3):
    an action's `action_start`, or a refusal's `action_fail` when the first action is refused."""
    for first in ("admitted", "refused"):
        store, audit = Store(), Audit()
        records = FireRecords(RUN_ROW, store, audit)
        if first == "admitted":
            await records.admitted(_fields("a1"), _sender([], "a1"))
        else:
            await records.refused(_refusal("a1"), _fields("a1"))
        assert store.writes == ["begin"] and store.runs == [RUN_ROW]
        (event,) = store.events
        kind = "action_start" if first == "admitted" else "action_fail"
        assert (event.seq, event.kind, event.node_ref) == (1, kind, "a1")


async def test_a_refused_action_writes_rules_blocked_and_action_fail_never_rules_fired() -> None:
    store, audit = Store(), Audit()
    records = FireRecords(RUN_ROW, store, audit)
    refusal = _refusal("a1")
    await records.refused(refusal, _fields("a1"))
    ((verb, fields),) = audit.log
    assert (verb, fields.blocked_by, fields.node_id) == ("blocked", "unavailable", "a1")
    (event,) = store.events
    assert (event.kind, event.severity) == ("action_fail", "warning")
    assert event.payload == refusal.model_dump(mode="json")
    with pytest.raises(ValueError):  # a result no check refused is no refusal
        await records.refused(_result("a2"), _fields("a2"))
    assert len(audit.log) == 1 and len(store.events) == 1


async def test_events_are_numbered_in_order_within_a_fire() -> None:
    store, audit = Store(), Audit()
    records = FireRecords(RUN_ROW, store, audit)
    await records.admitted(_fields("a1"), _sender([], "a1"))
    await records.answered(_result("a1"))
    await records.admitted(_fields("a2"), _sender([], "a2"))
    await records.answered(_result("a2", "unknown"))
    await records.refused(_refusal("a3"), _fields("a3"))
    await records.answered(_result("a4", "skipped"))
    await records.closed("aborted", 12)
    shown = [(e.seq, e.kind, e.node_ref, e.severity) for e in store.events]
    assert shown == [
        (1, "action_start", "a1", "info"), (2, "action_ok", "a1", "info"),
        (3, "action_start", "a2", "info"), (4, "action_fail", "a2", "error"),
        (5, "action_fail", "a3", "warning"), (6, "action_fail", "a4", "warning"),
    ]  # fmt: skip
    assert store.writes == ["begin", "append", "append", "append", "append", "append", "close"]
    assert store.closes == [(RUN, "aborted", 12)]
    other = Store()
    await FireRecords(RUN_ROW, other, Audit()).refused(_refusal("a1"), _fields("a1"))
    assert [e.seq for e in other.events] == [1]  # each fire numbers its own events from 1
    failing = FireRecords(RUN_ROW, Store(fail="close"), Audit())
    await failing.refused(_refusal("a1"), _fields("a1"))
    with pytest.raises(WriteAheadFailed) as failed:
        await failing.closed("ok", 0)
    assert failed.value.write == "run"
    unwritten = Store()
    await FireRecords(RUN_ROW, unwritten, Audit()).closed("ok", 0)
    assert unwritten.writes == []  # a fire that wrote nothing has no row to close
