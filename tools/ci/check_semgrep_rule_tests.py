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
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / ".semgrep"
TESTS_DIR = RULES_DIR / "tests"

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


def actual_lines(rule_yaml: Path, fixture: Path) -> set[int]:
    proc = subprocess.run(
        [
            "semgrep",
            "scan",
            "--config",
            str(rule_yaml),
            "--json",
            "--quiet",
            # Fixtures live under .semgrepignore'd paths (.semgrep/tests/, .semgrep-fixtures/) so the
            # product scan never reports their intentional violations; --include overrides that
            # ignore for this explicit, single-file scan (semgrep docs: --include wins over
            # .semgrepignore). Without it semgrep 1.99 (CI) silently scans nothing.
            "--include",
            fixture.name,
            str(fixture),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
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
        # Fixture language follows the rule (.py default; .ts/.tsx for TypeScript rules, E10-X02).
        fixture = next(
            (
                (TESTS_DIR / sub / f"{rule_id}{ext}")
                for sub, ext in (
                    (".", ".py"),
                    (".", ".ts"),
                    (".", ".tsx"),
                    # YAML fixtures live in /.semgrep-fixtures so `--config .semgrep` validates.
                    ("../../.semgrep-fixtures", ".yml"),
                )
                if (TESTS_DIR / sub / f"{rule_id}{ext}").exists()
            ),
            TESTS_DIR / f"{rule_id}.py",
        )
        if not fixture.exists():
            failures.append(f"{rule_id}: missing fixture {fixture}")
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
