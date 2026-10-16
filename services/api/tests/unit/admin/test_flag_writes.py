"""E42-T03: the flag write path: one step-up per write chosen from the locked row (D3a, D3b),
write-ahead audit, the live-gate evidence precondition and the evidence URL rules, D2a (no
overrides on the live gate or kill switches), concurrent writes and the 409 `current`, kind
validation, a store outage logged and counted but never audited, the repair of an unreadable row,
and `maintenance.*` records only on a real stored transition (D1c)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
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
    step_up_class,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from tests.unit.admin.flag_fakes import T0, Clock, FakeAudit, FakeFlagStore, FakeStepUp, NoStepUp

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


async def _service() -> tuple[FlagService, FakeFlagStore]:
    store = FakeFlagStore()
    service = FlagService(default_registry(), store, clock=Clock())
    await store.ensure(service.registry.values())
    return service, store


async def _writer(
    hook: _Hook | None = None, audit: FakeAudit | None = None, step_up: FakeStepUp | None = None
) -> tuple[FlagWriter, FakeFlagStore, FakeAudit]:
    service, store = await _service()
    audit = audit or FakeAudit()
    return FlagWriter(service, audit, step_up or FakeStepUp(), on_change=hook), store, audit


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


@pytest.mark.parametrize("key", [LIVE_ENABLED, MAINTENANCE_MODE])
async def test_the_live_gate_and_maintenance_take_no_user_override(key: str) -> None:
    """The probe: value false globally, user B pinned true, no evidence."""
    writer, store, audit = await _writer(_Hook())
    with pytest.raises(FlagValidationError) as exc:
        await _set(writer, key, False, user_overrides={_B: True})
    assert (exc.value.rule, exc.value.field) == ("overrides_not_allowed", "overrides")
    assert store.writes == [] and audit.records[0][1]["reason"] == "overrides_not_allowed"


async def test_concurrent_writes_one_succeeds_the_other_conflicts_both_audited() -> None:
    service, store = await _service()
    hook, audit, key = _Hook(), FakeAudit(), "rules.graph_editor"
    writer = FlagWriter(service, audit, FakeStepUp(), on_change=hook)
    first = await _set(writer, key, False, _who(_A), user_overrides={_B: True})
    with pytest.raises(FlagConflictError) as exc:
        await _set(writer, key, True, _who(_B))
    assert exc.value.current == first and store.rows[key].value is False
    # The 409 `current` is the row as it stands now, rendered for the caller (B's override).
    members = service.resolved(service.registry[key], exc.value.current, _B, frozenset()).members()
    assert (members["value"], members["default_value"], members["updated_by"]) == (True, False, _A)
    assert members["updated_at"] == T0 + timedelta(seconds=1)
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
        ("rules.graph_editor", "true", {}, "kind_mismatch", "value"),
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


@pytest.mark.parametrize(
    ("mid_write", "reasons", "phase"), [(False, [], "lock"), (True, ["rollout"], "write")]
)
async def test_a_store_outage_is_logged_and_counted_never_audited(
    mid_write: bool, reasons: list[str], phase: str
) -> None:
    writer, store, audit = await _writer(_Hook())
    store.down, store.fail_write = not mid_write, mid_write
    before = _changes("rules.form_editor", "store_unavailable")
    with capture_logs() as logs, pytest.raises(StoreUnavailableError):
        await _set(writer, "rules.form_editor", False)
    assert store.writes == [] and [r["reason"] for _, r in audit.records] == reasons  # intent only
    assert _changes("rules.form_editor", "store_unavailable") == before + 1
    assert [(e["event"], e["phase"]) for e in logs] == [
        ("feature_flag_write_store_unavailable", phase)
    ]


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


@pytest.mark.parametrize(
    ("key", "stored", "value", "expected"),
    [
        ("killswitch.ingestion", 0, False, "killswitch"),  # unreadable counts as engaged
        (MAINTENANCE_MODE, False, True, "flags"),  # engaging: the console is not the emergency stop
        (MAINTENANCE_MODE, True, True, "flags"),
        (LIVE_ENABLED, False, True, "live_enablement"),
        (LIVE_ENABLED, "yes", True, "live_enablement"),  # unreadable: not enabled
        (LIVE_ENABLED, True, True, "flags"),
        ("rules.graph_editor", True, False, "flags"),
    ],
)
def test_one_step_up_class_from_the_key_and_the_row_as_stored(
    key: str, stored: object, value: object, expected: str
) -> None:
    spec = default_registry()[key]
    assert step_up_class(spec, StoredFlag(stored), value) == expected  # type: ignore[arg-type]


async def test_validation_then_one_elevation_per_write_and_a_refused_one_records_nothing() -> None:
    step_up = FakeStepUp(missing=frozenset({"killswitch"}))
    writer, store, audit = await _writer(_Hook(), step_up=step_up)
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
    with pytest.raises(FlagValidationError):  # validation precedes the gate; its 422 is audited
        await _set(writer, MAINTENANCE_MODE, False, reason=" ")
    with pytest.raises(NoStepUp):  # a release refused at the gate records nothing
        await _set(writer, MAINTENANCE_MODE, False)
    assert (step_up.demanded, store.writes) == (["killswitch"], [])
    assert [r["reason"] for _, r in audit.records] == ["required"]
    with pytest.raises(UnknownFlagError):  # a 404 comes before the gate
        await _set(writer, "ui.nonexistent", True)
    await _set(writer, "rules.form_editor", False)
    assert step_up.demanded == ["killswitch", "flags"] and len(audit.records) == 4


async def test_a_release_is_judged_on_the_locked_row_not_a_cached_or_earlier_read() -> None:
    """A kill switch engaged in the store, not yet re-read by the resolver, put to `false` with
    only a graced `flags` elevation: the release still needs `killswitch`."""
    step_up = FakeStepUp(missing=frozenset({"killswitch"}))
    service, store = await _service()
    writer = FlagWriter(service, FakeAudit(), step_up)
    assert await service.value(MAINTENANCE_MODE) is False  # cached, and fresh until the lock
    engaged = replace(store.rows[MAINTENANCE_MODE], value=True)
    store.on_lock = lambda: store.rows.__setitem__(MAINTENANCE_MODE, engaged)
    with pytest.raises(NoStepUp):
        await _set(writer, MAINTENANCE_MODE, False)
    assert step_up.demanded == ["killswitch"] and store.writes == []


@pytest.mark.parametrize(
    ("url", "rule"),
    [
        ("javascript:alert(1)", "https_required"),
        ("http://github.com/basiltt/CandleViewer/issues/412", "https_required"),
        ("https:///issues/412", "https_required"),
        ("https://github.com/a b", "https_required"),
        ("https://[::1/issues", "https_required"),
        ("https://user:secret@github.com/x", "credential_in_url"),
        ("https://user@github.com/x", "credential_in_url"),
        ("https://github.com/x?tab=1&access_token=secret", "credential_in_url"),
        ("https://bucket.s3.amazonaws.com/pt.pdf?X-Amz-Signature=secret", "credential_in_url"),
        ("https://acct.blob.core.windows.net/c/pt.pdf?sv=1&sig=secret", "credential_in_url"),
        ("https://github.com/x#token=secret", "credential_in_url"),
        ("https://github.com/" + "a" * 2030, "string_too_long"),
    ],
)
async def test_evidence_is_an_https_url_without_userinfo_of_at_most_2048_chars(
    url: str, rule: str
) -> None:
    writer, store, audit = await _writer(_Hook())
    with pytest.raises(FlagValidationError) as exc:
        await _set(writer, LIVE_ENABLED, True, evidence_url=url)
    assert (exc.value.rule, exc.value.field) == (rule, "evidence_url") and store.writes == []
    ((_, record),) = audit.records
    assert record["reason"] == rule and ("secret" in str(record)) is False


async def test_evidence_of_exactly_2048_chars_is_recorded_without_a_push_hook() -> None:
    writer, store, audit = await _writer()
    url = "https://github.com/" + "a" * 2029  # 2048 characters
    await _set(writer, LIVE_ENABLED, True, evidence_url=url)
    assert store.rows[LIVE_ENABLED].value is True
    assert audit.records[0][1]["after_state"]["evidence_url"] == url


@pytest.mark.parametrize(
    ("value", "elevation", "toggles"),
    [(True, "flags", ["maintenance.enabled"]), (False, "killswitch", [])],
)
async def test_a_valid_write_repairs_an_unreadable_row(
    value: bool, elevation: str, toggles: list[str]
) -> None:
    step_up = FakeStepUp()
    writer, store, audit = await _writer(_Hook(), step_up=step_up)
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=1)  # 1 == True
    await _set(writer, MAINTENANCE_MODE, value)  # its updated_at (T0) is still the precondition
    assert store.rows[MAINTENANCE_MODE].value is value and step_up.demanded == [elevation]
    assert audit.records[0][1]["before_state"] == {"unreadable": True}  # never the raw value
    assert [a for a, _ in audit.records if a.startswith("maintenance.")] == toggles
