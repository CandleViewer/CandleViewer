"""Integration: the order budget's rebuild reads a rule's counted orders (E35-T10 #5002, BQ-7).

`SqlAlchemyRulesRepository.order_action_ages` is one static, parameterised read over `rule_events`
joined to `rule_runs` (`0013_rules`, no migration), on real Postgres 16 at head: the `action_start`
events of the counted types in the rule's armed runs started within the window, newest first, at
most the limit, each event's age taken from the database's own clock. Seeded as
`test_rule_runs_write_ahead_pg.py` seeds its world; `testcontainers` in CI.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from candleviewer.rules.executor.budget import DAY_S
from candleviewer.rules.executor.handlers import COUNTS_ORDERS
from candleviewer.rules_oms_wiring import RuleBudgetRebuild
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.rules_sqlalchemy import SqlAlchemyRulesRepository
from tests.integration import _refused
from tests.integration.storage.test_tg_frozen_after_draft_pg import (
    _RULE_A,
    _RULE_B,
    _VERSION,
    Conn,
    _conn,
    _world,
    db,
)

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head
__all__ = ["db", "pg_dsn"]  # fixtures, imported for this module
_VERSION_A = uuid.UUID(int=0xC9)
_TYPES = sorted(COUNTS_ORDERS)


def _repo(dsn: str) -> SqlAlchemyRulesRepository:
    return SqlAlchemyRulesRepository(SqlAlchemyRelationalRepository(dsn, "rule-budget"))


def _run(c: Conn, rule: uuid.UUID, version: uuid.UUID, mode: str, started: str) -> uuid.UUID:
    run = uuid.uuid4()
    c.execute(
        "INSERT INTO rule_runs (id, rule_id, rule_version_id, mode, trigger_reason, "
        "input_snapshot, matched, started_at) VALUES (%s, %s, %s, CAST(%s AS rule_mode), "
        "'tick', '{}', true, now() - CAST(%s AS interval))",
        (run, rule, version, mode, started),
    )
    return run


def _event(c: Conn, run: uuid.UUID, seq: int, kind: str, action_type: str, ago: str) -> None:
    payload: dict[str, Any] = {"action_type": action_type, "dedupe_key": "ab" * 32}
    c.execute(
        "INSERT INTO rule_events (rule_run_id, seq, kind, node_ref, payload, event_ts) "
        "VALUES (%s, %s, %s, 'a1', CAST(%s AS jsonb), now() - CAST(%s AS interval))",
        (run, seq, kind, json.dumps(payload), ago),
    )


def _seed(dsn: str) -> None:
    """Rule B's armed run holds the one counted start that counts; everything else is beside it:
    an uncounted type, an outcome event, a simulate run, a run older than 24 h, and rule A's."""
    with _conn(dsn) as c:
        _world(c)
        c.execute(
            "INSERT INTO rule_versions (id, rule_id, version, ir, ir_hash, compiler_version) "
            "VALUES (%s, %s, 1, '{\"conditions\": [], \"actions\": []}', repeat('cd', 32), 'v1')",
            (_VERSION_A, _RULE_A),
        )
        armed = _run(c, _RULE_B, _VERSION, "armed", "10 minutes")
        _event(c, armed, 1, "action_start", "place_order", "90 seconds")
        _event(c, armed, 2, "action_ok", "place_order", "89 seconds")
        _event(c, armed, 3, "action_start", "send_notification", "88 seconds")
        _event(c, armed, 4, "action_start", "modify_stop_loss", "87 seconds")
        simulate = _run(c, _RULE_B, _VERSION, "simulate", "10 minutes")
        _event(c, simulate, 1, "action_start", "place_order", "80 seconds")
        stale = _run(c, _RULE_B, _VERSION, "armed", "25 hours")
        _event(c, stale, 1, "action_start", "place_order", "25 hours")
        other = _run(c, _RULE_A, _VERSION_A, "armed", "10 minutes")
        _event(c, other, 1, "action_start", "place_order", "70 seconds")


async def test_the_rebuild_reads_a_rules_counted_action_starts_of_the_last_24_hours(
    db: str,
) -> None:
    _seed(db)
    ages = await _repo(db).order_action_ages(str(_RULE_B), _TYPES, since_s=DAY_S, limit=200)
    assert len(ages) == 1
    with _conn(db) as c:  # a second counted start, newer: newest first, and the limit holds
        (run,) = c.execute(
            "SELECT id FROM rule_runs WHERE rule_id = %s AND mode = 'armed' AND "
            "started_at > now() - interval '1 hour'",
            (_RULE_B,),
        ).fetchone() or (None,)
        _event(c, run, 5, "action_start", "scale_out", "30 seconds")
    newest = await _repo(db).order_action_ages(str(_RULE_B), _TYPES, since_s=DAY_S, limit=200)
    assert len(newest) == 2 and newest[0] < newest[1]
    assert len(await _repo(db).order_action_ages(str(_RULE_B), _TYPES, since_s=DAY_S, limit=1)) == 1
    adapter = RuleBudgetRebuild(_repo(db))
    assert len(await adapter.order_ages(str(_RULE_B), limit=200)) == 2


async def test_the_rebuild_ages_come_from_the_database_clock(db: str) -> None:
    """Each age is `now() - event_ts` on the database's clock, never the app's wall clock, so a
    skew between the two never shifts a window."""
    _seed(db)
    (age,) = await _repo(db).order_action_ages(str(_RULE_B), _TYPES, since_s=DAY_S, limit=200)
    assert 89.0 <= age <= 120.0  # 90 s before the database's now, read moments later
