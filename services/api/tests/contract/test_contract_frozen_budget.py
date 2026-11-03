"""#5639: the contract worlds read consequences on a budget no runner stall can spend.

The worlds once built `ConsequenceRead` / `ExposureRead` with the production budget, so a stall of
about a second inside a request answered `503 exchange_unavailable` where a test expected the
port's verdict. Every world builds them through `_frozen_budget.consequence_read`; the last
two tests show the stall on the production budget and the helper's immunity to it.
"""

from __future__ import annotations

import ast
import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from candleviewer.accounts.consequences import ConsequenceRead
from candleviewer.accounts.exposure import (
    ExposureFailed,
    ExposureRead,
    ExposureUnknown,
    KeyReadFailed,
)
from candleviewer.storage.repositories.accounts import OwnerScope
from tests.contract import _frozen_budget
from tests.contract._frozen_budget import consequence_read
from tests.contract.rbac.rbac_harness import GRANTED, user_id_of
from tests.contract.test_account_consequences_provider import Ports

CONTRACT = Path(__file__).resolve().parent
BUILT = frozenset({"ConsequenceRead", "ExposureRead"})
HELPER = Path(_frozen_budget.__file__).resolve()
#: This file builds one on the production budget on purpose, to show the mechanism.
ALLOWED = frozenset({HELPER, Path(__file__).resolve()})


def _builds(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            if name in BUILT:
                found.append(f"{path.relative_to(CONTRACT)}:{node.lineno} {name}")
    return found


def test_contract_readers_built_outside_the_helper_none() -> None:
    stray = [hit for p in sorted(CONTRACT.rglob("*.py")) if p not in ALLOWED for hit in _builds(p)]
    assert stray == []


def _stalling_clock() -> Callable[[], float]:
    """A wall clock that jumps 2 s between readings, as a runner stall inside a request does."""
    ticks = iter(range(0, 1000, 2))
    return lambda: float(next(ticks))


def _read_after_a_stall(read: ConsequenceRead, ports: Ports) -> object:
    """The granted account's consequence read, its key refused `ip_not_allowed` (fixable)."""
    ports.reset()
    ports.answer = KeyReadFailed("ip_not_allowed")
    owner = OwnerScope(user_id_of("owner"))
    return asyncio.run(read.read(owner, owner, GRANTED))


def test_contract_production_budget_after_a_stall_fails_closed_503() -> None:
    """The flake's mechanism: on the production budget a stall spends it, no request is sent and
    every key reads `timeout`, so the port's verdict never decides (`503 exchange_unavailable`)."""
    ports = Ports()
    stalled = ConsequenceRead(ports, ExposureRead(ports, env="demo"), ports, ports, env="demo",
                              clock=_stalling_clock())  # fmt: skip
    got = _read_after_a_stall(stalled, ports)
    assert isinstance(got, ExposureFailed) and got.status == 503 and ports.reads == 0


def test_contract_frozen_budget_after_a_stall_answers_the_port_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The helper never reads the wall clock, so the same stall leaves the verdict to the port."""
    monkeypatch.setattr(time, "monotonic", _stalling_clock())
    ports = Ports()
    got = _read_after_a_stall(consequence_read(ports, env="demo"), ports)
    assert isinstance(got, ExposureUnknown) and ports.reads == 1
