"""E42-T03: the flag write path: write-ahead audit, the live-gate evidence precondition, D2 (no
overrides on the live gate or kill switches), concurrent writes, kind validation, and the audit
of every attempt with its overrides."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import LIVE_ENABLED, MAINTENANCE_MODE, StoredFlag, default_registry
from candleviewer.admin.flags.metrics import flag_changes_total
from candleviewer.admin.flags.service import FlagService
from candleviewer.admin.flags.store import StoreUnavailableError
from candleviewer.admin.flags.writes import (
    FlagConflictError,
    FlagValidationError,
    FlagWriter,
    UnknownFlagError,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from tests.unit.admin.flag_fakes import T0, Clock, FakeAudit, FakeFlagStore

_A = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")
_B = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002")
_SESSION = UUID("5e000000-0000-4000-8000-000000000001")
_REQUEST = UUID("7e000000-0000-4000-8000-000000000001")


def _who(user: UUID = _A) -> AuditPrincipal:
    return AuditPrincipal(
        user_id=user,
        username=f"user-{str(user)[-1]}",
        permissions=frozenset({"flags:write"}),
        session_id=_SESSION,
        ip="127.0.0.1",
        request_id=_REQUEST,
    )


class _Hook:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, StoredFlag | None, StoredFlag]] = []
        self.fail = fail

    async def __call__(self, key: str, before: StoredFlag | None, after: StoredFlag) -> None:
        if self.fail:
            raise RuntimeError("push down")
        self.calls.append((key, before, after))


class _BrokenAudit(FakeAudit):
    """Fails every record from the `fail_from`-th on (0: the first)."""

    def __init__(self, fail_from: int = 0) -> None:
        super().__init__()
        self.fail_from = fail_from

    async def emit(self, action: str, **kwargs: Any) -> None:
        if len(self.records) >= self.fail_from:
            raise RuntimeError("audit unavailable")
        await super().emit(action, **kwargs)


async def _writer(
    hook: _Hook | None = None, audit: FakeAudit | None = None
) -> tuple[FlagWriter, FakeFlagStore, FakeAudit]:
    store, audit = FakeFlagStore(), audit or FakeAudit()
    service = FlagService(default_registry(), store, clock=Clock())
    await store.ensure(service.registry.values())
    return FlagWriter(service, audit, on_change=hook), store, audit


async def _set(
    writer: FlagWriter,
    key: str,
    value: object,
    who: AuditPrincipal | None = None,
    *,
    reason: str | None = "rollout",
    expected_updated_at: datetime | None = T0,
    evidence_url: str | None = None,
    user_overrides: dict[UUID, object] | None = None,
) -> StoredFlag:
    return await writer.set(
        key,
        who or _who(),
        value=value,
        reason=reason,
        expected_updated_at=expected_updated_at,
        evidence_url=evidence_url,
        user_overrides=user_overrides,
    )


def _changes(key: str, result: str) -> float:
    return float(flag_changes_total.labels(key, result)._value.get())


async def test_a_committed_write_is_audited_write_ahead_then_with_its_outcome() -> None:
    writer, store, audit = await _writer(_Hook())
    await _set(writer, "rules.form_editor", False, user_overrides={_B: True})
    (a1, intent), (a2, outcome) = audit.records
    assert (a1, a2) == ("flags.change", "flags.change")
    assert intent["after_state"]["phase"] == "intent"
    assert intent["before_state"] == {"value": True, "overrides": {}}
    assert outcome["after_state"] == {
        "value": False,
        "overrides": {str(_B): True},
        "phase": "outcome",
    }
    assert (outcome["outcome"], outcome["reason"]) == (AuditOutcome.SUCCESS, "ok")
    assert store.rows["rules.form_editor"].user_overrides == {_B: True}


async def test_an_unrecordable_intent_writes_nothing() -> None:
    writer, store, _ = await _writer(_Hook(), _BrokenAudit())
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await _set(writer, "rules.form_editor", False)
    assert store.writes == []


async def test_every_record_names_the_principal_object_and_severity() -> None:
    writer, _, audit = await _writer(_Hook())
    await _set(writer, "rules.form_editor", False)
    for _, record in audit.records:
        assert record["actor_user_id"] == _A and record["actor_label"] == "user-1"
        assert (record["session_id"], record["request_id"]) == (_SESSION, _REQUEST)
        assert record["actor_ip"] == "127.0.0.1"
        assert (record["object_kind"], record["object_id"]) == ("feature_flag", "rules.form_editor")
        assert record["severity"] is Severity.WARNING


async def test_live_enablement_without_evidence_is_refused_unwritten_and_audited() -> None:
    writer, store, audit = await _writer(_Hook())
    with pytest.raises(FlagValidationError) as exc:
        await _set(writer, LIVE_ENABLED, True)
    assert (exc.value.rule, exc.value.field) == ("gate_evidence_required", "evidence_url")
    assert store.writes == []
    ((action, record),) = audit.records
    assert (action, record["outcome"], record["reason"]) == (
        "flags.change",
        AuditOutcome.FAILURE,
        "gate_evidence_required",
    )


async def test_live_enablement_with_evidence_is_written() -> None:
    writer, store, _ = await _writer(_Hook())
    await _set(writer, LIVE_ENABLED, True, evidence_url="https://example.invalid/pt-1")
    assert store.rows[LIVE_ENABLED].value is True


async def test_the_live_gate_cannot_be_bypassed_with_a_user_override() -> None:
    """The probe: value false globally, user B pinned true, no evidence."""
    writer, store, audit = await _writer(_Hook())
    with pytest.raises(FlagValidationError) as exc:
        await _set(writer, LIVE_ENABLED, False, user_overrides={_B: True})
    assert (exc.value.rule, exc.value.field) == ("overrides_not_allowed", "overrides")
    assert store.writes == [] and audit.records[0][1]["reason"] == "overrides_not_allowed"


async def test_maintenance_mode_takes_no_override() -> None:
    writer, store, _ = await _writer(_Hook())
    with pytest.raises(FlagValidationError, match="overrides_not_allowed"):
        await _set(writer, MAINTENANCE_MODE, False, user_overrides={_B: True})
    assert store.writes == []


async def test_concurrent_writes_one_succeeds_the_other_conflicts_both_audited() -> None:
    hook = _Hook()
    writer, store, audit = await _writer(hook)
    first = await _set(writer, "rules.graph_editor", False, _who(_A))
    with pytest.raises(FlagConflictError) as exc:
        await _set(writer, "rules.graph_editor", True, _who(_B))
    assert exc.value.current == first and store.rows["rules.graph_editor"].value is False
    results = [(r["actor_user_id"], r["outcome"], r["reason"]) for _, r in audit.records]
    assert results == [
        (_A, AuditOutcome.SUCCESS, "rollout"),
        (_A, AuditOutcome.SUCCESS, "ok"),
        (_B, AuditOutcome.SUCCESS, "rollout"),
        (_B, AuditOutcome.FAILURE, "conflict"),
    ]
    assert [c[0] for c in hook.calls] == ["rules.graph_editor"]


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
    writer, store, audit = await _writer(_Hook())
    before = _changes(key, rule)
    with pytest.raises(FlagValidationError) as exc:
        await _set(writer, key, value, **extra)
    assert (exc.value.rule, exc.value.field) == (rule, field)
    assert store.writes == [] and [r["reason"] for _, r in audit.records] == [rule]
    assert audit.records[0][1]["before_state"] is not None
    assert _changes(key, rule) == before + 1


async def test_an_unknown_flag_is_audited_but_never_reaches_a_series() -> None:
    writer, _, audit = await _writer(_Hook())
    with pytest.raises(UnknownFlagError):
        await _set(writer, "ui.nonexistent", True)
    assert [(a, r["reason"]) for a, r in audit.records] == [("flags.change", "not_found")]
    assert not any(
        s.labels.get("flag") == "ui.nonexistent"
        for m in flag_changes_total.collect()
        for s in m.samples
    )


async def test_an_unreadable_store_refuses_before_deriving_any_overrides() -> None:
    writer, store, audit = await _writer(_Hook())
    store.down = True
    with pytest.raises(StoreUnavailableError):
        await _set(writer, "rules.form_editor", False)
    assert store.writes == [] and audit.records[-1][1]["reason"] == "unavailable"


async def test_a_store_failure_during_the_write_is_audited_as_its_outcome() -> None:
    writer, store, audit = await _writer(_Hook())

    async def fail(change: object) -> StoredFlag:
        raise StoreUnavailableError("down")

    store.write = fail  # type: ignore[method-assign]  # the store fails mid-write
    with pytest.raises(StoreUnavailableError):
        await _set(writer, "rules.form_editor", False)
    assert [r["reason"] for _, r in audit.records] == ["rollout", "unavailable"]


async def test_maintenance_toggles_add_their_own_audit_actions() -> None:
    writer, store, audit = await _writer(_Hook())
    for value in (True, True, False):
        await _set(
            writer,
            MAINTENANCE_MODE,
            value,
            expected_updated_at=store.rows[MAINTENANCE_MODE].updated_at,
        )
    toggles = [a for a, _ in audit.records if a.startswith("maintenance.")]
    assert toggles == ["maintenance.enabled", "maintenance.disabled"]


async def test_the_hook_gets_the_committed_before_and_after_rows() -> None:
    hook = _Hook()
    writer, store, _ = await _writer(hook)
    before = store.rows["rules.form_editor"]
    after = await _set(writer, "rules.form_editor", False)
    assert hook.calls == [("rules.form_editor", before, after)]


async def test_a_failing_push_never_undoes_a_committed_write() -> None:
    writer, store, _ = await _writer(_Hook(fail=True))
    with capture_logs() as logs:
        await _set(writer, "rules.form_editor", False)
    assert store.rows["rules.form_editor"].value is False
    assert logs[-1]["event"] == "feature_flag_push_failed"


async def test_a_writer_without_a_push_hook_still_commits() -> None:
    writer, store, _ = await _writer(None)
    await _set(writer, "rules.form_editor", False)
    assert store.rows["rules.form_editor"].value is False


async def test_omitted_overrides_are_kept_and_an_empty_list_clears_them() -> None:
    writer, store, _ = await _writer(_Hook())
    key = "rules.form_editor"
    await _set(writer, key, True, user_overrides={_B: False})
    await _set(writer, key, False, expected_updated_at=store.rows[key].updated_at)
    assert store.rows[key].user_overrides == {_B: False}
    await _set(
        writer, key, False, expected_updated_at=store.rows[key].updated_at, user_overrides={}
    )
    assert store.rows[key].user_overrides == {}


async def test_a_failed_outcome_record_is_logged_and_the_write_stands() -> None:
    writer, store, _ = await _writer(_Hook(), _BrokenAudit(fail_from=1))
    with capture_logs() as logs:
        await _set(writer, "rules.form_editor", False)
    assert store.rows["rules.form_editor"].value is False
    assert "flags_change_outcome_audit_failed" in [e["event"] for e in logs]


async def test_a_failed_maintenance_record_never_blocks_the_gate_hook() -> None:
    hook = _Hook()
    writer, _, _ = await _writer(hook, _BrokenAudit(fail_from=2))
    with capture_logs() as logs:
        await _set(writer, MAINTENANCE_MODE, True)
    assert [c[0] for c in hook.calls] == [MAINTENANCE_MODE]
    assert "maintenance_audit_failed" in [e["event"] for e in logs]
