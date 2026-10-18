"""The app the feature-flag route tests run (E42-T03): the real service and writer over a fake
store, audit, user directory and step-up, behind the audited admin guard, with one caller per role.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.admin.flags import FLAGS, FlagService, FlagWriter, StoredFlag, default_registry
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.feature_flags import make_feature_flags_routers
from candleviewer.audit.access import AuditPrincipal
from tests.unit.admin.flag_fakes import T0, FakeAudit, FakeFlagStore, FakeStepUp, FakeUsers

KEY, OWNER_ONLY, KNOWN = "rules.graph_editor", "recorder.auto_record", uuid.UUID(int=77)
#: `writer` is a non-owner granted the flag permissions, which no seeded role is; `reader` only
#: `flags:read`.
_PERMS = {"owner": {"flags:read", "flags:write"}, "writer": {"flags:read", "flags:write"}}
_PERMS |= {"manager": {"accounts:read"}, "viewer": {"audit:read"}, "reader": {"flags:read"}}


@dataclass
class _Flags:
    service: FlagService
    writer: Any  # the real writer, or a stand-in that raises


class Resolver:
    async def resolve(self, request: Request) -> AuditPrincipal | None:
        role = request.headers.get("x-role", "")
        if role not in _PERMS:
            return None
        n = list(_PERMS).index(role) + 1
        perms = frozenset(_PERMS[role])
        return AuditPrincipal(uuid.UUID(int=n), role, perms, uuid.UUID(int=10 + n), is_owner=n == 1)


def client(
    writer: Any = None, *, step_up: Any = None, down: bool = False, audit: FakeAudit | None = None
) -> tuple[TestClient, FakeAudit]:
    store, audit = FakeFlagStore(), audit or FakeAudit()
    store.rows, store.down = {s.key: StoredFlag(s.default, updated_at=T0) for s in FLAGS}, down
    service = FlagService(default_registry(), store)
    writer = writer or FlagWriter(service, audit, step_up or FakeStepUp(), FakeUsers([KNOWN]))
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    flags = _Flags(service, writer)
    for router in make_feature_flags_routers(flags, resolver=Resolver(), audit=audit):
        app.include_router(router)
    return TestClient(app), audit


def put(c: TestClient, body: object, key: str = KEY, role: str = "owner", query: str = "") -> Any:
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    return c.put(f"/admin/feature-flags/{key}{query}", content=data, headers={"x-role": role})


def write(**fields: Any) -> dict[str, Any]:
    return {"value": False, "reason": "rollout", "expected_updated_at": T0.isoformat()} | fields
