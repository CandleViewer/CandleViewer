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
#: The restore guard (BK-13) under the lock: each read alone (maintenance, the row, its bound
#: digest, the positions, #3084's check), and each `backup.restore` record, its job's end too.
RESTORE_READ_BUDGET_S: Final = 2.0
RESTORE_RECORD_BUDGET_S: Final = 2.0
_HOUR: Final = 3600.0
#: How long an admitted job may run before it fails `internal_error` and frees its lane.
JOB_DEADLINE_S: Final[Mapping[JobKind, float]] = {
    "backup": 24 * _HOUR,
    "backup_verify": 12 * _HOUR,
    "backup_restore": 24 * _HOUR,
}
#: `issueBackupDownload`: a user may issue at most 10 links per hour; one counts from its check.
LINKS_PER_HOUR: Final = 10
#: A link issue holds the lock 4.5 s at worst (read 2, resolve, record 2): under `ADMIT_WAIT_S`.
RESOLVE_BUDGET_S: Final = 0.5  # one artefact resolve: a walk of the path and an fstat
LINK_RECORD_BUDGET_S: Final = 2.0  # one `backup.downloaded` record
#: `createBackup`: "A user may start at most 4 runs in a rolling hour"; a run counts once its
#: `requested` record is written, and so does a refusal of an unencrypted plan once its record is.
RUNS_PER_HOUR: Final = 4
PLAN_BUDGET_S: Final = 2.0  # the engine's `plan`, under the admission lock
RECORD_BUDGET_S: Final = 2.0  # one `backup.run` record
#: A catalogue write, a run's end (BK-8) or a delete's mark (BK-12), and its tries: each write is
#: guarded (a run ends only while `running`, a mark lands only while `deleted_at IS NULL`), so a
#: try after a commit lost on the way back changes nothing.
WRITE_BUDGET_S: Final = 2.0  # one catalogue write; the store caps each statement at 1 s itself
WRITE_TRIES: Final = 2
LOST_READ_BUDGET_S: Final = 2.0  # the boot pass's one page of `running` rows
LOST_RUNS_LIMIT: Final = 16  # `running` rows a boot ends; any more wait for the next boot
#: Under the admission lock `deleteBackup` (BK-12) waits on the catalogue twice (the row and the
#: usable count, `READ_BUDGET_S` each), on its `backup.deleted` records, the engine's `remove`, the
#: guarded mark (`WRITE_BUDGET_S`, `WRITE_TRIES` times) and the freshness reload (`READ_BUDGET_S`).
#: A healthy delete holds the lock for milliseconds; with every budget spent, 22 s, past
#: `ADMIT_WAIT_S`, so an admission waiting meanwhile is refused `503 store_unavailable`, retryable.
DELETE_RECORD_BUDGET_S: Final = 2.0  # one `backup.deleted` record, as `AUDIT_TIMEOUT_S`
REMOVE_BUDGET_S: Final = 10.0  # the engine's `remove` of one artefact: a backstop for a hung engine
#: `downloadBackup` (BK-11): "At most 10 fetches per user per hour", counted at each spend, a
#: refused fetch's included.
FETCHES_PER_HOUR: Final = 10
#: A fetch's reads of its link's session family and its user's permissions, together.
FETCH_READ_BUDGET_S: Final = 2.0
#: One read of a served artefact (a 1 MiB chunk): past it the download is cut.
STREAM_READ_BUDGET_S: Final = 30.0
