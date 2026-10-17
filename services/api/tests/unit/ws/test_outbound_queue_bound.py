"""#2155 item 2: the flag-off outbound queue has an explicit `maxsize` (C-2.18).

`push` stops data frames at `OUTBOUND_QUEUE_MAX` (one more closes `slow_consumer`), and a close
queues its `bye`, the close sentinel and its code past that bound (S11). The `maxsize` is exactly
the two together: a close always fits on a full data part, and nothing else can.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

import candleviewer.ws.gateway as gateway
from candleviewer.ws.gateway import CLOSE_ITEMS, OUTBOUND_QUEUE_MAX, _Connection
from tests.unit.ws._auth_rig import BASE_MS, Sock


def _full() -> _Connection:
    conn = _Connection(
        cast(Any, Sock()),
        encoding="cv.v1.json",
        clock=lambda: 0.0,
        wall_ms=lambda: BASE_MS,
        auth_timeout_s=10.0,
    )
    for _ in range(OUTBOUND_QUEUE_MAX):
        conn.push({"t": "d", "p": {"kind": "tick"}})
    assert (conn.outbound.qsize(), conn.closing) == (OUTBOUND_QUEUE_MAX, False)
    return conn


def _drain(conn: _Connection) -> list[Any]:
    return [conn.outbound.get_nowait() for _ in range(conn.outbound.qsize())]


async def test_a_full_data_part_still_takes_the_slow_consumer_close_and_nothing_after() -> None:
    """The frame over the bound closes the socket: `bye`, sentinel and code fill the queue to its
    `maxsize` (1 024 + 3) with no `QueueFull`, the `bye` right after the data, and every later
    push is dropped."""
    conn = _full()
    for kind in ("over", "late", "later"):
        conn.push({"t": "d", "p": {"kind": kind}})
    assert (conn.outbound.maxsize, CLOSE_ITEMS) == (OUTBOUND_QUEUE_MAX + 3, 3)
    assert conn.closing and conn.outbound.full()
    assert _drain(conn)[OUTBOUND_QUEUE_MAX:] == [conn.bye_frame, gateway._CLOSE, 4429]


@pytest.mark.parametrize(
    ("first", "then_seal", "data_kept"),
    [
        ("auth_failed", False, OUTBOUND_QUEUE_MAX),
        ("shutdown", True, 0),
        ("token_expired", False, 0),
    ],
    ids=["ordinary", "ordinary_then_sealed", "sealed"],
)
async def test_any_close_fits_on_a_full_data_part(
    first: str, then_seal: bool, data_kept: int
) -> None:
    """An ordinary close keeps the data ahead of its `bye`; a sealed one (token expiry,
    revocation), first or landing on a close under way, keeps only the close items."""
    conn = _full()
    conn.close_with(first, seal=first == "token_expired")
    if then_seal:
        conn.close_with("token_expired", seal=True)
    items, bye = _drain(conn), conn.bye_frame
    assert bye is not None and bye["p"]["reason"] == first
    assert (len(items), items[-CLOSE_ITEMS:]) == (
        data_kept + 3,
        [bye, gateway._CLOSE, bye["p"]["code"]],
    )
