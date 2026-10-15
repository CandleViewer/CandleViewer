"""E42-T03: flag changes reach every session as role-filtered `system` frames carrying only the
changed key, resolved per user; maintenance toggles add a notice to every session."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import jsonschema

from candleviewer.admin.flags import (
    LIVE_ENABLED,
    MAINTENANCE_MODE,
    FlagService,
    FlagWriter,
    default_registry,
)
from candleviewer.admin.flags.metrics import flag_push_latency_seconds
from candleviewer.admin.flags.push import FlagPush, Session
from tests.unit.admin.flag_fakes import Clock, FakeAudit, FakeFlagStore

_OWNER = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")
_MANAGER = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002")
_VIEWER = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0003")
_WS = Path(__file__).resolve().parents[5] / "packages/protocol/ws-schemas.json"
_SYSTEM = json.loads(_WS.read_text(encoding="utf-8"))["schemas"]["cv://ws/v1/system.schema.json"]


class _Sessions:
    def __init__(self) -> None:
        self.frames: dict[UUID, list[dict[str, Any]]] = {_OWNER: [], _MANAGER: [], _VIEWER: []}
        roles = {_OWNER: "owner", _MANAGER: "manager", _VIEWER: "viewer"}
        self.sessions = [Session(u, frozenset({roles[u]}), self.frames[u].append) for u in roles]

    def authenticated(self) -> Iterable[Session]:
        return self.sessions


def _push_count() -> float:
    samples = [s for m in flag_push_latency_seconds.collect() for s in m.samples]
    return next(s.value for s in samples if s.name == "cv_flag_push_latency_seconds_count")


async def _rig() -> tuple[FlagService, FlagWriter, FakeFlagStore, _Sessions]:
    store, sessions = FakeFlagStore(), _Sessions()
    service = FlagService(default_registry(), store, clock=Clock())
    await store.ensure(service.registry.values())
    push = FlagPush(service, sessions)
    return service, FlagWriter(service, FakeAudit(), on_change=push.flag_changed), store, sessions


async def _write(writer: FlagWriter, key: str, value: object, store: FakeFlagStore) -> None:
    await writer.set(
        key,
        actor_id=_OWNER,
        actor_label="owner",
        value=value,
        reason="test",
        expected_updated_at=store.rows[key].updated_at,
        evidence_url="https://example.invalid/pt" if key == LIVE_ENABLED else None,
    )


async def test_a_flag_change_reaches_all_three_sessions_resolved_per_user() -> None:
    service, writer, store, sessions = await _rig()
    store.rows["rules.graph_editor"] = replace(
        store.rows["rules.graph_editor"], user_overrides={_OWNER: True}
    )
    count = _push_count()
    start = time.monotonic()
    await _write(writer, "rules.graph_editor", False, store)
    assert time.monotonic() - start < 2.0
    assert _push_count() == count + 1
    for user, frames in sessions.frames.items():
        roles = next(s.roles for s in sessions.sessions if s.user_id == user)
        expected = await service.value("rules.graph_editor", user_id=user, roles=roles)
        assert frames == [
            {"kind": "feature_flags", "feature_flags": {"rules.graph_editor": expected}}
        ]
        jsonschema.Draft202012Validator(_SYSTEM).validate(frames[0])
    assert sessions.frames[_OWNER][0]["feature_flags"]["rules.graph_editor"] is True
    assert sessions.frames[_MANAGER][0]["feature_flags"]["rules.graph_editor"] is False


async def test_a_manager_and_a_viewer_never_learn_an_owner_only_key() -> None:
    _, writer, store, sessions = await _rig()
    await _write(writer, "maintenance.keep_recorder", False, store)
    assert sessions.frames[_OWNER] == [
        {"kind": "feature_flags", "feature_flags": {"maintenance.keep_recorder": False}}
    ]
    assert sessions.frames[_MANAGER] == sessions.frames[_VIEWER] == []


async def test_maintenance_on_and_off_sends_every_session_a_notice() -> None:
    _, writer, store, sessions = await _rig()
    await _write(writer, MAINTENANCE_MODE, True, store)
    await _write(writer, MAINTENANCE_MODE, False, store)
    for frames in sessions.frames.values():
        notices = [(f["reason"], f["severity"]) for f in frames if f["kind"] == "notice"]
        assert notices == [("maintenance.enabled", "warning"), ("maintenance.disabled", "info")]
        values = [
            f["feature_flags"][MAINTENANCE_MODE] for f in frames if f["kind"] == "feature_flags"
        ]
        assert values == [True, False]
        for frame in frames:
            jsonschema.Draft202012Validator(_SYSTEM).validate(frame)


async def test_audience_decides_how_many_sessions_get_a_frame() -> None:
    service, _, _, sessions = await _rig()
    push = FlagPush(service, sessions)
    await push.flag_changed("storage.cold_tier")
    await push.flag_changed("rules.form_editor")
    counts = {u: len(f) for u, f in sessions.frames.items()}
    assert counts == {_OWNER: 2, _MANAGER: 1, _VIEWER: 1}
