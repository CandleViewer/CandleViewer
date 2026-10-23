"""#492 S2: `GET /recording/symbols` and one entry, over a bare app. A fresh database lists nothing
with a 200 (AC2); the filters; a cursor bound to its query and hour; 400 on a bad query; one 404
for unknown and malformed ids; 401; 403 with `rbac.denied`. Everyone but the Owner reads the R-I2
view (ruling Q6), with restricted refusal parity: no hidden cause changes a byte of it."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from candleviewer.api.recording_symbols import make_recording_symbols_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.recorder import control as rc
from candleviewer.recorder.models import Actor
from candleviewer.storage.errors import StorageTierUnavailable
from tests.unit.recorder._control_fakes import EmptyRows, FakeRecorder


class _Env:
    """The app over `fake`; the env resolves the caller and keeps the audit."""

    def __init__(self, fake: rc.RecordingReads, *perms: str, owner: bool = True) -> None:
        self.caller = AuditPrincipal(uuid.uuid4(), "u", frozenset(perms), is_owner=owner)
        self.audit: list[str] = []
        self.now = 1_000.0
        app = FastAPI()
        app.include_router(make_recording_symbols_router(lambda: fake, self, self,
                                                         clock=lambda: self.now))  # fmt: skip
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.caller if self.caller.permissions else None

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.audit.append(action)

    async def raw(self, path: str = "", **params: Any) -> bytes:
        return (await self.http.get("/recording/symbols" + path, params=params)).content

    async def get(self, path: str = "", **params: Any) -> Any:
        return json.loads(await self.raw(path, **params))


def _seeded() -> FakeRecorder:
    fake = FakeRecorder()
    fake.put("BTCUSDT", pinned=True)
    fake.put("ETHUSDT", "position_open", "chart_open", refusals=("position_open", "chart_open"))
    fake.put("SOLUSDT", "manual", "position_open", refusals=("position_open",))
    fake.put("XRPUSDT", "position_open", refusals=("position_open",))
    return fake


def _symbols(body: Any) -> list[str]:
    return [item["symbol"] for item in body["items"]]


async def test_a_fresh_database_lists_nothing_with_a_200() -> None:
    body = await _Env(rc.StoredRecordingControl(EmptyRows(), "demo"), "recording:read").get()
    meta = {"next_cursor": None, "has_more": False, "count": 0}
    assert body == {"items": [], "meta": meta, "role_restricted": False}


async def test_the_filters_and_a_cursor_bound_to_its_query_and_hour() -> None:
    env = _Env(_seeded(), "recording:read")
    assert _symbols(await env.get(pinned="true")) == ["BTCUSDT"]
    assert _symbols(await env.get(reason="manual")) == ["BTCUSDT", "SOLUSDT"]
    assert _symbols(await env.get(state="stopped")) == []
    first = await env.get(limit=2)
    assert _symbols(first) == ["BTCUSDT", "ETHUSDT"] and first["meta"]["has_more"]
    cursor = first["meta"]["next_cursor"]
    rest = await env.get(limit=3, cursor=cursor)
    assert _symbols(rest) == ["SOLUSDT", "XRPUSDT"]
    assert rest["meta"] == {"next_cursor": None, "has_more": False, "count": 2}
    for other in ({"pinned": "true"}, {"reason": "manual"}, {"cursor": "x" + cursor}):
        assert (await env.get(**{"cursor": cursor} | other))["code"] == "invalid_cursor"
    env.now += 3601
    assert (await env.get(cursor=cursor))["status"] == 400
    for bad in ({"state": "bogus"}, {"limit": 0}, {"pinned": "maybe"}, {"cursor": "c" * 513}):
        assert (await env.get(**bad))["code"] == "validation_failed"


async def test_one_entry_and_the_same_404_for_unknown_and_malformed_ids() -> None:
    env = _Env(fake := _seeded(), "recording:read")
    entry = await env.get(f"/{fake.entries['BTCUSDT'].id}")
    assert entry == (await env.get(pinned="true"))["items"][0] and entry["pinned"]
    for other in (str(uuid.uuid4()), "not-a-uuid"):
        assert (await env.get(f"/{other}"))["code"] == "not_found"


async def test_one_entry_of_another_environment_is_404() -> None:
    """C-2.11: a lookup asks for the settings' env, and another env's row is no entry."""
    row = {"id": str(uuid.uuid4()), "symbol": "BTCUSDT", "reason": "manual", "pinned": False,
           "streams": ["trades"], "depth": 200, "retention_days": None, "added_by": None,
           "session_state": None, "session_started_at": None}  # fmt: skip

    class _LiveRow(EmptyRows):
        async def recorded_row(self, entry_id: str, **query: object) -> dict[str, Any] | None:
            return row if query["env"] == "live" else None

    for env, status in (("live", 200), ("demo", 404)):
        env_app = _Env(rc.StoredRecordingControl(_LiveRow(), env), "recording:read")
        assert (await env_app.http.get(f"/recording/symbols/{row['id']}")).status_code == status


async def test_no_session_401_and_no_permission_403_audited() -> None:
    assert (await _Env(_seeded()).get())["code"] == "unauthenticated"
    denied = _Env(_seeded(), "marketdata:read")
    assert (await denied.get(f"/{uuid.uuid4()}"))["code"] == "forbidden"
    assert denied.audit == ["rbac.denied"]


async def test_everyone_but_the_owner_reads_the_restricted_view() -> None:
    fake = _seeded()
    owner = await _Env(fake, "recording:read").get()
    viewer = _Env(fake, "recording:read", owner=False)
    shown = await viewer.get()
    assert (_symbols(owner), owner["role_restricted"]) == (sorted(fake.entries), False)
    assert (_symbols(shown), shown["role_restricted"]) == (["BTCUSDT", "ETHUSDT", "SOLUSDT"], True)
    eth, sol = shown["items"][1:]
    assert (eth["reason"], eth["refusal"], sol["reason"], "refusal" in sol) == (
        "chart_open", "chart_open", "manual", False)  # fmt: skip
    assert "position_open" not in json.dumps(shown)
    assert (await viewer.get(f"/{fake.entries['XRPUSDT'].id}"))["code"] == "not_found"


@pytest.mark.parametrize("visible", [(), ("chart_open",)])
@pytest.mark.parametrize("cause", sorted(rc.HIDDEN_CAUSES))
async def test_restricted_refusal_parity(cause: Any, visible: Any) -> None:
    """(a) No hidden cause changes a byte a non-Owner reads; (b) the Owner's body names it."""
    plain, held = FakeRecorder(), FakeRecorder()
    plain.put("SOLUSDT", "manual", *visible, refusals=visible)
    held.put("SOLUSDT", "manual", cause, *visible, refusals=(cause, *visible))
    for path in ("", f"/{held.entries['SOLUSDT'].id}"):
        bodies = {await _Env(f, "recording:read", owner=False).raw(path) for f in (plain, held)}
        assert len(bodies) == 1
        named = await _Env(held, "recording:read").get(path)
        assert (named.get("items") or [named])[0]["refusal"] == cause


async def test_restricted_pages_end_where_the_view_ends() -> None:
    """A non-Owner's page edges follow the rows it can see, never the hidden-only row."""
    viewer = _Env(_seeded(), "recording:read", owner=False)
    whole = await viewer.get(limit=3)
    assert _symbols(whole) == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert whole["meta"] == {"next_cursor": None, "has_more": False, "count": 3}
    seen: list[str] = []
    page = await viewer.get(limit=2)
    while True:
        seen += _symbols(page)
        if not page["meta"]["has_more"]:
            break
        page = await viewer.get(limit=2, cursor=page["meta"]["next_cursor"])
    assert seen == ["BTCUSDT", "ETHUSDT", "SOLUSDT"] and "XRPUSDT" not in seen


async def test_a_cursor_issued_to_the_owner_is_foreign_to_a_viewer() -> None:
    fake = _seeded()
    cursor = (await _Env(fake, "recording:read").get(limit=1))["meta"]["next_cursor"]
    viewer = _Env(fake, "recording:read", owner=False)
    assert (await viewer.get(limit=1, cursor=cursor))["code"] == "invalid_cursor"


class _Refusing:
    """A control whose store is down."""

    async def list(self, query: rc.EntryQuery) -> rc.EntryPage:
        raise StorageTierUnavailable("down")

    async def get(self, entry_id: str) -> rc.RecordedEntry | None:
        raise StorageTierUnavailable("down")


async def test_a_store_outage_answers_503_on_both_routes() -> None:
    env = _Env(_Refusing(), "recording:read")  # type: ignore[arg-type]  # a two-method double
    for path in ("", f"/{uuid.uuid4()}"):
        body = await env.get(path)
        assert (body["status"], body["code"]) == (503, "store_unavailable")


async def test_a_refused_audit_write_answers_503_and_reads_nothing() -> None:
    class _NoAudit(_Env):
        async def emit(self, action: str, **kwargs: Any) -> None:
            raise AuditUnavailable("full")

    denied = _NoAudit(_seeded(), "marketdata:read")
    assert (await denied.get())["code"] == "store_unavailable"


async def test_the_fake_keeps_an_active_row_when_it_is_unpinned() -> None:
    fake = _seeded()
    await fake.set_pin("BTCUSDT", False, Actor(kind="user", id="u-1"))
    assert fake.entries["BTCUSDT"].pinned is False and fake.entries["BTCUSDT"].state == "recording"
