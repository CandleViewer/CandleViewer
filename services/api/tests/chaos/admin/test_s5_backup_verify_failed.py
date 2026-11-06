"""E42-Q03 scenario 5, server half: a backup verification failed (#1216).

[BQ-5] Blocked on main: `BACKUPS_CATALOGUED` is False until the E45 backup engine (#3319), so every
backups route answers `501` and no age series is served. Run in process instead, with the
constant left as it is: the shipped catalogue and freshness read BACKUP-VERIFY-FAILED (Q01's
`seed_backups`: BACKUP-VERIFIED three days old, the failed run the latest) from Postgres. The list
holds both rows, the failed one with its reason; the age reads the verified run's three days, and
its scraped value is written as a promtool suite that must raise the `BackupLastSuccessStale`
ticket. The result is labelled "engine not wired" (SCENARIOS.md) until #3319 lands; the restore
refusal (`409 backup_not_usable`) waits on BK-14's mount. The UI half is part 3's.
Marked `harness`: needs Docker, runs nightly.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from candleviewer import backups_wiring
from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.metrics import BackupFreshness, last_success_age_seconds
from candleviewer.storage.repositories.backups_sqlalchemy import SqlAlchemyBackups
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.admin import _alerts
from tests.chaos.admin._relay import Relay
from tests.chaos.admin._server import relational
from tests.fixtures.admin.handles import BACKUP_VERIFIED, BACKUP_VERIFY_FAILED
from tests.fixtures.admin.seed import backup_row, seed_backups

pytestmark = [pytest.mark.chaos, pytest.mark.harness]

AGE = "cv_backup_last_success_age_seconds"


@pytest.fixture
async def repo(relay: Relay, pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    made = relational(relay.through(pg_dsn), "admin")
    yield made
    await made.dispose()


async def test_s5_the_failed_verification_is_listed_and_the_age_raises_the_ticket(
    relay: Relay, pg_dsn: str, repo: SqlAlchemyRelationalRepository, tmp_path: Path
) -> None:
    assert backups_wiring.BACKUPS_CATALOGUED is False, "#3319 landed: run this through the routes"
    now = datetime.now(UTC)  # read once: the seed, the catalogue and the age share it
    engine = create_async_engine(pg_dsn)
    try:
        async with engine.begin() as conn:
            await seed_backups(conn, now=now)
    finally:
        await engine.dispose()
    store = SqlAlchemyBackups(repo)
    page = await BackupCatalogue(store, now=lambda: now).page(
        kind=None, status=None, cursor=None, limit=50
    )
    rows = {row.id: row for row in page.items}
    assert set(rows) == {BACKUP_VERIFIED.id, BACKUP_VERIFY_FAILED.id}
    failed = rows[BACKUP_VERIFY_FAILED.id]
    assert (failed.status, failed.error_message) == ("failed", "checksum_mismatch")
    freshness = BackupFreshness(store, now=lambda: now)
    await freshness.start()
    verified = backup_row(BACKUP_VERIFIED, now)
    kind = str(verified["kind"])
    expected = (now - verified["finished_at"]).total_seconds()
    try:
        scraped = _alerts.scrape(AGE, kind=kind)
    finally:
        with contextlib.suppress(KeyError):  # the series is process-wide: leave none behind
            last_success_age_seconds.remove(kind)
    assert scraped == pytest.approx(expected)  # the verified run's age, not the failed latest's
    labels = {"env": "testnet", "kind": kind}
    suite = [
        _alerts.case(
            "BackupLastSuccessStale",
            {_alerts.series(AGE, labels): f"{scraped:.0f}+60x40"},
            eval_time="20m",
            labels=labels,
        )
    ]
    _alerts.write_suite("s5_backup_age", suite, _alerts.out_dir(tmp_path / "alerts"))
    await relay.ensure_up()
