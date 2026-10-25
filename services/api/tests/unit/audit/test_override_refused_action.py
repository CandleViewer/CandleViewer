"""The refused-widening audit row (#2635, F-01; ADR-0040 (proposed, #4461) Decision 1; E28 threat
model section 8: "a row for every refused widening").

The comparator only builds the row; the route writes it ahead of its `403 risk_limit_breached`
(C-2.9). The action is registered, the row's keyword arguments are exactly `AuditWriter.emit`'s,
and its `after_state` names every violated field with its rule, limit and requested value.
"""

from __future__ import annotations

import inspect
import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from audit_fakes import FakeAuditRepository, FakeClock

from candleviewer.accounts.override_comparator import (
    OVERRIDE_REFUSED_ACTION,
    RefusalActor,
    RefusalEmitKwargs,
    refusal_record,
    refused_fields,
)
from candleviewer.audit.actions import AUDIT_ACTIONS, validate_action
from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity
from candleviewer.audit.writer import AuditWriter
from tests.unit.accounts._override_world import (
    ALTERNATE_ID,
    BOUND,
    figures,
    judge,
    leg,
    profile,
    violations,
)

_ACTOR = RefusalActor(
    user_id=UUID("00000000-0000-7000-8000-0000000000a7"),
    role="manager",
    env="demo",
    request_id=UUID("00000000-0000-7000-8000-000000002635"),
    ip="127.0.0.1",
)


def test_the_override_refused_action_is_registered() -> None:
    assert OVERRIDE_REFUSED_ACTION == "trade_group.override_refused"
    assert OVERRIDE_REFUSED_ACTION in AUDIT_ACTIONS
    assert validate_action(OVERRIDE_REFUSED_ACTION) == OVERRIDE_REFUSED_ACTION


def test_the_row_carries_actor_role_account_and_every_violation() -> None:
    result = judge(leg(qty=Decimal("0.4")), figures=figures(committed_risk=Decimal("450")))
    record = refusal_record(
        violations(result), actor=_ACTOR, bound=BOUND, leg_index=2, alternate_id=UUID(ALTERNATE_ID)
    )
    kwargs = record.emit_kwargs()
    assert record.action == OVERRIDE_REFUSED_ACTION
    assert set(kwargs) <= set(inspect.signature(AuditWriter.emit).parameters) - {"self", "action"}
    assert (kwargs["actor_user_id"], kwargs["actor_ip"]) == (_ACTOR.user_id, "127.0.0.1")
    assert {k: kwargs[k] for k in ("actor_label", "object_kind", "object_id", "outcome")} == {
        "actor_label": str(_ACTOR.user_id),
        "object_kind": "exchange_account",
        "object_id": str(BOUND.account_id),
        "outcome": "denied",
    }
    assert (kwargs["severity"], kwargs["reason"], kwargs["request_id"], kwargs["env"]) == (
        "warning",
        "risk_limit_breached",
        _ACTOR.request_id,
        "demo",
    )
    after = kwargs["after_state"]
    assert isinstance(after, dict)
    json.dumps(after)  # JSON-ready: every Decimal is a plain string
    assert {k: v for k, v in after.items() if k != "violations"} == {
        "exchange_account_id": str(BOUND.account_id),
        "role": "manager",
        "leg": 2,
        "bound_profile_id": str(BOUND.profile_id),
        "bound_profile_version": BOUND.version,
        "alternate_profile_id": ALTERNATE_ID,
    }
    assert after["violations"] == [
        {
            "field": "max_position_notional",
            "rule": "R1",
            "reason": "above_limit",
            "limit": "20000",
            "requested": "25604",
        },
        {
            "field": "max_daily_loss",
            "rule": "R2",
            "reason": "above_limit",
            "limit": "50",
            "requested": "284.2044",
            "net_headroom": "50",
            "committed_risk": "450",
        },
    ]


def test_an_unknown_input_is_named_and_carries_no_figure() -> None:
    result = judge(figures=figures(maintenance_margin_rate=None))
    record = refusal_record(violations(result), actor=_ACTOR, bound=BOUND, leg_index=0)
    assert record.emit_kwargs()["after_state"]["alternate_profile_id"] is None
    assert record.emit_kwargs()["after_state"]["violations"] == [
        {"field": "leverage", "rule": "R3", "reason": "unknown_input",
         "input": "maintenance_margin_rate"}
    ]  # fmt: skip


def test_the_metric_labels_are_the_distinct_refused_fields_in_order() -> None:
    result = judge(leg(qty=Decimal("0.4"), slippage_tolerance_bps=9))
    assert refused_fields(violations(result)) == ("max_position_notional", "slippage_tolerance_bps")


def test_a_figure_is_written_with_every_digit() -> None:
    """28 digits would round the headroom of `max_daily_loss` 71.0511 less 1E-27 committed."""
    result = judge(
        bound=profile(max_daily_loss="71.0511"), figures=figures(committed_risk=Decimal("1E-27"))
    )
    record = refusal_record(violations(result), actor=_ACTOR, bound=BOUND, leg_index=0)
    (entry,) = record.emit_kwargs()["after_state"]["violations"]
    assert entry["net_headroom"] == "71.051099999999999999999999999"
    assert entry["committed_risk"] == "0.000000000000000000000000001"


def test_the_row_is_built_by_the_audit_writer_with_its_own_types(
    repo: FakeAuditRepository, clock: FakeClock, tmp_path: Path
) -> None:
    """The keyword arguments type-check against `AuditWriter.build` (mypy --strict) and build a
    record: the request id is the request's UUID, the enums are the audit's own."""
    writer = AuditWriter(repo, str(tmp_path / "audit.wal"), clock=clock)
    result = judge(leg(qty=Decimal("0.4")))
    record = refusal_record(violations(result), actor=_ACTOR, bound=BOUND, leg_index=0)
    kwargs: RefusalEmitKwargs = record.emit_kwargs()
    emission = writer.build(record.action, **kwargs)
    assert emission.action == OVERRIDE_REFUSED_ACTION
    assert emission.outcome is AuditOutcome.DENIED
    assert emission.severity is Severity.WARNING
    assert emission.env is ExchangeEnv.DEMO
    assert emission.request_id == _ACTOR.request_id
    assert emission.actor_user_id == _ACTOR.user_id
    assert emission.after_state is not None
    assert emission.after_state["violations"][0]["field"] == "max_position_notional"
