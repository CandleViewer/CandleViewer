"""Seeded mutants of the bootstrap-Owner CLI and of the gate it runs on (#4479 C2; the repo's
convention, see `tests/unit/credentials_m2/test_mutations.py`).

Each case injects one plausible defect via monkeypatch, runs the real oracle test of
`test_bootstrap_owner_flow.py` under it and asserts that the oracle fails (mutant killed); every
oracle passes unmutated. A source mutant recompiles one method of the real code with one fragment
replaced, once it has checked that the fragment occurs exactly once, so a refactor that moves the
fragment fails here instead of passing unmutated. Two mutants keep the oracle's exit status (the
first probe skipped; `owner_exists` let through at the target, which the mint refuses again):
only the exact port trace kills them (DC-4479-06).
"""

from __future__ import annotations
import __future__

import inspect
import sys
import textwrap
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

import pytest

from candleviewer.admin import bootstrap_owner as flow
from candleviewer.admin.breakglass import HostGatedFlow, Verdict
from candleviewer.auth.bootstrap_owner import BootstrapTarget, bootstrap_identity
from candleviewer.secrets import KekCheckResult
from tests.unit.admin import test_bootstrap_owner_flow as oracle
from tests.unit.admin.test_bootstrap_owner_flow import _known_token  # noqa: F401 - autouse fixture

_KILLED = (AssertionError, pytest.fail.Exception)
X = flow.BootstrapOwnerExit
_CHECKS, _MINTS = oracle._CHECKS, oracle._MINTS
_REAL_TARGET = flow.BootstrapOwnerFlow._target


def _source(owner: type, name: str, fragment: str, replacement: str) -> Callable[..., Any]:
    """`owner.name` recompiled from its source, `fragment` (found exactly once) replaced, in its
    own module's globals."""
    source = textwrap.dedent(inspect.getsource(vars(owner)[name]))
    assert source.count(fragment) == 1, (owner.__name__, name, fragment)
    module = sys.modules[owner.__module__]
    flags = __future__.annotations.compiler_flag
    code = compile(source.replace(fragment, replacement), module.__file__ or "", "exec", flags)
    namespace: dict[str, Any] = {}
    exec(code, vars(module), namespace)  # noqa: S102 - the repo's own source, one fragment swapped
    mutant: Callable[..., Any] = namespace[name]
    return mutant


async def _owner_exists_let_through(
    self: flow.BootstrapOwnerFlow, records: Any, email: str
) -> Verdict | BootstrapTarget:
    """The target check forgets `owner_exists`: the run goes on to the TTY, the phrase and the
    mint, whose own re-check under its lock still refuses with 17."""
    found = await _REAL_TARGET(self, records, email)
    identity = bootstrap_identity(email)
    if isinstance(found, Verdict) and found.status is X.OWNER_EXISTS and identity is not None:
        return BootstrapTarget(*identity, None)
    return found


def _refusal(setup: dict[str, Any], status: X, ran: list[str]) -> Callable[[], Awaitable[None]]:
    """The oracle's refusal case for `setup`: its exit status and its exact trace."""
    each = oracle.test_each_refusal_writes_a_critical_denied_record
    return partial(each, setup, False, status, ran)


def _swap(owner: type, method: str, fragment: str, new: str) -> tuple[type, str, Callable[[], Any]]:
    return owner, method, partial(_source, owner, method, fragment, new)


_GATE, _FLOW = HostGatedFlow, flow.BootstrapOwnerFlow
_UP, _LAST = 'if await self._step("api_probe", self._ports.api_running):', "refused = None"
#: name -> (class, method, the mutant method, oracle): one plausible defect each.
MUTANTS: dict[str, tuple[type, str, Callable[[], Any], Callable[[], Awaitable[None]]]] = {
    "kcv_ok_ignored": (
        *_swap(_GATE, "_check", "if not proof.kcv_ok:", "if False:"),
        _refusal({"kek": KekCheckResult(None, False, "kek_mismatch")}, X.KEK_UNPROVEN, _CHECKS[:3]),
    ),
    "first_probe_skipped": (
        *_swap(_GATE, "_check", _UP, "if False:"),
        _refusal({"api_up": True}, X.API_RUNNING, _CHECKS[:4]),
    ),
    "last_probe_skipped": (
        *_swap(_FLOW, "_act", "refused = await self._probe_again()", _LAST),
        _refusal({"api_up": [False, True]}, X.API_RUNNING, _MINTS[:-1]),
    ),
    "is_interactive_ignored": (
        *_swap(_GATE, "_confirm", "if not terminal.is_interactive():", "if False:"),
        _refusal({"tty": False}, X.NO_TTY, _CHECKS[:6]),
    ),
    "phrase_check_bypassed": (
        *_swap(_GATE, "_confirm", "typed.strip() == phrase", "True"),
        _refusal({"typed": "bootstrap owner@example.invalid on demo"}, X.CONFIRMATION_MISMATCH,
                 _CHECKS),
    ),
    "live_flag_ignored": (
        *_swap(_GATE, "_check", "if live_flag != self._live:", "if False:"),
        _refusal({"env": oracle.LIVE}, X.LIVE_FLAG_REQUIRED, _CHECKS[:2]),
    ),
    "owner_exists_let_through_at_the_target": (
        _FLOW, "_target", lambda: _owner_exists_let_through,
        _refusal(oracle._OWNED, X.OWNER_EXISTS, _CHECKS[:5]),
    ),
    "mint_refusal_is_success": (
        *_swap(_FLOW, "_act", "Verdict(_REFUSED_BY_MINT[exc.reason])", "Verdict(_X.INVITED)"),
        _refusal({"minted": "owner_exists"}, X.OWNER_EXISTS, _MINTS),
    ),
    "token_printed_after_its_record_failed": (
        *_swap(_FLOW, "_outcome", "if verdict.unrecorded or token is None:", "if token is None:"),
        oracle.test_token_is_withheld_when_the_invited_record_fails,
    ),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(MUTANTS))
async def test_mutant_killed(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    owner, method, mutant, check = MUTANTS[name]
    monkeypatch.setattr(owner, method, mutant())
    with pytest.raises(_KILLED):
        await check()


@pytest.mark.parametrize("name", sorted(MUTANTS))
async def test_every_oracle_passes_unmutated(name: str) -> None:
    await MUTANTS[name][3]()
