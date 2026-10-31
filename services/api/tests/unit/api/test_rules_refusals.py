"""#4834 (E35 authoring limits, G-2): the rule routes' refusal records under a budget.

`rules.scope_denied` and `rules.arm` refusal records are held to `rules_refusal_budget_per_hour` per
acting user and per action (22 "Rule authoring refusal records"): past the cap a refusal is counted,
not recorded, and its count rides the user's next record of that action or the window's summary
record. Both writers of `rules.scope_denied`, the scope resolver's sink and the manager's hook, go
through one budget; a rule action's own denial at run time, the boot-time tamper record and a
record with no user never do. A due record that cannot be written is `AuditUnavailable`. Fake clock
and `test_audit_budget`'s fake writer; nothing sleeps.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi import FastAPI
from hypothesis import given, settings
from hypothesis import strategies as st
from prometheus_client import generate_latest

from candleviewer.admin.wiring import audit_writer_sink
from candleviewer.api.audit_budget import SUMMARY_REASON
from candleviewer.api.rules_actor import make_rules_audit
from candleviewer.api.rules_refusals import ACTIONS, ARM, SCOPE_DENIED, RuleRefusalBudgets
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditOutcome
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.main import _lifespan
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import RULES_REFUSAL_BUDGET_PER_HOUR, Settings
from tests.unit.api.test_audit_budget import _Clock, _Writer
from tests.unit.test_main_lifespan import _fake_ctx

CAP = RULES_REFUSAL_BUDGET_PER_HOUR
HOUR = 3600.0
#: Each budgeted refusal event of the manager's hook, with the action it is filed under.
HOOKED = {
    "rule.scope_refused": SCOPE_DENIED,
    "rule.system_rule_refused": SCOPE_DENIED,
    "rule.import_refused": SCOPE_DENIED,
    "rule.mode_refused": ARM,
}


class _Rig:
    """A budget on a fake clock and writer, with both hooks over it and the suppressed ticks."""

    def __init__(self, per_hour: int = CAP, **kw: Any) -> None:
        self.clock = _Clock()
        self.writer = _Writer(self.clock)
        self.ticks = 0
        self.budgets = RuleRefusalBudgets(
            self.writer, per_hour=per_hour, clock=self.clock, on_suppressed=self._tick, **kw
        )
        self.sink = audit_writer_sink(self.writer, acting=str, refusals=self.budgets)
        self.hook = make_rules_audit(self.writer, refusals=self.budgets)

    def _tick(self) -> None:
        self.ticks += 1

    async def scope(self, user: str = "u1") -> None:
        """A request's scope refusal, through the scope resolver's sink."""
        await self.sink("rule_scope_denied", {"caller": user, "account": "a1"})

    async def manager(self, event: str = "rule.scope_refused", user: str = "u1") -> None:
        """A refusal the manager records, through its hook."""
        await self.hook(event, {"rule_id": "r1", "op": "update", "reason": "x", "actor": user})

    def of(self, action: str, user: str = "u1") -> list[dict[str, Any]]:
        """The records written of `action` for `user`."""
        return [
            kw for a, kw, _ in self.writer.records if a == action and kw["actor_user_id"] == user
        ]


async def _refuse(rig: _Rig, writer: str, user: str = "u1") -> None:
    if writer == "sink":
        await rig.scope(user)
    else:
        await rig.manager(writer, user)


WRITERS = pytest.mark.parametrize("writer", ["sink", *HOOKED])


def _action(writer: str) -> str:
    return SCOPE_DENIED if writer == "sink" else HOOKED[writer]


@WRITERS
async def test_the_121st_refusal_of_an_hour_is_counted_not_recorded(writer: str) -> None:
    rig = _Rig()
    for _ in range(CAP):
        await _refuse(rig, writer)
    assert len(rig.of(_action(writer))) == CAP and rig.ticks == 0
    await _refuse(rig, writer)  # past the cap: nothing written, the count kept
    assert len(rig.of(_action(writer))) == CAP and rig.ticks == 1
    rig.clock.now += HOUR  # the hour has rolled: the next record carries the count
    await _refuse(rig, writer)
    (*_, carrying) = rig.of(_action(writer))
    assert carrying["after_state"]["suppressed"] == 1
    validate_action(_action(writer))


async def test_the_suppressed_count_rides_the_next_record_and_the_window_summary() -> None:
    rig = _Rig(per_hour=2)
    for _ in range(4):
        await rig.scope()
    assert len(rig.of(SCOPE_DENIED)) == 2 and rig.ticks == 2
    await rig.budgets.flush.run_once()  # no record followed: the summary carries the count
    summary = rig.of(SCOPE_DENIED)[-1]
    assert (summary["reason"], summary["after_state"]) == (SUMMARY_REASON, {"suppressed": 2})
    assert (summary["object_kind"], summary["outcome"]) == ("rule", AuditOutcome.DENIED)
    await rig.scope()  # counted again, within the summary's window
    await rig.budgets.flush.run_once()
    assert len(rig.of(SCOPE_DENIED)) == 3  # one summary per user, action and window
    rig.clock.now += 300.0
    await rig.budgets.flush.run_once()
    assert rig.of(SCOPE_DENIED)[-1]["after_state"] == {"suppressed": 1}
    rig.clock.now += HOUR
    await rig.scope()  # every count was carried: the next record carries none
    assert "suppressed" not in rig.of(SCOPE_DENIED)[-1]["after_state"]


async def test_a_count_rides_only_the_next_record_of_its_own_action() -> None:
    """`rules.scope_denied` and `rules.arm` keep their own counts: a mode refusal's record never
    carries a scope refusal's count, nor its slot."""
    rig = _Rig(per_hour=1)
    await rig.scope()
    await rig.scope()  # over its own cap
    await rig.manager("rule.mode_refused")  # its own budget: written, and carrying nothing
    (arm,) = rig.of(ARM)
    assert "suppressed" not in arm["after_state"] and rig.ticks == 1
    rig.clock.now += HOUR
    await rig.scope()
    assert rig.of(SCOPE_DENIED)[-1]["after_state"]["suppressed"] == 1


async def test_both_writers_share_one_budget_per_user() -> None:
    rig = _Rig(per_hour=2)
    await rig.scope()
    await rig.manager("rule.scope_refused")
    await rig.manager("rule.import_refused")  # the third record of `rules.scope_denied`
    await rig.scope()
    assert len(rig.of(SCOPE_DENIED)) == 2 and rig.ticks == 2


async def test_one_users_flood_leaves_another_users_records_untouched() -> None:
    rig = _Rig(per_hour=3)
    for _ in range(10):
        await rig.scope("u1")
    for _ in range(3):
        await rig.scope("u2")
    assert (len(rig.of(SCOPE_DENIED, "u1")), len(rig.of(SCOPE_DENIED, "u2"))) == (3, 3)
    assert rig.ticks == 7


async def test_runtime_action_denials_are_never_budgeted() -> None:
    """A rule action's denial while the rule runs, and the high-severity armed record, are one
    record each, whatever the acting user's budget holds."""
    rig = _Rig(per_hour=1)
    await rig.scope()
    await rig.scope()  # the budget is spent
    for _ in range(3):
        await rig.sink("rule_action_scope_denied", {"caller": "u1", "reason": "grant_revoked"})
        await rig.sink("rule_live_scope_armed", {"caller": "u1", "severity": "high"})
    events = [kw["after_state"] for a, kw, _ in rig.writer.records]
    assert sum(1 for e in events if e.get("reason") == "grant_revoked") == 3
    assert sum(1 for a, _, _ in rig.writer.records if a == "rules.live_scope_armed") == 3
    assert rig.ticks == 1


async def test_the_boot_tamper_record_and_a_record_with_no_user_pass_through() -> None:
    rig = _Rig(per_hour=1)
    for _ in range(3):  # the boot check names no actor
        await rig.hook("rule.system_rule_tampered", {"rule_id": "r", "name": "sys.x", "mode": "x"})
        await rig.hook("rule.scope_refused", {"rule_id": "r", "op": "update", "reason": "x"})
        await rig.sink("rule_scope_denied", {"account": "a1"})
    tampered = [kw for a, kw, _ in rig.writer.records if kw["after_state"].get("name") == "sys.x"]
    assert len(tampered) == 3 and len(rig.writer.records) == 9 and rig.ticks == 0
    for _ in range(3):  # a tamper record is never budgeted, whoever it named
        await rig.hook(
            "rule.system_rule_tampered", {"rule_id": "r", "name": "sys.y", "actor": "u1"}
        )
    assert len(rig.writer.records) == 12 and rig.ticks == 0


async def test_successes_are_never_budgeted() -> None:
    rig = _Rig(per_hour=1)
    for event in ("rule.created", "rule.updated", "rule.armed", "rule.deleted") * 3:
        await rig.hook(event, {"rule_id": "r", "actor": "u1"})
    assert len(rig.writer.records) == 12 and rig.ticks == 0


async def test_a_due_record_that_cannot_be_written_is_audit_unavailable_and_keeps_its_counts() -> (
    None
):
    """The refusal is then `503 audit_unavailable` at its route; the counts the record would have
    carried are kept for the next one, never dropped."""
    rig = _Rig(per_hour=1)
    await rig.scope()
    await rig.scope()
    await rig.scope()  # two counted
    rig.clock.now += HOUR
    rig.writer.mode = "fail"
    for refusal in (rig.scope(), rig.manager()):
        with pytest.raises(AuditUnavailable):
            await refusal
    rig.writer.mode = "ok"
    await rig.manager()
    assert rig.of(SCOPE_DENIED)[-1]["after_state"]["suppressed"] == 2


async def test_an_untracked_user_s_due_record_is_audit_unavailable() -> None:
    """The budget tracks a bounded set of users (C-2.18): a user it cannot track has no record
    written for it, so the refusal is `503`, never answered unrecorded."""
    rig = _Rig(per_hour=5, tracked_users=1)
    await rig.scope("u1")  # u1 holds the one entry for the hour
    with pytest.raises(AuditUnavailable):
        await rig.scope("u2")
    assert rig.of(SCOPE_DENIED, "u2") == []


def test_the_budget_default_is_120_an_hour_and_startup_refuses_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().rules_refusal_budget_per_hour == CAP == 120
    with pytest.raises(ValueError):
        Settings(rules_refusal_budget_per_hour=0)
    monkeypatch.setenv("CV_RULES_REFUSAL_BUDGET_PER_HOUR", "7")
    assert Settings().rules_refusal_budget_per_hour == 7


def test_create_app_wires_the_budget_from_the_setting_the_hooks_and_the_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candleviewer import app as app_module

    built: list[RuleRefusalBudgets] = []
    hooked: list[RuleRefusalBudgets | None] = []
    kwargs: list[dict[str, Any]] = []

    class _Built(RuleRefusalBudgets):
        def __init__(self, *args: Any, **kw: Any) -> None:
            super().__init__(*args, **kw)
            kwargs.append(kw)
            built.append(self)

    def hook(emitter: Any, *, refusals: RuleRefusalBudgets | None = None) -> Any:
        hooked.append(refusals)
        return make_rules_audit(emitter, refusals=refusals)

    monkeypatch.setattr(app_module, "RuleRefusalBudgets", _Built)
    monkeypatch.setattr(app_module, "make_rules_audit", hook)
    app = app_module.create_app(Settings(rules_refusal_budget_per_hour=7))
    (budgets,) = built
    assert kwargs[0]["per_hour"] == 7 and hooked == [budgets]
    assert app.state.rules_refusal_flush is budgets.flush
    kwargs[0]["on_suppressed"]()
    text = generate_latest(app.state.metrics_facade.registry).decode()
    line = r'^rule_authoring_refusals_suppressed_total\{env="[a-z]+"\} 1\.0$'
    assert re.search(line, text, re.MULTILINE), "the suppressed counter is not wired"
    (spec,) = [s for s in CATALOGUE if s.name == "rule_authoring_refusals_suppressed_total"]
    assert (spec.kind, spec.labels, spec.max_series, spec.status) == ("counter", (), 1, "live")


def test_one_instance_per_action_each_writing_its_own() -> None:
    budgets = _Rig().budgets
    assert ACTIONS == (SCOPE_DENIED, ARM)
    assert [budgets.budget(a).denial_action for a in ACTIONS] == list(ACTIONS)


async def test_the_lifespan_drain_writes_the_outstanding_counts_before_the_audit_writer_stops() -> (
    None
):
    app, ctx = FastAPI(), _fake_ctx()
    app.state.app_context = ctx
    rig = _Rig(per_hour=1)
    stopped_at_write: list[bool] = []
    real_emit = rig.writer.emit

    async def emit(action: str, **kw: Any) -> None:
        stopped_at_write.append(ctx.audit.stopped)
        await real_emit(action, **kw)

    rig.writer.emit = emit  # type: ignore[method-assign]
    app.state.rules_refusal_flush = rig.budgets.flush
    async with _lifespan(app):
        assert rig.budgets.flush.running
        await rig.scope()
        await rig.scope()
        await rig.manager("rule.mode_refused")
        await rig.manager("rule.mode_refused")
        assert rig.ticks == 2
    summaries = sorted(
        (action, kw["object_kind"], kw["after_state"]["suppressed"])
        for action, kw, _ in rig.writer.records
        if kw.get("reason") == SUMMARY_REASON
    )
    assert summaries == [(ARM, "rule", 1), (SCOPE_DENIED, "rule", 1)]
    assert stopped_at_write and not any(stopped_at_write) and ctx.audit.stopped
    assert not rig.budgets.flush.running


_STEP = st.one_of(
    st.tuples(st.just("refuse"), st.sampled_from(["u1", "u2"]), st.sampled_from(["sink", "mode"])),
    st.tuples(st.just("tick"), st.floats(min_value=0, max_value=1_500), st.just("")),
    st.tuples(st.just("flush"), st.just(""), st.just("")),
)


@settings(max_examples=60, deadline=None)
@given(steps=st.lists(_STEP, max_size=60))
async def test_records_per_user_per_hour_never_exceed_the_cap_plus_the_summaries(
    steps: list[tuple[str, Any, str]],
) -> None:
    """Over any sequence: in any rolling hour each user's capped records of an action are at most
    the cap, a summary goes out at most once a window, and after the drain every refusal is a
    record or a count one carries."""
    cap = 3
    rig = _Rig(per_hour=cap)
    refused: dict[tuple[str, str], int] = {}
    for kind, arg, how in steps:
        if kind == "refuse":
            await (rig.scope(arg) if how == "sink" else rig.manager("rule.mode_refused", arg))
            key = (arg, SCOPE_DENIED if how == "sink" else ARM)
            refused[key] = refused.get(key, 0) + 1
        elif kind == "tick":
            rig.clock.now += arg
        else:
            await rig.budgets.flush.run_once()
    await rig.budgets.flush.stop()
    for (user, action), n in refused.items():
        rows = [(kw, at) for a, kw, at in rig.writer.records if a == action
                and kw["actor_user_id"] == user]  # fmt: skip
        capped = [at for kw, at in rows if kw.get("reason") != SUMMARY_REASON]
        assert all(sum(1 for t in capped if s - HOUR < t <= s) <= cap for s in capped)
        carried = sum((kw["after_state"] or {}).get("suppressed", 0) for kw, _ in rows)
        assert len(capped) + carried == n  # never dropped
