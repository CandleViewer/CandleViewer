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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import candleviewer.app as appmod
from candleviewer.admin.user_disable import UserDisableService
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH
from candleviewer.audit.models import AuditPage, ExportResult, VerifyResult
from candleviewer.audit.query import VerifyPlan
from candleviewer.audit.verify_slot import VerifySlot
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.errors import (
    InviteNotFound,
    InviteRejected,
    SessionNotFound,
    StepUpRequired,
)
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import MfaMethodKind, SessionRecord, UserRecord, UserStatus
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from candleviewer.recorder.retention import PrunePlan, RunReport
from candleviewer.rules.manager import InMemoryRuleStore
from candleviewer.storage.repositories.account_access import (
    AccessGrant,
    AccessUserNotFoundError,
)
from candleviewer.storage.repositories.alerts import Page
from candleviewer.storage.repositories.user_lifecycle import UserStatusChange
from candleviewer.user_cascade_wiring import NoOrderCounter
from tests.csrf_helpers import csrf_headers

MATRIX_PATH = Path(__file__).with_name("matrix.yaml")
#: A stored-hash placeholder for seeded users; nothing in the pack ever verifies a password.
INERT_DIGEST = "unused"
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
#: `23-ws-protocol.md` §2.5: put in `CV_ALLOWED_ORIGINS` and sent by the client on every request,
#: so a WS upgrade passes the Origin check (REST outcomes are unchanged by an allowed Origin).
WS_ORIGIN = "http://testserver"


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


def seed_machine(app: FastAPI, row: dict[str, Any], actor: str) -> None:
    """Before a `machines.{kind}` cell: an emptied registry holding only the row's sample
    entity, on account A (`granted_accounts`) or as the caller's own (`self`), as in 23 §6.4."""
    from candleviewer.ws.machines import MachineEntity
    from candleviewer.ws.topics import EntityScope

    registry = app.state.ws_registry.services.machines
    registry._entries.clear()
    kind, _, ident = row["sample"].split(".")[1].partition(":")
    scope = EntityScope()
    if row["scope"] == "granted_accounts":
        scope = EntityScope(accounts=frozenset({GRANTED}))
    elif row["scope"] == "self":
        scope = EntityScope(user=_USER_IDS.get(actor))
    registry.publish(MachineEntity(kind, ident or None, scope), {"state": "seeded"})


class _Identity:
    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec

    def _actor(self, uid: str) -> str:
        return next(a for a, u in _USER_IDS.items() if str(u) == uid)

    async def user(self, user_id: str) -> dict[str, Any]:
        a = self._actor(user_id)
        return {
            "id": user_id,
            "username": a,
            "email": f"{a}@example.com",
            "roles": [ROLE_OF[a]],
            "status": "active",
        }

    async def session_info(self, user_id: str) -> dict[str, Any]:
        a = self._actor(user_id)
        return {
            "permissions": sorted(actor_permissions(a, self._spec)),
            "account_scope": [str(g) for g in actor_grants(a)],
        }

    async def accounts(self, user_id: str) -> list[dict[str, Any]]:
        """`GET /me` accounts: an owner reaches every account, a manager its grants (`trade`)."""
        a = self._actor(user_id)
        ids = (GRANTED, FOREIGN) if ROLE_OF[a] == "owner" else actor_grants(a)
        return [
            {"exchange_account_id": str(i), "label": f"acct-{i.hex[-1]}", "environment": "demo",
             "mode": "trade"}
            for i in ids
        ]  # fmt: skip


class _Sessions:
    async def list_sessions(self, user_id: str, *, current_session_id: str) -> list[Any]:
        return []

    async def revoke(self, session_id: str, *, reason: str) -> None:
        return None

    async def peek_access_token(self, token: str) -> Any:  # SR-041 sid binding (#2090)
        try:
            return await self.authenticate_access_token(token)
        except SessionNotFound:
            return None

    async def require_active(self, session_id: str, *, allow_locked: bool = False) -> Any:
        """`GET /auth/session` re-reads the session it identified (#2300, #2911)."""
        actor = next(a for a, u in _USER_IDS.items() if str(uuid.uuid5(u, "session")) == session_id)
        return await self.authenticate_access_token(token_of(actor))

    def now(self) -> datetime:  # the session routes judge deadlines by it (#2300)
        return datetime.now(UTC)

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


class _Users:
    """The user store's `find_by_id` over the seeded actors: each has `mfa_required` and a
    confirmed TOTP method, so the enrolment-only guard classifies every actor's session as a
    full one and the pack runs with it active (#2295)."""

    async def find_by_id(self, user_id: str) -> UserRecord | None:
        actor = next((a for a, u in _USER_IDS.items() if str(u) == user_id), None)
        if actor is None:
            return None
        return UserRecord(
            id=_USER_IDS[actor],
            username=actor,
            email=f"{actor}@example.test",
            password_hash=INERT_DIGEST,
            password_algo_params={},
            status=UserStatus.ACTIVE,
            mfa_required=True,
            failed_login_count=0,
            locked_until=None,
            mfa_methods=(MfaMethodKind.TOTP,),
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

    async def record_pending(self, session_id: str, action_class: str) -> StepUpChallenge:
        return StepUpChallenge(uuid.uuid4(), action_class, datetime.now(UTC) + CHALLENGE_WINDOW)

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

    async def reissue(self, user_id: uuid.UUID, *, invited_by: uuid.UUID, audit: Any) -> Any:
        raise InviteNotFound(str(user_id))

    async def revoke(self, user_id: uuid.UUID, *, audit: Any) -> None:
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

    def __init__(self) -> None:
        self.verify_slot = VerifySlot()

    async def query(self, **_kw: Any) -> AuditPage:
        return AuditPage(items=[], chain_verified=True)

    async def plan_verify(self, **_kw: Any) -> VerifyPlan:
        return VerifyPlan(None, None, 0)  # an empty log

    async def run_verify(self, plan: VerifyPlan, **_kw: Any) -> VerifyResult:
        return VerifyResult(
            verified=True,
            entries_checked=0,
            first_bad_id=None,
            checked_at=datetime.now(UTC),
            from_id=None,
            to_id=None,
            anchor_hash="0" * 64,
            last_hash=None,
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

    async def apply_roles(
        self,
        user_id: uuid.UUID,
        roles: frozenset[str],
        *,
        actor: uuid.UUID,
        audit: Callable[[frozenset[str]], Awaitable[None]],
    ) -> bool:
        await audit(self.roles[user_id])  # write-ahead, as the Postgres store does (C-2.9)
        self.roles[user_id] = roles
        return True


class AccessStore:
    """`AccountAccessStore` over the seeded actors (in-memory, no grants until a test gives
    some). Any other user id does not exist. `calls` records each user whose grants were read."""

    def __init__(self) -> None:
        self.grants: dict[uuid.UUID, list[AccessGrant]] = {u: [] for u in _USER_IDS.values()}
        self.calls: list[uuid.UUID] = []

    async def list_grants(self, user_id: uuid.UUID) -> list[AccessGrant]:
        self.calls.append(user_id)
        if user_id not in self.grants:
            raise AccessUserNotFoundError(str(user_id))
        return list(self.grants[user_id])

    async def replace_grants(self, user_id: uuid.UUID, grants: Any, **_kw: Any) -> Any:
        raise AssertionError("no matrix cell writes grants: its empty body is refused (400) first")


class LifecycleStore:
    """The S3 disable store's seam: it finds no user, so an authorised disable is a 404."""

    async def disable(
        self, user_id: uuid.UUID, *, actor: uuid.UUID, now: datetime, audit: Any
    ) -> UserStatusChange | None:
        return None

    async def read_back_disable(
        self, user_id: uuid.UUID, *, now: datetime
    ) -> tuple[uuid.UUID, ...] | None:
        return None  # never reached: `disable` finds no user, so no commit raises (#3445)


def user_disable_service(audit: Any) -> UserDisableService:
    """The real service (its guards are the cells' subject) over a store that finds no user."""
    unreached: Any = object()
    ports = (
        *("sessions", "session_rows", "chart", "publish_revocation", "close_user_sockets"),
        *("invites", "rules", "scope"),
    )
    return UserDisableService(
        LifecycleStore(),
        audit,
        positions=appmod._NoPositionStore(),
        orders=NoOrderCounter(),
        **dict.fromkeys(ports, unreached),
    )


class _AuditSink:
    """Stand-in for the started `AuditWriter`; records every emitted audit action."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.records.append({"action": action, **kw})


class _PurgeBackend:
    """`PurgeBackend` stand-in for `POST /admin/recorder/purge` (E16-T06, #2575).

    `create_app` builds the real `RetentionManager` only on the `real` storage backend, so without
    this seam the CI app answers 503 "purge backend is not wired" before the step-up gate and the
    pack could not observe the handler's gate order. It never plans, runs or deletes anything:
    every call is recorded, `plan_purge` / `run` fail the request (an unhandled 5xx, so a red
    cell), and the owner-only / step-up tests assert `calls` stayed empty."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def is_pinned(self, symbol: str) -> bool:
        self.calls.append("is_pinned")
        return True  # fail closed: nothing may be purged through this stand-in

    async def plan_purge(self, symbol: str, before_us: int, *, include_pinned: bool) -> PrunePlan:
        self.calls.append("plan_purge")
        raise AssertionError("the RBAC pack must never plan a purge")

    async def run(self, plan: PrunePlan, dry_run: bool) -> RunReport:
        self.calls.append("run")
        raise AssertionError("the RBAC pack must never run a purge")


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
    access: AccessStore = field(default_factory=AccessStore)
    rule_store: InMemoryRuleStore = field(default_factory=InMemoryRuleStore)
    purge_backend: _PurgeBackend = field(default_factory=_PurgeBackend)
    grants: dict[uuid.UUID, tuple[uuid.UUID, ...]] = field(default_factory=dict)


def audit_adapter(sink: _AuditSink) -> Any:
    async def _audit(action: str, payload: dict[str, Any]) -> None:
        await sink.emit(action, **{k: v for k, v in payload.items() if k != "action"})

    return _audit


def world_env(bars_state_root: Path | None) -> dict[str, str]:
    """The environment `build_world` sets through its `MonkeyPatch` (`create_app()` reads
    `get_settings()`). `WORLD_ENV` holds its names: the leak guard checks each one is restored.
    Without a `bars_state_root` the world keeps bars off, as it was before #399 slice E."""
    env = {"CV_ALLOWED_ORIGINS": WS_ORIGIN}
    if bars_state_root is not None:
        # `bars.*` answers `unknown_topic` while the feature is off (23 §6.1, #399 slice E), but
        # the matrix asserts its authorization outcome, so the pack runs with the feature on.
        # Remove this entry with the flag (#399).
        env["CV_BARS_ENABLED"] = "true"
        # `register()` loads (and, on a bad blob, deletes) builder state under this root, whose
        # default is the production `/data/bars/state`, so bars on always comes with a tmp root.
        env["CV_BARS_STATE_ROOT"] = str(bars_state_root)
    return env


WORLD_ENV = tuple(world_env(Path()))  # the names only


def build_world(mp: pytest.MonkeyPatch, *, bars_state_root: Path | None = None) -> World:
    """Build the app. With a `bars_state_root` the world runs with bars on and keeps their builder
    state there; without one bars stay off. The attribute patches and `world_env` are applied
    through `mp` and live as long as the caller's context (the alert repository is resolved per
    request, so the patch must outlive `create_app`). The caller undoes `mp` in a `finally`: a
    failure in here, after the first patch, must not leave the process patched."""
    spec = load_contract()
    resolver = _Resolver(spec)
    users = UserStore()
    access = AccessStore()
    audit = _AuditSink()

    async def snapshot_loader(uid: uuid.UUID) -> PrincipalSnapshot:
        actor = next(a for a, u in _USER_IDS.items() if u == uid)
        return resolver.snapshot(actor)

    async def ws_authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
        actor = _TOKENS.get(token)
        if actor is None:
            raise PermissionError("unknown token")
        return f"ws-{actor}", _USER_IDS[actor], datetime(2100, 1, 1, tzinfo=UTC)  # far future

    # The per-user connect rate (#2558) is not under test here, and this world lives for a whole
    # module on the real clock. `test_scope_and_ws.py` opens one socket per (topic family, actor)
    # cell plus a revocation case: `manager_with_grant` spent 19 of the default 20 first auths a
    # minute when the limit was added. The next topic family would be refused with
    # `client_rate_limited` and read as an RBAC regression. The limit itself is covered by
    # `tests/unit/ws/test_connect_rate.py`.
    mp.setenv("CV_WS_MAX_AUTHS_PER_USER_PER_MIN", "600")  # create_app() reads get_settings()
    mp.setattr(appmod, "build_identity_provider", lambda _settings: _Identity(spec))
    mp.setattr(appmod, "SqlAlchemyAlertRepository", lambda _pg: _AlertRepo())
    # E16-T06: the real retention manager exists only on the `real` storage backend; the purge
    # route is mounted either way, so give it the call-recording stand-in (never plans/deletes).
    purge_backend = _PurgeBackend()
    mp.setattr(appmod, "build_retention_manager", lambda *_a, **_k: purge_backend)
    for name, value in world_env(bars_state_root).items():
        mp.setenv(name, value)
    app = appmod.create_app(
        principal_resolver=resolver,
        user_role_store=users,
        account_access_store=access,
        user_disable=user_disable_service(audit),
        snapshot_loader=snapshot_loader,
        ws_authenticate=ws_authenticate,
    )
    _CSRF_CODEC[:] = [app.state.csrf_codec]
    ctx = app.state.app_context
    ctx.audit._writer = audit
    ctx.audit._query = _AuditQuery()  # the lifespan is not started; same seam tests/unit/ws uses
    ctx.auth._sessions = _Sessions()
    ctx.auth._repository = _Users()  # the enrolment-only guard classifies every session
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
    client = TestClient(
        app,
        client=("127.0.0.1", 50000),
        raise_server_exceptions=False,
        headers={"origin": WS_ORIGIN},
    )
    return World(
        app, client, audit, spec, resolver,
        scope_events=scope_events, step_up=step_up, users=users, access=access, rule_store=store,
        purge_backend=purge_backend,
    )  # fmt: skip


#: The app's SR-041 codec, set by `build_world` (one app per world).
_CSRF_CODEC: list[CsrfCodec] = []


def bearer(actor: str) -> dict[str, str]:
    """Bearer + the SR-041 header/cookie pair a browser would send for that session (#2090).
    The unauthenticated caller still sends a well-formed token so the route's own 401 is
    observed, not the CSRF refusal (that is covered by tests/security/auth/test_csrf_*)."""
    sid = None if actor == "unauthenticated" else uuid.uuid5(_USER_IDS[actor], "session")
    csrf = csrf_headers(_CSRF_CODEC[-1], sid) if _CSRF_CODEC else {}
    if actor == "unauthenticated":
        return csrf
    return {"Authorization": f"Bearer tok-{actor}", **csrf}


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
