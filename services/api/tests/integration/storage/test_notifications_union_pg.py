"""Integration: the E40-T04 inbox and `GET /notifications` union on real Postgres 16.

Covers what a fake unit of work cannot:

- each source's own visibility filter applied in SQL: the caller's in-app record only (no other
  channel, nothing undelivered, no other user's); readable rules; granted accounts' orders - none
  at all without `orders:read`; `system_events` the Owner's alone (04 §7.2.2 row 34b);
- the process's exchange environment on every account-bound row (C-2.11);
- one total order across sources when timestamps tie, keyset paging without gaps or repeats;
- the inbox's list (one user's rows, keyset pages across a tied `queued_at`, the window and
  filters) and its conditional updates: idempotent ack, a bounded ack-all that returns its ids and
  touches nothing else, the desktop transitions for the owner only, failure + one notice.

Needs docker (testcontainers); in CI it runs in the merge-group integration lane.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
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
_ENV = "demo"  # the process environment the repository reads for


def _owner_of(c: Conn, alert: str) -> str:
    got = c.execute("SELECT owner_user_id::text FROM alerts WHERE id = %s", (alert,)).fetchone()
    assert got is not None
    return str(got[0])


def _live_account(c: Conn) -> str:
    """An account of another exchange environment (`_account` makes `demo` ones)."""
    uid = str(uuid.uuid4().int % 10**15)
    row: dict[str, object] = {"id": str(uuid.uuid4()), "exchange": "bybit", "env": "live"}
    row |= {"kind": "main", "exchange_uid": uid, "label": f"live {uid}"}
    return _insert(c, "exchange_accounts", row)


def _delivery(c: Conn, alert: str, user: str, **cols: object) -> int:
    row: dict[str, object] = {"alert_id": alert, "user_id": user, "channel": "in_app"}
    row |= {"status": "sent", "title": "t", "queued_at": _TS}
    return int(_insert(c, "alert_deliveries", row | cols))


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
    """Two users; `demo` accounts ACC1 and ACC2 and a `live` one. User A (a Manager) is granted
    ACC1 only."""
    with _mig._conn(pg_dsn) as c:
        alert_a, alert_b = _mig._alert(c), _mig._alert(c)
        user_a, user_b = _owner_of(c, alert_a), _owner_of(c, alert_b)
        acc1, acc2, live = _account(c), _account(c), _live_account(c)
        w: dict[str, Any] = {"user_a": user_a, "user_b": user_b, "acc1": acc1, "acc2": acc2,
                             "live": live, "alert_a": alert_a}  # fmt: skip
        # alert: the in-app record (sent, acked, a failure notice) and what is not part of it
        w["d_sent"] = _delivery(c, alert_a, user_a)
        w["d_acked"] = _delivery(c, alert_a, user_a, status="acked", acked_at=_TS)
        notice = json.dumps({"channel_failure": True, "failed_delivery_id": 1})
        w["d_notice"] = _delivery(c, alert_a, user_a, context=notice)
        w["d_in_app_queued"] = _delivery(c, alert_a, user_a, status="queued")
        w["d_storm"] = _delivery(c, alert_a, user_a, status="suppressed")
        w["d_desktop"] = _delivery(c, alert_a, user_a, channel="desktop", status="sent")
        w["d_email_failed"] = _delivery(c, alert_a, user_a, channel="email", status="failed")
        w["d_other"] = _delivery(c, alert_b, user_b)
        # rule: user A's on ACC1, user B's on ACC1, user A's on the live account
        w["rule_a"], w["re_a"] = _rule_events(c, user_a, acc1)
        w["rule_b"], w["re_b"] = _rule_events(c, user_b, acc1)
        w["rule_live"], w["re_live"] = _rule_events(c, user_a, live)
        # order: outcomes on ACC1/ACC2/live, a request (never served), a kill-switch take
        w["oe_acc1"] = int(_event(c, acc1, kind="reject", source="rest", ret_code="10018",
                                  event_ts=_TS))  # fmt: skip
        w["oe_acc1_noise"] = int(_event(c, acc1, kind="submit_attempt", event_ts=_TS))
        w["oe_kill"] = int(_event(c, acc1, kind="kill", source="local", event_ts=_TS))
        w["oe_acc2"] = int(_event(c, acc2, kind="reject", source="rest", event_ts=_TS))
        w["oe_live"] = int(_event(c, live, kind="reject", source="rest", event_ts=_TS))
        # system: auth, unscoped, ACC1, ACC2, live
        w["se_auth"] = _system(c, "auth", None)
        w["se_global"] = _system(c, "ingestion", None)
        w["se_acc1"] = _system(c, "exchange", acc1)
        w["se_acc2"] = _system(c, "exchange", acc2)
        w["se_live"] = _system(c, "exchange", live)
    return w


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    """One engine per test, disposed after it: an async engine belongs to the event loop of the
    test that first used it."""
    repo = SqlAlchemyRelationalRepository(pg_dsn, "n-it")
    yield repo
    await repo.dispose()


@pytest.fixture
def union(rel: SqlAlchemyRelationalRepository) -> SqlAlchemyNotificationRepository:
    return SqlAlchemyNotificationRepository(rel, env=_ENV)


@pytest.fixture
def inbox(rel: SqlAlchemyRelationalRepository) -> SqlAlchemyAlertDeliveryRepository:
    return SqlAlchemyAlertDeliveryRepository(rel)


def _manager(w: dict[str, Any], **over: Any) -> NotificationScope:
    """User A as a Manager: their readable rules (incl. the live one's id: env must drop it)."""
    base = NotificationScope(user_id=w["user_a"], alerts=True, rules=True,
                             rule_ids=frozenset({w["rule_a"], w["rule_live"]}), orders=True,
                             accounts=frozenset({w["acc1"], w["live"]}))  # fmt: skip
    return replace(base, **over)  # a slotted dataclass: no __dict__ to splat


def _owner(w: dict[str, Any]) -> NotificationScope:
    rules = frozenset({w["rule_a"], w["rule_b"], w["rule_live"]})
    return _manager(w, rule_ids=rules, accounts=None, system=True)


Union = SqlAlchemyNotificationRepository


async def _all(union: Union, scope: NotificationScope, **kw: Any) -> set[tuple[str, int]]:
    rows, _ = await union.list_page(scope, limit=500, **kw)
    return {(r.nkind, r.src_id) for r in rows}


async def test_a_manager_sees_each_source_through_its_own_filter(
    world: dict[str, Any], union: Union
) -> None:
    got = await _all(union, _manager(world))
    w = world
    assert {
        ("alert", w["d_sent"]), ("alert", w["d_acked"]), ("alert", w["d_notice"]),
        ("rule", w["re_a"][0]), ("order", w["oe_acc1"]), ("order", w["oe_kill"]),
    } <= got  # fmt: skip
    assert not got & {
        ("alert", w["d_other"]),  # another user's delivery
        ("alert", w["d_in_app_queued"]),  # not delivered yet
        ("alert", w["d_storm"]),  # storm-suppressed: its summary is the record
        ("alert", w["d_desktop"]),  # another channel: the alert centre's, not SCR-014's
        ("alert", w["d_email_failed"]),  # its failure notice is the in-app record
        ("rule", w["re_a"][1]),  # condition_eval: never a notification
        ("rule", w["re_b"][0]),  # another user's rule on a granted account
        ("rule", w["re_live"][0]),  # a run on another environment's account (C-2.11)
        ("order", w["oe_acc1_noise"]),  # a submit attempt
        ("order", w["oe_acc2"]),  # an account not granted
        ("order", w["oe_live"]),  # granted, but another environment's account (C-2.11)
    }  # fmt: skip
    assert not {k for k, _ in got} & {"system"}  # the Owner's alone (04 §7.2.2 row 34b)


async def test_without_orders_read_no_order_event_is_served(
    world: dict[str, Any], union: Union
) -> None:
    got = await _all(union, _manager(world, orders=False))
    assert not {k for k, _ in got} & {"order"}


async def test_the_owner_sees_the_system_stream_and_every_account_of_its_environment(
    world: dict[str, Any], union: Union
) -> None:
    got = await _all(union, _owner(world))
    w = world
    assert {
        ("rule", w["re_b"][0]), ("order", w["oe_acc2"]), ("system", w["se_auth"]),
        ("system", w["se_global"]), ("system", w["se_acc1"]), ("system", w["se_acc2"]),
    } <= got  # fmt: skip
    assert not got & {
        ("rule", w["re_a"][1]),  # condition_eval is never a notification
        ("order", w["oe_acc1_noise"]),  # nor a submit attempt
        ("alert", w["d_other"]),  # another user's deliveries, even for the Owner
        ("order", w["oe_live"]), ("system", w["se_live"]), ("rule", w["re_live"][0]),
    }  # fmt: skip


async def test_ties_keep_one_total_order_and_pages_neither_skip_nor_repeat(
    world: dict[str, Any], union: Union
) -> None:
    scope = _owner(world)
    rows, _ = await union.list_page(scope, limit=500)
    keys = [(r.ts, r.src, r.src_id) for r in rows]
    assert keys == sorted(keys, reverse=True)
    assert len({src for ts, src, _ in keys if ts == _TS}) == 4  # all four sources tie at _TS
    paged: list[tuple[datetime, int, int]] = []
    cursor: str | None = None
    for _ in range(len(keys)):
        page, last = await union.list_page(scope, limit=2, cursor=cursor)
        paged += [(r.ts, r.src, r.src_id) for r in page]
        if last is None:
            break
        cursor = encode_cursor(last)
    assert paged == keys


async def test_unread_only_is_what_can_still_be_acked(world: dict[str, Any], union: Union) -> None:
    got = await _all(union, _manager(world), unread_only=True)
    assert {("alert", world["d_sent"]), ("alert", world["d_notice"])} <= got
    assert ("alert", world["d_acked"]) not in got


async def test_the_inbox_list_is_the_callers_own_paged_and_filtered(
    world: dict[str, Any], pg_dsn: str, inbox: SqlAlchemyAlertDeliveryRepository
) -> None:
    """`GET /alerts/deliveries`' statement on Postgres: one user's rows only, keyset pages
    without gaps or repeats across an equal `queued_at`, `from` inclusive, `to` exclusive."""
    user, at = world["user_a"], _TS - timedelta(days=30)  # before every other row, and now()
    end = at + timedelta(hours=1)
    with _mig._conn(pg_dsn) as c:
        tied = [_delivery(c, world["alert_a"], user, queued_at=at) for _ in range(3)]
        acked = _delivery(c, world["alert_a"], user, queued_at=at - timedelta(seconds=1),
                          status="acked", acked_at=at)  # fmt: skip
        at_end = _delivery(c, world["alert_a"], user, queued_at=end)
        other_alert = _mig._alert(c)
        other_user = _owner_of(c, other_alert)
        other = _delivery(c, other_alert, other_user, queued_at=at)
    window: dict[str, Any] = {"from_ts": at - timedelta(seconds=1), "to_ts": end}
    paged: list[int] = []
    cursor: str | None = None
    for _ in range(5):
        page = await inbox.list_page(user_id=user, limit=2, cursor=cursor, **window)
        paged += [d.id for d in page.items]
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert paged == [*sorted(tied, reverse=True), acked]  # newest first, ties by id
    assert at_end not in paged and other not in paged

    async def ids(**kw: Any) -> list[int]:
        return [d.id for d in (await inbox.list_page(**(window | kw))).items]

    assert await ids(user_id=user, unacked_only=True) == sorted(tied, reverse=True)
    assert await ids(user_id=user, status="acked") == [acked]
    assert await ids(user_id=user, alert_id=other_alert) == []
    assert await ids(user_id=other_user) == [other]


async def test_ack_twice_keeps_the_first_acked_at(
    world: dict[str, Any], pg_dsn: str, inbox: SqlAlchemyAlertDeliveryRepository
) -> None:
    with _mig._conn(pg_dsn) as c:
        did = _delivery(c, world["alert_a"], world["user_a"], queued_at=_TS + timedelta(days=1))
    first = await inbox.ack(did, world["user_a"])
    assert first is not None and first.status == "acked"
    assert await inbox.ack(did, world["user_a"]) is None  # the conditional update loses
    again = await inbox.get(did)
    assert again is not None and again.acked_at == first.acked_at
    assert await inbox.ack(did, world["user_b"]) is None


async def test_ack_all_is_bounded_returns_its_ids_and_touches_nothing_else(
    pg_dsn: str, inbox: SqlAlchemyAlertDeliveryRepository
) -> None:
    with _mig._conn(pg_dsn) as c:
        alert = _mig._alert(c)
        user = _owner_of(c, alert)
        sent = [_delivery(c, alert, user, queued_at=_TS + timedelta(minutes=n)) for n in range(3)]
        queued = _delivery(c, alert, user, status="queued")
        failed = _delivery(c, alert, user, status="failed")
        other_alert = _mig._alert(c)
        other = _delivery(c, other_alert, _owner_of(c, other_alert))
    assert await inbox.unacked_count(user) == 3
    first = await inbox.ack_all(user, cap=2)
    assert sorted(first) == [sent[1], sent[2]]  # the newest `cap`; RETURNING has no order
    assert await inbox.ack_all(user, cap=2) == [sent[0]]
    assert await inbox.ack_all(user, cap=2) == []
    assert await inbox.unacked_count(user) == 0
    with _mig._conn(pg_dsn) as c:
        got = c.execute(
            "SELECT id, status::text FROM alert_deliveries WHERE id = ANY(%s)",
            ([queued, failed, other, *sent],),
        ).fetchall()
    states: dict[int, str] = {int(str(i)): str(st) for i, st in got}
    assert (states[queued], states[failed], states[other]) == ("queued", "failed", "sent")
    assert {states[d] for d in sent} == {"acked"}


async def test_desktop_shown_moves_only_the_owners_queued_row(
    world: dict[str, Any], pg_dsn: str, inbox: SqlAlchemyAlertDeliveryRepository
) -> None:
    with _mig._conn(pg_dsn) as c:
        did = _delivery(c, world["alert_a"], world["user_a"], channel="desktop", status="queued")
    assert await inbox.report_desktop(did, user_id=world["user_b"], error=None,
                                      notice_title="n") is None  # fmt: skip
    got = await inbox.report_desktop(did, user_id=world["user_a"], error=None, notice_title="n")
    assert got is not None and got.status == "sent"
    with _mig._conn(pg_dsn) as c:
        sent_at = c.execute("SELECT sent_at FROM alert_deliveries WHERE id = %s",
                            (did,)).fetchone()  # fmt: skip
    assert sent_at is not None and sent_at[0] is not None


async def test_desktop_failure_fails_the_row_and_adds_one_notice(
    world: dict[str, Any], pg_dsn: str, inbox: SqlAlchemyAlertDeliveryRepository
) -> None:
    with _mig._conn(pg_dsn) as c:
        did = _delivery(c, world["alert_a"], world["user_a"], channel="desktop", status="queued")
    user = world["user_a"]
    got = await inbox.report_desktop(
        did, user_id=user, error="desktop notification blocked", notice_title="n"
    )
    assert got is not None and got.status == "failed"
    assert await inbox.report_desktop(did, user_id=user, error=None, notice_title="n") is None
    with _mig._conn(pg_dsn) as c:
        notices = c.execute(
            "SELECT count(*) FROM alert_deliveries WHERE context->>'failed_delivery_id' = %s "
            "AND channel = 'in_app' AND status = 'sent'",
            (str(did),),
        ).fetchone()
    assert notices == (1,)


async def test_alert_owner_survives_a_soft_delete(
    pg_dsn: str, inbox: SqlAlchemyAlertDeliveryRepository
) -> None:
    with _mig._conn(pg_dsn) as c:
        alert = _mig._alert(c)  # its own alert: the shared world's stay untouched
        owner = _owner_of(c, alert)
        c.execute("UPDATE alerts SET deleted_at = now() WHERE id = %s", (alert,))
    assert await inbox.alert_owner(alert) == owner
    assert await inbox.alert_owner(str(uuid.uuid4())) is None
