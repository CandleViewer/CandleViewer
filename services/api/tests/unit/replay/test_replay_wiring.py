"""E26-T01 composition root: the coverage adapter and the session-service wiring in `app.py`."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from candleviewer.app import _attach_replay_sessions, _build_replay_sessions, _ReplayCoverage
from candleviewer.recorder.coverage import CoveredInterval, GapInterval, StreamCoverage
from candleviewer.replay.service import ReplayService
from candleviewer.replay.sessions_service import ReplayLimits
from candleviewer.settings import Settings


class _CoverageService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], int, int]] = []

    async def coverage(self, symbol: str, streams: list[str], lo: int, hi: int) -> Any:
        self.calls.append((symbol, list(streams), lo, hi))
        trades = StreamCoverage(
            stream="trades",
            intervals=(CoveredInterval(10, 20, "questdb"), CoveredInterval(30, 40, "parquet")),
            gaps=(GapInterval(20, 30, "ws_disconnect"),),
        )
        return [trades]


async def test_replay_coverage_adapter_reads_the_recorded_trades_intervals() -> None:
    source = _CoverageService()
    window = await _ReplayCoverage(cast(Any, source)).window("BTCUSDT", 0, 50)
    assert window.covered == ((10, 20), (30, 40))
    assert source.calls == [("BTCUSDT", ["trades"], 0, 50)]


def test_build_replay_sessions_takes_its_limits_from_the_settings() -> None:
    settings = Settings(  # type: ignore[call-arg]  # pydantic-settings kwarg
        _env_file=None,
        replay_idle_ttl_s=600,
        replay_reclaim_interval_s=5,
        replay_max_sessions_per_user=3,
        replay_max_window_hours=6,
    )
    sessions = _build_replay_sessions(
        settings, cast(Any, object()), cast(Any, _CoverageService()), cast(Any, object())
    )
    assert sessions.limits == ReplayLimits(
        idle_ttl=timedelta(seconds=600),
        max_sessions_per_user=3,
        max_window=timedelta(hours=6),
        reclaim_interval_s=5.0,
    )


@pytest.mark.parametrize(
    ("with_pg", "with_coverage", "attached"),
    [(False, False, False), (True, False, False), (False, True, False), (True, True, True)],
)
def test_replay_sessions_are_attached_only_with_postgres_and_coverage(
    with_pg: bool, with_coverage: bool, attached: bool
) -> None:
    ctx = SimpleNamespace(replay=ReplayService(), audit=object())
    pg = object() if with_pg else None
    coverage = _CoverageService() if with_coverage else None
    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # pydantic-settings kwarg
    _attach_replay_sessions(cast(Any, ctx), settings, cast(Any, pg), cast(Any, coverage))
    assert (ctx.replay.sessions is not None) is attached
