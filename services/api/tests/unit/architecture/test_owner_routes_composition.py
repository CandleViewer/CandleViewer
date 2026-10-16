"""#2492/#2506 composition guard: the deployed `create_app()` (no injected seams) on the real
backend serves the role-change, invite and owner TOTP-reset routes (`SqlAlchemyUserRoleStore`) and
the self-scoped first-run checklist (`SqlAlchemyOnboardingStore`) through `SessionSnapshotResolver`:
every cell answers as `tests/contract/rbac/matrix.yaml` says and an authorised caller is never
refused with the fail-closed 501/503. Only the SQL edges of those real classes, the host socket
table and the session/step-up/invite services are faked (the RBAC pack's seams; no Postgres, no
network)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import SecretStr

import candleviewer.app as appmod
from candleviewer.api.onboarding_checklist import STEP_ORDER
from candleviewer.settings import Settings
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.onboarding_sqlalchemy import SqlAlchemyOnboardingStore
from candleviewer.storage.repositories.user_roles_sqlalchemy import SqlAlchemyUserRoleStore
from tests.contract.rbac import rbac_harness as rbac
from tests.csrf_helpers import csrf_headers

_ROWS = yaml.safe_load(rbac.MATRIX_PATH.read_text(encoding="utf-8"))["operations"]
#: Derived, not listed: every served (`executed`) operation gated by `users:write` alone.
OWNER_ROUTES = tuple(
    key
    for key, row in _ROWS.items()
    if row["state"] == "executed" and row["permissions"] == ["users:write"]
)
#: Derived, not listed (#2506): the self-scoped first-run checklist rows. The CI app cannot
#: execute them (no identity, no store on the fake backend), so the matrix parks them as
#: `not_executable`; this guard is where they run against the deployed composition.
ONBOARDING_ROUTES = tuple(
    key
    for key, row in _ROWS.items()
    if row["scope"] == "self" and key.split(" ", 1)[1].startswith("/onboarding/checklist")
)
_ONBOARDING_EDGES = (
    "is_dismissed",
    "dismiss",
    "has_confirmed_totp",
    "has_account_binding",
    "latest_binding_at",
)
#: The checklist steps whose owning work has not shipped on main: E27 key inventory (the
#: `api_key` probe never passes) and the flag-table steps (E39 limits, E27 demo sessions).
_UNSHIPPED_STEPS = frozenset({"api_key", "profile_limits", "demo_session"})
#: A sub-account binding older than the exchange's 48 h key-creation window.
_BOUND_LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


class _OnboardingRows:
    """The rows behind `SqlAlchemyOnboardingStore`'s SQL edges, in memory. Every call records
    `(edge, user_id)` so a test can prove which caller's rows the deployed router read."""

    def __init__(self) -> None:
        self.totp: set[uuid.UUID] = set()
        self.bound: dict[uuid.UUID, datetime] = {}
        self.dismissed: set[uuid.UUID] = set()
        self.calls: list[tuple[str, uuid.UUID]] = []

    async def is_dismissed(self, user_id: uuid.UUID) -> bool:
        self.calls.append(("is_dismissed", user_id))
        return user_id in self.dismissed

    async def dismiss(self, user_id: uuid.UUID) -> None:
        self.calls.append(("dismiss", user_id))
        self.dismissed.add(user_id)

    async def has_confirmed_totp(self, user_id: uuid.UUID) -> bool:
        self.calls.append(("has_confirmed_totp", user_id))
        return user_id in self.totp

    async def has_account_binding(self, user_id: uuid.UUID) -> bool:
        self.calls.append(("has_account_binding", user_id))
        return user_id in self.bound

    async def latest_binding_at(self, user_id: uuid.UUID) -> datetime | None:
        self.calls.append(("latest_binding_at", user_id))
        return self.bound.get(user_id)


def _loopback_only() -> list[str]:
    """The mesh self-check's host socket table (psutil / WSL portproxy), fixed: one loopback
    bind, so the checklist's `tailscale` probe is deterministic and reads nothing from the host."""
    return ["127.0.0.1:8000"]


def _delegate(target: Any, name: str) -> Callable[..., Any]:
    return lambda _self, *args: getattr(target, name)(*args)


@pytest.fixture(scope="module")
def deployed() -> Iterator[SimpleNamespace]:
    identity, users = rbac._Identity(rbac.load_contract()), rbac.UserStore()
    audit, onboarding = rbac._AuditSink(), _OnboardingRows()
    real = Settings(
        storage_backend="real",
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
    )
    with pytest.MonkeyPatch.context() as mp:
        for name in ("user", "session_info"):
            mp.setattr(SqlAlchemyIdentityProvider, name, _delegate(identity, name))
        for name in ("get_roles", "count_active_owners", "apply_roles"):
            mp.setattr(SqlAlchemyUserRoleStore, name, _delegate(users, name))
        for name in _ONBOARDING_EDGES:
            mp.setattr(SqlAlchemyOnboardingStore, name, _delegate(onboarding, name))
        mp.setattr(appmod, "real_socket_enumerator", lambda: _loopback_only)
        app = appmod.create_app(real)  # nothing injected: the deployed composition
        ctx = app.state.app_context
        ctx.audit._writer = audit
        ctx.auth._sessions, ctx.auth._step_up = rbac._Sessions(), rbac._StepUp()
        ctx.auth._invites = rbac._Invites()
        client = TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
        yield SimpleNamespace(client=client, users=users, audit=audit, onboarding=onboarding)


def _headers(client: TestClient, actor: str) -> dict[str, str]:
    codec = client.app.state.csrf_codec  # type: ignore[attr-defined]  # the FastAPI app
    if actor == "unauthenticated":
        return csrf_headers(codec)  # well-formed SR-041 pair, no session
    sid = uuid.uuid5(rbac.user_id_of(actor), "session")
    return {"Authorization": f"Bearer {rbac.token_of(actor)}", **csrf_headers(codec, sid)}


def _assert_matrix_cell(key: str, actor: str, resp: httpx.Response) -> None:
    """Branches on the cell's reviewed outcome class on purpose (allow / CSRF / 401-403)."""
    expected = _ROWS[key]["outcomes"][actor]
    if expected == "allow":  # authorised AND served by the wired backend
        assert resp.status_code not in (401, 403, 500, 501, 503), (key, resp.text)
    elif actor == "unauthenticated" and not key.startswith("GET "):  # SR-041 refuses first
        assert resp.status_code == 403 and resp.json()["code"] == "csrf_token_invalid"
    else:
        assert resp.status_code == int(expected), (key, actor, resp.text)


@pytest.mark.parametrize("actor", rbac.ACTORS)
@pytest.mark.parametrize("key", OWNER_ROUTES)
def test_deployed_app_owner_routes_answer_as_the_matrix_says(
    deployed: SimpleNamespace, key: str, actor: str
) -> None:
    method, path = key.split(" ", 1)
    body: dict[str, Any] | None = {} if method in ("POST", "PUT") else None
    resp = deployed.client.request(
        method, rbac.fill_path(path), json=body, headers=_headers(deployed.client, actor)
    )
    _assert_matrix_cell(key, actor, resp)


@pytest.mark.parametrize("actor", rbac.ACTORS)
@pytest.mark.parametrize("key", ONBOARDING_ROUTES)
def test_deployed_app_onboarding_checklist_answers_as_the_matrix_says(
    deployed: SimpleNamespace, key: str, actor: str
) -> None:
    """#2506. No body on purpose: the dismissal takes no client state (any body is the tamper
    refusal, 403), so the body-less request is what an authorised caller really sends."""
    method, path = key.split(" ", 1)
    resp = deployed.client.request(
        method, rbac.fill_path(path), headers=_headers(deployed.client, actor)
    )
    _assert_matrix_cell(key, actor, resp)
    if method == "GET" and _ROWS[key]["outcomes"][actor] == "allow":  # a real checklist body
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"complete", "dismissed", "items"}
        assert [item["key"] for item in body["items"]] == list(STEP_ORDER)


def test_deployed_app_role_change_reaches_the_store_and_is_audited(
    deployed: SimpleNamespace,
) -> None:
    viewer = rbac.user_id_of("viewer")
    headers = _headers(deployed.client, "owner")
    try:
        resp = deployed.client.put(
            f"/users/{viewer}/roles", json={"roles": ["manager"]}, headers=headers
        )
        assert resp.status_code == 200 and resp.json()["roles"] == ["manager"]
        assert deployed.users.roles[viewer] == frozenset({"manager"})
        assert {"roles.grant", "roles.revoke"} <= {r["action"] for r in deployed.audit.records}
    finally:
        deployed.users.roles.update(deployed.users.initial_roles)


def test_fake_backend_keeps_the_owner_routes_fail_closed() -> None:
    assert appmod.build_user_role_store(Settings()) is None
    client = TestClient(appmod.create_app(Settings()), client=("127.0.0.1", 50000))
    resp = client.get("/users/invites", headers={"Authorization": "Bearer tok-owner"})
    assert resp.status_code == 501


def _states(resp: httpx.Response) -> dict[str, str]:
    assert resp.status_code == 200, resp.text
    return {item["key"]: item["state"] for item in resp.json()["items"]}


def test_deployed_app_onboarding_reads_and_evaluates_dismissal_on_the_callers_own_rows(
    deployed: SimpleNamespace,
) -> None:
    """The owner's checklist and dismissal run on the owner's own rows in the real
    `SqlAlchemyOnboardingStore` (scope `self`, user id from the session). With every shipped
    step satisfied, the dismissal is evaluated against those rows and refused 409 with nothing
    written, because exactly the unshipped steps keep the card incomplete on main.
    Deviation (#2506): the 204 path that writes the dismissal row cannot be reached through the
    deployed router yet. The ticket that ships those steps turns this pin into that assertion."""
    owner, viewer, rows = rbac.user_id_of("owner"), rbac.user_id_of("viewer"), deployed.onboarding
    client = deployed.client
    rows.totp.add(owner)
    rows.bound[owner] = _BOUND_LONG_AGO
    try:
        mine = _states(client.get("/onboarding/checklist", headers=_headers(client, "owner")))
        theirs = _states(client.get("/onboarding/checklist", headers=_headers(client, "viewer")))
        assert {key for key, state in mine.items() if state != "ok"} == _UNSHIPPED_STEPS, mine
        assert theirs["totp"] == theirs["sub_account"] == "pending", theirs

        start = len(rows.calls)
        resp = client.post("/onboarding/checklist/dismiss", headers=_headers(client, "owner"))
        assert resp.status_code == 409 and resp.json()["title"] == "Conflict", resp.text
        edges = rows.calls[start:]
        assert {"has_confirmed_totp", "has_account_binding", "latest_binding_at"} <= {
            edge for edge, _ in edges
        }
        assert {user for _, user in edges} == {owner}  # only the caller's rows were read
        assert owner not in rows.dismissed and viewer not in rows.dismissed
    finally:
        rows.totp.discard(owner)
        rows.bound.pop(owner, None)


def test_fake_backend_keeps_the_onboarding_checklist_fail_closed() -> None:
    """The CI app has neither an identity provider nor an onboarding store, so the checklist
    answers 501 for every caller: the reason the matrix keeps both rows `not_executable`."""
    client = TestClient(appmod.create_app(Settings()), client=("127.0.0.1", 50000))
    resp = client.get("/onboarding/checklist", headers={"Authorization": "Bearer tok-owner"})
    assert resp.status_code == 501
    assert {_ROWS[key]["state"] for key in ONBOARDING_ROUTES} == {"not_executable"}


def test_owner_routes_derived_from_the_matrix_cover_the_issue_scope() -> None:
    """Guard for the derived parametrisation: it can never silently become empty."""
    named = {"PUT /users/{userId}/roles", "POST /users", "GET /users/invites"}  # by #2492
    assert named <= set(OWNER_ROUTES) and "POST /users/{userId}/mfa/reset" in OWNER_ROUTES


def test_onboarding_routes_derived_from_the_matrix_cover_the_issue_scope() -> None:
    """Same guard for the #2506 rows: never empty, and both checklist operations are in it."""
    named = {"GET /onboarding/checklist", "POST /onboarding/checklist/dismiss"}  # by #2506
    assert ONBOARDING_ROUTES and named <= set(ONBOARDING_ROUTES)
