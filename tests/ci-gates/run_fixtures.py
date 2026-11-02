#!/usr/bin/env python3
"""E03-Q01: fixture runner for the CI-gate black-box test plan (`PLAN.md`).

Drives the small set of *new* scripted fixtures this ticket adds
(`tests/ci-gates/fixtures/*`) against the real gate script each one targets,
and asserts the expected PASS/FAIL outcome — printing "expected FAIL,
observed FAIL" (or a mismatch) so a reader can never misread a red run as a
problem (ticket "Technical notes").

Existing fixtures owned by other tickets (coverage, contract, migrations,
gen-freshness, security, bypass-register) are proven by their own upstream
pytest suites under `scripts/tests/` / `services/api/tests/` — this runner
does not duplicate them; it lists them for the execution record only.

Usage:
    python tests/ci-gates/run_fixtures.py [--case E03-GT-16]

Exit codes: 0 all expectations matched; 1 an expectation mismatched
(a case that should have failed did not, or vice versa); 2 internal error.
Stdlib only.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load(module_name: str) -> ModuleType:
    """Load a fixture module by file path.

    `tests/ci-gates/` contains a hyphen, so it is not an importable Python
    package name — every fixture module is loaded directly from its file
    path instead of via a dotted import.
    """
    path = FIXTURES_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"ci_gate_fixture_{module_name}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class FixtureCase:
    case_id: str
    description: str
    expect_pass: bool
    run: Callable[[], tuple[bool, str]]


def _case_protection_drift() -> tuple[bool, str]:
    result: tuple[bool, str] = _load("protection").build_drift_fixture()
    return result


def _case_protection_clean() -> tuple[bool, str]:
    result: tuple[bool, str] = _load("protection").build_clean_fixture()
    return result


def _case_a11y_violation() -> tuple[bool, str]:
    result: tuple[bool, str] = _load("a11y").build_violation_fixture()
    return result


def _case_a11y_clean() -> tuple[bool, str]:
    result: tuple[bool, str] = _load("a11y").build_clean_fixture()
    return result


def _case_secret_planted() -> tuple[bool, str]:
    result: tuple[bool, str] = _load("secrets").build_planted_secret_fixture()
    return result


def _case_secret_clean() -> tuple[bool, str]:
    result: tuple[bool, str] = _load("secrets").build_clean_fixture()
    return result


def _case_engine_bench(fn: str) -> Callable[[], tuple[bool, str]]:
    def run() -> tuple[bool, str]:
        result: tuple[bool, str] = getattr(_load("engine_bench"), fn)()
        return result

    return run


CASES: list[FixtureCase] = [
    FixtureCase(
        "E03-GT-18a",
        "engine-bench reported not applicable on a non-engine diff",
        True,
        _case_engine_bench("build_not_applicable_fixture"),
    ),
    FixtureCase(
        "E03-GT-18b",
        "CI-GATE-001: applicable engine-bench lane failed",
        False,
        _case_engine_bench("build_applicable_failure_fixture"),
    ),
    FixtureCase(
        "E03-GT-19a",
        "CI-BEN-004: no GPU runner registered, fallback, no alert",
        True,
        _case_engine_bench("build_no_runner_fixture"),
    ),
    FixtureCase(
        "E03-GT-19b",
        "CI-BEN-003: GPU runner offline, fallback and alert",
        False,
        _case_engine_bench("build_runner_offline_fixture"),
    ),
    FixtureCase(
        "E03-GT-16a",
        "branch-protection reconciliation, clean",
        True,
        _case_protection_clean,
    ),
    FixtureCase(
        "E03-GT-16b",
        "CI-PROT-002: required check renamed, dropped from protection",
        False,
        _case_protection_drift,
    ),
    FixtureCase(
        "E03-GT-07a", "axe-core scan, zero serious/critical", True, _case_a11y_clean
    ),
    FixtureCase(
        "E03-GT-07b",
        "CI-A11Y-001: planted serious violation",
        False,
        _case_a11y_violation,
    ),
    FixtureCase("E03-GT-09a", "secrets scan, clean diff", True, _case_secret_clean),
    FixtureCase(
        "E03-GT-09b",
        "CI-SEC-001: synthetic dummy-prefixed secret (SR-145)",
        False,
        _case_secret_planted,
    ),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default=None, help="Run only this case id")
    args = parser.parse_args(argv)

    cases = [c for c in CASES if args.case is None or c.case_id == args.case]
    if not cases:
        print(f"no such case: {args.case}", file=sys.stderr)
        return 2

    mismatches: list[str] = []
    for case in cases:
        observed_pass, detail = case.run()
        expected_word = "PASS" if case.expect_pass else "FAIL"
        observed_word = "PASS" if observed_pass else "FAIL"
        status = "OK" if observed_pass == case.expect_pass else "MISMATCH"
        print(
            f"[{status}] {case.case_id} {case.description}: expected {expected_word}, "
            f"observed {observed_word} -- {detail}"
        )
        if observed_pass != case.expect_pass:
            mismatches.append(case.case_id)

    if mismatches:
        print(
            f"\n{len(mismatches)} case(s) did not match expectation: {mismatches}",
            file=sys.stderr,
        )
        return 1
    print(f"\nall {len(cases)} case(s) matched expectation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
