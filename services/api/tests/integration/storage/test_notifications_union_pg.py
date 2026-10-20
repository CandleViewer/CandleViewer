"""Integration: the E40-T04 inbox and `GET /notifications` union on real Postgres 16.

Covers what a fake unit of work cannot: each source's own visibility filter applied in SQL
(own deliveries; readable rules; granted accounts' orders - none at all without `orders:read`;
no `auth` system rows and no other accounts' rows for a non-Owner), one total order across
sources when timestamps tie, keyset paging without gaps or repeats, and the inbox's conditional
updates (idempotent ack, desktop failure + one notice). Not run locally (no docker); exercised
by the integration CI job.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import (
    SqlAlchemyAlertDeliveryRepository,
)
from candleviewer.storage.repositories.notifications import (
    NotificationScope,
    encode_cursor,
)
from candleviewer.storage.repositories.notifications_sqlalchemy import (
    SqlAlchemyNotificationRepository,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage import test_alerts_migration as _mig
from tests.integration.storage.test_oms_core_migration import Conn, _account, _event, _insert
from tests.integration.storage.test_rules_migration import _rule, _version

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # reuse the module-scoped Postgres 16 container fixture

_TS = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)  # every seeded row shares it: ties on purpose


def _owner_of(c: Conn, alert: str) -> str:
    got = c.execute("SELECT owner_user_id::text FROM alerts WHERE id = %s", (alert,)).fetchone()
    assert got is not None
    return str(got[0])


def _delivery(c: Conn, alert: str, user: str, **cols: object) -> int:
    row = {"alert_id": alert, "user_id": user, "channel": "in_app", "status": "sent",
           "title": "t", "queued_at": _TS} | cols  # fmt: skip
    return int(_insert(c, "alert_deliveries", row))


def _rule_events(c: Conn, owner: str, account: str | None) -> tuple[str, list[int]]:
    """A rule of *owner* with one run on *account*: an `action_ok` (served) and a
    `condition_eval` (never served)."""
    rule = _rule(c, owner)
    ver = _version(c, rule, 1, uuid.uuid4().hex * 2)
    run = str(uuid.uuid4())
    c.execute(
        "INSERT INTO rule_runs (id, rule_id, rule_version_id, mode, trigger_reason, "
        "scope_account_id, input_snapshot) VALUES (%s, %s, %s, 'simulate', 'tick', %s, '{}')",
        (run, rule, ver, account),
    )
    ids = []
    for n, kind in enumerate(("action_ok", "condition_eval")):
        event = {"rule_run_id": run, "seq": n, "kind": kind, "event_ts": _TS}
        ids.append(int(_insert(c, "rule_events", event)))
    return rule, ids


def _system(c: Conn, component: str, account: str | None) -> int:
    row: dict[str, object] = {"component": component, "kind": "k", "event_ts": _TS}
    row |= {"message": f"{component} event", "exchange_account_id": account}
    return int(_insert(c, "system_events", row))


@pytest.fixture(scope="module")
def world(pg_dsn: str) -> dict[str, Any]:
    """Two users and two accounts; user A (a Manager) is granted ACC1 only."""
    with _mig._conn(pg_dsn) as c:
        alert_a, alert_b = _mig._alert(c), _mig._alert(c)
        user_a, user_b = _owner_of(c, alert_a), _owner_of(c, alert_b)
        acc1, acc2 = _account(c), _account(c)
        w: dict[str, Any] = {"user_a": user_a, "user_b": user_b, "acc1": acc1, "acc2": acc2,
                             "alert_a": alert_a}  # fmt: skip
        w["d_sent"] = _delivery(c, alert_a, user_a)
        w["d_acked"] = _delivery(c, alert_a, user_a, status="acked", acked_at=_TS)
        w["d_other"] = _delivery(c, alert_b, user_b)
        w["rule_a"], w["re_a"] = _rule_events(c, user_a, acc1)
        w["rule_b"], w["re_b"] = _rule_events(c, user_b, acc1)
        w["oe_acc1"] = int(_event(c, acc1, kind="reject", source="rest", ret_code="10018",
                                  event_ts=_TS))  # fmt: skip
        w["oe_acc1_noise"] = int(_event(c, acc1, kind="submit_attempt", event_ts=_TS))
        w["oe_acc2"] = int(_event(c, acc2, kind="reject", source="rest", event_ts=_TS))
        w["se_auth"] = _system(c, "auth", None)
        w["se_global"] = _system(c, "ingestion", None)
        w["se_acc1"] = _system(c, "exchange", acc1)
        w["se_acc2"] = _system(c, "exchange", acc2)
    w["dsn"] = pg_dsn
    return w


def _union(w: dict[str, Any]) -> SqlAlchemyNotificationRepository:
    """Per test: an async engine belongs to the event loop of the test that first used it."""
    return SqlAlchemyNotificationRepository(SqlAlchemyRelationalRepository(w["dsn"], "n-it"))


def _inbox(w: dict[str, Any]) -> SqlAlchemyAlertDeliveryRepository:
    return SqlAlchemyAlertDeliveryRepository(SqlAlchemyRelationalRepository(w["dsn"], "i-it"))


def _manager(w: dict[str, Any], **over: Any) -> NotificationScope:
    base = NotificationScope(user_id=w["user_a"], alerts=True, rules=True,
                             rule_ids=frozenset({w["rule_a"]}), orders=True,
                             accounts=frozenset({w["acc1"]}), system=True)  # fmt: skip
    return replace(base, **over)  # a slotted dataclass: no __dict__ to splat


async def _all(w: dict[str, Any], scope: NotificationScope, **kw: Any) -> list[tuple[str, int]]:
    rows, _ = await _union(w).list_page(scope, limit=500, **kw)
    return [(r.nkind, r.src_id) for r in rows]


async def test_a_manager_sees_each_source_through_its_own_filter(world: dict[str, Any]) -> None:
    got = set(await _all(world, _manager(world)))
    w = world
    assert {
        ("alert", w["d_sent"]), ("alert", w["d_acked"]), ("rule", w["re_a"][0]),
        ("order", w["oe_acc1"]), ("system", w["se_global"]), ("system", w["se_acc1"]),
    } <= got  # fmt: skip
    assert not got & {
        ("alert", w["d_other"]),  # another user's delivery
        ("rule", w["re_a"][1]),  # condition_eval: never a notification
        ("rule", w["re_b"][0]),  # another user's rule on a granted account
        ("order", w["oe_acc1_noise"]),  # a submit attempt
        ("order", w["oe_acc2"]),  # an account not granted
        ("system", w["se_auth"]), ("system", w["se_acc2"]),
    }  # fmt: skip


async def test_without_orders_read_no_order_event_is_served(world: dict[str, Any]) -> None:
    got = await _all(world, _manager(world, orders=False))
    assert [k for k, _ in got if k == "order"] == []


async def test_the_owner_sees_auth_rows_and_every_account(world: dict[str, Any]) -> None:
    owner = _manager(world, rule_ids=None, accounts=None, system_all=True)
    got = set(await _all(world, owner))
    for row in [("rule", world["re_b"][0]), ("order", world["oe_acc2"]),
                ("system", world["se_auth"]), ("system", world["se_acc2"])]:  # fmt: skip
        assert row in got
    assert ("rule", world["re_a"][1]) not in got  # condition_eval is never a notification
    assert ("order", world["oe_acc1_noise"]) not in got  # nor a submit attempt
    assert ("alert", world["d_other"]) not in got  # another user's deliveries, even for the Owner


async def test_ties_keep_one_total_order_and_pages_neither_skip_nor_repeat(
    world: dict[str, Any],
) -> None:
    scope = _manager(world)
    rows, _ = await _union(world).list_page(scope, limit=500)
    keys = [(r.ts, r.src, r.src_id) for r in rows]
    assert keys == sorted(keys, reverse=True)
    assert len({src for ts, src, _ in keys if ts == _TS}) == 4  # all four sources tie at _TS
    paged: list[tuple[datetime, int, int]] = []
    cursor: str | None = None
    for _ in range(len(keys)):
        page, last = await _union(world).list_page(scope, limit=2, cursor=cursor)
        paged += [(r.ts, r.src, r.src_id) for r in page]
        if last is None:
            break
        cursor = encode_cursor(last)
    assert paged == keys


async def test_unread_only_drops_acked_deliveries(world: dict[str, Any]) -> None:
    got = await _all(world, _manager(world), unread_only=True)
    assert ("alert", world["d_acked"]) not in got and ("alert", world["d_sent"]) in got


async def test_ack_twice_keeps_the_first_acked_at(world: dict[str, Any], pg_dsn: str) -> None:
    with _mig._conn(pg_dsn) as c:
        did = _delivery(c, world["alert_a"], world["user_a"], queued_at=_TS + timedelta(days=1))
    inbox = _inbox(world)
    first = await inbox.ack(did, world["user_a"])
    assert first is not None and first.status == "acked"
    assert await inbox.ack(did, world["user_a"]) is None  # the conditional update loses
    again = await inbox.get(did)
    assert again is not None and again.acked_at == first.acked_at
    assert await inbox.ack(did, world["user_b"]) is None


async def test_desktop_failure_fails_the_row_and_adds_one_notice(
    world: dict[str, Any], pg_dsn: str
) -> None:
    with _mig._conn(pg_dsn) as c:
        did = _delivery(c, world["alert_a"], world["user_a"], channel="desktop", status="queued")
    inbox = _inbox(world)
    got = await inbox.report_desktop(did, error="desktop notification blocked", notice_title="n")
    assert got is not None and got.status == "failed"
    assert await inbox.report_desktop(did, error=None, notice_title="n") is None
    with _mig._conn(pg_dsn) as c:
        notices = c.execute(
            "SELECT count(*) FROM alert_deliveries WHERE context->>'failed_delivery_id' = %s "
            "AND channel = 'in_app' AND status = 'sent'",
            (str(did),),
        ).fetchone()
    assert notices == (1,)


async def test_alert_owner_survives_a_soft_delete(world: dict[str, Any], pg_dsn: str) -> None:
    with _mig._conn(pg_dsn) as c:
        c.execute("UPDATE alerts SET deleted_at = now() WHERE id = %s", (world["alert_a"],))
    assert await _inbox(world).alert_owner(world["alert_a"]) == world["user_a"]
    assert await _inbox(world).alert_owner(str(uuid.uuid4())) is None
