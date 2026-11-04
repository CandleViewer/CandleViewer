"""E24-S03 (#778) serving slice: the eight `deriv` leaves of 22 `Settings` through `/settings`
(`getSettings` / `updateSettings`), on the fakes of `test_user_settings_router.py`. The leaf table
is generated from 22 (#5699), so these pin the route's behaviour on the new group: a patch is
judged whole and refused `422 validation_failed` writing nothing, a change is audited
`settings.change`, the read conforms to 22, a Viewer is refused the write and one user's leaves are
never another's (ruling 6612964585 Q1/Q4)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.api.test_user_settings_router import (
    _MANAGER,
    _OWNER,
    _VIEWER,
    _Env,
    _problem,
    _settings,
)

_EVERY_LEAF: dict[str, Any] = {
    "oi_mode": "delta", "oi_quadrant_colouring": False, "funding_style": "bars",
    "funding_annualised": True, "basis_source": "mark", "liq_mode": "heatmap",
    "liq_min_notional_usd": "250000.50", "zones_enabled": True,
}  # fmt: skip


@pytest.fixture
def env() -> _Env:
    return _Env()


async def test_every_deriv_leaf_is_stored_audited_and_read_back_conforming(env: _Env) -> None:
    body = _settings(env.patch(_MANAGER, {"deriv": _EVERY_LEAF}))
    assert body["deriv"] == _EVERY_LEAF
    assert env.values(_MANAGER) == {f"deriv.{k}": v for k, v in _EVERY_LEAF.items()}
    ((action, record),) = env.audit.records
    assert action == "settings.change" and record["actor_label"] == "user:manager"
    assert record["after_state"] == {f"deriv.{k}": v for k, v in _EVERY_LEAF.items()}
    assert _settings(env.get(_MANAGER)) == body


@pytest.mark.parametrize(
    ("leaf", "value", "rule"),
    [
        ("liq_min_notional_usd", "1000000000.01", "string_pattern_mismatch"),
        ("liq_min_notional_usd", "-1", "string_pattern_mismatch"),
        ("liq_min_notional_usd", 50000, "string_type"),
        ("liq_mode", "dots", "literal_error"),
        ("funding_annualised", "yes", "bool_type"),
        ("liq_zones_enabled", True, "extra_forbidden"),
    ],
)
async def test_a_deriv_leaf_outside_its_table_row_is_422_and_nothing_is_written(
    env: _Env, leaf: str, value: object, rule: str
) -> None:
    await env.seed(_MANAGER, {"deriv.liq_mode": "bars"})
    patch = {"deriv": {leaf: value, "funding_style": "bars"}}
    problem = _problem(env.patch(_MANAGER, patch), 422, "validation_failed")
    assert [(e["field"], e["rule"]) for e in problem["errors"]] == [(f"deriv.{leaf}", rule)]
    assert env.values(_MANAGER) == {"deriv.liq_mode": "bars"}  # the good leaf neither
    assert env.audit.records == []


async def test_a_viewer_is_refused_a_deriv_write(env: _Env) -> None:
    problem = _problem(env.patch(_VIEWER, {"deriv": {"liq_mode": "heatmap"}}), 403, "forbidden")
    assert problem["required_permissions"] == ["settings:write"]
    assert env.values(_VIEWER) == {}


async def test_one_users_deriv_leaves_are_never_anothers(env: _Env) -> None:
    _settings(env.patch(_OWNER, {"deriv": {"zones_enabled": True}}))
    assert "deriv" not in _settings(env.get(_MANAGER))
    assert env.values(_MANAGER) == {}
