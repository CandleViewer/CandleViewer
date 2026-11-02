"""Integration: the executor's records written ahead, on real Postgres 16 (E35-T09 #5000, BQ-3).

No migration: `rule_runs` and `rule_events` (`0013_rules`) carry the write-ahead as they stand. The
run row lands under the fire's own id, with its first event, before the action is handed over, so a
rule-originated group's `origin_rule_run_id` resolves; a repeated run or event write lands once
(`ON CONFLICT ... DO NOTHING`); and the close sets the run's status once. Seeded as
`test_tg_frozen_after_draft_pg.py` seeds its world; `testcontainers` in CI.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.rules.executor.keys import client_ref, dedupe_key
from candleviewer.rules.executor.ports import ActionAuditFields, EventRow, RunRow, input_snapshot
from candleviewer.rules.executor.writeahead import FireRecords
from candleviewer.rules_oms_wiring import RuleRunRecords
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.rules_sqlalchemy import (
    RuleEventInsert,
    SqlAlchemyRulesRepository,
)
from tests.integration import _refused
from tests.integration.storage.test_tg_frozen_after_draft_pg import (
    _RULE_B,
    _USER,
    _VERSION,
    _conn,
    _group,
    _world,
    db,
)

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head
__all__ = ["db", "pg_dsn"]  # fixtures, imported for this module
RUN, ACCOUNT = uuid.UUID("3f1c9e2a-5b7d-4c8e-9a01-2b3c4d5e6f70"), uuid.UUID(int=0xB1)
KEY = dedupe_key(
    rule_id=_RULE_B, version=1, scope_instance=f"BTCUSDT@{ACCOUNT}", node_id="a1", run_id=RUN,
    account_id=ACCOUNT,
)  # fmt: skip


class _Audit:
    def __init__(self) -> None:
        self.log: list[ActionAuditFields] = []

    async def fired(self, fields: ActionAuditFields) -> None:
        self.log.append(fields)

    async def blocked(self, fields: ActionAuditFields) -> None:
        self.log.append(fields)


def _repo(dsn: str) -> SqlAlchemyRulesRepository:
    return SqlAlchemyRulesRepository(SqlAlchemyRelationalRepository(dsn, "rules-write-ahead"))


def _run() -> RunRow:
    return RunRow(
        run_id=RUN, rule_id=str(_RULE_B), version_id=str(_VERSION), mode="armed",
        trigger_reason="bar_close", account_id=ACCOUNT, symbol="BTCUSDT", matched=True,
        input_snapshot=input_snapshot({"rsi": Decimal("71.50"), "armed": True}),
    )  # fmt: skip


def _fields() -> ActionAuditFields:
    return ActionAuditFields(
        rule_id=str(_RULE_B), version=1, ir_hash="ab" * 32, run_id=RUN, node_id="a1",
        action_type="place_order", scope_instance=f"BTCUSDT@{ACCOUNT}", account_id=ACCOUNT,
        owner=_USER, armed_by=str(_USER), dedupe_key=KEY,
    )  # fmt: skip


def _events(dsn: str) -> list[tuple[Any, ...]]:
    with _conn(dsn) as c:
        return c.execute(
            "SELECT seq, kind, node_ref, payload FROM rule_events WHERE rule_run_id = %s "
            "ORDER BY seq",
            (RUN,),
        ).fetchall()


async def test_run_row_is_written_before_any_action_and_groups_can_reference_it(db: str) -> None:
    """24 §9.5 "Rule-originated groups": the group the action's hand-over creates names the run,
    which exists by then, under the action's `client_ref`."""
    with _conn(db) as c:
        _world(c)
    groups: list[uuid.UUID] = []

    async def send() -> None:
        with _conn(db) as c:
            groups.append(_group(
                c, origin="rule", origin_rule_id=_RULE_B, origin_rule_run_id=RUN,
                client_group_ref=client_ref(KEY),
            ))  # fmt: skip

    audit = _Audit()
    await FireRecords(_run(), RuleRunRecords(_repo(db)), audit).admitted(_fields(), send)
    with _conn(db) as c:
        run = c.execute(
            "SELECT status::text, mode::text, trigger_reason, scope_account_id, scope_symbol, "
            "input_snapshot, matched, finished_at FROM rule_runs WHERE id = %s",
            (RUN,),
        ).fetchone()
        (linked,) = c.execute(
            "SELECT origin_rule_run_id FROM trade_groups WHERE id = %s", (groups[0],)
        ).fetchone() or (None,)
    snapshot = {"rsi": "71.5", "armed": True}
    assert run == ("running", "armed", "bar_close", ACCOUNT, "BTCUSDT", snapshot, True, None)
    assert [(seq, kind, node) for seq, kind, node, _ in _events(db)] == [(1, "action_start", "a1")]
    assert linked == RUN and [f.dedupe_key for f in audit.log] == [KEY]


async def test_a_repeated_run_or_event_write_lands_once(db: str) -> None:
    with _conn(db) as c:
        _world(c)
    records = RuleRunRecords(_repo(db))
    first = EventRow(seq=1, kind="action_start", node_ref="a1", payload={"try": 1})
    await records.begin(_run(), first)
    await records.begin(_run(), EventRow(seq=1, kind="action_fail", node_ref="a9", payload={}))
    later = EventRow(seq=2, kind="action_ok", node_ref="a1", payload={"try": 1})
    await records.append(RUN, [later])
    await records.append(RUN, [later, EventRow(seq=2, kind="action_fail", node_ref="a9",
                                               payload={})])  # fmt: skip
    await _repo(db).append_events(str(RUN), [RuleEventInsert(3, "action_start", "a2", {})] * 2)
    with _conn(db) as c:
        (runs,) = c.execute("SELECT count(*) FROM rule_runs WHERE id = %s", (RUN,)).fetchone() or (
            0,
        )
    assert runs == 1
    assert [(seq, kind, node) for seq, kind, node, _ in _events(db)] == [
        (1, "action_start", "a1"), (2, "action_ok", "a1"), (3, "action_start", "a2"),
    ]  # fmt: skip


async def test_close_run_sets_the_status_once(db: str) -> None:
    with _conn(db) as c:
        _world(c)
    repo = _repo(db)
    await RuleRunRecords(repo).begin(
        _run(), EventRow(seq=1, kind="action_start", node_ref="a1", payload={})
    )
    assert await repo.close_run(str(RUN), status="error", duration_ms=12) is True
    assert await repo.close_run(str(RUN), status="ok", duration_ms=99) is False
    with _conn(db) as c:
        row = c.execute(
            "SELECT status::text, duration_ms, finished_at IS NOT NULL FROM rule_runs "
            "WHERE id = %s",
            (RUN,),
        ).fetchone()
    assert row == ("error", 12, True)
