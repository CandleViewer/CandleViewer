"""E35-T09 (#5000) part 1 of `rules_oms_wiring`: the executor's write-ahead adapters.

`RuleActionAudit` writes `rules.fired` and `rules.blocked` keyed by the fire key, naming the rule as
the actor and both users, never a parameter's value, a figure or a credential (24 §15.5, BQ-11).
`RuleRunRecords` writes the run row with its first event in one unit of work, appends events and
closes the row through the real `SqlAlchemyRulesRepository`, over a fake relational store that
logs each statement: the input snapshot goes in as JSON text, decimals as their plain text, and
is never logged, nor carried by an error.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import fields
from decimal import Decimal
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.redact import redact
from candleviewer.rules.executor.ports import (
    ActionAuditFields,
    EventRow,
    RunRow,
    audit_fields,
    input_snapshot,
)
from candleviewer.rules.ir.models import Action, RuleScope
from candleviewer.rules.scope import ScopeInstanceRef
from candleviewer.rules_oms_wiring import RuleActionAudit, RuleRunRecords, rule_action_records
from candleviewer.storage.repositories.rules_sqlalchemy import SqlAlchemyRulesRepository
from tests.rules.executor.request_builders import action_request

RULE, OWNER, ARMER = str(uuid.UUID(int=7)), uuid.UUID(int=0xA1), str(uuid.UUID(int=0xA2))
ACCOUNT, RUN = uuid.UUID(int=0xB1), uuid.UUID(int=8)
#: Planted where a careless record would copy it: a figure, a credential, a free-text value.
PLANTED = ("64123.75", "sk-live-planted", "planted note")


class _UnitOfWork:
    def __init__(self, store: _Relational) -> None:
        self.session, self.committed = self, False
        self._store = store

    async def execute(self, statement: Any, params: Any = None) -> Any:
        self._store.statements.append((" ".join(str(statement).split()), params))
        if self._store.fail:
            raise RuntimeError(f"refused: {self._store.fail}")
        return type("Result", (), {"rowcount": self._store.rowcount})()

    async def commit(self) -> None:
        self.committed = True


class _Relational:
    """`SqlAlchemyRelationalRepository`: each unit of work logs its statements and commit."""

    def __init__(self, *, fail: str | None = None, rowcount: int = 1) -> None:
        self.fail, self.rowcount = fail, rowcount
        self.statements: list[tuple[str, Any]] = []
        self.units: list[_UnitOfWork] = []

    @contextlib.asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[_UnitOfWork]:
        unit = _UnitOfWork(self)
        self.units.append(unit)
        yield unit


class _Emitter:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    async def emit_keyed(self, action: str, name: str, **kw: Any) -> None:
        self.records.append((action, name, kw))


def _fields(**over: Any) -> ActionAuditFields:
    base: dict[str, Any] = {
        "rule_id": RULE, "version": 3, "ir_hash": "ab" * 32, "run_id": RUN, "node_id": "a2",
        "action_type": "place_order", "scope_instance": f"BTCUSDT@{ACCOUNT}",
        "account_id": ACCOUNT, "owner": OWNER, "armed_by": ARMER, "dedupe_key": "cd" * 32,
    }  # fmt: skip
    return ActionAuditFields(**(base | over))


def _run(snapshot: dict[str, Any]) -> RunRow:
    return RunRow(
        run_id=RUN, rule_id=RULE, version_id=str(uuid.UUID(int=0xC0)), mode="armed",
        trigger_reason="bar_close", account_id=ACCOUNT, symbol="BTCUSDT", matched=True,
        input_snapshot=input_snapshot(snapshot),
    )  # fmt: skip


async def test_rule_action_records_name_the_rule_as_actor_and_both_users() -> None:
    """BQ-11: the actor is `rule:<rule_id>@v<n>`, with no user id and no request id (a fire is
    no request); `after_state` names both users, both roles `None` until E35-T10, and §15.5's ids,
    under names the writer's redactor keeps (`ir_sha256`, `dedupe_sha256`)."""
    emitter = _Emitter()
    audit = RuleActionAudit(emitter)
    await audit.fired(_fields())
    await audit.blocked(_fields(blocked_by="scope", account_id=None))
    (fired, key, entry), (blocked, again, refusal) = emitter.records
    assert (fired, blocked, key, again) == ("rules.fired", "rules.blocked", "cd" * 32, "cd" * 32)
    for kw in (entry, refusal):
        assert kw["actor_label"] == f"rule:{RULE}@v3" and kw["actor_user_id"] is None
        assert (kw["object_kind"], kw["object_id"], kw["request_id"]) == ("rule", RULE, None)
        assert redact(kw["after_state"]) == kw["after_state"]
    assert (entry["outcome"], entry["severity"], entry["reason"]) == (
        "success", "info", None,
    )  # fmt: skip
    assert (refusal["outcome"], refusal["severity"], refusal["reason"]) == (
        "denied", "warning", "scope",
    )  # fmt: skip
    assert entry["after_state"] == {
        "actor_type": "rule", "rule_id": RULE, "version": 3, "ir_sha256": "ab" * 32,
        "run_id": str(RUN), "node_id": "a2", "action_type": "place_order",
        "scope_instance": f"BTCUSDT@{ACCOUNT}", "account_id": str(ACCOUNT),
        "owner_user_id": str(OWNER), "owner_role": None, "armed_by_user_id": ARMER,
        "armed_by_role": None, "dedupe_sha256": "cd" * 32,
    }  # fmt: skip
    assert refusal["after_state"] == entry["after_state"] | {
        "account_id": None, "blocked_by": "scope",
    }  # fmt: skip
    with pytest.raises(ValueError):  # a refusal names its reason; an admitted action none
        await audit.blocked(_fields())
    with pytest.raises(ValueError):
        await audit.fired(_fields(blocked_by="cap"))
    assert len(emitter.records) == 2


async def test_rule_action_records_never_carry_a_parameter_value_a_figure_or_a_credential() -> None:
    params = {"qty": PLANTED[0], "api_key": PLANTED[1], "note": PLANTED[2]}
    scope = RuleScope.model_validate({"level": "account", "account_ids": [str(ACCOUNT)]})
    instance = ScopeInstanceRef(f"BTCUSDT@{ACCOUNT}", "BTCUSDT", ACCOUNT)
    action = Action(node_id="a2", type="place_order", params=params)
    req = action_request(scope, OWNER, instance, action_type="place_order", payload=action)
    emitter = _Emitter()
    audit = RuleActionAudit(emitter)
    await audit.fired(audit_fields(req, account_id=ACCOUNT, dedupe_key="ef" * 32))
    await audit.blocked(
        audit_fields(req, account_id=ACCOUNT, dedupe_key="ef" * 32, blocked_by="cap")
    )
    shown = repr(emitter.records)
    assert not [value for value in PLANTED if value in shown]
    assert {f.name for f in fields(ActionAuditFields)} == {
        "rule_id", "version", "ir_hash", "run_id", "node_id", "action_type", "scope_instance",
        "account_id", "owner", "armed_by", "dedupe_key", "blocked_by",
    }  # fmt: skip


async def test_the_input_snapshot_is_stored_with_decimals_as_text_and_never_logged() -> None:
    snapshot = {"close": Decimal("64123.750"), "rsi": Decimal("1E+1"), "armed": True,
                "label": PLANTED[2], "missing": None}  # fmt: skip
    run = _run(snapshot)
    assert not [value for value in ("64123.75", PLANTED[2]) if value in repr(run)]
    first = EventRow(seq=1, kind="action_start", node_ref="a1", payload={"action_type": "x"})
    store = _Relational()
    records, audit = rule_action_records(SqlAlchemyRulesRepository(cast(Any, store)), _Emitter())
    assert isinstance(records, RuleRunRecords) and isinstance(audit, RuleActionAudit)
    with capture_logs() as logs:
        await records.begin(run, first)
        await records.append(RUN, [first, EventRow(seq=2, kind="action_ok", node_ref="a1",
                                                   payload={}, severity="info")])  # fmt: skip
        await records.close(RUN, "ok", 41)
        failing = RuleRunRecords(SqlAlchemyRulesRepository(cast(Any, _Relational(fail="db"))))
        with pytest.raises(RuntimeError) as refused:
            await failing.begin(run, first)
    assert not [v for v in ("64123.75", PLANTED[2]) if v in repr(logs) + str(refused.value)]
    (insert_run, run_params), (insert_event, event_params) = store.statements[:2]
    assert "ON CONFLICT (id) DO NOTHING" in insert_run and "scope_account_id" in insert_run
    assert (run_params["id"], run_params["account_id"]) == (str(RUN), str(ACCOUNT))
    assert (run_params["trigger"], run_params["status"], run_params["mode"]) == (
        "bar_close", "running", "armed",
    )  # fmt: skip
    assert json.loads(run_params["snapshot"]) == {
        "close": "64123.75", "rsi": "10", "armed": True, "label": PLANTED[2], "missing": None,
    }  # fmt: skip
    assert "ON CONFLICT (rule_run_id, seq) DO NOTHING" in insert_event
    assert [(p["run_id"], p["seq"], p["kind"]) for p in event_params] == [
        (str(RUN), 1, "action_start"),
    ]
    assert len(store.units) == 3 and all(unit.committed for unit in store.units)
    assert [p["seq"] for p in store.statements[2][1]] == [1, 2]
    close, close_params = store.statements[3]
    assert close.startswith("UPDATE rule_runs SET status") and "status = 'running'" in close
    assert (close_params["id"], close_params["status"], close_params["duration_ms"]) == (
        str(RUN), "ok", 41,
    )  # fmt: skip


async def test_the_repository_serves_a_caller_that_names_no_run_as_before() -> None:
    """A caller that passes no id (no write-ahead) is served as today: a minted id, no conflict
    clause, no event; a run not persisted writes nothing; a close that finds no running row
    reports it."""
    store = _Relational(rowcount=0)
    repo = SqlAlchemyRulesRepository(cast(Any, store))
    common: dict[str, Any] = {
        "rule_id": RULE, "version_id": str(uuid.UUID(int=0xC0)), "mode": "simulate",
        "trigger_reason": "tick", "input_snapshot": {}, "status": "ok",
    }  # fmt: skip
    minted = await repo.record_run(**common, matched=True)
    assert minted is not None and uuid.UUID(minted).version == 4 and minted != str(RUN)
    ((statement, params),) = store.statements
    assert "ON CONFLICT" not in statement and params["account_id"] is None
    assert await repo.record_run(**common, matched=False) is None
    assert len(store.statements) == 1
    assert await repo.close_run(str(RUN), status="ok", duration_ms=0) is False
    await repo.append_events(str(RUN), [])
    assert len(store.statements) == 2
    with pytest.raises(RuntimeError):  # a write-ahead row the repository would not persist
        await RuleRunRecords(repo).begin(
            _unpersisted(), EventRow(seq=1, kind="action_start", node_ref="a1", payload={})
        )


def _unpersisted() -> RunRow:
    run = _run({})
    return RunRow(
        run_id=run.run_id, rule_id=run.rule_id, version_id=run.version_id, mode="simulate",
        trigger_reason=run.trigger_reason, account_id=None, symbol=None, matched=False,
        input_snapshot=run.input_snapshot,
    )  # fmt: skip
