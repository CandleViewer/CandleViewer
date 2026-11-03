"""E35-T13 (#5005) slice 4b: the notification and journal ports (24 §11.5 "Notification and
journal"; BQ-8, BQ-9 of #5005).

`send_notification` writes one `rule.notify` outbox row, keyed by the action's fire key, and awaits
no delivery; `log_journal_tag` answers its tag, which the executor writes as a `rule_events` `log`
row in the same write as the action's `action_ok` row. Both run through `EngineRig`; the outbox is
the rig's in-memory writer (Postgres: `tests/integration/storage/test_rule_notify_outbox_pg.py`).
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.rules.executor import control as control_module
from candleviewer.rules.executor.control import (
    JournalTagHandler,
    NotificationHandler,
    NotifyRow,
    render,
)
from candleviewer.rules.executor.keys import dedupe_key
from candleviewer.rules.executor.ports import RunRow
from candleviewer.rules.executor.results import ActionResult
from candleviewer.rules.executor.writeahead import FireRecords
from candleviewer.rules.ir.models import Action, RuleScope
from candleviewer.rules.scope import ScopeInstanceRef
from tests.rules.executor.engine_rig import EngineRig, FakeOutbox, act, engine
from tests.rules.executor.request_builders import Records, action_request
from tests.rules.test_scope_wiring import OWNER
from tests.rules.test_scope_wiring import A as ACCOUNT

__all__ = ["engine"]  # the rig's fixture, used by name

GUARD_S = 5.0
NOTE: dict[str, Any] = {"channel": "ui", "severity": "warning", "template": "Level $level hit"}


def _request(action_type: str, **params: Any) -> Any:
    action = Action.model_validate({"node_id": "n1", "type": action_type, "params": params})
    return action_request(
        RuleScope(level="account"), OWNER, ScopeInstanceRef("*@*", None, None),
        action_type=action_type, payload=action,
    )  # fmt: skip


async def test_send_notification_hands_off_without_awaiting_delivery(engine: EngineRig) -> None:
    """Scenario: The notification and journal ports hand off. `send_notification` writes one
    `rule.notify` row through the outbox, keyed by the action's own fire key, with the rule, its
    version, the run, the node, the channel, the severity and the rendered text, and is `ok`
    while nothing has delivered it."""
    rid = await engine.add(actions=[act("n1", "send_notification", **NOTE, vars={"level": 42})])
    await engine.fire()
    await engine.settle()
    assert engine.results(rid) == [("send_notification", "ok", None)]
    assert not engine.outbox.delivered.is_set()  # no delivery happened, and none was awaited
    (run_id,) = engine.records.runs
    key = dedupe_key(
        rule_id=rid, version=1, scope_instance=f"BTCUSDT@{ACCOUNT}", node_id="n1", run_id=run_id,
        account_id=None,
    )  # fmt: skip
    assert list(engine.outbox.rows) == [key]
    assert dict(engine.outbox.rows[key].payload) == {
        "rule_id": rid, "version": 1, "run_id": str(run_id), "node_id": "n1",
        "channel": "ui", "severity": "warning", "text": "Level 42 hit",
    }  # fmt: skip
    (start,) = [e for _, e in engine.records.events if e.kind == "action_start"]
    assert start.payload["dedupe_key"] == key  # the key the records name


async def test_a_notification_never_waits_for_its_delivery() -> None:
    """The handler's answer comes once the row is written: a delivery that never ends never holds
    it. A repeat of the action's key lands one row, as `ux_outbox_dedup` keeps it."""
    outbox = FakeOutbox()
    handler = NotificationHandler(outbox)
    prepared = handler.prepare(_request("send_notification", **NOTE), None, max_notional_usd=None)
    async with asyncio.timeout(GUARD_S):  # a delivery awaited here would never end
        first = await handler.send(prepared, client_ref="k")
        again = await handler.send(prepared, client_ref="k")
    assert (first.answer, again.answer) == ("done", "done")
    assert (outbox.writes, len(outbox.rows)) == (2, 1) and not outbox.delivered.is_set()


class _StuckOutbox:
    async def enqueue(self, row: NotifyRow) -> None:
        await asyncio.Event().wait()


async def test_a_notification_write_that_does_not_end_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The write's bound (2 s; here 0): no answer, so `unknown` (`timeout`), never re-sent."""
    monkeypatch.setattr(control_module, "NOTIFY_TIMEOUT_S", 0.0)
    handler = NotificationHandler(_StuckOutbox())
    prepared = handler.prepare(_request("send_notification", **NOTE), None, max_notional_usd=None)
    answer = await handler.send(prepared, client_ref="k")
    assert (answer.answer, answer.error_code) == ("no_answer", "timeout")


@pytest.mark.parametrize(
    "params",
    [{**NOTE, "channel": ""}, {**NOTE, "template": 7}, {**NOTE, "vars": [1]},
     {**NOTE, "severity": ""}, {**NOTE, "severity": 3}, {"channel": "ui", "severity": "info"}],
    ids=str,
)  # fmt: skip
async def test_a_mistyped_notification_fails(params: dict[str, Any]) -> None:
    outbox = FakeOutbox()
    handler = NotificationHandler(outbox)
    prepared = handler.prepare(_request("send_notification", **params), None, max_notional_usd=None)
    answer = await handler.send(prepared, client_ref="k")
    assert (answer.answer, answer.error_code, outbox.writes) == ("refused", "invalid_params", 0)


def test_the_template_is_rendered_never_evaluated() -> None:
    """`$name` and `${name}` take their value as text (a number as its plain decimal); any other
    `$` (a `$$` writes one), a brace and an attribute path stay as written."""
    values = {"px": Decimal("65000.50"), "n": 3, "on": True, "who": "A", "f": 0.1}
    assert render("$who at ${px}: $n, $on, $f", values) == "A at 65000.5: 3, true, 0.1"
    kept = "$missing {0.__class__} $$ ${who.upper} 100%"
    assert render(kept, values) == "$missing {0.__class__} $ ${who.upper} 100%"
    assert render("$xs", {"xs": [1, {"b": None}]}) == '[1, {"b": null}]'  # any other value: JSON


async def test_log_journal_tag_emits_the_tag(engine: EngineRig) -> None:
    """Scenario: The notification and journal ports hand off. `log_journal_tag` writes a
    `rule_events` `log` row on the fire's run, its payload the tag and the note, in the same write
    as the action's `action_ok` row, for E41 to read from the run log."""
    rid = await engine.add(actions=[act("j1", "log_journal_tag", tag="breakout", note="first")])
    await engine.fire()
    await engine.settle()
    assert engine.results(rid) == [("log_journal_tag", "ok", None)]
    kinds = [(e.seq, e.kind, e.node_ref) for _, e in engine.records.events]
    assert kinds == [(1, "action_start", "j1"), (2, "action_ok", "j1"), (3, "log", "j1")]
    (log,) = [e for _, e in engine.records.events if e.kind == "log"]
    assert (dict(log.payload), log.severity) == ({"tag": "breakout", "note": "first"}, "info")


async def test_the_tag_rides_the_result_write_and_never_a_failed_one() -> None:
    """The `log` row and the `action_ok` row go in one write; a result other than `ok` carries no
    tag, and a mistyped tag fails (`invalid_params`) with none."""
    records = _Appends()
    handler = JournalTagHandler()
    for params in ({"tag": ""}, {"tag": "t", "note": 7}):
        prepared = handler.prepare(
            _request("log_journal_tag", **params), None, max_notional_usd=None
        )
        answer = await handler.send(prepared, client_ref="k")
        assert (answer.answer, answer.error_code, answer.journal) == (
            "refused",
            "invalid_params",
            None,
        )
    prepared = handler.prepare(_request("log_journal_tag", tag="t"), None, max_notional_usd=None)
    assert (await handler.send(prepared, client_ref="k")).journal == {"tag": "t", "note": None}
    run = RunRow(
        run_id=uuid.UUID(int=8), rule_id="r", version_id="v", mode="armed", trigger_reason="tick",
        account_id=None, symbol=None, matched=True, input_snapshot={},
    )  # fmt: skip
    fire = FireRecords(run, records, records)
    ids: dict[str, Any] = {
        "node_id": "j1", "action_type": "log_journal_tag", "account_id": None,
        "resolved_accounts": (), "dedupe_key": "0" * 64, "duration_us": 0,
    }  # fmt: skip
    await fire.answered(ActionResult(**ids, outcome="failed"), {"tag": "t", "note": None})
    await fire.answered(ActionResult(**ids, outcome="ok"), {"tag": "t", "note": None})
    assert [[e.kind for e in batch] for batch in records.batches] == [["action_ok", "log"]]
    assert [e.kind for _, e in records.events] == ["action_fail", "action_ok", "log"]


class _Appends(Records):
    """`Records`, with each `append` call's events kept as one batch."""

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[Any]] = []

    async def append(self, run_id: uuid.UUID, events: Any) -> None:
        self.batches.append(list(events))
        await super().append(run_id, events)
