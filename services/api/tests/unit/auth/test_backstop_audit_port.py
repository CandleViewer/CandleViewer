"""#3120: `require_active` hands each revocation of a disabled user's session to an injected audit
port (C-2.9; `auth` may not import `audit`). The order is revoke, count and log, publish, then the
port, only for the call whose conditional revoke changed the row (#3029). The port never
decides the revocation: one that fails, hangs or is cancelled leaves the revocation, the signal and
the refusal as they were. Its writer side is `tests/unit/api/test_session_backstop_audit.py`, its
wiring through `create_app()` `tests/security/auth/test_backstop_audit_wiring.py`."""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.csrf import AUDIT_TIMEOUT_S
from candleviewer.auth.errors import SessionRevoked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import UserStatus
from candleviewer.auth.service import AuthService
from candleviewer.auth.session_service import BackstopRevocation, SessionService

from .session_fakes import FakeSessionRepository, LostRaceRepository, YieldingFindRepository

_NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
_RUNBOOK = Path(__file__).resolve().parents[5] / "docs" / "ops" / "runbooks" / "auth-rbac.md"
_BREACH = "auth_disabled_user_sessions_revoked_total"
_FAILED, _SLOW = "auth.disabled_user_session_audit_failed", "auth.disabled_user_session_audit_slow"
_DISABLED = UserStatus.DISABLED


async def _accepts(revocation: BackstopRevocation) -> None:
    return None


async def _delivers(session_id: str, reason: str) -> None:
    return None


class _Rig:
    """A service whose audit port records what it receives, then runs `on_audit`, and whose
    publish records what it is given, then runs `on_publish` (a test swaps either to make it fail,
    hang or look at the world)."""

    def __init__(self, repo: FakeSessionRepository | None = None, timeout_s: float = 2.0) -> None:
        self.repo = repo or FakeSessionRepository()
        self.received: list[BackstopRevocation] = []
        self.published: list[tuple[str, str]] = []
        self.on_audit: Callable[[BackstopRevocation], Awaitable[None]] = _accepts
        self.on_publish: Callable[[str, str], Awaitable[None]] = _delivers

        async def publish(session_id: str, reason: str) -> None:
            self.published.append((session_id, reason))
            await self.on_publish(session_id, reason)

        async def port(revocation: BackstopRevocation) -> None:
            self.received.append(revocation)
            await self.on_audit(revocation)

        self.service = SessionService(
            self.repo,
            Hasher(pepper=os.urandom(16).hex()),
            clock=lambda: _NOW,
            publish_revocation=publish,
            backstop_audit=port,
            backstop_audit_timeout_s=timeout_s,
        )

    async def stray(self, status: UserStatus | None = _DISABLED) -> str:
        """The id of a live session whose user's status is *status*, with no sweep run."""
        user = str(uuid.uuid4())
        sid = str((await self.service.mint(user)).session_id)
        self.repo.user_statuses[user] = status
        return sid


def _sample() -> float:
    return REGISTRY.get_sample_value(_BREACH) or 0.0


def _events(logs: list[Any], event: str) -> list[dict[str, Any]]:
    return [entry for entry in logs if entry["event"] == event]


@pytest.mark.parametrize("status", [_DISABLED, None], ids=["disabled", "gone"])
async def test_the_port_gets_the_revocation_after_the_signal(status: UserStatus | None) -> None:
    """The record is the last step, so a port that fails or hangs cannot hide the signal."""
    rig, seen = _Rig(), []
    sid = await rig.stray(status)
    before = _sample()

    async def look(revocation: BackstopRevocation) -> None:
        row = rig.repo.sessions[sid]
        seen.append(
            (row.revoked_reason, rig.published[:], _sample() - before, [e["event"] for e in logs])
        )

    rig.on_audit = look
    with capture_logs() as logs, pytest.raises(SessionRevoked):
        await rig.service.require_active(sid)

    row = rig.repo.sessions[sid]
    assert rig.received == [BackstopRevocation(row.id, row.user_id, status)]
    assert seen == [
        ("user_disabled", [(sid, "user_disabled")], 1.0, ["auth.disabled_user_session_revoked"])
    ]


async def test_three_racing_requests_write_one_record() -> None:
    rig = _Rig(YieldingFindRepository())
    sid = await rig.stray()

    outcomes = await asyncio.gather(
        *(rig.service.require_active(sid) for _ in range(3)), return_exceptions=True
    )

    assert [o.reason for o in outcomes if isinstance(o, SessionRevoked)] == ["user_disabled"] * 3
    assert len(rig.received) == 1


@pytest.mark.parametrize(
    ("repo_type", "status", "swept"),
    [
        (LostRaceRepository, _DISABLED, False),
        (FakeSessionRepository, _DISABLED, True),
        (FakeSessionRepository, UserStatus.ACTIVE, False),
        (FakeSessionRepository, UserStatus.LOCKED, False),
    ],
    ids=["lost_the_revoke", "swept_by_a_disable", "active", "locked"],
)
async def test_a_call_that_revoked_nothing_writes_no_record(
    repo_type: type[FakeSessionRepository], status: UserStatus, swept: bool
) -> None:
    rig = _Rig(repo_type())
    sid = await rig.stray(status)
    if swept:
        await rig.service.revoke(sid, reason="user_disabled")  # the disable's own sweep

    with contextlib.suppress(SessionRevoked):  # refused or not: the record is what is pinned
        await rig.service.require_active(sid)

    assert rig.received == []


@pytest.mark.parametrize(
    "failure", [RuntimeError("down: canary-text"), TimeoutError()], ids=["raises", "times_out"]
)
async def test_a_failing_port_changes_nothing_but_an_error_log(failure: Exception) -> None:
    """Sink down: the revocation, publish, count, WARNING and refusal stand, the record is dropped
    (never queued), and the log names the ids and the error class, never its text."""
    rig = _Rig()
    sid = await rig.stray()
    before = _sample()

    async def down(revocation: BackstopRevocation) -> None:
        raise failure

    rig.on_audit = down
    with capture_logs() as logs, pytest.raises(SessionRevoked) as refused:
        await rig.service.require_active(sid)

    row = rig.repo.sessions[sid]
    assert (refused.value.reason, row.revoked_reason) == ("user_disabled", "user_disabled")
    assert rig.published == [(sid, "user_disabled")] and _sample() == before + 1
    assert len(_events(logs, "auth.disabled_user_session_revoked")) == 1
    (failed,) = _events(logs, _FAILED)
    assert (failed["log_level"], failed["session_id"], failed["user_id"], failed["error"]) == (
        "error",
        sid,
        str(row.user_id),
        type(failure).__name__,
    )
    assert _events(logs, _SLOW) == [] and "canary-text" not in str(logs)


async def test_a_port_that_never_completes_does_not_hold_the_refusal() -> None:
    """The wait is bounded: the refusal comes back at the bound, the port is cancelled (the real
    one shields its write), and the log says the record may still land."""
    rig = _Rig(timeout_s=0.05)
    sid = await rig.stray()
    cancelled: list[bool] = []

    async def hangs(revocation: BackstopRevocation) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    rig.on_audit = hangs
    with capture_logs() as logs, pytest.raises(SessionRevoked) as refused:
        await asyncio.wait_for(rig.service.require_active(sid), 5.0)

    assert (refused.value.reason, cancelled) == ("user_disabled", [True])
    assert rig.repo.sessions[sid].revoked_reason == "user_disabled" and len(rig.published) == 1
    (slow,) = _events(logs, _SLOW)
    user = str(rig.repo.sessions[sid].user_id)
    assert (slow["log_level"], slow["session_id"], slow["user_id"]) == ("warning", sid, user)
    assert _events(logs, _FAILED) == []


async def test_cancelling_the_request_while_the_port_waits_propagates() -> None:
    """A cancel is honoured, not swallowed as a sink failure; the revocation already stands."""
    rig = _Rig()
    sid = await rig.stray()
    entered = asyncio.Event()

    async def waits(revocation: BackstopRevocation) -> None:
        entered.set()
        await asyncio.Event().wait()

    rig.on_audit = waits
    with capture_logs() as logs:
        request = asyncio.create_task(rig.service.require_active(sid))
        await asyncio.wait_for(entered.wait(), 5.0)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request

    assert rig.repo.sessions[sid].revoked_reason == "user_disabled" and len(rig.published) == 1
    assert _events(logs, _FAILED) == [] and _events(logs, _SLOW) == []


async def test_cancelling_the_request_while_the_revocation_is_published_drops_the_record() -> None:
    """The port comes after the publish, which suspends: a request cancelled there never reaches
    it, so that record is lost, and the runbook's reconcile step is what finds it. The revocation
    and the signal stand, since the count and the log come before the publish (#3029)."""
    rig = _Rig()
    sid = await rig.stray()
    before = _sample()
    entered = asyncio.Event()

    async def parked(session_id: str, reason: str) -> None:
        entered.set()
        await asyncio.Event().wait()

    rig.on_publish = parked
    with capture_logs() as logs:
        request = asyncio.create_task(rig.service.require_active(sid))
        await asyncio.wait_for(entered.wait(), 5.0)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(request, 5.0)

    assert rig.repo.sessions[sid].revoked_reason == "user_disabled"
    assert _sample() == before + 1 and len(_events(logs, "auth.disabled_user_session_revoked")) == 1
    assert rig.received == []


async def _auth_service_with_a_stray_session() -> tuple[AuthService, FakeSessionRepository, str]:
    repo = FakeSessionRepository()
    auth = AuthService(session_repository=repo, clock=lambda: _NOW)
    ctx: Any = None  # no settings: not a live environment, so process-local keys are used
    await auth.start(ctx)
    user = str(uuid.uuid4())
    sid = str((await auth.sessions.mint(user)).session_id)
    repo.user_statuses[user] = _DISABLED
    return auth, repo, sid


async def test_auth_service_hands_the_revocation_to_the_port_attached_after_start() -> None:
    """As the revocation sink: looked up per call, so the order of `attach` and `start` is free."""
    auth, _repo, sid = await _auth_service_with_a_stray_session()
    received: list[BackstopRevocation] = []

    async def port(revocation: BackstopRevocation) -> None:
        received.append(revocation)

    auth.attach_backstop_audit(port)
    with pytest.raises(SessionRevoked):
        await auth.sessions.require_active(sid)
    await auth.stop(grace_s=1.0)

    assert [str(r.session_id) for r in received] == [sid]


async def test_auth_service_with_no_port_attached_still_refuses_and_says_so() -> None:
    """A missing port is a wiring fault, not a reason to skip the record in silence."""
    auth, repo, sid = await _auth_service_with_a_stray_session()

    with capture_logs() as logs, pytest.raises(SessionRevoked):
        await auth.sessions.require_active(sid)
    await auth.stop(grace_s=1.0)

    assert repo.sessions[sid].revoked_reason == "user_disabled"
    assert [e["error"] for e in _events(logs, _FAILED)] == ["BackstopAuditNotAttached"]


@contextlib.contextmanager
def _recorded_timeouts() -> Iterator[list[float | None]]:
    """The delay of every `asyncio.timeout` opened inside the block."""
    bounds: list[float | None] = []
    real_timeout = asyncio.timeout

    def spy(delay: float | None) -> asyncio.Timeout:
        bounds.append(delay)
        return real_timeout(delay)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(asyncio, "timeout", spy)
        yield bounds


async def test_auth_service_bounds_the_port_by_the_two_seconds_the_runbook_promises() -> None:
    """Every other test injects its own bound. Built as production builds it, by
    `AuthService.start()`, the service gives the port the wait of the CSRF refusal audits, 2
    seconds: the runbook's "never holds the `401` for more than 2 seconds" rests on it. `auth` may
    not import `api`, so the number is repeated there, and this keeps the two together."""
    auth, _repo, sid = await _auth_service_with_a_stray_session()
    auth.attach_backstop_audit(_accepts)

    with _recorded_timeouts() as bounds, pytest.raises(SessionRevoked):
        await auth.sessions.require_active(sid)
    await auth.stop(grace_s=1.0)

    assert bounds == [2.0] and bounds == [AUDIT_TIMEOUT_S]


async def test_the_bound_a_caller_injects_is_the_one_the_port_waits() -> None:
    rig = _Rig(timeout_s=0.25)
    sid = await rig.stray()

    with _recorded_timeouts() as bounds, pytest.raises(SessionRevoked):
        await rig.service.require_active(sid)

    assert bounds == [0.25]


def test_the_runbooks_reconcile_command_opens_a_read_only_session() -> None:
    """Operator-run SQL on production (auth-rbac.md section 4): a copy-paste edit cannot write."""
    runbook = _RUNBOOK.read_text(encoding="utf-8")
    command = runbook[runbook.index("in a read-only session") :].split("<<'SQL'")[0]
    assert "-e PGOPTIONS='-c default_transaction_read_only=on'" in command
