"""#492 S5: `GET /recording/status` over a bare app, served from the 1 Hz snapshot: the Owner
reads the full body, everyone else the R-I2 view (ruling Q6); 401 without a session; 403 without
`recording:read`, audited `rbac.denied`; 503 before the first computation. No read computes."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastapi import FastAPI

from candleviewer.api.recording_status import make_recording_status_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.recorder.status import RecordingStatusCache
from tests.unit.recorder._control_fakes import FakeRecorder


class _Env:
    def __init__(self, cache: RecordingStatusCache, *perms: str, owner: bool = True) -> None:
        self.caller = AuditPrincipal(uuid.uuid4(), "u", frozenset(perms), is_owner=owner)
        self.audit: list[str] = []
        app = FastAPI()
        app.include_router(make_recording_status_router(cache, self, self))
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.caller if self.caller.permissions else None

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.audit.append(action)

    async def get(self) -> tuple[int, Any]:
        resp = await self.http.get("/recording/status")
        return resp.status_code, resp.json()


class _Counting(FakeRecorder):
    calls = 0

    async def status(self) -> Any:
        self.calls += 1
        return await super().status()


async def _cache() -> tuple[RecordingStatusCache, _Counting]:
    fake = _Counting()
    fake.put("BTCUSDT")
    fake.put("XRPUSDT", "position_open", refusals=("position_open",))
    cache = RecordingStatusCache(lambda: fake, None)
    await cache.refresh_once()
    return cache, fake


async def test_the_owner_reads_the_full_body_and_no_read_computes() -> None:
    cache, fake = await _cache()
    env = _Env(cache, "recording:read")
    for _ in range(3):
        status, body = await env.get()
        assert status == 200 and body == cache.body(restricted=False)
    assert [row["symbol"] for row in body["symbols"]] == ["BTCUSDT", "XRPUSDT"]
    assert fake.calls == 1 and env.audit == []


async def test_everyone_but_the_owner_reads_the_restricted_view() -> None:
    cache, _ = await _cache()
    status, body = await _Env(cache, "recording:read", owner=False).get()
    assert status == 200 and body == cache.body(restricted=True)
    assert body["role_restricted"] is True
    assert [row["symbol"] for row in body["symbols"]] == ["BTCUSDT"]


async def test_401_without_a_session_and_403_audited_without_the_permission() -> None:
    cache, _ = await _cache()
    status, body = await _Env(cache).get()
    assert (status, body["code"]) == (401, "unauthenticated")
    env = _Env(cache, "marketdata:read", owner=False)
    status, body = await env.get()
    assert (status, body["code"], env.audit) == (403, "forbidden", ["rbac.denied"])
    assert body["required_permissions"] == ["recording:read"]


async def test_503_before_the_first_computation() -> None:
    cache = RecordingStatusCache(lambda: None, None)
    status, body = await _Env(cache, "recording:read").get()
    assert (status, body["code"]) == (503, "store_unavailable")
