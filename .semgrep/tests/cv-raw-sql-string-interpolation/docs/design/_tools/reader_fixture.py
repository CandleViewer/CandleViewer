"""Fixture for cv-raw-sql-string-interpolation: design tooling under docs/ is out of the rule's scope.

A docs tool's file-reading helper named `text(...)` must not be read as SQLAlchemy `text()` (#4129).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def tokens(name: str) -> str:
    return text(f"packages/ui/tokens/{name}.tokens.json")  # ok: cv-raw-sql-string-interpolation


def plan(section: str) -> str:
    return text("docs/plan/%s.md" % section)  # ok: cv-raw-sql-string-interpolation
