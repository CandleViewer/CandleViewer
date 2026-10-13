"""Tier selection (E26-T02, ADR-0035 decision 4): one tier per session; `auto` reads Parquet
when the whole range is manifested, QuestDB when none of it is, and refuses anything else."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.replay import (
    ReplayItem,
    ReplaySourceUnavailable,
    ReplayTierStraddle,
    SourceTier,
)
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent
from candleviewer.storage.testing import StaticArchiveCoverage
from tests.unit.replay._events import SECOND, T0, Harness, digest, request, ticker, trade


def ids(items: Sequence[ReplayItem]) -> list[str]:
    return [str(item.tiebreak[0]) for item in items if isinstance(item, RecordedEvent)]


def recording() -> list[RecordedEvent]:
    return [trade(t * SECOND, trade_id=f"r{t:02}") for t in range(60)]


async def test_a_wholly_archived_session_reads_parquet_only_and_equals_questdb() -> None:
    """Ticket AC 2 under decision 4: the same window from either tier is byte-identical."""
    cold = Harness(cold=recording(), hot=[trade(SECOND, trade_id="stale")], archived=True)
    hot = Harness(hot=recording(), req=request(tier="questdb"))

    got = await cold.read_all(window_us=7 * SECOND)

    assert digest(got) == digest(await hot.read_all())
    assert cold.hot.reads == 0 and len(got) == 60


async def test_an_unarchived_session_reads_questdb_only() -> None:
    harness = Harness(cold=[trade(SECOND, trade_id="cold")], hot=[trade(SECOND, trade_id="hot")])

    assert ids(await harness.read_all()) == ["hot"]
    assert harness.cold.reads == 0


@pytest.mark.parametrize(("lo", "hi"), [(0, 30 * SECOND), (10 * SECOND, 20 * SECOND)])
async def test_a_partly_archived_range_is_refused_before_any_read(lo: int, hi: int) -> None:
    """A straddle is never stitched across tiers, and never read as a hole (C-2.14)."""
    harness = Harness(cold=recording()[:30], hot=recording()[30:]).archive(lo, hi)

    with pytest.raises(ReplayTierStraddle) as raised:
        await harness.read_all()

    assert raised.value.archived == (TimeRange(start_us=T0 + lo, end_us=T0 + hi),)
    assert raised.value.stream is StreamKind.TRADES
    assert harness.hot.reads == harness.cold.reads == 0


async def test_streams_archived_unevenly_are_refused_naming_the_first_mismatch() -> None:
    req = request(streams=(StreamKind.TRADES, StreamKind.TICKERS))
    harness = Harness(hot=[ticker(SECOND)], req=req).archive(
        0, 60 * SECOND, streams=[StreamKind.TRADES]
    )

    with pytest.raises(ReplayTierStraddle) as raised:
        await harness.read_all()

    assert (raised.value.stream, raised.value.archived) == (StreamKind.TICKERS, ())


class _RolledOffDuringRead(StaticArchiveCoverage):
    """A roll-off manifests the whole range while QuestDB serves the session's second read."""

    async def archived(self, symbol: str, stream: StreamKind, rng: TimeRange) -> list[TimeRange]:
        if self.calls == 2:  # calls: session resolution, check after read 1, check after read 2
            self.archive(symbol, stream, TimeRange(start_us=T0, end_us=T0 + 60 * SECOND))
        return await super().archived(symbol, stream, rng)


async def test_a_span_archived_mid_session_ends_the_questdb_replay_with_a_typed_error() -> None:
    harness = Harness(hot=recording()).replace_ports(coverage=_RolledOffDuringRead())

    with pytest.raises(ReplaySourceUnavailable) as raised:
        await harness.read_all(batch=1, window_us=10 * SECOND)

    assert (raised.value.tier, raised.value.reason) == ("questdb", "archived_during_replay")
    assert harness.hot.reads == 2


@pytest.mark.parametrize(("tier", "want"), [("questdb", ["hot"]), ("parquet", ["cold"])])
async def test_an_explicit_tier_never_consults_the_manifests(
    tier: SourceTier, want: list[str]
) -> None:
    harness = Harness(
        cold=[trade(SECOND, trade_id="cold")],
        hot=[trade(SECOND, trade_id="hot")],
        req=request(tier=tier),
    ).archive(0, 30 * SECOND)

    assert ids(await harness.read_all()) == want
    assert harness.coverage.calls == 0


async def test_the_session_tier_is_resolved_and_logged_once_and_reads_are_counted() -> None:
    labels = {"stream": "trades", "tier": "parquet"}
    before = REGISTRY.get_sample_value("replay_events_read_total", labels) or 0.0
    harness = Harness(cold=recording(), archived=True)

    with capture_logs() as logs:
        await harness.read_all(window_us=5 * SECOND)

    tiers = [entry["tier"] for entry in logs if entry["event"] == "replay_source_tier"]
    assert tiers == ["parquet"] and harness.coverage.calls == 1
    assert REGISTRY.get_sample_value("replay_events_read_total", labels) == before + 60
