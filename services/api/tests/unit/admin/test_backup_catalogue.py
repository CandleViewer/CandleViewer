"""Unit (E42-T05 #966 BK-4): `BackupCatalogue`, behind `listBackups` and `getBackup`. Time is
injected and nothing sleeps: a hung store is cut by a 10 ms budget that only a hang can reach."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.errors import InvalidCursor, OpsUnavailable
from candleviewer.admin.ops.incidents import CURSOR_TTL_S
from candleviewer.observability.context import bind_context
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from tests.unit.admin._backup_fakes import NOW, Store, row

#: Built by concatenation (as tests/security does) so no scanner sees a credential literal.
_ALIAS = "age-key-" + "q" * 20
_REQUEST = "req-bk4-read"


async def test_a_page_asks_for_one_extra_row_strictly_after_the_cursors_position() -> None:
    store = Store([row(n) for n in (1, 2, 3, 4)] + [row(5, kind="config_bundle")])
    pages = BackupCatalogue(store, now=lambda: NOW).page
    first = await pages(kind="pg_dump", status="verified", cursor=None, limit=2)
    last = await pages(kind="pg_dump", status="verified", cursor=first.next_cursor, limit=2)
    assert [r.id.int for r in first.items + last.items] == [1, 2, 3, 4] and last.next_cursor is None
    after = (row(2).started_at, row(2).id)  # the last row the first page served
    assert store.calls == [
        ("page", "pg_dump", "verified", None, 3),
        ("page", "pg_dump", "verified", after, 3),
    ]


async def test_a_cursor_lives_for_an_hour_on_the_catalogues_clock() -> None:
    clock = [NOW]
    catalogue = BackupCatalogue(Store([row(1), row(2)]), now=lambda: clock[0])
    cursor = (await catalogue.page(kind=None, status=None, cursor=None, limit=1)).next_cursor
    clock[0] = NOW + timedelta(seconds=CURSOR_TTL_S)
    await catalogue.page(kind=None, status=None, cursor=cursor, limit=1)  # an hour: still good
    clock[0] += timedelta(seconds=1)
    with pytest.raises(InvalidCursor):
        await catalogue.page(kind=None, status=None, cursor=cursor, limit=1)


@pytest.mark.parametrize("op", ["page", "get"])
@pytest.mark.parametrize(
    "error",
    [StorageTierUnavailable(_ALIAS), TimeoutError(_ALIAS), None],
    ids=["outage", "timeout", "hang"],
)
async def test_an_outage_or_a_hung_store_is_unavailable_and_only_the_class_is_logged(
    op: str, error: Exception | None
) -> None:
    store = Store([row(1)], error=error, hang=error is None)
    catalogue = BackupCatalogue(store, now=lambda: NOW, budget_s=0.01)
    pending = (
        catalogue.page(kind=None, status=None, cursor=None, limit=1)
        if op == "page"
        else catalogue.get(UUID(int=1))
    )
    with bind_context(request_id=_REQUEST), capture_logs() as logs:
        with pytest.raises(OpsUnavailable) as refused:
            async with asyncio.timeout(5):  # a hang the budget missed fails, never hangs
                await pending
    assert str(refused.value) == "backups: store unavailable"  # a fixed literal, never the text
    assert (refused.value.__cause__, refused.value.__context__) == (None, None)
    failed = "TimeoutError" if error is None else type(error).__name__
    entry = {"event": "admin_backups.read_failed", "op": op, "error": failed}
    assert logs == [entry | {"request_id": _REQUEST, "log_level": "warning"}]  # correlated


@pytest.mark.parametrize(
    "error", [StorageQueryFailed("42501"), RuntimeError("bug")], ids=["query-failed", "untyped"]
)
async def test_a_query_failure_or_an_untyped_error_is_a_bug_never_an_outage(
    error: Exception,
) -> None:
    with capture_logs() as logs, pytest.raises(type(error)) as raised:
        await BackupCatalogue(Store(error=error)).get(UUID(int=1))
    assert raised.value is error and logs == []  # kept for the app's 500; the store logs it
