#!/usr/bin/env python3
"""E02-X02-B1: rule-test fixture checker for the `.semgrep/` pack.

`semgrep --test` (the documented verification command) hangs/produces no
output against a directory config on this toolchain (semgrep 1.178.0) and,
per-rule, misattributes which line a finding matched on Windows/Python 3.13
(see QA bug #1559, defects #1 and #3) -- a rule whose fixture never actually
gets exercised is worse than no rule at all (ticket #146, "Technical notes /
design"). This script re-implements the same `# ruleid: <id>` / `# ok: <id>`
fixture contract using `semgrep scan --json`, which reports accurate,
directly-checkable line numbers, and is what CI/`make security` should call
instead of `semgrep --test`.

Usage: python tools/ci/check_semgrep_rule_tests.py
Exits non-zero (and prints a diagnostic) if any fixture's expected lines
do not match what the rule actually fires on.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / ".semgrep"
TESTS_DIR = RULES_DIR / "tests"
# YAML fixtures live outside `.semgrep/` so `semgrep --config .semgrep` never loads one as a rule.
FIXTURES_DIR = REPO_ROOT / ".semgrep-fixtures"
# Where a fixture is looked up, in order: (directory, suffix). The language follows the rule
# (.py default; .ts/.tsx for TypeScript rules, E10-X02; .yml for workflow rules).
FIXTURE_LOCATIONS: tuple[tuple[Path, str], ...] = (
    (TESTS_DIR, ".py"),
    (TESTS_DIR, ".ts"),
    (TESTS_DIR, ".tsx"),
    (FIXTURES_DIR, ".yml"),
)

RULEID_RE = re.compile(r"(?:#|//)\s*ruleid:\s*([\w-]+)\s*$")
OK_RE = re.compile(r"(?:#|//)\s*ok:\s*([\w-]+)\s*$")


def expected_lines(fixture: Path, rule_id: str) -> tuple[set[int], set[int]]:
    """Return (must_fire, must_not_fire) line numbers for `rule_id`."""
    must_fire: set[int] = set()
    must_not_fire: set[int] = set()
    for lineno, line in enumerate(fixture.read_text(encoding="utf-8").splitlines(), start=1):
        m = RULEID_RE.search(line)
        if m and m.group(1) == rule_id:
            must_fire.add(lineno)
            continue
        m = OK_RE.search(line)
        if m and m.group(1) == rule_id:
            must_not_fire.add(lineno)
    return must_fire, must_not_fire


def _staged_relpath(fixture: Path) -> Path:
    """Path of the fixture inside the temp scan tree.

    Rules scope themselves with `paths.include`; .py/.ts fixtures keep their real repo-relative
    path (`.semgrep/tests/<name>`) because several rules include `.semgrep/tests/**` on purpose,
    while the YAML fixture is staged under `.github/workflows/` so workflow-targeted rules match it
    without naming the fixture file. The result is always relative and never climbs out of the
    temp tree: a fixture outside the repo raises `ValueError`.
    """
    if fixture.suffix in (".yml", ".yaml"):
        return Path(".github/workflows") / fixture.name
    return fixture.resolve().relative_to(REPO_ROOT)


def find_fixture(rule_id: str) -> Path:
    """First existing fixture for `rule_id` in `FIXTURE_LOCATIONS` order, else the default path."""
    for directory, suffix in FIXTURE_LOCATIONS:
        candidate = directory / f"{rule_id}{suffix}"
        if candidate.exists():
            return candidate
    return TESTS_DIR / f"{rule_id}.py"


def actual_lines(rule_yaml: Path, fixture: Path) -> set[int]:
    # Fixtures live under .semgrepignore'd paths (.semgrep/tests/, .semgrep-fixtures/) so the
    # product scan never reports their intentional violations. Semgrep's ignore handling varies by
    # version (1.99, CI's pin before #3549, ignored the file even with --include), so the checker
    # copies the fixture into a temp tree with no .semgrepignore and scans that copy; line
    # numbers are unchanged.
    # `--no-git-ignore`: the temp tree is not a git checkout, and a fixture name that happens to
    # match a global gitignore pattern must still be scanned.
    with tempfile.TemporaryDirectory(prefix="cv-semgrep-fixture-") as tmp:
        staged = Path(tmp) / _staged_relpath(fixture)
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture, staged)
        proc = subprocess.run(
            [
                "semgrep",
                "scan",
                "--config",
                str(rule_yaml.resolve()),
                "--json",
                "--quiet",
                "--no-git-ignore",
                str(staged),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            cwd=tmp,
        )
    if proc.returncode not in (0, 1):
        raise RuntimeError(
            f"semgrep scan failed (exit {proc.returncode}) on {fixture}:\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    data = json.loads(proc.stdout or "{}")
    return {r["start"]["line"] for r in data.get("results", [])}


def main() -> int:
    failures: list[str] = []
    rule_yamls = sorted(RULES_DIR.glob("cv-*.yml"))
    if not rule_yamls:
        print(f"no rule files found under {RULES_DIR}", file=sys.stderr)
        return 1
    for rule_yaml in rule_yamls:
        rule_id = rule_yaml.stem
        fixture = find_fixture(rule_id)
        if not fixture.exists():
            wanted = " or ".join(
                f"{d.relative_to(REPO_ROOT)}/{rule_id}{s}" for d, s in FIXTURE_LOCATIONS
            )
            failures.append(f"{rule_id}: missing fixture ({wanted})")
            continue
        must_fire, must_not_fire = expected_lines(fixture, rule_id)
        if not must_fire:
            failures.append(
                f"{rule_id}: fixture has no '# ruleid: {rule_id}' lines -- "
                "a rule that never fires on its own fixture is untested"
            )
            continue
        actual = actual_lines(rule_yaml, fixture)
        missed = must_fire - actual
        incorrect = actual & must_not_fire
        if missed:
            failures.append(f"{rule_id}: expected to fire but did not on lines {sorted(missed)}")
        if incorrect:
            failures.append(f"{rule_id}: fired on 'ok' lines {sorted(incorrect)} (false positive)")
        if not missed and not incorrect:
            print(f"OK   {rule_id}: {sorted(must_fire)} fire, {sorted(must_not_fire)} clean")

    if failures:
        print("\nsemgrep rule-test failures:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"\n{len(rule_yamls)} rule(s) passed their fixture tests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
