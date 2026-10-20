"""E40-T04 PR-A storage with a fake UoW: the inbox additions to the deliveries repository
(`get`, `alert_owner`, `report_desktop`, the list's keyset) and the `GET /notifications` union.

Real-DB behaviour (the union on Postgres, per-source scoping, keyset ties) is covered by
`tests/integration/storage/test_notifications_union_pg.py` in the integration CI job.
"""

from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_alert_dispatch_store import _row
from test_alerts_repository_sqlalchemy import _Rel, _Result

import candleviewer
from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import (
    SqlAlchemyAlertDeliveryRepository,
)
from candleviewer.storage.repositories.alerts_sqlalchemy import (
    decode_cursor as decode_alert_cursor,
)
from candleviewer.storage.repositories.alerts_sqlalchemy import (
    encode_cursor as encode_alert_cursor,
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
    return SqlAlchemyNotificationRepository(rel, env="demo"), rel  # type: ignore[arg-type]  # fake


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


async def test_report_desktop_shown_is_the_owners_conditional_queued_to_sent() -> None:
    repo, rel = _deliveries(_Result([_row(channel="desktop", status="sent")]))
    got = await repo.report_desktop(7, user_id="u1", error=None, notice_title="n")
    assert got is not None and got.status == "sent"
    ((sql, p),) = rel.calls
    assert "user_id = CAST(:by AS uuid) AND channel = 'desktop' AND status = 'queued'" in sql
    assert p == {"id": 7, "by": "u1"} and rel.commits == 1


async def test_report_desktop_failure_writes_the_notice_in_the_same_transaction() -> None:
    failed = _row(channel="desktop", status="failed", alert_id="a", user_id="u1")
    repo, rel = _deliveries(_Result([failed]), _Result([]))
    got = await repo.report_desktop(
        7, user_id="u1", error="desktop notification blocked", notice_title="n"
    )
    assert got is not None and got.status == "failed"
    (s1, p1), (s2, p2) = rel.calls
    assert "status = 'failed'" in s1 and "user_id = CAST(:by AS uuid)" in s1
    assert p1 == {"id": 7, "by": "u1", "error": "desktop notification blocked"}
    assert "'in_app', 'sent'" in s2 and (p2["alert_id"], p2["user_id"]) == ("a", "u1")
    assert '"failed_delivery_id": 7' in p2["context"] and p2["title"] == "n"
    assert rel.commits == 1


async def test_report_desktop_on_a_settled_or_foreign_row_changes_nothing() -> None:
    repo, rel = _deliveries(_Result([]))
    assert await repo.report_desktop(7, user_id="u2", error="x", notice_title="n") is None
    assert len(rel.calls) == 1  # no notice without the transition


@pytest.mark.parametrize(
    "cursor",
    [
        encode_alert_cursor(_T0, "abc"),  # an id that is no integer
        encode_alert_cursor(_T0, 0),
        encode_alert_cursor(_T0, -1),
        encode_alert_cursor(_T0, 2**63),  # past bigint: a driver error at bind time, not a 400
        base64.urlsafe_b64encode(b'["2026-10-20T09:00:00", "7"]').decode(),  # no offset
        base64.urlsafe_b64encode(b'["0001-01-01T00:00:00+14:00", "7"]').decode(),  # no UTC instant
    ],
)
async def test_the_list_refuses_a_cursor_it_cannot_have_issued_before_any_read(
    cursor: str,
) -> None:
    repo, rel = _deliveries()
    with pytest.raises(ValueError, match="invalid cursor"):
        await repo.list_page(user_id="u1", cursor=cursor)
    assert rel.calls == []


async def test_the_list_keyset_round_trips() -> None:
    repo, rel = _deliveries(_Result([]))
    await repo.list_page(user_id="u1", cursor=encode_alert_cursor(_T0, 41))
    assert (rel.calls[0][1]["after_ts"], rel.calls[0][1]["after_id"]) == (_T0, 41)


@pytest.mark.parametrize(
    "payload",
    [
        b'["2026-10-20T09:00:00", "x"]',
        b'["2026-10-20T09:00:00+00:00", [1]]',
        b'["2026-10-20T09:00:00+00:00", {"a": 1}]',
    ],
)
def test_the_shared_alert_cursor_requires_an_offset_and_a_scalar_id(payload: bytes) -> None:
    """The `/alerts` list shares this decoder: it gains the same refusals (SR-E40T04A-04)."""
    with pytest.raises(ValueError, match="invalid cursor"):
        decode_alert_cursor(base64.urlsafe_b64encode(payload).decode())
    assert decode_alert_cursor(encode_alert_cursor(_T0, "id-1")) == (_T0, "id-1")


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
        b'["2026-10-20T09:00:00+00:00", [1], 1]',  # an unhashable rank (was a TypeError 500)
        b'["2026-10-20T09:00:00+00:00", true, 1]',  # a boolean is no rank
        b'["2026-10-20T09:00:00+00:00", 1, true]',  # nor an id
        b'["2026-10-20T09:00:00+00:00", 1, -1]',  # negative id
        b'["2026-10-20T09:00:00+00:00", 1, 0]',  # no bigserial row has id 0
        b'["2026-10-20T09:00:00+00:00", 1, 9223372036854775808]',  # past bigint
        b'["2026-10-20T09:00:00+00:00", 1, "1"]',  # id not an integer
        b'["2026-10-20T09:00:00", 1, 1]',  # no offset
        b'["0001-01-01T00:00:00+14:00", 1, 1]',  # no UTC instant (OverflowError)
    ],
)
def test_cursor_refuses_out_of_range_parts(payload: bytes) -> None:
    with pytest.raises(ValueError, match="invalid cursor"):
        decode_cursor(base64.urlsafe_b64encode(payload).decode())


async def test_an_empty_scope_reads_nothing() -> None:
    repo, rel = _union()
    assert await repo.list_page(NotificationScope(user_id="u1")) == ([], None)
    # rules allowed but no readable rule: nothing to read either
    only_rules = NotificationScope(user_id="u1", rules=True, rule_ids=frozenset())
    assert await repo.list_page(only_rules) == ([], None)
    assert rel.calls == []


async def test_list_binds_the_scope_and_fetches_one_extra_row() -> None:
    repo, rel = _union(_Result([_nrow(3), _nrow(2), _nrow(1)]))
    scope = NotificationScope(
        user_id="u1", alerts=True, rules=True, rule_ids=frozenset({"r2", "r1"}), orders=True,
        accounts=frozenset({"acc"}),
    )  # fmt: skip
    rows, last = await repo.list_page(scope, limit=2, unread_only=True)
    assert [r.src_id for r in rows] == [3, 2] and last is not None and last.src_id == 2
    ((_, p),) = rel.calls
    assert p["limit"] == 3 and p["unread_only"] is True and p["user"] == "u1"
    assert (p["rules"], p["rule_ids"]) == (True, ["r1", "r2"])
    assert (p["all_accounts"], p["accounts"]) == (False, ["acc"])
    assert (p["system"], p["env"]) == (False, "demo")
    assert p["rule_kinds"] == list(RULE_EVENT_KINDS) and p["order_kinds"] == list(ORDER_EVENT_KINDS)
    assert (p["after_ts"], p["after_src"], p["after_id"]) == (None, None, None)


async def test_the_owner_scope_binds_every_account_and_the_system_stream() -> None:
    repo, rel = _union(_Result([]))
    owner = NotificationScope(user_id="u1", orders=True, accounts=None, system=True)
    assert await repo.list_page(owner) == ([], None)
    p = rel.calls[0][1]
    assert p["all_accounts"] is True and p["accounts"] == [] and p["system"] is True


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


def test_the_repository_refuses_an_unknown_environment() -> None:
    with pytest.raises(ValueError, match="unknown exchange environment"):
        SqlAlchemyNotificationRepository(_Rel(), env="prod")  # type: ignore[arg-type]


async def test_the_union_applies_each_sources_own_filter() -> None:
    repo, rel = _union(_Result([]))
    await repo.list_page(NotificationScope(user_id="u1", alerts=True))
    sql = rel.calls[0][0]
    # alert: the caller's own in-app record, once delivered; unread = what can still be acked
    assert "d.user_id = CAST(:user AS uuid)" in sql and "d.channel = 'in_app'" in sql
    assert "d.status IN ('sent', 'acked')" in sql
    assert "(d.status = 'sent' AND d.acked_at IS NULL)" in sql
    # rule: only the readable rules' outcomes (the kinds bound from the port), never the payload
    assert "r.rule_id = ANY(CAST(:rule_ids AS uuid[]))" in sql
    assert "e.kind = ANY(CAST(:rule_kinds AS text[]))" in sql
    # order: granted accounts' outcomes; ret_code, never ret_msg or payload
    assert "o.exchange_account_id = ANY(CAST(:accounts AS uuid[]))" in sql
    assert "oe.kind::text = ANY(CAST(:order_kinds AS text[]))" in sql
    assert "ret_msg" not in sql and "payload" not in sql
    # system: the Owner's alone (the scope says so: no role-filtered path exists), no `details`
    assert "CAST(:system AS boolean)" in sql and "component" not in sql
    assert "details" not in sql
    # C-2.11: every account-bound branch (rule, order, system) is this environment's only
    assert sql.count("ea.env::text = :env") == 3
    # no SECRET column of `alerts` is ever selected (the ticket's security note)
    assert "_enc" not in sql
    # one total order across sources: (ts, src, src_id) descending, each branch pre-limited and
    # bounded by an index-usable `ts <= COALESCE(:after_ts, 'infinity')`
    assert sql.rstrip().endswith("ORDER BY ts DESC, src DESC, src_id DESC LIMIT :limit")
    assert sql.count("LIMIT :limit") == 5
    assert sql.count("'infinity'::timestamptz") == 4


# --- the served kinds stay inside the schema's vocabularies --------------------------------

_VERSIONS = Path(candleviewer.__file__).parent / "migrations" / "versions"


def _enum_values(text: str, type_name: str) -> set[str]:
    created = re.search(rf"CREATE TYPE {type_name}\s+AS ENUM \(([^)]*)\)", text)
    assert created is not None, type_name
    return set(re.findall(r"'([a-z_]+)'", created.group(1)))


def test_every_order_kind_served_is_an_order_event_kind() -> None:
    """A misspelt kind would match nothing and silently hide that outcome."""
    created = (_VERSIONS / "0029_oms_core.py").read_text(encoding="utf-8")
    known = _enum_values(created, "order_event_kind")
    added = (_VERSIONS / "0034_order_vocabulary.py").read_text(encoding="utf-8")
    known |= set(re.findall(r'\("order_event_kind", "([a-z_]+)"\)', added))
    assert set(ORDER_EVENT_KINDS) <= known and {"kill", "adopt"} <= set(ORDER_EVENT_KINDS)


def test_every_rule_kind_served_is_a_rule_event_kind() -> None:
    text = (_VERSIONS / "0013_rules.py").read_text(encoding="utf-8")
    check = re.search(r"CONSTRAINT re_kind CHECK \(kind IN\s*\(([^)]*)\)\)", text)
    assert check is not None
    assert set(RULE_EVENT_KINDS) <= set(re.findall(r"'([a-z_]+)'", check.group(1)))
