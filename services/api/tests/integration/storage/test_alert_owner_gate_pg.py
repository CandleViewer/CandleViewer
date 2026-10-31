"""Integration (#3349, E42-X01 UL-F8, residual O7) on real Postgres 16: the identity read path of
the owner gate agrees with the permission readers, and the regression test of the bug. The Owner
disables a user through the lifecycle store and the user's due alert neither fires nor delivers;
enabling the user again restores it. Not run locally without docker; exercised by CI `integration`.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa

from candleviewer.alerts.dispatcher import AlertDispatcher, default_adapters
from candleviewer.alerts.evaluator import AlertEvaluator, AlertMetrics, AlertTick
from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key
from candleviewer.alerts.owners import OwnerGate
from candleviewer.auth.owner_floor import assert_owner_floor
from candleviewer.storage.repositories.alert_dispatch_sqlalchemy import (
    SqlAlchemyAlertDispatchStore,
)
from candleviewer.storage.repositories.alert_firing_sqlalchemy import SqlAlchemyAlertFiringStore
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_lifecycle import UserPatch
from candleviewer.storage.repositories.user_lifecycle_sqlalchemy import (
    SqlAlchemyUserLifecycleStore,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserAdminStore
from tests.alerts._evaluator_env import COMPILER, T0, Metrics, Source, ir
from tests.alerts._owners_env import Time
from tests.integration.storage import test_alerts_migration as _mig
from tests.integration.storage import test_rule_perms_status_pg as _perms

pytestmark = pytest.mark.integration
pg_dsn, db = _perms.pg_dsn, _perms.db  # the module-scoped Postgres 16, one active owner standing


def _floor(current: frozenset[str], new: frozenset[str], owners: int) -> None:
    assert_owner_floor(current_roles=current, new_roles=new, active_owner_count=owners)


async def _noop(_change: Any) -> None:
    """A write-ahead audit hook that records nothing: C-2.9 is not what this test is about."""


class Relay:
    """The E04 relay: the idempotency key of each message handed to it."""

    def __init__(self) -> None:
        self.keys: list[str] = []

    async def send(self, *, user_id: str, subject: str, body: str, idempotency_key: str) -> None:
        self.keys.append(idempotency_key)


def _alert_state(dsn: str, alert: str) -> tuple[list[tuple[str, str, str | None]], int]:
    """The alert's deliveries (channel, status, reason) and its `fire_count`."""
    sql = "SELECT channel::text, status::text, error_message FROM alert_deliveries "
    with _mig._conn(dsn) as c:
        rows = c.execute(sql + "WHERE alert_id = %s ORDER BY id", (alert,)).fetchall()
        count = c.execute("SELECT fire_count FROM alerts WHERE id = %s", (alert,)).fetchone()
    assert count is not None
    why = [None if r[2] is None else str(r[2]) for r in rows]
    return [(str(r[0]), str(r[1]), w) for r, w in zip(rows, why, strict=True)], int(str(count[0]))


@pytest.mark.parametrize("change", list(_perms._CHANGES))
async def test_active_users_agrees_with_the_permission_readers(
    pg_dsn: str, db: Any, change: str
) -> None:
    engine, readers = db
    rel = SqlAlchemyRelationalRepository(pg_dsn, "owner-gate-it")
    try:
        user = await _perms._user(engine, "manager")
        ids = [str(user), str(uuid.uuid4())]  # and an id no user row has
        directory = SqlAlchemyIdentityProvider(rel)
        assert await directory.active_users(ids) == {str(user)}
        assert await readers["session_info"](user)
        async with engine.begin() as conn:
            await conn.execute(sa.text(_perms._CHANGES[change]), {"id": str(user)})
        assert await directory.active_users(ids) == frozenset()
        assert await readers["session_info"](user) == frozenset()
    finally:
        await rel.dispose()


@pytest.mark.usefixtures("db")  # the owner floor wants one active owner on every status write
async def test_disabled_owner_alert_neither_fires_nor_delivers_and_a_reenable_restores_it(
    pg_dsn: str,
) -> None:
    """Before the fix a disabled user's due alert committed a firing and the dispatcher sent its
    deliveries. Now neither happens and the alert row is left as it was, so the Owner enabling the
    user again is all it takes for the alert to fire and deliver."""
    cond = ir()
    with _mig._conn(pg_dsn) as c:
        alert = _mig._alert(
            c, condition_ir=json.dumps(cond), condition_hash=COMPILER.compile(cond).condition_hash,
            trigger_mode="every_time", cooldown_seconds=0, symbol="BTCUSDT",
            channels="{in_app,email}",
        )  # fmt: skip
        owned = c.execute("SELECT owner_user_id FROM alerts WHERE id = %s", (alert,)).fetchone()
    assert owned is not None
    owner = uuid.UUID(str(owned[0]))
    rel = SqlAlchemyRelationalRepository(pg_dsn, "owner-gate-it")
    try:
        cache_clock, relay, m, src = Time(), Relay(), Metrics(), Source()
        directory = SqlAlchemyIdentityProvider(rel)
        firing = SqlAlchemyAlertFiringStore(
            rel, topic=TOPIC_ALERT_DELIVER, dedup_key=alert_deliver_dedup_key
        )
        ev = AlertEvaluator(firing, src, owners=OwnerGate(directory, clock=cache_clock),
                            metrics=AlertMetrics(m), clock=lambda: T0)  # fmt: skip
        disp = AlertDispatcher(SqlAlchemyAlertDispatchStore(rel), default_adapters(relay),
                               worker="owner-gate-it", now=lambda: datetime.now(UTC),
                               owners=OwnerGate(directory), metric=m)  # fmt: skip
        await ev.warm_up()
        src.set("price", 65500, T0)
        tick = AlertTick("on_price_update", T0, "BTCUSDT")

        await ev.process(tick)  # the owner is active: a firing, two queued deliveries
        queued = [("in_app", "queued", None), ("email", "queued", None)]
        assert _alert_state(pg_dsn, alert) == (queued, 1)

        lifecycle = SqlAlchemyUserLifecycleStore(rel, owner_floor=_floor)
        acting = uuid.UUID(_perms._BASELINE)  # #2593: the actor must be an active owner
        await lifecycle.disable(owner, actor=acting, now=datetime.now(UTC), audit=_noop)
        cache_clock.now += 2  # past the evaluator's cache of the owner's status
        await ev.process(tick)  # due again, and the owner is disabled
        assert _alert_state(pg_dsn, alert) == (queued, 1)  # no firing, the alert row untouched

        await disp.run_once()  # the deliveries queued before the disable: dropped, on no channel
        gone = "owner_inactive"
        dropped = [("in_app", "suppressed", gone), ("email", "suppressed", gone)]
        assert _alert_state(pg_dsn, alert) == (dropped, 1) and relay.keys == []

        admin = SqlAlchemyUserAdminStore(rel, owner_floor=_floor)
        await admin.update_user(owner, UserPatch(enable=True), actor=acting,
                                check=lambda _user: None, audit=_noop)  # fmt: skip
        cache_clock.now += 2
        await ev.process(tick)
        await disp.run_once()
        sent = [("in_app", "sent", None), ("email", "sent", None)]
        assert _alert_state(pg_dsn, alert) == ([*dropped, *sent], 2) and len(relay.keys) == 1
    finally:
        await rel.dispose()
