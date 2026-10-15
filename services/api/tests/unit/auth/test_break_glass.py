"""Break-glass Owner reset (E09-S11 #2119 slice 3): the service over the real SQL
store with a scripted fake unit of work. The Postgres round trip is
tests/integration/auth/test_break_glass_reset_pg.py (CI only, needs docker)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from candleviewer.auth.break_glass import (
    BreakGlassRefusal,
    BreakGlassResetResult,
    BreakGlassResetService,
)
from candleviewer.auth.errors import BreakGlassRefused
from candleviewer.auth.recovery_codes import hash_recovery_code
from candleviewer.storage.repositories.break_glass_sqlalchemy import (
    SqlAlchemyBreakGlassRepository,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_NOW = datetime(2026, 10, 15, tzinfo=UTC)
_KEY = bytes(range(32))  # test-only HMAC key, not a credential
_UID, _CORR = uuid.UUID(int=7), uuid.UUID(int=9)
_CODE = "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2-3456"  # test value, not a real recovery code


class _Rel:
    """One scripted result (row list) per statement; records how the unit ends."""

    def __init__(self, *results: list[int]) -> None:
        self.results = list(results)
        self.sql: list[str] = []
        self.params: list[dict[str, Any]] = []
        self.ended: list[str] = []
        self.units = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[SimpleNamespace]:
        self.units += 1

        async def execute(stmt: object, params: dict[str, Any]) -> SimpleNamespace:
            self.sql.append(" ".join(str(stmt).split()))
            self.params.append(params)
            rows = self.results.pop(0)
            first = rows[0] if rows else None
            return SimpleNamespace(all=lambda: rows, first=lambda: first, scalar_one=lambda: first)

        async def end(how: str) -> None:
            self.ended.append(how)

        yield SimpleNamespace(
            session=SimpleNamespace(execute=execute),
            commit=lambda: end("commit"),
            rollback=lambda: end("rollback"),
        )


def _service(rel: _Rel) -> BreakGlassResetService:
    # cast: `_Rel` is a structural fake of the one method the store calls.
    store = SqlAlchemyBreakGlassRepository(cast(SqlAlchemyRelationalRepository, rel))
    return BreakGlassResetService(store, recovery_code_key=_KEY, clock=lambda: _NOW)


async def test_reset_runs_in_one_unit_of_work_committed_once() -> None:
    rel = _Rel([1], [1], [1, 2, 3], [1, 2], [41])
    got = await _service(rel).reset(_UID, live=True, recovery_code=_CODE, correlation_id=_CORR)
    assert got == BreakGlassResetResult(_UID, 3, 2, True, 41)
    assert rel.units == 1 and rel.ended == ["commit"]
    tables = ["FROM users", "recovery_codes", "mfa_methods", "UPDATE sessions", "system_events"]
    assert all(t in s for t, s in zip(tables, rel.sql, strict=True))
    assert "FOR UPDATE OF u" in rel.sql[0] and "revoked_reason = 'break_glass'" in rel.sql[3]
    assert "'auth', 'break_glass_used', 'critical'" in rel.sql[4]
    assert rel.params[1]["h"] == hash_recovery_code(_CODE, key=_KEY)
    assert not any(_CODE in str(p) for p in rel.params)  # the plaintext never reaches SQL
    assert json.loads(rel.params[4]["details"]) == {
        "methods_revoked": 3,
        "recovery_code_consumed": True,
        "sessions_revoked": 2,
        "target_user_id": str(_UID),
    }
    assert (rel.params[4]["corr"], rel.params[4]["now"]) == (str(_CORR), _NOW)


@pytest.mark.parametrize(
    ("results", "reason"),
    [(([],), BreakGlassRefusal.NOT_OWNER), (([1], []), BreakGlassRefusal.RECOVERY_CODE_INVALID)],
)
async def test_refusal_rolls_back_before_any_revoke(
    results: tuple[list[int], ...], reason: BreakGlassRefusal
) -> None:
    rel = _Rel(*results)
    with pytest.raises(BreakGlassRefused) as refused:
        await _service(rel).reset(_UID, live=True, recovery_code=_CODE, correlation_id=_CORR)
    assert refused.value.reason == reason
    assert len(rel.sql) == len(results) and rel.ended == ["rollback"]


async def test_live_without_code_is_refused_before_any_statement() -> None:
    rel = _Rel()
    with pytest.raises(BreakGlassRefused) as refused:
        await _service(rel).reset(_UID, live=True, recovery_code=None, correlation_id=_CORR)
    assert refused.value.reason == BreakGlassRefusal.RECOVERY_CODE_REQUIRED and rel.units == 0


async def test_outside_live_without_code_skips_the_consume_statement() -> None:
    rel = _Rel([1], [], [], [5])
    got = await _service(rel).reset(_UID, live=False, recovery_code=None, correlation_id=_CORR)
    assert got == BreakGlassResetResult(_UID, 0, 0, False, 5)
    assert not any("recovery_codes" in s for s in rel.sql) and rel.ended == ["commit"]
