"""E17-S02 subscription manager: sub/unsub/ctl, scope narrowing, limits, live revocation,
upstream reference counting and the bar-series lease (pure asyncio; fake clock, no sleeps)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, NoReturn

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.bars.errors import BarsError, BarServiceStopping, BarSpecError, SpecCapExceeded
from candleviewer.bars.models import BarSpec
from candleviewer.ws import limits
from candleviewer.ws._generated.error_codes import WS_ERROR_CODES
from candleviewer.ws.limits import MAX_BARS_SUBSCRIPTIONS
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SubscriptionServices,
    VersionedSnapshot,
    handle_ctl,
    handle_sub,
    handle_unsub,
)
from candleviewer.ws.revocation import CLOSE_USER_DISABLED
from candleviewer.ws.upstream import UpstreamRefs

A = uuid.UUID(int=0xA)
B = uuid.UUID(int=0xB)
C = uuid.UUID(int=0xC)
MGR_ID = uuid.UUID(int=0x100)
OWNER_ID = uuid.UUID(int=0x200)
VIEWER_ID = uuid.UUID(int=0x300)
RS = "bb000000-0000-4000-8000-000000000001"
MGR_PERMS = frozenset(
    {Permission.MARKETDATA_READ, Permission.ORDERS_READ, Permission.POSITIONS_READ}
)
CATALOGUE = {c.value for c in WS_ERROR_CODES}


def _grant(acc: uuid.UUID) -> AccountGrant:
    return AccountGrant(acc, True, False, False)


def _mgr(*accounts: uuid.UUID, perms: frozenset[Permission] = MGR_PERMS) -> PrincipalSnapshot:
    return PrincipalSnapshot(
        MGR_ID, frozenset({"manager"}), perms, tuple(_grant(a) for a in accounts)
    )


def _viewer() -> PrincipalSnapshot:
    perms = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ})
    return PrincipalSnapshot(VIEWER_ID, frozenset({"viewer"}), perms)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Sink:
    def __init__(self) -> None:
        self.opened: list[Any] = []
        self.dropped: list[Any] = []

    async def open(self, key: Any) -> None:
        self.opened.append(key)

    async def drop(self, key: Any) -> None:
        self.dropped.append(key)


class _Bars:
    def __init__(self, fail: Exception | None = None) -> None:
        self.registered: list[tuple[str, str, str, str | None]] = []
        self.released: list[tuple[str, str, str]] = []
        self.fail = fail

    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        if self.fail is not None:
            raise self.fail
        self.registered.append((spec.spec_hash, symbol, consumer, user))

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        self.released.append((spec_hash, symbol, consumer))


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.records.append({"action": action, **kw})


def _services(**kw: Any) -> SubscriptionServices:
    clock = kw.pop("clock", _Clock())
    return SubscriptionServices(
        upstream=kw.pop("upstream", UpstreamRefs(_Sink())), clock=clock, **kw
    )


def _sub(conn: ConnectionAuthz, *entries: Any, **body: Any) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def send(f: dict[str, Any]) -> None:
        sent.append(f)

    frame = {"t": "sub", "id": "c-1", "p": {"topics": list(entries), **body}}
    asyncio.run(handle_sub(conn, frame, send, now_ms=1))
    assert len(sent) == 1 and sent[0]["t"] == "sub_ok"
    results: list[dict[str, Any]] = sent[0]["p"]["results"]
    for r in results:
        assert r.get("error", {}).get("code", "forbidden") in CATALOGUE  # S10 closure
    return results


def _acc(*accounts: uuid.UUID) -> dict[str, Any]:
    return {"exchange_account_ids": [str(a) for a in accounts]}


# -- sub ---------------------------------------------------------------------------------------


def test_sub_partial_success_in_request_order() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    res = _sub(conn, {"ch": "book.BTCUSDT.50"}, "trades.BTCUSDT", {"ch": "orders", "opts": _acc(B)})
    assert [r["ch"] for r in res] == ["book.BTCUSDT.50", "trades.BTCUSDT", "orders"]
    assert [r["ok"] for r in res] == [True, True, False]
    assert res[2]["error"]["code"] == "account_scope_denied"
    for r in res[:2]:
        assert r["sub_id"] and r["snapshot_pending"] is True and r["effective"]
    assert conn.topics == {"book.BTCUSDT.50", "trades.BTCUSDT"}


def test_sub_clamping_is_reported() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": "book.BTCUSDT.50", "opts": {"throttle_ms": 5}})
    assert r["effective"] == {
        "throttle_ms": 50, "encoding": "binary", "coalesce": True, "depth": 50,
    }  # fmt: skip


def test_sub_unknown_option_is_rejected_and_nothing_created() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": "footprint.BTCUSDT.time.5", "opts": {"min_stak": 3}})
    assert r["error"]["code"] == "invalid_options" and r["error"]["field"] == "min_stak"
    assert conn.by_id == {}


def test_sub_unknown_entry_field_is_rejected() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": "trades.BTCUSDT", "opt": {}})
    assert r["error"]["code"] == "invalid_options"


def test_sub_malformed_topics_distinguished() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    res = _sub(conn, "book.BTCUSDT.77", "bars.BTCUSDT.time.1.5", "book.ETHUSD.50")
    assert [r["error"]["code"] for r in res] == [
        "invalid_topic_format", "invalid_topic_format", "unsupported_symbol",
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("p", "field"),
    [
        ("x", "p"),
        ({"topics": ["ticker.BTCUSDT"], "bogus": 1}, "p"),
        ({}, "topics"),
        ({"topics": []}, "topics"),
        ({"topics": "ticker.BTCUSDT"}, "topics"),
        ({"topics": ["ticker.BTCUSDT", 123]}, "topics[1]"),
        ({"topics": [None]}, "topics[0]"),
        ({"topics": ["Bad Topic"]}, "topics[0]"),
        ({"topics": ["t" * 121]}, "topics[0]"),
        ({"topics": [{"opts": {}}]}, "topics[0].ch"),
        ({"topics": [{"ch": 5}]}, "topics[0].ch"),
        ({"topics": [{"ch": "book.BTCUSDT.50\n"}]}, "topics[0].ch"),
    ],
)
def test_sub_with_a_malformed_shape_is_refused_whole(p: Any, field: str) -> None:
    """#2396, #2399: one `err invalid_options` naming the field, never echoing client input;
    no `sub_ok` and nothing subscribed."""
    conn = ConnectionAuthz(_mgr(A), _services())
    sent: list[dict[str, Any]] = []

    async def send(f: dict[str, Any]) -> None:
        sent.append(f)

    asyncio.run(handle_sub(conn, {"t": "sub", "id": "c-1", "p": p}, send, now_ms=1))
    ((t, fid, err),) = [(f["t"], f.get("id"), f["p"]) for f in sent]
    assert (t, fid, err["code"], err["field"]) == ("err", "c-1", "invalid_options", field)
    assert conn.by_id == {}


@pytest.mark.parametrize("fid", [{}, {"id": 5}, {"id": ["x"]}, {"id": "c-1"}])
def test_replies_echo_a_string_request_id_and_nothing_else(fid: dict[str, Any]) -> None:
    """#2572: `sub_ok` echoed `frame.get("id")` raw, so a request without a string id got `id:
    null` (or its value), which §13.1 does not allow. The gateway drops a long id before
    dispatch; the handlers do not rely on that for its type."""
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "book.BTCUSDT.50")
    sent: list[dict[str, Any]] = []

    async def send(f: dict[str, Any]) -> None:
        sent.append(f)

    for p in ({"topics": ["ticker.BTCUSDT"]}, "x"):  # a `sub_ok`, then a refusal
        asyncio.run(handle_sub(conn, {"t": "sub", "p": p, **fid}, send, now_ms=1))
    sent += [
        handle_unsub(conn, {"t": "unsub", "p": {"topics": ["nope.BTCUSDT"]}, **fid}, 7),
        handle_unsub(conn, {"t": "unsub", "p": "x", **fid}, 7),
        handle_ctl(conn, {"t": "ctl", "ch": "book.BTCUSDT.50", "p": {"paused": True}, **fid}, 7),
        handle_ctl(conn, {"t": "ctl", "ch": "Bad Topic", "p": {"paused": True}, **fid}, 7),
    ]
    assert [f["t"] for f in sent] == ["sub_ok", "err", "unsub_ok", "err", "ctl_ok", "err"]
    want = fid["id"] if isinstance(fid.get("id"), str) else None
    assert [f.get("id", "absent") for f in sent] == [want or "absent"] * 6


def test_sub_well_formed_topic_names_still_get_one_result_each() -> None:
    """A name with the topic shape that the server cannot serve keeps its own result (§5.2),
    and the string shorthand stays accepted (§5.1, as built)."""
    conn = ConnectionAuthz(_mgr(A), _services())
    res = _sub(conn, "nope.BTCUSDT", "ticker.BTCUSDT")
    assert [(r["ch"], r["ok"]) for r in res] == [("nope.BTCUSDT", False), ("ticker.BTCUSDT", True)]


def test_sub_duplicate_is_rejected_with_ctl_advice() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "trades.BTCUSDT")
    (r,) = _sub(conn, "trades.BTCUSDT")
    assert r["error"]["code"] == "duplicate_subscription" and "ctl" in r["error"]["message"]


def test_sub_system_is_implicit_ok_and_not_counted() -> None:
    conn = ConnectionAuthz(_viewer(), _services())
    (r,) = _sub(conn, "system")
    assert r == {"ch": "system", "ok": True, "sub_id": "system"}
    assert conn.by_id == {}


def test_sub_forbidden_role() -> None:
    conn = ConnectionAuthz(_viewer(), _services())
    (r,) = _sub(conn, {"ch": "positions", "opts": _acc(A)})
    assert r["error"]["code"] == "forbidden"


def test_viewer_subscribing_orders_on_granted_account_succeeds_read_only() -> None:
    v = PrincipalSnapshot(VIEWER_ID, _viewer().roles, _viewer().permissions, (_grant(A),))
    conn = ConnectionAuthz(v, _services())
    (r,) = _sub(conn, {"ch": "orders", "opts": _acc(A)})
    assert r["ok"] and not conn.may_submit_order()


def test_sub_cross_account_raw_frame_is_denied() -> None:
    """IDOR: a manager scoped to A hand-crafts a sub for B."""
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": "positions", "opts": _acc(B)})
    assert r["error"]["code"] == "account_scope_denied"
    assert conn.subs == set()


def test_sub_account_less_private_topic_is_denied() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, "positions")
    assert r["error"]["code"] == "account_scope_denied"


def test_sub_scope_is_silently_narrowed() -> None:
    conn = ConnectionAuthz(_mgr(A, C), _services())
    (r,) = _sub(conn, {"ch": "positions", "opts": _acc(A, B, C)})
    assert r["ok"] and r["effective"]["exchange_account_ids"] == sorted([str(A), str(C)])


def test_sub_owner_reaches_every_account() -> None:
    owner = PrincipalSnapshot(OWNER_ID, frozenset({"owner"}), frozenset(Permission))
    conn = ConnectionAuthz(owner, _services())
    (r,) = _sub(conn, {"ch": "wallet", "opts": _acc(B)})
    assert r["ok"]


def test_sub_snapshot_false_needs_from_seq() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, "trades.BTCUSDT", snapshot=False)
    assert r["error"]["field"] == "from_seq"
    (r,) = _sub(conn, {"ch": "trades.BTCUSDT", "opts": {"from_seq": 4}}, snapshot=False)
    # §7.6: continuity cannot be proven (no snapshot source) -> accepted, snapshot forced.
    assert r["ok"] and r["snapshot_pending"] is True and r["snapshot_forced"] is True
    (r,) = _sub(conn, "ticker.BTCUSDT", snapshot="yes")
    assert r["error"]["field"] == "snapshot"


def test_sub_limit_200_leaves_existing_untouched() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    for start in range(0, 200, 50):
        # footprint keeps §7.7 while the bar service is off; bars.* would be refused (§6.1)
        res = _sub(conn, *[f"footprint.BTCUSDT.tick.{i}" for i in range(start + 1, start + 51)])
        assert all(r["ok"] for r in res)
    before = dict(conn.by_id)
    (r,) = _sub(conn, "trades.BTCUSDT")
    assert r["error"]["code"] == "subscription_limit"
    assert conn.by_id == before


def test_sub_symbol_limit_40_per_connection() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    syms = [f"S{i:02d}USDT" for i in range(40)]
    assert _sub(conn, {"ch": "ticker", "opts": {"symbols": syms}})[0]["ok"]
    assert _sub(conn, "trades.S00USDT")[0]["ok"]  # already-held symbol
    (r,) = _sub(conn, "trades.NEWUSDT")
    assert r["error"]["code"] == "subscription_limit"


def test_sub_more_than_50_topics_rejects_the_excess() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    # footprint, not bars: bars.* stops at its own 16-per-connection cap first (§6.1)
    res = _sub(conn, *[f"footprint.BTCUSDT.tick.{i}" for i in range(1, 53)])
    assert all(r["ok"] for r in res[:50])
    assert [r["error"]["code"] for r in res[50:]] == ["too_many_topics"] * 2


def test_sub_encoding_unsupported() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": "ticker.BTCUSDT", "opts": {"encoding": "binary"}})
    assert r["error"]["code"] == "encoding_unsupported"


# -- replay coexistence --------------------------------------------------------------------------


def test_live_and_replay_subscriptions_coexist_by_sub_id() -> None:
    sink = _Sink()
    conn = ConnectionAuthz(_mgr(A), _services(upstream=UpstreamRefs(sink)))
    (live,) = _sub(conn, "book.BTCUSDT.200")
    (rep,) = _sub(conn, "book.BTCUSDT.200", replay_session_id=RS)
    assert live["ok"] and rep["ok"] and live["sub_id"] != rep["sub_id"]
    assert len(sink.opened) == 1  # replay never opens an upstream
    (dup,) = _sub(conn, "book.BTCUSDT.200", replay_session_id=RS)
    assert dup["error"]["code"] == "duplicate_subscription"


@pytest.mark.parametrize("topic", ["orders", "positions", "executions", "wallet"])
def test_private_topic_with_replay_session_is_invalid_options(topic: str) -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": topic, "opts": _acc(A)}, replay_session_id=RS)
    assert r["error"]["code"] == "invalid_options"


@pytest.mark.parametrize("bad", ["nope", 5])
def test_malformed_replay_session_id_is_invalid_options(bad: Any) -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, "trades.BTCUSDT", replay_session_id=bad)
    assert r["error"]["field"] == "replay_session_id"


# -- unsub ---------------------------------------------------------------------------------------


def _unsub(conn: ConnectionAuthz, p: Any) -> dict[str, Any]:
    return handle_unsub(conn, {"t": "unsub", "id": "u-1", "p": p}, 7)


def _unsub_results(conn: ConnectionAuthz, *topics: str) -> list[dict[str, Any]]:
    reply = _unsub(conn, {"topics": list(topics)})
    assert (reply["t"], reply["id"], reply["ts"]) == ("unsub_ok", "u-1", 7)
    results: list[dict[str, Any]] = reply["p"]["results"]
    return results


def test_unsub_twice_is_idempotent() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "book.BTCUSDT.50")
    assert _unsub_results(conn, "book.BTCUSDT.50") == [{"ch": "book.BTCUSDT.50", "ok": True}]
    assert _unsub_results(conn, "book.BTCUSDT.50") == [
        {"ch": "book.BTCUSDT.50", "ok": True, "noop": True}
    ]


def test_unsub_system_is_refused() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    assert _unsub_results(conn, "system") == [{"ch": "system", "ok": False}]


_T = ["book.BTCUSDT.50"]
_CAP = limits.MAX_TOPICS_PER_SUB  # §13.5 `maxItems` of `unsub.topics` (#2875)


def _names(n: int) -> list[str]:
    """`n` distinct, well-formed topic names, none of them subscribed."""
    return [f"trades.S{i}" for i in range(n)]


_BAD_UNSUB_SHAPES = [
    pytest.param("x", "p", id="p-not-an-object"),
    pytest.param(None, "p", id="p-null"),
    pytest.param({"topics": _T, "bogus": 1}, "p", id="unknown-key"),
    pytest.param({}, "topics", id="topics-missing"),
    pytest.param({"topics": []}, "topics", id="topics-empty"),
    pytest.param({"topics": "book.BTCUSDT.50"}, "topics", id="topics-a-string"),
    pytest.param({"topics": [*_T, 7]}, "topics[1]", id="int-entry"),
    pytest.param({"topics": [{"ch": _T[0]}]}, "topics[0]", id="entry-object"),  # names, not entries
    pytest.param({"topics": ["Bad Topic"]}, "topics[0]", id="bad-name"),
    pytest.param({"topics": ["t" * 10_000]}, "topics[0]", id="10000-chars"),
    # #2875: §13.5 `maxItems`. 51 well-formed names, the first one subscribed; 51 entries that are
    # not names, which the length check refuses before reading any (`topics`, not `topics[0]`);
    # and the cap with an unknown key, where the first way in §5.3's list names the field (`p`)
    pytest.param({"topics": [*_T, *_names(_CAP)]}, "topics", id="over-the-cap"),
    pytest.param({"topics": [7] * (_CAP + 1)}, "topics", id="over-the-cap-bad-names"),
    pytest.param({"topics": [*_T, *_names(_CAP)], "bogus": 1}, "p", id="over-the-cap-unknown-key"),
]


@pytest.mark.parametrize(("p", "field"), _BAD_UNSUB_SHAPES)
def test_unsub_with_a_malformed_shape_is_refused_whole(p: Any, field: str) -> None:
    """#2572: one `err invalid_options` naming the field and never the client's text; no
    `unsub_ok`, and the subscription the frame also named stays in place. A refusal writes no
    audit row, whatever the frame held (#2875)."""
    audit = _Audit()
    conn = ConnectionAuthz(_mgr(A), _services(audit=audit))
    _sub(conn, "book.BTCUSDT.50")
    reply = _unsub(conn, p)
    assert (reply["t"], reply["id"], reply["p"]["code"], reply["p"]["field"]) == (
        ("err", "u-1", "invalid_options", field)
    )
    assert "ch" not in reply and len(json.dumps(reply)) < 400  # nothing is reflected
    assert conn.topics == {"book.BTCUSDT.50"}
    assert audit.records == []


def test_unsub_at_the_cap_is_answered_entry_by_entry() -> None:
    """#2875: §13.5 allows 50 entries, so a frame of exactly 50 is processed, in request order."""
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "book.BTCUSDT.50")
    names = [*_T, *_names(_CAP - 1)]  # `maxItems` entries, the first one live
    assert len(names) == _CAP
    results = _unsub_results(conn, *names)
    assert [r["ch"] for r in results] == names
    assert results[0] == {"ch": _T[0], "ok": True}  # the live subscription is released
    assert all(r == {"ch": r["ch"], "ok": True, "noop": True} for r in results[1:])  # none held
    assert conn.topics == set()


class _NoEntryRead(list[str]):
    """A `topics` array that fails the test as soon as one of its entries is read, however it
    is read: iterated or reversed, indexed or sliced, searched (`in`, `index`) or counted. Its
    length, which the cap check needs, stays readable."""

    def _read(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise AssertionError("an entry was read")

    __iter__ = __reversed__ = __getitem__ = __contains__ = index = count = _read


def test_unsub_over_the_cap_is_refused_before_any_entry_is_read() -> None:
    """#2875: the length is checked first, so the shape check does not depend on how long the
    array is. This one holds 65 536 entries (the 256 KiB frame cap lets through 65 526
    one-character names): any read of an entry, by the shape check or a scan of any kind, fails
    the test. No timing."""
    conn = ConnectionAuthz(_mgr(A), _services())
    reply = _unsub(conn, {"topics": _NoEntryRead(["a"] * 65_536)})
    assert (reply["t"], reply["p"]["code"], reply["p"]["field"]) == (
        ("err", "invalid_options", "topics")
    )


# -- ctl -----------------------------------------------------------------------------------------


def _ctl(conn: ConnectionAuthz, ch: str, body: Any) -> dict[str, Any]:
    return handle_ctl(conn, {"t": "ctl", "id": "c-9", "ch": ch, "p": body}, 7)


def test_ctl_retunes_throttle_without_resnapshot_and_keeps_sequence() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "book.BTCUSDT.50")
    sub = conn.find("book.BTCUSDT.50")
    assert sub is not None
    sub.seq, sub.snapshot_pending = 3000, False
    ok = _ctl(conn, "book.BTCUSDT.50", {"throttle_ms": 200})
    assert (ok["t"], ok["id"], ok["p"]) == ("ctl_ok", "c-9", {"effective": {"throttle_ms": 200}})
    assert sub.seq == 3000  # the next delta continues at 3001 (E17-S03)
    assert _ctl(conn, "book.BTCUSDT.50", {"throttle_ms": 5})["p"]["effective"]["throttle_ms"] == 50


def test_ctl_identity_change_forces_resnapshot() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "heatmap.BTCUSDT")
    sub = conn.find("heatmap.BTCUSDT")
    assert sub is not None
    sub.seq, sub.snapshot_pending = 10, False
    ok = _ctl(conn, "heatmap.BTCUSDT", {"time_bucket_ms": 1000})
    assert ok["p"]["resnapshot"] is True and ok["p"]["effective"]["time_bucket_ms"] == 1000
    assert (sub.seq, sub.snapshot_pending, sub.pending_reason) == (10, True, "reconfigure")
    again = _ctl(conn, "heatmap.BTCUSDT", {"time_bucket_ms": 1000})
    assert "resnapshot" not in again["p"]  # unchanged identity -> no re-snapshot


def test_ctl_paused_is_echoed() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "trades.BTCUSDT")
    assert _ctl(conn, "trades.BTCUSDT", {"paused": True})["p"]["effective"]["paused"] is True


def test_ctl_resume_after_a_pause_forces_resnapshot() -> None:
    """#2517: deltas dropped while paused took no sequence number, so a resume re-snapshots."""
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "book.BTCUSDT.50")
    sub = conn.find("book.BTCUSDT.50")
    assert sub is not None
    sub.seq, sub.snapshot_pending = 10, False
    assert "resnapshot" not in _ctl(conn, "book.BTCUSDT.50", {"paused": False})["p"]
    assert "resnapshot" not in _ctl(conn, "book.BTCUSDT.50", {"paused": True})["p"]
    assert not sub.snapshot_pending  # pausing keeps the subscription as it is
    ok = _ctl(conn, "book.BTCUSDT.50", {"paused": False})
    assert ok["p"]["resnapshot"] is True and ok["p"]["effective"]["paused"] is False
    assert (sub.seq, sub.snapshot_pending, sub.pending_reason) == (10, True, "reconfigure")


@pytest.mark.parametrize("entry", ["book.BTCUSDT.50", {"ch": "positions", "opts": _acc(A)}])
def test_ctl_without_paused_keeps_the_pause(entry: Any) -> None:
    """#2517: a ctl that omits `paused` leaves it in place; a later resume re-snapshots."""
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, entry)
    ch = entry if isinstance(entry, str) else entry["ch"]
    sub = conn.find(ch)
    assert sub is not None
    sub.seq, sub.snapshot_pending = 10, False
    _ctl(conn, ch, {"paused": True})
    kept = _ctl(conn, ch, {"throttle_ms": 1000})
    assert kept["p"]["effective"]["paused"] is True and "resnapshot" not in kept["p"]
    assert sub.effective["paused"] is True and not sub.snapshot_pending
    ok = _ctl(conn, ch, {"throttle_ms": 500, "paused": False})
    assert ok["p"]["resnapshot"] is True and ok["p"]["effective"]["paused"] is False
    assert (sub.seq, sub.snapshot_pending, sub.pending_reason) == (10, True, "reconfigure")
    assert "paused" not in _ctl(conn, ch, {"throttle_ms": 1000})["p"]["effective"]


def test_ctl_resume_keeps_an_already_pending_reason() -> None:
    """A resume while a snapshot is pending keeps that snapshot's reason (an incident)."""
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "book.BTCUSDT.50")
    sub = conn.find("book.BTCUSDT.50")
    assert sub is not None
    _ctl(conn, "book.BTCUSDT.50", {"paused": True})
    sub.snapshot_pending, sub.pending_reason = True, "backpressure"
    assert _ctl(conn, "book.BTCUSDT.50", {"paused": False})["p"]["resnapshot"] is True
    assert (sub.snapshot_pending, sub.pending_reason) == (True, "backpressure")


@pytest.mark.parametrize(
    ("body", "code"),
    [({}, "invalid_options"), ({"history": 5}, "invalid_options"), ({"throttle_ms": -1},
     "invalid_options"), ("x", "invalid_options")],
)  # fmt: skip
def test_ctl_rejects_bad_bodies(body: Any, code: str) -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "trades.BTCUSDT")
    err = _ctl(conn, "trades.BTCUSDT", body)
    assert (err["t"], err["p"]["code"]) == ("err", code)


def test_ctl_on_unsubscribed_topic_is_not_subscribed() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    err = handle_ctl(conn, {"t": "ctl", "ch": "book.BTCUSDT.50", "p": {"throttle_ms": 9}}, 1)
    assert (err["p"]["code"], err["ch"], "id" in err) == (
        "not_subscribed",
        "book.BTCUSDT.50",
        False,
    )


_BAD_CH = [
    pytest.param("Bad Topic", id="bad-name"),
    pytest.param("t" * 10_000, id="10000-chars"),
    pytest.param("book.BTCUSDT.50\n", id="trailing-newline"),
    pytest.param(5, id="int"),
    pytest.param(["book.BTCUSDT.50"], id="list"),
]


@pytest.mark.parametrize("ch", _BAD_CH)
def test_ctl_with_a_non_topic_ch_is_refused_without_echoing_it(ch: Any) -> None:
    """#2572: the envelope `ch` is a topic name (§13.1), so a `ctl` whose `ch` is not one gets
    `err invalid_options` (`field: ch`) and no `ch`, whatever the body, and changes nothing."""
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "book.BTCUSDT.50")
    sub = conn.find("book.BTCUSDT.50")
    assert sub is not None
    before = dict(sub.opts)
    err = handle_ctl(conn, {"t": "ctl", "id": "c-9", "ch": ch, "p": {"throttle_ms": 200}}, 7)
    assert (err["t"], err["id"], err["p"]["code"], err["p"]["field"]) == (
        ("err", "c-9", "invalid_options", "ch")
    )
    assert "ch" not in err and len(json.dumps(err)) < 400  # nothing is reflected
    assert sub.opts == before


@pytest.mark.parametrize("frame_ch", [{}, {"ch": None}])
def test_ctl_without_a_ch_stays_not_subscribed_and_carries_none(frame_ch: dict[str, Any]) -> None:
    """A missing `ch` echoes nothing, so its as-built answer is unchanged (#2572)."""
    conn = ConnectionAuthz(_mgr(A), _services())
    err = handle_ctl(conn, {"t": "ctl", "id": "c-9", "p": {"throttle_ms": 9}, **frame_ch}, 1)
    assert (err["p"]["code"], "ch" in err) == ("not_subscribed", False)


def test_ctl_on_replay_only_subscription_resolves_it() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "trades.BTCUSDT", replay_session_id=RS)
    assert _ctl(conn, "trades.BTCUSDT", {"throttle_ms": 100})["t"] == "ctl_ok"


def _scope_of(conn: ConnectionAuthz, ch: str) -> tuple[Any, ...]:
    sub = conn.find(ch)
    assert sub is not None
    return (
        sub.accounts,
        sub.opts.get("exchange_account_ids"),
        sub.opts.get("symbols"),
        sub.opts.get("rule_ids"),
        sub.effective.get("exchange_account_ids"),
        sub.symbols,
        frozenset(sub.upstream),
    )


@pytest.mark.parametrize(
    ("ch", "opts", "key", "value"),
    [
        # Out-of-scope account (the IDOR widening attempt) and an in-scope one.
        ("positions", {"exchange_account_ids": [str(A)]}, "exchange_account_ids", [str(B)]),
        ("positions", {"exchange_account_ids": [str(A)]}, "exchange_account_ids", [str(A)]),
        ("positions", {"exchange_account_ids": [str(A)]}, "exchange_account_ids", [str(A), str(B)]),
        ("orders", {"exchange_account_ids": [str(A)]}, "symbols", ["BTCUSDT"]),
        ("ticker", {"symbols": ["BTCUSDT"]}, "symbols", ["ETHUSDT"]),
        ("ticker", {"symbols": ["BTCUSDT"]}, "symbols", ["BTCUSDT"]),
        ("liquidations", {"symbols": ["BTCUSDT"]}, "symbols", ["ETHUSDT"]),
        ("rules", {"exchange_account_ids": [str(A)]}, "rule_ids", [str(uuid.UUID(int=7))]),
        ("rules", {"exchange_account_ids": [str(A)]}, "exchange_account_ids", [str(B)]),
    ],
)
def test_ctl_cannot_change_subscription_scope(
    ch: str, opts: dict[str, Any], key: str, value: Any
) -> None:
    perms = MGR_PERMS | {Permission.RULES_READ}
    conn = ConnectionAuthz(_mgr(A, perms=perms), _services())
    (r,) = _sub(conn, {"ch": ch, "opts": opts})
    assert r["ok"], r
    before = _scope_of(conn, ch)
    err = _ctl(conn, ch, {key: value})
    assert (err["t"], err["p"]["code"], err["p"]["field"]) == ("err", "invalid_options", key)
    # Mixed with a legal retune, the whole ctl is still refused and nothing changes.
    err = _ctl(conn, ch, {"throttle_ms": 500, key: value})
    assert (err["p"]["code"], err["p"]["field"]) == ("invalid_options", key)
    assert _scope_of(conn, ch) == before
    if ch == "positions":
        assert conn.subs == {("positions", A)}


def test_ctl_keys_and_scope_keys_are_disjoint() -> None:
    from candleviewer.ws.topics import CTL_KEYS, SCOPE_OPTIONS

    every_scope_key = SCOPE_OPTIONS | {"exchange_account_ids", "symbols", "rule_ids"}
    assert not (CTL_KEYS & every_scope_key)
    # Every scope-bearing option any family declares is covered by SCOPE_OPTIONS.
    from candleviewer.ws.topics import FAMILIES

    declared = {k for f in FAMILIES.values() for k in f.options}
    assert declared & every_scope_key <= SCOPE_OPTIONS


# -- live revocation (§9.5) ----------------------------------------------------------------------


def _apply(conn: ConnectionAuthz, new: PrincipalSnapshot, now_ms: int) -> list[dict[str, Any]]:
    frames = conn.apply_snapshot(VersionedSnapshot(new, conn.version + 1), now_ms)
    assert frames is not None  # a newer version is always applied (SR-189)
    return frames


def test_scope_narrowed_mid_stream_revokes_only_the_removed_account() -> None:
    conn = ConnectionAuthz(_mgr(A, B), _services())
    _sub(conn, {"ch": "positions", "opts": _acc(A, B)}, "book.BTCUSDT.50")
    frames = _apply(conn, _mgr(A), 9)
    assert [f["t"] for f in frames] == ["permission_change", "revoked"]
    rv = frames[1]
    assert (rv["ch"], rv["p"]["reason"]) == ("positions", "account_scope_changed")
    assert rv["p"]["removed_accounts"] == [str(B)] and rv["p"]["resubscribe_allowed"] is True
    assert conn.subs == {("positions", A), ("book.BTCUSDT.50", None)}


def test_last_account_removed_drops_the_subscription() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, {"ch": "positions", "opts": _acc(A)})
    frames = _apply(conn, _mgr(), 9)
    assert frames[1]["p"]["removed_accounts"] == [str(A)]
    assert frames[1]["p"]["resubscribe_allowed"] is False
    assert conn.by_id == {}


def test_permission_lost_revokes_with_permission_revoked() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, {"ch": "positions", "opts": _acc(A)}, "trades.BTCUSDT")
    frames = _apply(conn, _mgr(A, perms=frozenset({Permission.MARKETDATA_READ})), 9)
    assert [(f["ch"], f["p"]["reason"]) for f in frames[1:]] == [
        ("positions", "permission_revoked")
    ]
    assert conn.topics == {"trades.BTCUSDT"}


def test_unchanged_snapshot_revokes_nothing() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, {"ch": "positions", "opts": _acc(A)})
    assert _apply(conn, _mgr(A), 1)[1:] == []


def _registry(snaps: dict[uuid.UUID, PrincipalSnapshot], **kw: Any) -> ConnectionRegistry:
    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        return snaps[uid]

    return ConnectionRegistry(resolve, lambda: 42, _services(**kw))


def test_registry_grants_changed_pushes_revoked_and_audits() -> None:
    audit = _Audit()
    snaps = {MGR_ID: _mgr(A, B)}
    reg = _registry(snaps, audit=audit)
    sent: list[dict[str, Any]] = []

    async def send(f: dict[str, Any]) -> None:
        sent.append(f)

    async def scenario() -> None:
        conn = ConnectionAuthz(snaps[MGR_ID], reg.services)
        reg.register(conn, send)
        await handle_sub(conn, {"p": {"topics": [{"ch": "positions", "opts": _acc(A, B)}]}}, send)
        snaps[MGR_ID] = _mgr(A)
        await reg.grants_changed(MGR_ID)

    asyncio.run(scenario())
    assert [f["t"] for f in sent] == ["sub_ok", "permission_change", "revoked"]
    assert [r["action"] for r in audit.records] == ["ws.subscription.revoked"]
    assert audit.records[0]["after_state"] == {"removed_accounts": [str(B)]}


def test_registry_kill_switch_reevaluates_every_user() -> None:
    snaps = {MGR_ID: _mgr(A), VIEWER_ID: _viewer()}
    reg = _registry(snaps)
    got: list[str] = []

    async def send(f: dict[str, Any]) -> None:
        got.append(f["t"])

    reg.register(ConnectionAuthz(snaps[MGR_ID], reg.services), send)
    reg.register(ConnectionAuthz(snaps[VIEWER_ID], reg.services), send)
    asyncio.run(reg.kill_switch_changed())
    assert got == ["permission_change", "permission_change"]


def test_registry_user_disabled_sends_bye_4403_and_releases() -> None:
    sink = _Sink()
    clock = _Clock()
    snaps = {MGR_ID: _mgr(A)}
    reg = _registry(snaps, upstream=UpstreamRefs(sink), clock=clock)
    closed: list[tuple[dict[str, Any], int]] = []

    async def closer(frame: dict[str, Any], code: int) -> None:
        closed.append((frame, code))

    async def noop(_f: dict[str, Any]) -> None:
        return None

    evicted: list[str] = []

    async def close() -> None:
        evicted.append("x")

    async def scenario() -> int:
        c1 = ConnectionAuthz(snaps[MGR_ID], reg.services)
        reg.register(c1, noop, None, closer)
        await handle_sub(c1, {"p": {"topics": ["trades.BTCUSDT"]}}, noop)
        reg.register(ConnectionAuthz(snaps[MGR_ID], reg.services), noop, close)
        n = await reg.user_disabled(MGR_ID)
        clock.now = 31.0
        await reg.services.upstream.sweep(clock.now)
        return n

    assert asyncio.run(scenario()) == 2
    (bye, code), = closed  # fmt: skip
    assert (bye["t"], bye["p"]["reason"], code) == ("bye", "user_disabled", CLOSE_USER_DISABLED)
    assert evicted == ["x"] and len(sink.dropped) == 1
    assert asyncio.run(reg.user_disabled(MGR_ID)) == 0


def test_registry_unregister_releases_upstream_into_grace() -> None:
    clock = _Clock()
    sink = _Sink()
    reg = _registry({MGR_ID: _mgr(A)}, upstream=UpstreamRefs(sink), clock=clock)

    async def noop(_f: dict[str, Any]) -> None:
        return None

    conn = ConnectionAuthz(_mgr(A), reg.services)
    reg.register(conn, noop)
    asyncio.run(handle_sub(conn, {"p": {"topics": ["book.BTCUSDT.50"]}}, noop))
    reg.unregister(conn)
    assert asyncio.run(reg.services.upstream.sweep(29.9)) == []
    assert len(asyncio.run(reg.services.upstream.sweep(30.0))) == 1


# -- upstream reference counting (US-MKT-005) ----------------------------------------------------


def test_three_panes_two_connections_share_one_upstream_and_drop_after_grace() -> None:
    clock = _Clock()
    sink = _Sink()
    services = _services(upstream=UpstreamRefs(sink), clock=clock)
    c1 = ConnectionAuthz(_mgr(A), services)
    c2 = ConnectionAuthz(_viewer(), services)
    _sub(c1, "book.BTCUSDT.50")
    _sub(c2, "book.BTCUSDT.50")
    _sub(c2, "book.BTCUSDT.50", replay_session_id=RS)  # third pane (replay: no upstream)
    key = ("BTCUSDT", "book", ("50",))
    assert sink.opened == [key] and services.upstream.consumers(key) == 2
    c1.unsubscribe("book.BTCUSDT.50")
    c2.release_all()
    clock.now = 10.0
    assert asyncio.run(services.upstream.sweep(clock.now)) == []
    assert asyncio.run(services.upstream.sweep(29.99)) == []
    assert asyncio.run(services.upstream.sweep(30.0)) == [key]
    assert sink.dropped == [key]


def test_reopen_inside_grace_does_not_churn_upstream() -> None:
    clock = _Clock()
    sink = _Sink()
    services = _services(upstream=UpstreamRefs(sink), clock=clock)
    conn = ConnectionAuthz(_mgr(A), services)
    _sub(conn, "trades.BTCUSDT")
    conn.unsubscribe("trades.BTCUSDT")
    clock.now = 20.0
    _sub(conn, "trades.BTCUSDT")
    assert asyncio.run(services.upstream.sweep(100.0)) == []
    assert len(sink.opened) == 1 and sink.dropped == []


def test_batched_ticker_takes_one_ref_per_symbol() -> None:
    sink = _Sink()
    conn = ConnectionAuthz(_mgr(A), _services(upstream=UpstreamRefs(sink)))
    _sub(conn, {"ch": "ticker", "opts": {"symbols": ["BTCUSDT", "ETHUSDT"]}})
    assert sorted(k[0] for k in sink.opened) == ["BTCUSDT", "ETHUSDT"]


def test_private_topics_take_no_upstream_ref() -> None:
    sink = _Sink()
    conn = ConnectionAuthz(_mgr(A), _services(upstream=UpstreamRefs(sink)))
    _sub(conn, {"ch": "positions", "opts": _acc(A)})
    assert sink.opened == []


# -- BarBuilderSet lease (spec cap) --------------------------------------------------------------


def test_bars_sub_registers_series_with_the_authenticated_principal() -> None:
    bars = _Bars()
    conn = ConnectionAuthz(_mgr(A), _services(bars=bars), connection_id="c-x")
    (r,) = _sub(conn, {"ch": "bars.BTCUSDT.time.5", "opts": {"history": 5}})
    assert r["ok"]
    ((spec_hash, sym, consumer, user),) = bars.registered
    assert (sym, consumer, user) == ("BTCUSDT", "c-x/" + r["sub_id"], str(MGR_ID))
    conn.unsubscribe("bars.BTCUSDT.time.5")
    assert bars.released == [(spec_hash, "BTCUSDT", "c-x/" + r["sub_id"])]


def test_bars_spec_cap_maps_to_subscription_limit_and_creates_nothing() -> None:
    bars = _Bars(fail=SpecCapExceeded("per_user", 8, 8))
    conn = ConnectionAuthz(_mgr(A), _services(bars=bars))
    (r,) = _sub(conn, "footprint.BTCUSDT.tick.100")
    assert r["error"]["code"] == "subscription_limit" and conn.by_id == {}


def test_bars_unbuildable_spec_is_invalid_topic_format() -> None:
    conn = ConnectionAuthz(_mgr(A), _services(bars=_Bars(fail=BarSpecError("no"))))
    (r,) = _sub(conn, "bars.BTCUSDT.pnf.10:3")
    assert r["error"]["code"] == "invalid_topic_format" and conn.by_id == {}


def test_replay_bars_never_take_a_live_lease() -> None:
    bars = _Bars()
    conn = ConnectionAuthz(_mgr(A), _services(bars=bars))
    _sub(conn, "bars.BTCUSDT.time.5", replay_session_id=RS)
    assert bars.registered == []


def test_release_all_logs_a_raising_release_and_still_releases_the_other_leases() -> None:
    """#2735: `BarBuilderSet.release` raises `BarsError` for a lease another connection's failed
    `register` dropped along with the shared series. One such release must not strand the upstream
    refs and bar leases of the subscriptions after it."""

    class _FirstReleaseRaises(_Bars):
        def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
            super().release(spec_hash, symbol, consumer)
            if len(self.released) == 1:
                raise BarsError("the series was dropped")

    bars = _FirstReleaseRaises()
    services = _services(bars=bars)
    conn = ConnectionAuthz(_mgr(A), services, connection_id="c-x")
    results = _sub(conn, "bars.BTCUSDT.time.5", "bars.ETHUSDT.time.5", "bars.SOLUSDT.time.5")
    consumers = [f"c-x/{r['sub_id']}" for r in results]

    with capture_logs() as logs:
        conn.release_all()  # does not raise

    assert [consumer for _hash, _symbol, consumer in bars.released] == consumers
    assert [services.upstream.consumers(key) for key in services.upstream.active()] == [0, 0, 0]
    assert conn.by_id == {} and conn.topics == set()
    (failed,) = [e for e in logs if e["event"] == "ws subscription release failed"]
    assert (failed["consumer"], bool(failed["exc_info"])) == (consumers[0], True)


# -- audit ---------------------------------------------------------------------------------------


def test_denials_are_audited_and_audit_failure_is_not_fatal() -> None:
    audit = _Audit()
    conn = ConnectionAuthz(_mgr(A), _services(audit=audit))
    _sub(conn, {"ch": "positions", "opts": _acc(B)}, "book.ETHUSD.50", {"ch": "orders", "opts": 1})
    assert [(r["action"], r["reason"]) for r in audit.records] == [
        ("ws.subscribe.denied", "account_scope_denied"),
        ("ws.subscribe.denied", "invalid_options"),
    ]

    class _Broken:
        async def emit(self, action: str, **kw: Any) -> None:
            raise RuntimeError("down")

    conn2 = ConnectionAuthz(_viewer(), _services(audit=_Broken()))
    (r,) = _sub(conn2, {"ch": "positions", "opts": _acc(A)})
    assert r["error"]["code"] == "forbidden"
    assert _apply(conn2, _viewer(), 1)  # no crash either
    reg = _registry({VIEWER_ID: _viewer()}, audit=_Broken())

    async def noop(_f: dict[str, Any]) -> None:
        return None

    c3 = ConnectionAuthz(PrincipalSnapshot(VIEWER_ID, _viewer().roles, MGR_PERMS, (_grant(A),)),
                         reg.services)  # fmt: skip
    reg.register(c3, noop)
    _sub(c3, {"ch": "positions", "opts": _acc(A)})
    asyncio.run(reg.roles_changed(VIEWER_ID))  # revocation audit fails: still delivered
    assert c3.by_id == {}


# -- #399 slice E: bars subscribe guards (23-ws-protocol.md §6.1, SR-E12-03, SR-E12-07) ---------


def test_bars_topic_is_unknown_while_the_bars_feature_is_off() -> None:
    conn = ConnectionAuthz(_mgr(A), _services(bars_off=True))
    bars, footprint = _sub(conn, "bars.BTCUSDT.time.5", "footprint.BTCUSDT.time.5")
    assert (bars["ok"], bars["error"]["code"]) == (False, "unknown_topic")
    assert footprint["ok"] is True  # footprint keeps §7.7 (pending) until #2197
    assert [s.ch for s in conn.by_id.values()] == ["footprint.BTCUSDT.time.5"]


@pytest.mark.parametrize(
    ("ch", "bound"),
    [("bars.BTCUSDT.tick.99", "100 and 1000000"), ("bars.BTCUSDT.tick.1000001", "100 and 1000000"),
     ("bars.BTCUSDT.range.1", "2 and 100000"), ("footprint.BTCUSDT.tick.50", "100 and 1000000")],
)  # fmt: skip
def test_bars_param_outside_its_bounds_is_refused_naming_the_bound(ch: str, bound: str) -> None:
    """SR-E12-03 on the WS path, as on REST: refused before any builder is registered."""
    bars = _Bars()
    conn = ConnectionAuthz(_mgr(A), _services(bars=bars))
    (r,) = _sub(conn, ch)
    assert (r["ok"], r["error"]["code"]) == (False, "invalid_topic_format")
    assert r["error"]["message"].endswith(f"must be between {bound}.")
    assert bars.registered == [] and conn.by_id == {}


def test_bars_param_at_its_bounds_is_accepted() -> None:
    bars = _Bars()
    conn = ConnectionAuthz(_mgr(A), _services(bars=bars))
    assert all(r["ok"] for r in _sub(conn, "bars.BTCUSDT.tick.100", "bars.BTCUSDT.range.2"))
    assert len(bars.registered) == 2


def test_bars_subscriptions_are_capped_per_connection_live_and_replay_alike() -> None:
    """SR-E12-07: the 17th `bars.*` subscription on a connection is refused."""
    conn = ConnectionAuthz(_mgr(A), _services(bars=_Bars()))
    live = [f"bars.BTCUSDT.tick.{100 + i}" for i in range(MAX_BARS_SUBSCRIPTIONS - 1)]
    assert all(r["ok"] for r in _sub(conn, *live))
    assert _sub(conn, "bars.ETHUSDT.time.5", replay_session_id=RS)[0]["ok"]
    (r,) = _sub(conn, "bars.BTCUSDT.time.5")
    assert (r["ok"], r["error"]["code"]) == (False, "subscription_limit")
    assert "16 bars subscriptions" in r["error"]["message"]
    assert _sub(conn, "footprint.BTCUSDT.time.5")[0]["ok"]  # other families are not capped here


def test_bar_service_shutting_down_is_a_retryable_internal_error() -> None:
    conn = ConnectionAuthz(_mgr(A), _services(bars=_Bars(fail=BarServiceStopping("stopping"))))
    (r,) = _sub(conn, "bars.BTCUSDT.time.5")
    assert (r["ok"], r["error"]["code"]) == (False, "internal_error")
    assert conn.by_id == {}


def test_bars_effective_echoes_the_defaults_and_explicit_values() -> None:
    conn = ConnectionAuthz(_mgr(A), _services(bars=_Bars()))
    default, explicit = _sub(
        conn,
        "bars.BTCUSDT.time.5",
        {"ch": "bars.BTCUSDT.time.1", "opts": {"history": 0, "include_delta": True}},
    )
    assert (default["effective"]["history"], default["effective"]["include_delta"]) == (500, False)
    assert (explicit["effective"]["history"], explicit["effective"]["include_delta"]) == (0, True)


def test_replay_bars_param_outside_its_bounds_is_refused_too() -> None:
    """SR-E12-03 holds on the replay path, which takes no live lease."""
    conn = ConnectionAuthz(_mgr(A), _services(bars=_Bars()))
    (r,) = _sub(conn, "bars.BTCUSDT.tick.1", replay_session_id=RS)
    assert (r["ok"], r["error"]["code"]) == (False, "invalid_topic_format")
    assert r["error"]["message"].endswith("must be between 100 and 1000000.")


def test_the_17th_bars_topic_of_one_frame_is_refused_and_an_unsub_frees_a_slot() -> None:
    conn = ConnectionAuthz(_mgr(A), _services(bars=_Bars()))
    topics = [f"bars.BTCUSDT.tick.{100 + i}" for i in range(MAX_BARS_SUBSCRIPTIONS + 1)]
    res = _sub(conn, *topics)
    assert [r["ok"] for r in res] == [True] * MAX_BARS_SUBSCRIPTIONS + [False]
    assert res[-1]["error"]["code"] == "subscription_limit"
    conn.unsubscribe(topics[0])
    assert _sub(conn, topics[-1])[0]["ok"]


def test_bars_volume_param_above_its_ceiling_is_refused() -> None:
    conn = ConnectionAuthz(_mgr(A), _services(bars=_Bars()))
    (r,) = _sub(conn, "bars.BTCUSDT.volume.1000000000001")
    assert r["error"]["message"].endswith("must be between 1 and 1000000000000.")
