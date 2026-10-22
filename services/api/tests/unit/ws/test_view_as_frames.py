"""§9.6 (#3085): a viewing session's action frames change nothing.

`cv.v1` has no action frame: every client frame type of §3.1 reads or tunes the connection
(`READ_FRAME_TYPES`), and `ACTION_FRAME_TYPES` is empty. A type added later that changes
server-side state is an action frame unless its change lists it as a read frame. While the session
views as another user, the gateway answers an action frame with `err` `view_as_read_only` carrying
its `id`, keeps the socket open (no strike) and writes one refusal record, whose object is the
frame type; the `err` is sent whatever the record does. Here a test type, `act`, stands for one.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

import pytest

from candleviewer.auth.view_as import ViewAsBinding, ViewAsPhase
from candleviewer.view_as_wiring import SessionViewAsRefusals
from candleviewer.ws import gateway
from tests.unit.ws._auth_rig import DEADLINE_S, LATER, Rig, Sock, hang_up, user_of

_VIEWER, _TARGET = user_of("good-1"), user_of("good-9")


class _Refusals:
    def __init__(self, fails: bool = False) -> None:
        self.fails, self.calls = fails, list[dict[str, Any]]()

    async def refuse_frame(self, **kwargs: Any) -> bool:
        self.calls.append(kwargs)
        if self.fails:
            raise ConnectionError("the audit store is down")
        return True


def _rig(refusals: _Refusals, *, viewing: bool) -> Rig:
    binding = ViewAsBinding(
        context_id=uuid.uuid4(), target_user_id=_TARGET, expires_at=LATER, phase=ViewAsPhase.LIVE
    )

    async def view_as(session_id: str) -> ViewAsBinding | None:
        return binding if viewing else None

    return Rig(options={"view_as": view_as, "view_as_refusals": refusals})


def test_the_read_frames_are_the_client_frames_of_section_3_1_and_no_action_frame_yet() -> None:
    assert gateway.READ_FRAME_TYPES == {
        "hello", "auth", "ping", "pong", "sub", "unsub", "ctl", "resync",
    }  # fmt: skip
    assert gateway.ACTION_FRAME_TYPES == frozenset()


async def _send_action(refusals: _Refusals, *, viewing: bool) -> tuple[dict[str, Any], Any]:
    rig, sock = _rig(refusals, viewing=viewing), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
        sock.feed({"t": "act", "id": "x1", "p": {"secret": "never stored"}})
        reply = await sock.sent.get()
        sock.feed({"t": "ping", "id": "p1"})  # still open, and served
        assert (await sock.sent.get())["t"] == "pong"
        hang_up(sock)
        await handler
    return reply, rig


class _Hangs:
    async def refuse_frame(self, **kwargs: Any) -> bool:
        await asyncio.Event().wait()  # never set: only the bound ends it
        return True


async def test_a_refusal_record_that_never_returns_is_cut_at_its_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.18: the reader waits for the record at most `CLOSE_AUDIT_TIMEOUT_S`, so a hung
    recorder never stalls the socket: the `err` is sent past the bound, and the next frame
    is served."""
    monkeypatch.setattr(gateway, "ACTION_FRAME_TYPES", frozenset({"act"}))
    monkeypatch.setattr(gateway, "CLOSE_AUDIT_TIMEOUT_S", 0.01)
    reply, _ = await _send_action(cast(Any, _Hangs()), viewing=True)
    assert (reply["t"], reply["p"]["code"]) == ("err", "view_as_read_only")


async def test_a_viewing_sessions_action_frame_is_refused_recorded_and_the_socket_stays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway, "ACTION_FRAME_TYPES", frozenset({"act"}))
    refusals = _Refusals()
    reply, _ = await _send_action(refusals, viewing=True)
    assert (reply["t"], reply["p"]["code"], reply["id"]) == ("err", "view_as_read_only", "x1")
    assert refusals.calls == [
        {
            "viewer_user_id": _VIEWER,
            "viewer_session_id": "sess-good-1",
            "frame_type": "act",
            "ip": "127.0.0.1",
        }
    ]


async def test_the_err_is_sent_when_the_record_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway, "ACTION_FRAME_TYPES", frozenset({"act"}))
    reply, _ = await _send_action(_Refusals(fails=True), viewing=True)
    assert (reply["t"], reply["p"]["code"]) == ("err", "view_as_read_only")


async def test_an_action_frame_outside_a_view_is_an_unknown_frame_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway, "ACTION_FRAME_TYPES", frozenset({"act"}))
    refusals = _Refusals()
    reply, _ = await _send_action(refusals, viewing=False)
    assert (reply["t"], reply["p"]["code"]) == ("err", "frame_malformed")
    assert refusals.calls == []


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, str | None]] = []

    async def refuse_frame(self, viewer: Any, frame_type: str, *, ip: str | None) -> bool:
        self.calls.append((viewer, frame_type, ip))
        return True


class _Labels:
    def __init__(self, names: dict[uuid.UUID, str]) -> None:
        self.names = names

    async def usernames(self, user_ids: Any) -> dict[uuid.UUID, str]:
        return {u: self.names[u] for u in user_ids if u in self.names}


async def test_the_record_names_the_viewer_by_username_and_the_viewers_session() -> None:
    recorder, session = _Recorder(), uuid.uuid4()
    labels = cast(Any, _Labels({_VIEWER: "owner"}))  # the identity read, faked
    port = SessionViewAsRefusals(lambda: cast(Any, recorder), labels)
    kwargs = {"viewer_session_id": str(session), "frame_type": "act", "ip": "10.0.0.1"}
    assert await port.refuse_frame(viewer_user_id=_VIEWER, **kwargs) is True
    ((viewer, frame_type, ip),) = recorder.calls
    assert (viewer.viewer_user_id, viewer.viewer_session_id, viewer.viewer_label) == (
        _VIEWER,
        session,
        "owner",
    )
    assert (frame_type, ip) == ("act", "10.0.0.1")
    assert await port.refuse_frame(viewer_user_id=uuid.uuid4(), **kwargs) is False  # gone
    none = SessionViewAsRefusals(lambda: None, labels)
    assert await none.refuse_frame(viewer_user_id=_VIEWER, **kwargs) is False
