"""`candleviewer.risk.models` (E39-T02 #882): the domain objects of 24-internal-schemas.md §8.11.

Each model round-trips through JSON unchanged and refuses what its table's CHECK refuses
(21-database-schema.md §3.11), so a bug cannot carry an invalid row between the store and the
evaluator in either direction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from candleviewer.risk import (
    KillSwitchOptions,
    KillSwitchScope,
    KillSwitchState,
    LockoutActions,
    LockoutReason,
    LockoutState,
    RiskDecision,
    RiskRefusal,
)

_SINCE = datetime(2026, 10, 20, 13, 41, tzinfo=UTC)
_ACCOUNT = uuid4()


def _lockout(**fields: Any) -> LockoutState:
    base: dict[str, Any] = {
        "id": uuid4(),
        "exchange_account_id": _ACCOUNT,
        "reason": LockoutReason.DAILY_LOSS,
        "since": _SINCE,
    }
    return LockoutState(**{**base, **fields})


def _switch(**fields: Any) -> KillSwitchState:
    base: dict[str, Any] = {
        "id": uuid4(),
        "scope": KillSwitchScope.GLOBAL,
        "engaged": False,
        "updated_at": _SINCE,
    }
    return KillSwitchState(**{**base, **fields})


def _refusal(**fields: Any) -> RiskDecision:
    base: dict[str, Any] = {
        "allowed": False,
        "code": RiskRefusal.RISK_LIMIT_BREACHED,
        "cap": "max_position_notional_usd",
        "limit": Decimal("25000"),
        "actual": Decimal("30000"),
        "evaluated_at": _SINCE,
    }
    return RiskDecision(**{**base, **fields})


@pytest.mark.parametrize(
    "model",
    [
        _lockout(
            user_id=uuid4(),
            threshold=Decimal("1000.000000000000000001"),
            actual_value=Decimal("-1400.5"),
            until=_SINCE + timedelta(hours=10),
            released_at=_SINCE + timedelta(hours=1),
            released_by=uuid4(),
            release_reason="owner override after review",
            actions_taken=LockoutActions(orders_cancelled=3, positions_flattened=1),
        ),
        _switch(
            scope=KillSwitchScope.ACCOUNTS,
            exchange_account_id=_ACCOUNT,
            engaged=True,
            engaged_at=_SINCE,
            engaged_by=uuid4(),
            reason="freeze during the outage",
            options=KillSwitchOptions(cancel_open_orders=False, disarm_rules=False),
        ),
        _refusal(),
        RiskDecision(allowed=True, evaluated_at=_SINCE),
    ],
    ids=["lockout", "switch", "refusal", "allowed"],
)
def test_every_model_round_trips_through_json_unchanged(model: BaseModel) -> None:
    assert type(model).model_validate_json(model.model_dump_json()) == model


def test_a_lockout_is_active_until_released_and_defaults_to_no_actions() -> None:
    active = _lockout(until=None)  # an explicit None passes the UTC validator untouched
    assert active.is_active and active.actions_taken == LockoutActions()
    end = _SINCE + timedelta(hours=10)
    assert not _lockout(until=end, released_at=end).is_active  # the clock's release
    assert not _lockout(released_at=_SINCE, released_by=uuid4(), release_reason="owner").is_active


def test_timestamps_are_normalised_to_utc() -> None:
    plus_five = datetime(2026, 10, 20, 18, 41, tzinfo=timezone(timedelta(hours=5)))
    since = _lockout(since=plus_five).since
    assert since == _SINCE and since.tzinfo is UTC


def test_the_switch_options_default_to_the_contracts_request_defaults() -> None:
    assert KillSwitchOptions().model_dump() == {
        "cancel_open_orders": True,
        "flatten_positions": False,
        "disarm_rules": True,
    }


@pytest.mark.parametrize(
    ("fields", "check"),
    [
        pytest.param({"until": _SINCE}, "rl_until", id="until-not-after-since"),
        pytest.param({"released_at": _SINCE - timedelta(seconds=1)}, "rl_released", id="early"),
        pytest.param({"released_by": uuid4()}, "rl_release", id="releaser-without-release"),
        pytest.param({"release_reason": "no release"}, "rl_release", id="reason-without-release"),
        pytest.param(
            {"reason": LockoutReason.MANUAL, "until": _SINCE + timedelta(hours=1)},
            "rl_manual",
            id="manual-with-a-clock-end",
        ),
        pytest.param({"released_at": _SINCE}, "rl_release", id="release-by-nobody-without-an-end"),
        pytest.param(
            {"until": _SINCE + timedelta(hours=2), "released_at": _SINCE + timedelta(hours=1)},
            "rl_release",
            id="clock-release-before-the-end",
        ),
        pytest.param(
            {"released_at": _SINCE, "released_by": uuid4()}, "rl_release", id="release-no-reason"
        ),
    ],
)
def test_a_lockout_refuses_what_its_table_refuses(fields: dict[str, Any], check: str) -> None:
    with pytest.raises(ValidationError, match=check):
        _lockout(**fields)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"reason": "drawdown"}, id="reason-unknown"),
        pytest.param({"released_at": _SINCE, "release_reason": "ab"}, id="reason-too-short"),
        pytest.param({"released_at": _SINCE, "release_reason": "x" * 281}, id="reason-too-long"),
        pytest.param({"released_at": _SINCE, "release_reason": "   "}, id="reason-blank"),
        pytest.param(  # 4 characters, 2 after trimming: refused by rl_text's trimmed count alone
            {"released_at": _SINCE, "released_by": uuid4(), "release_reason": "  ab"},
            id="reason-padded",
        ),
        pytest.param({"actions_taken": {"orders_cancelled": -1}}, id="negative-count"),
        pytest.param({"actions_taken": {"positions_flattened": -1}}, id="negative-flattened"),
        pytest.param({"actions_taken": {"rules_disarmed": 1}}, id="unknown-action-key"),
        pytest.param({"since": _SINCE.replace(tzinfo=None)}, id="naive-since"),
        pytest.param({"threshold": 1.5}, id="float-money"),
        # numeric(38,18) holds 20 whole digits: PostgreSQL refuses a 21st (22003), so the model does
        pytest.param({"threshold": Decimal("100000000000000000000")}, id="21-whole-digits"),
        pytest.param({"actual_value": Decimal("1E+20")}, id="21-whole-digits-exponent"),
        pytest.param({"actual_value": Decimal("0.1234567890123456789")}, id="19-places"),
        pytest.param({"threshold": Decimal("NaN")}, id="nan-money"),
        pytest.param({"note": "x"}, id="unknown-field"),
    ],
)
def test_a_lockout_refuses_an_invalid_field(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _lockout(**fields)


def test_lockout_bounds_are_inclusive() -> None:
    person = {"released_at": _SINCE, "released_by": uuid4()}
    assert _lockout(**person, release_reason="abc").release_reason == "abc"
    assert _lockout(**person, release_reason="x" * 280).released_at == _SINCE
    # a lockout that cancelled and flattened nothing records explicit zeros
    nothing = LockoutActions(orders_cancelled=0, positions_flattened=0)
    assert _lockout(actions_taken=nothing).actions_taken == LockoutActions()
    widest = Decimal("99999999999999999999.999999999999999999")  # 20 whole digits, 18 places
    # copy_negate: unary minus would round to the 28-digit default context
    assert _lockout(threshold=widest, actual_value=widest.copy_negate()).threshold == widest


@pytest.mark.parametrize(
    ("fields", "check"),
    [
        pytest.param({"exchange_account_id": _ACCOUNT}, "kss_target", id="global-with-account"),
        pytest.param({"scope": KillSwitchScope.ACCOUNTS}, "kss_target", id="accounts-no-account"),
        pytest.param({"engaged": True, "reason": "freeze"}, "kss_engaged", id="no-time"),
        pytest.param({"engaged": True, "engaged_at": _SINCE}, "kss_engaged", id="no-reason"),
    ],
)
def test_a_switch_row_refuses_what_its_table_refuses(fields: dict[str, Any], check: str) -> None:
    with pytest.raises(ValidationError, match=check):
        _switch(**fields)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"scope": "symbol"}, id="scope-unknown"),
        pytest.param({"reason": "ab"}, id="reason-too-short"),
        pytest.param({"reason": "  \t "}, id="reason-blank"),
        pytest.param({"reason": "  ab"}, id="reason-padded"),
        pytest.param({"options": {"cancel_open_orders": True, "panic": True}}, id="unknown-option"),
        pytest.param({"updated_at": _SINCE.replace(tzinfo=None)}, id="naive-updated-at"),
    ],
)
def test_a_switch_row_refuses_an_invalid_field(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _switch(**fields)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"code": None}, id="refusal-without-code"),
        pytest.param({"allowed": True}, id="allowed-with-code"),
        pytest.param({"cap": "Max Position"}, id="cap-not-a-name"),
        pytest.param({"limit": 1.5}, id="float-limit"),
        pytest.param({"actual": 1.5}, id="float-actual"),
        pytest.param({"evaluated_at": _SINCE.replace(tzinfo=None)}, id="naive-evaluated-at"),
    ],
)
def test_a_decision_is_either_allowed_or_one_refusal(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _refusal(**fields)


def test_a_refusal_carries_any_finite_figure() -> None:
    """A verdict is never persisted, so a computed figure needs no quantizing first."""
    third = Decimal(1) / Decimal(3)
    refusal = _refusal(limit=third, actual=Decimal("1E+30"))
    assert (refusal.limit, refusal.actual) == (third, Decimal("1E+30"))
    for figure in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValidationError, match="finite"):
            _refusal(actual=Decimal(figure))


@pytest.mark.parametrize(
    "named",
    [{"cap": "max_open_positions"}, {"limit": Decimal(1)}, {"actual": Decimal(1)}],
    ids=["cap", "limit", "actual"],
)
def test_an_allowed_decision_names_no_cap(named: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="names no cap"):
        RiskDecision(allowed=True, evaluated_at=_SINCE, **named)


def test_the_models_are_frozen() -> None:
    lockout = _lockout()
    with pytest.raises(ValidationError):
        lockout.reason = LockoutReason.MANUAL
