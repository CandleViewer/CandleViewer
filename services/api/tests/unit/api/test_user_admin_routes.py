"""E42-T09 (#2649): `getUser`, `updateUser`, `listUserSessions` and `revokeUserSession`.

The routes over an in-memory user admin store that keeps the SQL store's rules (the owner floor on
the roles it counts, the precondition and the write-ahead audit under its "lock"), the real
`UserDisableService` world of `tests/unit/admin/test_user_disable.py` for a PATCH to `disabled`,
and, for the session routes, the real `SessionService`, B16 `SessionChart` and WS `RevocationHub`
over the in-memory session rows. The store itself: `tests/unit/storage/test_user_admin_store.py`;
Postgres: `tests/integration/admin/test_user_admin_pg.py`; the deployed app:
`tests/security/auth/test_user_admin_e2e.py`.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.admin.lifecycle_metrics import user_lifecycle_steps_total, user_lifecycle_total
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.users import (
    ADMIN_REVOKE_REASON,
    make_user_admin_router,
    representation,
    user_etag,
)
from candleviewer.app import _hub_publisher
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.errors import SessionNotFound, StepUpRequired
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.owner_floor import assert_owner_floor
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_chart import SessionChart
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories import identity_sqlalchemy
from candleviewer.storage.repositories.owner_floor_sqlalchemy import LOCK_USER
from candleviewer.storage.repositories.user_lifecycle import (
    UserPatch,
    UserPrecondition,
    UserUpdate,
    UserUpdateAudit,
)
from candleviewer.ws.revocation import CLOSE_TOKEN_EXPIRED, RevocationHub
from tests.conftest import RecordingAuditSink
from tests.unit.admin.test_user_disable import _TARGET, _World
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.storage.test_user_lifecycle_sqlalchemy import _Rel

CALLER, OTHER_OWNER, MISSING = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
M = _TARGET  # manager M, the target of the disable world
_T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
_SESSION = uuid.uuid4()  # the caller's own session
_PATH = "/users/{}"
_ROLES = ("owner", "manager", "viewer")
#: A fixed session id: a parameter id must be the same in every collection (the QA pack).
_ANY_SESSION = uuid.UUID(int=0x5E55)


def _user(uid: uuid.UUID, roles: tuple[str, ...], status: str = "active") -> dict[str, Any]:
    """A `User` row as `identity_sqlalchemy.read_user` returns it."""
    name = f"u{uid.hex[:8]}"
    return {
        "id": str(uid),
        "username": name,
        "email": f"{name}@example.invalid",
        "display_name": None,
        "roles": sorted(roles),
        "status": status,
        "mfa_enabled": True,
        "mfa_required": True,
        "last_login_at": None,
        "created_at": "2026-10-01T00:00:00+00:00",
        "updated_at": "2026-10-01T00:00:00+00:00",
        "password_hash": "$argon2id$never-returned",  # a column the read model must not leak
    }


def _pushes(outcome: str) -> float:  # the role push's `cv_user_lifecycle_steps_total`, a delta
    return float(user_lifecycle_steps_total.labels(step="roles_push", outcome=outcome)._value.get())


def _calls(result: str) -> float:  # `cv_user_lifecycle_total` of the disable, read as a delta
    return float(user_lifecycle_total.labels(action="disable", result=result)._value.get())


class _Log(list[str]):
    pass


class _Emitter:
    """The audit writer: `fail` refuses every record, as a stopped writer does."""

    def __init__(self, log: _Log, *, fail: bool = False) -> None:
        self.log, self.fail, self.calls = log, fail, list[dict[str, Any]]()

    async def emit(self, action: str, **kwargs: Any) -> None:
        if self.fail:
            raise AuditUnavailable("WAL unwritable")
        self.log.append(action)
        self.calls.append({"action": action, **kwargs})

    def of(self, action: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["action"] == action]


class _Store:
    """`UserAdminStore` in memory, with the SQL store's rules: under its "lock" it hands the
    representation to `check`, refuses the owner floor on the roles it counts (an active
    target's), awaits `audit` ahead of the commit, and changes nothing when any of them raises."""

    def __init__(self, log: _Log, *users: dict[str, Any]) -> None:
        self.log, self.users = log, {uuid.UUID(u["id"]): u for u in users}
        self.read_error: Exception | None = None
        self.update_error: Exception | None = None

    async def get_user(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        self.log.append("read")
        if self.read_error is not None:
            raise self.read_error
        found = self.users.get(user_id)
        return None if found is None else copy.deepcopy(found)

    def _owners(self) -> int:
        return sum(u["status"] == "active" and "owner" in u["roles"] for u in self.users.values())

    async def update_user(
        self,
        user_id: uuid.UUID,
        patch: UserPatch,
        *,
        actor: uuid.UUID,
        check: UserPrecondition,
        audit: UserUpdateAudit,
    ) -> UserUpdate | None:
        self.log.append("lock")
        if self.update_error is not None:
            raise self.update_error
        if (found := self.users.get(user_id)) is None:
            return None
        before = copy.deepcopy(found)
        check(before)
        after = copy.deepcopy(before)
        if patch.roles is not None and frozenset(patch.roles) != frozenset(before["roles"]):
            counted = frozenset(before["roles"]) if before["status"] == "active" else frozenset()
            assert_owner_floor(
                current_roles=counted, new_roles=patch.roles, active_owner_count=self._owners()
            )
            after["roles"] = sorted(patch.roles)
        if patch.set_display_name:
            after["display_name"] = patch.display_name
        if patch.require_mfa:
            after["mfa_required"] = True
        if patch.enable and before["status"] == "disabled":
            after["status"] = "active"
        if after == before:
            return UserUpdate(user_id, before, before)
        after["updated_at"] = "2026-10-19T12:00:00+00:00"
        change = UserUpdate(user_id, before, after)
        await audit(change)
        self.users[user_id] = after  # the commit
        self.log.append("commit")
        return change


class _StepUp:
    """The step-up gate (SR-025) and the B16 charts (`StepUpService.chart`)."""

    def __init__(self, log: _Log, *, elevated: bool, chart: Any) -> None:
        self.log, self.elevated, self.chart = log, elevated, chart
        self.pending = list[tuple[str, str]]()

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        self.log.append("step_up")
        if not self.elevated:
            raise StepUpRequired(action_class)

    async def record_pending(self, session_id: str, action_class: str) -> StepUpChallenge:
        self.pending.append((session_id, action_class))
        return StepUpChallenge(uuid.uuid4(), action_class, _T0 + CHALLENGE_WINDOW)


class _Rows(FakeSessionRepository):
    """The session rows; a revoke logs how many `auth.session_revoked` records exist by then."""

    def __init__(self, log: _Log, b16: RecordingAuditSink) -> None:
        super().__init__()
        self.log, self.b16 = log, b16

    async def revoke(self, session_id: str, *, reason: str, now: datetime) -> SessionRecord | None:
        recorded = self.b16.actions().count("auth.session_revoked")
        self.log.append(f"row_revoke:{reason}:{recorded}")
        return await super().revoke(session_id, reason=reason, now=now)


class _Sessions(SessionService):
    """The real session service; the caller's bearer always names `_SESSION`."""

    async def authenticate_access_token(self, raw: str, **_: Any) -> Any:
        if raw != "tok":
            raise SessionNotFound("unknown token")
        return SimpleNamespace(id=_SESSION, user_id=CALLER)

    async def peek_access_token(self, raw: str) -> Any:
        return SimpleNamespace(id=_SESSION) if raw == "tok" else None


class _Auth:
    step_up_is_active = sessions_is_active = True

    def __init__(self, sessions: Any, step_up: _StepUp) -> None:
        self.sessions, self.step_up = sessions, step_up


def _record(user: uuid.UUID, **fields: Any) -> SessionRecord:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": user,
        "refresh_token_hash": uuid.uuid4().hex,  # token material the routes must never return
        "access_token_jti": uuid.uuid4(),
        "issued_at": _T0,
        "last_seen_at": _T0,
        "expires_at": _T0 + timedelta(hours=12),
        "revoked_at": None,
        "revoked_reason": None,
        "ip": "100.64.0.7",
        "user_agent": "cv-test",
        "device_label": "laptop",
        "is_electron": False,
        "mfa_satisfied_at": _T0,
    }
    return SessionRecord(**(row | fields))


def _principal(role: str, spec: dict[str, Any], uid: uuid.UUID = CALLER) -> PrincipalSnapshot:
    codes = frozenset(Permission) if role == "owner" else None
    perms = codes or frozenset(Permission(p) for p in spec["x-permissions"][role])
    return PrincipalSnapshot(uid, frozenset({role}), perms)


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    loaded: dict[str, Any] = load_openapi_spec()
    return loaded


class _Env:
    """One app: the store, the audit writer, the session world and (for a disable) `w`."""

    def __init__(
        self,
        b16: RecordingAuditSink,
        principal: PrincipalSnapshot | None,
        *users: dict[str, Any],
        elevated: bool = True,
        fail_audit: bool = False,
        world: _World | None = None,
        store: bool = True,
    ) -> None:
        self.log = _Log()
        self.emitter = _Emitter(self.log, fail=fail_audit)
        self.store = _Store(self.log, *users)
        self.rows, self.hub = _Rows(self.log, b16), RevocationHub()
        self.closed = dict[str, tuple[str, int]]()
        self.pushed = list[uuid.UUID]()
        self.sessions = _Sessions(
            self.rows, Hasher(), clock=lambda: _T0, publish_revocation=_hub_publisher(self.hub)
        )
        self.step_up = _StepUp(self.log, elevated=elevated, chart=SessionChart())
        self.world = world
        self.push_error: Exception | None = None
        notifier = SimpleNamespace(roles_changed=self.roles_changed)
        app = FastAPI()
        app.include_router(
            make_user_admin_router(
                self.store if store else None,
                self.emitter,
                SimpleNamespace(resolve=lambda request: principal),
                notifier,
                auth=_Auth(self.sessions, self.step_up),
                user_disable=None if world is None else world.svc,
            )
        )
        self.client = TestClient(
            app, headers={"Authorization": "Bearer tok"}, raise_server_exceptions=False
        )

    async def roles_changed(self, user_id: uuid.UUID) -> None:
        self.pushed.append(user_id)
        if self.push_error is not None:
            raise self.push_error

    def socket(self, record: SessionRecord) -> None:
        """A live socket on `record`, as the gateway registers one with the hub."""

        async def close(frame: dict[str, Any], code: int) -> None:
            self.closed[str(record.id)] = (frame["p"]["reason"], code)

        self.hub.register(str(record.id), close)

    def patch(self, target: uuid.UUID, body: Any, **kwargs: Any) -> Any:
        return self.client.patch(_PATH.format(target), json=body, **kwargs)


def _conforms(spec: dict[str, Any], path: str, method: str, r: Any) -> None:
    """The answer is one the operation declares, and a refusal is the contract's `Problem`."""
    assert str(r.status_code) in spec["paths"][path][method]["responses"], r.text
    if r.status_code >= 400:
        problem = {"$ref": "#/components/schemas/Problem", "components": spec["components"]}
        assert jsonschema.Draft202012Validator(problem).is_valid(r.json()), r.text
        assert r.headers["content-type"].startswith("application/problem+json")


# -- S10: GET /users/{userId} with an ETag ------------------------------------------------------


def test_get_user_answers_the_user_and_an_etag(b16_audit: RecordingAuditSink, spec: Any) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    r = env.client.get(_PATH.format(M))
    _conforms(spec, "/users/{userId}", "get", r)
    assert r.status_code == 200 and r.json()["roles"] == ["manager"]
    user = {"$ref": "#/components/schemas/User", "components": spec["components"]}
    assert jsonschema.Draft202012Validator(user).is_valid(r.json())
    assert r.headers["etag"] == user_etag(r.json())


def test_no_password_hash(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """UL3-I1: no `password_hash` (nor any column outside the contract's `User`) is answered."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    for r in (env.client.get(_PATH.format(M)), env.patch(M, {"display_name": "M"})):
        assert r.status_code == 200
        assert "password_hash" not in r.json() and "argon2" not in r.text
        assert set(r.json()) <= set(spec["components"]["schemas"]["User"]["properties"])


def test_etag_tracks_roles(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """R4 (UL3-T1): the tag versions the whole representation, so a role change, a field that is
    no column of `users`, makes an earlier tag stale; an unchanged user keeps its tag."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("viewer",)))
    first = env.client.get(_PATH.format(M)).headers["etag"]
    assert env.client.get(_PATH.format(M)).headers["etag"] == first  # stable while unchanged
    env.store.users[M]["roles"] = ["manager"]
    assert env.client.get(_PATH.format(M)).headers["etag"] != first


def test_get_missing_user_is_404_and_a_store_outage_503(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env = _Env(b16_audit, _principal("owner", spec))
    missing = env.client.get(_PATH.format(MISSING))
    _conforms(spec, "/users/{userId}", "get", missing)
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")

    env.store.read_error = ConnectionRefusedError(111, "database down")  # an outage (an OSError)
    down = env.client.get(_PATH.format(M))
    assert (down.status_code, down.json()["code"]) == (503, "store_unavailable")


@pytest.mark.parametrize("role", ["manager", "viewer"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/users/{}", None),
        ("PATCH", "/users/{}", {"display_name": "x"}),
        ("GET", "/users/{}/sessions", None),
        ("DELETE", "/users/{}/sessions/" + str(_ANY_SESSION), None),
    ],
)
def test_forbidden_manager_viewer_audited(
    b16_audit: RecordingAuditSink, spec: Any, role: str, method: str, path: str, body: Any
) -> None:
    """D1, U25: 403 before any lookup, the same for an existing and a missing id, audited as
    `rbac.denied` naming the target; nothing is read, checked for a step-up or changed."""
    for target in (M, MISSING):
        env = _Env(b16_audit, _principal(role, spec), _user(M, ("manager",)))
        r = env.client.request(method, path.format(target), json=body)
        assert (r.status_code, r.json()["code"]) == (403, "forbidden")
        (denied,) = env.emitter.calls
        assert (denied["action"], denied["object_id"]) == ("rbac.denied", str(target))
        assert denied["session_id"] == _SESSION
        assert env.log == ["rbac.denied"] and env.store.users[M]["roles"] == ["manager"]


def test_unauthenticated_is_401_and_unwired_is_501(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env = _Env(b16_audit, None, _user(M, ("manager",)))
    r = env.client.get(_PATH.format(M))
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    unwired = _Env(b16_audit, _principal("owner", spec), store=False)
    for method, path in (("GET", "/users/{}"), ("GET", "/users/{}/sessions")):
        got = unwired.client.request(method, path.format(M))
        assert (got.status_code, got.json()["code"]) == (501, "not_implemented")
    assert unwired.patch(M, {"display_name": "x"}).status_code == 501
    app = FastAPI()
    never_called: Any = object()  # a notifier no read reaches
    app.include_router(make_user_admin_router(None, _Emitter(_Log()), None, never_called))
    assert TestClient(app).get(_PATH.format(M)).status_code == 501


def test_router_requires_audit_emitter_and_notifier() -> None:
    with pytest.raises(TypeError, match="required"):
        make_user_admin_router(None, None, None, object())  # type: ignore[arg-type]  # the point
    with pytest.raises(TypeError, match="required"):
        make_user_admin_router(None, _Emitter(_Log()), None, None)  # type: ignore[arg-type]  # the point


# -- S10: PATCH name and MFA flag, If-Match, step-up, audit ---------------------------------------


def test_patch_name_answers_the_new_user_and_etag_written_ahead(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    tag = env.client.get(_PATH.format(M)).headers["etag"]
    r = env.patch(M, {"display_name": "Morgan"}, headers={"If-Match": tag})
    _conforms(spec, "/users/{userId}", "patch", r)
    assert r.status_code == 200 and r.json()["display_name"] == "Morgan"
    assert r.headers["etag"] == user_etag(r.json()) != tag
    assert env.log[-3:] == ["lock", "users.update", "commit"]  # the record ahead of the commit
    (record,) = env.emitter.of("users.update")
    assert (record["actor_user_id"], record["object_id"]) == (CALLER, str(M))
    assert record["reason"] == "display_name" and record["session_id"] == _SESSION
    assert "Morgan" not in str(record)  # O6: the field's name, never its value (PII)
    assert env.pushed == []  # no role changed: nothing to re-evaluate


@pytest.mark.parametrize("role", _ROLES)
def test_mfa_required_false_400(b16_audit: RecordingAuditSink, spec: Any, role: str) -> None:
    """O3 (C-12.2): `mfa_required: false` is 400 `validation_failed` whatever the target's role,
    before any lookup or step-up; nothing changes."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, (role,)))
    r = env.patch(M, {"mfa_required": False})
    _conforms(spec, "/users/{userId}", "patch", r)
    assert (r.status_code, r.json()["code"]) == (400, "validation_failed")
    assert "mfa_required" in r.json()["detail"]
    assert env.log == [] and env.store.users[M]["mfa_required"] is True


def test_mfa_required_true_sets_the_flag_and_records_it(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    legacy = _user(M, ("viewer",)) | {"mfa_required": False}
    env = _Env(b16_audit, _principal("owner", spec), legacy)
    r = env.patch(M, {"mfa_required": True})
    assert r.status_code == 200 and r.json()["mfa_required"] is True
    (record,) = env.emitter.of("users.update")
    assert record["before_state"] == {"mfa_required": False}
    assert record["after_state"] == {"changed": ["mfa_required"], "mfa_required": True}


def test_stale_if_match_412(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """UL3-T1: the owner read M; M's roles changed since; a PATCH with that ETag is 412
    `version_conflict` and nothing changes, before the store's lock is even taken."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("viewer",)))
    tag = env.client.get(_PATH.format(M)).headers["etag"]
    env.store.users[M]["roles"] = ["manager"]  # another owner's role change
    r = env.patch(M, {"display_name": "x"}, headers={"If-Match": tag})
    _conforms(spec, "/users/{userId}", "patch", r)
    assert (r.status_code, r.json()["code"]) == (412, "version_conflict")
    assert "lock" not in env.log and env.store.users[M]["display_name"] is None
    assert env.emitter.calls == []


def test_a_change_between_the_read_and_the_lock_is_412(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """R7: the version is checked again on what the store reads under its lock."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("viewer",)))
    tag = env.client.get(_PATH.format(M)).headers["etag"]
    update = env.store.update_user

    async def racing(user_id: uuid.UUID, patch: UserPatch, **kwargs: Any) -> Any:
        env.store.users[M]["roles"] = ["manager"]  # lands before this transaction's lock
        return await update(user_id, patch, **kwargs)

    env.store.update_user = racing  # type: ignore[method-assign]  # the race, injected
    r = env.patch(M, {"display_name": "x"}, headers={"If-Match": tag})
    assert (r.status_code, r.json()["code"]) == (412, "version_conflict")
    assert env.store.users[M]["display_name"] is None and "commit" not in env.log


@pytest.mark.parametrize("header", ['"*"', "*", '"a", "b"', "W/{tag}", "{tag}"])
def test_if_match_spellings(b16_audit: RecordingAuditSink, spec: Any, header: str) -> None:
    """One tag, quoted, bare or `W/`-prefixed, matches; `*` and a list match no version."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("viewer",)))
    tag = env.client.get(_PATH.format(M)).headers["etag"]
    value = header.format(tag=tag if header.startswith("W/") else tag.strip('"'))
    r = env.patch(M, {"display_name": "x"}, headers={"If-Match": value})
    assert r.status_code == (200 if "{tag}" in header else 412)


def test_patch_without_step_up_is_challenged_and_changes_nothing(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """SR-025 (UL-AC16): an owner without a live `users` elevation is challenged; nothing is
    read or changed. The deployed path guard challenges first (the composition tests)."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)), elevated=False)
    r = env.patch(M, {"display_name": "x"})
    _conforms(spec, "/users/{userId}", "patch", r)
    assert (r.status_code, r.json()["code"]) == (403, "step_up_required")
    assert env.log == ["step_up"] and env.step_up.pending == [(str(_SESSION), "users")]


def test_step_up_and_audit_503(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """AC8: with the audit writer down, every PATCH mutation answers 503 `audit_unavailable` and
    nothing changes; a refusal that cannot be audited is a 503 too."""
    for body in ({"display_name": "x"}, {"roles": ["viewer"]}, {"status": "active"}):
        env = _Env(
            b16_audit,
            _principal("owner", spec),
            _user(M, ("manager",), status="disabled"),
            fail_audit=True,
        )
        before = copy.deepcopy(env.store.users[M])
        r = env.patch(M, body)
        _conforms(spec, "/users/{userId}", "patch", r)
        assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable"), body
        assert env.store.users[M] == before and "commit" not in env.log
    refused = _Env(b16_audit, _principal("viewer", spec), _user(M, ("manager",)), fail_audit=True)
    r = refused.patch(M, {"display_name": "x"})
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")


def test_a_write_ahead_timeout_is_503_and_another_store_error_a_500(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    env.store.update_error = WriteAheadTimeout("write-ahead audit exceeded 5.0 s")
    r = env.patch(M, {"display_name": "x"})
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    env.store.update_error = TimeoutError()  # a commit's: an outage, never "nothing changed"
    r = env.patch(M, {"display_name": "x"})
    assert (r.status_code, r.json()["code"]) == (503, "store_unavailable")
    env.store.update_error = ValueError("a defect")
    assert env.patch(M, {"display_name": "x"}).status_code == 500


@pytest.mark.parametrize(
    "body",
    [
        {"status": "invited"},
        {"status": "locked"},
        {"roles": []},
        {"roles": ["root"]},
        {"bogus": 1},
        {"status": None},
        {"roles": None},
        {"mfa_required": None},
        {"display_name": "x" * 81},
        [],
    ],
)
def test_invited_or_locked_400(b16_audit: RecordingAuditSink, spec: Any, body: Any) -> None:
    """R6: `status` is `active` or `disabled` only (UL-AC10); any other body the contract refuses
    is 400 `validation_failed`, before any lookup, and nothing changes."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    r = env.patch(M, body)
    _conforms(spec, "/users/{userId}", "patch", r)
    assert (r.status_code, r.json()["code"]) == (400, "validation_failed")
    assert env.log == [] and "bogus" not in r.text


@pytest.mark.parametrize("status", ["invited", "locked"])
def test_an_invited_or_locked_user_is_not_enabled(
    b16_audit: RecordingAuditSink, spec: Any, status: str
) -> None:
    """UL-F3: R6 bars `invited` and `locked` as source states too: no PATCH activates an
    unredeemed invite or lifts a lock."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("viewer",), status=status))
    r = env.patch(M, {"status": "active"})
    assert (r.status_code, r.json()["code"]) == (400, "validation_failed")
    assert env.store.users[M]["status"] == status and env.emitter.calls == []


def test_a_body_too_large_or_a_bad_acknowledgement_is_400(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    big = env.client.patch(_PATH.format(M), content=b'{"display_name": "' + b"x" * 70_000 + b'"}')
    assert (big.status_code, big.json()["code"]) == (400, "validation_failed")
    for query in ("?acknowledge_unknown_positions=yes", "?acknowledge_unknown_positions=true&"
                  "acknowledge_unknown_positions=true"):  # fmt: skip
        r = env.client.patch(_PATH.format(M) + query, json={"status": "disabled"})
        assert (r.status_code, r.json()["code"]) == (400, "validation_failed")
    assert env.log == []


@pytest.mark.parametrize(
    "query",
    ["?purge=true", f"?userId={_ANY_SESSION}", "?acknowledge_unknown_positions=true&x=1"],
    ids=["purge", "target_user", "extra_key"],
)
def test_patch_undeclared_query_key_is_422(
    b16_audit: RecordingAuditSink, spec: Any, query: str
) -> None:
    """SR-026, as `DELETE /users/{userId}` refuses one (S7): a key `updateUser` does not declare
    is 422 `validation_failed`, decided on the names alone once RBAC passed, before any value,
    the body, the step-up or a lookup, and nothing changes. (`updateUser` declares no 422 yet:
    the contract wording is the E42-T04 contract lane's, #2710.)"""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    r = env.client.patch(_PATH.format(M) + query, json={"display_name": "x"})
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert [e["rule"] for e in r.json()["errors"]] == ["undeclared_parameter"]
    assert env.log == [] and env.store.users[M]["display_name"] is None
    viewer = _Env(b16_audit, _principal("viewer", spec), _user(M, ("manager",)))
    refused = viewer.client.patch(_PATH.format(M) + query, json={"display_name": "x"})
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")  # RBAC first


def test_a_display_name_with_a_nul_is_400(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """Postgres `text` cannot hold U+0000: 400 `validation_failed` before any lookup, never a data
    error at the store (a 500)."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    r = env.patch(M, {"display_name": "M\u0000"})
    _conforms(spec, "/users/{userId}", "patch", r)
    assert (r.status_code, r.json()["code"]) == (400, "validation_failed")
    assert "display_name" in r.json()["detail"] and env.log == []


def test_an_empty_patch_changes_nothing_and_takes_no_lock(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    r = env.patch(M, {})
    assert r.status_code == 200 and r.headers["etag"] == user_etag(r.json())
    assert env.log == ["step_up", "read"] and env.emitter.calls == []


def test_a_patch_that_changes_nothing_writes_no_record(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """A repeat is a state-based no-op: it succeeds, writes nothing and audits nothing."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    r = env.patch(M, {"roles": ["manager"], "status": "active", "mfa_required": True})
    assert r.status_code == 200 and "commit" not in env.log and env.emitter.calls == []


def test_patch_missing_user_is_404(b16_audit: RecordingAuditSink, spec: Any) -> None:
    env = _Env(b16_audit, _principal("owner", spec))
    r = env.patch(MISSING, {"display_name": "x"})
    _conforms(spec, "/users/{userId}", "patch", r)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")


# -- S11: roles and status under the owner lock -----------------------------------------------


@pytest.mark.parametrize("body", [{"roles": ["viewer"]}, {"status": "disabled"}])
def test_self_target_403(b16_audit: RecordingAuditSink, spec: Any, body: Any) -> None:
    """SR-055: never the acting user's roles or status, before the step-up; audited."""
    env = _Env(b16_audit, _principal("owner", spec), _user(CALLER, ("owner",)), elevated=False)
    r = env.patch(CALLER, body)
    _conforms(spec, "/users/{userId}", "patch", r)
    assert (r.status_code, r.json()["reason"]) == (403, "self_target")
    (denied,) = env.emitter.calls
    assert (denied["action"], denied["reason"], denied["object_id"]) == (
        "rbac.denied",
        "self_target",
        str(CALLER),
    )
    assert env.log == ["rbac.denied"] and env.store.users[CALLER]["roles"] == ["owner"]


def test_an_owner_may_rename_themselves(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """Only the caller's roles and status are refused (the contract's `updateUser`)."""
    env = _Env(b16_audit, _principal("owner", spec), _user(CALLER, ("owner",)))
    r = env.patch(CALLER, {"display_name": "Me"})
    assert r.status_code == 200 and r.json()["display_name"] == "Me"


def test_role_change_records_grant_and_revoke_ahead_and_pushes_after(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("viewer",)))
    pushed = _pushes("ok")
    r = env.patch(M, {"roles": ["manager"]})
    assert r.status_code == 200 and r.json()["roles"] == ["manager"]
    assert env.log[-4:] == ["lock", "roles.grant", "roles.revoke", "commit"]
    for action, reason in (("roles.grant", "manager"), ("roles.revoke", "viewer")):
        (record,) = env.emitter.of(action)
        assert record["reason"] == reason
        assert (record["before_state"], record["after_state"]) == (
            {"roles": ["viewer"]},
            {"roles": ["manager"]},
        )
    assert env.pushed == [M]  # live sockets re-evaluated after the commit (23 section 9.5)
    assert _pushes("ok") == pushed + 1  # R7: one count per post-commit step, its outcome


def test_a_failed_role_push_after_the_commit_is_logged_never_rolled_back(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """R7: counted (`roles_push`, `failed`: the `UserLifecycleStepFailed` ticket) and logged at
    error, never rolled back and never a 500."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("viewer",)))
    env.push_error = RuntimeError("socket registry down")
    failed = _pushes("failed")
    with capture_logs() as logs:
        r = env.patch(M, {"roles": ["manager"]})
    assert r.status_code == 200 and env.store.users[M]["roles"] == ["manager"]
    assert env.pushed == [M] and env.log[-1] == "commit"  # the push ran after the commit
    (line,) = [e for e in logs if e["event"] == "users.update.step"]
    assert (line["log_level"], line["step"], line["outcome"]) == ("error", "roles_push", "failed")
    assert _pushes("failed") == failed + 1


def test_last_owner_demotion_is_409_with_one_owner_floor_denial(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """SR-055, UL-F13: the last active owner is not demoted; the loser writes one `rbac.denied`
    (`owner_floor`) and no change record."""
    env = _Env(
        b16_audit,
        _principal("owner", spec),
        _user(OTHER_OWNER, ("owner",)),
        _user(CALLER, ("viewer",)),  # the caller's row counts no owner: B is the last one
    )
    r = env.patch(OTHER_OWNER, {"roles": ["manager"]})
    _conforms(spec, "/users/{userId}", "patch", r)
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    assert [(c["action"], c["reason"]) for c in env.emitter.calls] == [
        ("rbac.denied", "owner_floor")
    ]
    assert env.store.users[OTHER_OWNER]["roles"] == ["owner"] and env.pushed == []


def test_a_disabled_owner_is_demoted_while_one_other_owner_is_active(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """The floor counts an active target's owner grant only (`counted_roles`)."""
    env = _Env(
        b16_audit,
        _principal("owner", spec),
        _user(CALLER, ("owner",)),
        _user(OTHER_OWNER, ("owner",), status="disabled"),
    )
    r = env.patch(OTHER_OWNER, {"roles": ["viewer"]})
    assert r.status_code == 200 and r.json()["roles"] == ["viewer"]


def test_enable_audited_ahead(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """UL-F10 (R5): re-enabling writes `users.enable` ahead of the commit, with before and after
    (status and roles only, O6), named by the acting owner and the target."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",), status="disabled"))
    r = env.patch(M, {"status": "active"})
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert env.log[-3:] == ["lock", "users.enable", "commit"]
    (record,) = env.emitter.of("users.enable")
    assert (record["actor_user_id"], record["object_id"]) == (CALLER, str(M))
    assert record["before_state"] == {"status": "disabled", "roles": ["manager"]}
    assert record["after_state"] == {"status": "active", "roles": ["manager"]}


def test_enable_no_regrant(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """R6 (UL3-E2, UL-AC16): re-enabling restores nothing: no session, no grant, no role push (the
    store flips the status only; Postgres: `test_user_admin_pg.py::test_enable_no_regrant`)."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",), status="disabled"))
    asyncio.run(_seed(env, _record(M, revoked_at=_T0, revoked_reason="user_disabled")))
    r = env.patch(M, {"status": "active"})
    assert r.status_code == 200 and r.json()["roles"] == ["manager"]
    assert [row.revoked_reason for row in env.rows.sessions.values()] == ["user_disabled"]
    assert env.pushed == [] and env.closed == {}
    assert [c["action"] for c in env.emitter.calls] == ["users.enable"]  # nothing re-granted


def test_enable_audit_down_503(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """UL-F10: with the audit writer down a re-enable is 503 and M stays disabled."""
    env = _Env(
        b16_audit,
        _principal("owner", spec),
        _user(M, ("manager",), status="disabled"),
        fail_audit=True,
    )
    r = env.patch(M, {"status": "active"})
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert env.store.users[M]["status"] == "disabled"


def test_a_status_the_lock_reads_as_locked_is_not_enabled(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """R7: the status rule is checked again on the row read under the lock."""
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",), status="disabled"))
    update = env.store.update_user

    async def racing(user_id: uuid.UUID, patch: UserPatch, **kwargs: Any) -> Any:
        env.store.users[M]["status"] = "locked"
        return await update(user_id, patch, **kwargs)

    env.store.update_user = racing  # type: ignore[method-assign]  # the race, injected
    r = env.patch(M, {"status": "active"})
    assert (r.status_code, r.json()["code"]) == (400, "validation_failed")
    assert env.store.users[M]["status"] == "locked"


# -- S11: a PATCH to disabled is the disable cascade --------------------------------------------


def _disable_env(b16: RecordingAuditSink, spec: Any, **world: Any) -> tuple[_Env, _World]:
    """M in the disable world (`_World`, the real `UserDisableService` over the S3 store's fake
    unit of work); the user admin store reads M as the world's commit leaves it."""
    w = _World(_Rel(**world.pop("rel", {})), **world)
    env = _Env(b16, _principal("owner", spec), _user(M, ("manager",)), world=w)
    read = env.store.get_user

    async def as_committed(user_id: uuid.UUID) -> dict[str, Any] | None:
        found = await read(user_id)
        if found is not None and w.rel.committed:
            found["status"] = "disabled"
        return found

    env.store.get_user = as_committed  # type: ignore[method-assign]  # the read after the commit
    return env, w


def test_patch_disable_runs_disable_cascade(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """SR-029: the same service, guards, records and steps as `DELETE /users/{userId}`: one
    `users.disable` ahead (O2's fields), then the post-commit steps; the answer is the user."""
    env, w = _disable_env(b16_audit, spec, positions=0, orders=0)
    r = env.patch(M, {"status": "disabled"})
    _conforms(spec, "/users/{userId}", "patch", r)
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    assert r.headers["etag"] == user_etag(r.json())
    (record,) = w.of("users.disable")
    assert (record["actor_user_id"], record["object_id"]) == (CALLER, str(M))
    assert record["after_state"]["positions_decision"] == "leave" and w.rel.committed
    assert w.post_commit() and w.socket_users == [M]  # every socket of M (S7), after the commit


def test_patch_disable_positions_unknown_409(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """AC7 (O2): while the open-position count is unknown the disable needs the acknowledgement,
    else 409 `positions_unknown` and nothing changes; with it, the disable runs."""
    env, w = _disable_env(b16_audit, spec, positions=None)
    r = env.patch(M, {"status": "disabled"})
    _conforms(spec, "/users/{userId}", "patch", r)
    assert (r.status_code, r.json()["code"]) == (409, "positions_unknown")
    assert not w.rel.committed and w.of("users.disable") == []
    ok = env.client.patch(
        _PATH.format(M) + "?acknowledge_unknown_positions=true", json={"status": "disabled"}
    )
    assert ok.status_code == 200 and w.rel.committed
    (record,) = w.of("users.disable")
    assert record["after_state"]["acknowledged_unknown_positions"] is True


def test_patch_disable_of_the_last_owner_is_409_and_audit_down_503(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """AC6 / AC8 through the cascade's own refusals, mapped as the DELETE maps them."""
    env, _ = _disable_env(b16_audit, spec, rel={"roles": ("owner",), "owners": 1})
    r = env.patch(M, {"status": "disabled"})
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    env, w = _disable_env(b16_audit, spec, fail={"users.disable": [AuditUnavailable("x")]})
    r = env.patch(M, {"status": "disabled"})
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert not w.rel.committed


def test_a_disable_changes_nothing_else(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """One transaction per mutation (R7): a disable that would also change another field is 400
    before anything is read under a lock or written; the same values ride along freely."""
    env, w = _disable_env(b16_audit, spec)
    r = env.patch(M, {"status": "disabled", "roles": ["viewer"], "display_name": "x"})
    assert (r.status_code, r.json()["code"]) == (400, "validation_failed")
    assert "display_name, roles" in r.json()["detail"] and not w.rel.ran
    same = env.patch(M, {"status": "disabled", "roles": ["manager"], "mfa_required": True})
    assert same.status_code == 200 and w.rel.committed


def test_a_disable_without_the_service_is_501(b16_audit: RecordingAuditSink, spec: Any) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    r = env.patch(M, {"status": "disabled"})
    assert (r.status_code, r.json()["code"]) == (501, "not_implemented")


def _read_under_the_lock(user: Mapping[str, Any]) -> SimpleNamespace:
    """`user` as the disable store's `identity_sqlalchemy.read_user` reads its row under the lock
    (no `password_hash`; timestamps as the driver returns them)."""
    row = {key: value for key, value in user.items() if key != "password_hash"}
    for key in ("last_login_at", "created_at", "updated_at"):
        row[key] = None if row[key] is None else datetime.fromisoformat(row[key])
    return SimpleNamespace(_mapping=row)


def test_a_role_change_before_the_disable_lock_is_412(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """UL3-T1 (the #2649 review): a PATCH to `disabled` checks its `If-Match`
    again inside the disable's own transaction, on the user read under its lock. A role change
    committed after the route's read and before that lock is 412 `version_conflict`: the
    transaction rolls back with nothing written or recorded, no step runs, and the refusal is
    counted as `version_conflict`, never as an `error`."""
    env, w = _disable_env(b16_audit, spec, positions=0, orders=0)
    tag = env.client.get(_PATH.format(M)).headers["etag"]  # read while M is a manager
    changed = _read_under_the_lock(_user(M, ("viewer",)))  # another owner's change, committed
    w.rel.rows[identity_sqlalchemy._USER_SQL] = [changed]
    stale, errors = _calls("version_conflict"), _calls("error")
    r = env.patch(M, {"status": "disabled"}, headers={"If-Match": tag})
    _conforms(spec, "/users/{userId}", "patch", r)
    assert (r.status_code, r.json()["code"]) == (412, "version_conflict")
    assert w.rel.order() == [LOCK_USER, identity_sqlalchemy._USER_SQL]  # nothing written
    assert not w.rel.committed and w.calls == [] and w.post_commit() == []
    assert (_calls("version_conflict"), _calls("error")) == (stale + 1, errors)


def test_an_unchanged_user_under_the_disable_lock_is_disabled(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """The tag still names the version read under the lock: the cascade runs as without one."""
    env, w = _disable_env(b16_audit, spec, positions=0, orders=0)
    tag = env.client.get(_PATH.format(M)).headers["etag"]
    w.rel.rows[identity_sqlalchemy._USER_SQL] = [_read_under_the_lock(_user(M, ("manager",)))]
    r = env.patch(M, {"status": "disabled"}, headers={"If-Match": tag})
    assert r.status_code == 200 and r.json()["status"] == "disabled" and w.rel.committed
    assert w.rel.order()[:2] == [LOCK_USER, identity_sqlalchemy._USER_SQL]
    assert len(w.of("users.disable")) == 1


def test_a_disable_without_if_match_reads_nothing_more_under_the_lock(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """No `If-Match`, no precondition: the cascade's transaction is the DELETE's, statement for
    statement."""
    env, w = _disable_env(b16_audit, spec, positions=0, orders=0)
    assert env.patch(M, {"status": "disabled"}).status_code == 200
    assert identity_sqlalchemy._USER_SQL not in w.rel.order() and w.rel.committed


# -- S12: the admin view of a user's sessions ----------------------------------------------------


async def _seed(env: _Env, *records: SessionRecord) -> None:
    for record in records:
        await env.rows.create_session(record)


def _with_sessions(
    b16: RecordingAuditSink, spec: Any, **kwargs: Any
) -> tuple[_Env, SessionRecord, SessionRecord, SessionRecord]:
    """M with two live sessions (a socket on each) and another user's live session."""
    env = _Env(b16, _principal("owner", spec), _user(M, ("manager",)), **kwargs)
    first, second, foreign = _record(M), _record(M), _record(OTHER_OWNER)
    asyncio.run(_seed(env, first, second, foreign))
    for record in (first, second, foreign):
        env.socket(record)
    return env, first, second, foreign


def test_no_token_material(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """R4 (UL3-I1): the list is `listMySessions`' items, M's live sessions only, and no response
    carries `refresh_token_hash`, `access_token_jti` or any other token material."""
    env, first, second, foreign = _with_sessions(b16_audit, spec)
    r = env.client.get(f"/users/{M}/sessions")
    _conforms(spec, "/users/{userId}/sessions", "get", r)
    items = r.json()["items"]
    assert {i["id"] for i in items} == {str(first.id), str(second.id)}
    allowed = set(spec["components"]["schemas"]["UserSession"]["properties"])
    assert all(set(item) == allowed for item in items) and not any(i["current"] for i in items)
    for record in (first, second, foreign):
        assert (
            record.refresh_token_hash not in r.text and str(record.access_token_jti) not in r.text
        )


def test_list_sessions_of_a_missing_user_is_404(b16_audit: RecordingAuditSink, spec: Any) -> None:
    env = _Env(b16_audit, _principal("owner", spec))
    r = env.client.get(f"/users/{MISSING}/sessions")
    _conforms(spec, "/users/{userId}/sessions", "get", r)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")


def test_revoked_audit_ahead(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """R5: one `auth.session_revoked`, through B16 REVOKE, written before the row changes."""
    env, first, second, _ = _with_sessions(b16_audit, spec)
    r = env.client.delete(f"/users/{M}/sessions/{first.id}")
    _conforms(spec, "/users/{userId}/sessions/{sessionId}", "delete", r)
    assert r.status_code == 204 and r.content == b""
    (record,) = [c for c in b16_audit.calls if c["action"] == "auth.session_revoked"]
    assert (record["session_id"], record["reason"]) == (str(first.id), ADMIN_REVOKE_REASON)
    assert record["object_id"] == str(first.id) and record["object_kind"] == "session"
    assert env.log[-1] == f"row_revoke:{ADMIN_REVOKE_REASON}:1"  # one record already, by then
    assert env.rows.sessions[str(first.id)].revoked_reason == ADMIN_REVOKE_REASON
    assert env.rows.sessions[str(second.id)].revoked_at is None  # M's other session untouched
    assert env.step_up.log.count("step_up") == 1


def test_socket_4401_within_5s(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """23 section 9.5: the revoked session's socket gets `bye session_revoked` and closes 4401
    inside the DELETE itself, before its 204, so within 5 s on any clock (the fake one never
    moves); the other sockets stay open."""
    env, first, second, foreign = _with_sessions(b16_audit, spec)
    assert env.closed == {}
    assert env.client.delete(f"/users/{M}/sessions/{first.id}").status_code == 204
    assert env.closed == {str(first.id): ("session_revoked", CLOSE_TOKEN_EXPIRED)}
    assert {str(second.id), str(foreign.id)}.isdisjoint(env.closed)  # their sockets stay open


def _b16_into(env: _Env, b16: RecordingAuditSink) -> None:
    """B16's records join `env.log`, so their order against the route's records shows."""
    emit = b16.emit

    async def logged(action: str, **kwargs: Any) -> None:
        env.log.append(f"b16:{action}")
        await emit(action, **kwargs)

    b16.emit = logged  # type: ignore[method-assign]  # the sink, observed


def test_revoke_is_recorded_ahead_by_the_owner_then_by_b16(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """C-2.9, SR-055 (the #2649 review): the revoke's own record names the acting
    Owner: `users.session_revoked`, with the Owner's id, roles and elevated session, the revoked
    session and its user, and the reason. It is written ahead of B16 REVOKE, whose one
    `auth.session_revoked` (named by the session's own user) is written ahead of the row."""
    env, first, _, _ = _with_sessions(b16_audit, spec)
    _b16_into(env, b16_audit)
    r = env.client.delete(f"/users/{M}/sessions/{first.id}")
    assert r.status_code == 204
    revoke = f"row_revoke:{ADMIN_REVOKE_REASON}:1"
    ahead = ("users.session_revoked", "b16:auth.session_revoked", revoke)
    assert [e for e in env.log if e in ahead] == list(ahead)
    (record,) = env.emitter.of("users.session_revoked")
    assert (record["actor_user_id"], record["actor_label"]) == (CALLER, str(CALLER))
    assert record["session_id"] == _SESSION  # the Owner's elevated session, not the revoked one
    assert (record["object_kind"], record["object_id"]) == ("session", str(first.id))
    assert record["reason"] == ADMIN_REVOKE_REASON and "request_id" in record
    assert record["before_state"] == {"user_id": str(M), "revoked_reason": None}
    assert record["after_state"] == {
        "user_id": str(M),
        "revoked_reason": ADMIN_REVOKE_REASON,
        "actor_roles": ["owner"],
    }


def test_revoke_with_the_owner_record_refused_is_503_and_nothing_changes(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """AC8: the Owner's record cannot be written, so 503 `audit_unavailable`: B16 records
    nothing, and the session stays live with its socket open."""
    env, first, _, _ = _with_sessions(b16_audit, spec, fail_audit=True)
    r = env.client.delete(f"/users/{M}/sessions/{first.id}")
    _conforms(spec, "/users/{userId}/sessions/{sessionId}", "delete", r)
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert b16_audit.calls == [] and env.closed == {}
    assert env.rows.sessions[str(first.id)].revoked_at is None
    assert not [e for e in env.log if e.startswith("row_revoke")]


def test_a_session_that_ends_before_its_row_is_revoked_is_404(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    """The conditional row update revoked nothing: the session ended (here its own logout) after
    it was found live. The answer is the contract's 404 for an ended session, never a 204;
    nothing is published or closed, and nothing is written beyond the two records ahead."""
    env, first, _, _ = _with_sessions(b16_audit, spec)
    revoke = env.rows.revoke

    async def ended_first(session_id: str, *, reason: str, now: datetime) -> Any:
        await FakeSessionRepository.revoke(env.rows, session_id, reason="logout", now=now)
        return await revoke(session_id, reason=reason, now=now)

    env.rows.revoke = ended_first  # type: ignore[method-assign]  # the logout, landed in between
    r = env.client.delete(f"/users/{M}/sessions/{first.id}")
    _conforms(spec, "/users/{userId}/sessions/{sessionId}", "delete", r)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")
    assert env.rows.sessions[str(first.id)].revoked_reason == "logout" and env.closed == {}
    assert [c["action"] for c in env.emitter.calls] == ["users.session_revoked"]
    assert b16_audit.actions() == ["auth.session_revoked"]


def test_other_users_session_404(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """IDOR (UL3-I1, UL-AC11): another user's session id through M's path is 404, as an unknown
    or an ended one is; nothing is recorded, revoked or closed."""
    env, first, _, foreign = _with_sessions(b16_audit, spec)
    ended = _record(M, revoked_at=_T0, revoked_reason="logout")
    asyncio.run(_seed(env, ended))
    for sid in (foreign.id, uuid.uuid4(), ended.id):
        r = env.client.delete(f"/users/{M}/sessions/{sid}")
        _conforms(spec, "/users/{userId}/sessions/{sessionId}", "delete", r)
        assert (r.status_code, r.json()["code"]) == (404, "not_found")
    assert b16_audit.calls == [] and env.closed == {}
    assert env.rows.sessions[str(foreign.id)].revoked_at is None
    missing = env.client.delete(f"/users/{MISSING}/sessions/{first.id}")
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")


def test_audit_down_503(b16_audit: RecordingAuditSink, spec: Any) -> None:
    """AC8: B16 cannot write `auth.session_revoked`, so 503 `audit_unavailable` and the session
    stays live, its socket open. The Owner's record, written first, stands (the trail
    over-reports, never under-reports)."""
    env, first, _, _ = _with_sessions(b16_audit, spec)

    async def refuse(action: str, **kwargs: Any) -> None:
        raise AuditUnavailable("WAL unwritable")

    b16_audit.emit = refuse  # type: ignore[method-assign]  # the sink refuses every record
    r = env.client.delete(f"/users/{M}/sessions/{first.id}")
    _conforms(spec, "/users/{userId}/sessions/{sessionId}", "delete", r)
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert env.rows.sessions[str(first.id)].revoked_at is None and env.closed == {}
    assert not [e for e in env.log if e.startswith("row_revoke")]
    assert [c["action"] for c in env.emitter.calls] == ["users.session_revoked"]


def test_revoke_without_step_up_is_challenged(b16_audit: RecordingAuditSink, spec: Any) -> None:
    env, first, _, _ = _with_sessions(b16_audit, spec, elevated=False)
    r = env.client.delete(f"/users/{M}/sessions/{first.id}")
    assert (r.status_code, r.json()["code"]) == (403, "step_up_required")
    assert env.rows.sessions[str(first.id)].revoked_at is None and b16_audit.calls == []


def test_the_list_marks_the_callers_own_session_current(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(CALLER, ("owner",)))
    own = _record(CALLER).model_copy(update={"id": _SESSION})
    asyncio.run(_seed(env, own))
    r = env.client.get(f"/users/{CALLER}/sessions")
    assert [(i["id"], i["current"]) for i in r.json()["items"]] == [(str(_SESSION), True)]


def test_representation_keeps_the_contract_fields_only() -> None:
    shown = representation(_user(M, ("viewer", "manager")))
    assert "password_hash" not in shown and shown["roles"] == ["manager", "viewer"]
    tag = user_etag(shown)
    assert user_etag(dict(shown, roles=["viewer", "manager"])) == tag  # order-independent
    assert isinstance(shown, Mapping)


# -- the refusals and outages around each change -------------------------------------------------


class _Outage(ConnectionRefusedError):
    """A database that cannot be reached (an `OSError`, as the driver raises it)."""


def test_a_read_that_fails_otherwise_is_a_500(b16_audit: RecordingAuditSink, spec: Any) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    env.store.read_error = ValueError("a defect, never an outage")
    assert env.client.get(_PATH.format(M)).status_code == 500


def test_a_self_target_refusal_that_cannot_be_audited_is_503(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(CALLER, ("owner",)), fail_audit=False)
    env.emitter.fail = True  # the writer stops after RBAC passed (RBAC audits refusals only)
    r = env.patch(CALLER, {"status": "disabled"})
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")


def test_a_floor_denial_that_cannot_be_audited_is_503_and_changes_nothing(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env = _Env(
        b16_audit,
        _principal("owner", spec),
        _user(OTHER_OWNER, ("owner",)),
        _user(CALLER, ("viewer",)),
        fail_audit=True,
    )
    r = env.patch(OTHER_OWNER, {"roles": ["manager"]})
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert env.store.users[OTHER_OWNER]["roles"] == ["owner"]


def test_a_user_gone_before_the_lock_is_404(b16_audit: RecordingAuditSink, spec: Any) -> None:
    env = _Env(b16_audit, _principal("owner", spec), _user(M, ("manager",)))
    update = env.store.update_user

    async def deleted(user_id: uuid.UUID, patch: UserPatch, **kwargs: Any) -> Any:
        env.store.users.pop(M)
        return await update(user_id, patch, **kwargs)

    env.store.update_user = deleted  # type: ignore[method-assign]  # the deletion, injected
    r = env.patch(M, {"display_name": "x"})
    assert (r.status_code, r.json()["code"]) == (404, "not_found")


def test_a_disable_that_also_requires_mfa_is_refused(
    b16_audit: RecordingAuditSink, spec: Any
) -> None:
    env, w = _disable_env(b16_audit, spec)
    env.store.users[M]["mfa_required"] = False
    r = env.patch(M, {"status": "disabled", "mfa_required": True})
    assert (r.status_code, r.json()["code"]) == (400, "validation_failed")
    assert "mfa_required" in r.json()["detail"] and not w.rel.ran


@pytest.mark.parametrize(("error", "status"), [(_Outage(111, "down"), 503), (ValueError(), 500)])
def test_a_disable_store_failure_is_503_for_an_outage_else_500(
    b16_audit: RecordingAuditSink, spec: Any, error: Exception, status: int
) -> None:
    class _Failing:
        async def disable(self, *_args: Any, **_kwargs: Any) -> Any:
            raise error

        async def read_back_disable(self, *_args: Any, **_kwargs: Any) -> Any:
            return None

    env, _ = _disable_env(b16_audit, spec, store=_Failing())
    r = env.patch(M, {"status": "disabled"})
    assert r.status_code == status
    if status == 503:
        assert r.json()["code"] == "store_unavailable"


@pytest.mark.parametrize(("error", "status"), [(_Outage(111, "down"), 503), (ValueError(), 500)])
def test_a_session_row_that_cannot_be_revoked_is_503_for_an_outage_else_500(
    b16_audit: RecordingAuditSink, spec: Any, error: Exception, status: int
) -> None:
    """Recorded through B16 ahead, then the row fails: the trail over-reports, never under."""
    env, first, _, _ = _with_sessions(b16_audit, spec)

    async def failing(session_id: str, **_: Any) -> Any:
        raise error

    env.rows.revoke = failing  # type: ignore[method-assign]  # the row update fails
    r = env.client.delete(f"/users/{M}/sessions/{first.id}")
    assert r.status_code == status and env.closed == {}
    assert [c["action"] for c in b16_audit.calls] == ["auth.session_revoked"]
