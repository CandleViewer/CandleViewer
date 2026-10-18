"""#3402: the reconcile step of `docs/ops/runbooks/auth-rbac.md` section 4 (#3120 AC7, the
compensating control of EX-08) tells a session a disable revoked from a backstop revocation whose
record was lost. The deployed app of `test_disable_user_e2e.py`, every record written through the
real `AuditWriter` into an in-memory `audit_log`: the Owner disables M, who has two live sessions,
through `DELETE /users/{userId}`; a third session of M escaped both the disable's transaction and
its sweep, and the backstop revokes it on its next use while the sink refuses records (the writer
has stopped). The step's lookup is the query `GET /admin/audit` runs for the Owner."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace

import pytest
from structlog.testing import capture_logs

import candleviewer.app as appmod
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import SessionService
from candleviewer.rules.manager import InMemoryRuleStore
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from tests.csrf_helpers import csrf_headers
from tests.security.auth.test_disable_user_drill import _Clock
from tests.security.auth.test_disable_user_e2e import (
    _M,
    _OWNER,
    _delegate,
    _Rows,
    _settings,
    deployed,
)
from tests.unit.audit.audit_fakes import FakeAuditRepository

#: The runbook's lookup: the two records that name a revoked session as their subject.
_BY_SESSION = ["auth.session_revoked", "auth.disabled_user_session_revoked"]


async def _lookup(
    audit_log: FakeAuditRepository, actions: list[str], subject_type: str, subject_id: str
) -> list[tuple[str, str | None]]:
    """`GET /admin/audit?action=...&subject_type=...&subject_id=...` as the Owner reads it."""
    page = await AuditQueryService(audit_log).query(
        restrict_to_actor=None,
        raw=True,
        actions=actions,
        subject_type=subject_type,
        subject_id=subject_id,
    )
    return [(entry.action, entry.reason) for entry in page.items]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SimpleNamespace]:
    w = SimpleNamespace(repo=_Rows(), rules=InMemoryRuleStore(), clock=_Clock())
    w.audit_log = FakeAuditRepository()
    wal = str(tmp_path_factory.mktemp("audit") / "audit.wal")
    writer = AuditWriter(w.audit_log, wal, sleep=w.audit_log.retry_sleep)
    with pytest.MonkeyPatch.context() as mp:
        for name in ("user", "session_info"):
            mp.setattr(SqlAlchemyIdentityProvider, name, _delegate(w.repo, name))
        for name in ("load_grants", "load_permissions"):
            mp.setattr(SqlAlchemyScopeSource, name, _delegate(w.repo, name))
        mp.setattr(SqlAlchemySessionRepository, "find_by_id", _delegate(w.repo, "find_by_id"))
        relational = "candleviewer.user_cascade_wiring.SqlAlchemyRelationalRepository"
        mp.setattr(relational, lambda *_: w.repo)
        mp.setattr(appmod, "PostgresRuleStore", lambda _relational: w.rules)
        with deployed(mp, _settings(), w) as (app, client):
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
    found = await _lookup(world.audit_log, _BY_SESSION, "session", sid)
    assert found == [("auth.session_revoked", "user_disabled")]


async def test_the_step_lists_only_the_backstop_revocation_whose_record_was_refused(
    world: SimpleNamespace,
) -> None:
    """AC2: of M's `user_disabled` rows, the step lists those with neither record: only the session
    that escaped the disable, which the backstop revoked on use (401) while the sink refused its
    record, although a `users.disable` record names M."""
    assert (world.backstop, world.refused) == (401, ["AuditWriterStopped"])
    rows = [sid for sid, reason in world.revoked.items() if reason == "user_disabled"]
    found = {sid: await _lookup(world.audit_log, _BY_SESSION, "session", sid) for sid in rows}
    unaudited = [sid for sid, records in found.items() if not records]
    assert unaudited == [str(world.e.session_id)]
    disabled = await _lookup(world.audit_log, ["users.disable"], "user", str(_M))
    assert [action for action, _ in disabled] == ["users.disable"]
