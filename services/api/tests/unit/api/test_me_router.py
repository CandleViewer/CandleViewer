"""HTTP-level tests for `GET /me`, `GET /me/preferences` and `GET /me/keymap` (#2713).

The server half of the shell bootstrap (E10-T04). A real `SessionService` over the in-memory
repository (real revocation, idle lock and expiry), a fake identity read path, no database and
no network (C-13.5)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api import me
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import SessionService
from candleviewer.settings import Environment
from tests.openapi_helpers import deref
from tests.unit.auth.session_fakes import FakeSessionRepository

_START = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
_SPEC: Any = load_openapi_spec()
_ME, _PREFERENCES, _KEYMAP = "/api/v1/me", "/api/v1/me/preferences", "/api/v1/me/keymap"
_ROUTES = [_ME, _PREFERENCES, _KEYMAP]
_SETTINGS_ROUTES = [_PREFERENCES, _KEYMAP]
_VIEWER = ["accounts:read", "settings:read"]
_ACCOUNT = "00000000-0000-4000-8000-00000000000a"


def _assert_problem(resp: Any, status: int, code: str) -> dict[str, Any]:
    """A contract `Problem` (RFC 9457) with the stable `code`, nothing else of the caller."""
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = resp.json()
    jsonschema.validate(body, deref(_SPEC, {"$ref": "#/components/schemas/Problem"}))
    assert body["code"] == code
    return body


class _Identity:
    """The SQL identity read path as the router sees it (`user`, `session_info`, `accounts`)."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.permissions: dict[str, list[str]] = {}
        self.grants: dict[str, list[dict[str, Any]]] = {}
        self.account_reads: list[str] = []

    async def user(self, user_id: str) -> dict[str, Any]:
        if user_id not in self.users:
            raise LookupError("unknown user")
        return dict(self.users[user_id])

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {
            "permissions": list(self.permissions[user_id]),
            "account_scope": [g["exchange_account_id"] for g in self.grants[user_id]],
        }

    async def accounts(self, user_id: str) -> list[dict[str, Any]]:
        self.account_reads.append(user_id)
        return [dict(g) for g in self.grants[user_id]]


class _Auth:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions
        self.sessions_is_active = True


class _Env:
    def __init__(
        self, *, identity: bool = True, environment: Environment = Environment.DEMO
    ) -> None:
        self.now = _START
        self.repo = FakeSessionRepository()
        self.svc = SessionService(
            self.repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: self.now
        )
        self.identity = _Identity()
        self.auth = _Auth(self.svc)
        app = FastAPI()
        app.include_router(
            me.make_me_router(
                self.auth,
                identity=self.identity if identity else None,
                environment=environment,
                clock=lambda: self.now,
            ),
            prefix="/api/v1",
        )
        self.client = TestClient(app, base_url="https://testserver")

    async def sign_in(
        self,
        *,
        roles: list[str] | tuple[str, ...] = ("viewer",),
        permissions: list[str] | None = None,
        status: str = "active",
        email: str = "alice@example.com",
        grants: list[dict[str, Any]] | None = None,
        idle_timeout_s: int = 900,
        **extra: Any,
    ) -> tuple[str, dict[str, str], Any]:
        """A user with a live session: (user id, bearer headers, minted session)."""
        user_id = str(uuid.uuid4())
        self.identity.users[user_id] = {
            "id": user_id,
            "username": "alice",
            "email": email,
            "display_name": None,
            "roles": list(roles),
            "status": status,
            "mfa_enabled": True,
            "mfa_required": True,
            "last_login_at": "2026-10-15T08:00:00+00:00",
            "created_at": "2026-09-01T00:00:00+00:00",
            "updated_at": "2026-10-01T00:00:00+00:00",
            **extra,
        }
        self.identity.permissions[user_id] = list(_VIEWER if permissions is None else permissions)
        self.identity.grants[user_id] = list(grants or [])
        minted = await self.svc.mint(user_id, idle_timeout_s=idle_timeout_s)
        return user_id, {"Authorization": f"Bearer {minted.access_token}"}, minted


@pytest.fixture()
def env() -> _Env:
    return _Env()


# -- authentication: one uniform 401 ---------------------------------------------------------


@pytest.mark.parametrize("path", _ROUTES)
async def test_get_without_a_bearer_token_is_401_unauthenticated(env: _Env, path: str) -> None:
    _assert_problem(env.client.get(path), 401, "unauthenticated")


@pytest.mark.parametrize("path", _ROUTES)
async def test_get_with_an_unknown_token_is_the_same_401_as_no_token(env: _Env, path: str) -> None:
    anonymous = env.client.get(path)
    unknown = env.client.get(path, headers={"Authorization": "Bearer not-a-handle-we-issued"})
    wrong_scheme = env.client.get(path, headers={"Authorization": "Basic Zm9vOmJhcg=="})
    assert unknown.json() == anonymous.json() == wrong_scheme.json()
    assert unknown.status_code == wrong_scheme.status_code == 401


@pytest.mark.parametrize("path", _ROUTES)
async def test_get_with_a_revoked_session_is_401(env: _Env, path: str) -> None:
    _, headers, minted = await env.sign_in()
    assert env.client.get(path, headers=headers).status_code == 200
    await env.svc.revoke(str(minted.session_id), reason="user_revoked")
    revoked = env.client.get(path, headers=headers)
    assert _assert_problem(revoked, 401, "unauthenticated") == env.client.get(path).json()


@pytest.mark.parametrize("path", _ROUTES)
async def test_get_with_an_idle_locked_session_is_401(env: _Env, path: str) -> None:
    _, headers, _ = await env.sign_in(idle_timeout_s=300)
    env.now += timedelta(minutes=6)  # past the 5 min idle lock, inside the 12 min access TTL
    _assert_problem(env.client.get(path, headers=headers), 401, "unauthenticated")


@pytest.mark.parametrize("path", _ROUTES)
async def test_get_with_an_expired_access_token_is_401(env: _Env, path: str) -> None:
    _, headers, _ = await env.sign_in()
    env.now += timedelta(minutes=13)
    _assert_problem(env.client.get(path, headers=headers), 401, "unauthenticated")


@pytest.mark.parametrize("status", ["disabled", "locked", "invited"])
@pytest.mark.parametrize("path", _ROUTES)
async def test_get_for_a_user_who_is_not_active_is_401(env: _Env, path: str, status: str) -> None:
    _, headers, _ = await env.sign_in(status=status)
    _assert_problem(env.client.get(path, headers=headers), 401, "unauthenticated")


@pytest.mark.parametrize("path", _ROUTES)
async def test_get_for_a_user_the_identity_store_no_longer_has_is_401(env: _Env, path: str) -> None:
    user_id, headers, _ = await env.sign_in()
    del env.identity.users[user_id]
    _assert_problem(env.client.get(path, headers=headers), 401, "unauthenticated")


async def test_a_request_is_activity_that_extends_the_idle_deadline(env: _Env) -> None:
    _, headers, minted = await env.sign_in(idle_timeout_s=600)
    env.now += timedelta(minutes=8)
    assert env.client.get(_ME, headers=headers).status_code == 200
    assert env.repo.sessions[str(minted.session_id)].last_seen_at == env.now


# -- authorisation: `settings:read` for preferences and keymap, none for /me -------------------


@pytest.mark.parametrize("path", _SETTINGS_ROUTES)
async def test_preferences_and_keymap_without_settings_read_are_403_forbidden(
    env: _Env, path: str
) -> None:
    _, headers, _ = await env.sign_in(permissions=["accounts:read"])
    body = _assert_problem(env.client.get(path, headers=headers), 403, "forbidden")
    assert body["required_permissions"] == ["settings:read"]


async def test_me_needs_no_permission_and_lists_the_empty_set(env: _Env) -> None:
    _, headers, _ = await env.sign_in(permissions=[])
    resp = env.client.get(_ME, headers=headers)
    assert resp.status_code == 200 and resp.json()["permissions"] == []


@pytest.mark.parametrize("path", _SETTINGS_ROUTES)
async def test_the_permission_is_refused_before_a_query_parameter_is(env: _Env, path: str) -> None:
    _, headers, _ = await env.sign_in(permissions=["accounts:read"])
    refused = env.client.get(path, params={"user_id": str(uuid.uuid4())}, headers=headers)
    _assert_problem(refused, 403, "forbidden")


# -- SR-026: self only, no target-user or undeclared parameter --------------------------------


@pytest.mark.parametrize("param", ["user_id", "userId", "account_id", "fields"])
@pytest.mark.parametrize("path", _ROUTES)
async def test_an_undeclared_query_parameter_is_refused_422_with_no_data(
    env: _Env, path: str, param: str
) -> None:
    user_id, headers, _ = await env.sign_in(grants=[_grant(_ACCOUNT)])
    other = str(uuid.uuid4())
    resp = env.client.get(path, params={param: other}, headers=headers)
    body = _assert_problem(resp, 422, "validation_failed")
    assert param in body["detail"] and other not in resp.text
    assert not {"user", "role", "permissions", "accounts", "bindings", "_meta"} & set(body)
    assert env.identity.account_reads == [], f"{user_id}: nothing may be read for a refusal"


@pytest.mark.parametrize("path", _ROUTES)
async def test_authentication_is_decided_before_a_query_parameter(env: _Env, path: str) -> None:
    refused = env.client.get(path, params={"user_id": str(uuid.uuid4())})
    _assert_problem(refused, 401, "unauthenticated")


# -- GET /me ---------------------------------------------------------------------------------


def _grant(account_id: str, mode: str = "trade") -> dict[str, Any]:
    return {
        "exchange_account_id": account_id,
        "label": "main-demo",
        "environment": "demo",
        "mode": mode,
    }


async def test_me_is_the_contract_shape_for_the_caller(env: _Env) -> None:
    user_id, headers, minted = await env.sign_in(
        roles=["manager"],
        permissions=["settings:read", "orders:write", "accounts:read"],
        grants=[_grant(_ACCOUNT, "trade"), _grant(str(uuid.uuid4()), "read")],
    )
    resp = env.client.get(_ME, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    jsonschema.validate(body, deref(_SPEC, {"$ref": "#/components/schemas/Me"}))
    assert api.Me.model_validate(body).user.id == uuid.UUID(user_id)
    assert body["user"]["username"] == "alice" and body["role"] == "manager"
    assert body["permissions"] == ["accounts:read", "orders:write", "settings:read"]
    assert [a["mode"] for a in body["accounts"]] == ["trade", "read"]
    assert body["accounts"][0] == _grant(_ACCOUNT, "trade")
    assert body["session"] == {
        "session_id": str(minted.session_id),
        "environment": "demo",
        "elevated_until": None,
        "one_click_armed_until": None,
    }


@pytest.mark.parametrize("environment", list(Environment), ids=lambda e: e.value)
async def test_me_session_environment_is_the_configured_environment(
    environment: Environment,
) -> None:
    """The shell takes its LIVE/DEMO/TESTNET badge from this field alone and never guesses."""
    configured = _Env(environment=environment)
    _, headers, _ = await configured.sign_in()
    body = configured.client.get(_ME, headers=headers).json()
    assert body["session"]["environment"] == environment.value


@pytest.mark.parametrize(
    ("roles", "role"),
    [
        (["viewer"], "viewer"),
        (["viewer", "manager"], "manager"),
        (["viewer", "owner", "manager"], "owner"),
    ],
)
async def test_me_role_is_the_highest_role_the_user_holds(
    env: _Env, roles: list[str], role: str
) -> None:
    _, headers, _ = await env.sign_in(roles=roles)
    body = env.client.get(_ME, headers=headers).json()
    assert body["role"] == role and sorted(body["user"]["roles"]) == sorted(roles)


async def test_me_for_a_user_with_no_live_role_is_403_forbidden(env: _Env) -> None:
    _, headers, _ = await env.sign_in(roles=[])
    _assert_problem(env.client.get(_ME, headers=headers), 403, "forbidden")


async def test_me_permissions_are_sorted_and_only_from_the_closed_vocabulary(env: _Env) -> None:
    _, headers, _ = await env.sign_in(
        permissions=["settings:read", "not:a-permission", "accounts:read", "settings:read"]
    )
    assert env.client.get(_ME, headers=headers).json()["permissions"] == [
        "accounts:read",
        "settings:read",
    ]


async def test_me_elevated_until_is_the_live_step_up_grace_expiry(env: _Env) -> None:
    _, headers, minted = await env.sign_in()
    live, lapsed = env.now + timedelta(minutes=4), env.now - timedelta(minutes=1)
    await env.repo.save_step_up_state(
        str(minted.session_id),
        elevations={
            "users": live,
            "keys": lapsed,
            "once:killswitch": env.now + timedelta(minutes=1),
        },
        failures=0,
        readonly_until=None,
    )
    session = env.client.get(_ME, headers=headers).json()["session"]
    assert session["elevated_until"] == live.isoformat().replace("+00:00", "Z")


async def test_me_serves_an_address_the_contract_email_format_would_refuse(env: _Env) -> None:
    """`users.email` is only `position('@' in email) > 1` and the owner's address is operator
    input (`CV_BOOTSTRAP_OWNER_EMAIL`), so `owner@candleviewer.local` is real data. Refusing it
    would make `/me`, and with it the whole shell, a 500."""
    _, headers, _ = await env.sign_in(roles=["owner"], email="owner@candleviewer.local")
    resp = env.client.get(_ME, headers=headers)
    assert resp.status_code == 200 and resp.json()["user"]["email"] == "owner@candleviewer.local"


async def test_me_carries_no_secret_field_even_when_the_store_returns_one(env: _Env) -> None:
    planted: dict[str, Any] = {  # not credentials: values that must never reach a response
        "password_hash": "$argon2id$leak",
        "totp_secret": "planted-totp-seed",
        "refresh_token_hash": "planted-refresh-hash",
    }
    _, headers, minted = await env.sign_in(**planted)
    resp = env.client.get(_ME, headers=headers)
    assert resp.status_code == 200
    forbidden = [
        "password",
        "argon2",
        "totp_secret",
        "planted",
        "refresh_token",
        "access_token",
        str(minted.access_token_jti),
        headers["Authorization"].split(" ", 1)[1],
    ]
    assert not [f for f in forbidden if f in resp.text], resp.text
    assert set(resp.json()["user"]) <= set(api.User.model_fields)


async def test_me_is_always_about_the_caller_and_never_another_user(env: _Env) -> None:
    alice, alice_headers, _ = await env.sign_in(grants=[_grant(_ACCOUNT)])
    bob, bob_headers, _ = await env.sign_in(roles=["manager"], grants=[])
    as_alice = env.client.get(_ME, headers=alice_headers).json()
    as_bob = env.client.get(_ME, headers=bob_headers).json()
    assert (as_alice["user"]["id"], as_bob["user"]["id"]) == (alice, bob)
    assert len(as_alice["accounts"]) == 1 and as_bob["accounts"] == []
    assert env.identity.account_reads == [alice, bob]


@pytest.mark.parametrize("path", _ROUTES)
async def test_the_responses_are_not_cacheable(env: _Env, path: str) -> None:
    _, headers, _ = await env.sign_in()
    assert env.client.get(path, headers=headers).headers["cache-control"] == "no-store"


# -- GET /me/preferences and GET /me/keymap ---------------------------------------------------


async def test_preferences_are_the_empty_effective_settings_when_nothing_is_stored(
    env: _Env,
) -> None:
    _, headers, _ = await env.sign_in()
    resp = env.client.get(_PREFERENCES, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    jsonschema.validate(body, deref(_SPEC, {"$ref": "#/components/schemas/Settings"}))
    assert api.Settings.model_validate(body).field_meta == api.FieldMeta(overridden=[])
    assert body == {"_meta": {"overridden": []}}


async def test_keymap_is_the_empty_profile_when_no_profile_is_stored(env: _Env) -> None:
    _, headers, _ = await env.sign_in()
    resp = env.client.get(_KEYMAP, headers=headers)
    assert resp.status_code == 200
    schema = _SPEC["paths"]["/me/keymap"]["get"]["responses"]["200"]["content"]
    jsonschema.validate(resp.json(), deref(_SPEC, schema["application/json"]["schema"]))
    assert resp.json() == {"bindings": []}


@pytest.mark.parametrize("path", _SETTINGS_ROUTES)
async def test_preferences_and_keymap_read_no_account(env: _Env, path: str) -> None:
    _, headers, _ = await env.sign_in(grants=[_grant(_ACCOUNT)])
    assert env.client.get(path, headers=headers).status_code == 200
    assert env.identity.account_reads == []


# -- fail closed when the backend is not wired -----------------------------------------------


@pytest.mark.parametrize("path", _ROUTES)
async def test_routes_answer_503_while_the_session_backend_is_not_active(
    env: _Env, path: str
) -> None:
    _, headers, _ = await env.sign_in()
    env.auth.sessions_is_active = False
    _assert_problem(env.client.get(path, headers=headers), 503, "store_unavailable")


@pytest.mark.parametrize("path", _ROUTES)
async def test_routes_answer_501_without_an_identity_provider_after_authenticating(
    path: str,
) -> None:
    bare = _Env(identity=False)
    _, headers, _ = await bare.sign_in()
    _assert_problem(bare.client.get(path, headers=headers), 501, "not_implemented")
    _assert_problem(bare.client.get(path), 401, "unauthenticated")
