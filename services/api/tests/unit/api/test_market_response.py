"""E12-T05 (#398): shared `KlineResponse` assembly — cursor codec, meta, null-not-zero, ceiling."""

from __future__ import annotations

from dataclasses import dataclass

import orjson
import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.api import market_response as mr
from candleviewer.bars import limits


@dataclass(frozen=True, slots=True)
class _Row:
    ts_us: int = 0
    open: str = "1"
    high: str = "1"
    low: str = "1"
    close: str = "1"
    volume: str = "1"
    turnover: str = "1"
    confirmed: bool = True


_SCOPE = mr.cursor_scope("klines", "BTCUSDT", "1")
_LO, _HI = 1_420_070_400_000_000, 4_102_444_800_000_000


@given(st.integers(min_value=_LO, max_value=_HI))
def test_cursor_round_trips_any_plausible_ts(ts: int) -> None:
    c = mr.encode_cursor(_SCOPE, ts)
    assert len(c) <= 128 and mr.decode_cursor(c, scope=_SCOPE, end_us=_HI) == ts


@pytest.mark.parametrize("bad", ["", "a" * 129, "é", "!!!", "Zm9v", "djE6LTE", "djE6"])
def test_decode_cursor_rejects_foreign_input(bad: str) -> None:
    with pytest.raises(mr.InvalidCursor):
        mr.decode_cursor(bad, scope=_SCOPE, end_us=_HI)


@pytest.mark.parametrize(
    ("scope", "ts", "end", "grid"),
    [
        (mr.cursor_scope("bars", "BTCUSDT", "1"), _LO, _HI, None),  # other route
        (_SCOPE, _LO - 1, _HI, None),  # implausibly old
        (_SCOPE, _HI + 1, 2**63, None),  # implausibly new
        (_SCOPE, _LO + 60_000_000, _LO, None),  # after `to`
        (_SCOPE, _LO + 1, _HI, 60_000_000),  # off the bar grid
    ],
)
def test_decode_cursor_rejects_mismatches(scope: str, ts: int, end: int, grid: int | None) -> None:
    c = mr.encode_cursor(_SCOPE if scope.startswith("klines") else scope, ts)
    want = scope if not scope.startswith("bars") else _SCOPE
    with pytest.raises(mr.InvalidCursor):
        mr.decode_cursor(c, scope=want, end_us=end, grid_us=grid)


def test_kline_row_with_include_delta_gets_nulls_never_zero() -> None:
    bar = mr.serialize_bar(_Row(), include_delta=True)
    assert all(bar[k] is None for k in ("delta", "min_delta", "max_delta", "cvd"))
    assert "trades" not in bar and "close_time" not in bar


def test_meta_has_more_tracks_cursor_and_omits_holes_when_none() -> None:
    meta = mr.build_meta(count=0, next_cursor=None, sources=[], recording_started_at_us=None,
                         generated_at_us=0)  # fmt: skip
    assert meta["has_more"] is False and "coverage_holes" not in meta
    assert meta["recording_started_at"] is None
    more = mr.build_meta(count=1, next_cursor="x", sources=["tape"], recording_started_at_us=0,
                         generated_at_us=0)  # fmt: skip
    assert more["has_more"] is True and more["recording_started_at"].startswith("1970")


def test_oversized_page_is_response_too_large_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mr, "RESPONSE_MAX_BYTES", 200)
    meta = mr.build_meta(count=5, next_cursor=None, sources=[], recording_started_at_us=None,
                         generated_at_us=0)  # fmt: skip
    bars = [mr.serialize_bar(_Row(ts_us=i), include_delta=False) for i in range(5)]
    resp = mr.kline_response(symbol="BTCUSDT", interval="1", bar_type="time", bars=bars, meta=meta)
    assert resp.status_code == 422
    assert orjson.loads(resp.body)["code"] == "response_too_large"


def test_limits_are_the_threat_model_numbers() -> None:
    """SR-E12-01/02/03/07: a change here is a reviewed threat-model amendment."""
    assert (limits.MAX_LIMIT, limits.DEFAULT_LIMIT) == (5_000, 1_000)
    assert limits.RESPONSE_MAX_BYTES == 2 * 1024 * 1024 and limits.QUERY_TIMEOUT_S == 2.0
    assert limits.MAX_TIME_WINDOW_US == 400 * 86_400_000_000
    assert limits.MAX_NON_TIME_WINDOW_US == 31 * 86_400_000_000
    assert limits.MAX_WINDOW_BARS == 250_000
    assert limits.TICK_PARAM_RANGE == (100, 1_000_000)
    assert limits.RANGE_TICKS_RANGE == (2, 100_000) and limits.QTY_PARAM_MAX == 10**12
    assert limits.RENKO_TICKS_RANGE == (2, 100_000) and limits.MAX_REVERSAL_BRICKS == 10
    assert limits.MAX_BRICKS_PER_TRADE == 1_000
    assert limits.MAX_TAIL == 1_000  # SR-E12-07: the WS `bars` `history` maximum


def test_decode_cursor_rejects_position_before_from() -> None:
    """#2087 adversarial LOW: a valid on-grid cursor before `from` is rejected, never clamped."""
    c = mr.encode_cursor(_SCOPE, _LO + 60_000_000)
    with pytest.raises(mr.InvalidCursor):
        mr.decode_cursor(c, scope=_SCOPE, end_us=_HI, start_us=_LO + 120_000_000)
    assert mr.decode_cursor(c, scope=_SCOPE, end_us=_HI, start_us=_LO) == _LO + 60_000_000


# --- #2017: non-time-bar `(ts, generation, index)` cursor ---------------------------------
_SCOPE = "bars|BTCUSDT|renko:20"
_TS = 1_700_000_000_000_000


@pytest.mark.parametrize(
    "key", [(_TS, 0, -1), (_TS, 0, 0), (_TS, 0, 2), (_TS, 7, 0), (_TS + 1, 2**40, 2**62 - 1)]
)
def test_key_cursor_round_trips_including_generation_rollover(key: tuple[int, int, int]) -> None:
    c = mr.encode_key_cursor(_SCOPE, key)
    assert len(c) <= 128 and mr.decode_key_cursor(c, scope=_SCOPE, end_us=_TS + 10) == key


@pytest.mark.parametrize(
    "cursor",
    [
        mr.encode_key_cursor("bars|BTCUSDT|renko:30", (_TS, 0, 1)),  # other param
        mr.encode_key_cursor("bars|ETHUSDT|renko:20", (_TS, 0, 1)),  # other symbol
        mr.encode_key_cursor("klines|BTCUSDT|renko:20", (_TS, 0, 1)),  # other route
        mr.encode_cursor(_SCOPE, _TS),  # a v1 ts cursor is not a key cursor
        mr.encode_key_cursor(_SCOPE, (_TS - 1, 0, 1)),  # before `from`
        mr.encode_key_cursor(_SCOPE, (_TS, 0, 2**63)),  # index beyond a LONG
        "",
        "A" * 129,
        "!!!",
    ],
)
def test_key_cursor_rejects_foreign_or_forged(cursor: str) -> None:
    with pytest.raises(mr.InvalidCursor):
        mr.decode_key_cursor(cursor, scope=_SCOPE, end_us=_TS + 10, start_us=_TS)


def test_key_cursor_rejects_non_numeric_parts() -> None:
    import base64

    for body in (f"v2:{_SCOPE}|{_TS}|-1|0", f"v2:{_SCOPE}|{_TS}|0", f"v2:{_SCOPE}|x|0|0"):
        c = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
        with pytest.raises(mr.InvalidCursor):
            mr.decode_key_cursor(c, scope=_SCOPE, end_us=_TS + 10)


def test_v1_decoder_rejects_a_key_cursor() -> None:
    with pytest.raises(mr.InvalidCursor):
        mr.decode_cursor(mr.encode_key_cursor(_SCOPE, (_TS, 0, 0)), scope=_SCOPE, end_us=_TS + 1)
