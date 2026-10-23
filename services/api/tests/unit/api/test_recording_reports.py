"""#492 S3: `GET /recording/sessions` and `GET /recording/storage`, over a bare app. Sessions page
newest first by symbol, `from` and `to`, held to the settings' env (C-2.11), with a cursor bound to
its query and hour. Storage is the budget's last `report()`, never measured per request: 503
before the first sample or with no budget (the fake backend). Everyone but the Owner reads the
R-I2 view (ruling Q6): no session or symbol held only by a hidden cause, and never a path."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from candleviewer.api import recording_reports as reports
from candleviewer.audit.access import AuditPrincipal
from candleviewer.recorder import control as rc
from candleviewer.recorder.models import StorageUsage, SymbolUsage, TierUsage
from tests.unit.recorder._control_fakes import NOW, FakeRecorder


class _Sessions:
    """The session rows of two envs, filtered as the repository's SQL filters them."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.calls = 0

    def add(self, symbol: str, hours_ago: int, *, env: str = "demo", reason: str = "manual",
            ended: int | None = None) -> str:  # fmt: skip
        sid = str(uuid.UUID(int=len(self.rows) + 1))
        start = NOW - timedelta(hours=hours_ago)
        self.rows.append({
            "id": sid, "recorded_symbol_id": str(uuid.UUID(int=1000 + len(self.rows))),
            "symbol": symbol, "state": "stopped" if ended is not None else "recording",
            "started_at": start, "ended_at": None if ended is None else start + timedelta(
                hours=ended), "streams": ["trades"], "depth": 200, "messages_received": 7,
            "bytes_written": 99, "gap_count": 1, "env": env, "reason": reason,
        })  # fmt: skip
        return sid

    async def sessions_page(self, *, env: str, symbol: str | None, since: datetime | None,
                            until: datetime | None, hidden: tuple[str, ...],
                            after: tuple[datetime, str] | None,
                            limit: int) -> list[dict[str, Any]]:  # fmt: skip
        self.calls += 1
        hits = [
            r for r in self.rows
            if r["env"] == env and r["reason"] not in hidden and symbol in (None, r["symbol"])
            and (since is None or r["ended_at"] is None or r["ended_at"] > since)
            and (until is None or r["started_at"] < until)
            and (after is None or (r["started_at"], r["id"]) < after)
        ]  # fmt: skip
        hits.sort(key=lambda r: (r["started_at"], r["id"]), reverse=True)
        return [{k: v for k, v in r.items() if k not in ("env", "reason")} for r in hits[:limit]]


class _Budget:
    def __init__(self, usage: StorageUsage | None) -> None:
        self.usage, self.reads = usage, 0

    def report(self) -> StorageUsage | None:
        self.reads += 1
        return self.usage


def _usage() -> StorageUsage:
    symbols = tuple(SymbolUsage(symbol=s, used_bytes=b, daily_growth_bytes=5, pinned=s == "BTCUSDT")
                    for s, b in (("BTCUSDT", 900), ("XRPUSDT", 500), ("ETHUSDT", 100)))  # fmt: skip
    return StorageUsage(
        disk_total_bytes=10_000, disk_used_bytes=4_000, disk_free_bytes=6_000,
        projected_full_at=NOW + timedelta(days=90), daily_growth_bytes=15,
        tiers=(TierUsage(tier="questdb", used_bytes=1_000, retention_days=7),),
        symbols=symbols, generated_at=NOW, cap_bytes=5_000, level=0, write_gate="open",
        write_gate_reason=None, accelerate_retention=False,
    )  # fmt: skip


def _recorder() -> FakeRecorder:
    fake = FakeRecorder()
    fake.put("BTCUSDT", pinned=True)
    fake.put("ETHUSDT", "position_open", "chart_open")
    fake.put("XRPUSDT", "position_open")
    return fake


class _Env:
    def __init__(self, *perms: str, owner: bool = True, env: str = "demo",
                 budget: _Budget | None = None, control: Any = None) -> None:  # fmt: skip
        self.caller = AuditPrincipal(uuid.uuid4(), "u", frozenset(perms), is_owner=owner)
        self.audit: list[str] = []
        self.sessions, self.budget, self.now = _Sessions(), budget, 1_000.0
        self.control = _recorder() if control is None else control
        app = FastAPI()
        app.include_router(reports.make_recording_reports_router(
            lambda: self.control, lambda: self.sessions, lambda: self.budget, env, self, self,
            clock=lambda: self.now))  # fmt: skip
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.caller if self.caller.permissions else None

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.audit.append(action)

    async def get(self, path: str, **params: Any) -> Any:
        resp = await self.http.get(path, params=params)
        return resp.status_code, resp.json()


def _ids(body: Any) -> list[str]:
    return [item["id"] for item in body["items"]]


async def test_sessions_newest_first_by_symbol_from_and_to() -> None:
    env = _Env("recording:read")
    s = env.sessions
    old, mid = s.add("BTCUSDT", 30, ended=2), s.add("BTCUSDT", 10, ended=3)
    new = s.add("BTCUSDT", 1)
    eth = s.add("ETHUSDT", 5, ended=1)
    status, body = await env.get("/recording/sessions")
    assert status == 200 and _ids(body) == [new, eth, mid, old]
    assert body["meta"] == {"next_cursor": None, "has_more": False, "count": 4}
    first = body["items"][0]
    assert (first["rows"], first["bytes"], first["gap_count"]) == (7, 99, 1)
    assert first["ended_at"] is None
    assert first["started_at"] == "2026-10-23T11:00:00Z"
    assert _ids((await env.get("/recording/sessions", symbol="BTCUSDT"))[1]) == [new, mid, old]
    since = (NOW - timedelta(hours=8)).isoformat()
    until = (NOW - timedelta(hours=2)).isoformat()
    assert _ids((await env.get("/recording/sessions", **{"from": since}))[1]) == [new, eth, mid]
    window = {"from": since, "to": until}
    assert _ids((await env.get("/recording/sessions", **window))[1]) == [eth, mid]


async def test_sessions_cursor_is_bound_to_its_query_and_hour() -> None:
    env = _Env("recording:read")
    made = [env.sessions.add("BTCUSDT", h) for h in (4, 3, 2, 1)]
    first = (await env.get("/recording/sessions", limit=3))[1]
    assert _ids(first) == made[::-1][:3] and first["meta"]["has_more"]
    cursor = first["meta"]["next_cursor"]
    rest = (await env.get("/recording/sessions", limit=3, cursor=cursor))[1]
    assert _ids(rest) == [made[0]] and rest["meta"]["next_cursor"] is None
    other = (await env.get("/recording/sessions", cursor=cursor, symbol="BTCUSDT"))[1]
    assert other["code"] == "invalid_cursor"
    env.now += 3601
    assert (await env.get("/recording/sessions", cursor=cursor))[0] == 400


_BAD: list[dict[str, Any]] = [{"limit": 0}, {"limit": 501}, {"symbol": "btc"}, {"from": "x"}]
_BAD += [{"to": "2026-10-23T12:00:00"}, {"cursor": "c" * 513}]


@pytest.mark.parametrize("bad", _BAD)
async def test_sessions_bad_query_is_400(bad: dict[str, Any]) -> None:
    status, body = await _Env("recording:read").get("/recording/sessions", **bad)
    assert (status, body["code"]) == (400, "validation_failed")


async def test_another_environments_sessions_never_appear() -> None:
    env = _Env("recording:read", env="demo")
    mine = env.sessions.add("BTCUSDT", 2)
    env.sessions.add("BTCUSDT", 1, env="live")
    assert _ids((await env.get("/recording/sessions"))[1]) == [mine]


async def test_a_non_owner_never_reads_a_session_held_only_by_a_hidden_cause() -> None:
    env = _Env("recording:read", owner=False)
    shown = env.sessions.add("BTCUSDT", 2)
    env.sessions.add("XRPUSDT", 1, reason="position_open")
    assert _ids((await env.get("/recording/sessions"))[1]) == [shown]
    env.caller = AuditPrincipal(env.caller.user_id, "u", env.caller.permissions, is_owner=True)
    assert len((await env.get("/recording/sessions"))[1]["items"]) == 2


async def test_storage_is_the_last_report_and_never_measures() -> None:
    budget = _Budget(_usage())
    env = _Env("recording:read", budget=budget)
    status, body = await env.get("/recording/storage")
    assert status == 200 and body == _usage().model_dump(mode="json")
    assert body["generated_at"] == "2026-10-23T12:00:00Z" and budget.reads == 1


@pytest.mark.parametrize("budget", [None, _Budget(None)], ids=["fake-backend", "no-sample-yet"])
async def test_storage_is_503_before_the_first_sample_or_without_a_budget(
    budget: _Budget | None,
) -> None:
    status, body = await _Env("recording:read", budget=budget).get("/recording/storage")
    assert (status, body["code"]) == (503, "store_unavailable")


async def test_a_non_owner_storage_view_leaves_out_symbols_held_only_by_a_hidden_cause() -> None:
    env = _Env("recording:read", owner=False, budget=_Budget(_usage()))
    status, body = await env.get("/recording/storage")
    assert status == 200 and [s["symbol"] for s in body["symbols"]] == ["BTCUSDT", "ETHUSDT"]
    assert body["tiers"] == _usage().model_dump(mode="json")["tiers"]
    env.control = None  # no recorded set to filter by: fail closed
    assert (await env.get("/recording/storage"))[0] == 503


@pytest.mark.parametrize("path", ["/recording/sessions", "/recording/storage"])
async def test_no_session_401_and_no_permission_403_audited(path: str) -> None:
    assert (await _Env(budget=_Budget(_usage())).get(path))[1]["code"] == "unauthenticated"
    denied = _Env("marketdata:read", budget=_Budget(_usage()))
    assert (await denied.get(path))[1]["code"] == "forbidden"
    assert denied.audit == ["rbac.denied"]


async def test_no_non_owner_body_carries_a_path_character() -> None:
    env = _Env("recording:read", owner=False, budget=_Budget(_usage()))
    env.sessions.add("BTCUSDT", 2)
    bodies = [(await env.get(p))[1] for p in ("/recording/sessions", "/recording/storage")]
    assert re.search(r'[/\\]|"[A-Za-z]:', json.dumps(bodies)) is None


async def test_the_restricted_view_is_the_recorder_s_own() -> None:
    """The storage filter keeps exactly the symbols `restricted_view` keeps."""
    fake = _recorder()
    page = await fake.list(rc.EntryQuery(limit=500))
    kept = sorted(e.symbol for e in page.items if rc.restricted_view(e) is not None)
    env = _Env("recording:read", owner=False, budget=_Budget(_usage()), control=fake)
    assert sorted(s["symbol"] for s in (await env.get("/recording/storage"))[1]["symbols"]) == kept


async def test_a_non_owner_storage_view_fails_closed_when_the_set_is_over_one_page() -> None:
    fake = FakeRecorder()
    for n in range(501):
        fake.put(f"S{n:03d}USDT")
    env = _Env("recording:read", owner=False, budget=_Budget(_usage()), control=fake)
    status, body = await env.get("/recording/storage")
    assert (status, body["code"]) == (503, "store_unavailable")
    owner = _Env("recording:read", budget=_Budget(_usage()), control=fake)
    assert (await owner.get("/recording/storage"))[0] == 200  # the Owner needs no filter


async def test_sessions_are_503_without_a_session_store() -> None:
    env = _Env("recording:read")
    env.sessions = None  # type: ignore[assignment]  # the fake backend holds no session store
    status, body = await env.get("/recording/sessions")
    assert (status, body["code"]) == (503, "store_unavailable")


async def test_an_owner_cursor_replayed_by_a_non_owner_is_invalid() -> None:
    env = _Env("recording:read")
    for hours in (3, 2, 1):
        env.sessions.add("BTCUSDT", hours)
    cursor = (await env.get("/recording/sessions", limit=2))[1]["meta"]["next_cursor"]
    env.caller = AuditPrincipal(env.caller.user_id, "u", env.caller.permissions, is_owner=False)
    status, body = await env.get("/recording/sessions", limit=2, cursor=cursor)
    assert (status, body["code"]) == (400, "invalid_cursor")
