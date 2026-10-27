"""E28-T05 S2a (#909): `GateReadiness`, trade-group readiness over the order-entry gate, the kill
switch, the live gate and the account row, the first reason winning. The ports are faked."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.trade_group_readiness import ReadinessMember, ReadinessReason, readiness
from candleviewer.domain.order_entry import REFUSAL_REASONS, OrderEntryRefusal, RefusalReason
from candleviewer.domain.primitives import Environment
from candleviewer.trade_groups_wiring import GATE_REASONS, GateReadiness, NoLockouts
from tests.unit.accounts._fakes import ACC

NOT_A_BOOL = cast(bool, 1)  # truthy, and not the bool the type promises


def _only(answer: Any) -> Callable[[UUID], Any]:
    """A port's answer for `ACC` alone: a lookup on any other account fails the test."""

    def ask(account_id: UUID) -> Any:
        assert account_id == ACC
        return answer

    return ask


def _source(
    gate: Any = None, lockouts: Any = None, env: Environment = "demo", **world: Any
) -> GateReadiness:
    """`world`: the kill switch's answer (`kill`: a refusal, none) and the live gate's `setting` and
    `flag` (on). The flag is read for a live account alone, as the OMS reads it."""

    def flag() -> Any:
        assert env not in ("demo", "testnet")
        return world.get("flag", True)

    return GateReadiness(
        gate,
        kill_switch=_only(world.get("kill")),
        live_enabled=world.get("setting", True),
        live_flag=flag,
        lockouts=lockouts or Mock(locked=_only(False)),
    )


def _reason(
    row: bool = True,
    gate: RefusalReason | None = None,
    locked: object = False,
    env: Environment = "demo",
    **world: Any,
) -> ReadinessReason | None:
    refusal = None if gate is None else OrderEntryRefusal(gate, "Refused.")
    source = _source(Mock(refusal=_only(refusal)), Mock(locked=_only(locked)), env, **world)
    return source.reason(ACC, env, account_enabled=row)


CASES: dict[str, tuple[dict[str, Any], ReadinessReason | None]] = {
    "ready": ({}, None),
    "row switched off": ({"row": False}, "account_disabled"),
    "row not a bool": ({"row": NOT_A_BOOL}, "account_disabled"),
    "no active key": ({"gate": "no_active_key"}, "key_invalid"),
    "disabled by policy": ({"gate": "account_disabled_by_policy"}, "account_disabled"),
    "unhealthy": ({"gate": "account_unhealthy"}, "account_unhealthy"),
    "maintenance": ({"gate": "maintenance"}, "trading_disabled"),
    "kill switch": ({"kill": True}, "kill_switch_engaged"),
    "kill switch answering 0": ({"kill": 0}, "kill_switch_engaged"),
    "kill switch answering False": ({"kill": False}, "kill_switch_engaged"),
    "kill switch answering an empty string": ({"kill": ""}, "kill_switch_engaged"),
    "live, setting off": ({"env": "live", "setting": False}, "trading_disabled"),
    "live, setting not a bool": ({"env": "live", "setting": NOT_A_BOOL}, "trading_disabled"),
    "live, flag off": ({"env": "live", "flag": False}, "trading_disabled"),
    "live, flag not a bool": ({"env": "live", "flag": NOT_A_BOOL}, "trading_disabled"),
    "live, both on": ({"env": "live"}, None),
    "an unknown environment is live": ({"env": "paper", "flag": False}, "trading_disabled"),
    "demo meets no live gate": ({"setting": False, "flag": False}, None),
    "testnet meets no live gate": ({"env": "testnet", "setting": False}, None),
    "locked": ({"locked": True}, "account_locked"),
    "lockout source cannot tell": ({"locked": None}, "account_locked"),
    "first: row, gate": ({"row": False, "gate": "no_active_key"}, "account_disabled"),
    "first: gate, switch": ({"gate": "maintenance", "kill": True}, "trading_disabled"),
    "first: switch, live": ({"kill": True, "env": "live", "flag": False}, "kill_switch_engaged"),
    "first: live, lock": ({"env": "live", "flag": False, "locked": True}, "trading_disabled"),
}


@pytest.mark.parametrize(("world", "expected"), CASES.values(), ids=CASES)
def test_each_order_entry_refusal_maps_to_its_reason(
    world: dict[str, Any], expected: ReadinessReason | None
) -> None:
    assert _reason(**world) == expected
    assert not inspect.iscoroutinefunction(GateReadiness.reason)  # no await: C-2.21


def test_a_refusal_the_table_does_not_hold_is_not_ready() -> None:
    assert set(GATE_REASONS) == REFUSAL_REASONS  # a reason E27 adds must be decided here
    newer = SimpleNamespace(reason="a_reason_e27_adds_later")  # a look-alike the real gate refuses
    gate = Mock(refusal=_only(newer))
    assert _source(gate).reason(ACC, "demo", account_enabled=True) == "trading_disabled"


def test_no_gate_means_no_member_is_ready() -> None:
    members = [ReadinessMember(UUID(int=n), True, n != 2) for n in (1, 2, 3)]  # row 2 switched off
    result = readiness(members, _source(None), "demo")
    assert (result.ready, result.total) == (0, 3)
    assert [(m.ready, m.reason) for m in result.members] == [(False, "trading_disabled")] * 3


def test_no_lockout_is_reported_until_e39() -> None:
    assert NoLockouts().locked(ACC) is False
    with capture_logs() as logs:
        assert _source(None, NoLockouts()).announce()
    announced = [(e["log_level"], e["port"], e["replaced_by"], e["serves"]) for e in logs]
    assert announced == [("warning", "risk_lockouts", "E39-S02", NoLockouts.serves)]
    with capture_logs() as logs:
        assert not _source(None).announce()  # a real lockout source: nothing to say
    assert logs == []
