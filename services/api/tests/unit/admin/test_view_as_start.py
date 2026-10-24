"""#3085 S13a: `ViewAsService.start`, the start request's own write (22 `startViewAs`; plan
section 1.6): a fresh context, the target's notice and `admin.view_as_started` written ahead, in one
unit of work under the row's lock, and the session's sockets closed after it. The store is the
fake repository, whose unit lands every write together or none (`start_view_as_unit`)."""

from __future__ import annotations

import ast
import asyncio
import json
import unicodedata
import warnings
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

import candleviewer
from candleviewer.admin.errors import ViewAsStartUnavailable
from candleviewer.admin.view_as import notice_message
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsNotice, ViewAsState
from candleviewer.observability.context import bind_context
from tests.unit.admin.test_view_as_service import _TARGET, _VIEWER, _at, _Rig
from tests.unit.auth.test_step_up import _T0, _session

_REASON = "support ticket 4711"


async def _session_of(rig: _Rig, **view_as: Any) -> SessionRecord:
    """A live session of `_VIEWER`, holding `view_as` (a `ViewAsState`) if given."""
    record = SessionRecord.model_validate({**dict(_session(_VIEWER)), **view_as})
    assert await rig.repo.create_session(record) is not None
    return record


def _actions(rig: _Rig) -> list[str]:
    return [call["action"] for call in rig.ports.calls]


async def test_started_written_ahead_same_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """`admin.view_as_started` is written inside the unit, before the context lands, with the
    viewer and the viewer's session as its actor and the target as its object (22)."""
    rig = _Rig()
    record = await _session_of(rig)
    seen: list[ViewAsState | None] = []
    emit = rig.ports.emit

    async def ahead(action: str, **kwargs: Any) -> None:
        seen.append(rig.repo.sessions[str(record.id)].view_as)  # the row as the hook sees it
        await emit(action, **kwargs)

    monkeypatch.setattr(rig.ports, "emit", ahead)
    result = await rig.service.start(record, _TARGET, reason=_REASON, now=_T0)
    assert result.started is not None and result.held is None and seen == [None]
    state = result.started.view_as
    assert state is not None and state.target_user_id == _TARGET
    (call,) = rig.ports.calls
    assert call == {
        "action": "admin.view_as_started",
        "actor_label": "ana",
        "actor_user_id": _VIEWER,
        "actor_ip": None,  # the route gives the service its address; none is given here
        "session_id": record.id,
        "object_kind": "user",
        "object_id": str(_TARGET),
        "object_label": "bo",
        "outcome": AuditOutcome.SUCCESS,
        "severity": Severity.WARNING,
        "after_state": {
            "target_user_id": str(_TARGET),
            "started_at": state.started_at.isoformat(),
            "expires_at": state.expires_at.isoformat(),
            "reason": _REASON,
        },
        "request_id": None,
    }


async def test_one_notice_names_viewer_and_window_never_reason() -> None:
    rig = _Rig()
    record = await _session_of(rig)
    request = uuid4()
    with bind_context(request_id=str(request)):
        result = await rig.service.start(record, _TARGET, reason=_REASON, now=_T0)
    assert result.started is not None and result.started.view_as is not None
    state = result.started.view_as
    (notice,) = rig.repo.notices
    assert notice == ViewAsNotice(_TARGET, notice_message("ana", state), request)
    assert "'ana'" in notice.message and state.started_at.isoformat() in notice.message
    assert state.expires_at.isoformat() in notice.message and _REASON not in notice.message
    assert rig.ports.calls[0]["request_id"] == request


async def test_a_held_context_answers_held_and_writes_and_closes_nothing() -> None:
    """409 `view_as_active` at the route: no notice, no record, and no socket closed."""
    rig = _Rig()
    held = await _session_of(rig, view_as=ViewAsState.start(uuid4(), _TARGET, now=_T0))
    result = await rig.service.start(held, _TARGET, reason=_REASON, now=_at(1))
    assert result.started is None and result.held is not None
    assert rig.repo.notices == [] and rig.ports.calls == [] and rig.ports.closed == []


def _fails(ports: Any) -> None:
    ports.fails["emit"] = AuditUnavailable("down")


def _hangs(ports: Any) -> None:
    ports.holds.add("emit")


@pytest.mark.parametrize("write_ahead", [_fails, _hangs], ids=["fails", "hangs"])
async def test_a_write_ahead_that_fails_or_hangs_starts_nothing(write_ahead: Any) -> None:
    """`audit_unavailable`: no notice, no context."""
    rig = _Rig(record_timeout_s=0.01)
    fresh = await _session_of(rig)
    write_ahead(rig.ports)
    with pytest.raises(ViewAsStartUnavailable) as refused:
        await rig.service.start(fresh, _TARGET, reason=_REASON, now=_T0)
    assert refused.value.code == "audit_unavailable"
    assert rig.repo.notices == [] and rig.repo.sessions[str(fresh.id)].view_as is None


async def test_notice_failure_nothing_starts_503() -> None:
    rig = _Rig()
    record = await _session_of(rig)
    rig.repo.notice_fails = ConnectionError("system_events unreachable")
    with pytest.raises(ViewAsStartUnavailable) as refused:
        await rig.service.start(record, _TARGET, reason=_REASON, now=_T0)
    assert refused.value.code == "store_unavailable"
    assert rig.repo.sessions[str(record.id)].view_as is None and rig.ports.calls == []


async def test_a_label_read_that_fails_starts_nothing() -> None:
    rig = _Rig()
    record = await _session_of(rig)
    rig.ports.fails["usernames"] = ConnectionError("identity store unreachable")
    with pytest.raises(ViewAsStartUnavailable) as refused:
        await rig.service.start(record, _TARGET, reason=_REASON, now=_T0)
    assert refused.value.code == "store_unavailable"
    assert rig.repo.notices == [] and rig.ports.calls == []


async def test_two_starts_never_share_a_context() -> None:
    """S2b F6: each start mints its own `uuid4`."""
    rig = _Rig()
    first, second = await _session_of(rig), await _session_of(rig)
    ids = []
    for record in (first, second):
        result = await rig.service.start(record, _TARGET, reason=_REASON, now=_T0)
        assert result.started is not None and result.started.view_as is not None
        ids.append(result.started.view_as.context_id)
    assert ids[0] != ids[1] and {i.version for i in ids} == {4}


async def test_of_concurrent_starts_one_writes_and_the_other_reads_it_held() -> None:
    rig = _Rig()
    record = await _session_of(rig)
    one, two = await asyncio.gather(
        *(rig.service.start(record, _TARGET, reason=_REASON, now=_T0) for _ in range(2))
    )
    assert sorted((r.started is None, r.held is None) for r in (one, two)) == [
        (False, True),
        (True, False),
    ]
    assert len(rig.repo.notices) == 1 and _actions(rig) == ["admin.view_as_started"]


async def test_a_cleared_context_owing_its_record_gets_it_late_then_the_start_lands() -> None:
    rig = _Rig()
    started = ViewAsState.start(uuid4(), _TARGET, now=_T0)
    ended_at, why = started.end_at(now=_at(5), reason=ViewAsEndReason.ENDED)
    old = ViewAsState.model_validate(
        {**dict(started), "ended_at": ended_at, "end_reason": why, "cleared_at": _at(6)}
    )
    record = await _session_of(rig, view_as=old)
    result = await rig.service.start(record, _TARGET, reason=_REASON, now=_at(10))
    assert result.started is not None and result.started.view_as is not None
    assert result.started.view_as.context_id != old.context_id
    assert _actions(rig) == ["admin.view_as_ended", "admin.view_as_started"]
    ended = rig.ports.calls[0]
    assert ended["name"] == str(old.context_id) and ended["after_state"]["recorded_late"] is True


async def test_a_start_closes_the_sessions_sockets_bound_to_no_context() -> None:
    """The session's sockets bound to no context end `view_as_changed` and re-`auth` into the
    target's scope (22, 23 section 9.6); before a start, none is bound to one."""
    rig = _Rig()
    record = await _session_of(rig)
    await rig.service.start(record, _TARGET, reason=_REASON, now=_T0)
    assert rig.ports.closed == [(str(record.id), "view_as_changed")]
    assert rig.ports.closed_contexts == [None]


async def test_the_close_follows_the_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A socket that re-`auth`s on the close reads the started context, never the row before it."""
    rig = _Rig()
    record = await _session_of(rig)
    seen: list[ViewAsState | None] = []
    close = rig.ports.close_family

    async def reading(session_id: str, *, context_id: Any, reason: str) -> None:
        seen.append(rig.repo.sessions[session_id].view_as)
        await close(session_id, context_id=context_id, reason=reason)

    monkeypatch.setattr(rig.ports, "close_family", reading)
    result = await rig.service.start(record, _TARGET, reason=_REASON, now=_T0)
    assert result.started is not None and seen == [result.started.view_as]


async def test_a_failed_close_is_logged_and_the_start_stands() -> None:
    rig = _Rig()
    record = await _session_of(rig)
    rig.ports.fails["close_family"] = ConnectionError("hub down")
    with capture_logs() as logs:
        result = await rig.service.start(record, _TARGET, reason=_REASON, now=_T0)
    assert result.started is not None and rig.repo.sessions[str(record.id)].view_as is not None
    assert [(log["event"], log["context_id"], log["error"]) for log in logs] == [
        ("admin.view_as.close_failed", None, "ConnectionError")
    ]
    assert str(record.id) not in json.dumps(logs) and _REASON not in json.dumps(logs)


async def test_a_gone_or_revoked_session_starts_nothing() -> None:
    rig = _Rig()
    gone = await rig.service.start(_session(_VIEWER), _TARGET, reason=_REASON, now=_T0)
    revoked = await _session_of(rig, revoked_at=_T0, revoked_reason="logout")
    out = await rig.service.start(revoked, _TARGET, reason=_REASON, now=_at(1))
    assert (gone.started, gone.held, out.started, out.held) == (None, None, None, None)
    assert rig.repo.notices == [] and rig.ports.calls == [] and rig.ports.closed == []


async def test_a_self_targeting_start_is_a_caller_error_and_writes_nothing() -> None:
    rig = _Rig()
    record = await _session_of(rig)
    with pytest.raises(ValueError, match="its own user"):
        await rig.service.start(record, _VIEWER, reason=_REASON, now=_T0)
    assert rig.repo.notices == [] and rig.ports.calls == []


_STARTS = frozenset({"start_view_as", "start_view_as_unit"})


def _uses_of_the_stores_start(source: str) -> set[tuple[str, str]]:
    """Every use of the store's start in `source`, an attribute or a string (a `getattr`),
    anywhere in the module, by the innermost function or lambda around it (`<module>` if none)."""
    with warnings.catch_warnings():  # an old revision's SQL escapes are not ours
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source)
    scopes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    uses: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            name = node.value
        else:
            continue
        if name in _STARTS:
            around = [f for f in scopes if f.lineno <= node.lineno <= (f.end_lineno or f.lineno)]
            inner = min(around, key=lambda f: (f.end_lineno or f.lineno) - f.lineno, default=None)
            uses.add((getattr(inner, "name", "<lambda>") if inner else "<module>", name))
    return uses


def _callers_of_the_stores_start(root: Path) -> set[tuple[str, ...]]:
    """Every use of the store's start under `root`: (file, innermost function, name). A module is
    parsed only if it names the start, read NFKC-normalised as Python reads its identifiers."""
    return {
        (path.relative_to(root).as_posix(), *use)
        for path in sorted(root.rglob("*.py"))
        if "start_view_as" in unicodedata.normalize("NFKC", text := path.read_text("utf-8"))
        for use in _uses_of_the_stores_start(text)
    }


def test_only_the_start_calls_the_stores_start() -> None:
    """S2b F4: a context starts only through `ViewAsService.start`'s unit of work, never
    through the store's bare write or from anywhere else."""
    callers = _callers_of_the_stores_start(Path(candleviewer.__file__).parent)
    assert callers == {("admin/view_as.py", "start", "start_view_as_unit")}


def test_the_start_guard_reads_a_name_spelled_in_compatibility_letters(tmp_path: Path) -> None:
    """A name spelled with a fullwidth `s` is the store's `start_view_as_unit` to Python (NFKC,
    PEP 3131): the guard's filter reads a module the same way, or a call so spelled is never
    parsed (the #4170 re-check's Info-A)."""
    spelled = "async def go(store):\n    await store.\uff53tart_view_as_unit()\n"
    (tmp_path / "other.py").write_text(spelled, encoding="utf-8")
    assert _callers_of_the_stores_start(tmp_path) == {("other.py", "go", "start_view_as_unit")}


def test_the_start_guard_finds_an_alias_a_getattr_and_a_lambda() -> None:
    """The #4170 security look's evasions of the guard above."""
    planted = (
        "begin = Store.start_view_as\n"
        "class Rig:\n"
        "    go = Store.start_view_as_unit\n"
        "async def run(store):\n"
        '    return await getattr(store, "start_view_as_unit")()\n'
        "kick = lambda store: store.start_view_as\n"
    )
    assert _uses_of_the_stores_start(planted) == {
        ("<module>", "start_view_as"),
        ("<module>", "start_view_as_unit"),
        ("run", "start_view_as_unit"),
        ("<lambda>", "start_view_as"),
    }
