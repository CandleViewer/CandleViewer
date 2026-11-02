"""Integration: a rule-originated submit on real Postgres 16 (E35-T11 slice 3a; 24 Sec.8.4
"Rule-originated orders"; 21 Sec.3.3.4 "Origin"; the E35 threat model's RE-D6).

The pipeline runs over the real B1 facade, its step writer and the command port, every store a
Postgres adapter as production sets it up (C6's database, `test_submission_pipeline_pg.py`, shared
by import), with a demo `FakeTradingPort` as the exchange (C-13.5: no venue is reached; nothing
here is a recording). A rule's entry persists its order's origin columns, its group as the rule's
(`abort_on_first`, naming the rule and the fire's run, both rows real) and its records as the
rule's, its native stop at every layer; and a create a restart resumes, which has no request,
rides `entry` from its row's origin.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.oms.ports import KeyedRecord, RequestRecord, RuleOrigin, SubmitActor
from candleviewer.oms.submit import SubmitContext
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.oms.test_submission_pipeline_pg import (
    _RESUME_BOUND_S,
    Rig,
    _orders,
    _restart,
    _sql,
    pg,
    pg_dsn,
    rel,
)
from tests.rules.executor.native_sl import assert_entry_carries_native_stop
from tests.unit.oms.submit_rig import REFERENCE

pytestmark = pytest.mark.integration
__all__ = ["pg", "pg_dsn", "rel"]  # C6's database, its pool and its pipeline, for this module


@dataclass(frozen=True)
class _Entry:
    """An `orders` row as the native-SL helper reads it."""

    id: uuid.UUID
    order_link_id: str
    side: str
    reduce_only: bool
    stop_loss: Decimal | None


@dataclass(frozen=True)
class _Stop:
    """A `recorded_stops` row as the native-SL helper reads it."""

    id: uuid.UUID
    kind: str
    source: str
    order_id: uuid.UUID | None
    trigger_price: Decimal


def _rule(dsn: str, owner: uuid.UUID) -> RuleOrigin:
    """A rule of `owner`, its first version and an armed fire's run, as the group's FKs need
    them (`origin_rule_id`, `origin_rule_run_id`, 21 Sec.3.3.2), and the origin naming them."""
    rule, version, run = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO rules (id, name, owner_user_id) VALUES (%s, %s, %s)",
        rule,
        str(rule),
        owner,
    )
    _sql(
        dsn,
        "INSERT INTO rule_versions (id, rule_id, version, ir, ir_hash, compiler_version) "
        "VALUES (%s, %s, 1, '{\"conditions\": [], \"actions\": []}', repeat('ab', 32), 'v1')",
        version, rule,
    )  # fmt: skip
    _sql(
        dsn,
        "INSERT INTO rule_runs (id, rule_id, rule_version_id, mode, trigger_reason, "
        "input_snapshot) VALUES (%s, %s, %s, 'armed', 'tick', '{}')",
        run, rule, version,
    )  # fmt: skip
    return RuleOrigin(
        rule_id=rule, version=1, run_id=run, node_id="a1", armed_by=owner, armed_by_role="owner"
    )


def _rule_context(rig: Rig, origin: RuleOrigin) -> SubmitContext:
    """The composition root's context for a rule action: the owner with no session, the fire's
    key, no correlation id, and the origin."""
    owner = SubmitActor(user_id=rig.user, role="owner")
    return SubmitContext(owner, uuid.uuid4(), "c0ffee" + "ab" * 29, None, origin=origin)


def _entry_row(dsn: str, order_id: uuid.UUID) -> tuple[_Entry, str | None, str | None]:
    [(oid, link, side, reduce_only, stop, origin, ref)] = _sql(
        dsn,
        "SELECT id, order_link_id, side, reduce_only, stop_loss, origin, origin_ref FROM orders "
        "WHERE id = %s",
        order_id,
    )
    return _Entry(oid, link, side, reduce_only, stop), origin, ref


def _stops(dsn: str, order_id: uuid.UUID) -> list[_Stop]:
    rows = _sql(
        dsn,
        "SELECT id, kind::text, source::text, order_id, trigger_price FROM recorded_stops "
        "WHERE order_id = %s",
        order_id,
    )
    return [_Stop(*row) for row in rows]


async def test_a_rule_origin_entry_persists_its_columns_group_and_records_on_postgres(
    pg: Rig, pg_dsn: str
) -> None:
    """24 Sec.8.4 items 1 to 4 on the stores: the row is `origin = 'rule'` with the rule's id,
    which `ord_origin_ref` admits; the group is the rule's, `abort_on_first`, its rule and run
    real rows; each record the request writes ahead carries the origin; the create rides `entry`;
    and the entry carries its native stop at every layer (C-2.6)."""
    origin = _rule(pg_dsn, pg.user)
    context = _rule_context(pg, origin)
    outcome = await pg.submit(pg.entry(), context)
    assert (outcome.status, outcome.lifecycle) == (202, "submitted")
    assert outcome.order_id is not None and outcome.trade_group_id is not None
    entry, kept, ref = _entry_row(pg_dsn, outcome.order_id)
    assert (kept, ref) == ("rule", str(origin.rule_id))
    [group] = _sql(
        pg_dsn,
        "SELECT origin::text, origin_rule_id, origin_rule_run_id, leg_failure_policy::text, "
        "client_group_ref FROM trade_groups WHERE id = %s",
        outcome.trade_group_id,
    )
    assert group == (
        "rule",
        origin.rule_id,
        origin.run_id,
        "abort_on_first",
        str(context.client_ref),
    )
    written = [r for r in pg.audits.of(None) if isinstance(r, RequestRecord | KeyedRecord)]
    actions = {"orders.submit", "trade_group.submit", "sl.attached"}
    ours = [r for r in written if r.action in actions]
    assert {r.action for r in ours} == actions and all(r.origin == origin for r in ours)
    assert [c.lane for c in pg.demo.calls if c.method == "place_order"] == ["entry"]
    assert_entry_carries_native_stop(
        entry, reference_price=REFERENCE, stops=_stops(pg_dsn, outcome.order_id),
        records=[r for r, _ in pg.audits.written], calls=pg.demo.calls,
    )  # fmt: skip


async def test_a_resumed_rule_create_rides_entry_from_its_row_on_postgres(
    pg: Rig, rel: SqlAlchemyRelationalRepository, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The restart case of 24 Sec.8.4 item 3 for a create: a rule's entry persisted before its
    first send, which never left (the process went down with the create at the venue's door), is
    hydrated `submitting` by the next process; its create resumes with no request, reads the row,
    and leaves once, in `entry`, from the row's `origin` (RE-D6)."""
    origin = _rule(pg_dsn, pg.user)
    entered, door, land = asyncio.Event(), asyncio.Event(), pg.demo.place_order

    async def at_the_door(create: PlaceOrderRequest) -> Any:
        entered.set()
        await door.wait()  # never opened: this process goes down first
        return await land(create)

    monkeypatch.setattr(pg.demo, "place_order", at_the_door)
    task = asyncio.create_task(pg.submit(pg.entry(), _rule_context(pg, origin)))
    await entered.wait()
    task.cancel()  # the process goes down: the request first, then its facade
    await asyncio.gather(task, return_exceptions=True)
    [(order_id, link, state)] = _orders(pg_dsn, pg.account)
    assert state == "submitting"
    again = await _restart(pg, rel)
    monkeypatch.setattr(pg.demo, "place_order", land)
    try:
        hydrated = await again.machines.hydrate(again.account, order_id, environment="demo")
        assert hydrated == "submitting"
        left = await again.machines.settled(
            again.account, order_id, leaving="submitting", timeout_s=_RESUME_BOUND_S
        )
        assert left == "submitted"
        await again.settle()
        [create] = again.creates()
        assert (create.order_link_id, create.lane) == (link, "entry")
        assert [c.lane for c in again.demo.calls if c.method == "place_order"] == ["entry"]
        assert _entry_row(pg_dsn, order_id)[1:] == ("rule", str(origin.rule_id))
    finally:
        await again.machines.stop()
