"""#4517 (`23-ws-protocol.md` 15.9): the flags the principal's roles may see follow `auth_ok`: on a
first `auth` in the `system` snap (§12.1, #4992), on an in-place re-`auth` as one `feature_flags`
frame; then the notices."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from typing import Any

from structlog.testing import capture_logs

from candleviewer.admin.flags import FlagService, default_registry
from candleviewer.admin.flags.push import feature_flags_snapshot
from candleviewer.admin.flags.service import Resolution
from tests.unit.admin.flag_fakes import Clock, FakeFlagStore
from tests.unit.ws._auth_rig import Rig, Sock, hang_up
from tests.unit.ws.test_system_topic_roles import NOTICE, _as, _Rig, _system

_DEADLINE_S = 5.0
_OWNER_ONLY = "killswitch.ingestion"
_ROLE_FLAG = "rules.graph_editor"


async def _rig(notices: list[dict[str, Any]] | None = None, *, viewer_off: bool = False) -> _Rig:
    store = FakeFlagStore()
    service = FlagService(default_registry(), store, clock=Clock())
    await store.ensure(service.registry.values())
    if viewer_off:  # the one flag whose value differs by role, so a stale role shows in a value
        row = store.rows[_ROLE_FLAG]
        store.rows[_ROLE_FLAG] = replace(row, value=True, role_overrides={"viewer": False})
    return _Rig(
        notices=notices,
        flag_visible=default_registry().visible_to,
        flag_snapshot=lambda user, roles: feature_flags_snapshot(service, user, roles),
    )


def _keys(frames: list[tuple[int, Any]]) -> list[set[str]]:
    return [set(p["feature_flags"]) for _, p in frames if p["kind"] == "feature_flags"]


def _snap_flags(sock: Any) -> dict[str, Any]:
    """The flag set the socket's `system` snap carries (§12.1, #4992)."""
    assert sock.snap is not None and sock.snap["p"]["kind"] == "health"
    flags: dict[str, Any] = sock.snap["p"]["feature_flags"]
    return flags


async def test_the_snapshot_precedes_the_notices_and_is_cut_to_the_role() -> None:
    rig = await _rig(notices=[NOTICE])
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4(), "manager"))
        frames = await _system(sock)
        assert [(s, p["kind"]) for s, p in frames] == [(2, NOTICE["kind"])]  # folded into `s` 1
        assert _snap_flags(sock) and _OWNER_ONLY not in _snap_flags(sock)
        await rig.close()


async def test_an_owner_gets_the_owner_only_keys_in_its_snapshot() -> None:
    rig = await _rig()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4(), "owner"))
        assert set(_snap_flags(sock)) == set(default_registry())
        assert await _system(sock) == []  # never a second flag frame
        await rig.close()


async def test_a_reauth_that_changes_the_role_sends_a_fresh_snapshot_for_the_new_role() -> None:
    rig, user = await _rig(viewer_off=True), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "owner"))
        first = [set(_snap_flags(sock))]
        assert _snap_flags(sock)[_ROLE_FLAG] is True  # the owner's value
        rig.principals[user] = _as(user, "viewer")
        sock.feed({"t": "auth", "id": "re", "p": {"access_token": str(user)}})
        assert (await sock.sent.get())["t"] == "auth_ok"
        second_frames = await _system(sock)
        second = _keys(second_frames)
        assert second_frames[0][1]["feature_flags"][_ROLE_FLAG] is False  # the viewer's value
        assert [(s, p["kind"]) for s, p in second_frames] == [(2, "feature_flags")]  # no new snap
        assert _OWNER_ONLY in first[0]
        assert second and _OWNER_ONLY not in second[0] and second[0] < first[0]
        await rig.close()


async def test_a_reauth_that_keeps_the_role_still_sends_a_snapshot() -> None:
    rig, user = await _rig(), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "manager"))
        await _system(sock)
        sock.feed({"t": "auth", "id": "re", "p": {"access_token": str(user)}})
        assert (await sock.sent.get())["t"] == "auth_ok"
        assert len(_keys(await _system(sock))) == 1
        await rig.close()


async def test_a_failing_flag_read_costs_the_snapshot_never_the_auth() -> None:
    async def broken(user: uuid.UUID, roles: frozenset[str]) -> dict[str, Any] | None:
        raise RuntimeError("store down")

    rig = _Rig(flag_snapshot=broken)
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4(), "manager"))
        assert sock.snap is not None and "feature_flags" not in sock.snap["p"]  # the snap stays
        assert await _system(sock) == []
        await rig.close()


async def test_a_hung_flag_read_is_bounded_and_costs_the_frame_never_the_auth() -> None:
    """C-2.18 (F2): the snapshot await is an `auth` call like the rest, bounded by the gateway;
    `auth_ok`, the `system` snap without flags and the notices still arrive, one log."""

    async def hung(user: uuid.UUID, roles: frozenset[str]) -> dict[str, Any] | None:
        await asyncio.Event().wait()
        return None

    rig = Rig(hangs=True, options={"flag_snapshot": hung, "system_notices": lambda: [NOTICE]})
    sock = Sock()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        with capture_logs() as logs:
            assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
            frames = [await sock.sent.get()]
        assert sock.snap is not None and "feature_flags" not in sock.snap["p"]  # the snap stays
        assert [(f["t"], f["s"], f["p"]["kind"]) for f in frames] == [("d", 2, NOTICE["kind"])]
        assert [e["event"] for e in logs].count("ws flag snapshot failed") == 1
        hang_up(sock)
        await handler


async def test_a_snapshot_with_the_store_unreadable_is_still_sent_fail_closed() -> None:
    """F3: the fail-closed values reveal nothing more than the server enforces, so the frame is
    sent with the role's own key set, as `GET /admin/feature-flags` answers it."""
    store = FakeFlagStore()
    service = FlagService(default_registry(), store, clock=Clock())
    store.down = True
    assert (await service.visible(uuid.uuid4(), frozenset({"manager"}))).resolution is (
        Resolution.FAIL_CLOSED
    )
    rig = _Rig(
        flag_visible=default_registry().visible_to,
        flag_snapshot=lambda user, roles: feature_flags_snapshot(service, user, roles),
    )
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(uuid.uuid4(), "manager"))
        keys = set(_snap_flags(sock))
        assert keys and _OWNER_ONLY not in keys
        registry = default_registry()
        assert keys == {k for k in registry if registry[k].visible_to(frozenset({"manager"}))}
        await rig.close()
