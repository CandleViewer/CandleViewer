"""SR-193 (#2293): `resync`, re-snapshotting `ctl` and `sub` starts draw on one rebuild budget per
connection (`23-ws-protocol.md` §5.2, §5.4, §7.5, §7.7); the limits are §7.5's numbers."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.ws.permissions import handle_ctl, handle_sub
from candleviewer.ws.sequencing import SequencingHub
from tests.unit.ws._seq_support import ACC_A, ACC_B, Conn
from tests.unit.ws.test_sequencing import RS, _book_source, _CappedBars, _hold, _resync

TOPIC, CONNECTION, WINDOW = 5, 400, 60.0  # 23 §7.5
BOOK, HEAT = "book.BTCUSDT.50", "heatmap.BTCUSDT"
NOT_TAKEN = "Rebuild budget spent ({} a minute per {}); no snapshot was taken."


def _refused(path: str, scope: str) -> float:
    """One refusal series (bound at import: `test_rebuild_budget.py`)."""
    labels = {"kind": path, "cause": scope}
    return REGISTRY.get_sample_value("cv_ws_rebuild_refused_total", labels) or 0.0


def _ctl(conn: Conn, body: dict[str, Any], ch: str = HEAT) -> dict[str, Any]:
    reply = handle_ctl(conn.authz, {"t": "ctl", "id": "c-7", "ch": ch, "p": body}, 1)
    conn.push(reply)  # schema-checked like every frame the connection sends
    return reply


def _resume(conn: Conn, ch: str = BOOK) -> dict[str, Any]:
    """A pause, then a resume: the resume re-snapshots (§5.4, #2517), the pause does not."""
    _ctl(conn, {"paused": True}, ch)
    return _ctl(conn, {"paused": False}, ch)


def _sub(conn: Conn, *topics: Any) -> list[dict[str, Any]]:
    """One `sub` frame through `handle_sub`; its results (the `sub_ok` is schema-checked)."""
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        conn.push(frame)
        sent.append(frame)

    entries = [t if isinstance(t, dict) else {"ch": t} for t in topics]
    asyncio.run(handle_sub(conn.authz, {"t": "sub", "p": {"topics": entries}}, send, now_ms=1))
    results: list[dict[str, Any]] = sent[0]["p"]["results"]
    return results


def test_a_ctl_identity_flip_loop_is_refused_at_the_sixth_and_the_refusal_changes_nothing() -> None:
    src = _book_source()
    src.unavailable.add("BTCUSDT")  # the `initial` snap stays pending: a re-snapshot draws anyway
    conn, drops = Conn(src), list[Any]()
    conn.authz.on_drop = drops.append  # #3193: a re-snapshotting `ctl` drops the old stream
    _, sub = conn.sub(HEAT)
    for body in ({"throttle_ms": 200}, {"paused": False}, {"time_bucket_ms": 500}):
        assert "resnapshot" not in _ctl(conn, body)["p"]  # no re-snapshot: nothing drawn
    for i in range(TOPIC):
        conn.clock.now = float(i)
        assert _ctl(conn, {"time_bucket_ms": (1000, 500)[i % 2]})["p"]["resnapshot"] is True
    kept = (dict(sub.opts), dict(sub.effective), sub.snapshot_pending, sub.pending_reason)
    before = _refused("ctl", "topic")
    conn.clock.now = WINDOW - 1
    with capture_logs() as logs:
        err = _ctl(conn, {"time_bucket_ms": 5000, "throttle_ms": 1000, "paused": True})
        for _ in range(11):  # the line is capped per path: 10, then one `capped`, then none
            _ctl(conn, {"time_bucket_ms": 5000})
        _resync(conn, HEAT)  # another path: its line has its own cap
    lines = [(e["path"], e.get("capped")) for e in logs if e["event"] == "ws resync rate limited"]
    assert lines == [("ctl", None)] * 10 + [("ctl", True), ("resync", None)]
    told = "Rebuild budget spent (5 a minute per topic); nothing was changed."
    assert (err["t"], err["id"], err["ch"]) == ("err", "c-7", HEAT)
    assert (err["p"]["code"], err["p"]["message"]) == ("resync_rate_limited", told)
    assert (dict(sub.opts), dict(sub.effective), sub.snapshot_pending, sub.pending_reason) == kept
    assert (_refused("ctl", "topic"), len(drops)) == (before + 12, TOPIC)  # refusals drop none
    assert conn.authz.find(HEAT) is sub and "resnapshot" not in _ctl(conn, {"throttle_ms": 9})["p"]
    conn.clock.now = WINDOW  # the first flip is a full window old
    assert _ctl(conn, {"time_bucket_ms": 5000})["p"]["resnapshot"] is True


@pytest.mark.parametrize("held", [False, True], ids=["settled", "held-for-backpressure"])
@pytest.mark.parametrize("resumes", [3, 1])
def test_resync_and_a_resuming_ctl_draw_on_one_topic_budget(resumes: int, held: bool) -> None:
    conn = Conn(_book_source())
    _, sub = conn.sub(BOOK)
    conn.take()
    if held:
        _hold(sub)  # the ladder alone sends that snap, yet each request still draws (§7.7)
    for i in range(resumes):
        conn.clock.now = float(i)
        assert _resume(conn)["p"]["resnapshot"] is True
        conn.emitter.flush_pending([sub])  # the gateway's flush after `ctl_ok`
    for _ in range(TOPIC - resumes):
        _resync(conn, BOOK)
    snaps = [f["meta"]["reason"] for f in conn.take() if f["t"] == "snap"]
    own = ["client_resync"] * (TOPIC - resumes)
    assert snaps == ([] if held else ["reconfigure"] * resumes + own)
    before = _refused("resync", "topic")
    _resync(conn, BOOK)  # refused, yet a `ctl` is among the topic's five: not its own loop
    (err,) = conn.take()
    assert (err["t"], err["id"], err["p"]["code"]) == ("err", "c-90", "resync_rate_limited")
    assert err["p"]["message"] == NOT_TAKEN.format(5, "topic")
    assert conn.authz.find(BOOK) is sub and _refused("resync", "topic") == before + 1


def test_a_topic_and_its_replay_session_draw_on_separate_shares() -> None:
    conn, other = Conn(_book_source()), "book.BTCUSDT.050"
    conn.sub(BOOK)
    conn.sub(other)
    conn.sub(BOOK, replay_session_id=RS)
    for _ in range(2):
        _resume(conn, other)
    for ch in (BOOK, other, other, BOOK):
        _resync(conn, ch)  # the last is the topic's sixth draw, three of them resyncs: refused
    answers = [f["t"] for f in conn.take() if f["t"] in ("snap", "err")]
    assert answers[-4:] == ["snap", "snap", "snap", "err"]
    replay = {"t": "resync", "ch": BOOK, "rs": RS, "p": {"reason": "manual"}}  # §7.5 (#3218)
    for _ in range(TOPIC):  # named by its `rs` while the live topic's five are spent
        conn.emitter.client_resync(conn.authz, replay)
    assert [(f["t"], f.get("rs")) for f in conn.take()] == [("snap", RS)] * TOPIC


def test_a_replay_stream_s_ctl_draws_on_its_share_and_a_refused_resync_names_it() -> None:
    """W10, §7.5 (#3218): a `ctl` naming `rs` draws on that replay stream's share. Its refused
    `resync`, with one of the five draws a `ctl`'s, is no loop: the stream continues, and the
    `err` carries its `rs`. The live stream's share is untouched."""
    conn = Conn(_book_source())
    conn.sub(BOOK)
    conn.sub(BOOK, replay_session_id=RS)
    for paused in (True, False):  # the resume draws (§5.4, #2517), the pause does not
        frame = {"t": "ctl", "id": "c-8", "ch": BOOK, "rs": RS, "p": {"paused": paused}}
        conn.push(handle_ctl(conn.authz, frame, 1))
    replay = {"t": "resync", "id": "c-9", "ch": BOOK, "rs": RS, "p": {"reason": "manual"}}
    for _ in range(TOPIC):
        conn.emitter.client_resync(conn.authz, replay)
    _resync(conn, BOOK)
    answers = [(f["t"], f.get("rs")) for f in conn.take() if f["t"] in ("snap", "err")]
    tail = [("snap", RS)] * (TOPIC - 1) + [("err", RS), ("snap", None)]
    assert (answers[-len(tail) :], conn.authz.find(BOOK, RS) is not None) == (tail, True)


def test_the_server_s_own_snapshots_never_draw() -> None:
    hub, conn = SequencingHub(), Conn(_book_source())
    hub.register(conn.authz, conn.emitter)
    _, live = conn.sub(BOOK)
    conn.sub(BOOK, replay_session_id=RS)
    for _ in range(TOPIC + 1):  # more of each than the topic's limit
        hub.upstream_desync("BTCUSDT")
        hub.upstream_reconnect("BTCUSDT")
        hub.instrument_revision("BTCUSDT")
        hub.resnapshot(lambda s: True, "generation_swap")
        hub.replay_seek(RS)
        _hold(live)
        assert conn.emitter.snapshot(live, "backpressure")  # the overflow ladder's `drain`
    rounds = 1 + 1 + 2 + 2 + 1 + 1  # live; live; both; both; replay; live
    assert len([f for f in conn.take() if f["t"] == "snap"]) == 2 + (TOPIC + 1) * rounds
    for _ in range(TOPIC):
        _resync(conn, BOOK)
    assert [f["t"] for f in conn.take()] == ["snap"] * TOPIC  # all five are left


_DEPTHS = (1, 50, 200, 500)  # with `trades`, five topics on each of 40 symbols: the 200 cap
_HELD = [f"book.S{i % 40:02d}USDT.{_DEPTHS[i // 40]}" for i in range(160)]
_HELD += [f"trades.S{i:02d}USDT" for i in range(40)]
_FOREIGN = {"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_B)]}}


@pytest.mark.parametrize(
    ("held", "entry", "code"),
    [
        (40, "trades.S99USDT", "subscription_limit"),  # a 41st symbol
        (200, "ticker.S00USDT", "subscription_limit"),  # a 201st subscription
        (0, _FOREIGN, "account_scope_denied"),
    ],
    ids=["symbol-cap", "subscription-cap", "foreign-account"],
)
def test_the_caps_and_scope_refuse_before_a_spent_budget(held: int, entry: Any, code: str) -> None:
    """§5.2: refusals decided from the entry come first and draw nothing; each says if retryable."""
    authz = Conn(_book_source()).authz
    for ch in _HELD[:held]:
        assert authz.admit(ch)[1] is not None
    for i in range(CONNECTION):  # the connection's limit spent
        authz.rebuilds.take((f"x.S{i:03d}", None), "ctl")
    before, error = _refused("sub", "connection"), authz.admit(entry)[0]["error"]
    assert (error["code"], error["retryable"]) == (code, code == "subscription_limit")
    assert _refused("sub", "connection") == before


def test_unsub_and_sub_churn_of_a_topic_is_refused_at_its_sixth_restart() -> None:
    conn = Conn(_book_source())
    assert [r["ok"] for r in _sub(conn, BOOK)] == [True]  # a first `sub`: the connection's only
    for _ in range(TOPIC):
        conn.authz.unsubscribe(BOOK)
        assert [r["ok"] for r in _sub(conn, BOOK)] == [True]
    conn.authz.unsubscribe(BOOK)
    with capture_logs() as logs:
        refused, other = _sub(conn, BOOK, "trades.ETHUSDT")
    assert (refused["ok"], other["ok"], conn.authz.find(BOOK)) == (False, True, None)
    err, (line,) = refused["error"], [e for e in logs if e["event"] == "ws resync rate limited"]
    assert (err["code"], err["retryable"], line["scope"]) == ("resync_rate_limited", True, "topic")
    assert err["message"] == "Rebuild budget spent (5 a minute per topic); not subscribed."
    conn.clock.now = WINDOW  # its five starts leave the window
    assert [r["ok"] for r in _sub(conn, BOOK)] == [True]


def test_a_spent_connection_refuses_new_topics_resyncs_and_resumes_and_never_revokes() -> None:
    conn, sink = Conn(_book_source()), AsyncMock()
    conn.authz.services.audit = sink
    _sub(conn, BOOK)
    for i in range(CONNECTION - 1):  # with that first `sub`, the connection's 400
        assert conn.authz.rebuilds.take((f"trades.S{i:03d}USDT", None), "ctl") is None
    before = _refused("sub", "connection")
    positions = {"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_A)]}}
    with capture_logs() as logs:
        results = _sub(conn, "trades.ETHUSDT", BOOK, positions, "nope.BTCUSDT")
    codes = [r["error"]["code"] for r in results]
    spent = "resync_rate_limited"
    assert codes == [spent, "duplicate_subscription", spent, "unknown_topic"]
    told = "Rebuild budget spent (400 a minute per connection); not subscribed."
    assert results[0]["error"]["message"] == told and conn.authz.find("trades.ETHUSDT") is None
    assert _refused("sub", "connection") == before + 2  # one per refused entry
    line = {"connection_id": conn.authz.connection_id, "ch": "trades.ETHUSDT", "count": 2}
    assert [e for e in logs if e["event"] == "ws resync rate limited"] == [
        {"event": "ws resync rate limited", "log_level": "warning", **line, "path": "sub"}
        | {"scope": "connection", "limit": CONNECTION, "window_s": WINDOW}
    ]
    # A private topic's refusal, whatever its code, is in the frame's one record (§5.2 Audit).
    (row,) = sink.emit.await_args_list
    denied = (row.args[0], row.kwargs["object_id"], row.kwargs["reason"])
    assert denied == ("ws.subscribe.denied", "positions", "resync_rate_limited")
    paths_before = [_refused(p, "connection") for p in ("resync", "ctl")]
    with capture_logs() as logs:  # the other two paths: refused at the limit, never revoked
        _resync(conn, BOOK)
        messages = [conn.take()[-1]["p"]["message"], _resume(conn)["p"]["message"]]
    spent_400 = "Rebuild budget spent (400 a minute per connection);"
    assert messages == [f"{spent_400} no snapshot was taken.", f"{spent_400} nothing was changed."]
    scopes = {e["path"]: e["scope"] for e in logs if e["event"] == "ws resync rate limited"}
    assert scopes == {"resync": "connection", "ctl": "connection"} and conn.authz.find(BOOK)
    assert [_refused(p, "connection") for p in ("resync", "ctl")] == [n + 1 for n in paths_before]


def test_an_entry_refused_at_the_upstream_step_draws_nothing_and_releases_nothing() -> None:
    conn, bars = Conn(_book_source()), "bars.BTCUSDT.time.5"
    conn.authz.services.bars = _CappedBars()  # its lease is refused: `subscription_limit`
    for i in range(CONNECTION - 2):  # five on the bars topic, the rest elsewhere: room for two
        key = (bars, None) if i < TOPIC else (f"trades.S{i:03d}USDT", None)
        assert conn.authz.rebuilds.take(key, "ctl") is None
    capped, book = _sub(conn, bars, BOOK)
    assert (capped["error"]["code"], book["ok"]) == ("subscription_limit", True)
    conn.authz.services.bars = None  # no lease to take now
    assert [r["ok"] for r in _sub(conn, bars)] == [True]  # still a first `sub`, and with room
