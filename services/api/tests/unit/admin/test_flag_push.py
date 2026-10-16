"""E42-T03: flag changes reach every session as role-filtered `system` frames carrying only the
changed key, resolved per user from the committed row; maintenance toggles add a notice."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import jsonschema
import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import (
    MAINTENANCE_MODE,
    FlagService,
    FlagValue,
    FlagWriter,
    StoredFlag,
    default_registry,
)
from candleviewer.admin.flags.metrics import flag_push_latency_seconds
from candleviewer.admin.flags.push import FlagPush, Session
from candleviewer.audit.access import AuditPrincipal
from tests.unit.admin.flag_fakes import T0, Clock, FakeAudit, FakeFlagStore, FakeStepUp, FakeUsers

_OWNER = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")
_MANAGER = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002")
_VIEWER = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0003")
_WS = Path(__file__).resolve().parents[5] / "packages/protocol/ws-schemas.json"
_SYSTEM = json.loads(_WS.read_text(encoding="utf-8"))["schemas"]["cv://ws/v1/system.schema.json"]
_ROLES = {_OWNER: "owner", _MANAGER: "manager", _VIEWER: "viewer"}


class _Sessions:
    def __init__(self) -> None:
        self.frames: dict[UUID, list[dict[str, Any]]] = {u: [] for u in _ROLES}
        self.sessions = [
            Session(u, frozenset({r}), self.frames[u].append) for u, r in _ROLES.items()
        ]

    def authenticated(self) -> list[Session]:
        return self.sessions


def _push_count() -> float:
    samples = [s for m in flag_push_latency_seconds.collect() for s in m.samples]
    return next(s.value for s in samples if s.name == "cv_flag_push_latency_seconds_count")


async def _rig() -> tuple[FlagService, FlagPush, FakeFlagStore, _Sessions]:
    store, sessions = FakeFlagStore(), _Sessions()
    service = FlagService(default_registry(), store, clock=Clock())
    await store.ensure(service.registry.values())
    return service, FlagPush(service, sessions), store, sessions


def _owner() -> AuditPrincipal:
    return AuditPrincipal(user_id=_OWNER, username="owner", permissions=frozenset({"*"}))


async def test_each_session_gets_the_committed_value_resolved_for_its_user() -> None:
    _, push, store, sessions = await _rig()
    before = store.rows["rules.graph_editor"]
    after = replace(before, value=False, user_overrides={_OWNER: True})
    await push.flag_changed("rules.graph_editor", before, after)  # the cache still says True
    assert sessions.frames[_OWNER] == [
        {"kind": "feature_flags", "feature_flags": {"rules.graph_editor": True}}
    ]
    for user in (_MANAGER, _VIEWER):
        assert sessions.frames[user] == [
            {"kind": "feature_flags", "feature_flags": {"rules.graph_editor": False}}
        ]


async def test_every_frame_validates_against_the_system_schema() -> None:
    _, push, store, sessions = await _rig()
    before = store.rows[MAINTENANCE_MODE]
    await push.flag_changed(MAINTENANCE_MODE, before, replace(before, value=True))
    for frames in sessions.frames.values():
        for frame in frames:
            jsonschema.Draft202012Validator(_SYSTEM).validate(frame)


@pytest.mark.parametrize("key", ["maintenance.keep_recorder", "killswitch.ingestion"])
async def test_a_manager_and_a_viewer_never_learn_an_owner_only_key(key: str) -> None:
    _, push, store, sessions = await _rig()
    before = store.rows[key]
    await push.flag_changed(key, before, replace(before, value=not before.value))
    assert len(sessions.frames[_OWNER]) == 1
    assert sessions.frames[_MANAGER] == sessions.frames[_VIEWER] == []


@pytest.mark.parametrize(
    ("was", "now", "notices"),
    [
        (False, True, [("maintenance.enabled", "warning")]),
        (True, False, [("maintenance.disabled", "info")]),
        (1, True, [("maintenance.enabled", "warning")]),  # unreadable (1 == True): unknown to true
        ("on", False, []),  # unknown to false is no transition (D1c)
        (True, True, []),
    ],
)
async def test_only_a_real_stored_maintenance_transition_notifies_every_session(
    was: FlagValue, now: bool, notices: list[tuple[str, str]]
) -> None:
    _, push, store, sessions = await _rig()
    before = replace(store.rows[MAINTENANCE_MODE], value=was)
    await push.flag_changed(MAINTENANCE_MODE, before, replace(before, value=now))
    for frames in sessions.frames.values():
        assert [(f["reason"], f["severity"]) for f in frames if f["kind"] == "notice"] == notices


async def test_one_broken_session_never_stops_the_fan_out() -> None:
    _, push, store, sessions = await _rig()

    def broken(frame: dict[str, Any]) -> None:
        raise RuntimeError("socket gone")

    sessions.sessions.insert(0, Session(_VIEWER, frozenset({"viewer"}), broken))
    row = store.rows["rules.form_editor"]
    with capture_logs() as logs:
        await push.flag_changed("rules.form_editor", row, replace(row, value=False))
    assert [len(f) for f in sessions.frames.values()] == [1, 1, 1]
    assert "feature_flag_push_session_failed" in [e["event"] for e in logs]


async def test_sessions_are_snapshot_before_the_fan_out() -> None:
    _, push, store, sessions = await _rig()
    late: list[dict[str, Any]] = []

    def joins_late(frame: dict[str, Any]) -> None:
        sessions.sessions.append(Session(_VIEWER, frozenset({"viewer"}), late.append))

    sessions.sessions.insert(0, Session(_MANAGER, frozenset({"manager"}), joins_late))
    row = store.rows["rules.form_editor"]
    await push.flag_changed("rules.form_editor", row, replace(row, value=False))
    assert late == []


async def test_the_push_is_timed() -> None:
    _, push, store, _ = await _rig()
    count = _push_count()
    row = store.rows["rules.form_editor"]
    await push.flag_changed("rules.form_editor", row, row)
    assert _push_count() == count + 1


@pytest.mark.perf
async def test_a_write_reaches_all_three_sessions_within_2_s() -> None:
    service, push, store, sessions = await _rig()
    writer = FlagWriter(
        service, FakeAudit(), FakeStepUp(), FakeUsers(), on_change=push.flag_changed
    )
    start = time.monotonic()
    await writer.set(
        "rules.graph_editor",
        _owner(),
        value=False,
        reason="perf",
        expected_updated_at=T0,
    )
    assert time.monotonic() - start < 2.0
    assert all(len(frames) == 1 for frames in sessions.frames.values())
    assert isinstance(store.rows["rules.graph_editor"], StoredFlag)
