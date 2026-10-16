"""HTTP-level tests for `GET /me`, `GET /me/preferences` and `GET /me/keymap` (#2713).

The server half of the shell bootstrap (E10-T04). A real `SessionService` over the in-memory
repository (real revocation, idle lock and expiry), a fake identity read path, no database and
no network (C-13.5)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from structlog.testing import capture_logs

import candleviewer.app as appmod
from candleviewer.api import me
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import StepUpChallenge
from candleviewer.settings import Environment, Settings
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
    """A `Problem` (RFC 9457) with the stable `code`, nothing else of the caller, and the answer
    the contract declares for `status` on the operation `resp` came from (C-6.2): an undeclared
    status fails here, and so does a body its declared response does not describe."""
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    path = resp.request.url.path.removeprefix("/api/v1")
    declared = _SPEC["paths"][path]["get"]["responses"]
    assert str(status) in declared, f"{path} answers {status}, which the contract does not declare"
    body: dict[str, Any] = resp.json()
    schema = deref(_SPEC, declared[str(status)])["content"]["application/problem+json"]["schema"]
    jsonschema.validate(body, schema)
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
async def test_get_with_an_idle_locked_session_is_401_session_idle_locked(
    env: _Env, path: str
) -> None:
    """Contract "Idle lock" (#2300, #3053 item 1): the shell shows the unlock screen, not
    sign-in, when the bootstrap call is refused because the session is locked."""
    _, headers, _ = await env.sign_in(idle_timeout_s=300)
    env.now += timedelta(minutes=6)  # past the 5 min idle lock, inside the 12 min access TTL
    locked = _assert_problem(env.client.get(path, headers=headers), 401, "session_idle_locked")
    assert locked["idle_locked_at"] == (_START + timedelta(seconds=300)).isoformat()


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


@pytest.mark.parametrize("permissions", [None, []], ids=["default_permissions", "no_permissions"])
@pytest.mark.parametrize("roles", [["auditor"], ["viewer", "auditor"], ["owner", "superuser"]])
@pytest.mark.parametrize("path", _ROUTES)
async def test_get_for_a_user_holding_a_role_outside_the_closed_set_is_the_same_401(
    env: _Env, path: str, roles: list[str], permissions: list[str] | None
) -> None:
    """The snapshot and rules-actor resolvers build a `PrincipalSnapshot`, which refuses a role
    outside the closed set, and answer no principal (401). One unknown role refuses the whole
    principal, whatever else it holds: the answer must not depend on which roles come with it,
    and it must be the anonymous body. The refusal also comes before the permission check: with no
    permission at all (the default set holds `settings:read`) the two settings routes still answer
    the 401, not the `403 forbidden` that names what the caller lacks."""
    _, headers, _ = await env.sign_in(roles=roles, permissions=permissions)
    refused = _assert_problem(env.client.get(path, headers=headers), 401, "unauthenticated")
    assert refused == env.client.get(path).json()


@pytest.mark.parametrize("role", _SPEC["components"]["schemas"]["RoleName"]["enum"])
async def test_every_role_the_contract_names_is_served(env: _Env, role: str) -> None:
    """The closed set the gate admits is the contract's `RoleName`: a role added there must be
    served here, not refused as unknown."""
    _, headers, _ = await env.sign_in(roles=[role])
    resp = env.client.get(_ME, headers=headers)
    assert resp.status_code == 200 and resp.json()["role"] == role


async def test_a_request_is_never_activity_and_leaves_the_idle_deadline(env: _Env) -> None:
    """#2300, contract "Idle lock": activity is explicit (only extend and unlock record it)."""
    _, headers, minted = await env.sign_in(idle_timeout_s=600)
    signed_in_at = env.repo.sessions[str(minted.session_id)].last_seen_at
    env.now += timedelta(minutes=8)
    assert env.client.get(_ME, headers=headers).status_code == 200
    assert env.repo.sessions[str(minted.session_id)].last_seen_at == signed_in_at


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


def _wire(instant: datetime) -> str:
    """A UTC instant as the contract's `date-time` carries it."""
    return instant.isoformat().replace("+00:00", "Z")


async def _seed_step_up(env: _Env, minted: Any, elevations: dict[str, datetime]) -> None:
    """Put `elevations` on the signed-in session's row the way `StepUpService` keeps them: a
    grace window under its action class, a one-shot grant under `once:<class>`, a challenge
    under `StepUpChallenge.key()`."""
    await env.repo.save_step_up_state(
        str(minted.session_id), elevations=elevations, failures=0, readonly_until=None
    )


async def test_me_elevated_until_is_the_live_step_up_grace_expiry(env: _Env) -> None:
    """The latest live grace window, and nothing else. The one-shot grant and the pending
    challenge are newer than both windows and so expire after them: counting either of them, or
    answering with the earlier window, changes the answer."""
    _, headers, minted = await env.sign_in()
    latest = env.now + timedelta(minutes=4)
    earlier = env.now + timedelta(minutes=2)
    newest = env.now + timedelta(minutes=5)
    challenge = StepUpChallenge(uuid.UUID(int=7), "keys", newest)
    await _seed_step_up(
        env,
        minted,
        {"users": latest, "recorder": earlier, "once:killswitch": newest, challenge.key(): newest},
    )
    session = env.client.get(_ME, headers=headers).json()["session"]
    assert session["elevated_until"] == _wire(latest)


async def test_me_elevated_until_is_null_when_no_grace_window_is_live(env: _Env) -> None:
    """None of these is an elevation: a lapsed window, a window that ends at this very instant
    (`remaining_grace` refuses it too), a live one-shot grant and a live pending challenge. A
    lapsed window can never outlast a live one, so only a row with no live window can show that
    a lapsed one is not counted."""
    _, headers, minted = await env.sign_in()
    newest = env.now + timedelta(minutes=5)
    challenge = StepUpChallenge(uuid.UUID(int=7), "keys", newest)
    await _seed_step_up(
        env,
        minted,
        {
            "keys": env.now - timedelta(minutes=1),
            "audit": env.now,
            "once:killswitch": newest,
            challenge.key(): newest,
        },
    )
    session = env.client.get(_ME, headers=headers).json()["session"]
    assert session["elevated_until"] is None


async def test_me_serves_the_owner_address_on_a_special_use_domain(env: _Env) -> None:
    """`users.email` is only `position('@' in email) > 1` and the owner's address is operator
    input (`CV_BOOTSTRAP_OWNER_EMAIL`), so `owner@candleviewer.local` is real data, and the
    contract's `User.email` accepts it. Refusing it would make `/me`, and with it the whole
    shell, a 500."""
    _, headers, _ = await env.sign_in(roles=["owner"], email="owner@candleviewer.local")
    resp = env.client.get(_ME, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == "owner@candleviewer.local"
    jsonschema.validate(resp.json(), deref(_SPEC, {"$ref": "#/components/schemas/Me"}))


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


#: The text of the failure a stopping session store raises. It must never reach a client, and the
#: log gives it no field of its own.
_STORE_FAILURE = "session store stopped"


def _fail_the_session_store(
    env: _Env, monkeypatch: pytest.MonkeyPatch, failure: type[Exception] = RuntimeError
) -> None:
    """The store fails with `failure` while `authenticate_access_token` is awaited: the router has
    already taken `sessions_is_active` and `sessions` (nothing awaits between those reads, so that
    is the shape a stopping backend reaches it in; `AuthService.sessions` itself cannot raise
    there)."""

    async def _stopped(*_args: Any, **_kwargs: Any) -> Any:
        raise failure(_STORE_FAILURE)

    monkeypatch.setattr(env.svc, "authenticate_access_token", _stopped)


@pytest.mark.parametrize("path", _ROUTES)
async def test_routes_answer_503_when_the_session_store_fails_under_the_call(
    env: _Env, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same answer as an inactive backend, not an unhandled `RuntimeError` (a 500): the audit
    and snapshot resolvers catch it as well. The failure's text is not echoed."""
    _, headers, _ = await env.sign_in()
    _fail_the_session_store(env, monkeypatch)
    resp = env.client.get(path, headers=headers)
    failed = _assert_problem(resp, 503, "store_unavailable")
    assert _STORE_FAILURE not in resp.text
    env.auth.sessions_is_active = False
    assert env.client.get(path, headers=headers).json() == failed


@pytest.mark.parametrize("path", _ROUTES)
async def test_a_session_store_failure_is_logged_with_its_class_and_a_traceback(
    env: _Env, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The broad catch must not hide a defect: one error line names the class and carries the
    exception, which the processor chain renders as a traceback and then redacts. The message has
    no field of its own, so only that traceback can carry it."""
    _, headers, _ = await env.sign_in()
    _fail_the_session_store(env, monkeypatch)
    with capture_logs() as logs:
        env.client.get(path, headers=headers)
    (entry,) = logs
    assert (entry["event"], entry["log_level"], entry["error"]) == (
        "auth.me.session_backend_error",
        "error",
        "RuntimeError",
    )
    assert isinstance(entry["exc_info"], RuntimeError)
    assert _STORE_FAILURE not in repr({k: v for k, v in entry.items() if k != "exc_info"})


@pytest.mark.parametrize("path", _ROUTES)
async def test_a_session_store_failure_that_is_not_a_runtime_error_is_not_answered_503(
    env: _Env, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The contract's `503` names `RuntimeError` and nothing wider. A store that fails another way
    (a refused connection, say) is not described by it and is not hidden behind it: the exception
    reaches the boundary handler, as any defect does."""
    _, headers, _ = await env.sign_in()
    _fail_the_session_store(env, monkeypatch, ConnectionError)
    with pytest.raises(ConnectionError, match=_STORE_FAILURE):
        env.client.get(path, headers=headers)


@pytest.mark.parametrize("path", _ROUTES)
async def test_routes_answer_501_without_an_identity_provider_after_authenticating(
    path: str,
) -> None:
    bare = _Env(identity=False)
    _, headers, _ = await bare.sign_in()
    _assert_problem(bare.client.get(path, headers=headers), 501, "not_implemented")
    _assert_problem(bare.client.get(path), 401, "unauthenticated")


# -- the app composes the 501 away: the session backend and the identity provider come together --


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer not-a-handle-we-issued"}], ids=["no_token", "a_token"]
)
@pytest.mark.parametrize("path", [route.removeprefix("/api/v1") for route in _ROUTES])
def test_the_default_app_answers_503_on_every_route_with_or_without_a_token(
    path: str, headers: dict[str, str]
) -> None:
    """The default (fake) storage backend gives `create_app` no session backend and no identity
    provider, so the gate answers `503 store_unavailable` before it looks at a token. The `501` the
    contract also declares is not what that app answers: the contract text says so."""
    app = appmod.create_app()
    assert not app.state.app_context.auth.sessions_is_active
    assert app.state.identity_provider is None
    client = TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
    _assert_problem(client.get(path, headers=headers), 503, "store_unavailable")


@pytest.mark.parametrize(("backend", "wired"), [("fake", False), ("real", True)])
def test_the_session_backend_and_the_identity_provider_are_wired_together(
    backend: Literal["fake", "real"], wired: bool
) -> None:
    """The `501` needs an active session backend and no identity provider. The composition builds
    both on the real storage backend and neither on the fake one (nothing connects at
    construction), so only a router built by hand reaches it. A change that wires one without the
    other makes the `501` text of the contract, and this test, the place to look."""
    settings = Settings(
        storage_backend=backend,
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_pepper=SecretStr("pepper"),
    )
    assert (appmod.build_auth_service(settings)._session_repository is not None) is wired
    assert (appmod.build_identity_provider(settings) is not None) is wired


# -- wiring: the app hands the router its auth clock -------------------------------------------


async def test_the_app_gives_the_me_router_the_auth_clock_it_was_built_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`create_app` passes `make_me_router` the clock it builds the auth service with. Real UTC
    and the auth clock differ only under `CV_TEST_CLOCK` (#2086), so no other test here can tell
    them apart. This clock sits years before the wall clock: an elevation recorded on it reads
    live on it, and a router left on real UTC would read the same window as lapsed."""
    env = _Env()
    env.now = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _settings: env.identity)
    app = appmod.create_app(auth_clock=lambda: env.now)
    # The lifespan does not run, so the session service is wired by hand, as in the RBAC pack.
    app.state.app_context.auth._sessions = env.svc
    client = TestClient(app, client=("127.0.0.1", 50000))
    _, headers, minted = await env.sign_in()
    window = env.now + timedelta(minutes=4)
    await _seed_step_up(env, minted, {"users": window})
    resp = client.get("/me", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["session"]["elevated_until"] == _wire(window)
