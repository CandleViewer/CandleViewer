"""#3085 S6: view-as refusal records (22-api-openapi.yaml "View-as session", "Refusal records"):
the metric first, then one `admin.view_as_refused` per refusal within the viewer's own cap of the
"Audit budget" mechanism. Fake clock and `test_audit_budget`'s fake writer; no sleeps."""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from prometheus_client import generate_latest
from pydantic import ValidationError

import candleviewer.app as app_mod
from candleviewer.api.audit_budget import (
    SUMMARY_REASON,
    SYSTEM_ACTOR,
    AuditRecordBudget,
    BudgetActor,
    BudgetWriteFailed,
)
from candleviewer.api.csrf import match_operation
from candleviewer.api.deny_by_default import declared_operations
from candleviewer.api.view_as_refusals import (
    INVALID_FRAME_TYPE,
    REASONS_BY_KIND,
    UNMATCHED,
    VIEW_AS_REFUSED,
    ViewAsRefusalRecorder,
    ViewAsRefusalUnrecorded,
    Viewer,
)
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditEmission, AuditOutcome, Severity
from candleviewer.audit.redact import redact
from candleviewer.auth.metrics import VIEW_AS_REFUSAL_REASONS, auth_view_as_refused_total
from candleviewer.auth.view_as import ViewAsPhase, ViewAsRequestContext, ViewAsState
from candleviewer.main import _lifespan
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings
from tests.contract._admin_support import ROOT, SPEC, text
from tests.unit.api.test_audit_budget import _Clock, _Writer
from tests.unit.test_main_lifespan import _fake_ctx

_VIEWER, _SESSION, _TARGET, _OTHER = UUID(int=3), UUID(int=4), UUID(int=2), UUID(int=9)
_CALLER = Viewer(_VIEWER, _SESSION, "owner")  # a refused start's caller (S13b)
_CTX = ViewAsRequestContext(  # a live request's or socket's, viewing as the target (S7, S11)
    **asdict(_CALLER),
    target_user_id=_TARGET,
    context_id=UUID(int=1),
    subject_user_id=_TARGET,
    phase=ViewAsPhase.LIVE,
)
_HELD_CTX = ViewAsRequestContext(  # a held session's request: it answers as the viewer (S7)
    **asdict(_CALLER),
    target_user_id=_TARGET,
    context_id=UUID(int=1),
    subject_user_id=_VIEWER,
    phase=ViewAsPhase.HELD,
)
_HELD = ViewAsState.start(UUID(int=1), _TARGET, now=datetime(2026, 10, 20, 12, tzinfo=UTC))
_OPERATIONS = {("POST", "/x"), ("POST", "/x/{id}"), ("GET", "/me")}  # the contract's, in the app


def _rig(**kw: Any) -> tuple[_Clock, _Writer, ViewAsRefusalRecorder]:
    clock = _Clock()
    writer = _Writer(clock)
    return clock, writer, ViewAsRefusalRecorder(writer, operations=_OPERATIONS, clock=clock, **kw)


def _count(reason: str) -> float:
    return float(auth_view_as_refused_total.labels(reason=reason)._value.get())


async def test_recorder_writes_up_to_120_records_an_hour_per_viewer() -> None:
    clock, w, rec = _rig(per_hour=Settings().view_as_refusal_budget_per_hour)
    assert [await rec.refuse_frame(_CTX, "x") for _ in range(121)] == [True] * 120 + [False]
    assert await rec.refuse_frame(Viewer(_OTHER, _SESSION, "o2"), "x")  # the cap is per viewer
    clock.now += 3600
    assert await rec.refuse_frame(_CTX, "x") and len(w.records) == 122
    assert w.records[-1][1]["after_state"] == {"suppressed": 1}  # carried by the next record


@pytest.mark.parametrize("spent", ["view_as", "audit"])
async def test_recorder_cap_is_its_own_and_one_for_the_owner_too(spent: str) -> None:
    clock, w, rec = _rig(per_hour=1)
    audit = AuditRecordBudget(per_hour=1, owner_per_hour=1, clock=clock)
    owner = BudgetActor(str(_VIEWER), "owner", _VIEWER, owner=True)  # the viewer, as the Owner

    async def view_as() -> bool:
        return await rec.refuse_frame(_CTX, "x")

    async def audit_denied() -> bool:
        return await audit.write_denial(owner, w, {"actor_label": "owner"})

    first, other = (view_as, audit_denied) if spent == "view_as" else (audit_denied, view_as)
    assert [await first(), await first(), await other()] == [True, False, True]


async def test_recorder_over_the_cap_writes_nothing_and_the_summary_carries_the_count() -> None:
    _, w, rec = _rig(per_hour=1)
    assert [await rec.refuse_frame(_CTX, "x") for _ in range(3)] == [True, False, False]
    await rec.flush.run_once()
    summary = {"actor_label": "owner", "actor_user_id": _VIEWER, "object_kind": "view_as"}
    summary |= {"outcome": AuditOutcome.DENIED, "severity": Severity.WARNING}
    summary |= {"reason": SUMMARY_REASON, "after_state": {"suppressed": 2}}
    assert len(w.records) == 2 and w.records[-1][:2] == (VIEW_AS_REFUSED, summary)


@pytest.mark.parametrize("cause", ["writer", "inflight", "timeout"])
async def test_recorder_unwritable_operation_record_raises_for_503_counted_in_the_metric_alone(
    cause: str,
) -> None:
    inflight, timeout = (0 if cause == "inflight" else 64), (0.0 if cause == "timeout" else 2.0)
    _, w, rec = _rig(inflight_cap=inflight, write_timeout_s=timeout)
    w.mode = {"writer": "fail", "timeout": "hang"}.get(cause, "ok")
    before = _count("view_as_expired")
    with pytest.raises(ViewAsRefusalUnrecorded) as raised:
        await rec.refuse_operation(_HELD_CTX, "view_as_expired", method="GET", template="/me")
    assert isinstance(raised.value, BudgetWriteFailed)  # S7 answers it `503 audit_unavailable`
    assert _count("view_as_expired") == before + 1
    if cause == "timeout":
        await w.resolve(True)  # never cancelled: the slow write still lands
    w.mode = "ok"
    assert len(w.records) == int(cause == "timeout") and rec.budget.inflight == 0
    assert await rec.budget.flush_due(w) == 0  # a 503 answers no refusal: nothing to carry


@pytest.mark.parametrize("cause", ["writer", "inflight", "timeout"])
async def test_recorder_unwritable_frame_record_answers_and_the_summary_carries_it(
    cause: str,
) -> None:
    """23 section 9.6 sends the `err` anyway: nothing raises, and the refusal is counted into the
    viewer's next summary, as one over the cap is."""
    _, w, rec = _rig(inflight_cap=1, write_timeout_s=2.0 if cause == "writer" else 0.0)
    w.mode = "fail" if cause == "writer" else "hang"
    if cause == "inflight":  # another viewer's slow write holds the one slot
        assert not await rec.refuse_frame(Viewer(_OTHER, _SESSION, "o2"), "x")
    before = _count("view_as_read_only")
    assert not await rec.refuse_frame(_CTX, "x")
    assert _count("view_as_read_only") == before + 1
    if w.hanging:  # never cancelled: the other viewer's write lands, the timed-out one fails
        await w.resolve(cause == "inflight")
    w.mode = "ok"
    await rec.flush.run_once()
    mine = [
        (a, kw["reason"], kw["after_state"])
        for a, kw, _ in w.records
        if kw["actor_label"] == "owner"
    ]
    assert mine == [(VIEW_AS_REFUSED, SUMMARY_REASON, {"suppressed": 1})]  # the summary alone


async def test_recorder_frame_record_that_lands_late_is_not_counted_again() -> None:
    _, w, rec = _rig(write_timeout_s=0.0)
    w.mode = "hang"
    assert not await rec.refuse_frame(_CTX, "x")
    await w.resolve(True)
    assert len(w.records) == 1 and await rec.budget.flush_due(w) == 0


async def test_recorder_frame_refusal_of_an_untracked_viewer_is_carried_by_the_system() -> None:
    _, w, rec = _rig(tracked_users=1)
    assert await rec.refuse_frame(Viewer(_OTHER, _SESSION, "o2"), "x")  # holds the one entry
    assert not await rec.refuse_frame(_CTX, "x")
    await rec.flush.run_once()
    (_, written, _), (_, summary, _) = w.records
    assert (written["actor_label"], summary["actor_label"]) == ("o2", SYSTEM_ACTOR)
    assert summary["after_state"] == {"suppressed": 1, "untracked_users": True}


async def test_recorder_cap_is_one_across_the_viewers_sessions() -> None:
    """22 "Audit budget": per user, across all of the user's sessions, as a refresh rotates it."""
    _, _, rec = _rig(per_hour=1)
    assert await rec.refuse_frame(_CTX, "x")
    assert not await rec.refuse_frame(Viewer(_VIEWER, UUID(int=77), "owner"), "x")


async def test_recorder_cap_is_one_across_the_kinds_of_refusal() -> None:
    _, _, rec = _rig(per_hour=2)
    assert await rec.refuse_operation(_CTX, "view_as_read_only", method="POST", template="/x")
    assert await rec.refuse_frame(_CTX, "x")
    assert not await rec.refuse_start(_CALLER, "not_found", target_user_id=_OTHER)


async def test_recorder_counts_each_refusal_first_also_when_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, w, rec = _rig(per_hour=1)
    seen: list[float] = []
    emit = w.emit

    async def counted_then_emitted(action: str, **kw: Any) -> None:
        seen.append(_count(kw["reason"]))
        await emit(action, **kw)

    monkeypatch.setattr(w, "emit", counted_then_emitted)
    before = _count("view_as_owner_target")
    for _ in range(2):  # written, then over the cap
        await rec.refuse_start(_CALLER, "view_as_owner_target", target_user_id=_OTHER)
    assert seen == [before + 1] and _count("view_as_owner_target") == before + 2


async def test_recorder_writes_each_objects_exact_record_and_no_masked_state() -> None:
    _, w, rec = _rig()
    ip, rid = "10.0.0.1", UUID(int=5)
    await rec.refuse_operation(
        _CTX, "view_as_read_only", method="post", template="/x/{id}", ip=ip, request_id=rid
    )
    await rec.refuse_frame(_CTX, "x_action", ip=ip)
    await rec.refuse_start(
        _CALLER, "view_as_active", target_user_id=_OTHER, held=_HELD, ip=ip, request_id=rid
    )
    await rec.refuse_start(_CALLER, "not_found", target_user_id=_OTHER, ip=ip, request_id=rid)
    base = {"actor_label": "owner", "actor_user_id": _VIEWER, "session_id": _SESSION}
    base |= {"outcome": AuditOutcome.DENIED, "severity": Severity.WARNING, "actor_ip": ip}
    base |= {"request_id": rid, "before_state": None, "after_state": None}
    after = {"method": "POST", "path": "/x/{id}"}  # as auth.csrf_refused records its route
    operation: dict[str, Any] = {"object_kind": "operation", "object_id": "/x/{id}"}
    operation |= {"reason": "view_as_read_only", "after_state": after}
    frame = {"object_kind": "ws_frame", "object_id": "x_action", "reason": "view_as_read_only"}
    user = {"object_kind": "user", "object_id": str(_OTHER)}
    held = {"target_user_id": str(_TARGET), "started_at": "2026-10-20T12:00:00+00:00"}
    held["expires_at"] = "2026-10-20T12:30:00+00:00"
    assert [(action, kw) for action, kw, _ in w.records] == [
        (VIEW_AS_REFUSED, {**base, **operation}),
        (VIEW_AS_REFUSED, {**base, **frame, "request_id": None}),
        (VIEW_AS_REFUSED, {**base, **user, "reason": "view_as_active", "before_state": held}),
        (VIEW_AS_REFUSED, {**base, **user, "reason": "not_found"}),
    ]
    states = [kw[k] for _, kw, _ in w.records for k in ("before_state", "after_state") if kw[k]]
    assert len(states) == 2 and all(redact(s) == s for s in states)  # no session id, nothing masked
    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    for action, kw, _ in w.records:  # the writer's model takes each record (`extra="forbid"`)
        AuditEmission(record_id=UUID(int=6), action=validate_action(action), event_ts=at, **kw)


async def test_recorder_refuses_a_reason_its_object_cannot_carry() -> None:
    _, w, rec = _rig()
    wrong = [("ws_frame", "view_as_expired"), ("operation", "conflict"), ("user", "forbidden")]
    for kind, reason in [*wrong, ("session", "view_as_read_only")]:
        with pytest.raises(ValueError, match="never carries"):
            await rec._record_refusal(_CTX, reason, kind, "x")
    with pytest.raises(ValueError, match="held context"):  # it goes with view_as_active only
        await rec.refuse_start(_CALLER, "view_as_active", target_user_id=_OTHER)
    with pytest.raises(ValueError, match="held context"):
        await rec.refuse_start(_CALLER, "conflict", target_user_id=_OTHER, held=_HELD)
    served = {s.labels["reason"] for m in auth_view_as_refused_total.collect() for s in m.samples}
    assert w.records == [] and served == set(VIEW_AS_REFUSAL_REASONS)  # nothing written or labelled


@pytest.mark.parametrize("sent", ["", "Sub", "1x", "x y", "x\n", "x" * 65, "\u00e9t\u00e9"])
async def test_recorder_names_a_frame_type_off_the_pattern_by_its_length_alone(sent: str) -> None:
    """A frame type the client made up never lands raw; one of the pattern does, as sent."""
    _, w, rec = _rig()
    assert await rec.refuse_frame(_CTX, sent) and await rec.refuse_frame(_CTX, "a.b_" + "x" * 60)
    objects = [(kw["object_id"], kw["after_state"]) for _, kw, _ in w.records]
    assert objects == [
        (INVALID_FRAME_TYPE, {"frame_type_len": len(sent)}),
        ("a.b_" + "x" * 60, None),  # 64 characters, the most the pattern takes
    ]


async def test_recorder_refuses_an_operation_template_the_contract_does_not_declare() -> None:
    """Never a raw path, whose ids would land in the log; the error never echoes it. A path no
    operation declares is named as `api.csrf` names it."""
    _, w, rec = _rig()
    before = _count("view_as_read_only")
    for raw in ("/x/7", "/x/{id}/", "/X", "", "/api/v1/x"):
        with pytest.raises(ValueError, match=r"^a refused operation is named by its contract path"):
            await rec.refuse_operation(_CTX, "view_as_read_only", method="POST", template=raw)
    assert w.records == [] and _count("view_as_read_only") == before  # nothing counted either
    assert await rec.refuse_operation(_CTX, "view_as_read_only", method="PUT", template=UNMATCHED)
    assert w.records[0][1]["object_id"] == UNMATCHED == match_operation("PUT", "/nowhere", ())


def test_a_viewer_without_a_label_is_refused() -> None:
    with pytest.raises(ValueError, match="label"):
        Viewer(_VIEWER, _SESSION, "")


def test_reasons_are_the_problem_codes_the_contract_names_for_each_object() -> None:
    """Q9: a record's reason and the metric's label are the refusal's problem code, by object:
    22 "Refusal records" (REST), `startViewAs` (each refusal but the `422`), 23 section 9.6."""
    rest = re.search(
        r"Each `([a-z_]+)` or `([a-z_]+)` refusal, each refused start and each refused WebSocket "
        r"action frame writes one `admin\.view_as_refused` ahead of its answer",
        text(SPEC["info"]["description"]),
    )
    start = text(SPEC["paths"]["/admin/view-as"]["post"]["description"])
    listed = start.split("**Refusals.**", 1)[1].split("The `view_as_active` check", 1)[0]
    codes = re.findall(r"`(\d{3}) ([a-z_]+)`", listed)
    assert "Each refusal above but the `422` writes one `admin.view_as_refused`" in start
    ws = text((ROOT / "docs/plan/23-ws-protocol.md").read_text(encoding="utf-8"))
    frame = re.search(r"answers every action frame with `err` `([a-z_]+)`", ws)
    assert rest and frame and len(codes) == 6
    assert REASONS_BY_KIND == {
        "operation": set(rest.groups()),
        "ws_frame": {frame[1]},
        "user": {code for status, code in codes if status != "422"},
    }
    assert set(VIEW_AS_REFUSAL_REASONS) == set().union(*REASONS_BY_KIND.values())
    assert len(VIEW_AS_REFUSAL_REASONS) == len(set(VIEW_AS_REFUSAL_REASONS)) == 7


async def test_the_refusal_budget_plans_no_read_and_budgets_only_its_own_action() -> None:
    _, w, rec = _rig(per_hour=1)
    actor = BudgetActor(str(_VIEWER), "owner", _VIEWER, owner=False)
    with pytest.raises(ValueError, match="no read"):
        rec.budget.plan_read(actor, "digest")
    emitter = rec.budget.emitter(w, actor)
    for action in ("admin.audit_denied", VIEW_AS_REFUSED, VIEW_AS_REFUSED):
        await emitter.emit(action, actor_label="owner")
    assert [a for a, _, _ in w.records] == ["admin.audit_denied", VIEW_AS_REFUSED]
    assert emitter.suppressed  # the second refusal was over the cap


def test_the_cap_setting_is_bounded_and_read_from_its_env_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().view_as_refusal_budget_per_hour == 120
    with pytest.raises(ValidationError):
        Settings(view_as_refusal_budget_per_hour=0)
    monkeypatch.setenv("CV_VIEW_AS_REFUSAL_BUDGET_PER_HOUR", "7")
    assert Settings().view_as_refusal_budget_per_hour == 7


def test_create_app_builds_the_recorder_from_its_settings_and_serves_every_reason(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment=Environment.DEMO,
        metrics_enabled=False,
        bars_state_root=str(tmp_path / "bars"),
        view_as_refusal_budget_per_hour=7,
        audit_budget_tracked_users=71,
        audit_inflight_writes=29,
        audit_read_flush_seconds=19.0,
    )
    app = app_mod.create_app(settings)
    recorder = app.state.view_as_refusals
    b = recorder.budget
    assert (b._per_hour, b._owner_per_hour, b._tracked, b._inflight_cap) == (7, 7, 71, 29)
    assert b._flush_s == 19.0 and recorder.flush._budget is b
    assert app.state.view_as_refusal_flush is recorder.flush  # the lifespan runs it
    assert app.state.audit_budget_flush._budget is not b  # never a slot of `/admin/audit*`'s
    assert recorder._templates == {t for _, t in declared_operations(SPEC)} | {UNMATCHED}
    scraped = generate_latest(app.state.app_context.metrics).decode()
    served = set(re.findall(r'^auth_view_as_refused_total\{[^}]*reason="([a-z_]+)"', scraped, re.M))
    assert served == set(VIEW_AS_REFUSAL_REASONS)  # bound at import: the first is an increase()


def test_the_catalogue_row_bounds_the_series_by_the_reasons_and_exports_them() -> None:
    (spec,) = [s for s in CATALOGUE if s.name == "auth_view_as_refused_total"]
    assert (spec.max_series, spec.exported) == (len(VIEW_AS_REFUSAL_REASONS), True)


async def test_lifespan_runs_the_view_as_flush_and_drains_it_before_audit_stops() -> None:
    app = FastAPI()
    ctx = _fake_ctx()
    app.state.app_context = ctx
    seen: list[str] = []

    class _Flush:
        def start(self) -> None:
            seen.append("start")

        async def stop(self) -> int:
            seen.append(f"stop, audit stopped={ctx.audit.stopped}")
            return 0

    app.state.view_as_refusal_flush = _Flush()
    async with _lifespan(app):
        assert seen == ["start"]
    assert seen == ["start", "stop, audit stopped=False"] and ctx.audit.stopped
