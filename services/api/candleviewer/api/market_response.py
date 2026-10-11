"""Shared `KlineResponse` assembly for `/market/klines` and `/market/bars` (E12-T05, #398).

One place builds what both routes return, so the two cannot drift from `22-api-openapi.yaml`:
RFC 9457 problems carrying a catalogued `code`, the opaque bar cursor, `DataMeta`, the
null-not-zero delta rule and the response size ceiling (SR-E12-01).

**Cursor.** Opaque to clients (OpenAPI `MarketCursor`). It encodes `v1`, the issuing route,
symbol and series (interval, or `bar_type:param`) and the next page's first position: a `ts`
(µs) for klines and time bars (`v1`), or the full stored key `(ts, generation, index)` for
non-time bars (`v2`, #2017), whose `ts` may repeat. Every field is checked against the request
on decode (`invalid_cursor` on any mismatch); a `v1` cursor is never accepted as `v2` or back.

**Response ceiling (A5).** The 2 MiB check runs on the serialised page. That is bounded by
construction: `limit <= 5000` rows of at most ~400 bytes each is ~2 MB, so a page is never
materialised beyond that before the check.

**Null, not zero (BR-07).** Exchange klines carry no order flow, so a kline-sourced bar's
`delta`/`min_delta`/`max_delta`/`cvd` are `null` when `include_delta=true`; a zero would be a lie
that reaches CVD and rules. Tape-built bars carry their stored values; `cvd` is not persisted
per bar, so it is `null` there too.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final, Protocol

import orjson
from fastapi.responses import JSONResponse, Response

from candleviewer.bars.limits import RESPONSE_MAX_BYTES

_PROBLEM_MEDIA: Final = "application/problem+json"
_ERR_BASE: Final = "https://candleviewer.local/errors/"
_CURSOR_TAG: Final = "v1:"
_KEY_CURSOR_TAG: Final = "v2:"
_KEY_PART_MAX: Final = 2**62  # generation/index bound: a LONG, with headroom; larger is forged
_CURSOR_MAX_LEN: Final = 128
_DELTA_FIELDS: Final = ("delta", "min_delta", "max_delta")


class InvalidCursor(ValueError):
    """The cursor is not one this server issued (400 `invalid_cursor`)."""


def problem(status: int, code: str, title: str, detail: str) -> JSONResponse:
    """RFC 9457 body matching `components.schemas.Problem` (`code` is required)."""
    return JSONResponse(
        status_code=status,
        content={
            "type": f"{_ERR_BASE}{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
        },
        media_type=_PROBLEM_MEDIA,
    )


def with_recording_started_at(resp: JSONResponse, started_us: int | None) -> JSONResponse:
    """E16-T04: a `no_data_recorded` problem carries `recording_started_at` (null when nothing
    was ever recorded) so the UI can offer the first recorded window (22-api /market/bars)."""
    body = json.loads(bytes(resp.body))
    body["recording_started_at"] = iso_us(started_us) if started_us is not None else None
    return JSONResponse(status_code=resp.status_code, content=body, media_type=resp.media_type)


#: Plausible exchange time: 2015-01-01 .. 2100-01-01 (µs). Outside it a cursor is forged.
_TS_MIN_US: Final = 1_420_070_400_000_000
_TS_MAX_US: Final = 4_102_444_800_000_000


def cursor_scope(route: str, symbol: str, series: str) -> str:
    """What a cursor is bound to: `klines|BTCUSDT|1` or `bars|BTCUSDT|tick:100`."""
    return f"{route}|{symbol}|{series}"


def encode_cursor(scope: str, ts_us: int) -> str:
    """Opaque cursor: next page's first `ts` bound to the issuing request's `scope`.

    Not a MAC (no secret material exists, and none is needed): a cursor only names a position
    in public market data, and `decode_cursor` re-validates every field against the request, so
    a forged or replayed cursor can at worst select a page the caller could request directly.
    """
    raw = f"{_CURSOR_TAG}{scope}|{ts_us}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(
    cursor: str, *, scope: str, end_us: int, start_us: int = 0, grid_us: int | None = None
) -> int:
    """`ts_us` from a cursor this server issued for exactly this request, else `InvalidCursor`.

    Rejects: wrong length/encoding/version, a different route/symbol/series, a `ts` outside the
    plausible range, before the request's `from` or after its `to`, and (time bars) a `ts` off
    the interval grid — rejected, never clamped.
    """
    if not cursor or len(cursor) > _CURSOR_MAX_LEN or not cursor.isascii():
        raise InvalidCursor("cursor is empty or too long")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursor("cursor is not valid base64") from exc
    body = raw.removeprefix(_CURSOR_TAG)
    got_scope, _, ts = body.rpartition("|")
    if body == raw or got_scope != scope or not ts.isdigit() or len(ts) > 19:
        raise InvalidCursor("cursor does not belong to this request")
    ts_us = int(ts)
    if not _TS_MIN_US <= ts_us <= _TS_MAX_US or not start_us <= ts_us <= end_us:
        raise InvalidCursor("cursor position is outside this request")
    if grid_us is not None and ts_us % grid_us:
        raise InvalidCursor("cursor position is not on a bar boundary")
    return ts_us


def _decode_body(cursor: str, tag: str) -> str:
    if not cursor or len(cursor) > _CURSOR_MAX_LEN or not cursor.isascii():
        raise InvalidCursor("cursor is empty or too long")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursor("cursor is not valid base64") from exc
    body = raw.removeprefix(tag)
    if body == raw:
        raise InvalidCursor("cursor does not belong to this request")
    return body


def encode_key_cursor(scope: str, key: tuple[int, int, int]) -> str:
    """Opaque non-time-bar cursor (#2017): the next page's first `(ts, generation, index)`.
    Same trust model as `encode_cursor` (not a MAC; every field re-validated on decode)."""
    ts_us, generation, index = key
    # `index` is stored +1 so a NULL-index boundary row (`row_key` index -1) encodes as 0 and
    # decodes back to -1: the server never issues a cursor it would refuse (#2181 security LOW).
    raw = f"{_KEY_CURSOR_TAG}{scope}|{ts_us}|{generation}|{index + 1}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_key_cursor(
    cursor: str, *, scope: str, end_us: int, start_us: int = 0
) -> tuple[int, int, int]:
    """`(ts, generation, index)` from a `v2` cursor issued for exactly this request, else
    `InvalidCursor`. Length is checked here, before decoding (never `Query(max_length=)`)."""
    parts = _decode_body(cursor, _KEY_CURSOR_TAG).rsplit("|", 3)
    if len(parts) != 4 or parts[0] != scope:
        raise InvalidCursor("cursor does not belong to this request")
    nums = parts[1:]
    if not all(n.isdigit() and n.isascii() and len(n) <= 19 for n in nums):
        raise InvalidCursor("cursor does not belong to this request")
    ts_us, generation, index = (int(n) for n in nums)
    if not _TS_MIN_US <= ts_us <= _TS_MAX_US or not start_us <= ts_us <= end_us:
        raise InvalidCursor("cursor position is outside this request")
    if generation > _KEY_PART_MAX or index > _KEY_PART_MAX:
        raise InvalidCursor("cursor position is outside this request")
    return ts_us, generation, index - 1  # -1 = the NULL-index position (sorts first)


def iso_us(ts_us: int) -> str:
    return datetime.fromtimestamp(ts_us / 1_000_000, tz=UTC).isoformat()


class BarRowLike(Protocol):
    """What either tier hands the assembler. Kline rows lack the order-flow attributes."""

    @property
    def ts_us(self) -> int: ...
    @property
    def open(self) -> str: ...
    @property
    def high(self) -> str: ...
    @property
    def low(self) -> str: ...
    @property
    def close(self) -> str: ...
    @property
    def volume(self) -> str: ...
    @property
    def turnover(self) -> str: ...
    @property
    def confirmed(self) -> bool: ...


def serialize_bar(row: BarRowLike, *, include_delta: bool) -> dict[str, object]:
    bar: dict[str, object] = {
        "t": iso_us(row.ts_us),
        "o": row.open,
        "h": row.high,
        "l": row.low,
        "c": row.close,
        "v": row.volume,
        "turnover": row.turnover,
        "confirm": row.confirmed,
    }
    for name in ("index", "generation"):  # stored bars only (#2017); klines have neither
        value = getattr(row, name, None)
        if isinstance(value, int) and not isinstance(value, bool):
            bar[name] = value
    close_ts = getattr(row, "close_ts_us", None)
    if isinstance(close_ts, int):
        bar["close_time"] = iso_us(close_ts)
    if include_delta:
        trades = getattr(row, "trades", None)
        if isinstance(trades, int):
            bar["trades"] = trades
        for name in _DELTA_FIELDS:
            value = getattr(row, name, None)  # absent on kline rows -> null, never "0"
            bar[name] = value if isinstance(value, str) else None
        bar["cvd"] = None  # not persisted per bar (24 §3.1); never fabricated
    return bar


def build_meta(
    *,
    count: int,
    next_cursor: str | None,
    sources: Sequence[str],
    recording_started_at_us: int | None,
    generated_at_us: int,
    coverage_holes: list[dict[str, int]] | None = None,
) -> dict[str, object]:
    meta: dict[str, object] = {
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "count": count,
        "sources": list(sources),
        "recording_started_at": (
            iso_us(recording_started_at_us) if recording_started_at_us is not None else None
        ),
        "generated_at": iso_us(generated_at_us),
    }
    if coverage_holes is not None:
        meta["coverage_holes"] = coverage_holes
    return meta


def kline_response(
    *, symbol: str, interval: str, bar_type: str, bars: list[dict[str, object]],
    meta: dict[str, object],
) -> Response:  # fmt: skip
    """200 `KlineResponse`, or `422 response_too_large` past the ceiling (never truncated)."""
    body = orjson.dumps(
        {"symbol": symbol, "interval": interval, "bar_type": bar_type, "bars": bars, "meta": meta}
    )
    if len(body) > RESPONSE_MAX_BYTES:
        return problem(
            422,
            "response_too_large",
            "Response too large",
            "This page of bars is larger than the server sends at once; request a smaller limit.",
        )
    return Response(content=body, status_code=200, media_type="application/json")


__all__ = [
    "BarRowLike",
    "InvalidCursor",
    "build_meta",
    "cursor_scope",
    "decode_cursor",
    "decode_key_cursor",
    "encode_cursor",
    "encode_key_cursor",
    "iso_us",
    "kline_response",
    "problem",
    "serialize_bar",
]
