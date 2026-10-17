"""Break-glass Owner reset (E09-S11 #2119 slice 3): the service over the real SQL
store with a scripted fake unit of work. The Postgres round trip is
tests/integration/auth/test_break_glass_reset_pg.py (CI only, needs docker)."""

from __future__ import annotations

import inspect
import json
import traceback
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast, get_args

import pytest

from candleviewer.audit.redact import redact
from candleviewer.auth.break_glass import (
    BreakGlassRefusal,
    BreakGlassResetResult,
    BreakGlassResetService,
    BreakGlassStoreRefusal,
)
from candleviewer.auth.errors import BreakGlassRefused
from candleviewer.auth.recovery_codes import hash_recovery_code, normalize_recovery_code
from candleviewer.settings import Environment
from candleviewer.storage.repositories.break_glass_sqlalchemy import (
    BreakGlassStoreRefusal as RepositoryRefusal,
)
from candleviewer.storage.repositories.break_glass_sqlalchemy import (
    SqlAlchemyBreakGlassRepository,
)
from candleviewer.storage.repositories.incident_grouping import (
    incident_signature,
    normalise_message,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_NOW = datetime(2026, 10, 15, tzinfo=UTC)
_KEY = bytes(range(32))  # test-only HMAC key, not a credential
_UID, _CORR = uuid.UUID(int=7), uuid.UUID(int=9)
_CODE = "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2-3456"  # test value, not a real recovery code
_NORMALIZED = normalize_recovery_code(_CODE)
_BLANK = [
    pytest.param("", id="empty"),
    pytest.param("   ", id="spaces"),
    pytest.param(" \t\n", id="whitespace"),
    pytest.param("- -", id="separators"),
]


class _Rel:
    """One scripted outcome per statement (its rows, or an error it raises);
    records how the unit ends."""

    def __init__(self, *results: list[int] | Exception) -> None:
        self.results = list(results)
        self.sql: list[str] = []
        self.params: list[dict[str, Any]] = []
        self.statements: list[Any] = []
        self.ended: list[str] = []
        self.units = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[SimpleNamespace]:
        self.units += 1

        async def execute(stmt: object, params: dict[str, Any] | None = None) -> SimpleNamespace:
            self.sql.append(" ".join(str(stmt).split()))
            self.params.append(params or {})
            self.statements.append(stmt)
            rows = self.results.pop(0)
            if isinstance(rows, Exception):
                raise rows
            first = rows[0] if rows else None
            return SimpleNamespace(all=lambda: rows, first=lambda: first, scalar_one=lambda: first)

        async def end(how: str) -> None:
            self.ended.append(how)

        yield SimpleNamespace(
            session=SimpleNamespace(execute=execute),
            commit=lambda: end("commit"),
            rollback=lambda: end("rollback"),
        )


def _service(rel: _Rel, environment: Environment) -> BreakGlassResetService:
    # cast: `_Rel` is a structural fake of the one method the store calls.
    store = SqlAlchemyBreakGlassRepository(cast(SqlAlchemyRelationalRepository, rel))
    return BreakGlassResetService(
        store, recovery_code_key=_KEY, environment=environment, clock=lambda: _NOW
    )


async def test_reset_runs_in_one_unit_of_work_committed_once() -> None:
    rel = _Rel([1], [1], [1, 2, 3], [1, 2], [41], [])
    svc = _service(rel, Environment.LIVE)
    got = await svc.reset(_UID, recovery_code=_CODE, correlation_id=_CORR)
    assert got == BreakGlassResetResult(_UID, 3, 2, True, 41)
    assert rel.units == 1 and rel.ended == ["commit"]
    tables = ["FROM users", "recovery_codes", "mfa_methods", "UPDATE sessions", "system_events"]
    tables.append("INSERT INTO incidents")  # E42-T05: the event's incident, in the same unit
    assert all(t in s for t, s in zip(tables, rel.sql, strict=True))
    assert "FOR UPDATE OF u" in rel.sql[0] and "revoked_reason = 'break_glass'" in rel.sql[3]
    assert "'auth', 'break_glass_used', 'critical'" in rel.sql[4]
    assert rel.params[1]["h"] == hash_recovery_code(_CODE, key=_KEY)
    # The keyed hash is bound to the consume statement only, never to the event.
    assert ["h" in p for p in rel.params] == [False, True, False, False, False, False]
    assert set(rel.params[4]) == {"message", "details", "corr", "now"}
    assert not any(_CODE in str(p) for p in rel.params)  # the plaintext never reaches SQL
    details = json.loads(rel.params[4]["details"])
    assert details == {
        "methods_revoked": 3,
        "codes_consumed": True,  # the name `admin/breakglass.py` uses; no secret fragment in it
        "sessions_revoked": 2,
        "target_user_id": str(_UID),
    }
    assert redact(details) == details  # 24-internal-schemas 15.4: the serializer masks none of it
    assert (rel.params[4]["corr"], rel.params[4]["now"]) == (str(_CORR), _NOW)
    incident = rel.statements[5].compile().params  # the event's own fields and time, no hash
    title = normalise_message(rel.params[4]["message"])
    assert {k: incident[k] for k in ("component", "signature", "severity", "title")} == {
        "component": "auth",
        "signature": incident_signature("auth", "break_glass_used", title),
        "severity": "critical",
        "title": title,
    }
    assert incident["detail"] == rel.params[4]["message"]
    assert incident["first_seen_at"] == incident["last_seen_at"] == _NOW
    assert not any(_CODE in str(v) or _NORMALIZED in str(v) for v in incident.values())


@pytest.mark.parametrize(
    ("results", "reason"),
    [(([],), BreakGlassRefusal.NOT_OWNER), (([1], []), BreakGlassRefusal.RECOVERY_CODE_INVALID)],
)
async def test_refusal_rolls_back_before_any_revoke(
    results: tuple[list[int], ...], reason: BreakGlassRefusal
) -> None:
    rel = _Rel(*results)
    with pytest.raises(BreakGlassRefused) as refused:
        await _service(rel, Environment.LIVE).reset(_UID, recovery_code=_CODE, correlation_id=_CORR)
    assert refused.value.reason == reason
    assert len(rel.sql) == len(results) and rel.ended == ["rollback"]


def test_every_store_refusal_is_a_refusal_value() -> None:
    # `storage` may not import the `auth` enum, so each side types its own Literal.
    port, repository = set(get_args(BreakGlassStoreRefusal)), set(get_args(RepositoryRefusal))
    assert repository == port and port <= {r.value for r in BreakGlassRefusal}


async def test_live_without_code_is_refused_before_any_statement() -> None:
    rel = _Rel()
    with pytest.raises(BreakGlassRefused) as refused:
        await _service(rel, Environment.LIVE).reset(_UID, recovery_code=None, correlation_id=_CORR)
    assert refused.value.reason == BreakGlassRefusal.RECOVERY_CODE_REQUIRED and rel.units == 0


@pytest.mark.parametrize("code", _BLANK)
async def test_live_with_blank_code_is_refused_before_any_statement(code: str) -> None:
    rel = _Rel()
    with pytest.raises(BreakGlassRefused) as refused:
        await _service(rel, Environment.LIVE).reset(_UID, recovery_code=code, correlation_id=_CORR)
    assert refused.value.reason == BreakGlassRefusal.RECOVERY_CODE_REQUIRED and rel.units == 0


@pytest.mark.parametrize("code", [None, *_BLANK])
@pytest.mark.parametrize("environment", [Environment.DEMO, Environment.TESTNET])
async def test_outside_live_without_code_skips_the_consume_statement(
    environment: Environment, code: str | None
) -> None:
    rel = _Rel([1], [], [], [5], [])
    got = await _service(rel, environment).reset(_UID, recovery_code=code, correlation_id=_CORR)
    assert got == BreakGlassResetResult(_UID, 0, 0, False, 5)
    assert not any("recovery_codes" in s for s in rel.sql) and rel.ended == ["commit"]


async def test_live_rule_follows_the_configured_environment_not_a_caller_flag() -> None:
    # A caller hands over the target, the code and a correlation id: no environment flag.
    params = inspect.signature(BreakGlassResetService.reset).parameters
    assert list(params) == ["self", "target_user_id", "recovery_code", "correlation_id"]
    live, demo = _Rel(), _Rel([1], [], [], [5], [])
    with pytest.raises(BreakGlassRefused):
        await _service(live, Environment.LIVE).reset(_UID, recovery_code=None, correlation_id=_CORR)
    await _service(demo, Environment.DEMO).reset(_UID, recovery_code=None, correlation_id=_CORR)
    assert (live.units, demo.units) == (0, 1)


async def test_store_failure_leaves_no_plaintext_code_in_the_traceback() -> None:
    rel = _Rel([1], ConnectionError("injected store failure"))  # dies at the consume statement
    with pytest.raises(ConnectionError) as failed:
        await _service(rel, Environment.LIVE).reset(_UID, recovery_code=_CODE, correlation_id=_CORR)
    here = inspect.currentframe()  # this test's own frame heads the traceback: skip it
    frames = [f for f, _ in traceback.walk_tb(failed.tb) if f is not here]
    assert "BreakGlassResetService.reset" in {f.f_code.co_qualname for f in frames}
    shown = [repr(v) for f in frames for v in f.f_locals.values()]
    shown += [str(failed.value), repr(failed.value)]
    assert not [s for s in shown if _CODE in s or _NORMALIZED in s]
