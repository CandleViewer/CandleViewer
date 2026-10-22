"""#2914 PR C (ADR-0037 Q2): the login router hands its outcome and refusal rows to the audit lane's
façade, as the session router does (`api/sessions.py`).

The real `LaneFacade` over an in-memory lane and a writer that was never started, so the sink
refuses every record (`AuditWriterStopped`): a row the lane takes is journaled and the answer
stands; a row both refuse is counted lost (`auth_audit_outcome_lost_total`), logged with the action
and the error class only, and the answer stands. A service with no façade (`LaneNotWired`) hands the
row to the writer and says so once; any other failure is a defect, counted and raised. Each write is
bounded by the audit timeout, and a cancelled one is counted too. In process, no network: the loop's
clock is advanced, never waited on.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.auth import make_auth_router
from candleviewer.api.csrf import AUDIT_TIMEOUT_S
from candleviewer.audit import lane_journal as lj
from candleviewer.audit.lane import AuditLane, LaneFacade
from candleviewer.audit.models import AuditEmission, AuditOutcome
from candleviewer.audit.service import AuditService
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.errors import InvalidCredentials
from candleviewer.auth.models import LoginRequest
from tests.unit.api._fakes import BASE, CSRF_CODEC, RecordingWriter
from tests.unit.audit.audit_fakes import FakeAuditRepository
from tests.unit.auth.session_fakes import LoopClock

_FAILED = "auth.login_failed"
_LOST, _UNWIRED = "auth.login_audit.outcome_lost", "auth.login_audit.lane_unavailable"
_BODY = {"identifier": "alice", "password": "pw-unit-only"}  # never a credential
_WRONG = (401, "Username or password is incorrect")


class _WrongPassword:
    """`/auth/login`'s service: every password is wrong, so the route writes `auth.login_failed`."""

    async def login(self, request: LoginRequest, *, source_ip: str) -> object:
        raise InvalidCredentials(_WRONG[1])


class _Auth:
    is_active = True
    mfa_is_active = sessions_is_active = False
    login = _WrongPassword()


class _Journal:
    """The lane (an `AuditLane` stand-in): it keeps each record, or refuses it for *refusal*."""

    def __init__(self, refusal: lj.LaneReason | None = None) -> None:
        self.records: list[AuditEmission] = []
        self.refusal = refusal

    async def append(self, record: AuditEmission) -> int:
        if self.refusal is not None:
            raise lj.LaneRefused(self.refusal)
        self.records.append(record)
        return len(self.records)


class _Audit:
    """A started service as the router sees it: a writer that refuses every record, as a stopped
    sink does, and the real façade over *journal*."""

    is_active = True

    def __init__(self, tmp_path: Path, journal: _Journal) -> None:
        self.writer = AuditWriter(FakeAuditRepository(), str(tmp_path / "audit.wal"))
        self.lane = LaneFacade(self.writer, cast(AuditLane, journal))


class _Stuck:
    """A façade that does not answer until the request's own bound ends the write."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def emit(self, action: str, **row: Any) -> None:
        self.entered.set()
        try:
            await asyncio.wait_for(asyncio.Event().wait(), timeout=5)  # bounded: fails, not hangs
        except TimeoutError:
            raise AssertionError("the request's own bound never ended the write") from None


class _Defect:
    """A façade that fails for another reason than the sink's refusal."""

    async def emit(self, action: str, **row: Any) -> None:
        raise ValueError("not the sink's refusal")


class _Service:
    """An active service with *lane* as its façade and a recording writer."""

    is_active = True

    def __init__(self, lane: object) -> None:
        self.writer, self._lane = RecordingWriter(), lane

    @property
    def lane(self) -> Any:
        if isinstance(self._lane, Exception):
            raise self._lane
        return self._lane


def _client(audit: object) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(make_auth_router(cast(Any, _Auth()), cast(Any, audit), csrf=CSRF_CODEC))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


def _lost() -> float:
    return float(
        REGISTRY.get_sample_value("auth_audit_outcome_lost_total", {"action": _FAILED}) or 0
    )


async def _sign_in(audit: object) -> tuple[int, str]:
    async with _client(audit) as http:
        reply = await http.post("/auth/login", json=_BODY)
    return reply.status_code, reply.json()["detail"]


async def test_a_row_the_lane_takes_while_the_sink_refuses_is_journaled_and_the_401_stands(
    tmp_path: Path,
) -> None:
    journal, lost = _Journal(), _lost()

    assert await _sign_in(_Audit(tmp_path, journal)) == _WRONG

    (row,) = journal.records  # `shared`, any outcome (ADR-0037 decision 3)
    assert (row.action, row.outcome, row.actor_label) == (
        _FAILED,
        AuditOutcome.FAILURE,
        "ali***(len=5)",  # the redacted identifier, never the one sent (C-12.6)
    )
    assert _lost() == lost


async def test_a_row_the_lane_and_the_sink_both_refuse_is_counted_lost_and_the_401_stands(
    tmp_path: Path,
) -> None:
    journal, lost = _Journal("held"), _lost()

    with capture_logs() as logs:
        assert await _sign_in(_Audit(tmp_path, journal)) == _WRONG

    assert journal.records == [] and _lost() - lost == 1
    assert [e for e in logs if e["event"] == _LOST] == [
        {"event": _LOST, "log_level": "error", "action": _FAILED, "error": "AuditWriterStopped"}
    ]  # the action and the error class only: no identifier, address or token (C-12.6)


async def test_a_row_with_no_audit_sink_is_counted_lost_as_inactive() -> None:
    lost = _lost()

    with capture_logs() as logs:
        assert await _sign_in(None) == _WRONG

    assert _lost() - lost == 1
    assert [e["error"] for e in logs if e["event"] == _LOST] == ["inactive"]


async def test_a_service_without_its_facade_hands_the_row_to_the_writer_and_says_so_once() -> None:
    """`LaneNotWired` (before `start()`, or once `stop()` began): the writer alone, as before."""
    audit, writer = AuditService(), RecordingWriter()
    cast(Any, audit)._writer = writer  # set without `start()`, so there is no façade

    async with _client(audit) as http:
        with capture_logs() as logs:
            for _ in range(2):
                assert (await http.post("/auth/login", json=_BODY)).status_code == 401

    assert [event["action"] for event in writer.events] == [_FAILED, _FAILED]
    assert [e for e in logs if e["event"] == _UNWIRED] == [
        {"event": _UNWIRED, "log_level": "warning", "action": _FAILED}
    ]


async def test_another_failure_of_the_lane_is_a_defect_counted_and_raised() -> None:
    """Only `LaneNotWired` sends a row to the writer; nothing is written."""
    audit, lost = _Service(RuntimeError("not a missing facade")), _lost()

    with pytest.raises(RuntimeError, match="not a missing facade"):
        await _sign_in(audit)

    assert audit.writer.events == [] and _lost() - lost == 1


async def test_a_defect_of_the_write_is_counted_and_raised() -> None:
    lost = _lost()

    with capture_logs() as logs, pytest.raises(ValueError, match="not the sink's refusal"):
        await _sign_in(_Service(_Defect()))

    assert _lost() - lost == 1
    assert [e["error"] for e in logs if e["event"] == _LOST] == ["ValueError"]


async def test_a_row_that_never_returns_is_bounded_and_counted_as_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stuck = _Stuck()
    clock, lost = LoopClock(monkeypatch), _lost()
    async with _client(_Service(stuck)) as http:
        request = asyncio.create_task(http.post("/auth/login", json=_BODY))
        await asyncio.wait_for(stuck.entered.wait(), timeout=5)
        with capture_logs() as logs:
            clock.advance(AUDIT_TIMEOUT_S)  # the bound expires; the real clock has not moved
            reply = await asyncio.wait_for(request, timeout=5)

    assert (reply.status_code, reply.json()["detail"]) == _WRONG
    assert _lost() - lost == 1
    assert [e["error"] for e in logs if e["event"] == _LOST] == ["timeout"]


async def test_a_row_cancelled_in_flight_is_counted_and_the_cancellation_goes_on() -> None:
    stuck, lost = _Stuck(), _lost()
    async with _client(_Service(stuck)) as http:
        request = asyncio.create_task(http.post("/auth/login", json=_BODY))
        await asyncio.wait_for(stuck.entered.wait(), timeout=5)
        with capture_logs() as logs:
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request

    assert _lost() - lost == 1
    assert [e["error"] for e in logs if e["event"] == _LOST] == ["cancelled"]
