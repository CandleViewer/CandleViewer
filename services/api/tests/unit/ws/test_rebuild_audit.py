"""#3476 (`23-ws-protocol.md` §7.7): a user's first `user` refusal in a window leaves one
`ws.rebuild.refused` record, written after the refusal went out. Best effort and bounded: a record
not confirmed is counted and logged and changes no refusal; a cancellation propagates."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.ws import permissions
from candleviewer.ws.permissions import audit_rebuild_refusal, handle_ctl
from tests.unit.ws._seq_support import Conn
from tests.unit.ws.test_rebuild_paths import BOOK, HEAT, _asub, _one_user, _resume, _Rows

TOLD = "Rebuild budget spent (1 a minute per user); nothing was changed."


def _failures(reason: str) -> float:
    labels = {"reason": reason}
    return REGISTRY.get_sample_value("cv_ws_audit_failures_total", labels) or 0.0


class _Sink:
    """An audit sink that raises (`error`), or waits until its bound or a cancel ends it."""

    def __init__(self, fault: str) -> None:
        self.fault, self.entered = fault, asyncio.Event()

    async def emit(self, action: str, **row: Any) -> None:
        self.entered.set()
        if self.fault == "error":
            raise RuntimeError("the audit store is down")
        await asyncio.Event().wait()


class _Held:
    """An audit sink that counts the writes asked of it. The first raises (`error`) or waits for
    `go` (`timeout`: the writer's bound cuts it when no test sets `go`); every later one is kept
    at once."""

    def __init__(self, fault: str = "timeout") -> None:
        self.fault, self.entered, self.go = fault, asyncio.Event(), asyncio.Event()
        self.calls, self.rows = 0, list[str]()

    async def emit(self, action: str, **row: Any) -> None:
        self.calls += 1
        self.entered.set()
        if self.calls == 1:
            if self.fault == "error":
                raise RuntimeError("the audit store is down")
            await self.go.wait()
        self.rows.append(row["object_id"])


async def _refused_resume(fault: str) -> tuple[Conn, dict[str, Any], _Sink]:
    """A user with a limit of 1, spent by its `sub`: its resume is refused, a record due."""
    (conn,) = _one_user(1, limit=1)
    conn.authz.services.audit = sink = _Sink(fault)
    await _asub(conn, BOOK)
    for paused in (True, False):
        reply = handle_ctl(conn.authz, {"t": "ctl", "ch": BOOK, "p": {"paused": paused}}, 1)
    return conn, reply, sink


@pytest.mark.parametrize("fault", ["error", "timeout"])
async def test_a_record_not_confirmed_is_counted_and_the_refusal_stands(
    fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(permissions, "FANOUT_AUDIT_TIMEOUT_S", 0.01)
    conn, reply, sink = await _refused_resume(fault)
    before = _failures(fault)
    with capture_logs() as logs:
        async with asyncio.timeout(5):
            await audit_rebuild_refusal(conn.authz)  # never raises
            await audit_rebuild_refusal(conn.authz)  # nothing more is due
    (line,) = [e for e in logs if e["event"] == "ws audit not confirmed"]
    assert (line["action"], line["object_id"]) == ("ws.rebuild.refused", "book")
    assert (reply["t"], reply["p"]["message"], sink.entered.is_set()) == ("err", TOLD, True)
    assert _failures(fault) == before + 1
    sub = conn.authz.find(BOOK)
    assert sub is not None and sub.effective["paused"] is True  # the refused resume changed nothing


async def test_a_cancelled_record_write_is_counted_and_propagates() -> None:
    conn, _, sink = await _refused_resume("stall")
    before = _failures("cancelled")
    task = asyncio.create_task(audit_rebuild_refusal(conn.authz))
    async with asyncio.timeout(5):
        await sink.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _failures("cancelled") == before + 1


@pytest.mark.parametrize("ended", ["sub", "ctl"])
async def test_a_record_its_request_never_wrote_is_left_to_the_next_refusal(ended: str) -> None:
    """#3476: the window is marked as its record is written, not at the refusal. A `sub` frame
    cancelled during its `ws.subscribe.denied` write, or a refused `ctl` whose write never ran (a
    `flush` that raised first), writes no record; the user's next `user` refusal, on another
    connection, writes the window's one."""
    a, b = _one_user(2, limit=1)
    a.authz.services.audit = rows = _Rows(block="ws.subscribe.denied")
    await _asub(a, BOOK)  # the user's one draw
    if ended == "sub":  # HEAT is refused for the user, then `wallet` is forbidden
        frame = asyncio.create_task(_asub(a, HEAT, "wallet"))
        async with asyncio.timeout(5):
            await rows.entered.wait()
        frame.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await frame
    else:
        _resume(a)
    assert [r["ok"] for r in await _asub(b, "trades.BTCUSDT")] == [False]
    assert [(action, row["object_id"]) for action, row, _ in rows.rows] == [
        ("ws.rebuild.refused", "trades")
    ]


async def test_a_sub_entry_s_record_is_written_after_its_frame_s_sub_ok() -> None:
    """#3476 (23 §7.7): a refused `sub` entry's record is written once its frame's `sub_ok` went
    to `send`, as the gateway writes a `ctl`'s or `resync`'s after its reply."""
    (conn,) = _one_user(1, limit=1)
    conn.authz.services.audit = rows = _Rows(conn.out)
    await _asub(conn, BOOK)
    conn.out.clear()
    await _asub(conn, HEAT)  # refused for the user
    assert [(action, sent) for action, _, sent in rows.rows] == [("ws.rebuild.refused", ["sub_ok"])]


async def test_two_sockets_of_one_user_racing_to_write_leave_one_record_a_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#3476 (23 §7.7): the window is marked as a write starts. Two sockets of one user, A and B,
    are refused for the user; while A's write is in flight, B's refusal finds the window marked
    and `handle_sub` writes none for it: the user has one record."""
    monkeypatch.setattr(permissions, "FANOUT_AUDIT_TIMEOUT_S", 30.0)  # a held write is not cut
    a, b = _one_user(2, limit=1)
    a.authz.services.audit = sink = _Held()
    await _asub(a, BOOK)  # the user's one draw
    _resume(a)  # refused for the user: A's record is due
    write = asyncio.create_task(audit_rebuild_refusal(a.authz))
    async with asyncio.timeout(5):
        await sink.entered.wait()  # A's write is in flight
    assert [r["ok"] for r in await _asub(b, HEAT)] == [False]  # refused for the user: no write
    # B's call ran, took its due key and found the window marked:
    assert b.authz.rebuilds.audit_due is None
    assert sink.calls == 1
    sink.go.set()
    async with asyncio.timeout(5):
        await write
    assert sink.rows == ["book"]


@pytest.mark.parametrize("fault", ["timeout", "error"])
async def test_a_record_not_confirmed_leaves_the_window_marked_for_the_user_s_next_refusal(
    fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3476 (23 §7.7): a write not confirmed, cut at its bound (`timeout`) or raised (`error`),
    does not reopen the window. A later `user` refusal in it, on the user's other socket, reaches
    no writer: one attempt for the window."""
    monkeypatch.setattr(permissions, "FANOUT_AUDIT_TIMEOUT_S", 0.01)
    a, b = _one_user(2, limit=1)
    a.authz.services.audit = sink = _Held(fault)  # the first write is cut at the bound, or raises
    await _asub(a, BOOK)
    _resume(a)
    async with asyncio.timeout(5):
        await audit_rebuild_refusal(a.authz)  # not confirmed: counted, logged
        assert [r["ok"] for r in await _asub(b, HEAT)] == [False]
    assert (sink.calls, sink.rows) == (1, [])


async def test_a_cancelled_record_write_leaves_the_window_marked_for_the_user_s_next_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#3476 (23 §4.3, §7.7): a write cancelled while it runs, the third way a record is not
    confirmed, does not reopen the window. The cancel propagates, and a later `user` refusal in it,
    on the user's other socket, reaches no writer: one attempt for the window."""
    monkeypatch.setattr(permissions, "FANOUT_AUDIT_TIMEOUT_S", 30.0)  # a held write is not cut
    a, b = _one_user(2, limit=1)
    a.authz.services.audit = sink = _Held()  # the first write waits for `go`: only a cancel ends it
    await _asub(a, BOOK)
    _resume(a)
    write = asyncio.create_task(audit_rebuild_refusal(a.authz))
    async with asyncio.timeout(5):
        await sink.entered.wait()  # A's write is in flight
    write.cancel()
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(5):  # inside `raises`: a cancel that hangs is a TimeoutError
            await write
    async with asyncio.timeout(5):
        assert [r["ok"] for r in await _asub(b, HEAT)] == [False]
        # B's call ran, took its due key and found the window marked:
        assert b.authz.rebuilds.audit_due is None
        assert (sink.calls, sink.rows) == (1, [])
