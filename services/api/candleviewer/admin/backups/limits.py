"""Backups limits (E42-T05, #966): the one module the backups services' budgets live in (Q5).

The job deadlines are a backstop for a hung engine, not a performance budget. Each is set past
the slowest healthy v1 job of its kind (a run includes the first restic sync of the Parquet lake),
so a healthy job never meets it; the backup engine (#966 Q1) tunes them from measured runs."""

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
