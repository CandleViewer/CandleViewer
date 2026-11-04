"""The preferences slice's `/settings` rules (#1130 slice 3, 24 §19.106 CC-8): the
`notifications.risk_channel_muted` record of a locked cell turned off, the `sound_only_channel`
refusal (D-29), the duplicate-mute refusal and the quiet-hours zone check. Fakes only: no
database, no network (C-13.5). Gherkin: "Muting a risk channel is refused and audited" and "Sound
cannot become the only channel"."""

from __future__ import annotations

import json
from typing import Any

import pytest

from candleviewer.alerts._generated.notification_overrides import CATEGORIES, LOCKED_CELLS
from candleviewer.api import user_settings_models as m
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable
from tests.unit.api.test_user_settings_router import _MANAGER, _OWNER, _Env, _problem

_QH = {"enabled": True, "start": "22:00", "end": "07:00", "tz": "Europe/Berlin"}
_MUTE = {"symbol": "ETHUSDT", "muted_at": "2026-11-03T14:02:00Z"}


@pytest.fixture
def env() -> _Env:
    return _Env()


def _rules(doc: object) -> list[tuple[str, str]]:
    with pytest.raises(m.PatchRefused) as refused:
        m.judge_patch(json.dumps(doc).encode())
    return [(e["field"], e["rule"]) for e in refused.value.errors]


def _ok(doc: object) -> dict[str, object]:
    return m.judge_patch(json.dumps(doc).encode())


@pytest.mark.parametrize(
    ("category", "row"),
    [
        ("alerts", {"toast": False}),  # its sound is on by default
        ("alerts", {"toast": False, "sound": True}),
        ("rule_actions", {"toast": False, "sound": True}),
        ("system_health", {"toast": False, "desktop": False, "sound": True}),
        ("recorder", {"toast": False, "sound": True}),
    ],
)  # fmt: skip
def test_judge_patch_refuses_sound_as_a_rows_only_channel(
    category: str, row: dict[str, bool]
) -> None:
    assert _rules({"notifications": {"matrix": {category: row}}}) == [
        (f"notifications.matrix.{category}.sound", "sound_only_channel")
    ]


@pytest.mark.parametrize(
    "matrix",
    [
        {"alerts": {"toast": False, "sound": False}},
        {"rule_actions": {"toast": False}},  # its sound is off by default
        {"system_health": {"toast": False, "desktop": True, "sound": True}},
        {"order_rejects": {"sound": True}},  # its toast is locked on
        {"risk_events": {"desktop": False, "sound": True}},
    ],
)
def test_judge_patch_takes_sound_beside_a_visual_channel(matrix: dict[str, Any]) -> None:
    assert _ok({"notifications": {"matrix": matrix}}) == {"notifications.matrix": matrix}


def test_matrix_defaults_cover_every_category_and_no_locked_row_is_sound_only() -> None:
    assert set(m.MATRIX_DEFAULTS) == set(CATEGORIES)
    for category in CATEGORIES:
        assert _ok({"notifications": {"matrix": {category: {}}}})  # the defaults stand alone
    for category, _channel in LOCKED_CELLS:
        quiet = {"toast": True, "desktop": False, "sound": True}
        assert _ok({"notifications": {"matrix": {category: quiet}}})


def test_judge_patch_refuses_a_symbol_muted_twice() -> None:
    later = {**_MUTE, "muted_at": "2026-11-03T15:00:00Z"}
    assert _rules({"notifications": {"muted_symbols": [_MUTE, later]}}) == [
        ("notifications.muted_symbols.1.symbol", "duplicate_symbol")
    ]
    two = [_MUTE, {**_MUTE, "symbol": "BTCUSDT"}]
    assert _ok({"notifications": {"muted_symbols": two}}) == {"notifications.muted_symbols": two}


@pytest.mark.parametrize("tz", ["Mars/Olympus", "Europe/Nowhere", "../etc", "UTC+1"])
def test_judge_patch_refuses_a_zone_the_tz_database_lacks(tz: str) -> None:
    assert _rules({"notifications": {"quiet_hours": {**_QH, "tz": tz}}}) == [
        ("notifications.quiet_hours.tz", "unknown_timezone")
    ]


def test_judge_patch_takes_a_known_zone() -> None:
    assert _ok({"notifications": {"quiet_hours": _QH}}) == {"notifications.quiet_hours": _QH}


def test_patch_refused_keeps_every_locked_cell_past_the_error_bound() -> None:
    noise = {f"x{i}": 1 for i in range(30)}
    matrix = {c: {ch: False} for c, ch in LOCKED_CELLS}
    with pytest.raises(m.PatchRefused) as refused:
        m.judge_patch(
            json.dumps({"appearance": noise, "notifications": {"matrix": matrix}}).encode()
        )
    assert len(refused.value.errors) == 20
    assert refused.value.locked == sorted(
        f"notifications.matrix.{c}.{ch}" for c, ch in LOCKED_CELLS
    )


def test_risk_channel_muted_is_a_registered_action() -> None:
    assert "notifications.risk_channel_muted" in AUDIT_ACTIONS


async def test_patch_settings_a_locked_cell_off_is_audited_and_refused(env: _Env) -> None:
    """Muting a risk channel is refused and audited (the API-level attempt)."""
    await env.seed(_MANAGER, {"appearance.density": "compact"})
    body = {"notifications": {"matrix": {"risk_events": {"toast": False}}},
            "appearance": {"density": "spacious"}}  # fmt: skip
    problem = _problem(env.patch(_MANAGER, body), 422, "validation_failed")
    assert [e["rule"] for e in problem["errors"]] == ["risk_channel_locked"]
    assert env.values(_MANAGER) == {"appearance.density": "compact"}  # nothing stored
    [(action, rec)] = env.audit.records
    assert action == "notifications.risk_channel_muted"
    assert (rec["outcome"], rec["severity"]) == (AuditOutcome.DENIED, Severity.ERROR)
    assert rec["object_id"] == str(_MANAGER) and rec["actor_label"] == "user:manager"
    assert rec["after_state"] == {"cells": ["notifications.matrix.risk_events.toast"],
                                  "rule": "risk_channel_locked"}  # fmt: skip


async def test_patch_settings_other_refusals_write_no_risk_record(env: _Env) -> None:
    body = {"notifications": {"matrix": {"alerts": {"toast": False}}}}
    _problem(env.patch(_OWNER, body), 422, "validation_failed")
    assert env.audit.records == []


async def test_patch_settings_an_unwritten_risk_record_is_503_and_stores_nothing(
    env: _Env,
) -> None:
    env.audit.fail = AuditUnavailable("down")
    body = {"notifications": {"matrix": {"order_rejects": {"toast": False}}}}
    _problem(env.patch(_OWNER, body), 503, "audit_unavailable")
    assert env.values(_OWNER) == {}
