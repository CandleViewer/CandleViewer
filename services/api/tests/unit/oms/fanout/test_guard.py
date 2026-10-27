"""E28-T05 S3a2 (#909): the E28-T04 leg-guard hook. `S4SGuard` refuses a market leg past
`max_mkt_order_qty`, reads the switches then the risk gate, maps the gate's verdict onto 22's codes
and fails closed on a fence or a fault, logged by its class alone; it reads memory only and imports
no write or exchange port (SR-E28-22, C-2.21, C-12.6)."""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

import candleviewer.oms.fanout.guard as guard
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.oms import ports
from candleviewer.oms.errors import OmsNotReady, TradingDisabled
from candleviewer.risk.models import RiskDecision, RiskRefusal
from tests.unit.oms.submit_rig import instrument, profile

D = Decimal
A = AccountId(UUID(int=1))
NOW = datetime(2026, 10, 27, tzinfo=UTC)
ALLOWED = RiskDecision(allowed=True, evaluated_at=NOW)


class _Port:
    """A switch or a risk gate answering `answer`, or raising it (a fence, a fault); it records."""

    def __init__(self, answer: Any = None) -> None:
        self.answer, self.asked = answer, list[Any]()

    def _answer(self, asked: Any) -> Any:
        self.asked.append(asked)
        if isinstance(self.answer, OmsNotReady | RuntimeError):
            raise self.answer
        return self.answer

    def refusal(self, account_id: AccountId, environment: Environment) -> Any:
        return self._answer(account_id)

    def check(self, order: ports.SizedOrder, *, profile: Any) -> Any:
        return self._answer(order)


def _guard(gate: Any = None, switch: Any = None) -> guard.S4SGuard:
    return guard.S4SGuard(gate or ports.InterimRiskGate(now=lambda: NOW), _Port(switch))


def _order(**over: Any) -> ports.SizedOrder:
    """A demo market buy of 1 BTCUSDT from 60000, its native stop at 57000."""
    base: dict[str, Any] = dict(
        account_id=A, environment="demo", symbol="BTCUSDT", side="buy", qty=D(1), price=None,
        order_type="market", trigger_price=None, reduce_only=False, intent="entry",
        reference_price=D(60000), stop_loss=D(57000), effect=ports.OrderEffect.ENTRY,
    )  # fmt: skip
    return ports.SizedOrder(**(base | over))


def _refused(code: RiskRefusal) -> RiskDecision:
    return RiskDecision(allowed=False, code=code, message="Refused.", evaluated_at=NOW)


@pytest.mark.parametrize("env", ["demo", "testnet", "live"])
def test_the_hook_blocks_what_the_interim_risk_gate_refuses(env: Environment) -> None:
    """Over the interim risk gate: demo admitted unevaluated, any other environment refused."""
    got = _guard().refusal(_order(environment=env), profile=profile(A), instrument=instrument())
    assert got == (None if env == "demo" else "risk_state_unavailable")


@pytest.mark.parametrize(
    ("over", "code"),
    [({"qty": D(50)}, None), ({"qty": D("50.001")}, "cap_breached"),
     ({"order_type": "limit", "price": D(60000), "qty": D(60)}, None)],
    ids=["market_at_the_cap", "market_past_it", "limit_past_it"],
)  # fmt: skip
def test_a_market_leg_over_max_mkt_order_qty_is_refused(over: dict[str, Any], code: Any) -> None:
    """The comparator leaves `max_mkt_order_qty` (50 on BTCUSDT) to its caller (#2635)."""
    assert _guard().refusal(_order(**over), profile=profile(A), instrument=instrument()) == code


@pytest.mark.parametrize(
    ("switch", "decision", "code"),
    [(TradingDisabled(), ALLOWED, "trading_disabled"), (OmsNotReady(), ALLOWED, "trading_disabled"),
     (None, RuntimeError("echoed exchange text"), "risk_state_unavailable"),
     (None, _refused(RiskRefusal.RISK_LIMIT_BREACHED), "cap_breached"),
     (None, _refused(RiskRefusal.ACCOUNT_LOCKED), "account_locked"),
     (None, _refused(RiskRefusal.RISK_STATE_UNAVAILABLE), "risk_state_unavailable")],
    ids=["switched_off", "fenced", "gate_raises", "risk_limit", "locked", "no_state"],
)  # fmt: skip
def test_the_hook_reads_the_switches_then_the_risk_gate_and_fails_closed(
    switch: Any, decision: Any, code: str
) -> None:
    gate = _Port(decision)
    with capture_logs() as logs:
        got = _guard(gate, switch).refusal(_order(), profile=profile(A), instrument=instrument())
    assert got == code and len(gate.asked) == (switch is None)
    faulted = isinstance(decision, Exception)  # a port's fault is logged by its class alone
    assert [(e["account_id"], e["error"]) for e in logs] == [(str(A), "RuntimeError")] * faulted
    assert "echoed" not in repr(logs)  # never its text (C-12.6)


def test_a_value_outside_22s_codes_fails_closed() -> None:
    assert guard.rejection_code(RiskRefusal.ACCOUNT_LOCKED, "trading_disabled") == "account_locked"
    assert guard.rejection_code("member_disabled", "trading_disabled") == "trading_disabled"


def test_the_guard_reads_memory_and_imports_no_write_or_exchange_port() -> None:
    """SR-E28-22, C-2.21: what the hook imports, the `ports` it reads, and no `await`."""
    tree = ast.parse(inspect.getsource(guard))
    froms = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert {(n.module, a.name) for n in froms if n.module != "typing" for a in n.names} == {
        ("__future__", "annotations"), ("candleviewer.accounts.profiles", "AccountProfile"),
        ("candleviewer.domain.events", "Instrument"), ("candleviewer.oms", "ports"),
        ("candleviewer.oms.errors", "OmsNotReady"), ("candleviewer.risk.models", "RiskRefusal"),
    }  # fmt: skip
    read = {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and ast.unparse(n.value) == "ports"}  # fmt: skip
    assert read == {"RiskGate", "SizedOrder", "TradingSwitches"}
    assert {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} == {
        "structlog"
    }
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Await | ast.AsyncFunctionDef)]
