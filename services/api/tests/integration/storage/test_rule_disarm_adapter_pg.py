"""Integration (E42-T04 S5, #965): `RuleDisarmAdapter` over `PostgresRuleStore` and `RulesManager`
on real Postgres 16. The unit tests' in-memory store hands the adapter `owner` strings it chose
itself; here they are `rules.owner_user_id::text`, so the owner match and the `armed` mode are
proved against real rows, and a disarm is written through `rule_armed_shape` and read back by a
manager with no chart in memory. Not run on a laptop without docker; exercised by CI `integration`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from candleviewer.rules.manager import Actor, RulesManager
from candleviewer.rules.vocabulary import default_registry
from candleviewer.rules_store_pg import PostgresRuleStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.user_cascade_wiring import RuleDisarmAdapter
from tests.integration.storage import test_rules_migration as _mig
from tests.integration.storage.test_rules_store_pg import _ir, _owner

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # reuse the module-scoped Postgres 16 container fixture


async def _rule(manager: RulesManager, user: str, name: str, *, armed: bool = True) -> str:
    """A rule owned by `user`, simulated on its active version and then, if `armed`, armed."""
    actor = Actor(user, "s1", frozenset({"rules:write"}), is_owner=True)
    rid = str((await manager.create({**_ir("1"), "name": name}, actor))["id"])
    await manager.set_mode(rid, "simulate", actor, f"sim-{name}")
    active = (await manager.get(rid, actor))["active_version_id"]
    await manager.record_simulation(
        rid, next(v["ir_hash"] for v in await manager.versions(rid) if v["id"] == active), 5, 0.0
    )
    if armed:
        await manager.set_mode(rid, "armed", actor, f"arm-{name}")
    return rid


async def test_disarms_owner_user_id_rules_in_postgres(pg_dsn: str) -> None:
    """SR-029, AC1: the armed rules of one `owner_user_id` are listed and disarmed by B9 DISARM
    on charts rebuilt from their rows; another owner's armed rule and the user's own simulating
    rule keep their rows."""
    repo = SqlAlchemyRelationalRepository(pg_dsn, "rule-disarm-it")
    user, other, owner = await _owner(repo), await _owner(repo), await _owner(repo)
    store, tag = PostgresRuleStore(repo), uuid.uuid4().hex[:8]
    writer = RulesManager(store, default_registry())
    mine = [await _rule(writer, user, f"s5-{tag}-a"), await _rule(writer, user, f"s5-{tag}-b")]
    theirs = await _rule(writer, other, f"s5-{tag}-c")
    sim = await _rule(writer, user, f"s5-{tag}-d", armed=False)

    restarted = RulesManager(store, default_registry())  # a new process: no chart in memory
    adapter = RuleDisarmAdapter(store, lambda: restarted)
    assert await adapter.armed_rule_ids(uuid.UUID(user)) == tuple(sorted(mine))
    when = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
    for rid in mine:
        await adapter.disarm(rid, user_id=uuid.UUID(user), actor=uuid.UUID(owner), disabled_at=when)

    again = PostgresRuleStore(repo)  # read back, as any other process would
    for rid, mode, reason in [(r, "disabled", "disarmed") for r in mine] + [
        *((theirs, "armed", None), (sim, "simulate", None)),
    ]:
        row = await again.get(rid)
        assert row is not None and (row.mode, row.disabled_reason) == (mode, reason)
    assert await adapter.armed_rule_ids(uuid.UUID(user)) == ()
    assert await adapter.armed_rule_ids(uuid.UUID(other)) == (theirs,)
