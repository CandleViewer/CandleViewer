"""#3402: the reconcile step of `docs/ops/runbooks/auth-rbac.md` section 4 (#3120 AC7, the
compensating control of EX-08) tells a session a disable revoked from a backstop revocation whose
record was lost. The deployed app of `test_disable_user_e2e.py`, every record written through the
real `AuditWriter` into an in-memory `audit_log`: the Owner disables M, who has two live sessions,
through `DELETE /users/{userId}`; a third session of M escaped both the disable's transaction and
its sweep, and the backstop revokes it on its next use while the sink refuses records (the writer
has stopped). The step's lookup is the query `GET /admin/audit` runs for the Owner. So is its
fallback for a window from before #3402, whose `auth.session_revoked` records name no subject. The
runbook's literal of each is pinned to the one run here."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.models import AuditEntry
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import SessionService
from tests.csrf_helpers import csrf_headers
from tests.security.auth.test_disable_user_e2e import _M, _OWNER, _world
from tests.unit.audit.audit_fakes import FakeAuditRepository

_RUNBOOK = Path(__file__).resolve().parents[5] / "docs" / "ops" / "runbooks" / "auth-rbac.md"
#: The runbook's lookups (section 4, AC7), as the query of each `GET $API/admin/audit?...` it
#: gives; `<...>` stands for the value the operator fills in. The first reads the subject of the
#: two revocation records, the second is the fallback for a window from before #3402.
_BY_SESSION = {
    "action": ["auth.session_revoked", "auth.disabled_user_session_revoked"],
    "subject_type": ["session"],
    "subject_id": ["<id>"],
}
_BY_USER_AND_TIME = {
    "action": ["auth.session_revoked"],
    "actor_user_id": ["<user_id>"],
    "from": ["<start>"],
    "to": ["<end>"],
}


async def _read(audit_log: FakeAuditRepository, **filters: Any) -> list[AuditEntry]:
    """`GET /admin/audit` as the Owner reads it: the raw view, no scope. Each service owns a
    hashing pool, shut down here: left open, one idle thread stays behind per read."""
    with closing(AuditQueryService(audit_log)) as service:
        page = await service.query(restrict_to_actor=None, raw=True, **filters)
    return list(page.items)


async def _by_session(
    audit_log: FakeAuditRepository, session_id: str
) -> list[tuple[str, str | None]]:
    """The first lookup: each revocation record that names the session as its subject."""
    entries = await _read(
        audit_log,
        actions=_BY_SESSION["action"],
        subject_type=_BY_SESSION["subject_type"][0],
        subject_id=session_id,
    )
    return [(entry.action, entry.reason) for entry in entries]


async def _by_user_and_time(
    audit_log: FakeAuditRepository, user_id: str, start: datetime, end: datetime
) -> list[tuple[str, str | None]]:
    """The fallback: the user's records in the window, each as its session and its reason."""
    entries = await _read(
        audit_log,
        actions=_BY_USER_AND_TIME["action"],
        actor_user_id=user_id,
        from_ts=start,
        to_ts=end,
    )
    return [(str(entry.session_id), entry.reason) for entry in entries]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SimpleNamespace]:
    with _world() as (w, app, client):
        w.audit_log = FakeAuditRepository()
        wal = str(tmp_path_factory.mktemp("audit") / "audit.wal")
        writer = AuditWriter(w.audit_log, wal, sleep=w.audit_log.retry_sleep)
        assert client.portal is not None  # inside the client's `with`
        run, ctx = client.portal.call, app.state.app_context
        run(writer.start)
        ctx.audit._writer = writer
        # As `AuthService.start()` builds it: the backstop's audit port is the app's own.
        sessions = SessionService(
            w.repo,
            Hasher(),
            clock=w.clock,
            publish_revocation=ctx.auth._publish_revocation,
            backstop_audit=ctx.auth._audit_backstop,
        )
        ctx.auth._sessions = sessions
        run(ctx.rules.start, ctx)
        mine, w.a, w.b, w.e = (run(sessions.mint, u) for u in (str(_OWNER), *[str(_M)] * 3))
        until = w.clock.now + timedelta(minutes=5)  # the Owner's step-up for `users`
        sid = str(mine.session_id)
        run(w.repo.update_step_up_state, sid, lambda _: ({"users": until}, 0, None))
        headers = {"Authorization": f"Bearer {mine.access_token}"}
        headers |= csrf_headers(app.state.csrf_codec, mine.session_id)
        # Neither the disable's statement nor its sweep sees this session: it escapes both.
        escaped = w.repo.sessions.pop(str(w.e.session_id))
        path = f"/users/{_M}?acknowledge_unknown_positions=true"
        w.disabled = client.delete(path, headers=headers).status_code
        w.repo.sessions[str(w.e.session_id)] = escaped
        run(writer.flush, 5.0)
        run(writer.stop, 1.0)  # from here on the sink refuses every record
        bearer = {"Authorization": f"Bearer {w.e.access_token}"}
        with capture_logs() as logs:
            w.backstop = client.get("/auth/session", headers=bearer).status_code
        failed = "auth.disabled_user_session_audit_failed"
        w.refused = [line["error"] for line in logs if line["event"] == failed]
        w.revoked = {str(s.id): s.revoked_reason for s in w.repo.sessions.values()}
        yield w


@pytest.mark.parametrize("session", ["a", "b"])
async def test_the_lookup_finds_the_disables_record_of_a_session_it_revoked(
    world: SimpleNamespace, session: str
) -> None:
    """AC1: the disable's per-session revoke record (B16 REVOKE, R5) is found by the session."""
    sid = str(getattr(world, session).session_id)
    assert (world.disabled, world.revoked[sid]) == (204, "user_disabled")
    found = await _by_session(world.audit_log, sid)
    assert found == [("auth.session_revoked", "user_disabled")]


async def test_the_step_lists_only_the_backstop_revocation_whose_record_was_refused(
    world: SimpleNamespace,
) -> None:
    """AC2: of M's `user_disabled` rows, the step lists those with neither record: only the session
    that escaped the disable, which the backstop revoked on use (401) while the sink refused its
    record, although a `users.disable` record names M."""
    assert (world.backstop, world.refused) == (401, ["AuditWriterStopped"])
    rows = [sid for sid, reason in world.revoked.items() if reason == "user_disabled"]
    found = {sid: await _by_session(world.audit_log, sid) for sid in rows}
    unaudited = [sid for sid, records in found.items() if not records]
    assert unaudited == [str(world.e.session_id)]
    disable = await _read(
        world.audit_log, actions=["users.disable"], subject_type="user", subject_id=str(_M)
    )
    assert [entry.action for entry in disable] == ["users.disable"]


_START = datetime(2026, 10, 17, 6, 0, tzinfo=UTC)  # the runbook's example window: 06:00 to 07:00
_END = datetime(2026, 10, 17, 7, 1, tzinfo=UTC)  # a minute past it: B16 writes after the revoke
_OTHER = uuid.UUID(int=0x3402B)
_A, _B, _C, _D, _O = (str(uuid.UUID(int=0x3402A0 + n)) for n in range(5))


async def _written_before_3402() -> FakeAuditRepository:
    """`auth.session_revoked` as B16 wrote it before #3402: the session in `session_id`, its user
    the actor, no object. M's sessions `a` and `b` were revoked by a disable inside the window,
    `c` by a logout, and `d` by a disable before it; `o` is another user's."""
    minute = timedelta(minutes=1)
    rows = [
        (_M, _A, "user_disabled", _START + 10 * minute),
        (_M, _B, "user_disabled", _START + 10 * minute + timedelta(seconds=1)),
        (_M, _C, "logout", _START + 20 * minute),
        (_M, _D, "user_disabled", _START - 10 * minute),
        (_OTHER, _O, "user_disabled", _START + 10 * minute),
    ]
    audit_log = FakeAuditRepository()
    for n, (user, session, reason, at) in enumerate(rows):
        await audit_log.insert(
            {
                "record_id": str(uuid.UUID(int=0x3402F0 + n)),
                "action": "auth.session_revoked",
                "actor_label": str(user),
                "actor_user_id": str(user),
                "session_id": session,
                "outcome": "success",
                "severity": "warning",
                "reason": reason,
                "event_ts": at.isoformat(),
            }
        )
    return audit_log


async def test_the_first_lookup_misses_a_record_written_before_3402() -> None:
    """The limit the runbook states: the lookup by session reads the subject, which a record
    written before #3402 has none of, so it lists each session a disable revoked then."""
    audit_log = await _written_before_3402()
    assert [await _by_session(audit_log, sid) for sid in (_A, _B)] == [[], []]


async def test_the_fallback_finds_a_record_written_before_3402_by_its_user_and_time() -> None:
    """The fallback reads the session and the reason of the user's records in the window. A session
    that is the `session_id` of one with reason `user_disabled` is covered by the disable's own
    record; a logout's record, an earlier window's and another user's are not taken for it."""
    audit_log = await _written_before_3402()
    found = await _by_user_and_time(audit_log, str(_M), _START, _END)
    assert sorted(found) == sorted([(_A, "user_disabled"), (_B, "user_disabled"), (_C, "logout")])
    assert {sid for sid, reason in found if reason == "user_disabled"} == {_A, _B}


def _same_query(query: dict[str, list[str]]) -> dict[str, list[str]]:
    """A query's parameters, whatever the order of a repeated one."""
    return {name: sorted(values) for name, values in query.items()}


def test_the_runbook_gives_the_lookups_these_tests_run() -> None:
    """The operator copies the runbook's `GET` literals, so each is the query a test above runs:
    editing the runbook or `_BY_SESSION` and `_BY_USER_AND_TIME` alone fails here, as the reconcile
    command's read-only session is pinned in `tests/unit/auth/test_backstop_audit_port.py`."""
    runbook = _RUNBOOK.read_text(encoding="utf-8")
    section = runbook[runbook.index("## 4. Disable a user") : runbook.index("## 5. ")]
    given = [parse_qs(q) for q in re.findall(r"`GET \$API/admin/audit\?([^`\s]+)`", section)]
    assert list(map(_same_query, given)) == list(map(_same_query, [_BY_SESSION, _BY_USER_AND_TIME]))
