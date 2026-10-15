"""#2624: every permission-shaped string literal in the backend is a seeded RBAC code.

The rule scope gate checked `rules.arm_live` while the database seeds `rules:arm_live`
(migration 0015), so nobody could scope a rule to live, and test fakes granting the same dot
form hid it. This scans every string constant under `candleviewer/` and fails on:

1. a `domain:action` literal whose domain is a seeded permission domain but which is not a
   code in `auth/rbac_seed.json` (a typo, or a permission nobody can hold); and
2. a dot-form twin of a seeded code (`rules.arm_live` for `rules:arm_live`) unless it is a
   registered audit action (`audit.actions.AUDIT_ACTIONS`, a separate vocabulary) or an
   entry of `_ALLOWED_DOT_TWINS`.

Only whole literals are checked, so prose that mentions a permission is never flagged.
"""

from __future__ import annotations

import ast
import json
import re
import warnings
from collections.abc import Collection, Mapping
from functools import cache
from pathlib import Path

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS

PKG = Path(__file__).resolve().parents[3] / "candleviewer"
SEED = json.loads((PKG / "auth" / "rbac_seed.json").read_text("utf-8"))
CODES = frozenset(p["code"] for p in SEED["permissions"])
DOMAINS = frozenset(c.partition(":")[0] for c in CODES)
_COLON = re.compile(r"(?P<domain>[A-Za-z][A-Za-z0-9_]*):[A-Za-z0-9_*.\-]+")

#: Genuine non-permission literals that are dot-form twins of a seeded code, keyed by
#: (path relative to `candleviewer/`, literal) so one exception never covers another module.
#: Each value names the vocabulary the literal belongs to. Example of a legitimate future
#: entry: the `rules.arm_live` feature flag (24-internal-schemas.md flags table) in a flags
#: registry. Never list a permission check here: it must use the seeded `domain:action` code.
_ALLOWED_DOT_TWINS: dict[tuple[str, str], str] = {}


def _literals(source: str, filename: str) -> list[tuple[int, str]]:
    with warnings.catch_warnings():
        # Migration 0001 is immutable (C-5.4) and has an invalid escape in its SQL text; the
        # SyntaxWarning concerns that file's escapes, not the literals this test checks.
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source, filename=filename)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _violations(
    literals: list[tuple[int, str]],
    rel: str,
    *,
    audit_actions: Collection[str] = AUDIT_ACTIONS,
    allowed: Mapping[tuple[str, str], str] = _ALLOWED_DOT_TWINS,
) -> list[str]:
    out: list[str] = []
    for line, s in literals:
        m = _COLON.fullmatch(s)
        if m and m.group("domain").lower() in DOMAINS and s not in CODES:
            out.append(f"{rel}:{line}: {s!r} is not a permission code in rbac_seed.json")
        twin = s.replace(".", ":", 1)
        if twin != s and twin in CODES and s not in audit_actions and (rel, s) not in allowed:
            out.append(f"{rel}:{line}: {s!r} is a dot-form twin of the seeded code {twin!r}")
    return out


@cache
def _backend_literals() -> dict[str, list[tuple[int, str]]]:
    return {
        path.relative_to(PKG).as_posix(): _literals(path.read_text("utf-8"), str(path))
        for path in sorted(PKG.rglob("*.py"))
    }


def test_permission_literals_every_backend_literal_is_a_seeded_code() -> None:
    scanned = _backend_literals()
    seen = {s for literals in scanned.values() for _, s in literals}
    assert CODES <= seen  # not vacuous: the generated `Permission` enum itself was scanned
    problems = [v for rel, literals in scanned.items() for v in _violations(literals, rel)]
    assert problems == [], "\n".join(problems)


def test_permission_literals_allow_list_has_no_stale_entries() -> None:
    scanned = _backend_literals()
    present = {(rel, s) for rel, literals in scanned.items() for _, s in literals}
    assert set(_ALLOWED_DOT_TWINS) <= present


@pytest.mark.parametrize(
    ("literal", "flagged"),
    [
        ("rules.arm_live", True),  # #2624: the dot-form twin of the seeded code
        ("rules:arm-live", True),  # not a seeded code (typo)
        ("RULES:arm_live", True),  # a different string to the database
        ("rules:loosen_stop", True),  # a permission no role can hold
        ("rules:arm_live", False),  # the seeded code
        ("rules.arm", False),  # an audit action whose colon form is not a code
        ("users.id", False),  # a foreign-key target, not a permission twin
        ("Including live needs rules.arm_live.", False),  # prose is not a whole literal
    ],
)
def test_permission_literals_scanner_flags_only_drifted_codes(literal: str, flagged: bool) -> None:
    literals = _literals(f"X = {literal!r}\n", "x.py")
    assert bool(_violations(literals, "x.py")) is flagged


def test_permission_literals_dot_twin_exemptions_are_exact() -> None:
    literals = _literals('X = "rules.arm_live"\n', "x.py")
    assert _violations(literals, "x.py", audit_actions={"rules.arm_live"}) == []
    assert _violations(literals, "x.py", allowed={("x.py", "rules.arm_live"): "flag key"}) == []
    assert _violations(literals, "y.py", allowed={("x.py", "rules.arm_live"): "flag key"})
