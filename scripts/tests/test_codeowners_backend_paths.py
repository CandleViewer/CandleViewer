"""#2706: backend CODEOWNERS rules name the real package root, `services/api/candleviewer/`.

The rules for the backend modules used to name the planned layout `services/api/<module>/`, which
matches no file. Their `# future:` markers hid that from GOV-001, so every module, the security
ones included, fell through to the `/services/api/` catch-all (backend only). These tests run
against this repository's own CODEOWNERS and tracked files.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_codeowners_coverage as gov

PACKAGE = "services/api/candleviewer/"
SECURITY = "@CandleViewer/security"
#: Modules whose code needs the security owner (C-10.2). `exchange/base/` is the adapter
#: interface, owned by architecture and backend; `exchange/` and `exchange/bybit/` are security's.
SECURITY_MODULES = (
    "secrets",
    "auth",
    "audit",
    "admin",
    "exchange",
    "oms",
    "risk",
    "rules",
    "accounts",
)


def _rules_and_files() -> tuple[list[gov.Rule], list[str]]:
    rules, _declared = gov.parse_codeowners(str(REPO_ROOT))
    return rules, gov.git_tracked_files(str(REPO_ROOT))


def _winning_owners() -> dict[str, tuple[str, ...]]:
    """Each tracked path's winning owners, as GOV-001 resolves them."""
    _violations, results = gov.check(str(REPO_ROOT))
    return {m.path: m.rule.owners if m.rule else () for m in results}


def _placeholder_module(pattern: str) -> str | None:
    """`x` for a `/services/api/x/` rule outside the package and the tests, else None."""
    if not (pattern.startswith("/services/api/") and pattern.endswith("/")):
        return None
    if pattern.startswith(("/" + PACKAGE, "/services/api/tests/")):
        return None
    return pattern.removeprefix("/services/api/").rstrip("/")


def test_codeowners_no_backend_rule_names_a_placeholder_for_a_real_module() -> None:
    rules, files = _rules_and_files()
    stale = []
    for rule in rules:
        module = _placeholder_module(rule.pattern)
        if module and any(path.startswith(f"{PACKAGE}{module}/") for path in files):
            stale.append(
                f"line {rule.line_no}: {rule.pattern} (module is {PACKAGE}{module}/)"
            )
    assert stale == [], "\n".join(stale)


def test_codeowners_security_modules_resolve_to_the_security_owner() -> None:
    owners = _winning_owners()
    prefixes = tuple(f"{PACKAGE}{module}/" for module in SECURITY_MODULES)
    in_scope = [
        path
        for path in owners
        if path.startswith(prefixes) and not path.startswith(f"{PACKAGE}exchange/base/")
    ]
    # Not vacuous: every module still has files at its real path (a rename fails here first).
    empty = [
        m
        for m in SECURITY_MODULES
        if not any(p.startswith(f"{PACKAGE}{m}/") for p in in_scope)
    ]
    assert empty == [], f"no tracked files under {PACKAGE} for: {empty}"
    unowned = [
        f"{path} -> {' '.join(owners[path]) or '(no rule)'}"
        for path in in_scope
        if SECURITY not in owners[path]
    ]
    assert unowned == [], "\n".join(unowned[:20])
