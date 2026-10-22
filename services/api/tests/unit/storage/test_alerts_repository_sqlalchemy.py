"""`SqlAlchemyAlertRepository` with a fake unit of work (E40-T01, no live Postgres).

Real-DB behaviour (ux_alerts_name partiality, trigger) is covered by
`tests/integration/storage/test_alerts_migration.py` (CI, docker).
"""

from __future__ import annotations

import json
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from candleviewer.alerts.outbox import (
    ALERT_OUTBOX_TOPICS,
    TOPIC_ALERT_DELIVER,
    TOPIC_WEBHOOK_POST,
    alert_deliver_dedup_key,
    webhook_post_dedup_key,
)
from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.repositories.alerts import AlertNameTakenError
from candleviewer.storage.repositories.alerts_sqlalchemy import (
    ALERT_COLUMNS,
    AlertConflictError,
    SqlAlchemyAlertRepository,
    array_literal,
    decode_cursor,
    encode_cursor,
)

_T0 = datetime(2026, 10, 1, tzinfo=UTC)


def _mapping(i: int = 1, **over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": f"id-{i}",
        "owner_user_id": "u1",
        "name": f"a{i}",
        "symbol": "BTCUSDT",
        "scope_account_id": None,
        "condition_ir": {"k": 1},
        "condition_hash": "h",
        "enabled": True,
        "trigger_mode": "once",
        "cooldown_seconds": 60,
        "snoozed_until": None,
        "expires_at": None,
        "severity": "info",
        "channels": ["in_app"],
        "has_webhook": False,
        "message_template": "",
        "last_fired_at": None,
        "fire_count": 0,
        "created_at": _T0 - timedelta(minutes=i),
        "updated_at": _T0,
    }
    d.update(over)
    return d


class _Result:
    def __init__(self, rows: list[Any], rowcount: int = 1) -> None:
        self.rows = rows
        self.rowcount = rowcount

    def mappings(self) -> _Result:
        return self

    def one(self) -> Any:
        return self.rows[0]

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def all(self) -> list[Any]:
        return self.rows

    def __iter__(self) -> Any:
        return iter(self.rows)

    def scalar_one(self) -> Any:
        return self.rows[0]


class _Rel:
    def __init__(self, *results: _Result) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> _Result:
            self.calls.append((str(stmt), params or {}))
            return self.results.pop(0)

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _repo(rel: _Rel) -> SqlAlchemyAlertRepository:
    return SqlAlchemyAlertRepository(rel)  # type: ignore[arg-type]  # structural fake


def test_read_allow_list_never_selects_secret_columns() -> None:
    assert "webhook_secret_enc" not in ALERT_COLUMNS
    assert "webhook_url_enc IS NOT NULL" in ALERT_COLUMNS  # only a boolean leaks


def test_cursor_roundtrip_and_invalid() -> None:
    assert decode_cursor(encode_cursor(_T0, "x")) == (_T0, "x")
    with pytest.raises(ValueError, match="invalid cursor"):
        decode_cursor("!!notbase64")


def test_array_literal() -> None:
    assert array_literal(("in_app", "webhook")) == "{in_app,webhook}"


async def test_create_binds_params_commits_and_maps_row() -> None:
    rel = _Rel(_Result([_mapping()]))
    row = await _repo(rel).create(
        owner_user_id="u1",
        name="a1",
        condition_ir={"b": 1, "a": 2},
        condition_hash="h",
        channels=("in_app", "webhook"),
        webhook_url_enc=b"enc",
    )
    sql, p = rel.calls[0]
    assert "INSERT INTO alerts" in sql and rel.commits == 1
    assert p["ir"] == json.dumps({"a": 2, "b": 1}) and p["channels"] == "{in_app,webhook}"
    assert p["url_enc"] == b"enc" and p["mode"] == "once"
    assert row.channels == ("in_app",) and row.etag == _T0.isoformat()


async def test_get_hit_miss_filters_soft_deleted() -> None:
    rel = _Rel(_Result([_mapping()]), _Result([]))
    repo = _repo(rel)
    assert (await repo.get("id-1")) is not None
    assert (await repo.get("gone")) is None
    assert "deleted_at IS NULL" in rel.calls[0][0]


async def test_list_page_first_page_sets_next_cursor_keyset() -> None:
    rows = [_mapping(i) for i in (1, 2, 3)]
    rel = _Rel(_Result(rows))
    page = await _repo(rel).list_page("u1", limit=2)
    assert [r.id for r in page.items] == ["id-1", "id-2"]
    assert rel.calls[0][1]["limit"] == 3 and rel.calls[0][1]["after_ts"] is None
    assert "OFFSET" not in rel.calls[0][0]
    assert decode_cursor(page.next_cursor or "") == (page.items[-1].created_at, "id-2")


async def test_list_page_last_page_has_no_cursor_and_passes_cursor() -> None:
    rel = _Rel(_Result([_mapping(3)]))
    cur = encode_cursor(_T0, "id-2")
    page = await _repo(rel).list_page("u1", cursor=cur, limit=2)
    assert page.next_cursor is None and len(page.items) == 1
    assert rel.calls[0][1]["after_ts"] == _T0 and rel.calls[0][1]["after_id"] == "id-2"


async def test_list_page_empty() -> None:
    page = await _repo(_Rel(_Result([]))).list_page("u1")
    assert page.items == [] and page.next_cursor is None


def _update_kwargs() -> dict[str, Any]:
    return {
        "if_match": _T0,
        "name": "n",
        "condition_ir": {},
        "condition_hash": "h",
        "trigger_mode": "once",
        "cooldown_seconds": 1,
        "expires_at": None,
        "severity": "info",
        "channels": ("in_app",),
        "message_template": "",
    }


async def test_update_success_uses_if_match_predicate() -> None:
    rel = _Rel(_Result([_mapping(name="n")]))
    row = await _repo(rel).update("id-1", **_update_kwargs())
    sql, p = rel.calls[0]
    assert "updated_at = :if_match" in sql and p["if_match"] == _T0
    assert row.name == "n" and rel.commits == 1


async def test_update_stale_etag_raises_conflict() -> None:
    with pytest.raises(AlertConflictError):
        await _repo(_Rel(_Result([]))).update("id-1", **_update_kwargs())


async def test_soft_delete_disables_and_reports_rowcount() -> None:
    rel = _Rel(_Result([], rowcount=1), _Result([], rowcount=0))
    repo = _repo(rel)
    assert await repo.soft_delete("id-1") is True
    assert await repo.soft_delete("id-1") is False  # already deleted
    sql = rel.calls[0][0]
    assert "deleted_at = now()" in sql and "enabled = false" in sql


async def test_set_enabled_and_snooze_return_rows_or_none() -> None:
    rel = _Rel(_Result([_mapping(enabled=False)]), _Result([]), _Result([_mapping()]))
    repo = _repo(rel)
    r = await repo.set_enabled("id-1", False)
    assert r is not None and r.enabled is False and rel.calls[0][1]["enabled"] is False
    assert await repo.set_enabled("missing", True) is None
    assert await repo.set_snooze("id-1", _T0) is not None
    assert rel.calls[2][1]["until"] == _T0


async def test_bump_fire_counters_and_load_armed() -> None:
    rel = _Rel(_Result([]), _Result([_mapping(1), _mapping(2)]))
    repo = _repo(rel)
    await repo.bump_fire_counters("id-1", _T0)
    assert "fire_count + 1" in rel.calls[0][0] and rel.commits == 1
    armed = await repo.load_armed("BTCUSDT")
    assert len(armed) == 2 and rel.calls[1][1] == {"symbol": "BTCUSDT"}


async def test_gauges_defaults_missing_enabled_buckets_to_zero() -> None:
    rel = _Rel(_Result([{"enabled": True, "n": 3}]), _Result([4]))
    g = await _repo(rel).gauges()
    assert g == {
        "cv_alerts_total{enabled=true}": 3,
        "cv_alerts_total{enabled=false}": 0,
        "cv_alert_deliveries_pending": 4,
    }


async def test_delivery_purge_split_fetch_then_delete_by_ids() -> None:
    from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import (
        SqlAlchemyAlertDeliveryRepository,
    )

    row = {
        "id": 7, "alert_id": "a", "user_id": None, "channel": "in_app", "status": "sent",
        "title": "t", "body": "", "context": {}, "attempt": 1, "http_status": None,
        "error_message": None, "queued_at": _T0, "sent_at": None, "acked_at": None,
        "acked_by": None,
    }  # fmt: skip
    rel = _Rel(_Result([row]), _Result([], rowcount=1))
    repo = SqlAlchemyAlertDeliveryRepository(rel)  # type: ignore[arg-type]  # structural fake
    got = await repo.fetch_expired(180, 10)
    assert [r.id for r in got] == [7] and rel.calls[0][1] == {"days": 180, "limit": 10}
    assert await repo.delete_ids([]) == 0 and len(rel.calls) == 1
    assert await repo.delete_ids([7]) == 1
    assert "DELETE FROM alert_deliveries" in rel.calls[1][0] and rel.commits == 1


def test_array_literal_rejects_unknown_channel() -> None:
    import pytest

    for bad in ("a,b", "x}", "sms"):
        with pytest.raises(ValueError):
            array_literal(("in_app", bad))


_ROW = "canary-2748-row"  # a value the server's DETAIL would quote


class _Raising(_Rel):
    """Execute raises an IntegrityError with `state` and `constraint`, the row in its text."""

    def __init__(self, state: str, constraint: str | None) -> None:
        super().__init__()
        self.state, self.constraint = state, constraint

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> _Result:
            orig = Exception(f"refused: Failing row contains ({_ROW})")
            orig.sqlstate, orig.constraint_name = self.state, self.constraint  # type: ignore[attr-defined]
            raise IntegrityError(str(stmt), params, orig)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=None)


@pytest.mark.parametrize(
    ("state", "constraint", "refusal"),
    [
        ("23505", "ux_alerts_name", AlertNameTakenError),
        ("23505", "alerts_pkey", StorageConstraintViolated),
        ("23514", "al_cooldown", StorageConstraintViolated),
        ("23502", None, StorageConstraintViolated),
        ("23503", "alerts_owner_user_id_fkey", StorageConstraintViolated),
    ],
)
@pytest.mark.parametrize("write", ["create", "update"])
async def test_only_the_name_key_is_name_taken_and_no_write_chains_the_row(
    state: str, constraint: str | None, refusal: type[Exception], write: str
) -> None:
    repo = _repo(_Raising(state, constraint))
    with pytest.raises(refusal) as raised:
        if write == "create":
            await repo.create(owner_user_id="u1", name="a", condition_ir={}, condition_hash="h")
        else:
            await repo.update("id-1", **_update_kwargs())
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert _ROW not in "".join(traceback.format_exception(raised.value))
    if isinstance(raised.value, StorageConstraintViolated):
        assert (raised.value.sqlstate, raised.value.constraint) == (state, constraint)


async def test_list_page_passes_enabled_and_symbol_filters() -> None:
    rel = _Rel(_Result([]))
    await _repo(rel).list_page("u1", enabled=False, symbol="BTCUSDT")
    sql, p = rel.calls[0]
    assert p["enabled"] is False and p["symbol"] == "BTCUSDT" and ":enabled" in sql


def test_outbox_dedup_keys() -> None:
    assert alert_deliver_dedup_key(7) == "7"
    assert webhook_post_dedup_key("a", 1, 2) == "a:1:2"
    assert {TOPIC_ALERT_DELIVER, TOPIC_WEBHOOK_POST} == ALERT_OUTBOX_TOPICS
