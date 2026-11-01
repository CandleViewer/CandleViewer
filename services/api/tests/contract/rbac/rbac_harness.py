"""Shared harness for the RBAC allow/deny matrix pack (E09-Q03, SR-018).

Builds the REAL `create_app()` with a session-shaped fake identity layer (no Postgres, no network,
C-13.5). Actors are seeded once per process from the contract (`22-api-openapi.yaml`
`x-permissions`); every request authenticates with its own bearer token so no cell can inherit
state from another.
"""

from __future__ import annotations

import asyncio
import atexit
import re
import shutil
import tempfile
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
from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.downloads import BackupDownloads
from candleviewer.admin.backups.links import DownloadLinks
from candleviewer.admin.user_disable import UserDisableService
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH
from candleviewer.api.view_as_subject import view_as_subject
from candleviewer.audit.models import (
    AuditEntry,
    AuditOutcome,
    AuditPage,
    AuditPageMeta,
    ExportResult,
    Severity,
    VerifyResult,
)
from candleviewer.audit.query import VerifyPlan
from candleviewer.audit.verify_slot import VerifySlot
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.errors import (
    InviteNotFound,
    InviteRejected,
    MfaEnrollmentNotFound,
    SessionNotFound,
    StepUpRequired,
)
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import (
    MfaEnrollResult,
    MfaMethodKind,
    SessionRecord,
    UserRecord,
    UserStatus,
)
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from candleviewer.auth.view_as import ViewAsBinding, ViewAsState
from candleviewer.recorder.retention import PrunePlan, RunReport
from candleviewer.rules.manager import InMemoryRuleStore
from candleviewer.storage.errors import ActorNotAuthorised
from candleviewer.storage.repositories.account_access import (
    AccessGrant,
    AccessUserNotFoundError,
)
from candleviewer.storage.repositories.alerts import Page
from candleviewer.storage.repositories.backups import BackupRow
from candleviewer.storage.repositories.user_lifecycle import UserStatusChange
from candleviewer.user_cascade_wiring import NoOrderCounter
from candleviewer.ws.lifecycle import ConnectRateLimiter
from tests.csrf_helpers import csrf_headers
from tests.unit.admin._backup_fakes import row
from tests.unit.admin._link_fakes import Reader
from tests.unit.api._purge_anchors import InMemoryPurgeAnchors
from tests.unit.storage.fakes_user_settings import FakeUserSettings

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
#: E27-X03 (#902): an account id no store and no grant knows, beside A and B (`account_scope`).
ABSENT = uuid.UUID("00000000-0000-4000-8000-00000000000c")
SCOPE_KEY_ID = "00000000-0000-4000-8000-0000000000dd"  # the `{keyId}` of the account-scope cells
SCOPE_PROFILE_ID = "00000000-0000-4000-8000-0000000000de"  # and their `{profileId}`
#: The three roles of the `account_scope` cells; its viewer holds a grant on A (`_Resolver.extra`).
SCOPE_ACTOR = {"owner": "owner", "manager": "manager_with_grant", "viewer": "viewer"}
_USER_IDS = {a: uuid.uuid5(uuid.NAMESPACE_URL, f"cv-rbac-matrix/{a}") for a in ACTORS[:4]}
_TOKENS = {f"tok-{a}": a for a in ACTORS[:4]}
#: #3085 S9: the users the Owner views as, every non-Owner actor (an Owner target is refused at
#: the start). `tok-owner-as-<target>` names the Owner's session holding a live context on it.
VIEW_TARGETS = ("manager_with_grant", "manager_without_grant", "viewer")
_VIEW_TOKENS = {f"tok-owner-as-{t}": t for t in VIEW_TARGETS}
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


def session_id_of(actor: str, *, viewing: str | None = None) -> uuid.UUID:
    """The session an actor's token names; with *viewing*, the Owner's session viewing as it."""
    name = "session" if viewing is None else f"view-as/{viewing}"
    return uuid.uuid5(_USER_IDS[actor], name)


def session_record(token: str) -> SessionRecord:
    """The session row a token names. A `tok-owner-as-<target>` session is the Owner's, holding a
    context on <target> that started a minute ago and so is live for 29 more (#3085 S9)."""
    target = _VIEW_TOKENS.get(token)
    actor = "owner" if target is not None else _TOKENS.get(token)
    if actor is None:
        raise SessionNotFound("unknown token")
    now = datetime.now(UTC)
    view_as = None
    if target is not None:
        context_id = uuid.uuid5(_USER_IDS[target], "view-as")
        view_as = ViewAsState.start(context_id, _USER_IDS[target], now=now - timedelta(minutes=1))
    return SessionRecord(
        id=session_id_of(actor, viewing=target),
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
        view_as=view_as,
    )


def seed_payload(kind: str) -> dict[str, Any]:
    """A 23 §15.10 payload of an entity of `kind` (`algo`: B4's chart), as the registry records."""
    chart = "oco" if kind == "algo" else kind
    return {"machine_kind": chart, "state": "seeded", "tags": [], "degraded": False,
            "machine_hash": "0" * 64, "environment": "demo", "updated_at_ms": 1}  # fmt: skip


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
    assert registry.publish(MachineEntity(kind, ident or None, scope), seed_payload(kind))


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

    async def names(self, user_id: str) -> tuple[str, str | None]:
        """`SqlAlchemyIdentityProvider.names` (#3085 S12's view-as read): the actor's username
        and no display name."""
        return self._actor(user_id), None

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
        tokens = [*_TOKENS, *_VIEW_TOKENS]
        token = next(t for t in tokens if str(session_record(t).id) == session_id)
        return await self.authenticate_access_token(token)

    async def touch(self, session_id: str) -> Any:  # `POST /auth/session/extend` (#2300)
        return await self.require_active(session_id)

    async def lock(
        self, session_id: str, *, write_ahead: Any, audit_timeout_s: float
    ) -> tuple[Any, bool]:
        """`POST /auth/lock` (#4743): its record written ahead, then the row as locked."""
        row = await self.require_active(session_id)
        await write_ahead(row)
        return row.model_copy(update={"locked_at": self.now()}), True

    def now(self) -> datetime:  # the session routes judge deadlines by it (#2300)
        return datetime.now(UTC)

    async def authenticate_access_token(
        self, token: str, *, touch: bool = False, allow_locked: bool = False
    ) -> Any:
        return session_record(token)


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


class _Login:
    """`LoginService` seam: wired, so the enrolment routes reach their handler (#2295). The
    pack's sign-in rows post an empty body, which is refused before any call here."""

    async def login(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the RBAC pack never signs in")


class _Mfa:
    """`MfaService` seam for enrol and confirm (#2295). Every seeded actor has a confirmed
    method, so both routes answer 409 before any call here; only the enrolment-only owner of
    `test_enrolment_only_matrix.py` gets this far. It stores nothing: an enrolment returns a
    method id and no secret, and every confirmation is refused as not found (422)."""

    async def enroll(self, user_id: str, *_args: Any, **_kwargs: Any) -> MfaEnrollResult:
        method_id = uuid.uuid5(uuid.UUID(user_id), "enrol")
        return MfaEnrollResult(method_id=method_id, method=MfaMethodKind.TOTP)

    async def check_enrollment(self, *_args: Any, **_kwargs: Any) -> int:
        raise MfaEnrollmentNotFound("the RBAC pack stores no pending method")


class _Resolver:
    """`SnapshotResolver`: bearer -> `PrincipalSnapshot` from the actor's contract permissions."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec
        #: actors whose account grants have been withdrawn mid-run (SR-050 / revocation tests).
        self.revoked: set[str] = set()
        #: grants added to an actor's own for one test (E27-X03: the viewer granted A).
        self.extra: dict[str, tuple[uuid.UUID, ...]] = {}

    def resolve(self, request: Any) -> PrincipalSnapshot | None:
        """As the deployed resolver (`SessionSnapshotResolver`): the session's subject, the
        target on a viewing session's live read (#3085 S8); an unstamped context raises."""
        token = request.headers.get("authorization", "").partition(" ")[2].strip()
        try:
            record = session_record(token)
        except SessionNotFound:
            return None
        subject = view_as_subject(request, record)
        return self.snapshot(next(a for a, u in _USER_IDS.items() if u == subject))

    def snapshot(self, actor: str) -> PrincipalSnapshot:
        perms = frozenset(Permission(p) for p in actor_permissions(actor, self._spec))
        held = () if actor in self.revoked else actor_grants(actor) + self.extra.get(actor, ())
        grants = tuple(AccountGrant(g, True, True, False) for g in held)
        return PrincipalSnapshot(_USER_IDS[actor], frozenset({ROLE_OF[actor]}), perms, grants)


class _StepUp:
    """Stand-in for the DB-backed `StepUpService` (same seam as `tests/unit/ws`). `elevated`
    models a completed step-up on the caller's session (SR-025), a window or a one-shot grant.
    `classes`, when set, elevates only those action classes, as the real service's per-class
    grace does (`tests/unit/auth/test_step_up.py`, E27-X03 #902)."""

    def __init__(self) -> None:
        self.elevated = True
        self.classes: frozenset[str] | None = None

    def _held(self, action_class: str) -> bool:
        return self.elevated and (self.classes is None or action_class in self.classes)

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        if not self._held(action_class):
            raise StepUpRequired(action_class)

    async def record_pending(
        self, session_id: str, action_class: str, *, fingerprint: str | None = None
    ) -> StepUpChallenge:
        expires = datetime.now(UTC) + CHALLENGE_WINDOW
        return StepUpChallenge(uuid.uuid4(), action_class, expires, fingerprint)

    async def consume_single_use(
        self, session_id: str, action_class: str, *, fingerprint: str
    ) -> StepUpChallenge:
        if not self._held(action_class):
            raise StepUpRequired(action_class)
        return await self.record_pending(session_id, action_class, fingerprint=fingerprint)

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

    async def revoke(self, user_id: uuid.UUID, *, actor: uuid.UUID, audit: Any) -> None:
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


class _AlertDeliveryRepo:
    """Empty delivery inbox (E40-T04): nothing to list, ack or report (no SQL, no mutation);
    the retention purge task built from the same class finds nothing expired."""

    async def get(self, delivery_id: int) -> None:
        return None

    async def alert_owner(self, alert_id: str) -> None:
        return None

    async def unacked_count(self, user_id: str) -> int:
        return 0

    async def list_page(self, **_kw: Any) -> Page[Any]:
        return Page([], None)

    async def ack(self, delivery_id: int, user_id: str) -> None:
        return None

    async def ack_all(self, user_id: str, cap: int = 1000) -> list[int]:
        return []

    async def report_desktop(self, delivery_id: int, **_kw: Any) -> None:
        return None

    async def fetch_expired(self, days: int, limit: int = 5000) -> list[Any]:
        return []

    async def delete_ids(self, ids: list[int]) -> int:
        return 0


class _NotificationRepo:
    """Empty `GET /notifications` read model (E40-T04, no SQL)."""

    async def list_page(self, scope: Any, **_kw: Any) -> tuple[list[Any], None]:
        return [], None


class _AuditQuery:
    """`AuditQueryService` stand-in (no DB): one event per matrix user, scoped as the repository
    scopes every page, so a read answered in the wrong user's scope shows in its body (the view-as
    matrix compares these bodies)."""

    def __init__(self) -> None:
        self.verify_slot = VerifySlot()

    async def query(self, **kw: Any) -> AuditPage:
        """A non-Owner's `restrict_to_actor`, and an `actor_user_id` filter, keep one user's."""
        wanted = {str(v) for v in (kw.get("restrict_to_actor"), kw.get("actor_user_id")) if v}
        items = [
            AuditEntry(
                id=n,
                ts=datetime(2026, 1, 1, tzinfo=UTC),
                actor_user_id=user,
                action="auth.login",
                outcome=AuditOutcome.SUCCESS,
                severity=Severity.INFO,
                ip=None,
                request_id=None,
                entry_hash=None,
                prev_hash=None,
            )
            for n, user in enumerate(_USER_IDS.values(), start=1)
            if wanted <= {str(user)}
        ]
        return AuditPage(items=items, chain_verified=True, meta=AuditPageMeta(count=len(items)))

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

    async def get_status(self, user_id: uuid.UUID) -> str | None:
        return "active" if user_id in self.roles else None

    async def count_active_owners(self) -> int:
        return sum("owner" in r for r in self.roles.values())

    def is_active_owner(self, user_id: uuid.UUID) -> bool:
        return "owner" in self.roles.get(user_id, frozenset())

    async def apply_roles(
        self,
        user_id: uuid.UUID,
        roles: frozenset[str],
        *,
        actor: uuid.UUID,
        audit: Callable[[frozenset[str]], Awaitable[None]],
    ) -> bool:
        if not self.is_active_owner(actor):  # #2593: the actor re-read at the effect, first
            raise ActorNotAuthorised(str(actor))
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
        self,
        user_id: uuid.UUID,
        *,
        actor: uuid.UUID,
        now: datetime,
        audit: Any,
        check: Any = None,  # E42-T09: a PATCH's `If-Match`, judged under the lock
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


class _Backups:
    """The catalogue's reads (E42-T05 BK-10): every id is one usable backup, and none is listed."""

    async def page(self, *_args: Any) -> list[BackupRow]:
        return []

    async def get(self, backup_id: uuid.UUID) -> BackupRow:
        return row(1, id=backup_id)  # verified, encrypted, not deleted


def _backup_downloads(
    _settings: Any, catalogue: BackupCatalogue, *, gate: Any, audit: Any
) -> BackupDownloads:
    return BackupDownloads(catalogue, Reader(), DownloadLinks(), gate=gate, audit=audit)


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


class _Views:
    """`ViewAsViews` (the view-as guard's port) over the seeded contexts (#3085 S9): each is live
    and both its users stay eligible, so a request binds what its row holds."""

    async def evaluate(self, record: SessionRecord, *, now: datetime) -> ViewAsBinding | None:
        return None if record.view_as is None else record.view_as.binding(now=now)

    async def viewer_label(self, record: SessionRecord) -> str:
        return next(a for a, u in _USER_IDS.items() if u == record.user_id)

    async def leave(
        self, record: SessionRecord, *, now: datetime, ip: str | None = None
    ) -> SessionRecord | None:
        """`DELETE /auth/session/view-as` (#3085 S12): the seeded contexts are never ended
        here, so nothing applies."""
        return None


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


def world_env(bars_state_root: Path) -> dict[str, str]:
    """The environment `build_world` sets through its `MonkeyPatch` (`create_app()` reads
    `get_settings()`). `WORLD_ENV` holds its names: the leak guard checks each one is restored."""
    return {
        "CV_ALLOWED_ORIGINS": WS_ORIGIN,
        # `register()` loads (and, on a bad blob, deletes) builder state under this root, whose
        # default is the production `/data/bars/state`. Bars are always on (#399), so every world
        # comes with a tmp root.
        "CV_BARS_STATE_ROOT": str(bars_state_root),
    }


WORLD_ENV = tuple(world_env(Path()))  # the names only


def build_world(mp: pytest.MonkeyPatch, *, bars_state_root: Path | None = None) -> World:
    """Build the app. The world keeps the bars builder state under `bars_state_root`, a fresh tmp
    dir when not given (bars are always on, #399). The attribute patches and `world_env` are applied
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

    mp.setattr(appmod, "build_identity_provider", lambda _settings: _Identity(spec))
    mp.setattr(appmod, "SqlAlchemyAlertRepository", lambda _pg: _AlertRepo())
    mp.setattr(appmod, "SqlAlchemyAlertDeliveryRepository", lambda _pg: _AlertDeliveryRepo())
    mp.setattr(appmod, "SqlAlchemyNotificationRepository", lambda _pg, **_kw: _NotificationRepo())
    # E16-T06: the real retention manager exists only on the `real` storage backend; the purge
    # route is mounted either way, so give it the call-recording stand-in (never plans/deletes).
    purge_backend = _PurgeBackend()
    mp.setattr(appmod, "build_retention_manager", lambda *_a, **_k: purge_backend)
    # ... and an in-memory stand-in for its durable idempotency anchors (Postgres-only too).
    mp.setattr(appmod, "build_purge_anchors", lambda *_a, **_k: InMemoryPurgeAnchors())
    # E42-T05 BK-10: a catalogue and artefact store stand-in, so the link issue reaches its gate.
    mp.setattr(appmod, "build_admin_backups", lambda *_a, **_k: BackupCatalogue(_Backups()))
    mp.setattr(appmod, "build_backup_downloads", _backup_downloads)
    if bars_state_root is None:
        bars_state_root = Path(tempfile.mkdtemp(prefix="cv-bars-state-"))
        atexit.register(shutil.rmtree, bars_state_root, ignore_errors=True)
    state_root = bars_state_root
    for name, value in world_env(state_root).items():
        mp.setenv(name, value)
    app = appmod.create_app(
        principal_resolver=resolver,
        user_role_store=users,
        account_access_store=access,
        user_disable=user_disable_service(audit),
        snapshot_loader=snapshot_loader,
        ws_authenticate=ws_authenticate,
    )
    # The per-user connect rate (#2558) is not under test here, and this world lives for a whole
    # module on the real clock. `test_scope_and_ws.py` opens one socket per (topic family, actor)
    # cell plus a revocation case: `manager_with_grant` spent 19 of the default 20 first auths a
    # minute when the limit was added. The next topic family would be refused with
    # `client_rate_limited` and read as an RBAC regression. The limit itself is covered by
    # `tests/unit/ws/test_connect_rate.py`. Settings cap it at 20 (#415), so the hub's limiter is
    # widened here, on the built app.
    app.state.ws_hub.connect_rate = ConnectRateLimiter(600)
    # #3085 S9: the guard runs as deployed (`build_view_as` wires it on the real backend). A
    # session holding no context passes it untouched, so every other cell is unchanged.
    app.state.view_as = _Views()
    # E02-T13 (#5181): the per-user settings store `/settings` and `/me/preferences` read is
    # Postgres-only (`None` on this backend), so the world gives them the in-memory one.
    app.state.user_settings_repository = FakeUserSettings()
    _CSRF_CODEC[:] = [app.state.csrf_codec]
    ctx = app.state.app_context
    ctx.audit._writer = audit
    ctx.audit._query = _AuditQuery()  # the lifespan is not started; same seam tests/unit/ws uses
    ctx.auth._sessions = _Sessions()
    ctx.auth._repository = _Users()  # the enrolment-only guard classifies every session
    ctx.auth._login, ctx.auth._mfa = _Login(), _Mfa()  # enrol and confirm reach the handler
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
    sid = None if actor == "unauthenticated" else session_id_of(actor)
    csrf = csrf_headers(_CSRF_CODEC[-1], sid) if _CSRF_CODEC else {}
    if actor == "unauthenticated":
        return csrf
    return {"Authorization": f"Bearer tok-{actor}", **csrf}


def bearer_viewing(target: str) -> dict[str, str]:
    """`bearer` for the Owner's session viewing as *target* (#3085 S9)."""
    csrf = csrf_headers(_CSRF_CODEC[-1], session_id_of("owner", viewing=target))
    return {"Authorization": f"Bearer tok-owner-as-{target}", **csrf}


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


def grant_viewer_a(world: World) -> None:
    """The `account_scope` viewer holds a grant on A (the matrix's viewer column), for this test
    only: the fixture clears `_Resolver.extra`. Called for a viewer cell, never otherwise."""
    world.resolver.extra["viewer"] = (GRANTED,)


def scope_request(
    world: World, key: str, req: dict[str, Any], role: str, account: uuid.UUID
) -> Any:
    """One `account_scope` cell (E27-X03, #902): `key` as `role` on `account`, with the row's
    `request` (body, headers). A viewer cell needs `grant_viewer_a(world)` first."""
    method, path = key.split(" ", 1)
    body = req.get("json")
    # A position route's situation is its position's account (4.2): the CI app composes no
    # position store, so the id is the situation's account id, which names no position there.
    ids = {"accountId": str(account), "keyId": SCOPE_KEY_ID, "profileId": SCOPE_PROFILE_ID}
    ids["positionId"] = str(account)
    return world.client.request(
        method,
        fill_path(path, ids),
        json=body if body is not None else ({} if method in ("POST", "PUT", "PATCH") else None),
        headers={**bearer(SCOPE_ACTOR[role]), **req.get("headers", {})},
    )


def observed(resp: Any) -> str:
    """`<status> <problem code>`, or the bare status of an answer that is not a problem."""
    try:
        code = resp.json().get("code")
    except (ValueError, AttributeError):
        code = None
    return f"{resp.status_code} {code}" if isinstance(code, str) else str(resp.status_code)
