"""Every audit action the HTTP and WS edges emit is registered (#2144).

`AuditWriter.emit` refuses an action outside `AUDIT_ACTIONS`, which turns an audited refusal
into a 500 with no row: that happened to `users.invite_refused` and
`users.invite_role_downgraded`. Router fakes accept any string, so this reads the literal action
arguments of the emit calls straight from the source of every `api/*.py` module and the WS edge.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import candleviewer
from candleviewer.audit.actions import AUDIT_ACTIONS

_ROOT = Path(candleviewer.__file__).parent
_MODULES = sorted(
    [p.relative_to(_ROOT).as_posix() for p in (_ROOT / "api").glob("*.py")]
    + ["ws/gateway.py", "ws/permissions.py"]
)
_EMITTERS = frozenset({"emit", "_audit", "_audit_owner"})
_ACTION = re.compile(r"^[a-z0-9_]+([.][a-z0-9_]+){1,3}$")


def _emitted(module: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse((_ROOT / module).read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _EMITTERS:
            continue
        for arg in node.args[:2]:  # `emit(action, ...)` or `_audit(service, action, ...)`
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if _ACTION.match(arg.value):
                    found.add(arg.value)
    return found


@pytest.mark.parametrize("module", _MODULES)
def test_every_literal_audit_action_emitted_is_registered(module: str) -> None:
    assert _emitted(module) - AUDIT_ACTIONS == set()


def test_the_scan_still_finds_the_actions_it_guards() -> None:
    found = (
        _emitted("api/auth.py")
        | _emitted("api/sessions.py")
        | _emitted("api/invites.py")
        | _emitted("api/onboarding.py")
    )
    assert {
        "auth.login",
        "auth.session_fixation_attempt",
        "users.invite_refused",
        "onboarding.checklist_tamper_rejected",
    } <= found
