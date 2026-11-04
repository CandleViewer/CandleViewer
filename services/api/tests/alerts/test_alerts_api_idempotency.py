"""#1851 `createAlert` dedupes by `Idempotency-Key` (convention C4, 22-api-openapi.yaml).

The same caller, key and request replay the stored `201` with `Idempotency-Replayed: true`:
one alert, one `alert.created` record. The key with another body is
`409 idempotency_key_reuse`; another caller's key is its own; an entry lives 24 h. The lookup
runs after authentication and the permission check, and only a `2xx` is stored, so a refusal
(403 for an ungranted account, 422) is evaluated afresh. Without a key nothing changes: a
second create of the same name is the duplicate-name `409 conflict`.
"""

from __future__ import annotations

from typing import Any

from _alert_api_env import PRICE_CROSS, USER_B, Env

from candleviewer.api.idempotency import IDEMPOTENCY_TTL_S, IdempotencyCache

IDEM = "8f9c2b8e-3d1a-4c55-9a77-1f2e3d4c5b6a"
ACCT = "00000000-0000-4000-8000-0000000000aa"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def _env() -> tuple[Env, IdempotencyCache, Clock]:
    clock = Clock()
    cache = IdempotencyCache(clock=clock)
    return Env(idempotency=cache), cache, clock


def _post(env: Env, body: dict[str, Any], key: str | None = IDEM) -> Any:
    headers = {} if key is None else {"Idempotency-Key": key}
    return env.c.post("/alerts", json=body, headers=headers)


def _created(env: Env) -> int:
    return env.audit.actions().count("alert.created")


def test_create_alert_same_key_and_body_replays_the_stored_201() -> None:
    env, _, _ = _env()
    first = _post(env, PRICE_CROSS)
    again = _post(env, PRICE_CROSS)
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json()
    assert again.headers["Idempotency-Replayed"] == "true"
    assert "Idempotency-Replayed" not in first.headers
    assert again.headers["ETag"] == first.headers["ETag"]
    assert len(env.repo.rows) == 1
    assert _created(env) == 1  # no second write-ahead record
    assert env.compiles == [None]  # the replay never re-compiles


def test_create_alert_same_key_other_body_is_idempotency_key_reuse() -> None:
    env, _, _ = _env()
    assert _post(env, PRICE_CROSS).status_code == 201
    r = _post(env, PRICE_CROSS | {"name": "another"})
    assert r.status_code == 409
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["code"] == "idempotency_key_reuse"
    assert r.json()["type"] == "https://candleviewer.local/errors/idempotency_key_reuse"
    assert len(env.repo.rows) == 1 and _created(env) == 1


def test_create_alert_same_key_other_actor_is_independent() -> None:
    env, _, _ = _env()
    mine = _post(env, PRICE_CROSS)
    env.user = USER_B
    theirs = _post(env, PRICE_CROSS)
    assert mine.status_code == theirs.status_code == 201
    assert "Idempotency-Replayed" not in theirs.headers
    assert theirs.json()["owner_user_id"] == USER_B != mine.json()["owner_user_id"]
    assert len(env.repo.rows) == 2 and _created(env) == 2


def test_create_alert_key_after_24h_is_a_first_submission() -> None:
    env, _, clock = _env()
    assert _post(env, PRICE_CROSS).status_code == 201
    clock.now += IDEMPOTENCY_TTL_S - 1
    assert _post(env, PRICE_CROSS).headers["Idempotency-Replayed"] == "true"
    clock.now += 1
    r = _post(env, PRICE_CROSS)  # expired: runs again and meets its own name
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"
    assert len(env.repo.rows) == 1


def test_create_alert_without_key_keeps_the_duplicate_name_conflict() -> None:
    env, cache, _ = _env()
    assert _post(env, PRICE_CROSS, key=None).status_code == 201
    r = _post(env, PRICE_CROSS, key=None)
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"
    assert len(cache) == 0 and len(env.repo.rows) == 1


def test_create_alert_malformed_key_is_422_and_changes_nothing() -> None:
    env, cache, _ = _env()
    r = _post(env, PRICE_CROSS, key="not-a-uuid")
    assert r.status_code == 422
    assert r.json()["code"] == "validation_failed"
    assert r.json()["errors"] == [{"field": "Idempotency-Key", "rule": "uuid_parsing",
                                   "message": "Idempotency-Key must be a UUID."}]  # fmt: skip
    assert env.repo.rows == {} and env.audit.calls == [] and len(cache) == 0


def test_create_alert_key_lookup_runs_after_authentication() -> None:
    env, _, _ = _env()
    assert _post(env, PRICE_CROSS).status_code == 201
    env.user = None
    r = _post(env, PRICE_CROSS)
    assert r.status_code == 401
    assert "Idempotency-Replayed" not in r.headers


def test_create_alert_forbidden_role_is_refused_before_the_replay() -> None:
    env, cache, _ = _env()
    assert _post(env, PRICE_CROSS).status_code == 201
    env.perms = frozenset({"alerts:read"})  # write revoked since the first send
    r = _post(env, PRICE_CROSS)
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
    assert "Idempotency-Replayed" not in r.headers
    assert len(cache) == 1 and _created(env) == 1


def test_create_alert_forbidden_role_stores_nothing_under_the_key() -> None:
    env, cache, _ = _env()
    env.perms = frozenset({"alerts:read"})
    assert _post(env, PRICE_CROSS).status_code == 403
    assert len(cache) == 0 and env.repo.rows == {}


def test_create_alert_ungranted_account_refusal_is_not_stored() -> None:
    env, cache, _ = _env()
    body = PRICE_CROSS | {"exchange_account_id": ACCT}
    for _ in range(2):  # a refusal is never replayed: each send is checked and audited again
        r = _post(env, body)
        assert r.status_code == 403
        assert r.json()["detail"] == "no grant on that account"
    assert env.audit.actions() == ["alert.scope_refused", "alert.scope_refused"]
    assert len(cache) == 0 and env.repo.rows == {}
    env.granted = frozenset({ACCT})
    ok = _post(env, body)
    assert ok.status_code == 201
    assert ok.json()["exchange_account_id"] == ACCT


def test_create_alert_validation_refusal_is_not_stored_under_the_key() -> None:
    env, cache, _ = _env()
    bad = PRICE_CROSS | {"condition_ir": {"ir_version": 1}}
    assert _post(env, bad).status_code == 422
    assert len(cache) == 0
    assert _post(env, bad).status_code == 422  # evaluated afresh, same answer
    assert _post(env, PRICE_CROSS).status_code == 201  # nothing stored: a new body is a first send
    assert len(env.repo.rows) == 1
