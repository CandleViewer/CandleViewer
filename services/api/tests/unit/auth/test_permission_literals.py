"""#2624: every permission-shaped string literal in the backend is a seeded RBAC code.

The rule scope gate checked `rules.arm_live` while the database seeds `rules:arm_live`
(migration 0015), so nobody could scope a rule to live, and test fakes granting the same dot
form hid it. This scans every Python file under `candleviewer/` and fails on:

1. a `domain:action` literal whose domain is a seeded permission domain but which is not a
   code in `auth/rbac_seed.json` (a typo, or a permission nobody can hold);
2. a dot-form twin of a seeded code (`rules.arm_live` for `rules:arm_live`) unless it is an
   entry of `_ALLOWED_DOT_TWINS`. Audit actions get no blanket exemption, and no registered
   audit action may be such a twin; and
3. a module-level constant named `*_PERMISSION` (or a string item of a `*_PERMISSIONS`
   tuple, list or set) that is not a seeded code, unless it is an entry of `_KNOWN_UNSEEDED`.
   This catches a permission in a domain the seed does not have at all.

Rules 1 and 2 check only whole literals, so prose that mentions a permission is never flagged.
"""

from __future__ import annotations

import ast
import json
import re
import warnings
from collections.abc import Mapping
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

#: Known defects, keyed like `_ALLOWED_DOT_TWINS`: permission constants with no seeded code.
#: Each fails closed (no role, owner included, holds it). Seeding a code needs an OpenAPI
#: x-rbac change, `tools/rbac/generate.py` and a migration, so each is its own ticket. This
#: list only shrinks: drop an entry in the PR that seeds its code (the stale-entry test fails
#: until you do), and give every new permission constant a seeded code instead of a row here.
_KNOWN_UNSEEDED: dict[tuple[str, str], str] = {
    ("rules/validator.py", "rules.loosen_stop"): (
        "LOOSEN_STOP_PERMISSION, also declared by the widen_stop action and probed by "
        "api/rules.py: until rules:loosen_stop is seeded, only_tighten=false is a save-blocking "
        "safety error for everyone"
    ),
    ("storage/retention/policy.py", "retention.change"): (
        "RETENTION_CHANGE_PERMISSION, also an audit action: require_retention_change has no "
        "production caller yet"
    ),
}

_Literal = tuple[int, str]  # (line, value)
_Declared = tuple[int, str, str]  # (line, constant name, value)
_DISPLAYS = (ast.Tuple, ast.List, ast.Set)  # `*_PERMISSIONS` collections whose items are read


def _parse(source: str, filename: str) -> ast.Module:
    with warnings.catch_warnings():
        # Migration 0001 is immutable (C-5.4) and has an invalid escape in its SQL text; the
        # SyntaxWarning concerns that file's escapes, not the literals this test checks.
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source, filename=filename)


def _literals(tree: ast.Module) -> list[_Literal]:
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _declared(tree: ast.Module) -> list[_Declared]:
    """String values bound at module level to `*_PERMISSION` or in a `*_PERMISSIONS` display.

    Names (`ARM_LIVE = LIVE_ARM_PERMISSION`) are skipped: their source constant is checked.
    """
    out: list[_Declared] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets: list[ast.expr] = stmt.targets
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [stmt.target]
            value = stmt.value
        else:
            continue
        for name in (t.id for t in targets if isinstance(t, ast.Name)):
            if name.endswith("_PERMISSION"):
                items: list[ast.expr] = [value]
            elif name.endswith("_PERMISSIONS") and isinstance(value, _DISPLAYS):
                items = value.elts
            else:
                continue
            out += [
                (item.lineno, name, item.value)
                for item in items
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
    return out


def _violations(
    literals: list[_Literal],
    rel: str,
    *,
    allowed: Mapping[tuple[str, str], str] = _ALLOWED_DOT_TWINS,
) -> list[str]:
    out: list[str] = []
    for line, s in literals:
        m = _COLON.fullmatch(s)
        if m and m.group("domain").lower() in DOMAINS and s not in CODES:
            out.append(f"{rel}:{line}: {s!r} is not a permission code in rbac_seed.json")
        twin = s.replace(".", ":", 1)
        if twin != s and twin in CODES and (rel, s) not in allowed:
            out.append(f"{rel}:{line}: {s!r} is a dot-form twin of the seeded code {twin!r}")
    return out


def _unseeded(
    declared: list[_Declared],
    rel: str,
    *,
    known: Mapping[tuple[str, str], str] = _KNOWN_UNSEEDED,
) -> list[str]:
    return [
        f"{rel}:{line}: {name} = {s!r} is not a permission code in rbac_seed.json"
        for line, name, s in declared
        if s not in CODES and (rel, s) not in known
    ]


@cache
def _backend() -> dict[str, tuple[list[_Literal], list[_Declared]]]:
    scanned: dict[str, tuple[list[_Literal], list[_Declared]]] = {}
    for path in sorted(PKG.rglob("*.py")):
        tree = _parse(path.read_text("utf-8"), str(path))
        scanned[path.relative_to(PKG).as_posix()] = (_literals(tree), _declared(tree))
    return scanned


def test_permission_literals_every_backend_literal_is_a_seeded_code() -> None:
    scanned = _backend()
    seen = {s for literals, _ in scanned.values() for _line, s in literals}
    assert CODES <= seen  # not vacuous: the generated `Permission` enum itself was scanned
    problems = [v for rel, (literals, _) in scanned.items() for v in _violations(literals, rel)]
    assert problems == [], "\n".join(problems)


def test_permission_literals_every_permission_constant_is_a_seeded_code() -> None:
    scanned = _backend()
    found = {(rel, s) for rel, (_, declared) in scanned.items() for _line, _name, s in declared}
    assert ("rules/arming.py", "rules:arm_live") in found  # not vacuous
    problems = [v for rel, (_, declared) in scanned.items() for v in _unseeded(declared, rel)]
    assert problems == [], "\n".join(problems)


def test_permission_literals_no_audit_action_is_a_dot_twin_of_a_seeded_code() -> None:
    # Audit actions are a separate vocabulary but get no exemption (#2624 review): one named
    # `rules.arm_live` would make a drifted permission check read as an audit name. Rename it.
    twins = sorted(a for a in AUDIT_ACTIONS if a.replace(".", ":", 1) in CODES)
    assert twins == []


def test_permission_literals_allow_lists_have_no_stale_entries() -> None:
    scanned = _backend()
    literals = {(rel, s) for rel, (lits, _) in scanned.items() for _line, s in lits}
    declared = {(rel, s) for rel, (_, decl) in scanned.items() for _line, _name, s in decl}
    assert set(_ALLOWED_DOT_TWINS) <= literals
    assert set(_KNOWN_UNSEEDED) <= declared


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
    literals = _literals(_parse(f"X = {literal!r}\n", "x.py"))
    assert bool(_violations(literals, "x.py")) is flagged


@pytest.mark.parametrize(
    ("source", "flagged"),
    [
        ('X_PERMISSION = "retention.change"', True),  # a domain the seed does not have
        ('X_PERMISSION: Final = "rules.loosen_stop"', True),  # annotated, never seeded
        ('X_PERMISSIONS = ("orders:write", "retention.change")', True),
        ('X_PERMISSION = "rules:arm_live"', False),  # the seeded code
        ('X_PERMISSIONS = ("orders:write", Y_PERMISSION)', False),  # a name: checked at source
        ('class Reason:\n    MISSING_PERMISSION = "missing_permission"', False),  # not module level
    ],
)
def test_permission_literals_scanner_flags_unseeded_constants(source: str, flagged: bool) -> None:
    declared = _declared(_parse(f"{source}\n", "x.py"))
    assert bool(_unseeded(declared, "x.py")) is flagged


def test_permission_literals_exemptions_are_exact() -> None:
    literals = _literals(_parse('X = "rules.arm_live"\n', "x.py"))
    assert _violations(literals, "x.py", allowed={("x.py", "rules.arm_live"): "flag key"}) == []
    assert _violations(literals, "y.py", allowed={("x.py", "rules.arm_live"): "flag key"})
    declared = _declared(_parse('X_PERMISSION = "retention.change"\n', "x.py"))
    assert _unseeded(declared, "x.py", known={("x.py", "retention.change"): "known gap"}) == []
    assert _unseeded(declared, "y.py", known={("x.py", "retention.change"): "known gap"})
