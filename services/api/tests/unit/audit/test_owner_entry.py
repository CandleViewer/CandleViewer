"""#2445: the Owner's `AuditEntry` carries every contract field (#2392); a Manager's
projection (SR-067) keeps only the allow-list. Fields are filled from the stored row."""

from __future__ import annotations

import json
import uuid

from audit_fakes import FakeAuditRepository, FakeClock

from candleviewer.audit.access import OWN_REDACTED_FIELDS, AuditView, redact_entry_for_view
from candleviewer.audit.models import AuditEntry, AuditOutcome, ExchangeEnv, Severity
from candleviewer.audit.query import AuditQueryService

#: Every property of the contract's `AuditEntry` schema (#2392).
CONTRACT_FIELDS = frozenset(
    {
        "id", "ts", "actor_user_id", "actor_username", "action", "subject_type",
        "subject_id", "subject_label", "outcome", "severity", "reason", "environment",
        "session_id", "ip", "user_agent", "request_id", "detail", "entry_hash", "prev_hash",
    }
)  # fmt: skip

_SESSION = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
_ACTOR = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
_REQUEST = uuid.UUID("00000000-0000-4000-8000-0000000000cc")


async def _full(repo: FakeAuditRepository, clock: FakeClock) -> AuditEntry:
    await repo.insert(
        {
            "record_id": "00000000-0000-4000-8000-000000000001",
            "action": "orders.submit",
            "actor_user_id": str(_ACTOR),
            "actor_label": "alice",
            "actor_ip": "100.84.12.9",
            "session_id": str(_SESSION),
            "object_kind": "order",
            "object_id": "o-1",
            "object_label": "BTCUSDT long",
            "outcome": "denied",
            "severity": "warning",
            "reason": "owner_only",
            "before_state": {"qty": "1"},
            "after_state": {"qty": "2"},
            "request_id": str(_REQUEST),
            "env": "demo",
            "event_ts": clock().isoformat(),
        }
    )
    page = await AuditQueryService(repo).query(restrict_to_actor=None)
    return page.items[0]


async def test_owner_entry_populates_every_contract_field(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    entry = await _full(repo, clock)
    assert set(AuditEntry.model_fields) == CONTRACT_FIELDS
    assert entry.actor_username == "alice"
    assert entry.subject_label == "BTCUSDT long"
    assert entry.reason == "owner_only"
    assert entry.environment is ExchangeEnv.DEMO
    assert entry.session_id == _SESSION
    assert entry.detail == {"before": {"qty": "1"}, "after": {"qty": "2"}}
    assert entry.outcome is AuditOutcome.DENIED and entry.severity is Severity.WARNING
    assert entry.entry_hash and entry.prev_hash
    assert entry.user_agent is None  # no `audit_log` column carries it


async def test_owner_entry_with_all_null_columns(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await repo.insert(
        {
            "record_id": "00000000-0000-4000-8000-000000000002",
            "action": "system.tick",
            "actor_label": "system",
            "outcome": "success",
            "severity": "info",
            "event_ts": clock().isoformat(),
        }
    )
    [entry] = (await AuditQueryService(repo).query(restrict_to_actor=None)).items
    assert entry.reason is None and entry.environment is None and entry.session_id is None
    assert entry.subject_label is None
    # The contract: `detail` is "`before` and `after`, each an object or null".
    assert entry.detail == {"before": None, "after": None}


async def test_manager_projection_blanks_everything_not_allow_listed(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    entry = await _full(repo, clock)
    out = redact_entry_for_view(entry, AuditView.OWN_REDACTED)
    dumped = out.model_dump()
    for name in CONTRACT_FIELDS - OWN_REDACTED_FIELDS:
        assert dumped[name] == ({} if name == "detail" else None), name
    assert out.actor_username == "alice" and out.action == "orders.submit"
    assert out.subject_id == "o-1" and out.request_id == str(_REQUEST)


def test_allow_list_names_only_contract_fields() -> None:
    assert OWN_REDACTED_FIELDS <= CONTRACT_FIELDS
    assert OWN_REDACTED_FIELDS == {
        "id", "ts", "actor_user_id", "actor_username", "action", "subject_type",
        "subject_id", "outcome", "severity", "request_id",
    }  # fmt: skip


async def test_owner_json_round_trips_state(repo: FakeAuditRepository, clock: FakeClock) -> None:
    entry = await _full(repo, clock)
    assert json.loads(entry.model_dump_json())["detail"]["after"] == {"qty": "2"}
