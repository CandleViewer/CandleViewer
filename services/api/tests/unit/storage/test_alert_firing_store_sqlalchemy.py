"""`SqlAlchemyAlertFiringStore`: one-transaction firing semantics with a fake unit of work.

Real-Postgres behaviour (enum casts, `ux_outbox_dedup`) is exercised by the E40-Q02 chaos run.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key
from candleviewer.storage.repositories.alert_firing_sqlalchemy import SqlAlchemyAlertFiringStore
from tests.unit.storage.test_alerts_repository_sqlalchemy import _mapping, _Result

_T = datetime(2026, 10, 5, tzinfo=UTC)


class _Rel:
    def __init__(self, *results: _Result) -> None:
        self.results = list(results)
        self.sql: list[str] = []
        self.params: list[dict[str, Any] | None] = []
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> _Result:
            self.params.append(params)
            self.sql.append(str(stmt).split()[0] + " " + str(stmt).split()[2])
            return self.results.pop(0) if self.results else _Result([], 1)

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel) -> SqlAlchemyAlertFiringStore:
    return SqlAlchemyAlertFiringStore(
        rel,
        topic=TOPIC_ALERT_DELIVER,
        dedup_key=alert_deliver_dedup_key,  # type: ignore[arg-type]  # structural fake
    )


def _fire(store: SqlAlchemyAlertFiringStore, **kw: Any) -> Any:
    args: dict[str, Any] = dict(
        alert_id="a", user_id="u", channels=("in_app", "email"), status="queued", title="t",
        body="", context={"v": 1}, fired_at=_T, once=False, bump=True,
    )  # fmt: skip
    return store.record_firing(**(args | kw))


async def test_firing_store_queued_writes_delivery_and_outbox_in_one_commit() -> None:
    rel = _Rel(_Result([], 1), _Result([11]), _Result([], 1), _Result([12]), _Result([], 1))
    assert await _fire(_store(rel)) == [11, 12]
    assert rel.commits == 1
    assert [s for s in rel.sql if "outbox" in s] == ["INSERT outbox", "INSERT outbox"]


async def test_firing_store_once_lost_race_commits_nothing() -> None:
    rel = _Rel(_Result([], 0))
    assert await _fire(_store(rel), once=True) is None
    assert rel.commits == 0 and len(rel.sql) == 1


async def test_firing_store_suppressed_never_enqueues_outbox_and_disable_disarms() -> None:
    rel = _Rel(_Result([], 1), _Result([5]))
    ids = await _fire(_store(rel), status="suppressed", channels=("in_app",), bump=False,
                      disarm_reason="source_unavailable")  # fmt: skip
    assert ids == [5] and not any("outbox" in s for s in rel.sql) and rel.commits == 1


async def test_firing_store_once_wins_then_bumps() -> None:
    rel = _Rel(_Result([], 1), _Result([], 1), _Result([9]))
    assert await _fire(_store(rel), once=True, channels=("in_app",), status="suppressed") == [9]


async def test_firing_store_load_live_and_get() -> None:
    rel = _Rel(_Result([_mapping(1)]), _Result([_mapping(2)]), _Result([]))
    s = _store(rel)
    assert [r.id for r in await s.load_live()] == ["id-1"]
    got = await s.get("id-2")
    assert got is not None and got.id == "id-2"
    assert await s.get("nope") is None


async def test_firing_store_disable_already_disarmed_commits_nothing() -> None:
    rel = _Rel(_Result([], 0))
    assert await _fire(_store(rel), bump=False, disarm_reason="source_unavailable") is None
    assert rel.commits == 0 and rel.sql == ["UPDATE SET"]


def test_firing_store_select_mirrors_alert_column_allow_list() -> None:
    from candleviewer.storage.repositories import alert_firing_sqlalchemy as m
    from candleviewer.storage.repositories.alerts_sqlalchemy import ALERT_COLUMNS

    for stmt in (str(m._LIVE), str(m._GET)):
        assert ALERT_COLUMNS + ", " in stmt  # no secret column can slip in
        assert "webhook_url_enc," not in stmt and "secret" not in stmt


async def test_firing_store_rows_carry_last_bar_open_ms() -> None:
    rel = _Rel(_Result([dict(_mapping(1)) | {"last_bar_open_ms": 300_000}]))
    [r] = await _store(rel).load_live()
    assert r.last_bar_open_ms == 300_000 and r.id == "id-1"


async def test_firing_store_disarm_reason_is_a_bound_parameter_not_a_literal() -> None:
    from candleviewer.storage.repositories import alert_firing_sqlalchemy as m

    assert "disarm_reason = :reason" in str(m._DISARM_SOURCE)
    assert "source_unavailable" not in str(m._DISARM_SOURCE)
    rel = _Rel(_Result([], 1), _Result([5]))
    await _fire(_store(rel), channels=("in_app",), status="suppressed", bump=False,
                disarm_reason="source_unavailable")  # fmt: skip
    assert rel.params[0] == {"id": "a", "reason": "source_unavailable"}


def test_re_enable_clears_the_disarm_reason_in_sql() -> None:
    from candleviewer.storage.repositories import alerts_sqlalchemy as m

    sql = str(m._SET_ENABLED)
    assert "disarm_reason = CASE WHEN :enabled THEN NULL ELSE disarm_reason END" in sql
    assert "disarm_reason = CASE WHEN :enabled THEN NULL" in str(m._UPDATE)
