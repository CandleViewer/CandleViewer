"""A router-only test app for `/settings/hotkeys*` (E10-T05, #5211) over the in-memory store
(`_fake_store.FakeHotkeyProfileStore`), with audit and metric fakes, as
tests/watchlists/_watchlists_env.py is for the watchlists."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.hotkey_profiles import make_hotkey_profiles_router
from candleviewer.audit.access import AuditPrincipal
from tests.hotkey_profiles._fake_store import FakeHotkeyProfileStore

USER_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
USER_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")
VIEWER = uuid.UUID("00000000-0000-4000-8000-00000000000c")
SID = uuid.UUID("00000000-0000-4000-8000-0000000000e1")
WRITE = frozenset({"settings:read", "settings:write"})
PERMS = {USER_A: WRITE, USER_B: WRITE, VIEWER: frozenset({"settings:read"})}
MISSING = "00000000-0000-4000-8000-0000000000ff"
#: The Gherkin's remap: "Toggle footprint" on Ctrl+Alt+F.
FOOTPRINT: dict[str, Any] = {"action": "chart.footprint_toggle", "keys": "Ctrl+Alt+F",
                             "scope": "chart"}  # fmt: skip
SCALPING: dict[str, Any] = {"name": "Scalping", "bindings": [FOOTPRINT]}


def tag(profile: dict[str, Any]) -> dict[str, str]:
    """The `If-Match` of a profile as last read: `W/"<id>:<version>"` (22 `HotkeyProfileETag`)."""
    return {"If-Match": f'W/"{profile["id"]}:{profile["version"]}"'}


class Audit:
    """The audit emitter: records every call; `fail` is raised instead (a refused record)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail: Exception | None = None

    async def emit(self, action: str, **kw: Any) -> None:
        if self.fail is not None:
            raise self.fail
        self.calls.append({"action": action, **kw})

    def actions(self) -> list[str]:
        return [c["action"] for c in self.calls]


class _Child:
    def __init__(self, counts: dict[tuple[str, ...], float], key: tuple[str, ...]) -> None:
        self.counts, self.key = counts, key

    def inc(self, amount: float = 1) -> None:
        self.counts[self.key] = self.counts.get(self.key, 0) + amount


class Refusals:
    """`hotkey_profile_refusals_total`: its children, counted by (code, rule)."""

    def __init__(self) -> None:
        self.counts: dict[tuple[str, ...], float] = {}

    def labels(self, *values: str) -> _Child:
        return _Child(self.counts, tuple(values))


class Env:
    """The router over a `FakeHotkeyProfileStore`. `user` is the session's principal (None: no
    session); `viewing`, when set, is the viewer acting while that principal is its target."""

    def __init__(self) -> None:
        self.store, self.audit, self.refusals = FakeHotkeyProfileStore(), Audit(), Refusals()
        self.user: uuid.UUID | None = USER_A
        self.viewing: uuid.UUID | None = None
        self.store_up = True
        env = self

        class _Resolver:  # async, like the session-backed `SessionAuditPrincipalResolver`
            async def resolve(self, _request: Request) -> AuditPrincipal | None:
                if env.user is None:
                    return None
                return AuditPrincipal(env.user, "u", PERMS[env.user], session_id=SID,
                                      ip="10.0.0.9", actor_user_id=env.viewing)  # fmt: skip

        ids = iter(range(1, 1_000_000))
        app = FastAPI()
        app.include_router(make_hotkey_profiles_router(
            lambda: self.store if self.store_up else None, _Resolver(), self.audit,
            refusals=self.refusals, new_id=lambda: uuid.UUID(int=(0x0193 << 112) | next(ids)),
        ))  # fmt: skip
        self.app = app  # for an `httpx.ASGITransport` (a streamed body read as it arrives)
        self.c = TestClient(app)

    def create(self, **over: Any) -> dict[str, Any]:
        r = self.c.post("/settings/hotkeys", json=dict(SCALPING) | over)
        assert r.status_code == 201, r.text
        return dict(r.json())

    def listed(self) -> list[dict[str, Any]]:
        r = self.c.get("/settings/hotkeys")
        assert r.status_code == 200, r.text
        return list(r.json()["items"])

    def put(self, pid: object, body: Any, headers: dict[str, str] | None = None) -> Any:
        return self.c.put(f"/settings/hotkeys/{pid}", json=body, headers=headers)

    def activate(self, pid: object) -> Any:
        return self.c.post(f"/settings/hotkeys/{pid}/activate")

    def delete(self, pid: object) -> Any:
        return self.c.delete(f"/settings/hotkeys/{pid}")
