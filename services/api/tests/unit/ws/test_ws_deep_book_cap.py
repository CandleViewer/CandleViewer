"""E21-T01 (#604; 23 §6.1, §16.2, BQ-2): the deep-book cap and the flag-off depth 500 at `sub`.

A connection holds at most `ws.max_deep_book_subs` distinct deep (depth >= 200) `book`
subscriptions, each (symbol, depth) live and in each replay session counted apart; the next is
refused `subscription_limit` before it is pending, never clamped to a shallower depth.
`book.{symbol}.500` while `heatmap_depth_500` is off is `invalid_topic_format`, never served at
another depth."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws.limits import MAX_DEEP_BOOK_SUBSCRIPTIONS
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices, handle_sub
from candleviewer.ws.upstream import UpstreamRefs

RS = "bb000000-0000-4000-8000-000000000001"
RS2 = "bb000000-0000-4000-8000-000000000002"
RS3 = "bb000000-0000-4000-8000-000000000003"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT")


class _Sink:
    def __init__(self) -> None:
        self.opened: list[Any] = []

    async def open(self, key: Any) -> None:
        self.opened.append(key)

    async def drop(self, key: Any) -> None:
        return None


def _conn(**services: Any) -> tuple[ConnectionAuthz, _Sink]:
    sink = _Sink()
    principal = PrincipalSnapshot(
        uuid.UUID(int=1), frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ})
    )
    return ConnectionAuthz(
        principal, SubscriptionServices(upstream=UpstreamRefs(sink), **services)
    ), sink


def _sub(conn: ConnectionAuthz, *topics: str, **body: Any) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    frame = {"t": "sub", "id": "s", "p": {"topics": [{"ch": t} for t in topics], **body}}
    asyncio.run(handle_sub(conn, frame, send, now_ms=1))
    results: list[dict[str, Any]] = sent[0]["p"]["results"]
    return results


def _code(result: dict[str, Any]) -> str | None:
    return None if result["ok"] else str(result["error"]["code"])


def test_deep_book_cap_refuses_the_fifth_distinct_deep_book_subscription() -> None:
    conn, sink = _conn()
    deep = [f"book.{s}.200" for s in SYMBOLS[:MAX_DEEP_BOOK_SUBSCRIPTIONS]]
    assert [_code(r) for r in _sub(conn, *deep)] == [None] * MAX_DEEP_BOOK_SUBSCRIPTIONS
    (refused,) = _sub(conn, f"book.{SYMBOLS[4]}.200")
    assert _code(refused) == "subscription_limit"
    assert "4 deep book subscriptions" in refused["error"]["message"]
    assert f"book.{SYMBOLS[4]}.200" not in {s.ch for s in conn.by_id.values()}  # never pending
    assert len(sink.opened) == MAX_DEEP_BOOK_SUBSCRIPTIONS  # nothing held for the refused one
    shallow = _sub(conn, f"book.{SYMBOLS[4]}.50", f"book.{SYMBOLS[5]}.1")  # never counted
    assert [_code(r) for r in shallow] == [None, None]


def test_deep_book_cap_counts_each_replay_session_and_live_apart() -> None:
    """F1: the same (symbol, depth) live and in N replay sessions is N + 1 deep subscriptions."""
    conn, _ = _conn()
    assert _code(_sub(conn, "book.BTCUSDT.200")[0]) is None
    for rs in (RS, RS2):
        assert _code(_sub(conn, "book.BTCUSDT.200", replay_session_id=rs)[0]) is None
    assert _code(_sub(conn, "book.ETHUSDT.200", replay_session_id=RS)[0]) is None
    (refused,) = _sub(conn, "book.BTCUSDT.200", replay_session_id=RS3)
    assert _code(refused) == "subscription_limit"  # one live and three replay hold the cap


def test_deep_book_cap_frees_a_slot_on_unsub() -> None:
    conn, _ = _conn()
    _sub(conn, *(f"book.{s}.200" for s in SYMBOLS[:4]))
    assert conn.unsubscribe("book.BTCUSDT.200") is not None
    assert _code(_sub(conn, "book.ADAUSDT.200")[0]) is None


def test_deep_book_cap_follows_the_setting() -> None:
    conn, _ = _conn(max_deep_book_subs=1)
    first, second = _sub(conn, "book.BTCUSDT.200", "book.ETHUSDT.200")
    assert (_code(first), _code(second)) == (None, "subscription_limit")
    assert "At most 1 deep book" in second["error"]["message"]


@pytest.mark.parametrize("rs", [None, RS], ids=["live", "replay"])
def test_depth_500_is_invalid_topic_format_while_heatmap_depth_500_is_off(rs: str | None) -> None:
    conn, sink = _conn()
    body = {} if rs is None else {"replay_session_id": rs}
    (refused,) = _sub(conn, "book.BTCUSDT.500", **body)
    assert _code(refused) == "invalid_topic_format"
    assert conn.by_id == {} and sink.opened == []  # never served at another depth


def test_depth_500_is_offered_with_heatmap_depth_500_and_counts_against_the_cap() -> None:
    conn, sink = _conn(depth_500=True)
    assert _code(_sub(conn, "book.BTCUSDT.500")[0]) is None
    assert [k[2] for k in sink.opened] == [("500",)]  # the upstream key names the depth
    deep = _sub(conn, "book.BTCUSDT.200", "book.ETHUSDT.500", "book.SOLUSDT.200")
    assert [_code(r) for r in deep] == [None, None, None]
    assert _code(_sub(conn, "book.XRPUSDT.500")[0]) == "subscription_limit"
