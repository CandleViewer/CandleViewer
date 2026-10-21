"""#1016 (E40-T04): `SqlAlchemyAlertDispatchStore.depth` with a fake UoW. The count itself, over
real rows, is `tests/integration/storage/test_alert_outbox_depth_pg.py`."""

from __future__ import annotations

from test_alerts_repository_sqlalchemy import _Rel, _Result

from candleviewer.storage.repositories.alert_dispatch_sqlalchemy import (
    SqlAlchemyAlertDispatchStore,
)


async def test_depth_counts_one_topics_unprocessed_not_dead_rows_in_a_read_only_unit() -> None:
    rel = _Rel(_Result([5]))
    store = SqlAlchemyAlertDispatchStore(rel)  # type: ignore[arg-type]  # structural fake
    assert await store.depth("alert.deliver") == 5
    ((sql, params),) = rel.calls
    assert params == {"topic": "alert.deliver"} and rel.commits == 0
    assert sql.startswith("SELECT count(*) FROM outbox WHERE topic = :topic")
    assert "processed_at IS NULL" in sql and "dead_at IS NULL" in sql
