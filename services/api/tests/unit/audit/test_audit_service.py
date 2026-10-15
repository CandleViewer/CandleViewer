"""AuditService lifecycle: scaffold without a repository, wired with one."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository

from candleviewer.audit.hashing import ChainHasherBusy
from candleviewer.audit.service import AuditService
from candleviewer.observability.health import HealthStatus


def _ctx(tmp_path: Path, budget: int = 50_000) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(
            audit_wal_path=str(tmp_path / "a.wal"), audit_page_structure_budget=budget
        )
    )


async def test_service_without_repository_is_inactive_scaffold(tmp_path: Path) -> None:
    svc = AuditService()
    assert svc.health().status is HealthStatus.STOPPED
    await svc.start(_ctx(tmp_path))
    assert not svc.is_active and svc.health().status is HealthStatus.OK
    with pytest.raises(RuntimeError):
        _ = svc.writer
    with pytest.raises(RuntimeError):
        _ = svc.query
    await svc.stop(1)


async def test_service_with_repository_wires_writer_and_query(tmp_path: Path) -> None:
    svc = AuditService(FakeAuditRepository())
    await svc.start(_ctx(tmp_path))
    assert svc.is_active and svc.health().detail == ""
    assert (await svc.query.verify()).verified
    await svc.writer.emit("auth.login", actor_label="a")
    await svc.stop(1)
    assert not svc.is_active


async def test_service_start_refuses_a_second_writer_on_the_same_wal(tmp_path: Path) -> None:
    """#2250 review: two writers on one WAL would truncate each other's in-flight frames."""
    svc = AuditService(FakeAuditRepository())
    await svc.start(_ctx(tmp_path))
    with pytest.raises(RuntimeError, match="already running"):
        await svc.start(_ctx(tmp_path))
    await svc.stop(1)
    await svc.start(_ctx(tmp_path))  # allowed again after stop()
    await svc.stop(1)


async def test_stop_shuts_the_chain_hasher_down(tmp_path: Path) -> None:
    svc = AuditService(FakeAuditRepository())
    await svc.start(_ctx(tmp_path))
    query = svc.query
    await svc.stop(1)
    with pytest.raises(ChainHasherBusy):
        await query.query(restrict_to_actor=None)


async def test_start_gives_the_query_service_the_page_structure_budget_setting(
    tmp_path: Path,
) -> None:
    """`audit_page_structure_budget` reaches the Owner's page: under a 1-token budget no
    state of more than one token is served."""
    repo = FakeAuditRepository()
    state = {"qty": ["1", "2"]}  # 3 tokens: `{`, `[` and `,`
    await repo.insert(
        {
            "record_id": "00000000-0000-4000-8000-000000000001",
            "action": "orders.submit",
            "actor_label": "a",
            "outcome": "success",
            "severity": "info",
            "before_state": state,
            "after_state": state,
            "event_ts": "2026-10-01T12:00:00+00:00",
        }
    )
    svc = AuditService(repo)
    await svc.start(_ctx(tmp_path, budget=1))
    try:
        page = await svc.query.query(restrict_to_actor=None, raw=True)
    finally:
        await svc.stop(1)
    assert page.items[0].detail == {"before": None, "after": None, "elided": ["before", "after"]}
