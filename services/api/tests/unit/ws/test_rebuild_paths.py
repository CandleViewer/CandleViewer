"""SR-193 (#2293): `resync` and re-snapshotting `ctl` draw on one rebuild budget per connection
(`23-ws-protocol.md` §5.4, §7.5, §7.7); the limits are §7.5's numbers, written out here."""

from __future__ import annotations

from typing import Any

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.ws.permissions import handle_ctl
from candleviewer.ws.sequencing import SequencingHub
from tests.unit.ws._seq_support import Conn
from tests.unit.ws.test_sequencing import RS, _book_source, _hold, _resync

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
    err = _ctl(conn, {"time_bucket_ms": 5000, "throttle_ms": 1000, "paused": True})
    told = "Rebuild budget spent (5 a minute per topic); nothing was changed."
    assert (err["t"], err["id"], err["ch"]) == ("err", "c-7", HEAT)
    assert (err["p"]["code"], err["p"]["message"]) == ("resync_rate_limited", told)
    assert (dict(sub.opts), dict(sub.effective), sub.snapshot_pending, sub.pending_reason) == kept
    assert (_refused("ctl", "topic"), len(drops)) == (before + 1, TOPIC)  # the refusal dropped none
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
    _, live = conn.sub(BOOK)
    conn.sub(other)
    conn.sub(BOOK, replay_session_id=RS)
    for _ in range(2):
        _resume(conn, other)
    for ch in (BOOK, other, other, BOOK):
        _resync(conn, ch)  # the last is the topic's sixth draw, three of them resyncs: refused
    answers = [f["t"] for f in conn.take() if f["t"] in ("snap", "err")]
    assert answers[-4:] == ["snap", "snap", "snap", "err"]
    conn.authz.revoke(live, "resync_rate_limited", 1)  # a `resync` of BOOK now finds the replay one
    for _ in range(TOPIC):
        _resync(conn, BOOK)
    assert [(f["t"], f.get("rs")) for f in conn.take()] == [("snap", RS)] * TOPIC


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


@pytest.mark.parametrize("path", ["resync", "ctl"])
def test_a_refusal_at_the_connection_limit_says_so_and_revokes_nothing(path: str) -> None:
    conn = Conn(_book_source())
    conn.sub(BOOK)
    conn.take()
    for i in range(CONNECTION):  # draws on other topics spend the connection's limit
        assert conn.authz.rebuilds.take((f"trades.S{i:03d}USDT", None), "ctl") is None
    before = _refused(path, "connection")
    with capture_logs() as logs:
        if path == "resync":
            _resync(conn, BOOK)
        else:
            _resume(conn)
    (err,) = [f for f in conn.take() if f["t"] != "ctl_ok"]
    then = "no snapshot was taken" if path == "resync" else "nothing was changed"
    assert err["p"]["message"] == f"Rebuild budget spent (400 a minute per connection); {then}."
    assert conn.authz.find(BOOK) is not None and _refused(path, "connection") == before + 1
    assert [e for e in logs if e["event"] == "ws resync rate limited"] == [
        {
            "event": "ws resync rate limited",
            "log_level": "warning",
            "connection_id": (conn.emitter if path == "resync" else conn.authz).connection_id,
            "ch": BOOK,
            "path": path,
            "scope": "connection",
            "limit": CONNECTION,
            "window_s": WINDOW,
            **({"client_reason": "sequence_gap"} if path == "resync" else {}),
        }
    ]


def test_a_refused_sub_entry_says_whether_its_code_is_retryable() -> None:
    authz = Conn(_book_source()).authz
    for i in range(40):  # the 40-symbol cap (§16.2)
        assert authz.admit(f"trades.S{i:02d}USDT")[1] is not None
    told = "40 symbols per connection reached."
    error = {"code": "subscription_limit", "message": told, "retryable": True}  # §10.2: yes
    assert authz.admit("trades.S40USDT")[0]["error"] == error
