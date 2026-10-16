"""#2754: the `reauth_age_s` key of `admin.area_entered` must survive the audit redactor.

`audit/redact.py` masks any state key whose normalised name contains `token`, so the original
`reauth_token_age_s` would have been persisted as `<redacted:secret>`. These tests drive the real
`AuditWriter` and the real redactor (no stub of either) and read the stored row back."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from audit_fakes import FakeAuditRepository, FakeClock

from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.redact import REDACTION_MARKER
from candleviewer.audit.writer import AuditWriter

_ROUTE = "/admin/overview"
_STEPPED = datetime(2026, 10, 16, 9, 0, 0, tzinfo=UTC)


def _principal(last_step_up_at: datetime | None) -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(),
        username="owner",
        permissions=frozenset({"admin:read"}),
        last_step_up_at=last_step_up_at,
    )


async def _emit_and_read(
    repo: FakeAuditRepository, wal: Path, clock: FakeClock, after_state: dict[str, object]
) -> dict[str, object]:
    writer = AuditWriter(repo, str(wal), clock=clock, sleep=repo.retry_sleep)
    await writer.start()
    # Any registered action runs the same redaction: it works on the state's key names.
    await writer.emit(
        "admin.audit_read",
        actor_label="owner",
        object_kind="admin_route",
        object_id=_ROUTE,
        after_state=after_state,
    )
    await writer.flush(5)
    await writer.stop(1)
    (row,) = repo.rows
    stored = json.loads(row["after_state"])
    assert isinstance(stored, dict)
    return stored


@pytest.mark.parametrize("elapsed_s", [0, 47, 301, 7203])
async def test_reauth_age_s_survives_the_real_writer_and_redactor_as_an_integer(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, elapsed_s: int
) -> None:
    now = _STEPPED + timedelta(seconds=elapsed_s)
    age = _principal(_STEPPED).reauth_age_s(now)
    stored = await _emit_and_read(
        repo, tmp_path / "audit.wal", clock, {"route": _ROUTE, "reauth_age_s": age}
    )
    assert stored == {"route": _ROUTE, "reauth_age_s": elapsed_s}
    assert type(stored["reauth_age_s"]) is int


async def test_reauth_age_s_null_before_any_step_up_survives_as_null(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    age = _principal(None).reauth_age_s(_STEPPED)
    stored = await _emit_and_read(
        repo, tmp_path / "audit.wal", clock, {"route": _ROUTE, "reauth_age_s": age}
    )
    assert stored == {"route": _ROUTE, "reauth_age_s": None}


async def test_a_token_named_age_key_is_masked_which_is_why_it_was_renamed(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    stored = await _emit_and_read(
        repo, tmp_path / "audit.wal", clock, {"route": _ROUTE, "reauth_token_age_s": 47}
    )
    assert stored == {"route": _ROUTE, "reauth_token_age_s": REDACTION_MARKER}
