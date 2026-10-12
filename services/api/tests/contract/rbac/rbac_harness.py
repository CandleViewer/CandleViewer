"""Shared harness for the RBAC allow/deny matrix pack (E09-Q03, SR-018).

Builds the REAL `create_app()` with a session-shaped fake identity layer (no Postgres, no network,
C-13.5). Actors are seeded once per process from the contract (`22-api-openapi.yaml`
`x-permissions`); every request authenticates with its own bearer token so no cell can inherit
state from another.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import candleviewer.app as appmod
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH
from candleviewer.audit.models import AuditPage, ExportResult, VerifyResult
from candleviewer.auth.errors import (
    InviteNotFound,
    InviteRejected,
    SessionNotFound,
    StepUpRequired,
)
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.rules.manager import InMemoryRuleStore
from candleviewer.storage.repositories.alerts import Page

MATRIX_PATH = Path(__file__).with_name("matrix.yaml")
ACTORS = ("owner", "manager_with_grant", "manager_without_grant", "viewer", "unauthenticated")
ROLE_OF = {
    "owner": "owner",
    "manager_with_grant": "manager",
    "manager_without_grant": "manager",
    "viewer": "viewer",
}
GRANTED = uuid.UUID("00000000-0000-4000-8000-00000000000a")  # the one account the grant covers
FOREIGN = uuid.UUID("00000000-0000-4000-8000-00000000000b")  # an account nobody here is granted
_USER_IDS = {a: uuid.uuid5(uuid.NAMESPACE_URL, f"cv-rbac-matrix/{a}") for a in ACTORS[:4]}
_TOKENS = {f"tok-{a}": a for a in ACTORS[:4]}
#: operations the real app serves that are intentionally outside the contract (deny_by_default).
NON_CONTRACT = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json", "/metrics"})
PUBLIC_OPERATIONAL = NON_CONTRACT | {"/healthz", "/readyz"}
HTTP = ("get", "put", "post", "delete", "patch")


def load_contract() -> dict[str, Any]:
    with OPENAPI_SPEC_PATH.open(encoding="utf-8") as fh:
        spec: dict[str, Any] = yaml.safe_load(fh)
    return spec


def role_permissions(spec: dict[str, Any]) -> dict[str, frozenset[str]]:
    """Permission set per role from the contract's `x-permissions` (owner holds every code)."""
    allcodes = frozenset(p.value for p in Permission)
    out = {r: frozenset(v) for r, v in spec["x-permissions"].items()}
    out["owner"] = allcodes
    return out


def actor_permissions(actor: str, spec: dict[str, Any]) -> frozenset[str]:
    return role_permissions(spec)[ROLE_OF[actor]]


def actor_grants(actor: str) -> tuple[uuid.UUID, ...]:
    return (GRANTED,) if actor == "manager_with_grant" else ()


def user_id_of(actor: str) -> uuid.UUID:
    return _USER_IDS[actor]


def token_of(actor: str) -> str:
    return f"tok-{actor}"


class _Identity:
    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec

    def _actor(self, uid: str) -> str:
        return next(a for a, u in _USER_IDS.items() if str(u) == uid)

    async def user(self, user_id: str) -> dict[str, Any]:
        a = self._actor(user_id)
        return {"id": user_id, "username": a, "roles": [ROLE_OF[a]], "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        a = self._actor(user_id)
        return {
            "permissions": sorted(actor_permissions(a, self._spec)),
            "account_scope": [str(g) for g in actor_grants(a)],
        }


class _Sessions:
    async def list_sessions(self, user_id: str, *, current_session_id: str) -> list[Any]:
        return []

    async def revoke(self, session_id: str, *, reason: str) -> None:
        return None

    async def authenticate_access_token(
        self, token: str, *, touch: bool = False, allow_locked: bool = False
    ) -> Any:
        actor = _TOKENS.get(token)
        if actor is None:
            raise SessionNotFound("unknown token")
        now = datetime.now(UTC)
        return SessionRecord(
            id=uuid.uuid5(_USER_IDS[actor], "session"),
            user_id=_USER_IDS[actor],
            refresh_token_hash="x",  # noqa: S106 - inert placeholder, not a credential
            access_token_jti=None,
            issued_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
            revoked_at=None,
            revoked_reason=None,
            ip=None,
            user_agent=None,
            device_label=None,
            is_electron=False,
            mfa_satisfied_at=now,
        )


class _Resolver:
    """`SnapshotResolver`: bearer -> `PrincipalSnapshot` from the actor's contract permissions."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec
        #: actors whose account grants have been withdrawn mid-run (SR-050 / revocation tests).
        self.revoked: set[str] = set()

    def resolve(self, request: Any) -> PrincipalSnapshot | None:
        token = request.headers.get("authorization", "").partition(" ")[2].strip()
        actor = _TOKENS.get(token)
        return None if actor is None else self.snapshot(actor)

    def snapshot(self, actor: str) -> PrincipalSnapshot:
        perms = frozenset(Permission(p) for p in actor_permissions(actor, self._spec))
        grants = tuple(
            AccountGrant(g, True, True, False)
            for g in (() if actor in self.revoked else actor_grants(actor))
        )
        return PrincipalSnapshot(_USER_IDS[actor], frozenset({ROLE_OF[actor]}), perms, grants)


class _StepUp:
    """Stand-in for the DB-backed `StepUpService` (same seam as `tests/unit/ws`). `elevated`
    models a completed step-up on the caller's session (SR-025)."""

    def __init__(self) -> None:
        self.elevated = True

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        if not self.elevated:
            raise StepUpRequired(action_class)

    async def record_pending(self, session_id: str, action_class: str) -> None:
        return None

    async def assert_writable(self, session_id: str) -> None:
        return None


class _Invites:
    """Invite service seam. Every owner operation reports "no such invite" (4xx) and creates
    nothing, so an authorised call is observable (non-401/403) while mutating no state."""

    def is_blocked(self, _ip: str) -> bool:
        return False

    def now(self) -> Any:
        return datetime.now(UTC)

    async def list_pending(self) -> tuple[Any, ...]:
        return ()

    async def reissue(self, user_id: uuid.UUID, *, invited_by: uuid.UUID) -> Any:
        raise InviteNotFound(str(user_id))

    async def revoke(self, user_id: uuid.UUID) -> None:
        raise InviteNotFound(str(user_id))

    async def inspect(self, token: str, *, source_ip: str) -> Any:
        raise InviteRejected("unknown")

    async def begin_redemption(self, *args: Any, **kwargs: Any) -> Any:
        raise InviteRejected("unknown")

    async def complete_redemption(self, *args: Any, **kwargs: Any) -> Any:
        raise InviteRejected("unknown")


class _AlertRepo:
    """Empty alert store: reads find nothing, deletes remove nothing (no SQL, no mutation)."""

    async def list_page(self, owner: str, **_kw: Any) -> Page[Any]:
        return Page([], None)

    async def get(self, alert_id: str) -> None:
        return None

    async def soft_delete(self, alert_id: str) -> bool:
        return False

    async def set_enabled(self, alert_id: str, enabled: bool) -> None:
        return None


class _AuditQuery:
    """`AuditQueryService` stand-in returning empty, valid results (no DB)."""

    async def query(self, **_kw: Any) -> AuditPage:
        return AuditPage(items=[], chain_verified=True)

    async def verify(self, **_kw: Any) -> VerifyResult:
        return VerifyResult(
            verified=True, entries_checked=0, first_bad_id=None, checked_at=datetime.now(UTC)
        )

    async def schedule_export(self, **_kw: Any) -> ExportResult:
        return ExportResult(job_id=uuid.UUID(int=1))


class UserStore:
    """`UserRoleStore` over the seeded actors (in-memory; `apply_roles` records the change)."""

    def __init__(self) -> None:
        self.initial_roles = {u: frozenset({ROLE_OF[a]}) for a, u in _USER_IDS.items()}
        self.roles = dict(self.initial_roles)

    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None:
        return self.roles.get(user_id)

    async def count_active_owners(self) -> int:
        return sum("owner" in r for r in self.roles.values())

    async def apply_roles(self, user_id: uuid.UUID, roles: frozenset[str]) -> bool:
        self.roles[user_id] = roles
        return True


class _AuditSink:
    """Stand-in for the started `AuditWriter`; records every emitted audit action."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.records.append({"action": action, **kw})


class _ScopeSource:
    """`ScopeSource` over the seeded actors: grants and permissions come from the contract."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec

    def _actor(self, owner: uuid.UUID) -> str:
        return next(a for a, u in _USER_IDS.items() if u == owner)

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        if ROLE_OF[self._actor(owner)] == "owner":
            return [(GRANTED, True, False), (FOREIGN, True, False)]
        return [(g, True, False) for g in actor_grants(self._actor(owner))]

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        return actor_permissions(self._actor(owner), self._spec)


@dataclass
class World:
    app: FastAPI
    client: TestClient
    audit: _AuditSink
    spec: dict[str, Any]
    resolver: _Resolver
    scope_events: list[str] = field(default_factory=list)
    step_up: _StepUp = field(default_factory=_StepUp)
    users: UserStore = field(default_factory=UserStore)
    rule_store: InMemoryRuleStore = field(default_factory=InMemoryRuleStore)
    grants: dict[uuid.UUID, tuple[uuid.UUID, ...]] = field(default_factory=dict)


def audit_adapter(sink: _AuditSink) -> Any:
    async def _audit(action: str, payload: dict[str, Any]) -> None:
        await sink.emit(action, **{k: v for k, v in payload.items() if k != "action"})

    return _audit


def build_world(mp: pytest.MonkeyPatch) -> World:
    """Build the app. Patches are applied through `mp` and live as long as the caller's context
    (the alert repository is resolved per request, so the patch must outlive `create_app`)."""
    spec = load_contract()
    resolver = _Resolver(spec)
    users = UserStore()

    async def snapshot_loader(uid: uuid.UUID) -> PrincipalSnapshot:
        actor = next(a for a, u in _USER_IDS.items() if u == uid)
        return resolver.snapshot(actor)

    async def ws_authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
        actor = _TOKENS.get(token)
        if actor is None:
            raise PermissionError("unknown token")
        return f"ws-{actor}", _USER_IDS[actor], datetime.now(UTC) + timedelta(hours=1)

    mp.setattr(appmod, "build_identity_provider", lambda _settings: _Identity(spec))
    mp.setattr(appmod, "SqlAlchemyAlertRepository", lambda _pg: _AlertRepo())
    app = appmod.create_app(
        principal_resolver=resolver,
        user_role_store=users,
        snapshot_loader=snapshot_loader,
        ws_authenticate=ws_authenticate,
    )
    ctx = app.state.app_context
    audit = _AuditSink()
    ctx.audit._writer = audit
    ctx.audit._query = _AuditQuery()  # the lifespan is not started; same seam tests/unit/ws uses
    ctx.auth._sessions = _Sessions()
    step_up = _StepUp()
    ctx.auth._step_up = step_up
    ctx.auth._invites = _Invites()
    # Rules: a real manager over an in-memory store plus a real scope resolver (no Postgres).
    scope_events: list[str] = []

    async def _scope_sink(event: str, _data: dict[str, str]) -> None:
        scope_events.append(event)

    store = InMemoryRuleStore()
    ctx.rules.bind(store=store, audit=audit_adapter(audit))
    ctx.rules.wire_scope(_ScopeSource(spec), "demo", _scope_sink)
    asyncio.run(ctx.rules.start(ctx))
    client = TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
    return World(
        app, client, audit, spec, resolver,
        scope_events=scope_events, step_up=step_up, users=users, rule_store=store,
    )  # fmt: skip


def bearer(actor: str) -> dict[str, str]:
    return {} if actor == "unauthenticated" else {"Authorization": f"Bearer tok-{actor}"}


def fill_path(path: str, params: dict[str, str] | None = None) -> str:
    """Substitute `{param}` placeholders with fixed well-formed values (deterministic)."""
    params = params or {}
    return re.sub(
        r"\{([^}]+)\}",
        lambda m: params.get(m.group(1), "00000000-0000-4000-8000-0000000000ff"),
        path,
    )


#: (group -> seconds per executed cell); printed by the conftest summary hook.
TIMINGS: dict[str, list[float]] = defaultdict(list)
#: "<operation>|<actor>" -> "pass" / "xfail"; rendered into the HTML artefact.
CELLS: dict[str, str] = {}


def record_cell(group: str, key: str, actor: str, outcome: str, started: float) -> None:
    TIMINGS[group].append(time.perf_counter() - started)
    CELLS[f"{key}|{actor}"] = outcome
