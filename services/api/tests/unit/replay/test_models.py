"""Replay domain types (E26-T02): the validated request, the gap marker and typed errors."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from candleviewer.replay import (
    ReplayError,
    ReplayGap,
    ReplayMemoryCeilingExceeded,
    ReplayRequest,
    ReplayRequestInvalid,
    ReplaySourceUnavailable,
    ReplayTiers,
    ReplayTierStraddle,
)
from candleviewer.replay.models import MAX_REPLAY_SPAN
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.testing import (
    InMemoryRecordedTier,
    StaticArchiveCoverage,
    StaticGapReader,
)

START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
GOOD: dict[str, object] = {
    "symbols": ("BTCUSDT", "ETHUSDT"),
    "streams": (StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA),
    "start": START,
    "end": START + timedelta(hours=1),
}


def test_request_defaults_to_auto_tier_at_depth_200() -> None:
    req = ReplayRequest.model_validate(GOOD)

    assert (req.source_tier, req.depth) == ("auto", 200)


def test_request_bounds_are_exact_epoch_microseconds() -> None:
    start = datetime(2026, 10, 1, 12, 0, 0, 123_457, tzinfo=UTC)
    req = ReplayRequest.model_validate(GOOD | {"start": start, "end": start + timedelta(1)})

    assert req.start_us == 1_790_856_000_123_457
    assert req.end_us - req.start_us == 86_400_000_000


def test_request_accepts_any_utc_offset_as_the_same_instant() -> None:
    plus_two = timezone(timedelta(hours=2))
    req = ReplayRequest.model_validate(GOOD | {"start": START.astimezone(plus_two)})

    assert req.start_us == ReplayRequest.model_validate(GOOD).start_us


@pytest.mark.parametrize(
    "override",
    [
        {"start": datetime(2026, 10, 1, 12, 0)},  # naive: not tz-aware UTC
        {"end": START},  # empty window
        {"end": START - timedelta(seconds=1)},  # reversed window
        {"symbols": ()},
        {"symbols": ("BTCUSDT", "BTCUSDT")},
        {"symbols": tuple(f"SYM{i}USDT" for i in range(9))},  # > 8, the OpenAPI bound
        {"symbols": ("btc/usdt",)},
        {"streams": ()},
        {"streams": (StreamKind.TRADES, StreamKind.TRADES)},
        {"streams": (StreamKind.BARS,)},  # derived data is rebuilt, never replayed
        {"depth": 100},
        {"source_tier": "hot"},
        {"speed": 2},  # extra fields are refused
    ],
)
def test_invalid_requests_are_rejected(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ReplayRequest.model_validate(GOOD | override)


def test_request_and_gap_marker_are_immutable() -> None:
    req = ReplayRequest.model_validate(GOOD)
    gap = ReplayGap(1, "BTCUSDT", StreamKind.TRADES, 0, 5, "ws_disconnect")

    depth, cause = "depth", "cause"  # attribute names as data: the assignment is the test
    with pytest.raises(ValidationError):
        setattr(req, depth, 50)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(gap, cause, "other")


def test_a_window_over_the_cap_is_refused_and_one_at_the_cap_accepted() -> None:
    """Security notes: the window cap bounds every read, so no request scans the whole lake."""
    at_cap = ReplayRequest.model_validate(GOOD | {"end": START + MAX_REPLAY_SPAN})

    assert at_cap.end_us - at_cap.start_us == MAX_REPLAY_SPAN // timedelta(microseconds=1)
    with pytest.raises(ValidationError, match="24 h cap"):
        over = START + MAX_REPLAY_SPAN + timedelta(microseconds=1)
        ReplayRequest.model_validate(GOOD | {"end": over})


def test_tier_ports_accept_the_storage_fakes() -> None:
    tiers = ReplayTiers(
        hot=InMemoryRecordedTier(),
        cold=InMemoryRecordedTier(),
        coverage=StaticArchiveCoverage(),
        gaps=StaticGapReader(),
    )

    assert tiers.hot is not tiers.cold


def test_errors_carry_stable_codes_and_context_without_values() -> None:
    ceiling = ReplayMemoryCeilingExceeded(
        budget_bytes=1024, symbol="BTCUSDT", stream=StreamKind.ORDERBOOK_DELTA
    )
    unavailable = ReplaySourceUnavailable(
        tier="questdb", symbol="BTCUSDT", stream=None, reason="timeout"
    )
    archived = [TimeRange(start_us=0, end_us=10)]
    straddle = ReplayTierStraddle(symbol="BTCUSDT", stream=StreamKind.TRADES, archived=archived)

    assert [e.code for e in (ceiling, unavailable, straddle)] == [
        "REPLAY_MEMORY_CEILING_EXCEEDED",
        "REPLAY_SOURCE_UNAVAILABLE",
        "REPLAY_TIER_STRADDLE",
    ]
    assert "orderbook_delta" in str(ceiling) and "1024" in str(ceiling)
    assert "recording_gaps" in str(unavailable) and unavailable.reason == "timeout"
    assert straddle.archived == tuple(archived) and "trades" in str(straddle)
    assert issubclass(ReplayRequestInvalid, ValueError)
    assert all(
        issubclass(e, ReplayError)
        for e in (ReplayMemoryCeilingExceeded, ReplaySourceUnavailable, ReplayTierStraddle)
    )
