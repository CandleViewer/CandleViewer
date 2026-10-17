"""Unit tests for the runner's WAL-apply wait (#3064).

`_cv_migrations` is a WAL table: an INSERT is visible to a SELECT only after QuestDB's apply job
ran, so a second `run_migrations` pass could miss the newest record and re-run its file ("column
'batch_index' already exists"). No docker: the executors below script what `wal_tables()` and the
SELECT answer; the real engine is `tests/integration/storage/test_questdb_hot_tier.py`.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from candleviewer.storage.errors import StorageError, StorageWalNotApplied
from candleviewer.storage.questdb.runner import run_migrations, wait_for_wal_apply

DDL_DIR = Path(__file__).resolve().parents[6] / "backend" / "db" / "questdb"

#: The status query is a fixed literal: the table name is a bind value, never interpolated.
_WAL_SQL = "SELECT writerTxn, sequencerTxn, suspended FROM wal_tables() WHERE name = $1"

_ADD_COLUMN = re.compile(r"ALTER TABLE (?P<table>\w+) ADD COLUMN (?P<column>\w+)", re.IGNORECASE)


class _FakeClock:
    """Monotonic seconds; the fake `sleep` advances it, so wall-clock bounds need no real time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        assert self.now < 1_000.0, "runaway wait: the wall-clock bound never tripped"
        self.slept.append(seconds)
        self.now += seconds


def _wal(writer: object, sequencer: object, *, suspended: bool = False) -> dict[str, object]:
    """One `wal_tables()` row: what the apply job has done (`writerTxn`) vs what was committed."""
    return {"writerTxn": writer, "sequencerTxn": sequencer, "suspended": suspended}


class _ScriptedWal:
    """A `QuestDbExecutor` whose `wal_tables()` answers follow a script: one answer per poll, the
    last one repeating (the apply job's progress as the runner sees it). It only ever reads."""

    def __init__(self, script: list[list[dict[str, object]]]) -> None:
        self._script = script
        self.polls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, sql: str, *args: object) -> None:
        raise AssertionError("the wait must only read")

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        self.polls.append((sql, args))
        return self._script[min(len(self.polls), len(self._script)) - 1]


class _HungWal:
    """The status poll is accepted and never answers."""

    def __init__(self) -> None:
        self.polling = asyncio.Event()

    async def execute(self, sql: str, *args: object) -> None:
        raise AssertionError("the wait must only read")

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        self.polling.set()
        await asyncio.Event().wait()
        return []


async def test_wait_for_wal_apply_returns_at_once_when_the_writer_has_caught_up() -> None:
    clock, wal = _FakeClock(), _ScriptedWal([[_wal(7, 7)]])
    await wait_for_wal_apply(wal, "_cv_migrations", sleep=clock.sleep, clock=clock)
    assert wal.polls == [(_WAL_SQL, ("_cv_migrations",))]
    assert clock.slept == []


async def test_wait_for_wal_apply_polls_with_doubling_backoff_until_the_writer_converges() -> None:
    clock = _FakeClock()
    wal = _ScriptedWal([[_wal(4, 7)], [_wal(5, 7)], [_wal(6, 7)], [_wal(7, 7)]])
    await wait_for_wal_apply(wal, "_cv_migrations", sleep=clock.sleep, clock=clock)
    assert len(wal.polls) == 4
    assert clock.slept == [0.02, 0.04, 0.08]


@pytest.mark.parametrize(
    "status",
    [[], [_wal(-1, 0)]],
    ids=["not-a-wal-table", "no-txn-committed-yet"],
)
async def test_wait_for_wal_apply_nothing_pending_returns_at_once(
    status: list[dict[str, object]],
) -> None:
    """No `wal_tables()` row = not a WAL table; sequencerTxn 0 = nothing was ever committed."""
    clock, wal = _FakeClock(), _ScriptedWal([status])
    await wait_for_wal_apply(wal, "t", sleep=clock.sleep, clock=clock)
    assert len(wal.polls) == 1 and clock.slept == []


async def test_wait_for_wal_apply_never_converging_raises_a_typed_timeout_after_the_bound() -> None:
    clock, wal = _FakeClock(), _ScriptedWal([[_wal(4, 7)]])
    with pytest.raises(StorageWalNotApplied) as exc:
        await wait_for_wal_apply(
            wal, "_cv_migrations", timeout_s=2.0, sleep=clock.sleep, clock=clock
        )
    err = exc.value
    assert isinstance(err, StorageError)
    assert err.reason == "timeout" and "reason=timeout" in str(err)
    assert err.table == "_cv_migrations"
    assert 2.0 <= err.waited_s < 2.25 and err.waited_s == pytest.approx(sum(clock.slept))
    assert clock.slept[:5] == [0.02, 0.04, 0.08, 0.16, 0.25]
    assert max(clock.slept) == 0.25  # the backoff doubles from 20 ms and caps at 250 ms


async def test_wait_for_wal_apply_suspended_table_fails_fast_without_waiting() -> None:
    """A suspended apply can never catch up: do not burn the bound, say so."""
    clock, wal = _FakeClock(), _ScriptedWal([[_wal(4, 7, suspended=True)]])
    with pytest.raises(StorageWalNotApplied) as exc:
        await wait_for_wal_apply(wal, "_cv_migrations", sleep=clock.sleep, clock=clock)
    assert exc.value.reason == "suspended" and "reason=suspended" in str(exc.value)
    assert len(wal.polls) == 1 and clock.slept == []


@pytest.mark.parametrize(
    "row",
    [{"name": "t"}, _wal("n/a", 3), _wal(None, 3), _wal(3, None)],
    ids=["no-txn-columns", "unparsable-writer-txn", "null-writer-txn", "null-sequencer-txn"],
)
async def test_wait_for_wal_apply_status_without_readable_txns_fails_closed(
    row: dict[str, object],
) -> None:
    """A shape we cannot read must never read as 'caught up': that would reopen the race."""
    clock, wal = _FakeClock(), _ScriptedWal([[row]])
    with pytest.raises(StorageWalNotApplied) as exc:
        await wait_for_wal_apply(wal, "t", sleep=clock.sleep, clock=clock)
    assert exc.value.reason == "unexpected_shape"
    assert len(wal.polls) == 1 and clock.slept == []  # no retry on a shape we cannot read


async def test_wait_for_wal_apply_hung_poll_is_a_typed_timeout() -> None:
    with pytest.raises(StorageWalNotApplied) as exc:
        # The 10 ms wall-clock bound trips; the 5 s guard only fails a hang.
        await asyncio.wait_for(
            wait_for_wal_apply(_HungWal(), "_cv_migrations", timeout_s=0.01), timeout=5
        )
    assert exc.value.reason == "timeout"


async def test_wait_for_wal_apply_cancellation_is_not_swallowed() -> None:
    wal = _HungWal()
    task = asyncio.create_task(wait_for_wal_apply(wal, "_cv_migrations"))
    await wal.polling.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_wait_for_wal_apply_logs_one_warning_per_failure_and_nothing_per_poll() -> None:
    clock = _FakeClock()
    with capture_logs() as quiet:
        script = [[_wal(1, 3)], [_wal(2, 3)], [_wal(3, 3)]]
        await wait_for_wal_apply(_ScriptedWal(script), "t", sleep=clock.sleep, clock=clock)
    assert quiet == []  # three polls, two waits: nothing logged
    with capture_logs() as logs, pytest.raises(StorageWalNotApplied):
        stuck = _ScriptedWal([[_wal(1, 3, suspended=True)]])
        await wait_for_wal_apply(stuck, "t", sleep=clock.sleep, clock=clock)
    assert [(e["event"], e["log_level"], e["table"], e["reason"]) for e in logs] == [
        ("questdb_wal_not_applied", "warning", "t", "suspended")
    ]


#: How many `wal_tables()` polls the apply job needs, after an INSERT, to make the record visible.
_APPLY_LAG_POLLS = 2


class _LaggingMigrationsExecutor:
    """`_cv_migrations` as QuestDB serves it (#3064).

    An INSERT is acknowledged once committed (`recorded`) but a SELECT sees only what the apply job
    applied (`applied`). Time passes between statements, so each INSERT first applies everything
    earlier: only the newest record is ever behind, and needs `_APPLY_LAG_POLLS` status polls. Like
    the server, it rejects a plain `ADD COLUMN` of an existing column.
    """

    def __init__(self, *, suspended: bool = False) -> None:
        self.suspended = suspended
        self.recorded: list[str] = []
        self.applied = 0
        self.wal_polls = 0
        self.executed: list[str] = []
        self._polls_to_apply = 0
        self._added: set[tuple[str, str]] = set()

    async def execute(self, sql: str, *args: object) -> None:
        self.executed.append(sql)
        text = " ".join(sql.split())
        if text.upper().startswith("INSERT INTO _CV_MIGRATIONS"):
            self.applied = len(self.recorded)
            self.recorded.append(str(args[0]))
            self._polls_to_apply = _APPLY_LAG_POLLS
        elif (match := _ADD_COLUMN.match(text)) is not None:
            column = (match["table"].lower(), match["column"].lower())
            if column in self._added:
                raise RuntimeError(f"column '{match['column']}' already exists")
            self._added.add(column)

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        if "wal_tables" in sql:
            self.wal_polls += 1
            if self._polls_to_apply and not self.suspended:
                self._polls_to_apply -= 1
                if not self._polls_to_apply:
                    self.applied = len(self.recorded)
            return [_wal(self.applied, len(self.recorded), suspended=self.suspended)]
        assert "_cv_migrations" in sql, sql
        return [{"filename": name} for name in sorted(self.recorded[: self.applied])]


async def test_second_pass_waits_for_the_newest_migration_record_to_be_applied() -> None:
    """#3064: the second pass missed the newest record and re-ran 0005 ("column 'batch_index'
    already exists"). It must wait for the apply job, read every record and apply nothing."""
    clock, executor = _FakeClock(), _LaggingMigrationsExecutor()
    first = await run_migrations(executor, DDL_DIR, sleep=clock.sleep)
    assert len(first) == 5 and first[-1] == "0005_liquidations_batch_index.sql"
    # Precondition: the fake really lags. Read right now, the newest record is not there yet:
    # the stale read the old second pass acted on.
    stale = await executor.fetch("SELECT filename FROM _cv_migrations")
    assert [row["filename"] for row in stale] == first[:-1]

    second = await run_migrations(executor, DDL_DIR, sleep=clock.sleep)

    assert second == []
    assert clock.slept == [0.02]  # one backoff: the second status poll saw the apply caught up
    assert executor.wal_polls == 3  # one on the fresh table, two before the second read


async def test_suspended_migrations_table_raises_instead_of_re_running_ddl() -> None:
    """A suspended apply never shows the newest record: a typed error, not a stale read that
    re-runs a file's DDL against a live schema."""
    clock, executor = _FakeClock(), _LaggingMigrationsExecutor(suspended=True)
    await run_migrations(executor, DDL_DIR, sleep=clock.sleep)
    ddl_before = len(executor.executed)
    with pytest.raises(StorageWalNotApplied) as exc:
        await run_migrations(executor, DDL_DIR, sleep=clock.sleep)
    assert (exc.value.reason, exc.value.table) == ("suspended", "_cv_migrations")
    # Only the `_cv_migrations` bootstrap ran again: no migration statement was re-issued.
    assert len(executor.executed) == ddl_before + 1
    assert "CREATE TABLE IF NOT EXISTS _cv_migrations" in executor.executed[-1]
