"""Backups limits (E42-T05, #966): the one module the backups services' budgets live in (Q5).

The job deadlines are a backstop for a hung engine, not a performance budget. Each is set past
the slowest healthy v1 job of its kind (a run includes the first restic sync of the Parquet lake),
so a healthy job never meets it; the backup engine (#966 Q1) tunes them from measured runs.

Every other await inside an admission, in a job's end or in the boot pass has its own bound
below (SR-BK7-01, SR-BK7A-02): a stalled one holds the admission lock, its job's lane, or boot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from candleviewer.admin.backups.ports import JobKind

#: How long an admission waits for the admission lock before it is refused, retryable (503).
ADMIT_WAIT_S: Final = 5.0
_HOUR: Final = 3600.0
#: How long an admitted job may run before it fails `internal_error` and frees its lane.
JOB_DEADLINE_S: Final[Mapping[JobKind, float]] = {
    "backup": 24 * _HOUR,
    "backup_verify": 12 * _HOUR,
    "backup_restore": 24 * _HOUR,
}
RESOLVE_BUDGET_S: Final = 2.0  # one artefact resolve, under the admission lock
LINK_RECORD_BUDGET_S: Final = 2.0  # one `backup.downloaded` record
#: `createBackup`: "A user may start at most 4 runs in a rolling hour"; a run counts once its
#: `requested` record is written, and so does a refusal of an unencrypted plan once its record is.
RUNS_PER_HOUR: Final = 4
PLAN_BUDGET_S: Final = 2.0  # the engine's `plan`, under the admission lock
RECORD_BUDGET_S: Final = 2.0  # one `backup.run` record
WRITE_BUDGET_S: Final = 2.0  # one catalogue write; the store caps each statement at 1 s itself
WRITE_TRIES: Final = 2  # a run's end: each update ends a row only while `running`, so retry-safe
LOST_READ_BUDGET_S: Final = 2.0  # the boot pass's one page of `running` rows
LOST_RUNS_LIMIT: Final = 16  # `running` rows a boot ends; any more wait for the next boot
