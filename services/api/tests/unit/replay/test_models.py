"""Replay domain types (E26-T02): the validated request, the gap marker and typed errors."""

from __future__ import annotations

import calendar
import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.replay import (
    ReplayError,
    ReplayGap,
    ReplayInternalError,
    ReplayMemoryCeilingExceeded,
    ReplayRequest,
    ReplayRequestInvalid,
    ReplaySourceUnavailable,
    ReplayTiers,
    ReplayTierStraddle,
    SourceTier,
)
from candleviewer.replay.models import MAX_SPAN_CEILING_US
from candleviewer.settings import Settings
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    REPLAYABLE_STREAMS,
    ManifestCoverage,
    RecordedStreamReader,
    RecordingGapReader,
)
from candleviewer.storage.testing import (
    InMemoryRecordedTier,
    StaticGapReader,
    StaticManifestCoverage,
)

START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
GOOD: dict[str, object] = {
    "symbols": ("BTCUSDT", "ETHUSDT"),
    "streams": (StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA),
    "start": START,
    "end": START + timedelta(hours=1),
}
#: E26-T01's `CV_REPLAY_MAX_WINDOW_HOURS`: default 24, at most 24 x 31 (`settings.py`).
DAY = timedelta(hours=24)
US = timedelta(microseconds=1)
HOUR_US = 3_600_000_000


def oracle_us(moment: datetime) -> int:
    """Integer-only epoch microseconds: whole UTC seconds from `calendar.timegm`, plus the
    microsecond field. No float on any path, so a float conversion cannot agree by accident."""
    return calendar.timegm(moment.utctimetuple()) * 1_000_000 + moment.microsecond


_OFFSETS = st.sampled_from(
    [UTC, timezone(timedelta(hours=14)), timezone(-timedelta(hours=12)), timezone(timedelta(0))]
)
_MOMENTS = st.datetimes(
    min_value=datetime(2, 1, 1), max_value=datetime(9998, 12, 31), timezones=_OFFSETS
)


def test_request_defaults_to_auto_tier_at_depth_200() -> None:
    req = ReplayRequest.model_validate(GOOD)

    assert (req.source_tier, req.depth) == ("auto", 200)


def test_the_window_cap_defaults_to_24_hours_in_microseconds() -> None:
    assert ReplayRequest.model_validate(GOOD).max_span_us == 86_400_000_000


@given(start=_MOMENTS, span_us=st.integers(1, 24 * HOUR_US))
@example(start=datetime(9998, 12, 31, 23, 59, 59, 999_999, tzinfo=UTC), span_us=1)
@example(start=datetime(1969, 12, 31, 23, 59, 59, 999_999, tzinfo=UTC), span_us=2)
@example(start=datetime(2026, 10, 1, 12, 0, 0, 123_457, tzinfo=UTC), span_us=24 * HOUR_US)
def test_request_bounds_are_exact_epoch_microseconds(start: datetime, span_us: int) -> None:
    """Year 9998 is where float seconds lose whole microseconds; 1969 is where truncation
    toward zero picks the wrong second."""
    end = start + timedelta(microseconds=span_us)

    req = ReplayRequest.model_validate(GOOD | {"start": start, "end": end})

    assert (req.start_us, req.end_us) == (oracle_us(start), oracle_us(end))


def test_request_accepts_any_utc_offset_as_the_same_instant() -> None:
    plus_two = timezone(timedelta(hours=2))
    req = ReplayRequest.model_validate(GOOD | {"start": START.astimezone(plus_two)})

    assert req.start_us == ReplayRequest.model_validate(GOOD).start_us


def test_eight_symbols_are_accepted() -> None:
    symbols = tuple(f"SYM{i}USDT" for i in range(8))

    assert ReplayRequest.model_validate(GOOD | {"symbols": symbols}).symbols == symbols


@pytest.mark.parametrize("depth", [1, 50, 200, 500])
def test_each_recorded_book_depth_is_accepted(depth: int) -> None:
    assert ReplayRequest.model_validate(GOOD | {"depth": depth}).depth == depth


@pytest.mark.parametrize("tier", ["auto", "questdb", "parquet"])
def test_each_source_tier_is_accepted(tier: SourceTier) -> None:
    assert ReplayRequest.model_validate(GOOD | {"source_tier": tier}).source_tier == tier


def test_every_recorded_stream_is_accepted() -> None:
    req = ReplayRequest.model_validate(GOOD | {"streams": REPLAYABLE_STREAMS})

    assert req.streams == REPLAYABLE_STREAMS


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"start": datetime(2026, 10, 1, 12, 0)}, id="naive-start"),
        pytest.param({"end": START}, id="empty-window"),
        pytest.param({"end": START - US}, id="reversed-window"),
        pytest.param({"symbols": ()}, id="no-symbols"),
        pytest.param({"symbols": ("BTCUSDT", "BTCUSDT")}, id="repeated-symbol"),
        pytest.param({"symbols": tuple(f"SYM{i}USDT" for i in range(9))}, id="nine-symbols"),
        pytest.param({"symbols": ("btc/usdt",)}, id="malformed-symbol"),
        pytest.param({"streams": ()}, id="no-streams"),
        pytest.param({"streams": (StreamKind.TRADES, StreamKind.TRADES)}, id="repeated-stream"),
        pytest.param({"streams": (StreamKind.BARS,)}, id="derived-stream"),
        pytest.param({"depth": 100}, id="unrecorded-depth"),
        pytest.param({"source_tier": "hot"}, id="unknown-tier"),
        pytest.param({"speed": 2}, id="extra-field"),
        pytest.param({"max_span_us": True}, id="bool-cap"),
        pytest.param({"max_span_us": float(HOUR_US)}, id="float-cap"),
    ],
)
def test_an_invalid_request_raises_the_typed_error(override: dict[str, object]) -> None:
    with pytest.raises(ReplayRequestInvalid):
        ReplayRequest.model_validate(GOOD | override)


def test_a_refusal_names_the_field_and_type_never_the_value() -> None:
    with pytest.raises(ReplayRequestInvalid) as raised:
        ReplayRequest.model_validate(GOOD | {"symbols": ("btc/usdt",)})

    assert str(raised.value) == (
        "invalid replay request: symbols (string_pattern_mismatch, too_short)"
    )
    assert raised.value.__cause__ is None and raised.value.__context__ is None


def test_a_zero_cap_is_refused_as_a_bad_cap_not_as_a_long_window() -> None:
    with pytest.raises(ReplayRequestInvalid) as raised:
        ReplayRequest.model_validate(GOOD | {"max_span_us": 0})

    assert str(raised.value) == "invalid replay request: max_span_us (greater_than)"


def test_a_window_at_the_default_cap_is_accepted() -> None:
    """Security notes: the window cap bounds every read, so no request scans the whole lake."""
    req = ReplayRequest.model_validate(GOOD | {"end": START + DAY})

    assert req.end_us - req.start_us == 86_400_000_000


def test_a_window_one_microsecond_over_the_default_cap_is_refused() -> None:
    with pytest.raises(ReplayRequestInvalid, match="exceeds the 86400000000 µs cap"):
        ReplayRequest.model_validate(GOOD | {"end": START + DAY + US})


def test_the_callers_cap_admits_the_longest_window_the_session_service_accepts() -> None:
    """One source of truth: a 31-day window E26-T01 accepted is not refused here."""
    month = 24 * 31 * HOUR_US
    req = ReplayRequest.model_validate(
        GOOD | {"end": START + timedelta(microseconds=month), "max_span_us": month}
    )

    assert (req.max_span_us, req.end_us - req.start_us) == (month, month)


def test_the_callers_cap_refuses_a_window_one_microsecond_over_it() -> None:
    hour = timedelta(hours=1)

    with pytest.raises(ReplayRequestInvalid, match=f"exceeds the {HOUR_US} µs cap"):
        ReplayRequest.model_validate(GOOD | {"end": START + hour + US, "max_span_us": HOUR_US})


def test_the_cap_ceiling_is_the_ceiling_of_the_window_setting() -> None:
    """One source of truth: `CV_REPLAY_MAX_WINDOW_HOURS` cannot be set above this many hours."""
    field = Settings.model_fields["replay_max_window_hours"]
    ceiling_hours = next(rule.le for rule in field.metadata if hasattr(rule, "le"))

    assert isinstance(ceiling_hours, int)
    assert MAX_SPAN_CEILING_US == ceiling_hours * HOUR_US == 24 * 31 * HOUR_US


def test_the_smallest_cap_is_one_microsecond() -> None:
    req = ReplayRequest.model_validate(GOOD | {"end": START + US, "max_span_us": 1})

    assert (req.max_span_us, req.end_us - req.start_us) == (1, 1)


def test_a_cap_no_deployment_can_configure_is_refused_and_the_ceiling_itself_accepted() -> None:
    accepted = ReplayRequest.model_validate(GOOD | {"max_span_us": MAX_SPAN_CEILING_US})

    with pytest.raises(ReplayRequestInvalid) as raised:
        ReplayRequest.model_validate(GOOD | {"max_span_us": MAX_SPAN_CEILING_US + 1})

    assert accepted.max_span_us == MAX_SPAN_CEILING_US
    assert str(raised.value) == "invalid replay request: max_span_us (less_than_equal)"


def test_the_request_is_immutable() -> None:
    req = ReplayRequest.model_validate(GOOD)
    depth = "depth"  # the attribute name as data: the assignment is the test

    with pytest.raises(ValidationError):
        setattr(req, depth, 50)


def test_the_gap_marker_is_immutable() -> None:
    gap = ReplayGap(1, "BTCUSDT", StreamKind.TRADES, 0, 5, "ws_disconnect")
    cause = "cause"

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(gap, cause, "other")


def test_tier_ports_hold_the_injected_storage_fakes() -> None:
    """Typed against the Protocols, so mypy checks the fakes' signatures."""
    hot: RecordedStreamReader = InMemoryRecordedTier()
    cold: RecordedStreamReader = InMemoryRecordedTier()
    coverage: ManifestCoverage = StaticManifestCoverage()
    gaps: RecordingGapReader = StaticGapReader()

    tiers = ReplayTiers(hot=hot, cold=cold, coverage=coverage, gaps=gaps)

    assert tiers.hot is hot
    assert tiers.cold is cold
    assert tiers.coverage is coverage
    assert tiers.gaps is gaps


def _ceiling() -> ReplayMemoryCeilingExceeded:
    stream = StreamKind.ORDERBOOK_DELTA
    return ReplayMemoryCeilingExceeded(budget_bytes=1024, symbol="BTCUSDT", stream=stream)


def _unavailable() -> ReplaySourceUnavailable:
    return ReplaySourceUnavailable(tier="questdb", symbol="BTCUSDT", stream=None, reason="timeout")


def _straddle() -> ReplayTierStraddle:
    archived = [TimeRange(start_us=0, end_us=10)]
    return ReplayTierStraddle(symbol="BTCUSDT", stream=StreamKind.TRADES, archived=archived)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ReplayRequestInvalid("x"), "REPLAY_REQUEST_INVALID"),
        (ReplayInternalError(), "REPLAY_INTERNAL_ERROR"),
        (_ceiling(), "REPLAY_MEMORY_CEILING_EXCEEDED"),
        (_unavailable(), "REPLAY_SOURCE_UNAVAILABLE"),
        (_straddle(), "REPLAY_TIER_STRADDLE"),
    ],
)
def test_each_error_carries_its_stable_code(error: ReplayError, code: str) -> None:
    assert error.code == code


def test_the_memory_ceiling_error_names_the_stream_and_the_budget() -> None:
    error = _ceiling()

    assert str(error) == (
        "replay memory budget of 1024 bytes cannot hold one read of orderbook_delta for BTCUSDT"
    )
    assert (error.budget_bytes, error.stream, error.max_rows) == (
        1024,
        StreamKind.ORDERBOOK_DELTA,
        None,
    )


@pytest.mark.parametrize(
    ("stream", "what"), [(StreamKind.TRADES, "trades"), (None, "recording_gaps")]
)
def test_the_memory_ceiling_error_names_the_row_ceiling_when_it_bound_the_read(
    stream: StreamKind | None, what: str
) -> None:
    """A gap read has no stream and no byte share, only the row ceiling."""
    error = ReplayMemoryCeilingExceeded(
        budget_bytes=1024, symbol="BTCUSDT", stream=stream, max_rows=8192
    )

    assert (
        str(error)
        == f"replay row ceiling of 8192 rows per read cannot hold one read of {what} for BTCUSDT"
    )
    assert (error.stream, error.max_rows) == (stream, 8192)


def test_an_unavailable_gap_read_names_recording_gaps_and_the_reason() -> None:
    error = _unavailable()

    assert str(error) == "replay read of recording_gaps for BTCUSDT from questdb failed: timeout"
    assert (error.tier, error.stream, error.reason) == ("questdb", None, "timeout")


def test_the_straddle_error_carries_the_archived_spans() -> None:
    error = _straddle()

    assert (error.stream, error.archived) == (
        StreamKind.TRADES,
        (TimeRange(start_us=0, end_us=10),),
    )
    assert "trades of BTCUSDT" in str(error)


@pytest.mark.parametrize(
    "error_type",
    [
        ReplayRequestInvalid,
        ReplayInternalError,
        ReplayMemoryCeilingExceeded,
        ReplaySourceUnavailable,
        ReplayTierStraddle,
    ],
)
def test_every_replay_error_is_a_replay_error(error_type: type[Exception]) -> None:
    assert issubclass(error_type, ReplayError)
