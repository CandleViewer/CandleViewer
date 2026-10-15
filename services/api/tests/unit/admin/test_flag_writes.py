"""E42-T03: the flag write path: the live-gate evidence precondition, concurrent writes, kind
validation and the audit of every attempt (maintenance toggles included)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import LIVE_ENABLED, MAINTENANCE_MODE, StoredFlag, default_registry
from candleviewer.admin.flags.service import FlagService
from candleviewer.admin.flags.store import StoreUnavailableError
from candleviewer.admin.flags.writes import (
    FlagConflictError,
    FlagValidationError,
    FlagWriter,
    UnknownFlagError,
)
from candleviewer.audit.models import AuditOutcome
from tests.unit.admin.flag_fakes import T0, Clock, FakeAudit, FakeFlagStore

_A = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")
_B = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002")


async def _writer(
    on_change: list[str] | None = None,
) -> tuple[FlagWriter, FakeFlagStore, FakeAudit]:
    store, audit = FakeFlagStore(), FakeAudit()
    service = FlagService(default_registry(), store, clock=Clock())
    await service.store.ensure(service.registry.values())

    async def changed(key: str) -> None:
        if on_change is None:
            raise RuntimeError("push down")
        on_change.append(key)

    return FlagWriter(service, audit, on_change=changed), store, audit


async def _set(
    writer: FlagWriter,
    key: str,
    value: object,
    actor: UUID = _A,
    *,
    reason: str | None = "rollout",
    expected_updated_at: datetime | None = T0,
    evidence_url: str | None = None,
    user_overrides: dict[UUID, object] | None = None,
) -> StoredFlag:
    return await writer.set(
        key,
        actor_id=actor,
        actor_label=str(actor),
        value=value,
        reason=reason,
        expected_updated_at=expected_updated_at,
        evidence_url=evidence_url,
        user_overrides=user_overrides,
    )


async def test_live_enablement_without_evidence_is_refused_unwritten_and_audited() -> None:
    writer, store, audit = await _writer([])
    with pytest.raises(FlagValidationError) as exc:
        await _set(writer, LIVE_ENABLED, True)
    assert (exc.value.rule, exc.value.field) == ("gate_evidence_required", "evidence_url")
    assert store.writes == [] and store.rows[LIVE_ENABLED].value is False
    ((action, record),) = audit.records
    assert action == "flags.change" and record["outcome"] is AuditOutcome.FAILURE
    assert record["reason"] == "gate_evidence_required"
    assert record["after_state"]["value"] is True and record["object_id"] == LIVE_ENABLED


async def test_live_enablement_with_evidence_is_written_and_audited() -> None:
    writer, store, audit = await _writer([])
    await _set(writer, LIVE_ENABLED, True, evidence_url="https://example.invalid/pt-1")
    assert store.rows[LIVE_ENABLED].value is True
    ((_, record),) = audit.records
    assert record["after_state"]["evidence_url"] == "https://example.invalid/pt-1"
    assert record["before_state"] == {"value": False}


async def test_concurrent_writes_one_succeeds_the_other_conflicts_both_audited() -> None:
    changes: list[str] = []
    writer, store, audit = await _writer(changes)
    first = await _set(writer, "rules.graph_editor", False, actor=_A)
    with pytest.raises(FlagConflictError) as exc:
        await _set(writer, "rules.graph_editor", True, actor=_B)
    assert exc.value.current == first and exc.value.current.updated_by == _A
    assert store.rows["rules.graph_editor"].value is False
    outcomes = [(r["actor_user_id"], r["outcome"], r["reason"]) for _, r in audit.records]
    assert outcomes == [
        (_A, AuditOutcome.SUCCESS, "rollout"),
        (_B, AuditOutcome.FAILURE, "conflict"),
    ]
    assert changes == ["rules.graph_editor"]


@pytest.mark.parametrize(
    ("key", "value", "extra", "rule", "field"),
    [
        ("rules.graph_editor", True, {"reason": " "}, "required", "reason"),
        (
            "rules.graph_editor",
            True,
            {"expected_updated_at": None},
            "required",
            "expected_updated_at",
        ),
        ("rules.graph_editor", 1, {}, "kind_mismatch", "value"),
        ("engine.heatmap_renderer", "texture_v9", {}, "kind_mismatch", "value"),
        ("rules.graph_editor", True, {"user_overrides": {_B: "yes"}}, "kind_mismatch", "overrides"),
    ],
)
async def test_invalid_writes_are_refused_before_the_store_and_audited(
    key: str, value: object, extra: dict[str, Any], rule: str, field: str
) -> None:
    writer, store, audit = await _writer([])
    with pytest.raises(FlagValidationError) as exc:
        await _set(writer, key, value, **extra)
    assert (exc.value.rule, exc.value.field) == (rule, field)
    assert store.writes == []
    assert [r["reason"] for _, r in audit.records] == [rule]


async def test_unknown_flag_is_not_found_and_audited() -> None:
    writer, _, audit = await _writer([])
    with pytest.raises(UnknownFlagError):
        await _set(writer, "ui.nonexistent", True)
    assert [(a, r["reason"]) for a, r in audit.records] == [("flags.change", "not_found")]


async def test_maintenance_toggles_add_their_own_audit_actions() -> None:
    writer, store, audit = await _writer([])
    await _set(writer, MAINTENANCE_MODE, True)
    updated = store.rows[MAINTENANCE_MODE].updated_at
    await _set(writer, MAINTENANCE_MODE, True, expected_updated_at=updated)
    updated = store.rows[MAINTENANCE_MODE].updated_at
    await _set(writer, MAINTENANCE_MODE, False, expected_updated_at=updated)
    actions = [a for a, _ in audit.records]
    assert actions == [
        "flags.change",
        "maintenance.enabled",
        "flags.change",
        "flags.change",
        "maintenance.disabled",
    ]


async def test_store_outage_on_write_is_audited_and_raised() -> None:
    writer, store, audit = await _writer([])
    store.down = True
    with pytest.raises(StoreUnavailableError):
        await _set(writer, "rules.form_editor", False)
    assert audit.records[-1][1]["reason"] == "unavailable"


async def test_a_failing_push_never_undoes_a_committed_write() -> None:
    writer, store, _ = await _writer(None)
    with capture_logs() as logs:
        await _set(writer, "rules.form_editor", False)
    assert store.rows["rules.form_editor"].value is False
    assert logs[-1]["event"] == "feature_flag_push_failed"


async def test_a_writer_without_a_push_hook_still_commits() -> None:
    store = FakeFlagStore()
    service = FlagService(default_registry(), store, clock=Clock())
    await store.ensure(service.registry.values())
    await _set(FlagWriter(service, FakeAudit()), "rules.form_editor", False)
    assert store.rows["rules.form_editor"].value is False
