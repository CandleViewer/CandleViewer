"""#3009 S4b-1a, ADR-0037 decision 13 (Q9): a replay against a family this process contained writes
the `shared` `auth.refresh_reuse_replayed` row ahead; only a first containment intent is `reserved`.
A real writer (its flusher killable), lane journal, drain and façade in `tmp_path`, or the recording
writer; requests through `httpx.ASGITransport`. Each test runs on a `VirtualTimeLoop` (`@virtual`,
#3816), the drain's polls and retries a fake millisecond; the memo's clock is a fake. No sleeps."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.sessions import REPLAY_LOG_WINDOW_S, ContainedFamilies, make_session_router
from candleviewer.audit import lane_journal as lj
from candleviewer.audit.lane import REFUSALS, AuditLane, LaneFacade
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.errors import RefreshReuseDetected
from candleviewer.auth.models import MintedSession, RefreshOutcome
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.csrf_helpers import arm_csrf
from tests.unit.api._fakes import (
    BASE,
    CSRF_CODEC,
    HASHER,
    NOW,
    USER,
    AuditService,
    Identity,
    RacedSessionService,
    RecordingWriter,
    SessionsAuth,
    enrolment_recorder,
)
from tests.unit.audit.audit_fakes import FakeAuditRepository, FakeClock
from tests.unit.audit.audit_waits import virtual
from tests.unit.auth.session_fakes import FakeSessionRepository

_KEYS = lj.LaneKeys(bytes(range(32)))  # a test vector, never a key
_WAIT_S = 5.0  # fake seconds: a bound on what the drain or the flusher must do, never a sleep
_FAST: dict[str, Any] = {"retry_s": (0.001, 0.001), "poll_s": 0.001}  # a fake millisecond
_REUSE, _REPLAY = "auth.refresh_reuse_detected", "auth.refresh_reuse_replayed"
_LOGGED = "auth.refresh_reuse.replay_refused"


def _reuses() -> float:
    """`auth_refresh_reuse_total`, which the session service moves (process-global: deltas)."""
    return float(REGISTRY.get_sample_value("auth_refresh_reuse_total") or 0.0)


def _client(
    svc: SessionService, audit: Any, memo: ContainedFamilies | None = None
) -> httpx.AsyncClient:
    """The session router over *svc*, *audit* and *memo*, with roomy refresh throttles."""
    roomy = [PerIpLoginThrottle(max_attempts=10_000, clock=lambda: 0.0) for _ in range(2)]
    router = make_session_router(
        SessionsAuth(svc),
        audit,
        identity=Identity(),
        ip_throttle=roomy[0],
        session_throttle=roomy[1],
        csrf=CSRF_CODEC,
        enrolment_refusals=enrolment_recorder(RecordingWriter()),  # SessionsAuth: gate off
        contained=memo,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    transport = httpx.ASGITransport(app=app, client=("198.51.100.7", 50000))  # RFC 5737
    return httpx.AsyncClient(transport=transport, base_url=BASE)


async def _present(http: httpx.AsyncClient, member: MintedSession) -> int:
    """`POST /auth/refresh`, *member*'s refresh token in the body (a rotated one skips SR-041)."""
    body = {"refresh_token": member.refresh_token}
    return (await http.post("/api/v1/auth/refresh", json=body)).status_code


async def _family(svc: SessionService, rotations: int = 1) -> list[MintedSession]:
    """A new family's rotated-away members, oldest first; its live head is not among them."""
    members = [await svc.mint(str(USER))]
    for _ in range(rotations):
        members.append((await svc.refresh(members[-1].refresh_token)).minted)
    return members[:-1]


class _LostClaim(SessionService):
    """A concurrent request wins the claim on a live token: it rotates it and its successor lives,
    and this `refresh()` raises the race's reuse error, with no ids: nothing was revoked."""

    async def refresh(self, raw_refresh_token: str, **kw: Any) -> RefreshOutcome:
        await super().refresh(raw_refresh_token, **kw)  # a spent token raises the real reuse here
        raise RefreshReuseDetected("refresh token reuse detected (concurrent refresh)")


class _Lane:
    """The router's audit service over a real writer, lane and façade (journal-first) in *path*,
    started with its boot rows drained; `kill()`: a failed insert kills the writer's flusher."""

    is_active = True

    def __init__(
        self, path: Path, shared: int = lj.SHARED_MAX_BYTES, total: int = lj.LANE_MAX_BYTES
    ) -> None:
        self.repo, self.died = FakeAuditRepository(), asyncio.Event()
        wal, sleep = str(path / "audit.wal"), self.repo.retry_sleep
        alarm, clock = self._alarm, FakeClock()
        self.writer = AuditWriter(
            self.repo, wal, clock=clock, sleep=sleep, max_insert_attempts=1, on_alarm=alarm
        )
        files = lj.LaneFiles(path / "lane")
        self.journal = lj.LaneJournal(files, _KEYS, shared_max_bytes=shared, lane_max_bytes=total)
        self.drain = AuditLane(self.journal, self.writer, **_FAST)
        self.lane = LaneFacade(self.writer, self.drain)
        self.svc = SessionService(FakeSessionRepository(), HASHER, clock=lambda: NOW)
        self.http = _client(self.svc, self)

    async def __aenter__(self) -> _Lane:
        await self.writer.start()
        await self.drain.start()
        await self.drain.flush(_WAIT_S)
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.drain.close()
        await self.writer.stop(_WAIT_S)
        await self.http.aclose()

    async def _alarm(self, _reason: str) -> None:
        self.died.set()

    async def kill(self) -> None:
        self.repo.down = True
        await self.writer.emit("auth.login", actor_label="lost-for-now")
        await self.died.wait()

    def refusals(self) -> tuple[int, int, int]:
        """The lane's `reserved` and `shared` refusals, every reason (`cv_audit_lane_refused_total`
        by class), and the writer's `auth` ones (`cv_audit_writer_refused_total{domain}`)."""
        lane = [sum(self.lane.refused[c, why] for why in REFUSALS) for c in ("reserved", "shared")]
        return lane[0], lane[1], self.writer.refused_by_domain["auth"]


@virtual
async def test_the_first_containment_intent_stays_reserved_and_a_replay_takes_the_shared_id(
    tmp_path: Path,
) -> None:
    """A later presentation of the rotated token, or of another rotated member of its family, is
    the `shared` replay row; the 401 stands, and a replay both lane and sink refuse is the 503."""
    async with _Lane(tmp_path) as w:
        first, second = await _family(w.svc, rotations=2)
        reserved, shared = w.journal.appended["reserved"], w.journal.appended["shared"]
        assert [await _present(w.http, m) for m in (first, second, first)] == [401] * 3
        assert w.journal.appended == {"reserved": reserved + 1, "shared": shared + 2}
        await w.drain.flush(_WAIT_S)
        rows = [(r["action"], r["outcome"], r["severity"]) for r in w.repo.rows]
        written = [row for row in rows if row[0].startswith("auth.")]
        assert written == [(_REUSE, "denied", "critical")] + [(_REPLAY, "denied", "warning")] * 2
        w.journal.hold()  # every append is refused `held`, so the façade falls back
        await w.kill()
        assert await _present(w.http, second) == 503


@virtual
async def test_a_replay_flood_leaves_the_reserved_waiters_untouched(tmp_path: Path) -> None:
    """As the login flood test, with caps small enough to fill and the flusher dead: concurrent
    replays fill the `shared` share, the rest are refused there and by the writer (503, counted
    as `shared` refusals). No `reserved` frame, byte or refusal (`busy`: its waiters), so a
    sign-out after the flood is journaled and answers 204."""
    async with _Lane(tmp_path, shared=4096, total=8192) as w:
        (member,), signed_in = await _family(w.svc), await w.svc.mint(str(USER))
        assert await _present(w.http, member) == 401  # the family's containment: `reserved`
        await w.drain.flush(_WAIT_S)  # its frame drained: nothing moves the marker once it dies
        await w.kill()
        reserved, appended = w.journal.class_bytes[0], dict(w.journal.appended)
        refused, flood = w.refusals(), 2 * lj.LANE_WAITERS["shared"]
        statuses = await asyncio.gather(*(_present(w.http, member) for _ in range(flood)))
        journaled, bounced = statuses.count(401), statuses.count(503)
        assert 0 < journaled < flood and journaled + bounced == flood
        assert w.journal.appended == {**appended, "shared": appended["shared"] + journaled}
        assert w.journal.class_bytes[0] == reserved and w.lane.refused["shared", "full"] > 0
        assert w.refusals() == (refused[0], refused[1] + bounced, refused[2] + bounced)
        bearer = {"Authorization": f"Bearer {signed_in.access_token}"}
        logout = await w.http.post(
            "/api/v1/auth/logout", json={"all_sessions": False}, headers=bearer
        )
        assert logout.status_code == 204
        assert w.journal.appended["reserved"] == appended["reserved"] + 2  # intent and outcome


@virtual
async def test_every_refused_replay_is_counted_and_the_first_per_family_per_window_is_logged() -> (
    None
):
    """The session service counts each replay (`auth_refresh_reuse_total`); one warning per family
    per window names the presented session only, a new window logs again, another family its own."""
    now, audit = [100.0], AuditService()
    svc = SessionService(FakeSessionRepository(), HASHER, clock=lambda: NOW)
    (a,), (b,) = await _family(svc), await _family(svc)
    async with _client(svc, audit, ContainedFamilies(clock=lambda: now[0])) as http:
        assert [await _present(http, m) for m in (a, b)] == [401, 401]  # their containments
        reuses = _reuses()
        with capture_logs() as logs:
            assert [await _present(http, m) for m in (a, a, a, b, b)] == [401] * 5
            now[0] += REPLAY_LOG_WINDOW_S  # the next window
            assert await _present(http, a) == 401
    assert _reuses() - reuses == 6  # every replay
    lines = [entry for entry in logs if entry["event"] == _LOGGED]
    assert [(e["log_level"], e["session_id"]) for e in lines] == [
        ("warning", str(m.session_id)) for m in (a, b, a)
    ]
    assert all(set(entry) == {"event", "log_level", "session_id"} for entry in lines)
    assert a.refresh_token not in repr(logs) and b.refresh_token not in repr(logs)


@virtual
async def test_the_contained_family_memo_is_bounded_and_a_restart_rearms_one_reserved_intent() -> (
    None
):
    """At most `max_ids` ids, the oldest containment forgotten first, none past `ttl_s`: a family
    forgotten so, or by a restart (a new router), takes the `reserved` intent once more (safe)."""
    now, audit = [100.0], AuditService()
    memo = ContainedFamilies(max_ids=4, ttl_s=60.0, clock=lambda: now[0])  # two families of two
    svc = SessionService(FakeSessionRepository(), HASHER, clock=lambda: NOW)
    (a,), (b,), (c,) = [await _family(svc) for _ in range(3)]
    async with _client(svc, audit, memo) as http:
        for m in (a, b, a, c):  # `a`'s replay renews its family, so `c` evicts `b`'s
            assert await _present(http, m) == 401
        assert len(memo) == 4
        assert [await _present(http, m) for m in (b, b)] == [401, 401]  # re-armed, held again
        now[0] += 60.0  # the TTL
        assert [await _present(http, m) for m in (b, b)] == [401, 401]
    async with _client(svc, audit) as http:  # a restart: a new process's memo
        assert [await _present(http, m) for m in (b, b)] == [401, 401]
    first, again = [_REUSE, _REUSE, _REPLAY, _REUSE], [_REUSE, _REPLAY]
    assert [event["action"] for event in audit.writer.events] == first + again * 3


@virtual
async def test_a_lost_claim_race_holds_no_family_so_the_real_reuse_stays_reserved() -> None:
    """The race revokes nothing, so it holds no family: the token's next presentation, the one that
    does contain it, is the `reserved` intent, and only the one after that is a replay."""
    audit = AuditService()
    svc = _LostClaim(FakeSessionRepository(), HASHER, clock=lambda: NOW)
    member = await svc.mint(str(USER))
    async with _client(svc, audit) as http:
        arm_csrf(http, CSRF_CODEC, member.session_id)  # the live token's SR-041 pair
        assert [await _present(http, member) for _ in range(3)] == [401] * 3
    race = ["auth.session_refreshed", _REUSE]  # the race's write-ahead intent, then its outcome row
    assert [event["action"] for event in audit.writer.events] == [*race, _REUSE, _REPLAY]


@virtual
async def test_each_replay_the_service_refuses_renews_the_familys_ttl() -> None:
    """The TTL runs from a family's last containment: a replay 40 s in holds it another `ttl_s`,
    so the next, 40 s on and past the first 60 s, is still the `shared` row."""
    now, audit = [100.0], AuditService()
    memo = ContainedFamilies(ttl_s=60.0, clock=lambda: now[0])
    svc = SessionService(FakeSessionRepository(), HASHER, clock=lambda: NOW)
    (member,) = await _family(svc)
    async with _client(svc, audit, memo) as http:
        assert await _present(http, member) == 401  # contained at 100: held to 160
        for _ in range(2):  # the replay at 140 renews it to 200, so the one at 180 is held too
            now[0] += 40.0
            assert await _present(http, member) == 401
    assert [event["action"] for event in audit.writer.events] == [_REUSE, _REPLAY, _REPLAY]


@virtual
async def test_a_refresh_that_loses_to_a_rotation_holds_the_family_its_service_revoked() -> None:
    """A refresh the route took as live and the service found rotated (it lost a race) revokes the
    family and carries its ids: the token's next presentation is the `shared` replay row, not a
    second `reserved` containment."""
    audit = AuditService()
    svc = RacedSessionService(FakeSessionRepository(), HASHER, clock=lambda: NOW)
    member = await svc.mint(str(USER))
    async with _client(svc, audit) as http:
        arm_csrf(http, CSRF_CODEC, member.session_id)  # the live token's SR-041 pair
        assert [await _present(http, member) for _ in range(2)] == [401] * 2
    race = ["auth.session_refreshed", _REUSE]  # the race's write-ahead intent, then its outcome row
    assert [event["action"] for event in audit.writer.events] == [*race, _REPLAY]


@virtual
async def test_the_revoked_head_of_a_contained_family_is_refused_with_no_replay_row() -> None:
    """Only a rotated token is a replay. The family's head is held by the memo, but it is revoked
    as `rotation_reuse`, not `rotated`: refused as any revoked session is, with no replay row."""
    audit, memo = AuditService(), ContainedFamilies()
    svc = SessionService(FakeSessionRepository(), HASHER, clock=lambda: NOW)
    first = await svc.mint(str(USER))
    head = (await svc.refresh(first.refresh_token)).minted
    async with _client(svc, audit, memo) as http:
        arm_csrf(http, CSRF_CODEC, head.session_id)  # the head's SR-041 pair: no rotated token
        assert await _present(http, first) == 401  # contains the family, the head with it
        assert memo.contains(str(head.session_id))
        assert await _present(http, head) == 401
    assert _REPLAY not in [event["action"] for event in audit.writer.events]
