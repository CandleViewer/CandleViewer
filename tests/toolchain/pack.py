"""tests/toolchain/pack.py — E02-Q03 automated toolchain regression pack.

Guards CONSTITUTION.md §9's quality-gate table and the C-9.2/C-9.3/C-9.4
invariants it protects against decay: a contract exception added "just for
now", a coverage `omit` entry that never expires, a renamed task whose
documentation row rotted. E02-Q01 verified these once, by hand, when E02
closed; this module makes the verification mechanical and repeatable so it
survives every future PR.

Each `check_*` function below implements exactly one Definition-of-Done
assertion from the ticket and returns a list of human-actionable violation
strings (empty list == pass). Every message names the rule id, the file,
and — where the ticket's acceptance criteria call for it — the owning
ticket, so a red run always says what to do next (Technical notes / design).

Runner: `python -m tests.toolchain.pack` (wired to `pnpm test:toolchain`).
Stdlib + PyYAML only — no network access.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

QUALITY_GATES_PATH = "quality-gates.json"
FLAKY_TICKET_RE = re.compile(r"ticket:\s*([A-Z][A-Z0-9]*-\d+)")
FLAKY_DATE_RE = re.compile(r"quarantined:\s*(\d{4}-\d{2}-\d{2})")
PYTEST_FLAKY_RE = re.compile(r"@pytest\.mark\.flaky")
VITEST_FLAKY_RE = re.compile(r"\b(?:it|test|describe)\.flaky\s*\(")
QUARANTINE_WORKING_DAYS = 10

# Directory names pruned outright while walking the tree for `check_*` scans
# below. Bug #1576 (E02-Q03-B1): the previous `Path.rglob("**/*")` /
# `Path.glob("**/pyproject.toml")` calls descended into every one of these
# (node_modules across 8+ workspaces, .venv, .git) *before* the per-path
# `part in {...}` filter ran, which is what pushed the pack past its own
# 3-minute budget (measured 3m56s-4m11s). Pruning at directory-walk time
# (`os.walk`, `topdown=True`, mutate `dirnames` in place) instead of
# filtering matched paths after the fact is the fix — os.walk never
# descends into a pruned directory in the first place.
_PRUNED_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        ".git",
        ".turbo",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "coverage",
        ".next",
        ".cache",
    }
)


def _walk_files(repo_root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    """Yield every file under `repo_root` whose name ends with one of
    `suffixes`, pruning `_PRUNED_DIR_NAMES` at directory-walk time so the
    scan never descends into node_modules/.venv/.git/etc (see
    `_PRUNED_DIR_NAMES` docstring above -- this is the E02-Q03-B1 fix)."""
    import os

    matches: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in _PRUNED_DIR_NAMES]
        for filename in filenames:
            if filename.endswith(suffixes):
                matches.append(Path(dirpath) / filename)
    return matches


@dataclass(frozen=True)
class Violation:
    """One actionable failure: which rule, which file, what to do."""

    rule: str
    message: str

    def __str__(self) -> str:  # pragma: no cover -- trivial formatting
        return f"[{self.rule}] {self.message}"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _import_check_reconciliation() -> Any:
    """Import scripts/check_required_check_reconciliation.py (GOV-005) as a
    module. It already implements assertion 1's exact logic (every §9 gate
    enforced through `.github/branch-protection.json` or listed in its
    `pending_checks`); this pack reuses it rather than re-implementing a second
    parser of the same source-of-truth table (C-16.5 duplication ban)."""
    import importlib.util

    module_path = REPO_ROOT / "scripts" / "check_required_check_reconciliation.py"
    spec = importlib.util.spec_from_file_location(
        "check_required_check_reconciliation", module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_gate_registration(repo_root: Path = REPO_ROOT) -> list[Violation]:
    """Assertion 1 (ticket Scope item 1): every gate name in CONSTITUTION.md
    §9's table is either implemented locally (a job exists) or explicitly
    registered as CI-only via `pending_checks`, with the reason and the item
    that closes it -- no gate silently missing."""
    recon = _import_check_reconciliation()
    try:
        errors, _pending = recon.reconcile_repo(
            str(repo_root / ".github" / "branch-protection.json"),
            str(repo_root / "CONSTITUTION.md"),
            str(repo_root / ".github" / "workflows" / "*.yml"),
        )
    except recon.ReconciliationError as exc:
        return [Violation("C-9.1", f"gate registration check could not run: {exc}")]
    return [Violation("C-9.1", e) for e in errors]


def check_agents_commands(repo_root: Path = REPO_ROOT) -> list[Violation]:
    """Assertion 2 (ticket Scope item 2): every documented task in
    `AGENTS.md` §4 resolves in the task graph. Reuses
    `scripts/check-agents-commands.mjs` (a Node ESM script; imported over
    subprocess so a broken command still reports which one, not just a
    non-zero exit)."""
    import subprocess

    script = repo_root / "scripts" / "check-agents-commands.mjs"
    if not script.exists():
        return [Violation("E02-T01", f"missing {script} — cannot verify AGENTS.md §4 commands")]
    result = subprocess.run(
        ["node", str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return [Violation("AGENTS.md §4", detail or "check-agents-commands.mjs failed")]
    return []


# §9 rows #3/#4/#5: the minimum floors named in the Constitution table itself
# (independent of whatever quality-gates.json currently declares -- this is
# the "assertion, not only a diff" the ticket calls for; quality_gates.py's
# diff-vs-main guard catches a same-PR lowering, this catches a floor that
# has quietly drifted below the Constitution's own number over many PRs).
CONSTITUTION_COVERAGE_FLOORS: dict[str, dict[str, float]] = {
    "services/api": {"lines": 85.0, "branches": 75.0},
    "packages/chart-engine": {"lines": 85.0, "branches": 75.0},
    "apps/web": {"lines": 80.0, "branches": 70.0},
    "packages/ui": {"lines": 80.0, "branches": 70.0},
}


def check_coverage_floors(repo_root: Path = REPO_ROOT) -> list[Violation]:
    """Assertion 3 (ticket Scope item 3): coverage thresholds in
    `quality-gates.json` equal or exceed the §9 values for every package --
    run as a direct assertion against the Constitution's own numbers, not
    only as a diff against `main` (that diff is `tools/ci/quality_gates.py`,
    reused by #5 of `pnpm verify`; this is the independent floor check)."""
    path = repo_root / QUALITY_GATES_PATH
    if not path.exists():
        return [Violation("C-9.4", f"{QUALITY_GATES_PATH} not found")]
    data = json.loads(_read_text(path))
    coverage = data.get("coverage", {})
    violations: list[Violation] = []
    for package, floors in CONSTITUTION_COVERAGE_FLOORS.items():
        entry = coverage.get(package)
        if entry is None:
            violations.append(
                Violation(
                    "C-9.4",
                    f"{QUALITY_GATES_PATH} has no coverage entry for '{package}' "
                    "(CONSTITUTION.md §9 requires one)",
                )
            )
            continue
        for metric, floor in floors.items():
            measured = entry.get(metric)
            if measured is None or measured < floor:
                violations.append(
                    Violation(
                        "C-9.4",
                        f"{package}.{metric} = {measured!r} is below the CONSTITUTION.md §9 "
                        f"floor of {floor} — naming the package: {package}",
                    )
                )
    return violations


ADR_REF_RE = re.compile(r"ADR-\d{4}")
IMPORTLINTER_CONTRACT_RE = re.compile(r"^\[importlinter:contract:([^\]]+)\]", re.MULTILINE)
IGNORE_IMPORTS_RE = re.compile(r"^\s*ignore_imports\s*=", re.MULTILINE)


def check_architecture_contracts(repo_root: Path = REPO_ROOT) -> list[Violation]:
    """Assertion 5 (ticket Scope item 5): every `import-linter`/
    `dependency-cruiser` contract from E02-T06 is present and has zero
    exceptions; an added exception fails the pack unless accompanied by an
    ADR reference."""
    violations: list[Violation] = []

    importlinter_path = repo_root / "services" / "api" / ".importlinter"
    if not importlinter_path.exists():
        violations.append(Violation("E02-T06", f"{importlinter_path} not found"))
    else:
        text = _read_text(importlinter_path)
        contracts = IMPORTLINTER_CONTRACT_RE.findall(text)
        if not contracts:
            violations.append(Violation("E02-T06", f"{importlinter_path} declares zero contracts"))
        for m in IGNORE_IMPORTS_RE.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            window = text[max(0, m.start() - 400) : m.start()]
            if not ADR_REF_RE.search(window):
                violations.append(
                    Violation(
                        "E02-T06",
                        f".importlinter:{line_no} has an `ignore_imports` exception with no "
                        "preceding ADR reference",
                    )
                )

    depcruiser_path = repo_root / ".dependency-cruiser.js"
    if not depcruiser_path.exists():
        violations.append(Violation("E02-T06", f"{depcruiser_path} not found"))
    else:
        text = _read_text(depcruiser_path)
        rule_count = len(re.findall(r"\bname:\s*[\"'`]", text))
        if rule_count == 0:
            violations.append(
                Violation("E02-T06", f"{depcruiser_path} declares zero forbidden rules")
            )
        for m in re.finditer(r"\bignoreImports?\s*:", text, re.IGNORECASE):
            line_no = text.count("\n", 0, m.start()) + 1
            window = text[max(0, m.start() - 400) : m.start()]
            if not ADR_REF_RE.search(window):
                violations.append(
                    Violation(
                        "E02-T06",
                        f".dependency-cruiser.js:{line_no} has an ignore-imports exception "
                        "with no preceding ADR reference",
                    )
                )
    return violations


def _working_days_ago(start: date, end: date) -> int:
    """Count working days (Mon-Fri) strictly between start (exclusive) and
    end (inclusive) -- a simple business-day counter, no holiday calendar
    (matches C-9.3's own wording, which does not name one)."""
    if end <= start:
        return 0
    days = 0
    cursor = start
    while cursor < end:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


def check_flaky_quarantine_age(repo_root: Path = REPO_ROOT) -> list[Violation]:
    """Assertion 6 (ticket Scope item 6): every `@flaky`-marked test has a
    ticket reference and a quarantine start date within 10 working days
    (C-9.3). Reuses the scan patterns from
    `tools/ci/flaky_quarantine_report.py` (unreferenced-marker detection)
    and adds the working-day expiry check that script does not perform."""
    violations: list[Violation] = []
    today = datetime.now(timezone.utc).date()

    # scripts/tests/test_flaky_quarantine_report.py and this pack's own
    # tests/toolchain/test_pack.py exercise the marker scanner with literal
    # `@pytest.mark.flaky` strings as fixtures; those are not real
    # quarantined tests and must not be double-counted here.
    _SELF_TEST_FIXTURES = {
        "scripts/tests/test_flaky_quarantine_report.py",
        "tests/toolchain/test_pack.py",
    }

    def _scan(paths: list[Path], marker_re: re.Pattern[str]) -> None:
        for path in paths:
            if any(part in {".venv", "node_modules", "__pycache__", "dist"} for part in path.parts):
                continue
            if path.relative_to(repo_root).as_posix() in _SELF_TEST_FIXTURES:
                continue
            lines = _read_text(path).splitlines()
            for i, line in enumerate(lines):
                if not marker_re.search(line):
                    continue
                probe = "\n".join(lines[max(0, i - 1) : i + 1])
                rel = path.relative_to(repo_root).as_posix()
                ticket_match = FLAKY_TICKET_RE.search(probe)
                if not ticket_match:
                    violations.append(
                        Violation(
                            "C-9.3",
                            f"{rel}:{i + 1} `@flaky`/`.flaky(...)` marker has no "
                            "`ticket: <KEY>` reference",
                        )
                    )
                date_match = FLAKY_DATE_RE.search(probe)
                if not date_match:
                    violations.append(
                        Violation(
                            "C-9.3",
                            f"{rel}:{i + 1} `@flaky`/`.flaky(...)` marker has no "
                            "`quarantined: YYYY-MM-DD` start date",
                        )
                    )
                    continue
                start = date.fromisoformat(date_match.group(1))
                age = _working_days_ago(start, today)
                if age > QUARANTINE_WORKING_DAYS:
                    ticket = ticket_match.group(1) if ticket_match else "<missing ticket>"
                    violations.append(
                        Violation(
                            "C-9.3",
                            f"{rel}:{i + 1} quarantined since {start.isoformat()} "
                            f"({age} working days ago, > {QUARANTINE_WORKING_DAYS}) "
                            f"owning ticket {ticket}",
                        )
                    )

    _scan(
        [p for p in _walk_files(repo_root, (".py",)) if p.name.startswith("test_")],
        PYTEST_FLAKY_RE,
    )
    _scan(
        _walk_files(repo_root, (".test.ts", ".test.tsx", ".test.mjs")),
        VITEST_FLAKY_RE,
    )
    return violations


TICKET_REF_RE = re.compile(r"\b[A-Z]{1,4}\d{2}(?:-[A-Z]\d{2,3})?\b")
DATED_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
EXPIRES_RE = re.compile(r"expires?:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def _omit_block_comment(text: str) -> tuple[str, int] | None:
    """Return (comment_text, omit_line_index) for the first `omit = [` in a
    pyproject.toml-style file, where comment_text is every contiguous `#`
    line immediately preceding it."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s*omit\s*=\s*\[", line):
            comment_lines: list[str] = []
            j = i - 1
            while j >= 0 and lines[j].strip().startswith("#"):
                comment_lines.append(lines[j])
                j -= 1
            comment_lines.reverse()
            return "\n".join(comment_lines), i + 1
    return None


def check_coverage_omit_provenance(repo_root: Path = REPO_ROOT) -> list[Violation]:
    """Assertion 4 (ticket Scope item 4): every coverage `omit`/exclusion
    list carries a dated ticket reference, and none is past a stated
    expiry. Guards against the decay the ticket's Context names: "a
    coverage `omit` entry is added and never removed"."""
    violations: list[Violation] = []
    for pyproject in _walk_files(repo_root, ("pyproject.toml",)):
        text = _read_text(pyproject)
        block = _omit_block_comment(text)
        if block is None:
            continue  # no `omit = [` list in this file — nothing to check
        comment, line_no = block
        rel = pyproject.relative_to(repo_root).as_posix()
        if not TICKET_REF_RE.search(comment):
            violations.append(
                Violation(
                    "C-9.4",
                    f"{rel}:{line_no} coverage `omit` list has no ticket reference in its "
                    "preceding comment",
                )
            )
        if not DATED_RE.search(comment):
            violations.append(
                Violation(
                    "C-9.4",
                    f"{rel}:{line_no} coverage `omit` list has no dated reference in its "
                    "preceding comment",
                )
            )
        expiry_match = EXPIRES_RE.search(comment)
        if expiry_match:
            expiry = date.fromisoformat(expiry_match.group(1))
            if expiry < datetime.now(timezone.utc).date():
                violations.append(
                    Violation(
                        "C-9.4",
                        f"{rel}:{line_no} coverage `omit` list expired on {expiry.isoformat()} "
                        "and must be re-justified or removed",
                    )
                )
    return violations


def _import_lint_compose() -> Any:
    import importlib.util

    module_path = REPO_ROOT / "infra" / "scripts" / "lint_compose.py"
    spec = importlib.util.spec_from_file_location("lint_compose", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPOSE_FILES = ("infra/compose/docker-compose.yml",)
# Only the base file: docker-compose.dev.yml/.vps.yml are override layers
# merged on top of it (`docker compose -f ... -f ...`), so a service they
# only partially redeclare legitimately inherits healthcheck/image/ports
# from the base -- linting them standalone would flag correct compose-merge
# usage as a violation.


def check_compose_invariants(repo_root: Path = REPO_ROOT) -> list[Violation]:
    """Assertion 7 (ticket Scope item 7): compose invariants -- all
    published ports bound to loopback, all images digest-pinned, all
    services healthchecked. Reuses `infra/scripts/lint_compose.py`
    (E02-T08) rather than re-implementing the YAML rules (C-16.5); static
    file assertions only, never starts Docker (ticket Performance notes)."""
    lint_compose = _import_lint_compose()
    violations: list[Violation] = []
    for rel_path in COMPOSE_FILES:
        path = repo_root / rel_path
        if not path.exists():
            violations.append(Violation("E02-T08", f"{rel_path} not found"))
            continue
        try:
            errors = lint_compose.lint(path)
        except lint_compose.ComposeLintError as exc:  # pragma: no cover -- defensive
            violations.append(Violation("E02-T08", f"{rel_path}: {exc}"))
            continue
        violations.extend(Violation("E02-T08", f"{rel_path}: {e}") for e in errors)
    return violations


ALL_CHECKS: tuple[tuple[str, Any], ...] = (
    ("gate-registration (C-9.1)", check_gate_registration),
    ("agents-commands (AGENTS.md §4)", check_agents_commands),
    ("coverage-floors (C-9.4)", check_coverage_floors),
    ("coverage-omit-provenance (C-9.4)", check_coverage_omit_provenance),
    ("architecture-contracts (E02-T06)", check_architecture_contracts),
    ("flaky-quarantine-age (C-9.3)", check_flaky_quarantine_age),
    ("compose-invariants (E02-T08)", check_compose_invariants),
)


def run_all(repo_root: Path = REPO_ROOT) -> dict[str, list[Violation]]:
    return {name: fn(repo_root) for name, fn in ALL_CHECKS}


def write_report(results: dict[str, list[Violation]], repo_root: Path = REPO_ROOT) -> Path:
    """Emits `reports/toolchain-regression.json` (ticket Observability):
    gate status, threshold values and exception counts."""
    out_path = repo_root / "reports" / "toolchain-regression.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gates": {
            name: {
                "status": "pass" if not violations else "fail",
                "violation_count": len(violations),
                "violations": [str(v) for v in violations],
            }
            for name, violations in results.items()
        },
        "overall": "pass" if all(not v for v in results.values()) else "fail",
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    results = run_all(repo_root)
    report_path = write_report(results, repo_root)

    exit_code = 0
    for name, violations in results.items():
        if violations:
            exit_code = 1
            print(f"toolchain-regression: FAIL [{name}]", file=sys.stderr)
            for v in violations:
                print(f"  - {v}", file=sys.stderr)
        else:
            print(f"toolchain-regression: PASS [{name}]")
    print(f"toolchain-regression: report written to {report_path}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
