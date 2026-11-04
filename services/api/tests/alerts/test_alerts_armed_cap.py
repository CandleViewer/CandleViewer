"""#1864 (E40-T03 follow-up): the per-user armed-alert cap on `/alerts` (24 §19.104).

A create, replace or `{enabled: true}` that would arm a 201st alert is `409 conflict`, rule
`limit_reached`, a message naming the cap and never a count; nothing is written and the refusal
is counted. A disarm, and any write to an alert that is already armed, is never refused. The
in-memory store applies `armed_breach` as the SQL store does; the SQL count and its lock are
pinned in `tests/integration/storage/test_alerts_armed_cap_pg.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest
from _alert_api_env import PRICE_CROSS, USER_A, USER_B, Env

from candleviewer.api.alerts import armed_cap_message, make_alerts_router
from candleviewer.storage.repositories.alerts import (
    MAX_ARMED_ALERTS,
    AlertArmedLimitError,
    armed_breach,
)

CAP = MAX_ARMED_ALERTS


@pytest.fixture
def env() -> Env:
    return Env()


def _seed(env: Env, n: int, *, owner: str = USER_A, enabled: bool = True) -> None:
    """`n` more stored alerts for `owner`, cloned from one created through the route."""
    template = env.repo.rows.get(next(iter(env.repo.rows), ""))
    if template is None:
        template = env.repo.rows[env.create(name="template", enabled=False)["id"]]
    for _ in range(n):
        aid = str(uuid.uuid4())
        env.repo.rows[aid] = replace(
            template, id=aid, name=f"a-{aid}", owner_user_id=owner, enabled=enabled
        )


def _armed(env: Env, owner: str = USER_A) -> int:
    return sum(
        1
        for r in env.repo.rows.values()
        if r.owner_user_id == owner and r.enabled and r.id not in env.repo.deleted
    )


def _assert_cap_problem(body: dict[str, Any]) -> None:
    message = armed_cap_message(CAP)
    assert body == {
        "type": "https://candleviewer.local/errors/conflict",
        "title": "Concurrent modification or state conflict",
        "status": 409,
        "code": "conflict",
        "detail": message,
        "errors": [{"field": "enabled", "rule": "limit_reached", "message": message}],
    }
    assert str(CAP) in message and "armed alerts" in message


# --- the pure check ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("armed", "arming", "refused"),
    [
        (199, True, False),
        (200, True, True),
        (250, True, True),
        (200, False, False),
        (0, True, False),
    ],
)
def test_armed_breach_refuses_only_arming_at_or_past_the_cap(
    armed: int, arming: bool, refused: bool
) -> None:
    got = armed_breach(armed, arming=arming, limit=CAP)
    assert (got is not None) is refused
    if got is not None:
        assert isinstance(got, AlertArmedLimitError) and got.limit == CAP
        assert str(got) == f"armed-alert cap ({CAP}) reached"  # the cap, never the count


def test_the_cap_is_200() -> None:
    assert MAX_ARMED_ALERTS == 200


# --- create ------------------------------------------------------------------------------


def test_create_at_199_armed_is_201_and_arms_the_200th(env: Env) -> None:
    _seed(env, CAP - 1)
    assert _armed(env) == CAP - 1
    r = env.c.post("/alerts", json=PRICE_CROSS)
    assert r.status_code == 201, r.text
    assert _armed(env) == CAP and env.cap_refusals == []


def test_create_at_200_armed_is_409_limit_reached_and_writes_nothing(env: Env) -> None:
    _seed(env, CAP)
    before = dict(env.repo.rows)
    r = env.c.post("/alerts", json=PRICE_CROSS)
    assert r.status_code == 409 and r.headers["content-type"] == "application/problem+json"
    _assert_cap_problem(r.json())
    assert env.repo.rows == before and env.cap_refusals == [1]
    # Ruling of record on #1864: the write-ahead record of the attempt stays as it is.
    assert env.audit.actions()[-1] == "alert.created"


def test_create_disabled_at_the_cap_is_201(env: Env) -> None:
    _seed(env, CAP)
    r = env.c.post("/alerts", json=PRICE_CROSS | {"enabled": False})
    assert r.status_code == 201 and r.json()["enabled"] is False
    assert _armed(env) == CAP and env.cap_refusals == []


def test_another_users_armed_alerts_never_count(env: Env) -> None:
    _seed(env, CAP, owner=USER_B)
    assert env.c.post("/alerts", json=PRICE_CROSS).status_code == 201


# --- disarm / re-arm ---------------------------------------------------------------------


def test_disabling_at_the_cap_is_always_200(env: Env) -> None:
    _seed(env, CAP)
    aid = next(r.id for r in env.repo.rows.values() if r.enabled)
    r = env.c.put(f"/alerts/{aid}/enabled", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert _armed(env) == CAP - 1 and env.cap_refusals == []


def test_disabling_over_a_lowered_cap_is_200(env: Env) -> None:
    _seed(env, 5)
    env.repo.max_armed = 2  # the owner holds more than the cap now allows
    aid = next(r.id for r in env.repo.rows.values() if r.enabled)
    assert env.c.put(f"/alerts/{aid}/enabled", json={"enabled": False}).status_code == 200
    assert env.cap_refusals == []


def test_re_enabling_at_the_cap_is_409_and_the_alert_stays_disarmed(env: Env) -> None:
    _seed(env, CAP)
    off = env.create(name="parked", enabled=False)
    r = env.c.put(f"/alerts/{off['id']}/enabled", json={"enabled": True})
    assert r.status_code == 409
    _assert_cap_problem(r.json())
    assert env.repo.rows[off["id"]].enabled is False and env.cap_refusals == [1]


def test_enabling_an_alert_already_armed_at_the_cap_is_200(env: Env) -> None:
    _seed(env, CAP)
    aid = next(r.id for r in env.repo.rows.values() if r.enabled)
    assert env.c.put(f"/alerts/{aid}/enabled", json={"enabled": True}).status_code == 200
    assert env.cap_refusals == []


def test_replace_turning_enabled_on_at_the_cap_is_409_and_keeps_the_row(env: Env) -> None:
    _seed(env, CAP)
    off = env.create(name="parked", enabled=False)
    stored = env.repo.rows[off["id"]]
    r = env.c.put(f"/alerts/{off['id']}", json=PRICE_CROSS | {"name": "parked", "enabled": True})
    assert r.status_code == 409
    _assert_cap_problem(r.json())
    assert env.repo.rows[off["id"]] == stored and env.cap_refusals == [1]


def test_replace_of_an_armed_alert_at_the_cap_is_200(env: Env) -> None:
    _seed(env, CAP - 1)
    on = env.create(name="mine")
    assert _armed(env) == CAP
    r = env.c.put(f"/alerts/{on['id']}", json=PRICE_CROSS | {"name": "renamed"})
    assert r.status_code == 200 and r.json()["name"] == "renamed"
    assert env.cap_refusals == []


def test_snooze_at_the_cap_is_200(env: Env) -> None:
    _seed(env, CAP)
    aid = next(r.id for r in env.repo.rows.values() if r.enabled)
    until = "2026-11-01T12:00:00Z"
    assert env.c.put(f"/alerts/{aid}/snooze", json={"until": until}).status_code == 200


# --- RBAC (C-12.4) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/alerts", PRICE_CROSS),
        ("PUT", "/alerts/{id}", PRICE_CROSS | {"name": "parked", "enabled": True}),
        ("PUT", "/alerts/{id}/enabled", {"enabled": True}),
    ],
)
def test_a_caller_without_alerts_write_is_403_before_the_cap(
    env: Env, method: str, path: str, body: Any
) -> None:
    _seed(env, CAP)
    off = env.create(name="parked", enabled=False)
    env.perms = frozenset({"alerts:read"})
    r = env.c.request(method, path.format(id=off["id"]), json=body)
    assert r.status_code == 403 and r.json()["required_permissions"] == ["alerts:write"]
    assert env.cap_refusals == [] and env.repo.rows[off["id"]].enabled is False


def test_another_users_alert_is_404_and_never_armed(env: Env) -> None:
    """`scope: self` (IDOR): B cannot arm A's alert, whatever either user's count."""
    off = env.create(name="parked", enabled=False)
    env.user = USER_B
    r = env.c.put(f"/alerts/{off['id']}/enabled", json={"enabled": True})
    assert r.status_code == 404 and env.cap_refusals == []
    assert env.repo.rows[off["id"]].enabled is False
    assert env.audit.actions()[-1] == "alert.denied"


# --- wiring: `create_app()` counts a refusal on `cv_alert_armed_cap_refused_total` -----------


def test_create_app_wires_the_refusal_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    from candleviewer import app as app_module
    from candleviewer.settings import Settings

    seen: dict[str, Any] = {}
    real = make_alerts_router

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr("candleviewer.app.make_alerts_router", spy)
    app = app_module.create_app(Settings(alerts_evaluator_enabled=False))
    registry = app.state.metrics_facade.registry
    labels = {"env": app.state.metrics_facade.env}
    name = "cv_alert_armed_cap_refused_total"
    before = registry.get_sample_value(name, labels) or 0.0
    seen["on_cap_refused"]()
    assert registry.get_sample_value(name, labels) == before + 1
