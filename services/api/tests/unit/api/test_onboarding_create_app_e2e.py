"""E09-S06 e2e through the real `create_app()` wiring (PR #1721 review).

Real onboarding router + probes + audit emitter; only the Postgres-facing
store is an in-memory fake (shared across app rebuilds to prove persistence).
The tamper refusal also runs against the real `AuditWriter` (#2323): a permissive
recording fake accepts any action and any kwargs, which is how an unregistered
action without `actor_label` reached `main`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from candleviewer.app import create_app
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.scopes import PrincipalSnapshot
from tests.csrf_helpers import arm_csrf, wire_fake_sessions

MGR = uuid.uuid4()
OTHER = uuid.uuid4()


class _Store:
    def __init__(self) -> None:
        self.totp: set[uuid.UUID] = set()
        self.bound: dict[uuid.UUID, datetime] = {}
        self.dismissed: set[uuid.UUID] = set()

    async def is_dismissed(self, u: uuid.UUID) -> bool:
        return u in self.dismissed

    async def dismiss(self, u: uuid.UUID) -> None:
        self.dismissed.add(u)

    async def has_confirmed_totp(self, u: uuid.UUID) -> bool:
        return u in self.totp

    async def has_account_binding(self, u: uuid.UUID) -> bool:
        return u in self.bound

    async def latest_binding_at(self, u: uuid.UUID) -> datetime | None:
        return self.bound.get(u)


class _Resolver:
    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        tok = request.headers.get("authorization", "").removeprefix("Bearer ")
        uid = {"mgr": MGR, "other": OTHER}.get(tok)
        return PrincipalSnapshot(uid, frozenset({"manager"}), frozenset()) if uid else None


class _Writer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append({"action": action, **kw})


def _client(store: _Store, w: _Writer) -> TestClient:
    app = create_app(principal_resolver=_Resolver(), onboarding_store=store)
    app.state.app_context.audit._writer = w
    wire_fake_sessions(app, "mgr", "other")
    return arm_csrf(TestClient(app, client=("127.0.0.1", 50000)), app.state.csrf_codec)


H = {"Authorization": "Bearer mgr"}


def _states(c: TestClient) -> dict[str, str]:
    body = c.get("/onboarding/checklist", headers=H).json()
    return {i["key"]: i["state"] for i in body["items"]}


def test_new_manager_to_completion_dismiss_persist_and_tamper() -> None:
    store, w = _Store(), _Writer()
    c = _client(store, w)
    first = _states(c)
    assert first["totp"] == "pending" and first["sub_account"] == "pending"
    assert first["profile_limits"] == first["demo_session"] == "pending"
    assert c.get("/onboarding/checklist", headers=H).json()["complete"] is False
    assert c.post("/onboarding/checklist/dismiss", headers=H).status_code == 409

    store.totp.add(MGR)  # real actions: enrol TOTP, get an account assigned
    store.bound[MGR] = datetime.now(UTC) - timedelta(days=3)
    assert _states(c)["api_key"] == "pending"  # no key inventory on main yet

    # Tamper: forging step state / another user's completion -> 403 + audit.
    forged = c.post(
        "/onboarding/checklist/dismiss",
        headers=H,
        json={"user_id": str(OTHER), "items": [{"key": "api_key", "state": "ok"}]},
    )
    assert forged.status_code == 403
    assert w.calls[-1]["action"] == "onboarding.checklist_tamper_rejected"
    assert OTHER not in store.dismissed and MGR not in store.dismissed
    anon = c.post("/onboarding/checklist/dismiss", headers={})  # SR-041: no session -> CSRF 403
    assert anon.status_code == 403 and anon.json()["code"] == "csrf_token_invalid"

    # Completion is reachable; dismiss persists across a rebuilt app.
    # Unshipped steps keep the card incomplete: it cannot be dismissed yet.
    assert c.get("/onboarding/checklist", headers=H).json()["complete"] is False
    assert c.post("/onboarding/checklist/dismiss", headers=H).status_code == 409


def test_dismissal_persists_across_app_rebuild_and_is_per_user() -> None:
    store, w = _Store(), _Writer()
    store.dismissed.add(MGR)
    store.totp.add(MGR)
    c2 = _client(store, w)  # fresh app / service rebuild, same persistent store
    body = c2.get("/onboarding/checklist", headers=H).json()
    assert body["dismissed"] is False  # dismissal only counts while complete
    other = c2.get("/onboarding/checklist", headers={"Authorization": "Bearer other"}).json()
    assert other["dismissed"] is False
    assert any(i["key"] == "profile_limits" and i["state"] == "pending" for i in body["items"])


class _AuditTable:
    """`audit_log` as the real writer's flusher sees it: `insert` is the one call it makes."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def insert(self, record: dict[str, Any]) -> None:
        self.rows.append(record)


@pytest.fixture
async def real_audit(tmp_path: Path) -> AsyncIterator[tuple[AuditWriter, _AuditTable]]:
    """A started `AuditWriter` (temp WAL) that refuses what production refuses."""
    table = _AuditTable()
    writer = AuditWriter(cast(AuditRepository, table), str(tmp_path / "audit.wal"))
    await writer.start()
    yield writer, table
    await writer.stop(1)


_REFUSAL = {
    "type": "about:blank",
    "title": "Forbidden",
    "status": 403,
    "detail": "the checklist accepts no client-supplied state",
}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"user_id": str(OTHER)}, id="another-users-checklist"),
        pytest.param({"items": [{"key": "api_key", "state": "ok"}]}, id="forged-step-state"),
    ],
)
async def test_tamper_through_the_real_audit_writer_is_refused_with_exactly_one_row(
    real_audit: tuple[AuditWriter, _AuditTable], body: dict[str, Any]
) -> None:
    writer, table = real_audit
    store = _Store()
    app = create_app(principal_resolver=_Resolver(), onboarding_store=store)
    app.state.app_context.audit._writer = writer  # the lazy emitter resolves it per call
    wire_fake_sessions(app, "mgr", "other")
    transport = httpx.ASGITransport(
        app=app, client=("127.0.0.1", 50000), raise_app_exceptions=False
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        arm_csrf(client, app.state.csrf_codec)
        refused = await client.post("/onboarding/checklist/dismiss", headers=H, json=body)
    await writer.flush(5)

    assert refused.status_code == 403
    assert refused.headers["content-type"] == "application/problem+json"
    assert refused.json() == _REFUSAL
    (row,) = table.rows
    assert (row["action"], row["actor_user_id"], row["actor_label"]) == (
        "onboarding.checklist_tamper_rejected",
        str(MGR),
        str(MGR),
    )
    assert (row["outcome"], row["severity"], row["reason"]) == (
        "denied",
        "warning",
        "client_supplied_state",
    )
    assert store.dismissed == set()  # neither the caller nor the user the body named
