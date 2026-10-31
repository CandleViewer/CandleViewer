"""E40-S01 (E40-D02 CC-3/4/5/10): read-model fields, snooze route, cooldown bounds, past expiry."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from _alert_api_env import NOW, PRICE_CROSS, USER_B, Env

FUTURE = (NOW + timedelta(hours=1)).isoformat()


@pytest.fixture
def env() -> Env:
    return Env()


def test_read_model_exposes_defaults_on_create_list_and_get(env: Env) -> None:
    created = env.create()
    for body in (
        created,
        env.c.get(f"/alerts/{created['id']}").json(),
        env.c.get("/alerts").json()["items"][0],
    ):
        assert body["cooldown_seconds"] == 60
        assert body["snoozed_until"] is None
        assert body["disarm_reason"] is None


def test_read_model_exposes_stored_snooze_and_disarm_reason(env: Env) -> None:
    aid = env.create()["id"]
    until = NOW + timedelta(hours=2)
    env.repo.rows[aid] = replace(
        env.repo.rows[aid], snoozed_until=until, enabled=False, disarm_reason="source_unavailable"
    )
    got = env.c.get(f"/alerts/{aid}").json()
    assert got["snoozed_until"] == until.isoformat()
    assert got["disarm_reason"] == "source_unavailable" and got["enabled"] is False


def test_snooze_set_then_clear_is_audited(env: Env) -> None:
    aid = env.create()["id"]
    r = env.c.put(f"/alerts/{aid}/snooze", json={"until": FUTURE})
    assert r.status_code == 200 and r.json()["snoozed_until"] == FUTURE
    assert env.repo.rows[aid].snoozed_until is not None
    r = env.c.put(f"/alerts/{aid}/snooze", json={"until": None})
    assert r.status_code == 200 and r.json()["snoozed_until"] is None
    assert env.audit.actions()[-2:] == ["alert.snoozed", "alert.unsnoozed"]
    snoozed = env.audit.calls[-2][1]
    assert snoozed["after_state"] == {"snoozed_until": FUTURE}
    assert snoozed["before_state"] == {"snoozed_until": None}


@pytest.mark.parametrize(
    "body",
    [
        {"until": (NOW - timedelta(seconds=1)).isoformat()},
        {"until": NOW.isoformat()},
        {"until": "2099-01-01T00:00:00"},  # no offset
        {},
        {"until": FUTURE, "extra": 1},
        {"until": "tomorrow"},
    ],
)
def test_snooze_invalid_body_is_422_and_changes_nothing(env: Env, body: dict[str, object]) -> None:
    aid = env.create()["id"]
    before = env.repo.rows[aid]
    n = len(env.audit.calls)
    r = env.c.put(f"/alerts/{aid}/snooze", json=body)
    assert r.status_code == 422
    assert env.repo.rows[aid] == before and len(env.audit.calls) == n


def test_snooze_other_users_alert_is_404_and_denial_audited(env: Env) -> None:
    aid = env.create()["id"]
    env.user = USER_B
    r = env.c.put(f"/alerts/{aid}/snooze", json={"until": FUTURE})
    assert r.status_code == 404
    assert env.repo.rows[aid].snoozed_until is None
    assert env.audit.actions()[-1] == "alert.denied"


def test_snooze_unknown_alert_404(env: Env) -> None:
    r = env.c.put("/alerts/00000000-0000-4000-8000-0000000000ff/snooze", json={"until": None})
    assert r.status_code == 404


@pytest.mark.parametrize("value", [0, 1, 300, 86400])
def test_cooldown_accepted_on_create_and_replace(env: Env, value: int) -> None:
    created = env.create(cooldown_seconds=value)
    assert created["cooldown_seconds"] == value
    other = (value + 7) % 86401
    r = env.c.put(f"/alerts/{created['id']}", json=PRICE_CROSS | {"cooldown_seconds": other})
    assert r.status_code == 200 and r.json()["cooldown_seconds"] == other


@pytest.mark.parametrize("value", [-1, 86401, 1.5, "soon"])
def test_cooldown_out_of_bounds_is_422(env: Env, value: object) -> None:
    r = env.c.post("/alerts", json=PRICE_CROSS | {"cooldown_seconds": value})
    assert r.status_code == 422 and not env.repo.rows
    assert r.json()["errors"][0]["field"] == "cooldown_seconds"


def test_replace_without_cooldown_keeps_the_stored_value(env: Env) -> None:
    aid = env.create(cooldown_seconds=900)["id"]
    r = env.c.put(f"/alerts/{aid}", json=PRICE_CROSS)
    assert r.status_code == 200 and r.json()["cooldown_seconds"] == 900


@pytest.mark.parametrize(
    "when", ["2026-10-31T11:59:59Z", "2026-10-31T12:00:00Z", "2020-01-01T00:00:00+00:00"]
)
def test_past_expiry_is_422_on_create_and_replace(env: Env, when: str) -> None:
    r = env.c.post("/alerts", json=PRICE_CROSS | {"expires_at": when})
    assert r.status_code == 422 and not env.repo.rows
    assert r.json()["errors"][0] == {
        "field": "expires_at",
        "rule": "expires_in_past",
        "message": "expires_at must be in the future",
    }
    aid = env.create()["id"]
    r = env.c.put(f"/alerts/{aid}", json=PRICE_CROSS | {"expires_at": when})
    assert r.status_code == 422 and env.repo.rows[aid].expires_at is not None
    kept = env.repo.rows[aid].expires_at
    assert kept is not None and kept.year == 2099


def test_naive_expiry_is_422_and_null_or_future_expiry_is_accepted(env: Env) -> None:
    assert (
        env.c.post("/alerts", json=PRICE_CROSS | {"expires_at": "2099-01-01T00:00:00"}).status_code
        == 422
    )
    assert env.c.post("/alerts", json=PRICE_CROSS | {"expires_at": None}).status_code == 201


def test_replace_echoing_a_stored_past_expiry_is_accepted(env: Env) -> None:
    aid = env.create()["id"]
    past = datetime(2026, 10, 1, tzinfo=UTC)
    env.repo.rows[aid] = replace(env.repo.rows[aid], expires_at=past)
    r = env.c.put(f"/alerts/{aid}", json=PRICE_CROSS | {"expires_at": "2026-10-01T00:00:00Z"})
    assert r.status_code == 200 and env.repo.rows[aid].expires_at == past


def test_replace_changing_to_another_past_expiry_is_422(env: Env) -> None:
    aid = env.create()["id"]
    past = datetime(2026, 10, 1, tzinfo=UTC)
    env.repo.rows[aid] = replace(env.repo.rows[aid], expires_at=past)
    r = env.c.put(f"/alerts/{aid}", json=PRICE_CROSS | {"expires_at": "2026-10-02T00:00:00Z"})
    assert r.status_code == 422 and env.repo.rows[aid].expires_at == past
    assert r.json()["errors"][0]["rule"] == "expires_in_past"


def test_snooze_of_an_alert_deleted_after_the_read_is_404_with_no_success_audit(
    env: Env,
) -> None:
    aid = env.create()["id"]
    real_get, calls = env.repo.get, []

    async def get(alert_id: str) -> object:
        calls.append(alert_id)
        return await real_get(alert_id) if len(calls) == 1 else None  # gone before the audit

    env.repo.get = get  # type: ignore[method-assign]
    n = len(env.audit.calls)
    r = env.c.put(f"/alerts/{aid}/snooze", json={"until": FUTURE})
    assert r.status_code == 404
    assert env.repo.rows[aid].snoozed_until is None
    assert not {"alert.snoozed", "alert.unsnoozed"} & set(env.audit.actions()[n:])


def test_snooze_numeric_epoch_is_422_and_changes_nothing(env: Env) -> None:
    aid = env.create()["id"]
    n = len(env.audit.calls)
    for bad in (4102444800, 4102444800.5, True):
        r = env.c.put(f"/alerts/{aid}/snooze", json={"until": bad})
        assert r.status_code == 422
    assert env.repo.rows[aid].snoozed_until is None and len(env.audit.calls) == n


def test_snooze_beyond_30_days_is_422_until_too_far_and_30_days_is_accepted(env: Env) -> None:
    aid = env.create()["id"]
    n = len(env.audit.calls)
    r = env.c.put(f"/alerts/{aid}/snooze", json={"until": "2026-12-01T12:00:01Z"})
    assert r.status_code == 422 and r.json()["errors"][0]["rule"] == "until_too_far"
    assert env.repo.rows[aid].snoozed_until is None and len(env.audit.calls) == n
    ok = env.c.put(f"/alerts/{aid}/snooze", json={"until": "2026-11-30T12:00:00Z"})
    assert ok.status_code == 200
