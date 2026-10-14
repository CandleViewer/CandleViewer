"""Opaque `GET /admin/audit` cursor (contract #2392, design D4): round trip and refusals."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.audit.cursor import (
    CURSOR_MAX_LEN,
    AuditCursor,
    InvalidAuditCursor,
    decode_cursor,
    encode_cursor,
)

_TS = datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=UTC)


def _raw(obj: object) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj, separators=(",", ":"))
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_cursor_round_trips_position_in_compact_v1_form() -> None:
    token = encode_cursor(AuditCursor(_TS, 88120440))
    assert json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))) == {
        "v": 1,
        "ts": "2026-10-01T12:00:00.123456+00:00",
        "id": 88120440,
    }
    assert decode_cursor(token) == AuditCursor(_TS, 88120440)
    assert "=" not in token and len(token) <= CURSOR_MAX_LEN


def test_cursor_position_is_kept_in_utc() -> None:
    local = _TS.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert decode_cursor(encode_cursor(AuditCursor(local, 7))) == AuditCursor(_TS, 7)


@given(
    ts=st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2200, 1, 1),
        timezones=st.just(UTC),
    ),
    entry_id=st.integers(min_value=1, max_value=2**63 - 1),
)
def test_cursor_round_trip_property(ts: datetime, entry_id: int) -> None:
    assert decode_cursor(encode_cursor(AuditCursor(ts, entry_id))) == AuditCursor(ts, entry_id)


_GOOD = {"v": 1, "ts": "2026-10-01T12:00:00.123456+00:00", "id": 5}


@pytest.mark.parametrize(
    "token",
    [
        "",
        "a" * (CURSOR_MAX_LEN + 1),
        "!!notbase64",
        _raw(_GOOD) + "=",  # padding is not part of the issued form
        _raw(_GOOD) + "é",
        _raw("not json"),
        _raw([1, 2]),
        _raw({**_GOOD, "v": 2}),
        _raw({**_GOOD, "v": True}),
        _raw({**_GOOD, "id": 0}),
        _raw({**_GOOD, "id": -1}),
        _raw({**_GOOD, "id": 2**63}),
        _raw({**_GOOD, "id": "5"}),
        _raw({**_GOOD, "id": 5.0}),
        _raw({**_GOOD, "id": True}),
        _raw({**_GOOD, "ts": "2026-10-01T12:00:00.123456"}),  # naive
        _raw({**_GOOD, "ts": "2026-10-01T17:30:00.123456+05:30"}),  # not the issued UTC form
        _raw({**_GOOD, "ts": "yesterday"}),
        _raw({**_GOOD, "ts": 1}),
        _raw({**_GOOD, "scope": "all"}),  # a cursor never carries scope
        _raw({"v": 1, "id": 5}),
        _raw(json.dumps(_GOOD, separators=(", ", ": "))),  # not the issued byte form
    ],
)
def test_malformed_cursor_is_refused(token: str) -> None:
    with pytest.raises(InvalidAuditCursor) as err:
        decode_cursor(token)
    assert str(err.value) == "cursor is not one this server issued"  # never echoes the input


def test_issued_form_is_the_only_accepted_form() -> None:
    assert decode_cursor(_raw(_GOOD)) == AuditCursor(_TS.replace(microsecond=123456), 5)
