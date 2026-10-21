"""ADR-0037 S3 (#3009): the session-route rows that Q1's default admits go through the audit lane's
façade, `AuditService.lane`: the sign-out intent and its outcome rows, revoke-my-session, reuse
containment's intent and the race outcome, and a disabled user's refused refresh.

A real `AuditWriter` over `FakeAuditRepository` that refuses as #2872's `_RefusingWriter` does, a
real lane journal and drain in `tmp_path` and the real façade, all on the test's loop (requests go
through `httpx.ASGITransport`). Flag on, the sink refusing and the lane accepting: sign-out and
revoke answer 204, a reused token's family is revoked, nothing is counted lost and every row reaches
the chain once after a restart. Both refusing: today's answers and counters. Flag off: today's path,
byte for byte. No network; every wait is a bound, never a sleep.
"""

from __future__ import annotations

import contextlib
import itertools
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.sessions import REFRESH_COOKIE, make_session_router
from candleviewer.audit import lane_journal as lj
from candleviewer.audit.lane import AuditLane, LaneFacade
from candleviewer.audit.models import AuditEmission, AuditOutcome
from candleviewer.audit.service import AuditService
from candleviewer.audit.writer import AuditUnavailable, AuditWriter, AuditWriterStopped
from candleviewer.auth.models import MintedSession, UserStatus
from candleviewer.auth.session_service import SessionService
from tests.csrf_helpers import csrf_headers
from tests.unit.api._fakes import (
    BASE,
    CSRF_CODEC,
    HASHER,
    NOW,
    USER,
    Identity,
    RacedSessionService,
    RecordingWriter,
    SessionsAuth,
    enrolment_recorder,
    throttle,
)
from tests.unit.audit.audit_fakes import FakeAuditRepository, FakeClock
from tests.unit.auth.session_fakes import FakeSessionRepository

_CLIENT_IP = "198.51.100.7"  # documentation range (RFC 5737)
_KEYS = lj.LaneKeys(bytes(range(32)))  # a test vector, never a key
_LANE = uuid.UUID(int=1 << 96)  # one lane id, so two worlds write equal boot rows
_WAIT_S = 5.0  # a bound on what the drain or the flusher must do, never a sleep
_LOGOUT, _OUT, _REUSE = "auth.logout", "auth.session_revoked", "auth.refresh_reuse_detected"
_REFRESHED, _UNWIRED = "auth.session_refreshed", "auth.session_audit.lane_unavailable"
_ERRORS: list[Callable[[], Exception]] = [
    lambda: AuditUnavailable("audit WAL unavailable: OSError"),
    AuditWriterStopped,
]


def _lost() -> list[float]:
    """`auth_audit_outcome_lost_total` of each outcome action (#3222, #3235)."""
    name = "auth_audit_outcome_lost_total"
    actions = (_OUT, _REUSE, _REFRESHED)
    return [float(REGISTRY.get_sample_value(name, {"action": a}) or 0.0) for a in actions]


def _bearer(m: MintedSession) -> dict[str, str]:
    return {"Authorization": f"Bearer {m.access_token}"}


class _Sink(AuditWriter):
    """#2872's `_RefusingWriter` on the real writer, which the façade's fallback and the lane's
    drain share: it takes `accept` more records (None: all), then refuses each with `error` and
    lists its action in `refused`. While it refuses its `failure` is set, so the drain waits for a
    restart (§15.6 Ingest step 2) and never spends a credit."""

    def __init__(
        self, repo: FakeAuditRepository, wal: Path, error: Exception, clock: FakeClock
    ) -> None:
        super().__init__(repo, str(wal), clock=clock, sleep=repo.retry_sleep)
        self.error, self.refused = error, list[str]()
        self.accept: int | None = None

    @property
    def failure(self) -> BaseException | None:
        return self.error if self.accept == 0 else super().failure

    async def ingest(self, record: AuditEmission | dict[str, Any]) -> int:
        if self.accept == 0:
            self.refused.append(AuditEmission.model_validate(record).action)
            raise self.error
        if self.accept is not None:
            self.accept -= 1
        return await super().ingest(record)


class _Lane(AuditLane):
    """The real lane; `seen` holds the sessions live as each caller's record came in (C-2.9)."""

    def __init__(
        self, journal: lj.LaneJournal, sink: _Sink, live: Callable[[], Awaitable[set[str]]]
    ) -> None:
        super().__init__(journal, sink, retry_s=(3600.0, 3600.0), new_lane=lambda: _LANE)
        self.live, self.seen = live, list[frozenset[str]]()

    async def append(self, record: AuditEmission) -> int:
        if not record.action.startswith("audit.lane_"):  # the boot's rows are the lane's own
            self.seen.append(frozenset(await self.live()))
        return await super().append(record)


class _World:
    """The session router over the façade, a real lane and `_Sink`; the world is the router's audit
    service (`is_active`, `writer`, `lane`). `today` gives the router the writer as `lane`, the
    receiver every row had before S3. `caps`: the `shared` and lane byte limits (§15.6 Limits)."""

    is_active = True

    def __init__(
        self,
        path: Path,
        *,
        flag: bool = True,
        today: bool = False,
        error: Exception | None = None,
        service: type[SessionService] = SessionService,
        caps: tuple[int, int] = (lj.SHARED_MAX_BYTES, lj.LANE_MAX_BYTES),
    ) -> None:
        path.mkdir()
        self.path, self.flag, self.today, self.caps = path, flag, today, caps
        self.error = error or _ERRORS[0]()
        self.repo, self.clock, self.sessions = (
            FakeAuditRepository(),
            FakeClock(),
            FakeSessionRepository(),
        )
        self.svc = service(self.sessions, HASHER, clock=lambda: NOW)
        app = FastAPI()
        router = make_session_router(
            SessionsAuth(self.svc),
            self,
            identity=Identity(),
            ip_throttle=throttle(),
            session_throttle=throttle(),
            csrf=CSRF_CODEC,
            enrolment_refusals=enrolment_recorder(RecordingWriter()),  # SessionsAuth: gate off
        )
        app.include_router(router, prefix="/api/v1")
        transport = httpx.ASGITransport(app=app, client=(_CLIENT_IP, 50000))
        self.http = httpx.AsyncClient(transport=transport, base_url=BASE)

    async def start(self) -> None:
        """`AuditService.start()`: the writer, the lane's boot (its rows drained), the façade."""
        self.writer = _Sink(self.repo, self.path / "audit.wal", self.error, self.clock)
        await self.writer.start()
        shared, total = self.caps
        files = lj.LaneFiles(self.path / "lane")
        journal = lj.LaneJournal(files, _KEYS, shared_max_bytes=shared, lane_max_bytes=total)
        self.drain = _Lane(journal, self.writer, self.live)
        await self.drain.start()
        await self.drain.flush(_WAIT_S)
        facade = LaneFacade(self.writer, self.drain, lambda: self.flag)
        self.lane: LaneFacade | _Sink = self.writer if self.today else facade

    async def stop(self) -> None:
        """`AuditService.stop()`: the lane first, then the writer."""
        await self.drain.close()
        await self.writer.stop(_WAIT_S)

    async def restart(self) -> list[str]:
        """Stop, then start with the sink back: the callers' rows that reached the chain since."""
        await self.stop()
        held = len(self.repo.rows)
        await self.start()
        ids = [row["record_id"] for row in self.repo.rows]
        assert len(set(ids)) == len(ids)  # each record once
        return [r["action"] for r in self.repo.rows[held:] if not r["action"].startswith("audit.")]

    async def mint(self) -> MintedSession:
        return await self.svc.mint(str(USER))

    async def live(self) -> set[str]:
        return {str(s.id) for s in await self.sessions.find_live_by_user(str(USER))}

    async def logout(self, m: MintedSession, *, every: bool = False) -> httpx.Response:
        self.http.cookies.clear()
        body = {"all_sessions": every}
        return await self.http.post("/api/v1/auth/logout", json=body, headers=_bearer(m))

    async def revoke(self, m: MintedSession, target: uuid.UUID) -> httpx.Response:
        self.http.cookies.clear()
        return await self.http.delete(f"/api/v1/me/sessions/{target}", headers=_bearer(m))

    async def refresh(self, m: MintedSession) -> httpx.Response:
        self.http.cookies.clear()  # the body token is under test, never a cookie a reply set
        body, pair = {"refresh_token": m.refresh_token}, csrf_headers(CSRF_CODEC, m.session_id)
        return await self.http.post("/api/v1/auth/refresh", json=body, headers=pair)


Opener = Callable[..., Awaitable[_World]]


@pytest.fixture
async def worlds(tmp_path: Path) -> AsyncIterator[Opener]:
    """Opens started worlds in `tmp_path`; each is stopped at the end."""
    opened: list[_World] = []

    async def open_world(**kw: Any) -> _World:
        world = _World(tmp_path / str(len(opened)), **kw)
        await world.start()
        opened.append(world)
        return world

    yield open_world
    for world in opened:
        await world.stop()
        await world.http.aclose()


Answer = tuple[httpx.Response, set[str], set[str]]  # the answer, who was live before, what ends


async def _logout(w: _World, accept: int | None, *, every: bool) -> Answer:
    a, _ = await w.mint(), await w.mint()
    before, w.writer.accept = await w.live(), accept
    return await w.logout(a, every=every), before, before if every else {str(a.session_id)}


async def _revoke(w: _World, accept: int | None) -> Answer:
    a, b = await w.mint(), await w.mint()
    before, w.writer.accept = await w.live(), accept
    return await w.revoke(a, b.session_id), before, {str(b.session_id)}


async def _reuse(w: _World, accept: int | None) -> Answer:
    m = await w.mint()
    assert (await w.refresh(m)).status_code == 200  # `m`'s token is spent: its replay is reuse
    before, w.writer.accept = await w.live(), accept
    return await w.refresh(m), before, before  # the family, its live successor too


async def _race(w: _World, accept: int | None) -> Answer:
    """A live token whose refresh a competing request wins (`RacedSessionService`)."""
    m = await w.mint()
    before, w.writer.accept = await w.live(), accept
    return await w.refresh(m), before, before  # the family, the winner's successor too


async def _disabled(w: _World, accept: int | None) -> Answer:
    """A live token of a user disabled since (#2911): nothing is minted or rotated, and the session
    is revoked before its outcome row (#3331)."""
    m = await w.mint()
    w.sessions.user_statuses[str(USER)] = UserStatus.DISABLED
    before, w.writer.accept = await w.live(), accept
    return await w.refresh(m), before, before


@dataclass(frozen=True)
class _Row:
    act: Callable[[_World, int | None], Awaitable[Answer]]
    accept: int  # what the sink takes first: a refresh writes its own intent there, never the lane
    status: int  # the answer once the rows are written (by the lane, or a sink that takes them)
    lane: tuple[str, ...]  # the rows the lane holds, in order
    intents: int  # how many of them come before the action (C-2.9)
    both: int  # today's answer while the lane and the sink refuse
    refused: tuple[str, ...]  # what the sink refuses then
    lost: tuple[int, int, int] = (0, 0, 0)  # and today's `_lost()` deltas
    service: type[SessionService] = SessionService


_ONE, _EVERY = partial(_logout, every=False), partial(_logout, every=True)
_ALL = (_LOGOUT, _OUT, _OUT)
_ROWS = {
    "logout": _Row(_ONE, 0, 204, (_LOGOUT, _OUT), 1, 503, (_LOGOUT,)),
    "logout-all": _Row(_EVERY, 0, 204, _ALL, 1, 503, (_LOGOUT,)),
    "logout-outcomes": _Row(_EVERY, 1, 204, _ALL, 1, 204, (_OUT, _OUT), (2, 0, 0)),
    "revoke": _Row(_revoke, 0, 204, (_OUT,), 1, 503, (_OUT,)),
    "reuse": _Row(_reuse, 0, 401, (_REUSE,), 1, 503, (_REUSE,)),
    "race": _Row(_race, 1, 401, (_REUSE,), 0, 401, (_REUSE,), (0, 1, 0), RacedSessionService),
    "disabled": _Row(_disabled, 1, 401, (_REFRESHED,), 0, 401, (_REFRESHED,), (0, 0, 1)),
}
#: `logout-outcomes` is `logout-all` with a sink credit that only a fallback spends.
_LANE_TAKES = ("logout", "logout-all", "revoke", "reuse", "race", "disabled")
_WRITE_AHEAD = ("logout", "logout-all", "revoke", "reuse")
_OUTCOMES = ("logout-outcomes", "race", "disabled")


@pytest.mark.parametrize("make_error", _ERRORS, ids=["wal_unavailable", "writer_stopped"])
@pytest.mark.parametrize("name", _LANE_TAKES)
async def test_lane_takes_the_row_while_the_sink_refuses_and_the_chain_gets_it_after_a_restart(
    worlds: Opener, name: str, make_error: Callable[[], Exception]
) -> None:
    row = _ROWS[name]
    w, lost = await worlds(error=make_error(), service=row.service), _lost()
    answer, before, ended = await row.act(w, row.accept)
    assert answer.status_code == row.status  # signed out, revoked, or the refresh's own 401
    assert await w.live() == before - ended  # a reused token's family is revoked
    assert _lost() == lost and w.writer.refused == []  # nothing counted lost, no fallback
    # C-2.9: each intent while its targets were live, each outcome after the action.
    after = [before - ended] * (len(row.lane) - row.intents)
    assert w.drain.seen == [before] * row.intents + after
    assert await w.restart() == list(row.lane)  # every row reaches the chain once, in order


@pytest.mark.parametrize("name", _WRITE_AHEAD)
async def test_both_refusing_a_write_ahead_row_is_todays_503_and_nothing_changes(
    worlds: Opener, name: str
) -> None:
    row = _ROWS[name]
    w = await worlds(service=row.service)
    w.drain.journal.hold()  # every append is refused `held`, so the façade falls back
    lost = _lost()
    answer, before, _ = await row.act(w, row.accept)
    assert answer.status_code == 503
    assert await w.live() == before  # nothing signed out, revoked or rotated (C-2.9)
    assert _lost() == lost and w.writer.refused == list(row.refused)


@pytest.mark.parametrize("name", _OUTCOMES)
async def test_both_refusing_an_outcome_row_keeps_todays_answer_and_counts_it_lost(
    worlds: Opener, name: str
) -> None:
    row = _ROWS[name]
    w = await worlds(service=row.service)
    w.drain.journal.hold()  # every append is refused `held`, so the façade falls back
    lost = _lost()
    answer, before, ended = await row.act(w, row.accept)
    assert answer.status_code == row.both
    assert await w.live() == before - ended  # the action stands
    assert [b - a for a, b in zip(lost, _lost(), strict=True)] == list(row.lost)
    assert w.writer.refused == list(row.refused)


def _ids() -> Callable[[], uuid.UUID]:
    """A `uuid.uuid4` stand-in that gives each world the same ids in the same order."""
    counter = itertools.count(1)
    return lambda: uuid.UUID(int=next(counter))


async def _off(
    open_world: Opener, monkeypatch: pytest.MonkeyPatch, row: _Row, accept: int | None, today: bool
) -> tuple[Any, ...]:
    """One flag-off world's run of *row*: the answer (a cleared cookie's `expires` is the wall
    clock's, so it is dropped; all else is kept), the lost-counter deltas, the refusals and the
    rows. The lane must hold nothing."""
    monkeypatch.setattr(uuid, "uuid4", _ids())
    w = await open_world(flag=False, today=today, service=row.service)
    end, lost = w.drain.journal.end, _lost()
    answer, *_ = await row.act(w, accept)
    await w.writer.flush(_WAIT_S)
    assert w.drain.journal.end == end  # the lane holds nothing
    cleared = [(k, re.sub(r"expires=[^;]*; ", "", v)) for k, v in answer.headers.multi_items()]
    deltas = [b - a for a, b in zip(lost, _lost(), strict=True)]
    return answer.status_code, cleared, answer.content, deltas, w.writer.refused, w.repo.rows


_OFF = [(n, None, r.status) for n, r in _ROWS.items()] + [
    (n, r.accept, r.both) for n, r in _ROWS.items()
]


@pytest.mark.parametrize(
    ("name", "accept", "status"),
    _OFF,
    ids=[f"{n}-sink" for n in _ROWS] + [f"{n}-sink-refusing" for n in _ROWS],
)
async def test_flag_off_is_todays_path_byte_for_byte(
    worlds: Opener, monkeypatch: pytest.MonkeyPatch, name: str, accept: int | None, status: int
) -> None:
    """Off, the façade hands each row to the writer as `emit()` did. With the same ids and clock:
    the same answer, counters, refusals and rows as the writer as receiver, and today's answer."""
    today = await _off(worlds, monkeypatch, _ROWS[name], accept, today=True)
    off = await _off(worlds, monkeypatch, _ROWS[name], accept, today=False)
    assert off == today
    assert off[0] == status


async def test_login_flood_leaves_room_for_logout(worlds: Opener) -> None:
    """S1c's quotas (§15.6 Limits), with caps small enough to fill: `shared` records (the login rows
    #2914's PR C will write) fill their share while the sink refuses, and the overflow falls back
    and is refused; a sign-out, `reserved`, still fits and answers 204."""
    w = await worlds(caps=(4096, 8192))
    a, flood = await w.mint(), 64
    w.writer.accept = 0
    for _ in range(flood):
        with contextlib.suppress(AuditUnavailable):
            await w.lane.emit("auth.login_failed", actor_label="f", outcome=AuditOutcome.FAILURE)
    journaled = flood - len(w.writer.refused)
    assert 0 < journaled < flood and set(w.writer.refused) == {"auth.login_failed"}
    assert (await w.logout(a)).status_code == 204 and await w.live() == set()
    assert len(w.writer.refused) == flood - journaled  # the sign-out never fell back
    assert await w.restart() == ["auth.login_failed"] * journaled + [_LOGOUT, _OUT]


async def test_a_refresh_stays_fail_closed_while_the_sink_refuses(worlds: Opener) -> None:
    """Q1: a refresh writes its intent to the writer, never the lane, so while the sink refuses it
    is 503 and rotates nothing."""
    w = await worlds()
    m = await w.mint()
    end, w.writer.accept = w.drain.journal.end, 0
    assert (await w.refresh(m)).status_code == 503 and await w.live() == {str(m.session_id)}
    assert w.writer.refused == [_REFRESHED] and w.drain.journal.end == end


async def test_a_rotated_cookie_at_sign_out_is_the_writers_probe_row(worlds: Opener) -> None:
    """Q9: a rotated cookie presented to sign-out is the writer's probe row, never a `reserved`
    lane frame."""
    w = await worlds()
    m = await w.mint()
    assert (await w.refresh(m)).status_code == 200  # `m`'s refresh token is rotated away
    end, w.writer.accept = w.drain.journal.end, 0
    w.http.cookies.clear()  # only the rotated cookie, never the one the refresh set
    cookie = {"Cookie": f"{REFRESH_COOKIE}={m.refresh_token}"}
    assert (await w.http.post("/api/v1/auth/logout", headers=cookie)).status_code == 401
    assert w.writer.refused == [_REUSE] and w.drain.journal.end == end


def _bare(audit: Any) -> tuple[httpx.AsyncClient, SessionService]:
    """The router over *audit*, with no world's lane, and its session service."""
    svc = SessionService(FakeSessionRepository(), HASHER, clock=lambda: NOW)
    app = FastAPI()
    refusals = enrolment_recorder(RecordingWriter())  # SessionsAuth's enrolment gate is off
    router = make_session_router(
        SessionsAuth(svc), audit, identity=Identity(), csrf=CSRF_CODEC, enrolment_refusals=refusals
    )
    app.include_router(router, prefix="/api/v1")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE), svc


def _unwired() -> tuple[AuditService, RecordingWriter]:
    """A real service with a writer and no façade: `stop()` drops the façade before the writer,
    and test seams (rbac_harness) set a writer without `start()`."""
    audit, writer = AuditService(), RecordingWriter()
    audit._writer = writer  # type: ignore[assignment]  # set without `start()`: no façade
    return audit, writer


class _FailingLane:
    """An audit service whose `lane` fails for another reason than a missing façade."""

    is_active = True

    def __init__(self) -> None:
        self.writer = RecordingWriter()

    @property
    def lane(self) -> Any:
        raise RuntimeError("not a missing facade")


async def test_a_service_without_its_facade_writes_the_rows_to_the_writer() -> None:
    """`LaneNotWired`: a lane row takes today's path, never a 500."""
    audit, writer = _unwired()
    http, svc = _bare(audit)
    m = await svc.mint(str(USER))
    async with http:
        assert (await http.post("/api/v1/auth/logout", headers=_bearer(m))).status_code == 204
    assert [event["action"] for event in writer.events] == [_LOGOUT, _OUT]


async def test_a_service_without_its_facade_is_logged_once_with_the_action_alone() -> None:
    """S3-L1: the fallback is never silent, and one warning per router is enough."""
    audit, _ = _unwired()
    http, svc = _bare(audit)
    first, second = await svc.mint(str(USER)), await svc.mint(str(USER))
    async with http:
        with capture_logs() as logs:
            await http.post("/api/v1/auth/logout", headers=_bearer(first))
            await http.post("/api/v1/auth/logout", headers=_bearer(second))
    warned = [entry for entry in logs if entry["event"] == _UNWIRED]
    assert warned == [{"event": _UNWIRED, "log_level": "warning", "action": _LOGOUT}]


async def test_another_failure_of_the_lane_is_not_taken_for_a_missing_facade() -> None:
    """S3-L1: only `LaneNotWired` sends a lane row to the writer; any other error is a defect and
    propagates, with nothing written."""
    audit = _FailingLane()
    http, svc = _bare(audit)
    m = await svc.mint(str(USER))
    async with http:
        with pytest.raises(RuntimeError, match="not a missing facade"):
            await http.post("/api/v1/auth/logout", headers=_bearer(m))
    assert audit.writer.events == []
