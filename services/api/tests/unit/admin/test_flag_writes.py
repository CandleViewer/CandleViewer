"""E42-T03: the flag write path: RBAC first, validation (`unknown_user` included) before the one
step-up chosen from the locked row, write-ahead audit, no overrides on the live gate or the kill
switches, conflicts and the 409 `current`, a store outage logged and counted (and audited once a
row was read), the repair of an unreadable row, `maintenance.*` records only on a real stored
transition, every external await bounded, and the cache dropped after every write."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import LIVE_ENABLED, MAINTENANCE_MODE, StoredFlag, default_registry
from candleviewer.admin.flags.evidence import REDACTED_CREDENTIAL, REDACTED_UNPARSEABLE
from candleviewer.admin.flags.metrics import flag_changes_total
from candleviewer.admin.flags.service import FlagService
from candleviewer.admin.flags.store import StoreUnavailableError
from candleviewer.admin.flags.writes import (
    WRITE_AWAIT_TIMEOUT_S,
    FlagConflictError,
    FlagsWriteDenied,
    FlagValidationError,
    FlagWriter,
    UnknownFlagError,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditWriter
from tests.unit.admin.flag_fakes import (
    T0,
    Clock,
    FakeAudit,
    FakeFlagStore,
    FakeStepUp,
    FakeUsers,
    NoStepUp,
)

_A = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")
_B = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002")
_C = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0003")  # names no user
_SESSION = UUID("5e000000-0000-4000-8000-000000000001")
_REQUEST = UUID("7e000000-0000-4000-8000-000000000001")
_K = "rules.graph_editor"


def _who(user: UUID = _A) -> AuditPrincipal:
    can = frozenset({"flags:write"})
    return AuditPrincipal(user, f"user-{str(user)[-1]}", can, _SESSION, "127.0.0.1", _REQUEST)


class _Hook:
    def __init__(self, fail: bool = False, hang: bool = False) -> None:
        self.calls: list[tuple[str, StoredFlag | None, StoredFlag]] = []
        self.fail, self.hang = fail, hang

    async def __call__(self, key: str, before: StoredFlag | None, after: StoredFlag) -> None:
        if self.hang:
            await asyncio.Event().wait()
        if self.fail:
            raise RuntimeError("push down")
        self.calls.append((key, before, after))


class _Audit(FakeAudit):
    """Yields on every record, as a WAL append does. From the `fail_from`-th record on (0: the
    first) it raises; from the `stall_from`-th on it stalls until `release` is set."""

    def __init__(self, fail_from: int = 99, stall_from: int = 99) -> None:
        super().__init__()
        self.fail_from, self.stall_from = fail_from, stall_from
        self.stalled, self.release = asyncio.Event(), asyncio.Event()

    async def emit(self, action: str, **kwargs: Any) -> None:
        await asyncio.sleep(0)
        if len(self.records) >= self.fail_from:
            raise RuntimeError("audit unavailable")
        if len(self.records) >= self.stall_from:
            self.stalled.set()
            await self.release.wait()
        await super().emit(action, **kwargs)


async def _service() -> tuple[FlagService, FakeFlagStore]:
    store = FakeFlagStore()
    service = FlagService(default_registry(), store, clock=Clock())
    await store.ensure(service.registry.values())
    return service, store


async def _writer(
    hook: _Hook | None = None,
    audit: FakeAudit | None = None,
    *,
    step_up: FakeStepUp | None = None,
    users: FakeUsers | None = None,
    timeout_s: float = WRITE_AWAIT_TIMEOUT_S,
) -> tuple[FlagWriter, FakeFlagStore, FakeAudit]:
    service, store = await _service()
    audit = audit or FakeAudit()
    step_up, users = step_up or FakeStepUp(), users or FakeUsers({_A, _B})
    writer = FlagWriter(service, audit, step_up, users, on_change=hook, await_timeout_s=timeout_s)
    return writer, store, audit


async def _set(
    writer: FlagWriter, key: str, value: object, who: AuditPrincipal | None = None, **extra: Any
) -> StoredFlag:
    """A write by `who` (default user A) with reason `rollout`, read at `T0` unless `extra` says."""
    request: dict[str, Any] = {"reason": "rollout", "expected_updated_at": T0, **extra}
    async with asyncio.timeout(5):  # a removed await bound fails here instead of hanging CI
        return await writer.set(key, who or _who(), value=value, **request)


def _changes(key: str, result: str) -> float:
    return float(flag_changes_total.labels(key, result)._value.get())


async def test_a_committed_write_is_audited_write_ahead_then_with_its_outcome() -> None:
    writer, store, audit = await _writer(_Hook(), step_up=(step_up := FakeStepUp()))
    ok = _changes("rules.form_editor", "ok")
    await _set(writer, "rules.form_editor", False, user_overrides={_B: True})
    (a1, intent), (a2, outcome) = audit.records
    assert (a1, a2) == ("flags.change", "flags.change")
    asked = {
        "value": False,
        "overrides": {str(_B): True},
        "reason": "rollout",
        "evidence_url": None,
    }
    assert intent["after_state"] == {**asked, "phase": "intent"}
    assert intent["before_state"] == outcome["before_state"] == {"value": True, "overrides": {}}
    assert outcome["after_state"] == {
        "value": False,
        "overrides": {str(_B): True},
        "phase": "outcome",
    }
    assert (outcome["outcome"], outcome["reason"]) == (AuditOutcome.SUCCESS, "ok")
    assert [w.user_overrides for w in store.writes] == [{_B: True}]
    assert step_up.changes == store.writes  # restated with its overrides
    assert _changes("rules.form_editor", "ok") == ok + 1


@pytest.mark.parametrize("key", ["rules.form_editor", MAINTENANCE_MODE])
async def test_an_unrecordable_intent_writes_nothing(key: str) -> None:
    writer, store, _ = await _writer(_Hook(), _Audit(fail_from=0))
    store.rows[key] = replace(store.rows[key], value=True)  # a kill-switch release too
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await _set(writer, key, False)
    assert store.writes == [] and store.rows[key].value is True


@pytest.mark.parametrize("key", ["ui.nonexistent", LIVE_ENABLED])  # a 404 and a 422 probe
async def test_rbac_precedes_every_lookup_and_every_422(key: str) -> None:
    writer, store, audit = await _writer(_Hook())
    with pytest.raises(FlagsWriteDenied):
        await _set(writer, key, True, AuditPrincipal(_B, "viewer", frozenset({"flags:read"})))
    assert (store.writes, audit.records) == ([], [])


async def test_every_record_names_the_principal_and_binds_to_the_audit_writer() -> None:
    writer, _, audit = await _writer(_Hook())
    await _set(writer, MAINTENANCE_MODE, True)  # intent, outcome, maintenance.enabled
    for key, value in (("ui.nonexistent", True), (_K, 1), (MAINTENANCE_MODE, False)):
        with pytest.raises((UnknownFlagError, FlagValidationError, FlagConflictError)):
            await _set(writer, key, value)  # a 404, a 422, and a 409 (T0 is stale now)
    assert len(audit.records) == 7
    for action, record in audit.records:
        inspect.signature(AuditWriter.emit).bind(None, action, **record)
        assert (record["actor_user_id"], record["actor_label"]) == (_A, "user-1")
        assert (record["session_id"], record["request_id"]) == (_SESSION, _REQUEST)
        assert (record["actor_ip"], record["object_kind"]) == ("127.0.0.1", "feature_flag")
        assert record["object_id"] in (key, MAINTENANCE_MODE, "ui.nonexistent", _K)
        assert record["severity"] is Severity.WARNING


@pytest.mark.parametrize("user_overrides", [None, {}])
async def test_a_safety_flag_write_drops_override_rows_found_in_the_store(
    user_overrides: dict[UUID, object] | None,
) -> None:
    writer, store, audit = await _writer(_Hook())
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], user_overrides={_B: True})
    await _set(writer, MAINTENANCE_MODE, True, user_overrides=user_overrides)
    assert [w.user_overrides for w in store.writes] == [{}]
    assert audit.records[0][1]["before_state"] == {"value": False, "overrides": {str(_B): True}}


async def test_omitted_overrides_are_kept_and_an_empty_list_clears_them() -> None:
    writer, store, _ = await _writer(_Hook())
    key = "rules.form_editor"
    await _set(writer, key, True, user_overrides={_B: False})
    await _set(writer, key, False, expected_updated_at=store.rows[key].updated_at)
    assert store.rows[key].user_overrides == {_B: False}
    stored = store.rows[key].updated_at
    await _set(writer, key, False, expected_updated_at=stored, user_overrides={})
    assert store.rows[key].user_overrides == {} and len(store.writes) == 3


async def test_a_stale_write_is_a_conflict_that_writes_nothing() -> None:
    hook = _Hook()
    writer, store, audit = await _writer(hook)
    conflicts = _changes(_K, "conflict")
    first = await _set(writer, _K, False, _who(_A), user_overrides={_B: True})
    with pytest.raises(FlagConflictError) as exc:
        await _set(writer, _K, True, _who(_B))  # read at T0, before the first write
    assert exc.value.current == first and store.rows[_K] == first and len(store.writes) == 1
    assert [c[0] for c in hook.calls] == [_K] and _changes(_K, "conflict") == conflicts + 1
    results = [(r["actor_user_id"], r["outcome"], r["reason"]) for _, r in audit.records[2:]]
    assert results == [
        (_B, AuditOutcome.SUCCESS, "rollout"),
        (_B, AuditOutcome.FAILURE, "conflict"),
    ]


async def test_the_conflicts_current_is_resolved_for_the_caller() -> None:
    service, _ = await _service()
    writer = FlagWriter(service, FakeAudit(), FakeStepUp(), FakeUsers({_B}))
    await _set(writer, _K, False, _who(_A), user_overrides={_B: True})
    with pytest.raises(FlagConflictError) as exc:
        await _set(writer, _K, True, _who(_B))
    members = service.resolved(service.registry[_K], exc.value.current, _B, frozenset()).members()
    assert (members["value"], members["default_value"], members["updated_by"]) == (True, False, _A)
    assert members["updated_at"] == T0 + timedelta(seconds=1)


async def test_two_writes_from_one_read_commit_once_and_conflict_once() -> None:
    writer, store, _ = await _writer(_Hook(), _Audit())
    done = await asyncio.gather(
        _set(writer, _K, False), _set(writer, _K, True, _who(_B)), return_exceptions=True
    )
    assert [type(result) for result in done] == [StoredFlag, FlagConflictError]
    assert len(store.writes) == 1


@pytest.mark.parametrize(
    ("key", "value", "extra", "rule", "field"),
    [
        (_K, True, {"reason": " "}, "required", "reason"),
        (_K, True, {"expected_updated_at": None}, "required", "expected_updated_at"),
        (_K, 1, {}, "kind_mismatch", "value"),
        (_K, "true", {}, "kind_mismatch", "value"),
        (_K, True, {"user_overrides": {_A: True, _B: "yes"}}, "kind_mismatch", "overrides"),
        (_K, True, {"user_overrides": {_A: True, _C: True}}, "unknown_user", "overrides"),
        (LIVE_ENABLED, False, {"user_overrides": {_B: True}}, "overrides_not_allowed", "overrides"),
        (
            MAINTENANCE_MODE,
            False,
            {"user_overrides": {_B: True}},
            "overrides_not_allowed",
            "overrides",
        ),
        (_K, True, {"evidence_url": "http://h.example/pt-1"}, "https_required", "evidence_url"),
        (LIVE_ENABLED, True, {}, "gate_evidence_required", "evidence_url"),
        (LIVE_ENABLED, True, {"evidence_url": ""}, "gate_evidence_required", "evidence_url"),
    ],
)
async def test_invalid_writes_are_refused_before_the_gate_and_audited(
    key: str, value: object, extra: dict[str, Any], rule: str, field: str
) -> None:
    step_up, users = FakeStepUp(), FakeUsers({_A, _B})
    writer, store, audit = await _writer(_Hook(), step_up=step_up, users=users)
    before = _changes(key, rule)
    with pytest.raises(FlagValidationError) as exc:
        await _set(writer, key, value, **extra)
    assert (exc.value.rule, exc.value.field) == (rule, field)
    ((_, record),) = audit.records
    assert (record["outcome"], record["reason"]) == (AuditOutcome.FAILURE, rule)
    assert record["after_state"]["result"] == rule and record["before_state"] is not None
    assert (store.writes, step_up.demanded, _changes(key, rule)) == ([], [], before + 1)
    assert users.lookups == ([frozenset({_A, _C})] if rule == "unknown_user" else [])


@pytest.mark.parametrize(
    ("url", "audited"),
    [
        ("https://[::1/x?token=secret", REDACTED_UNPARSEABLE),
        ("https://u\uff20h.example/x#token=secret", REDACTED_UNPARSEABLE),
        ("https://github.com/x?access_token=secret", REDACTED_CREDENTIAL),
        ("https:user:secret@github.com/x", REDACTED_CREDENTIAL),  # userinfo without a netloc
    ],
)
async def test_a_refused_evidence_url_never_reaches_the_record_raw(url: str, audited: str) -> None:
    writer, _, audit = await _writer(_Hook())
    with pytest.raises(FlagValidationError):
        await _set(writer, LIVE_ENABLED, True, evidence_url=url)
    ((_, record),) = audit.records
    assert record["after_state"]["evidence_url"] == audited and "secret" not in str(record)


async def test_an_unknown_flag_is_audited_but_never_reaches_a_series_or_the_gate() -> None:
    step_up = FakeStepUp()
    writer, _, audit = await _writer(_Hook(), step_up=step_up)
    with pytest.raises(UnknownFlagError):
        await _set(writer, "ui.nonexistent", True)
    assert [(a, r["reason"]) for a, r in audit.records] == [("flags.change", "not_found")]
    samples = [s for m in flag_changes_total.collect() for s in m.samples]
    assert step_up.demanded == [] and all(s.labels["flag"] != "ui.nonexistent" for s in samples)


async def test_a_stalled_record_of_an_unknown_flag_is_a_bounded_503() -> None:
    writer, _, _ = await _writer(audit=_Audit(stall_from=0), timeout_s=0.1)
    with pytest.raises(StoreUnavailableError):  # mapped as a stall under the row lock is
        await _set(writer, "ui.nonexistent", True)


@pytest.mark.parametrize(
    ("mid_write", "request_id", "reasons"),
    [(False, _REQUEST, []), (True, None, ["rollout", "store_unavailable"])],
)
async def test_a_store_outage_is_counted_once_and_audited_once_a_row_was_read(
    mid_write: bool, request_id: UUID | None, reasons: list[str]
) -> None:
    writer, store, audit = await _writer(_Hook())
    store.down, store.fail_write = not mid_write, mid_write
    before = _changes("rules.form_editor", "store_unavailable")
    with capture_logs() as logs, pytest.raises(StoreUnavailableError):
        await _set(writer, "rules.form_editor", False, replace(_who(), request_id=request_id))
    assert store.writes == [] and [r["reason"] for _, r in audit.records] == reasons
    assert _changes("rules.form_editor", "store_unavailable") == before + 1
    ids = {} if request_id is None else {"request_id": str(request_id)}  # the key and id only
    assert logs == [
        {"event": "feature_flag_write_store_unavailable", "key": "rules.form_editor"}
        | ids
        | {"log_level": "warning"}
    ]


@pytest.mark.parametrize("hung", ["users", "step_up", "intent"])
async def test_a_hung_await_under_the_row_lock_is_an_outage_that_writes_nothing(hung: str) -> None:
    users, step_up = FakeUsers({_B}), FakeStepUp()
    users.hold = asyncio.Event() if hung == "users" else None
    step_up.hold = asyncio.Event() if hung == "step_up" else None
    audit = _Audit(stall_from=0 if hung == "intent" else 99)
    writer, store, _ = await _writer(audit=audit, step_up=step_up, users=users, timeout_s=0.1)
    with pytest.raises(StoreUnavailableError):
        await _set(writer, "rules.form_editor", False, user_overrides={_B: True})
    assert store.writes == [] and store.rows["rules.form_editor"].value is True
    # The row was read, so the outcome is recorded too: unless the audit is what hung.
    reasons = [r["reason"] for _, r in audit.records]
    assert reasons == ([] if hung == "intent" else ["store_unavailable"])


@pytest.mark.parametrize(
    ("moved", "fail", "raised"),
    [(False, False, None), (True, False, FlagConflictError), (True, True, StoreUnavailableError)],
)
async def test_a_write_drops_the_cached_row_whatever_its_outcome(
    moved: bool, fail: bool, raised: type[Exception] | None
) -> None:
    service, store = await _service()
    writer, key = FlagWriter(service, FakeAudit(), FakeStepUp(), FakeUsers()), "rules.form_editor"
    assert await service.value(key) is True  # cached now
    row = replace(store.rows[key], value=False, updated_at=T0 + timedelta(seconds=9))
    store.on_lock = (lambda: store.rows.__setitem__(key, row)) if moved else None
    store.fail_write = fail
    with pytest.raises(raised) if raised else contextlib.nullcontext():
        await _set(writer, key, False)
    assert await service.value(key) is False  # read again, well inside the 30 s TTL


async def test_a_cancel_in_the_outage_record_still_drops_the_cache() -> None:
    (service, store), audit, key = await _service(), _Audit(stall_from=1), "rules.form_editor"
    writer = FlagWriter(service, audit, FakeStepUp(), FakeUsers())
    assert await service.value(key) is True  # cached
    store.rows[key], store.fail_write = replace(store.rows[key], value=False), True
    task = asyncio.create_task(_set(writer, key, False))
    await audit.stalled.wait()  # the intent passed and the write failed: the outcome stalls
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert await service.value(key) is False  # dropped before the outcome record (decision 2)


async def test_maintenance_toggles_add_their_own_audit_actions() -> None:
    writer, store, audit = await _writer(_Hook())
    steps = [(MAINTENANCE_MODE, True), (MAINTENANCE_MODE, True), (MAINTENANCE_MODE, False)]
    for key, value in [*steps, ("killswitch.order_entry", True)]:  # another switch: no record
        await _set(writer, key, value, expected_updated_at=store.rows[key].updated_at)
    records = [(a, r["reason"], r["after_state"]) for a, r in audit.records]
    assert [r for r in records if r[0].startswith("maintenance.")] == [
        ("maintenance.enabled", "rollout", {"value": True, "overrides": {}}),
        ("maintenance.disabled", "rollout", {"value": False, "overrides": {}}),
    ]


@pytest.mark.parametrize("hang", [False, True])
async def test_a_failing_or_hung_push_never_undoes_a_committed_write(hang: bool) -> None:
    writer, store, _ = await _writer(_Hook(fail=not hang, hang=hang), timeout_s=0.1)
    with capture_logs() as logs:
        await _set(writer, "rules.form_editor", False)
    assert store.rows["rules.form_editor"].value is False
    assert (logs[-1]["event"], logs[-1]["log_level"]) == ("feature_flag_push_failed", "error")


async def test_the_hook_gets_the_committed_rows_before_a_stalled_outcome_record() -> None:
    hook, audit = _Hook(), _Audit(stall_from=1)  # the intent passes; the outcome stalls
    writer, store, _ = await _writer(hook, audit)
    before = store.rows[MAINTENANCE_MODE]
    write = asyncio.create_task(_set(writer, MAINTENANCE_MODE, True))
    await audit.stalled.wait()
    assert hook.calls == [(MAINTENANCE_MODE, before, store.rows[MAINTENANCE_MODE])]
    audit.release.set()
    assert (await write).value is True


@pytest.mark.parametrize(
    ("key", "audit", "event"),
    [
        ("rules.form_editor", {"fail_from": 1}, "flags_change_outcome_audit_failed"),
        ("rules.form_editor", {"stall_from": 1}, "flags_change_outcome_audit_failed"),
        (MAINTENANCE_MODE, {"fail_from": 2}, "maintenance_audit_failed"),
    ],
)
async def test_a_failed_or_hung_record_after_the_commit_is_logged_and_the_write_stands(
    key: str, audit: dict[str, int], event: str
) -> None:
    hook, bound = _Hook(), 0.1 if "stall_from" in audit else WRITE_AWAIT_TIMEOUT_S
    writer, store, _ = await _writer(hook, _Audit(**audit), timeout_s=bound)
    value = store.rows[key].value is not True  # a change, so maintenance.mode transitions
    with capture_logs() as logs:
        await _set(writer, key, value)
    assert store.rows[key].value is value and [c[0] for c in hook.calls] == [key]
    assert event in [e["event"] for e in logs]


async def test_each_write_demands_exactly_one_elevation_for_its_key_and_value() -> None:
    step_up, users = FakeStepUp(), FakeUsers()
    writer, store, audit = await _writer(step_up=step_up, users=users)  # and no change hook
    with capture_logs() as logs:
        await _set(writer, "rules.form_editor", False)
        await _set(writer, LIVE_ENABLED, True, evidence_url="https://h.example/pt-1")
        stored = store.rows[LIVE_ENABLED].updated_at
        await _set(writer, LIVE_ENABLED, False, expected_updated_at=stored)  # off: no evidence
    assert step_up.demanded == ["flags", "live_enablement", "flags"]
    assert step_up.changes == store.writes  # each restates the change it lets through
    assert store.rows[LIVE_ENABLED].value is False and logs == []
    assert users.lookups == []  # no overrides given: no user lookup
    assert audit.records[2][1]["after_state"]["evidence_url"] == "https://h.example/pt-1"


async def test_a_release_refused_at_the_gate_records_and_writes_nothing() -> None:
    step_up = FakeStepUp(missing=frozenset({"killswitch"}))
    writer, store, audit = await _writer(_Hook(), step_up=step_up)
    store.rows[MAINTENANCE_MODE] = replace(store.rows[MAINTENANCE_MODE], value=True)
    with pytest.raises(NoStepUp):
        await _set(writer, MAINTENANCE_MODE, False)
    assert (step_up.demanded, store.writes, audit.records) == (["killswitch"], [], [])


async def test_a_release_is_judged_on_the_locked_row_not_a_cached_or_earlier_read() -> None:
    """A kill switch engaged in the store, not yet re-read by the resolver, put to `false` with
    only a graced `flags` elevation: the release still needs `killswitch`."""
    step_up = FakeStepUp(missing=frozenset({"killswitch"}))
    service, store = await _service()
    writer = FlagWriter(service, FakeAudit(), step_up, FakeUsers())
    assert await service.value(MAINTENANCE_MODE) is False  # cached, and fresh until the lock
    engaged = replace(store.rows[MAINTENANCE_MODE], value=True)
    store.on_lock = lambda: store.rows.__setitem__(MAINTENANCE_MODE, engaged)
    with pytest.raises(NoStepUp):
        await _set(writer, MAINTENANCE_MODE, False)
    assert step_up.demanded == ["killswitch"] and store.writes == []


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
