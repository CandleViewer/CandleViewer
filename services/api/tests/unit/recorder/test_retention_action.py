"""Unit (#2188 S2c): both retention readers read a stored `retention_policies` row by its `action`
through one mapping (`read_policy_row`), and the reaper and the roll-off act on it alike. The
readers are the real ones over fake rows; the stores are the in-memory fakes of E16-T05/T06.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.recorder.retention import US_PER_DAY, PolicyRow, RetentionConfig
from candleviewer.recorder.retention_defaults import STREAM_DEFAULTS, canonical_stream
from candleviewer.retention_wiring import PgRetentionFacts
from candleviewer.storage.models import StreamKind
from candleviewer.storage.retention.policy import RowReading, read_policy_row
from tests.unit.recorder._retention_fakes import NOW_US, FakeFacts, T, World, day, manager
from tests.unit.recorder.test_retention_wiring import _Rel
from tests.unit.recorder.test_rolloff import FakeArchiver, FakeHot, FakeMarks, _job
from tests.unit.storage.test_recorder_repository_unit import _ARCHIVE, _DROP, _repo

SYM = "BTCUSDT"


class _Facts(FakeFacts):
    """The world's symbols and pins; the policies are the real `PgRetentionFacts` over fake rows."""

    def __init__(
        self, w: World, stream: StreamKind, days: int, action: str, db_stream: str | None = None
    ) -> None:
        super().__init__(w)
        label = db_stream or stream.value  # the DB's spelling, when a test gives one
        row = dict(scope="symbol", symbol=SYM, stream=label, retain_days=days, action=action)
        self._pg = PgRetentionFacts(_Rel([row]))  # type: ignore[arg-type]  # fake relational repo

    async def policies(self) -> Mapping[tuple[str | None, str], PolicyRow]:
        return await self._pg.policies()


def _config(stream: StreamKind) -> RetentionConfig:
    return RetentionConfig(hot_streams=(stream,), cold_streams=(stream,), hard_default=(7, 30))


@pytest.mark.parametrize("action", ["archive_parquet", "downsample", "pin", "a_later_action"])
def test_drop_is_the_total_horizon_and_any_other_action_the_hot_window(action: str) -> None:
    assert read_policy_row("drop", 7) == RowReading(7, 7)
    assert read_policy_row(action, 7) == RowReading(7, None)


@pytest.mark.parametrize("days", [0, -3])
def test_a_drop_row_below_one_day_reads_as_archive_parquet(days: int) -> None:
    """The DDL's `rp_days` refuses it; if one ever arrives, it states no horizon (fail closed)."""
    assert read_policy_row("drop", days) == RowReading(days, None)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    action=st.sampled_from(["drop", "archive_parquet", "downsample", "pin"]),
    stream=st.sampled_from([StreamKind.TRADES, StreamKind.KLINES, StreamKind.LIQUIDATIONS]),
    days=st.integers(1, 60),
    cold=st.sets(st.integers(1, 800), max_size=8),
    hot=st.sets(st.integers(2, 40), max_size=5),
    mark=st.integers(0, 45),
    pinned=st.booleans(),
)
async def test_property_a_drop_row_deletes_at_n_and_never_before_other_rows_wait_for_the_total(
    action: str,
    stream: StreamKind,
    days: int,
    cold: set[int],
    hot: set[int],
    mark: int,
    pinned: bool,
) -> None:
    """For any N and ages: a `drop` row deletes a cold partition exactly once it is N days old
    (klines, liquidations, whose §7 total is forever, included); the other actions none inside
    the §7 total; no hot day goes unarchived or inside its window; a pin loses nothing."""
    w = World()
    w.pinned = {SYM} if pinned else set()
    cold |= {days + offset for offset in range(-2, 3) if days + offset >= 1}  # the horizon itself
    keys = {n: w.add_cold(SYM, stream, n) for n in cold}
    for n in hot:
        w.add_hot(stream, n, {SYM: 3})
    w.archived[(SYM, stream)] = day(mark)
    w.facts = _Facts(w, stream, days, action)
    await manager(w, config=_config(stream)).run_nightly()

    section7 = STREAM_DEFAULTS[stream.value][1]
    total = days if action == "drop" else section7 and max(section7, days)  # None = forever
    due = {n for n in cold if total and day(n) + US_PER_DAY <= NOW_US - total * US_PER_DAY}
    gone = {n for n, key in keys.items() if key not in w.cold.get((SYM, stream), {})}
    assert gone == (set() if pinned else due)
    for n in hot:
        if day(n) not in w.hot[stream]:  # a hot day dropped
            assert not pinned
            assert day(n) + US_PER_DAY <= NOW_US - days * US_PER_DAY  # past its hot window
            assert day(mark) >= day(n) + US_PER_DAY  # and archived through its end


@pytest.mark.parametrize("db_stream", ["klines", "liquidations", "open_interest", "funding"])
async def test_a_drop_row_on_a_stream_kept_forever_deletes_at_n_and_says_so_once(
    db_stream: str,
) -> None:
    """§7 keeps these four forever, so a `drop` row is their first delete, by intent: the cold
    partition N days old goes, the one a day short stays; the row is logged once, not per read."""
    stream = StreamKind(canonical_stream(db_stream))
    assert STREAM_DEFAULTS[stream.value][1] is None
    w = World()
    kept, due = w.add_cold(SYM, stream, 20), w.add_cold(SYM, stream, 21)
    w.facts = facts = _Facts(w, stream, 20, "drop", db_stream=db_stream)
    with capture_logs() as logs:
        await manager(w, config=_config(stream)).run_nightly()
        await facts.policies()
    assert set(w.cold[(SYM, stream)]) == {kept} and due not in w.cold[(SYM, stream)]
    assert [e for e in logs if e["event"] == "retention_drop_finite_total"] == [
        {"event": "retention_drop_finite_total", "log_level": "warning", "symbol": SYM,
         "stream": stream.value, "retain_days": 20}
    ]  # fmt: skip


async def test_rolloff_a_drop_row_never_holds_a_shared_day_from_archiving() -> None:
    """Read as `None`, a `drop` row would make `_window_ok` refuse every day its symbol shares, and
    nothing would delete those days. Read by the real reader it is a window that ages out."""
    repos = {"DROPPER": _repo([{**_DROP, "retain_days": 5}])[0], "KEEPER": _repo([_ARCHIVE])[0]}

    async def hot_days(symbol: str, kind: StreamKind) -> int | None:  # as `rolloff_wiring`'s
        return await repos[symbol].resolve_policy(symbol, kind.value)

    shared = ["DROPPER", "KEEPER"]
    hot, arch = FakeHot({T: {day(10): shared, day(6): shared}}), FakeArchiver()
    report = await _job(hot, arch, FakeMarks(), hot_days=hot_days).run()
    assert report.dropped == [(T, day(10))]  # day(6) is still inside DROPPER's own 5 d window
    assert {sym for sym, _ in arch.calls} == set(shared)
