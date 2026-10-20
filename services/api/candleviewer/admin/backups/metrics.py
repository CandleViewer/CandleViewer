"""Backup metrics (E42-T05 #966 BK-5), on the facade like the admin area's other series, served on
the scraped registry with `env` by `export_backup_metrics` only once `BACKUPS_CATALOGUED` is set
(`backups_wiring`). Labels are closed sets, never an id, a path, a user or an IP: `kind` is one of
the five `BackupKind` values, `result` one of the four `RESTORE_RESULTS` and `reason` one of the
seven `BACKUP_ERROR_CODES`.

- `cv_backup_last_success_age_seconds{kind}`: `BackupFreshness`, now minus the last success of
  each kind, computed at scrape from a cache: `start()` loads it once, within a budget, at boot
  (BK-3's `last_success_by_kind`), and `record_success()` moves it forward. A scrape reads only the
  cache and the clock, never the store. A kind that never succeeded has no sample, so the
  stale-backup alert (`BackupLastSuccessStale`) cannot fire for it (Q16: its `absent()` guards come
  with the engine's schedule, #3319). Every finished run, a scheduled one included, must reach
  `record_success()`: a run the catalogue records without it leaves the age stale-high until the
  next boot. A success that leaves the catalogue's successes (a delete, BK-12) reaches
  `recompute()`, which reloads its kind, so the age never reads fresher than the catalogue.
- `cv_backup_verify_failures_total{reason}`: verifications that failed, by `Backup.error` code.
- `cv_backup_download_source_rate_limited_total`: fetches refused because their source address
  missed too often (BK-11), counted whatever the answer, a `503` for an unwritten record too; no
  label, so never an address or a user.
- `cv_restore_jobs_total{result}`: restores by result, a refusal counted as `refused` although it
  creates no job (Q17). Every result is bound at import, so a first one after a restart is an
  increase.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from datetime import datetime
from typing import Final, Literal, Protocol, get_args

import structlog

from candleviewer.admin.audited import audit_exempt
from candleviewer.admin.backups.catalogue import READ_BUDGET_S
from candleviewer.admin.overview.fanout import utc_now
from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    ReexportCollector,
)
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.backups import (
    BACKUP_ERROR_CODES,
    SUCCESS_STATUSES,
    BackupErrorCode,
    BackupKind,
    BackupRow,
)

RestoreResult = Literal["refused", "succeeded", "failed", "cancelled"]
RESTORE_RESULTS: Final[tuple[RestoreResult, ...]] = get_args(RestoreResult)
KINDS: Final[frozenset[str]] = frozenset(get_args(BackupKind))

verify_failures_total = Counter(
    "cv_backup_verify_failures_total",
    "Backup verifications that failed, by reason: checksum_mismatch, checksum_unbound, "
    "artefact_missing or verify_failed (conclusive), or store_unavailable, "
    "audit_unavailable or internal_error (inconclusive: the row is left as it was).",
    ["reason"],
)
_VERIFY_FAILURES: Final = {code: verify_failures_total.labels(code) for code in BACKUP_ERROR_CODES}
source_rate_limited_total = Counter(
    "cv_backup_download_source_rate_limited_total",
    "Backup download fetches refused because their source address missed (a token or backup id "
    "that is malformed or matches no link) more than 10 times in a minute.",
)
restore_jobs_total = Counter(
    "cv_restore_jobs_total",
    "Restores by result: refused (a precondition failed or could not be evaluated; no job "
    "created), succeeded, failed or cancelled.",
    ["result"],
)
_RESTORES: Final = {result: restore_jobs_total.labels(result) for result in RESTORE_RESULTS}
last_success_age_seconds = Gauge(
    "cv_backup_last_success_age_seconds",
    "Seconds since the last successful backup of each kind (ok, verified or restored, its artefact "
    "not deleted): pg_basebackup, pg_dump, questdb_snapshot, parquet_sync or config_bundle. No "
    "sample for a kind that never succeeded.",
    ["kind"],
)

EXPORTED_NAMES: Final = frozenset(
    {
        "cv_backup_last_success_age_seconds",
        "cv_backup_verify_failures_total",
        "cv_backup_download_source_rate_limited_total",
        "cv_restore_jobs_total",
    }
)


def count_restore(result: RestoreResult) -> None:
    """One restore's result, or its refusal (Q17). A value outside the closed set is a `KeyError`
    and never a new series."""
    _RESTORES[result].inc()


def count_verify_failure(reason: BackupErrorCode) -> None:
    """One failed verification, by its job's code (BK-9). A value outside the closed set is a
    `KeyError` and never a new series."""
    _VERIFY_FAILURES[reason].inc()


def export_backup_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the backup series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})


class LastSuccesses(Protocol):
    """The one read the freshness makes of BK-3's `BackupStore`."""

    async def last_success_by_kind(self) -> dict[BackupKind, datetime]:
        """Per kind, the latest `finished_at` of a success whose artefact was not deleted."""


class BackupFreshness:
    """The cache behind `cv_backup_last_success_age_seconds{kind}`: each kind's last success. It
    is the store's `last_success_by_kind` at boot; after that `record_success` moves it forward,
    and `recompute` reloads a kind whose last success was deleted (BK-12) or, with BK-9, failed a
    verification."""

    def __init__(
        self,
        store: LastSuccesses | None,
        *,
        now: Callable[[], datetime] = utc_now,
        budget_s: float = READ_BUDGET_S,
        gauge: Gauge = last_success_age_seconds,
    ) -> None:
        self._store, self._now, self._budget_s, self._gauge = store, now, budget_s, gauge
        self._last: dict[str, datetime] = {}

    @audit_exempt("lifecycle")
    async def start(self) -> None:
        """Load each kind's last success, once, within the budget. An outage, a read the store
        refuses, or the budget spent is logged and fails nothing: boot goes on with the cache as it
        is, and each kind's age appears with its next success. No store (the fake backend) loads
        nothing."""
        if self._store is None:
            return
        try:
            async with asyncio.timeout(self._budget_s):
                loaded = await self._store.last_success_by_kind()
        except (TimeoutError, StorageError) as exc:
            # The class only, never the store's text. Until each kind succeeds again, the
            # stale-backup alert cannot fire for it.
            log = structlog.get_logger(__name__)
            log.error("backups.freshness_not_loaded", error=type(exc).__name__)
            return
        for kind, at in loaded.items():
            self._advance(kind, at)

    @audit_exempt("read")
    def record_success(self, row: BackupRow) -> None:
        """A finished run: it moves its kind's last success forward only when it succeeded (`ok`,
        `verified` or `restored`, finished) and its artefact is kept. A failed, running or
        deleted run is never a success."""
        kept = row.deleted_at is None
        if row.status in SUCCESS_STATUSES and row.finished_at is not None and kept:
            self._advance(row.kind, row.finished_at)

    @audit_exempt("read")
    async def recompute(self, row: BackupRow) -> None:
        """`row` is a success no longer. When it held its kind's last success, that kind's is read
        again within the budget: an older success, or no sample when none is left. A success
        recorded meanwhile is newer, so it stays. A failed or slow read is logged with its class
        and keeps the cache as it was; nothing raises. Callers hold the backups admission lock,
        so two recomputations never interleave."""
        kind, held = row.kind, self._last.get(row.kind)
        if self._store is None or held is None or row.finished_at != held:
            return  # not its kind's last success: the age stands
        try:
            async with asyncio.timeout(self._budget_s):
                loaded = (await self._store.last_success_by_kind()).get(kind)
        except Exception as exc:  # an outage, a stall or a refused read: logged, never raised
            log = structlog.get_logger(__name__)
            log.error("backups.freshness_not_reloaded", kind=kind, error=type(exc).__name__)
            return
        if self._last.get(kind) != held:  # `record_success` moved it on during the read
            return
        if loaded is None:
            del self._last[kind]
            self._gauge.remove(kind)
        else:
            self._last[kind] = loaded

    @audit_exempt("read")
    def age_s(self, kind: str) -> float:
        """Now minus the kind's last success; a scrape calls it, and it does no I/O."""
        return (self._now() - self._last[kind]).total_seconds()

    def _scrape(self, kind: str) -> float:
        """The sample a scrape takes: NaN and a log line if the age raises, so one bad value can
        never fail the whole exposition."""
        try:
            return self.age_s(kind)
        except Exception as exc:  # a bug stays local to this sample
            log = structlog.get_logger(__name__)
            log.error("backups.freshness_scrape_failed", kind=kind, error=type(exc).__name__)
            return math.nan

    def _advance(self, kind: str, at: datetime) -> None:
        if kind not in KINDS or at.utcoffset() is None:  # a closed label set; aware times only
            return
        last = self._last.get(kind)
        if last is not None and at <= last:
            return
        self._last[kind] = at
        if last is None:  # the kind's first success binds its series
            self._gauge.labels(kind).set_function(lambda: self._scrape(kind))
