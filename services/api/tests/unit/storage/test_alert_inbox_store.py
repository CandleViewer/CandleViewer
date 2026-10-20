"""E40-T04 PR-A storage with a fake UoW: the inbox additions to the deliveries repository
(`get`, `alert_owner`, `report_desktop`) and the `GET /notifications` union.

Real-DB behaviour (the union on Postgres, per-source scoping, keyset ties) is covered by
`tests/integration/storage/test_notifications_union_pg.py` in the integration CI job.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from test_alert_dispatch_store import _row
from test_alerts_repository_sqlalchemy import _Rel, _Result

from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import (
    SqlAlchemyAlertDeliveryRepository,
)
from candleviewer.storage.repositories.notifications import (
    ORDER_EVENT_KINDS,
    RULE_EVENT_KINDS,
    NotificationRow,
    NotificationScope,
    decode_cursor,
    encode_cursor,
)
from candleviewer.storage.repositories.notifications_sqlalchemy import (
    SqlAlchemyNotificationRepository,
)

_T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def _deliveries(*results: _Result) -> tuple[SqlAlchemyAlertDeliveryRepository, _Rel]:
    rel = _Rel(*results)
    return SqlAlchemyAlertDeliveryRepository(rel), rel  # type: ignore[arg-type]  # structural fake


def _union(*results: _Result) -> tuple[SqlAlchemyNotificationRepository, _Rel]:
    rel = _Rel(*results)
    return SqlAlchemyNotificationRepository(rel), rel  # type: ignore[arg-type]  # structural fake


def _nrow(src_id: int, **over: Any) -> dict[str, Any]:
    return {
        "nkind": "alert", "src": 1, "src_id": src_id, "ts": _T0, "severity": "info",
        "title": "t", "body": None, "read_at": None, "symbol": None, "account_id": None,
        "source_uuid": None, "event": "in_app", "code": None,
    } | over  # fmt: skip


# --- deliveries repository ---------------------------------------------------------------


async def test_get_is_unscoped_and_maps_the_row() -> None:
    repo, rel = _deliveries(_Result([_row(user_id="u2")]), _Result([]))
    got = await repo.get(7)
    assert got is not None and got.user_id == "u2"
    assert "user_id = CAST" not in rel.calls[0][0] and rel.calls[0][1] == {"id": 7}
    assert await repo.get(8) is None


async def test_alert_owner_includes_deleted_alerts() -> None:
    repo, rel = _deliveries(_Result([("u1",)]), _Result([]))
    assert await repo.alert_owner("a1") == "u1"
    assert "deleted_at" not in rel.calls[0][0] and rel.calls[0][1] == {"id": "a1"}
    assert await repo.alert_owner("a2") is None


async def test_report_desktop_shown_is_a_conditional_queued_to_sent() -> None:
    repo, rel = _deliveries(_Result([_row(channel="desktop", status="sent")]))
    got = await repo.report_desktop(7, error=None, notice_title="n")
    assert got is not None and got.status == "sent"
    ((sql, p),) = rel.calls
    assert "channel = 'desktop' AND status = 'queued'" in sql and p == {"id": 7}
    assert rel.commits == 1


async def test_report_desktop_failure_writes_the_notice_in_the_same_transaction() -> None:
    failed = _row(channel="desktop", status="failed", alert_id="a", user_id="u1")
    repo, rel = _deliveries(_Result([failed]), _Result([]))
    got = await repo.report_desktop(7, error="desktop notification blocked", notice_title="n")
    assert got is not None and got.status == "failed"
    (s1, p1), (s2, p2) = rel.calls
    assert "status = 'failed'" in s1 and p1 == {"id": 7, "error": "desktop notification blocked"}
    assert "'in_app', 'sent'" in s2 and (p2["alert_id"], p2["user_id"]) == ("a", "u1")
    assert '"failed_delivery_id": 7' in p2["context"] and p2["title"] == "n"
    assert rel.commits == 1


async def test_report_desktop_on_a_settled_row_changes_nothing() -> None:
    repo, rel = _deliveries(_Result([]))
    assert await repo.report_desktop(7, error="x", notice_title="n") is None
    assert len(rel.calls) == 1  # no notice without the transition


# --- notifications union -----------------------------------------------------------------


def test_cursor_round_trips_and_refuses_foreign_shapes() -> None:
    row = NotificationRow(**_nrow(42, src=3))
    assert decode_cursor(encode_cursor(row)) == (_T0, 3, 42)
    for bad in ("!!", "WzFd", encode_cursor(row).replace("A", "B")):
        with pytest.raises(ValueError, match="invalid cursor"):
            decode_cursor(bad)


@pytest.mark.parametrize(
    "payload",
    [
        b'["2026-10-20T09:00:00+00:00", 9, 1]',  # unknown source rank
        b'["2026-10-20T09:00:00+00:00", 1, -1]',  # negative id
        b'["2026-10-20T09:00:00+00:00", 1, "1"]',  # id not an integer
        b'["2026-10-20T09:00:00", 1, 1]',  # no offset
    ],
)
def test_cursor_refuses_out_of_range_parts(payload: bytes) -> None:
    import base64

    with pytest.raises(ValueError, match="invalid cursor"):
        decode_cursor(base64.urlsafe_b64encode(payload).decode())


async def test_an_empty_scope_reads_nothing() -> None:
    repo, rel = _union()
    assert await repo.list_page(NotificationScope(user_id="u1")) == ([], None)
    assert rel.calls == []


async def test_list_binds_the_scope_and_fetches_one_extra_row() -> None:
    repo, rel = _union(_Result([_nrow(3), _nrow(2), _nrow(1)]))
    scope = NotificationScope(
        user_id="u1", alerts=True, rules=True, rule_ids=frozenset({"r2", "r1"}), orders=True,
        accounts=frozenset({"acc"}), system=True,
    )  # fmt: skip
    rows, last = await repo.list_page(scope, limit=2, unread_only=True)
    assert [r.src_id for r in rows] == [3, 2] and last is not None and last.src_id == 2
    ((_, p),) = rel.calls
    assert p["limit"] == 3 and p["unread_only"] is True and p["user"] == "u1"
    assert (p["all_rules"], p["rule_ids"]) == (False, ["r1", "r2"])
    assert (p["all_accounts"], p["accounts"]) == (False, ["acc"])
    assert (p["system"], p["system_all"]) == (True, False)
    assert (p["after_ts"], p["after_src"], p["after_id"]) == (None, None, None)


async def test_the_owner_scope_binds_every_rule_and_account() -> None:
    repo, rel = _union(_Result([]))
    owner = NotificationScope(user_id="u1", rules=True, rule_ids=None, orders=True,
                              accounts=None, system=True, system_all=True)  # fmt: skip
    assert await repo.list_page(owner) == ([], None)
    p = rel.calls[0][1]
    assert p["all_rules"] is True and p["all_accounts"] is True and p["system_all"] is True
    assert p["rule_ids"] == [] and p["accounts"] == []


async def test_a_cursor_binds_the_keyset() -> None:
    repo, rel = _union(_Result([]))
    cursor = encode_cursor(NotificationRow(**_nrow(9, src=2)))
    await repo.list_page(NotificationScope(user_id="u1", alerts=True), cursor=cursor)
    p = rel.calls[0][1]
    assert (p["after_ts"], p["after_src"], p["after_id"]) == (_T0, 2, 9)


async def test_a_bad_cursor_raises_before_any_read() -> None:
    repo, rel = _union()
    with pytest.raises(ValueError, match="invalid cursor"):
        await repo.list_page(NotificationScope(user_id="u1", alerts=True), cursor="nope")
    assert rel.calls == []


async def test_the_union_applies_each_sources_own_filter() -> None:
    repo, rel = _union(_Result([]))
    await repo.list_page(NotificationScope(user_id="u1", alerts=True))
    sql = rel.calls[0][0]
    # alert: own rows only; read state is the ack
    assert "d.user_id = CAST(:user AS uuid)" in sql and "d.acked_at IS NULL" in sql
    # rule: only the readable rules' action outcomes, never the payload
    assert "r.rule_id = ANY(CAST(:rule_ids AS uuid[]))" in sql
    assert all(f"'{k}'" in sql for k in RULE_EVENT_KINDS) and "condition_eval" not in sql
    # order: granted accounts' outcomes; ret_code, never ret_msg or payload
    assert "o.exchange_account_id = ANY(CAST(:accounts AS uuid[]))" in sql
    assert all(f"'{k}'" in sql for k in ORDER_EVENT_KINDS) and "submit_attempt" not in sql
    assert "ret_msg" not in sql and "payload" not in sql
    # system: auth rows and other accounts' rows only for the Owner; never `details`
    assert "se.component <> 'auth'" in sql and "details" not in sql
    # one total order across sources: (ts, src, src_id) descending, each branch pre-limited
    assert sql.rstrip().endswith("ORDER BY ts DESC, src DESC, src_id DESC LIMIT :limit")
    assert sql.count("LIMIT :limit") == 5
