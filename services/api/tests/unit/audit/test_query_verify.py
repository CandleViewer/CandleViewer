"""Query pagination/filters, chain verify and tamper location (property
test), export stub, checkpoint job."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.audit.checkpoint import run_checkpoint
from candleviewer.audit.errors import AuditChainBroken
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.query import AuditQueryService


async def _seed(repo: FakeAuditRepository, n: int, clock: FakeClock) -> None:
    for i in range(n):
        await repo.insert(
            {
                "record_id": f"00000000-0000-4000-8000-{i:012d}",
                "action": "orders.submit" if i % 2 else "auth.login",
                "actor_label": f"u{i}",
                "outcome": "denied" if i % 3 == 0 else "success",
                "severity": "error" if i % 5 == 0 else "info",
                "object_id": str(i),
                "before_state": {"i": i} if i % 4 else None,
                "event_ts": clock().isoformat(),
            }
        )


async def test_query_cursor_pagination_walks_newest_first(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 7, clock)
    svc = AuditQueryService(repo)
    page1 = await svc.query(limit=3)
    assert [e.id for e in page1.items] == [7, 6, 5] and page1.has_more
    assert page1.next_cursor == "5" and page1.count == 3
    page3 = await svc.query(limit=3, cursor=2)
    assert [e.id for e in page3.items] == [1] and not page3.has_more
    assert page3.next_cursor is None


async def test_query_filters_by_action_severity_outcome(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 10, clock)
    page = await AuditQueryService(repo).query(
        actions=["auth.login"], severity="error", outcome="denied"
    )
    assert [e.id for e in page.items] == [1]
    assert page.items[0].outcome is AuditOutcome.DENIED
    assert page.items[0].severity is Severity.ERROR


async def test_query_filters_by_subject_type(repo: FakeAuditRepository, clock: FakeClock) -> None:
    """PR #1608 review finding 5: `subject_type` used to be accepted and
    silently dropped instead of being passed to the repository."""
    await repo.insert(
        {
            "record_id": "00000000-0000-4000-8000-000000000100",
            "action": "order.place",
            "actor_label": "u1",
            "outcome": "success",
            "severity": "info",
            "object_kind": "order",
            "object_id": "1",
            "event_ts": clock().isoformat(),
        }
    )
    await repo.insert(
        {
            "record_id": "00000000-0000-4000-8000-000000000101",
            "action": "key.rotate",
            "actor_label": "u1",
            "outcome": "success",
            "severity": "info",
            "object_kind": "api_key",
            "object_id": "2",
            "event_ts": clock().isoformat(),
        }
    )
    page = await AuditQueryService(repo).query(subject_type="order")
    assert [e.subject_type for e in page.items] == ["order"]


async def test_query_rejects_naive_from_ts(repo: FakeAuditRepository) -> None:
    from datetime import datetime

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await AuditQueryService(repo).query(from_ts=datetime(2026, 1, 1))


async def test_query_rejects_from_ts_after_to_ts(repo: FakeAuditRepository) -> None:
    from datetime import UTC, datetime

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await AuditQueryService(repo).query(
            from_ts=datetime(2026, 1, 2, tzinfo=UTC),
            to_ts=datetime(2026, 1, 1, tzinfo=UTC),
        )


async def test_verify_empty_log_is_verified(repo: FakeAuditRepository) -> None:
    result = await AuditQueryService(repo).verify()
    assert result.verified and result.entries_checked == 0 and result.first_bad_id is None


async def test_verify_batches_and_subrange(repo: FakeAuditRepository, clock: FakeClock) -> None:
    await _seed(repo, 12, clock)
    svc = AuditQueryService(repo)
    full = await svc.verify(batch_size=5)
    assert full.verified and full.entries_checked == 12
    part = await svc.verify(from_id=4, to_id=9, batch_size=2)
    assert part.verified and part.entries_checked == 6


async def test_verify_broken_prev_link_located(repo: FakeAuditRepository, clock: FakeClock) -> None:
    await _seed(repo, 5, clock)
    del repo.rows[2]  # out-of-band delete of id 3
    result = await AuditQueryService(repo).verify()
    assert not result.verified and result.first_bad_id == 4


_FIELDS = ["actor_label", "action", "reason", "before_state", "object_id", "event_ts", "severity"]


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    n=st.integers(min_value=1, max_value=15),
    data=st.data(),
)
def test_verify_any_single_tamper_reports_first_divergent_id(n: int, data: st.DataObject) -> None:
    repo = FakeAuditRepository()
    asyncio.run(_seed(repo, n, FakeClock()))
    victim = data.draw(st.integers(min_value=0, max_value=n - 1))
    field = data.draw(st.sampled_from(_FIELDS))
    original = repo.rows[victim][field]
    repo.rows[victim][field] = (original or "") + "X"
    result = asyncio.run(AuditQueryService(repo).verify(batch_size=4))
    assert not result.verified
    assert result.first_bad_id == victim + 1


def test_chain_broken_error_carries_id() -> None:
    err = AuditChainBroken(42)
    assert err.first_bad_id == 42 and "42" in str(err)


async def test_export_returns_job_id(repo: FakeAuditRepository, clock: FakeClock) -> None:
    result = await AuditQueryService(repo).schedule_export(from_ts=clock(), to_ts=clock())
    assert result.download_url is None and result.job_id.version == 4


async def test_checkpoint_empty_log_writes_nothing(
    repo: FakeAuditRepository, tmp_path: Path
) -> None:
    assert await run_checkpoint(repo, off_box_path=str(tmp_path / "cp.ndjson")) is None
    assert not (tmp_path / "cp.ndjson").exists()


async def test_checkpoint_writes_db_row_and_off_box_file(
    repo: FakeAuditRepository, clock: FakeClock, tmp_path: Path
) -> None:
    await _seed(repo, 3, clock)
    path = tmp_path / "offbox" / "cp.ndjson"
    result = await run_checkpoint(repo, off_box_path=str(path))
    assert result is not None and result.head_id == 3 and result.row_count == 3
    assert repo.checkpoints[3]["head_hash"] == repo.rows[-1]["entry_hash"]
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["head_hash"] == repo.rows[-1]["entry_hash"] and line["head_id"] == 3
    await run_checkpoint(repo, off_box_path=str(path))  # idempotent per head_id
    assert len(repo.checkpoints) == 1


@pytest.mark.parametrize("bad", ["", "x"])
async def test_verify_detects_tampered_head_hash(
    repo: FakeAuditRepository, clock: FakeClock, bad: str
) -> None:
    await _seed(repo, 2, clock)
    repo.rows[-1]["entry_hash"] = bad
    result = await AuditQueryService(repo).verify()
    assert result.first_bad_id == 2


_HASHED_KEYS = (
    "actor_user_id",
    "actor_label",
    "actor_ip",
    "session_id",
    "action",
    "object_kind",
    "object_id",
    "outcome",
    "severity",
    "reason",
    "before_state",
    "after_state",
    "request_id",
    "env",
    "event_ts",
)
_field = st.one_of(st.none(), st.text(alphabet="ab:-1|", max_size=4))


# deadline=None: 300 examples x 32 generated strings takes 12-15 s on the CI
# runner; hypothesis's default 200 ms per-example deadline trips under full-suite
# load (observed on PR #1601, unrelated diff). The property itself is cheap and
# deterministic; the deadline is the only source of flakiness (C-9.3).
@settings(max_examples=300, deadline=None)
@given(a=st.lists(_field, min_size=16, max_size=16), b=st.lists(_field, min_size=16, max_size=16))
def test_canonical_hash_input_is_injective(a: list[str | None], b: list[str | None]) -> None:
    from candleviewer.audit.query import _canonical_field

    def encode(vals: list[str | None]) -> str:
        return "".join(_canonical_field(v) for v in vals)

    if a != b:
        assert encode(a) != encode(b)


def test_canonical_field_golden() -> None:
    from candleviewer.audit.query import _canonical_field, _canonical_hash

    assert _canonical_field(None) == "-" and _canonical_field("") == "0:"
    assert _canonical_field("ab") == "2:ab" and _canonical_field("é") == "1:é"
    row = dict.fromkeys(_HASHED_KEYS)
    row.update(actor_label="a", action="auth.login", outcome="success", severity="info")
    # sha256("64:000..0" "-" "1:a" "-" "-" "10:auth.login" "-" "-" "7:success" "4:info" "-"*6)
    import hashlib

    expected = hashlib.sha256(
        ("64:" + "0" * 64 + "-1:a--10:auth.login--7:success4:info" + "-" * 6).encode()
    ).hexdigest()
    assert _canonical_hash("0" * 64, row) == expected


def test_sqlstate_extraction_and_timeout_mapping() -> None:
    import sqlalchemy as sa

    from candleviewer.storage.repositories import audit_sqlalchemy as mod

    class _Orig(Exception):
        sqlstate = "57014"

    class _Wrapped(Exception):
        def __init__(self) -> None:
            self.__cause__ = _Orig()

    assert mod._sqlstate(sa.exc.DBAPIError("s", {}, _Orig())) == "57014"
    assert mod._sqlstate(sa.exc.DBAPIError("s", {}, _Wrapped())) == "57014"
    assert mod._sqlstate(sa.exc.DBAPIError("s", {}, Exception())) is None
