"""Per-page `chain_verified` (contract #2392, design §5): computed on the full rows, on the
dedicated hashing executor, and never true for a row that was not fetched in full."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository, FakeClock

from candleviewer.audit import query as query_mod
from candleviewer.audit.query import AuditQueryService


async def _seed(repo: FakeAuditRepository, n: int, clock: FakeClock) -> None:
    for i in range(n):
        await repo.insert(
            {
                "record_id": f"00000000-0000-4000-8000-{i:012d}",
                "action": "orders.submit",
                "actor_label": f"u{i}",
                "outcome": "success",
                "severity": "info",
                "reason": None,
                "after_state": {"i": i, "note": "é"},
                "event_ts": clock().isoformat(),
            }
        )


async def _verified(repo: FakeAuditRepository, **kw: Any) -> bool:
    page = await AuditQueryService(repo).query(restrict_to_actor=None, **kw)
    return page.chain_verified


async def test_intact_page_is_verified_from_genesis(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 5, clock)
    assert await _verified(repo) and await _verified(repo, limit=2)
    assert repo.rows[0]["prev_hash"] == "0" * 64  # id 1 links to genesis


async def test_empty_page_is_verified(repo: FakeAuditRepository) -> None:
    assert await _verified(repo)


@pytest.mark.parametrize("field", ["actor_label", "reason", "after_state", "object_id"])
async def test_an_altered_row_is_not_verified(
    repo: FakeAuditRepository, clock: FakeClock, field: str
) -> None:
    await _seed(repo, 4, clock)
    repo.rows[1][field] = (repo.rows[1][field] or "") + "x"  # out-of-band edit of id 2
    assert not await _verified(repo, actions=["orders.submit"])


async def test_a_removed_predecessor_breaks_the_link_even_off_the_page(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 5, clock)
    del repo.rows[2]  # id 3 removed out of band
    assert not await _verified(repo, limit=2)  # ids 5, 4: 4's predecessor is now 2
    assert await _verified(repo, limit=1)  # id 5 still links to 4


async def test_a_row_over_the_render_caps_is_unverified_never_verified(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 3, clock)
    repo.over_cap.add(2)
    assert not await _verified(repo)
    assert await _verified(repo, limit=1)  # id 3 alone was fetched in full


async def test_chain_check_runs_on_the_dedicated_executor(
    repo: FakeAuditRepository, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(repo, 2, clock)
    threads: list[str] = []
    real = query_mod._page_chain_verified

    def spy(rows: list[dict[str, Any]]) -> bool:
        threads.append(threading.current_thread().name)
        return real(rows)

    monkeypatch.setattr(query_mod, "_page_chain_verified", spy)
    assert await _verified(repo)
    assert len(threads) == 1 and threads[0].startswith("cv-audit-hash")


async def test_the_owner_flag_reaches_the_repository(repo: FakeAuditRepository) -> None:
    svc = AuditQueryService(repo)
    await svc.query(restrict_to_actor=None, owner=True)
    await svc.query(restrict_to_actor=None)
    assert [call["owner"] for call in repo.page_calls] == [True, False]
